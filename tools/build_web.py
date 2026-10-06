"""Build the browser app: a static site where a reader drops a chess book PDF
and reads it beside a live board. Every book is processed on the reader's own
device. The start page is the user's library (web/library.js): served by the
Cloudflare site (wrangler.toml, docs/CLOUDFLARE.md), the site stores the books
and their readings; served anywhere else (GitHub Pages), the browser keeps
them on the device, and nothing is uploaded anywhere.

Usage:
    python3 tools/build_web.py [--out output/site] [--local PYODIDE_DIR]
                               [--pymupdf WHEEL] [--chess WHEEL] [--engine DIR]

By default the site loads Pyodide from its CDN and PyMuPDF from PyPI, so the
site itself stays small. --local copies a Pyodide distribution into the site
and --pymupdf copies the PyMuPDF wheel, for hosts or tests without those
networks. --engine copies the chess engine (tools/fetch_engine.py fetches
it) into site/engine/, where the reader loads it the first time analysis is
turned on; without it the reader says that the engine is not installed.
"""
import argparse
import json
import shutil
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook import engine_files, style  # noqa: E402

PYODIDE_VERSION = "0.29.5"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
# Packages of the Pyodide distribution itself that board reading needs.
PYODIDE_PACKAGES = ["numpy", "opencv-python"]
PYMUPDF_WHEEL = "pymupdf-1.28.2-cp313-abi3-pyemscripten_2025_0_wasm32.whl"

SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chess Book Reader</title>
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon-180.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Chess books">
<style>__CSS__
html,body{height:100%}
body{margin:0;display:flex;flex-direction:column}
#start{max-width:620px;margin:0 auto;padding:72px 16px 32px;width:100%;box-sizing:border-box}
#start h1{font-size:26px;margin-bottom:10px}
#start p{margin:0 0 10px;color:var(--muted)}
#drop{margin-top:28px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);
  padding:40px 0;text-align:center;cursor:pointer}
#drop.over{border-color:var(--accent)}
#drop .big{font-size:17px;font-weight:500;color:var(--fg)}
#drop .small{font-size:13px;color:var(--muted);margin-top:6px}
#file{position:absolute;left:-9999px}
#status{margin-top:20px;font-size:13px;color:var(--muted);min-height:1.5em;
  font-variant-numeric:tabular-nums}
#status.error{color:var(--fail)}
#resume{margin:28px 0 0;font-size:15px;color:var(--fg)}
#resume button{font:inherit;color:var(--accent);background:none;border:0;padding:0;cursor:pointer;margin-left:12px}
#resume button:hover{text-decoration:underline}
#resume[hidden]{display:none}
body.resuming #intro,body.resuming #lib,body.resuming #drop{display:none}
#bar{height:1px;background:var(--line);margin-top:8px;position:relative;overflow:hidden}
#bar i{position:absolute;left:0;top:0;bottom:0;width:30%;background:var(--accent);
  animation:run 1.4s linear infinite;display:none}
#bar.on i{display:block}
@keyframes run{from{left:-30%}to{left:100%}}
#view{flex:1;border:0;width:100%;display:none}
#top{display:none;flex-wrap:wrap;align-items:baseline;gap:4px 20px;padding:10px 16px;
  border-bottom:1px solid var(--line);font-size:13px;color:var(--muted);position:relative}
#note{flex-basis:100%}
#note:empty{display:none}
#note.error{color:var(--fail)}
#topbar{position:absolute;left:0;right:0;bottom:-1px;height:1px;overflow:hidden}
#topbar i{position:absolute;top:0;bottom:0;width:30%;background:var(--accent);
  animation:run 1.4s linear infinite;display:none}
#topbar.on i{display:block}
#top button{font:inherit;color:var(--fg);background:none;border:0;padding:0;cursor:pointer}
#top button:hover{text-decoration:underline}
#top .gap{flex:1}
#top button[hidden]{display:none}
/* the library (web/library.js): the Cloudflare site's, or the one in this browser */
body.library #start{max-width:760px;padding-top:40px}
#lib{margin-top:24px}
#books{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}
.book{display:flex;flex-wrap:wrap;align-items:center;gap:0 16px;padding:12px 0;
  border-bottom:1px solid var(--line)}
