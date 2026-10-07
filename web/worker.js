// Runs Python (Pyodide) off the page's main thread, so that the page stays
// responsive while a book is processed. The page sends {type, ...} messages;
// the worker answers with progress lines and results.
let py = null;
let driver = null;

function say(text) {
  postMessage({ type: "progress", text: String(text) });
}

async function init(cfg) {
  importScripts(cfg.indexURL + "pyodide.js");
  say("Starting Python in the browser");
  py = await loadPyodide({ indexURL: cfg.indexURL });
  say("Loading the PDF and chess libraries");
  // numpy and OpenCV (for reading the board pictures) come from Pyodide itself
  // (without them the book is read as before, and its diagrams stay unread).
  // loadPackage reports a package it cannot fetch on the console and goes on,
  // so the packages loaded are checked afterwards.
  let boards = true;
  if (cfg.packages && cfg.packages.length) {
    try { await py.loadPackage(cfg.packages, { messageCallback: () => {}, errorCallback: () => {} }); }
    catch (err) { /* checked below */ }
    boards = cfg.packages.every((name) => name in py.loadedPackages);
  }
  await py.loadPackage(cfg.wheels);
  const zip = await (await fetch(cfg.appZip)).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/app" });
  py.FS.mkdirTree("/books");
  py.runPython("import sys; sys.path.insert(0, '/app/web')");
  driver = py.pyimport("driver");
  postMessage({ type: "ready", boards, version: driver.VERSION });
}

