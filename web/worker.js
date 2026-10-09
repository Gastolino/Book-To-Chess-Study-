// Runs Python (Pyodide) off the page's main thread, so that the page stays
// responsive while a book is processed. The page sends {type, ...} messages;
// the worker answers with progress lines and results.
let py = null;
let driver = null;

function say(text) {
  postMessage({ type: "progress", text: String(text) });
}

// numpy and OpenCV (for reading the board pictures and the figurines' shapes)
// come from Pyodide itself. A book opened from its stored reading needs neither
// to show, so they load after the worker is ready; reading a book, a
// correction and the state that applies corrections wait for them (boardsP).
// loadPackage reports a package it cannot fetch on the console and goes on,
// so the packages loaded are checked afterwards (without them a book is read
// as before, and its diagrams stay unread).
let boardsP = Promise.resolve(true);
async function loadBoards(cfg) {
  if (!cfg.packages || !cfg.packages.length) return true;
  try { await py.loadPackage(cfg.packages, { messageCallback: () => {}, errorCallback: () => {} }); }
  catch (err) { /* checked below */ }
  const ok = cfg.packages.every((name) => name in py.loadedPackages);
  postMessage({ type: "boards", ok });
  return ok;
}

async function init(cfg) {
  importScripts(cfg.indexURL + "pyodide.js");
  say("Starting Python in the browser");
  py = await loadPyodide({ indexURL: cfg.indexURL });
  say("Loading the PDF and chess libraries");
  await py.loadPackage(cfg.wheels);
  const zip = await (await fetch(cfg.appZip)).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/app" });
  py.FS.mkdirTree("/books");
  py.runPython("import sys; sys.path.insert(0, '/app/web')");
  driver = py.pyimport("driver");
  postMessage({ type: "ready", version: driver.VERSION });
  boardsP = loadBoards(cfg);
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
      await boardsP;
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
      // corrections the reading may lack are applied before the book shows: with the state
      // that applies them, which needs the board libraries
      if (msg.corrections) await boardsP;
      const id = ++job;
      const events = JSON.parse(driver.restore(path, "/books/reading.bin", msg.selection || null,
                                               msg.corrections || null));
      py.FS.unlink("/books/reading.bin");
      for (const ev of events) postMessage(ev);
      if (events.length && events[0].type === "stale") return;
      // the book shows; the state that applies corrections loads once the libraries are there
      await boardsP;
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
      await boardsP;
      // a correction made in the open chapter: applied to the book at once
      const out = driver.correct(msg.corrections, msg.chapter);
      postMessage({ type: "patch", chapter: msg.chapter, result: JSON.parse(out) });
    } else if (msg.type === "correct-more") {
      await boardsP;
      // a piece-symbol correction reaching the other chapters, a few at a time;
      // the patch is for the chapter the worker opened last
      const result = JSON.parse(driver.correct_more(JSON.stringify(msg.chapters), msg.chapter || ""));
      postMessage({ type: "patch", chapter: result.chapter || msg.chapter, more: true, result });
    } else if (msg.type === "words") {
      // the words of the page around the reader's tap, for the selection to snap to
      const words = JSON.parse(driver.words(msg.page, msg.rect[0], msg.rect[1], msg.rect[2], msg.rect[3], msg.near || 0));
      postMessage({ type: "words", id: msg.id, page: msg.page, words });
    } else if (msg.type === "region") {
      // a section of a page the program missed, read with the book's decoder (which needs the
      // state that applies corrections, and so the board libraries)
      await boardsP;
      const result = JSON.parse(driver.read_region(msg.page, JSON.stringify(msg.rect), msg.at, msg.side || "after",
                                                   msg.other || null));
      postMessage({ type: "region", id: msg.id, result });
    } else if (msg.type === "suggest") {
      // what follows a move the reader joined to its line: the next printed move the line does
      // not hold, read with the state that applies corrections
      await boardsP;
      const result = JSON.parse(driver.suggest(msg.after, msg.chapter || "", JSON.stringify(msg.before || []),
                                               JSON.stringify(msg.skip || [])));
      postMessage({ type: "suggest", id: msg.id, result });
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
    postMessage({ type: "error", during: msg.type, chapter: msg.chapter || "", id: msg.id,
                  text: String(err && err.message ? err.message : err) });
  }
};