.book .open{flex:1;min-width:0;display:flex;align-items:center;gap:14px;background:none;border:0;
  border-radius:0;padding:0;margin:0;text-align:left;cursor:pointer;color:var(--fg);font:inherit}
.book .cover{flex:none;width:44px;height:62px;border:1px solid var(--line);overflow:hidden}
.book .cover img{display:block;width:100%;height:100%;object-fit:cover}
.book .words{min-width:0;display:flex;flex-direction:column;gap:2px}
.book .title{font-size:17px;font-weight:500;line-height:1.35;letter-spacing:-0.01em;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.book .meta{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
.book .open:hover .title{color:var(--accent)}
.book .acts{display:flex;gap:4px 20px;align-items:baseline}
.book .acts .tb{font-size:13px;color:var(--muted)}
.book .acts .tb:hover{color:var(--accent)}
.book .bms{flex-basis:100%;padding-left:58px;margin-top:4px;font-size:13px;color:var(--muted);
  font-variant-numeric:tabular-nums}
.book .bms .tb{font-size:13px;padding:6px 2px;margin:-6px 0}
.book .confirm{flex-basis:100%;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 20px;
  margin-top:10px;font-size:13px}
.book .confirm span{flex-basis:100%}
.book .confirm .yes{color:var(--fail)}
#libempty{color:var(--muted);padding:16px 0;border-bottom:1px solid var(--line)}
#libhint{font-size:13px;color:var(--muted);margin:0 0 16px}
#libhint button{margin-left:8px;font-size:13px;color:var(--fg);white-space:nowrap}
#libspace{font-size:13px;color:var(--muted);margin:12px 0 0;font-variant-numeric:tabular-nums}
@media (max-width:560px){
  .book .acts{flex-basis:100%;padding-left:58px;margin-top:6px}
}
body.library #drop{margin-top:0;border-top:0;padding:28px 0;text-align:left}
body.library #drop .small{max-width:46em}
@media (min-width:900px){
  .book{padding:16px 0}
  .book .cover{width:56px;height:78px}
  .book .open{gap:20px}
  .book .bms{padding-left:76px}
}
</style></head>
<body>
<div id="top"><span id="took"></span><span class="gap"></span>
<button id="again" type="button" hidden>Read again</button>
<button id="another" type="button">Open another book</button>
<span id="note" role="status"></span><div id="topbar"><i></i></div></div>
<main id="start">
<h1>Chess Book Reader</h1>
<div id="intro">
<p>This page turns a chess book in PDF form into a reader: the book's pages beside a
live board that follows the moves and variations.</p>
<p>Your book stays on this device. The page reads it here and sends it nowhere.</p>
</div>
<section id="lib" hidden aria-label="Your library">
<p id="libhint" hidden><span></span><button class="tb" type="button">Hide this note</button></p>
<ul id="books"></ul>
<p id="libempty" hidden>Your library holds no books yet. Add a chess book below: the program
reads it once, and every device you sign in on opens it at once.</p>
<p id="libspace" hidden></p>
</section>
<div id="drop" tabindex="0" role="button" aria-label="Choose a chess book PDF">
<div class="big">Drop a chess book here</div>
<div class="small">or click to choose a PDF file</div></div>
<input id="file" type="file" accept="application/pdf,.pdf,.chessbook,application/zip,.zip">
<p id="resume" hidden><span></span><button type="button">Library</button></p>
<div id="status">Preparing the reader. The first visit downloads about 40 MB; later visits
start at once.</div>
<div id="bar" class="on"><i></i></div>
</main>
<iframe id="view" title="Book reader"></iframe>
<script src="library.js"></script>
<script>
const CFG = __CFG__;
const $ = (id) => document.getElementById(id);
const worker = new Worker("worker.js");
let ready = false, busy = false, current = null, lastFile = null, lastName = "";
// While the worker reads the book, the reader can already read it: the top bar
// says how far the reading has come, and the thin line under it moves.
let loading = false;
// ?pace=MS slows the reading down by MS milliseconds a step (for tests)
CFG.pace = parseInt(new URLSearchParams(location.search).get("pace") || "0", 10) || 0;

// Links inside the reader pages ask this page to open another page.
// String.raw keeps the backslashes of the pattern below; an ordinary template
// literal would turn \\d into d, and no chapter link would match.
const NAV = String.raw`<script>window.CHESSBOOK_APP=true;
document.addEventListener("click",function(e){var a=e.target.closest("a[href]");
if(!a)return;var h=a.getAttribute("href"),m=h.match(/^(index\\.html|ch\\d+\\.html)(#.*)?$/);
if(m){e.preventDefault();parent.postMessage({open:m[1],hash:m[2]||""},"*");}},true);<${"/"}script>`;

// Where the reader was, so that the app comes back there after the system
// closed it (an iPhone or iPad drops a page left in the background; the page
// then loads from the start): one small record in the browser's storage with
// the open book, the chapter, the page, the move and the screen as it stood
// (window.readerView in the reader). It is written a moment after each
// change, and at once when the page is hidden or about to be dropped; it is
// recent for a day, and "Library" forgets it.
const SESSION = (() => {
  const KEY = "chessbook-session", LIMIT = 24 * 3600 * 1000;
  let rec = null, timer = 0;
  function load() {
    try {
      const v = JSON.parse(localStorage.getItem(KEY) || "null");
      return v && typeof v === "object" && v.time ? v : null;
    } catch (e) { return null; }
  }
  function save() {
    if (!rec) return;
    rec.time = Date.now();
    try { localStorage.setItem(KEY, JSON.stringify(rec)); } catch (e) { /* no storage */ }
  }
  // the reader's view, read from its page (the same origin as this one)
  function view() {
    try {
      const w = $("view").contentWindow;
      return w && typeof w.readerView === "function" ? w.readerView() : null;
    } catch (e) { return null; }
  }
  const api = {
    // the record from before, when it is recent: {id, kind, title, name, chapter, page, node, label, view}
    pending() {
      const v = load();
      return v && Date.now() - v.time < LIMIT ? v : null;
    },
    // a book opens: the record starts (place: where it opens, or null for the contents page)
    begin(info, place) {
      rec = Object.assign({ id: null, kind: null, title: null, name: null, chapter: null, page: null, node: null,
                            label: null, view: null }, info);
      if (place) Object.assign(rec, { chapter: place.chapter || null, page: place.page || null, node: place.node || null,
                                      label: place.label || null, view: place.view || null });
      save();
    },
    title(t) { if (rec && t) { rec.title = t; save(); } },
    // the contents page is open
    contents() { if (rec) { rec.chapter = null; rec.view = null; save(); } },
    // the view, now (the chapter open in the reader, its page, move and screen)
    take() {
      if (!rec || !/^ch\\d+\\.html$/.test(openChapter)) return;
      const v = view();
      if (!v || !v.page) return;
      Object.assign(rec, { chapter: openChapter, page: v.page, node: v.node || null, label: v.label || null, view: v });
      save();
    },
    // the view, a moment after a change
    soon() { clearTimeout(timer); timer = setTimeout(api.take, 500); },
    clear() { rec = null; clearTimeout(timer); try { localStorage.removeItem(KEY); } catch (e) { /* no storage */ } },
    place() { return rec && rec.chapter ? { chapter: rec.chapter, page: rec.page, node: rec.node, label: rec.label, view: rec.view } : null; },
    record() { return rec; },
  };
  // the page hidden, dropped or frozen: the view and the place go to the storage at once
  const leaving = () => { api.take(); LIB.leaving(rec); };
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") leaving(); });
  window.addEventListener("pagehide", leaving);
  document.addEventListener("freeze", leaving);
  return api;
})();
// The words of the line that says where the app came back to.
function backTo(r) {
  if (!r) return "";
  const where = r.chapter && r.page ? ", page " + (r.label || r.page) : "";
  return "Back to " + (r.title || "your book") + where;
}
// the hash that reopens a chapter at a place: the page, the move and the view
function placeHash(p) {
  if (!p || !p.page) return "";
  return "#at=" + p.page + ":" + (p.node || "") + (p.view ? "&v=" + encodeURIComponent(JSON.stringify(p.view)) : "");
}
// Messages go to the start screen while it shows, and to the top bar after.
function status(text, error) {
  const inReader = $("top").style.display === "flex";
  const el = inReader ? $("note") : $("status");
  el.textContent = text;
  el.classList.toggle("error", !!error);
}
function working(on) {
  $("bar").classList.toggle("on", on);
  $("topbar").classList.toggle("on", on || loading);
}
// The flag goes first in the head, so that the page's own script sees it
// while it starts (the stored corrections it sends, the words it chooses).
const FLAG = "<script>window.CHESSBOOK_APP=true;window.CHESSBOOK_ENGINE=" + JSON.stringify(CFG.engine) + ";<" + "/script>";
function show(name, hash, htmlText) {
  const page = htmlText.replace("<head>", "<head>" + FLAG).replace("</body>", NAV + "</body>");
  const blob = new Blob([page], { type: "text/html" });
  if (current) URL.revokeObjectURL(current);
  current = URL.createObjectURL(blob);
  $("view").src = current + (hash || "");
  $("start").style.display = "none";
  $("view").style.display = "block";
  $("top").style.display = "flex";
}
worker.onmessage = (e) => {
  const m = e.data;
  // the library's own messages (the stored reading, the cover) end here
  if (LIB.message(m)) return;
  if (m.type === "progress") status(m.text);
  else if (m.type === "ready") {
    ready = true;
    if (!busy) $("bar").classList.remove("on");
    const choose = LIB.on ? "Ready. Open a book or add one." : "Ready. Choose a book.";
    if (!busy) status(m.boards === false ? choose + " This browser could not load board reading, so " +
      "the program reads only the diagrams that the book prints in a chess font." : choose);
  } else if (m.type === "index") {
    // the contents, as soon as the chapters are known: the reading goes on
    // (a book of the library opened from its stored reading is read already)
    busy = false;
    loading = !m.restored;
    $("bar").classList.remove("on");
    $("took").textContent = m.restored ? LIB.openedIn() : "Reading the book";
    openChapter = "index.html";
    show("index.html", "", m.html);
    working(false);
    if (resuming) resumed(m);
  } else if (m.type === "status") {
    if (loading) $("took").textContent = (resumeWords ? resumeWords + ". " : "") + m.text;
  } else if (m.type === "thumbs") {
    if (openChapter === "index.html") toView({ thumbs: m.thumbs });
  } else if (m.type === "done") {
    loading = false;
    if (!m.restored) $("took").textContent = (resumeWords ? resumeWords + ", " : "") + "read in " + Math.round(m.seconds) + " seconds";
    resumeWords = "";
    working(false);
    if (m.html && openChapter === "index.html") show("index.html", "", m.html);
  } else if (m.type === "reopen") {
    // the final reading changed the chapters: the open one opens again
    worker.postMessage({ type: "chapter", name: m.chapter, small: window.matchMedia("(max-width: 700px)").matches });
  } else if (m.type === "patch") {
    patched(m);
  } else if (m.type === "page") {
    working(false);
    $("note").textContent = resumeNote || "";
    resumeNote = "";
    openChapter = m.name;
    show(m.name, m.hash, m.html);
  } else if (m.type === "error") {
    working(false);
    if (m.during === "correct" || m.during === "correct-more") {
      // the reader says so too, instead of waiting for a patch that does not come
      if (m.during === "correct-more") { moreBusy = false; more = []; }
      const text = "Your correction could not be applied: " + m.text;
      status(text, true);
      toView({ failed: text });
      return;
    }
    busy = false;
    if (m.during === "process" || m.during === "restore") { loading = false; working(false); }
    if (m.during === "restore" && lastFile) {
      // a stored reading that cannot be opened: the book is read instead
      status("The stored reading could not be opened (" + m.text + "). The program reads the book again.");
      read(lastFile, lastName);
      return;
    }
    status("Something went wrong: " + m.text, true);
  }
};
// A worker that dies (for instance when a phone runs out of memory) sends no
// message, so its error event is reported here.
worker.onerror = (e) => {
  busy = false;
  working(false);
  status("The reader stopped: " + (e.message || "the browser ran out of memory") +
    ". Closing other tabs or using a computer can help.", true);
};
// Corrections made in a chapter reader are applied at once by the worker,
// which answers with a patch for the open page. A changed piece symbol
// reaches the other chapters afterwards, one chapter at a time. One request
// for them is on its way at a time: a correction made meanwhile (which
// answers with the chapters still pending) does not start a second chain.
let more = [], moreDone = 0, moreBusy = false, openChapter = "";
// The app comes back to where the reader was (SESSION): resuming holds the
// record while the book opens; resumeNote is said in the top bar once the
// chapter shows.
let resuming = null, resumeNote = "", resumeWords = "";
function resumeStart(r) {
  resuming = r;
  document.body.classList.add("resuming");
  $("resume").querySelector("span").textContent = backTo(r) + ".";
  $("resume").hidden = false;
}
// the contents page of the resumed book showed: the chapter follows (the
// library posts it); the top bar says where the app came back to
function resumed(m) {
  const r = resuming;
  resuming = null;
  document.body.classList.remove("resuming");
  $("resume").hidden = true;
  if (m.title) SESSION.title(m.title);
  const words = backTo(SESSION.record() || r);
  if (m.restored) $("took").textContent = words;
  else {
    // the book is read again: the top bar's progress line carries the words meanwhile
    resumeWords = words;
    $("took").textContent = words + ". Reading the book";
    resumeNote = words + (LIB.on ? ". The book is read again, because the app was closed before its reading was finished."
                                 : ". The book is read again, because this browser keeps no library.");
  }
  if (!LIB.on) {
    // no library: the book the user chose again opens at the place
    const place = SESSION.place();
    if (place) worker.postMessage({ type: "chapter", name: place.chapter, hash: placeHash(place),
                                    small: window.matchMedia("(max-width: 700px)").matches });
  }
}
$("resume").querySelector("button").addEventListener("click", () => { SESSION.clear(); location.reload(); });
function toView(msg) { if ($("view").contentWindow) $("view").contentWindow.postMessage(msg, "*"); }
function patched(m) {
  const r = m.result || {};
  if (r.patch && m.chapter === openChapter) toView({ patch: r.patch });
  if (m.more) moreBusy = false;
  const pend = (r.pending || []).slice(), had = more.length;
  if (!had) moreDone = 0;
  moreDone += more.filter((c) => pend.indexOf(c) < 0).length;
  more = pend;
  if (more.length) {
    // a chapter stays pending until all its pages are done, ten pages at a time
    const text = "Applying your piece choice to the other chapters: " + (moreDone + 1) + " of " +
      (moreDone + more.length) + ".";
    status(text); toView({ progress: text });
    if (!moreBusy) {
      moreBusy = true;
      worker.postMessage({ type: "correct-more", chapters: [more[0]], chapter: openChapter });
    }
  } else if (m.more || had) {
    status("Your piece choice is applied to the whole book.");
    toView({ progress: "Your piece choice is applied to the whole book." });
  } else status("");
}
window.addEventListener("message", (e) => {
  LIB.fromReader(e.data);
  if (e.data && (e.data.position || e.data.view)) { SESSION.soon(); return; }
  if (e.data && e.data.open === "index.html") { openChapter = "index.html"; SESSION.contents(); }
  if (e.data && e.data.correct) {
    openChapter = e.data.chapter;
    worker.postMessage({ type: "correct", corrections: e.data.correct, chapter: e.data.chapter });
    return;
  }
  if (e.data && e.data.selectionChanged) { $("again").hidden = false; return; }
  if (e.data && e.data.bookmarksChanged) return;
  if (!e.data || !e.data.open) return;
  working(true);
  status(e.data.open === "index.html" ? "Opening the contents." :
    "Opening chapter " + parseInt(e.data.open.slice(2), 10) +
    ". The first opening of a chapter takes a few seconds.");
  worker.postMessage(e.data.open === "index.html"
    ? { type: "index", hash: e.data.hash }
    : { type: "chapter", name: e.data.open, hash: e.data.hash,
        small: window.matchMedia("(max-width: 700px)").matches });
});
// A book the user chose: added to the library first (the site's, or the one
// in this browser), which takes a book file saved from a library as well.
async function take(file) {
  if (!file || busy) return;
  if (LIB.on) { LIB.add(file); return; }
  if (!/\\.pdf$/i.test(file.name)) { status("Please choose a PDF file.", true); return; }
  read(file, file.name);
}
// The program reads the book (file, a File or Blob, named fileName).
async function read(file, fileName) {
  if (!file || busy) return;
  if (!ready) { status("The reader is still starting. Try again in a moment."); return; }
  busy = true;
  lastFile = file;
  lastName = fileName;
  $("again").hidden = true;
  $("bar").classList.add("on");
  status("Reading " + fileName);
  const bytes = await file.arrayBuffer();
  const name = fileName.replace(/[^\\w.\\-]+/g, "_");
  if (!LIB.on) {
    // no library: the record names the file, and the book opens at the place when it is chosen again
    const r = SESSION.pending();
    const same = !!(r && !r.id && r.name === name);
    SESSION.begin({ name, title: same && r.title ? r.title : fileName.replace(/\\.pdf$/i, "") }, same ? r : null);
    if (same && !resuming) resumeStart(r);
  }
  worker.postMessage({ type: "process", name, bytes, selection: storedSelection(name),
    corrections: storedCorrections(name) }, [bytes]);
}
$("drop").addEventListener("click", () => $("file").click());
$("drop").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") $("file").click(); });
// the chooser forgets the file, so that choosing the same file again is noticed
$("file").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; take(f); });
["dragenter", "dragover"].forEach((t) => $("drop").addEventListener(t, (e) => {
  e.preventDefault(); $("drop").classList.add("over"); }));