// Bytes made by Python, as a JavaScript array (the Python object is freed).
function bytesOf(proxy) {
  const out = proxy.toJs();
  proxy.destroy();
  return out;
}
// gzip on the way to the library and back, with the browser's own streams.
async function gzip(bytes, how) {
  const stream = new Blob([bytes]).stream().pipeThrough(
    how === "decompress" ? new DecompressionStream("gzip") : new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

// The book is read in small steps (driver.step). Between two steps the
// worker lets the page's messages in (a chapter to open, a correction), so
// that the reader can read the book while it is processed. Only one book is
// read at a time: a new "process" message ends the steps of the one before.
let job = 0, pace = 0;
const pause = () => new Promise((resolve) => setTimeout(resolve, pace));
async function run(id, t0) {
  for (;;) {
    await pause();
    if (id !== job) return;
    let out;
    try { out = JSON.parse(driver.step()); }
    catch (err) {
      postMessage({ type: "error", during: "process", text: String(err && err.message ? err.message : err) });
      return;
    }
    for (const ev of out.events) {
      if (ev.type === "done") ev.seconds = (performance.now() - t0) / 1000;
      if (ev.type === "checkpoint") {
        if (id !== job) return;
        // a finished part of the reading, gzipped, for the library (driver.checkpoint)
        try {
          const bytes = await gzip(bytesOf(driver.checkpoint()));
          postMessage({ type: "partial", bytes, parts: ev.parts, version: driver.VERSION }, [bytes.buffer]);
        } catch (err) { /* the reading goes on; only a reading cut short misses it */ }
        continue;
      }
      postMessage(ev);
    }
    if (out.done) return;
  }
}

onmessage = async (event) => {
  const msg = event.data;
  try {
    if (msg.type === "init") {
      pace = msg.cfg.pace || 0;
      await init(msg.cfg);
    } else if (msg.type === "process") {
      const t0 = performance.now();
      const path = "/books/" + msg.name;
      py.FS.writeFile(path, new Uint8Array(msg.bytes));
      const id = ++job;
      // the parts of an earlier reading cut short (the library keeps them): not read again
      let partial = null;
      if (msg.partial) {
        try {
          partial = "/books/partial.bin";
          py.FS.writeFile(partial, await gzip(msg.partial, "decompress"));
        } catch (err) { partial = null; }
      }
      const notes = JSON.parse(driver.start(path, msg.selection || null, msg.corrections || null, partial));
      if (partial) py.FS.unlink(partial);
      for (const ev of notes) postMessage(ev);
      await run(id, t0);
    } else if (msg.type === "restore") {
      // a book of the library, opened from its stored reading (gzip) instead of read;
      // a reading the driver refuses ("stale") makes the page read the book instead
      const t0 = performance.now();
      const path = "/books/" + msg.name;
      py.FS.writeFile(path, new Uint8Array(msg.bytes));
      py.FS.writeFile("/books/reading.bin", await gzip(msg.reading, "decompress"));
      const id = ++job;
      const events = JSON.parse(driver.restore(path, "/books/reading.bin", msg.selection || null,
                                               msg.corrections || null));
      py.FS.unlink("/books/reading.bin");
      for (const ev of events) postMessage(ev);
      if (events.length && events[0].type === "stale") return;
      await run(id, t0);
    } else if (msg.type === "save") {
      // the finished reading, gzipped, for the library
      const t0 = performance.now();
      const raw = bytesOf(driver.save_reading());
      const bytes = await gzip(raw);
      postMessage({ type: "reading", bytes, size: raw.length, version: driver.reading_version(),
                    seconds: (performance.now() - t0) / 1000 }, [bytes.buffer]);
    } else if (msg.type === "cover") {
      const bytes = bytesOf(driver.cover("/books/" + msg.name));
      postMessage({ type: "cover", bytes }, [bytes.buffer]);
    } else if (msg.type === "chapter") {
      // prepare: the chapter the reader is about to turn to, built without opening it
      const html = driver.chapter(msg.name, msg.prepare ? () => {} : say, !!msg.small, !!msg.prepare);
      postMessage({ type: "page", name: msg.name, hash: msg.hash || "", html, prepared: !!msg.prepare,
                    quiet: !!msg.quiet });
    } else if (msg.type === "draw") {
      // the pictures of a window of pages: one header line, then the JPEGs
      const t0 = performance.now();
      const all = bytesOf(driver.draw(JSON.stringify(msg.pages), msg.size || "large"));
      const nl = all.indexOf(10);
      const head = JSON.parse(new TextDecoder().decode(all.subarray(0, nl)));
      const pages = {};
      let at = nl + 1;
      for (const [p, n] of head.pages) { pages[p] = all.slice(at, at + n); at += n; }
      postMessage({ type: "drawn", pages, size: head.size, window: msg.window, gen: msg.gen,
                    seconds: (performance.now() - t0) / 1000 }, Object.values(pages).map((b) => b.buffer));
    } else if (msg.type === "correct") {
      // a correction made in the open chapter: applied to the book at once
      const out = driver.correct(msg.corrections, msg.chapter);
      postMessage({ type: "patch", chapter: msg.chapter, result: JSON.parse(out) });
    } else if (msg.type === "correct-more") {
      // a piece-symbol correction reaching the other chapters, a few at a time;
      // the patch is for the chapter the worker opened last
      const result = JSON.parse(driver.correct_more(JSON.stringify(msg.chapters), msg.chapter || ""));
      postMessage({ type: "patch", chapter: result.chapter || msg.chapter, more: true, result });
    } else if (msg.type === "index") {
      postMessage({ type: "page", name: "index.html", hash: msg.hash || "", html: driver.index() });
    } else if (msg.type === "timeline") {
      postMessage({ type: "timeline", timeline: JSON.parse(driver.timeline()) });
    } else if (msg.type === "memory") {
      // what the worker holds (for measurements): the wasm heap never shrinks,
      // so its size is the most memory Python has needed so far
      const mem = JSON.parse(driver.memory());
      mem.heap = py._module.HEAP8.length;
      mem.jsHeap = self.performance && performance.memory ? performance.memory.usedJSHeapSize : null;
      postMessage({ type: "memory", memory: mem });
    }
  } catch (err) {
    // the type of the failed request lets the page say what did not happen
    postMessage({ type: "error", during: msg.type, chapter: msg.chapter || "",
                  text: String(err && err.message ? err.message : err) });
  }
};
