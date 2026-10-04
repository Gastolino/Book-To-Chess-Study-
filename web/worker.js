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
  // (without them the book is read as before, and its diagrams stay unread)
  if (cfg.packages && cfg.packages.length) {
    try { await py.loadPackage(cfg.packages); }
    catch (err) { say("Board reading is not available: " + String(err && err.message ? err.message : err)); }
  }
  await py.loadPackage(cfg.wheels);
  const zip = await (await fetch(cfg.appZip)).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/app" });
  py.FS.mkdirTree("/books");
  py.runPython("import sys; sys.path.insert(0, '/app/web')");
  driver = py.pyimport("driver");
  postMessage({ type: "ready" });
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
      const html = driver.process(path, say, msg.selection || null);
      postMessage({ type: "index", html, seconds: (performance.now() - t0) / 1000 });
    } else if (msg.type === "chapter") {
      const html = driver.chapter(msg.name, say, !!msg.small);
      postMessage({ type: "page", name: msg.name, hash: msg.hash || "", html });
    } else if (msg.type === "index") {
      postMessage({ type: "page", name: "index.html", hash: msg.hash || "", html: driver.index() });
    }
  } catch (err) {
    postMessage({ type: "error", text: String(err && err.message ? err.message : err) });
  }
};