["dragleave", "drop"].forEach((t) => $("drop").addEventListener(t, (e) => {
  e.preventDefault(); $("drop").classList.remove("over"); }));
$("drop").addEventListener("drop", (e) => take(e.dataTransfer.files[0]));
$("another").addEventListener("click", () => { SESSION.clear(); location.reload(); });
$("again").addEventListener("click", () => {
  if (!lastFile || busy) return;
  $("start").style.display = "block"; $("view").style.display = "none"; $("top").style.display = "none";
  read(lastFile, lastName);
});
// The reader keeps a changed selection under "chessbook-selection:<file>:<pages>".
function storedSelection(name) {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith("chessbook-selection:" + name + ":")) {
        const v = JSON.parse(localStorage.getItem(k));
        if (v && v.selection) return JSON.stringify(v.selection);
      }
    }
  } catch (e) { /* no storage */ }
  return null;
}
// The reader keeps its corrections under "chessbook-corrections:<file>:<pages>".
function storedCorrections(name) {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith("chessbook-corrections:" + name + ":")) {
        const v = JSON.parse(localStorage.getItem(k));
        if (v && v.corrections) return JSON.stringify(v.corrections);
      }
    }
  } catch (e) { /* no storage */ }
  return null;
}
worker.postMessage({ type: "init", cfg: CFG });
// the start page becomes the library: the Cloudflare site's, or the one in
// this browser; a book the system closed while it was open opens again there
LIB.start(SESSION.pending()).then((on) => {
  if (on) return;
  const r = SESSION.pending();
  if (r && !r.id && r.name) {
    $("resume").querySelector("span").textContent = "The app was closed while you read " + (r.title || "a book") +
      (r.page ? " at page " + (r.label || r.page) : "") + ". This browser keeps no library, so the book has to be " +
      "chosen again; it then opens at that place.";
    $("resume").querySelector("button").hidden = true;
    $("resume").hidden = false;
  } else SESSION.clear();
});
</script>
</body></html>
"""


def icon_png(size):
    """The Home Screen icon: a corner of a chess board in the board colours of
    DESIGN.md, flat, as a PNG of size by size pixels."""
    light, dark, bg = (0xec, 0xeb, 0xe6), (0xbd, 0xba, 0xb2), (0xfb, 0xfb, 0xfa)
    margin, cells = size // 6, 4
    cell = (size - 2 * margin) // cells
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            cx, cy = (x - margin) // cell, (y - margin) // cell
            inside = 0 <= x - margin < cell * cells and 0 <= y - margin < cell * cells
            row += bytes(bg if not inside else light if (cx + cy) % 2 == 0 else dark)
        rows.append(bytes(row))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


# Added to the Home Screen of an iPhone or iPad, the app opens on its own
# (without Safari's bars) and keeps its library apart from Safari, which may
# clear the storage of a site left unused for a week.
MANIFEST = {"name": "Chess Book Reader", "short_name": "Chess books", "start_url": "./", "scope": "./",
            "display": "standalone", "background_color": "#fbfbfa", "theme_color": "#fbfbfa",
            "icons": [{"src": "icon-180.png", "sizes": "180x180", "type": "image/png"},
                      {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}]}


def app_zip(dest):
    """The project's Python code (and fonts) as one archive for the browser."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted((ROOT / "chessbook").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                z.write(path, path.relative_to(ROOT).as_posix())
        z.write(ROOT / "stage1_inspect.py", "stage1_inspect.py")
        z.write(ROOT / "web" / "driver.py", "web/driver.py")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "site")
    ap.add_argument("--local", type=Path, default=None,
                    help="a Pyodide distribution folder to copy into the site")
    ap.add_argument("--pymupdf", type=Path, default=None, help="PyMuPDF wheel to copy")
    ap.add_argument("--chess", type=Path, required=True, help="python-chess wheel to copy")
    ap.add_argument("--pymupdf-url", default=None,
                    help="where browsers fetch the PyMuPDF wheel when it is not copied")
    ap.add_argument("--engine", type=Path, default=None,
                    help="folder holding the chess engine files (tools/fetch_engine.py)")
    args = ap.parse_args(argv)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "wheels").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "web" / "worker.js", out / "worker.js")
    shutil.copyfile(ROOT / "web" / "library.js", out / "library.js")
    (out / "manifest.webmanifest").write_text(json.dumps(MANIFEST, indent=1), encoding="utf-8")
    for size in (180, 512):
        (out / f"icon-{size}.png").write_bytes(icon_png(size))
    app_zip(out / "app.zip")
    shutil.copyfile(args.chess, out / "wheels" / args.chess.name)
    wheels = ["wheels/" + args.chess.name]
    if args.pymupdf:
        shutil.copyfile(args.pymupdf, out / "wheels" / args.pymupdf.name)
        wheels.insert(0, "wheels/" + args.pymupdf.name)
    elif args.pymupdf_url:
        wheels.insert(0, args.pymupdf_url)
    else:
        raise SystemExit("Give --pymupdf or --pymupdf-url.")
    if args.local:
        shutil.copytree(args.local, out / "pyodide", dirs_exist_ok=True)
        index_url = "pyodide/"
    else:
        index_url = PYODIDE_CDN
    # The engine (1.8 MB) is fetched only when a reader turns analysis on; once
    # fetched, the reader keeps it in the browser's storage, so it runs offline.
    # The files never change under one name, so a host that takes a _headers
    # file (Cloudflare Pages) may cache them for a year; GitHub Pages sets its
    # own headers and ignores the file.
    engine = "null"
    if args.engine:
        engine_files.copy(args.engine, out / "engine")
        engine = "new URL('engine/', location.href).href"
        (out / "_headers").write_text("/engine/*\n  Cache-Control: public, max-age=31536000, immutable\n",
                                      encoding="utf-8")
    # Wheel paths are made absolute against the site, because the worker
    # resolves them from its own location.
    cfg = ("{indexURL: new URL(%r, location.href).href, appZip: new URL('app.zip', location.href).href, "
           "wheels: %s.map(w => new URL(w, location.href).href), packages: %s, engine: %s}") % (
               index_url, wheels, PYODIDE_PACKAGES, engine)
    text = SHELL.replace("__CSS__", style.page_css()).replace("__CFG__", cfg)
    (out / "index.html").write_text(text, encoding="utf-8")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"Site written to {out} ({size / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
