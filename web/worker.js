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
  postMessage({ type: "ready", boards });
}

onmessage = async (event) => {
  const msg = event.data;
  try {
    if (msg.type === "init") {
      await init(msg.cfg);
    } else if (msg.type === "process") {
      const path = "/books/" + msg.name;
      py.FS.writeFile(path, new Uint8Array(msg.bytes));
      const t0 = performance.now();
      const html = driver.process(path, say, msg.selection || null, msg.corrections || null);
      postMessage({ type: "index", html, seconds: (performance.now() - t0) / 1000 });
    } else if (msg.type === "chapter") {
      const html = driver.chapter(msg.name, say, !!msg.small);
      postMessage({ type: "page", name: msg.name, hash: msg.hash || "", html });
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
    }
  } catch (err) {
    // the type of the failed request lets the page say what did not happen
    postMessage({ type: "error", during: msg.type, chapter: msg.chapter || "",
                  text: String(err && err.message ? err.message : err) });
  }
};
