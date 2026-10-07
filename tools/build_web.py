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
import hashlib
import json
import shutil
import sys
import zipfile
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
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Chess Book Reader</title>
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="icon" href="icon-32.png" sizes="32x32" type="image/png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Chess books">
<style>__CSS__
html,body{height:100%}
/* the page keeps clear of the iPhone's notch and rounded corners, and lifts the reader's bar
   just above the home indicator (the reader's frame cannot: a frame is told no safe area). The
   lift is the safe area less 14 px (20 px on an iPhone X and later, against Apple's 34): the
   bar's buttons stay out of the indicator's swipe, and the bar grows only a little */
body{margin:0;display:flex;flex-direction:column;box-sizing:border-box;
  padding:env(safe-area-inset-top) env(safe-area-inset-right)
    max(0px, calc(env(safe-area-inset-bottom) - 14px)) env(safe-area-inset-left)}
#start{max-width:620px;margin:0 auto;padding:72px 16px 32px;width:100%;box-sizing:border-box}
#start h1{font-size:26px;margin-bottom:10px}
#start p{margin:0 0 10px;color:var(--muted)}
#drop{margin-top:28px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);
  padding:40px 0;text-align:center;cursor:pointer}
#drop.over{border-color:var(--accent)}
#drop .big{font-size:17px;font-weight:500;color:var(--fg)}
#drop .small{font-size:13px;color:var(--muted);margin-top:6px}
#file{position:absolute;left:-9999px}
#status{margin-top:12px;font-size:13px;color:var(--muted);min-height:1.5em;
  font-variant-numeric:tabular-nums}
#status.error{color:var(--fail)}
#resume{margin:28px 0 0;font-size:15px;color:var(--fg)}
#resume button{font:inherit;color:var(--accent);background:none;border:0;padding:0;cursor:pointer;margin-left:12px}
#resume button:hover{text-decoration:underline}
#resume[hidden]{display:none}
body.resuming #intro,body.resuming #lib,body.resuming #drop{display:none}
/* The sign that the app is at work: the open book whose page turns (chessbook/style.py), over a
   thin bar that fills as far as the work has come where the app knows it, and otherwise carries
   a sliding segment; the words of the work go under it. In the reader, the small book stands at
   the right of the top bar, over the same thin line along the bar's foot. */
#loader{display:none;margin-top:28px}
#loader.on{display:block}
#loader .bookicon{width:88px;height:auto;margin:0 auto 14px}
#bar{height:2px;background:var(--line);position:relative;overflow:hidden}
#bar i,#topbar i{position:absolute;left:0;top:0;bottom:0;width:30%;background:var(--accent);
  animation:run 1.4s linear infinite;display:none}
#bar b,#topbar b{position:absolute;left:0;top:0;bottom:0;width:0;background:var(--accent);display:none;
  transition:width .3s ease-out}
#bar.on:not(.det) i,#topbar.on:not(.det) i{display:block}
#bar.on.det b,#topbar.on.det b{display:block}
@keyframes run{from{left:-30%}to{left:100%}}
@media (prefers-reduced-motion:reduce){#bar i,#topbar i{animation-duration:4s}}
#busy{display:inline-flex;align-items:center;justify-content:center;width:26px;height:18px;
  margin:-2px -4px -2px 0;visibility:hidden;align-self:center;padding:0}
#busy.on{visibility:visible}
#busy .bookicon{width:24px;height:auto}
#view{flex:1;border:0;width:100%;display:none}
iframe.view{flex:1;border:0;width:100%}
#top{display:none;flex-wrap:wrap;align-items:baseline;gap:4px 16px;padding:10px 16px;
  border-bottom:1px solid var(--line);font-size:13px;color:var(--muted);position:relative}
/* One line: the book's name takes the room that the small book and Library leave in the
   right-hand corner, and a long name ends in an ellipsis, so that the bar keeps its height. The
   words of the work do not show in the bar (#took keeps them): a tap on the small book shows them. */
#booktitle{flex:1 1 0;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* Under the line, only when one of them has something to say: the notes, the way back from the
   contents and Read again, so that none of them crowds the book's name on a phone. */
#sub{flex-basis:100%;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 20px}
#sub:not(:has(> :not([hidden]):not(:empty))){display:none}
/* the whole words of the work, for a few seconds after a tap on the small book (and where the
   app came back to): over the page, under the bar, so that nothing moves */
#tip{position:absolute;top:100%;left:0;right:0;z-index:5;padding:8px 16px;background:var(--bg);
  border-bottom:1px solid var(--line);color:var(--fg)}
#tip[hidden]{display:none}
#note:empty{display:none}
#note.error{color:var(--fail)}
#topbar{position:absolute;left:0;right:0;bottom:-1px;height:1px;overflow:hidden}
#top button{font:inherit;color:var(--fg);background:none;border:0;padding:0;cursor:pointer}
#top button:hover{text-decoration:underline}
#top{transition:margin-top .2s ease}
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
<div id="top"><span id="booktitle"></span>
<button id="busy" type="button" aria-label="What the program is doing" title="What the program is doing">__BOOK_SMALL__</button>
<button id="another" type="button">Open another book</button>
<div id="sub"><span id="note" role="status"></span><button id="backbtn" type="button" hidden></button>
<button id="again" type="button" hidden>Read again</button></div>
<span id="took" hidden></span><span id="tip" role="status" hidden></span><div id="topbar"><i></i><b></b></div></div>
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
<div id="loader" class="on">__BOOK__<div id="bar" class="on" role="progressbar" aria-label="Progress"><i></i><b></b></div></div>
<div id="status">Preparing the reader. The first visit downloads about 40 MB; later visits
start at once.</div>
</main>
<iframe id="view" title="Book reader"></iframe>
<script src="library.js"></script>
<script>
const CFG = __CFG__;
const $ = (id) => document.getElementById(id);
// The libraries come from the device after the first visit (sw.js). On the very first visit
// the worker starts once the service worker looks after the page (or after two seconds), so
// that what it loads is kept already.
const SW = ("serviceWorker" in navigator && /^https?:$/.test(location.protocol))
  ? navigator.serviceWorker.register("sw.js").then(() => {
      if (navigator.serviceWorker.controller) return;
      return new Promise((resolve) => {
        navigator.serviceWorker.addEventListener("controllerchange", resolve, { once: true });
        setTimeout(resolve, 2000);
      });
    }).catch(() => {})
  : Promise.resolve();
const worker = new Worker("worker.js");
let ready = false, busy = false, current = null, lastFile = null, lastName = "";
// While the worker reads the book, the reader can already read it: the thin line
// along the top bar's foot moves, and a tap on the small book says how far the
// reading has come.
let loading = false;
// ?pace=MS slows the reading down by MS milliseconds a step (for tests)
CFG.pace = parseInt(new URLSearchParams(location.search).get("pace") || "0", 10) || 0;

// Links inside the reader pages ask this page to open another page.
// String.raw keeps the backslashes of the pattern below; an ordinary template
// literal would turn \\d into d, and no chapter link would match.
const NAV = String.raw`<script>window.CHESSBOOK_APP=true;
document.addEventListener("click",function(e){var a=e.target.closest("a[href]");
if(!a)return;var h=a.getAttribute("href"),m=h.match(/^(index\\.html|ch\\d+\\.html)(#.*)?$/);
if(m){e.preventDefault();parent.postMessage({open:m[1],hash:m[2]||""},"*");}},true);
var sy=0;window.addEventListener("scroll",function(){if(sy)return;sy=requestAnimationFrame(function(){sy=0;
parent.postMessage({scrollY:window.scrollY},"*");});},{passive:true});<${"/"}script>`;

// Where the reader was, so that the app comes back there after the system
// closed it (an iPhone or iPad drops a page left in the background; the page
// then loads from the start): one small record in the browser's storage with
// the open book, the chapter, the page, the move and the screen as it stood
// (window.readerView in the reader). It is written a moment after each
// change, and at once when the page is hidden or about to be dropped; it is
// recent for a day, and "Library" forgets it.
const SESSION = (() => {
  const KEY = "chessbook-session", LIMIT = 24 * 3600 * 1000;
  // stopped: the page is about to load the library (the Library button), and
  // a book still opening must not record itself as the open book again
  let rec = null, timer = 0, stopped = false;
  function load() {
    try {
      const v = JSON.parse(localStorage.getItem(KEY) || "null");
      return v && typeof v === "object" && v.time ? v : null;
    } catch (e) { return null; }
  }
  function save() {
    if (!rec || stopped) return;
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
    // forget the record; final: the page is about to reload, and records nothing more
    clear(final) {
      rec = null; clearTimeout(timer);
      if (final) stopped = true;
      try { localStorage.removeItem(KEY); } catch (e) { /* no storage */ }
    },
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
  if (error && window.TOPBAR) TOPBAR.show();       // a failure is never out of sight
}
// One sign of work: the book and the bar on the start page, the small book and the line along the
// top bar's foot in the reader. It shows while a request is on its way (working), while the book
// is read (loading), while pictures of pages are drawn and while the reading is saved. The words
// of the work are kept, for a tap on the small book.
let workingNow = false, saving = false, workWords = "", fraction = null;
function working(on) {
  workingNow = !!on;
  indicate();
}
function indicate() {
  let drawing = false;
  try { drawing = PICS.busy(); } catch (e) { drawing = false; }   // (before PICS exists)
  const on = workingNow || loading || saving || drawing;
  const startOn = $("start").style.display !== "none" && (workingNow || busy || !ready);
  $("bar").classList.toggle("on", startOn);
  $("loader").classList.toggle("on", startOn);
  $("topbar").classList.toggle("on", on);
  $("busy").classList.toggle("on", on);
  const det = fraction !== null && fraction >= 0 && fraction <= 1;
  for (const id of ["bar", "topbar"]) {
    $(id).classList.toggle("det", det);
    if (det) $(id).querySelector("b").style.width = (100 * fraction).toFixed(1) + "%";
  }
  if (det) $("bar").setAttribute("aria-valuenow", String(Math.round(100 * fraction)));
  else $("bar").removeAttribute("aria-valuenow");
}
// how far the work has come, from its words: "Reading the pages: 12 of 402" (null: not known)
function progressOf(text) {
  const m = /(\d+) of (\d+)/.exec(text || "");
  return m && +m[2] > 0 ? Math.min(1, +m[1] / +m[2]) : null;
}
function workSay(text, frac) {
  workWords = text || workWords;
  fraction = frac === undefined ? progressOf(text) : frac;
  indicate();
}
// the words of the work now, for a tap on the small book
function workNow() {
  const parts = [];
  if (loading) parts.push($("took").textContent || workWords);
  let w = null;
  try { w = PICS.drawing(); } catch (e) { w = null; }
  if (w) parts.push("Drawing pages " + w[0] + " to " + w[1] + ".");
  if (saving) parts.push("Saving the program's reading to your library.");
  if (!parts.length && workingNow) parts.push(workWords);
  return parts.filter(Boolean).join(" ").replace(/([^.])( Drawing| Saving)/g, "$1.$2");
}
// Words shown whole for a few seconds, in a slip under the bar (#tip) that moves nothing: the
// words of the work after a tap on the small book, and where the app came back to. A tap on the
// slip puts it away at once, so that it never stands between the reader and the page's tools.
let tipTimer = 0;
function tip(text) {
  const el = $("tip");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(tipTimer);
  tipTimer = setTimeout(() => { el.hidden = true; }, 4000);
}
$("busy").addEventListener("click", () => tip(workNow() || "The program has nothing to do now."));
$("tip").addEventListener("click", () => { clearTimeout(tipTimer); $("tip").hidden = true; });
// The book's name in the top bar: the title the library knows, or the one the reading found, or
// the file's name in words; the whole name shows on a pointer's hover when the bar cuts it short.
function bookTitle(text) {
  $("booktitle").textContent = text || "";
  $("booktitle").title = text || "";
}
// The flag goes first in the head, so that the page's own script sees it
// while it starts (the stored corrections it sends, the words it chooses).
const FLAG = "<script>window.CHESSBOOK_APP=true;window.CHESSBOOK_ENGINE=" + JSON.stringify(CFG.engine) + ";<" + "/script>";
// The app's top bar names the book, so the reader's own bar shows the chapter alone (a reader
// opened from disk keeps the book's name there). The rule goes after the page's own style, which
// it overrides.
const APP_STYLE = "<style>.where .book{display:none}</style>";
// A page of the reader shows in a fresh frame. While a reader shows, the next one loads in a
// hidden frame of the same size and takes its place once it has shown its page (or after a
// short while), so that turning from one chapter to the next shows no empty page between them.
let swapping = null;
function show(name, hash, htmlText) {
  TOPBAR.show();
  const page = htmlText.replace("<head>", "<head>" + FLAG).replace("</head>", APP_STYLE + "</head>")
    .replace("</body>", NAV + "</body>");
  const url = URL.createObjectURL(new Blob([page], { type: "text/html" }));
  const old = $("view");
  const fresh = document.createElement("iframe");
  fresh.title = "Book reader";
  fresh.className = "view";
  if (swapping) swapping.abandon();
  const before = current;
  current = url;
  if (old.style.display !== "block" || name === "index.html" || openChapter === "index.html") {
    fresh.id = "view";
    fresh.style.display = "block";
    old.replaceWith(fresh);
    fresh.src = url + (hash || "");
    if (before) URL.revokeObjectURL(before);
  } else {
    const r = old.getBoundingClientRect();
    fresh.style.cssText = "display:block;position:fixed;visibility:hidden;left:" + r.left + "px;top:" + r.top +
      "px;width:" + r.width + "px;height:" + r.height + "px;flex:none";
    old.after(fresh);
    let done = false, timer = 0;
    const swap = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      swapping = null;
      fresh.style.cssText = "display:block";
      old.remove();
      fresh.id = "view";
      if (before) URL.revokeObjectURL(before);
    };
    swapping = { frame: fresh, swap, abandon: () => { done = true; clearTimeout(timer); fresh.remove(); URL.revokeObjectURL(url); swapping = null; } };
    // the reader says when its page shows; a reader that says nothing takes its place on load
    fresh.addEventListener("load", () => { timer = setTimeout(swap, 400); }, { once: true });
    fresh.src = url + (hash || "");
  }
  $("start").style.display = "none";
  $("top").style.display = "flex";
}
worker.onmessage = (e) => {
  const m = e.data;
  // the reading is saved to the library after the book is read: the sign of work shows meanwhile
  if (m.type === "done" && (!m.restored || m.resave) && LIB.on && LIB.current && !LIB.current.ephemeral) saving = true;
  if (m.type === "reading" || (m.type === "error" && m.during === "save")) { saving = false; indicate(); }
  // the library's own messages (the stored reading, the cover) end here
  if (LIB.message(m)) return;
  if (m.type === "progress") {
    status(m.text);
    // the steps of starting: Python, then the libraries
    workSay(m.text, !ready ? (/^Starting Python/.test(m.text) ? 0.15 : /^Loading the PDF/.test(m.text) ? 0.45 : null)
                         : undefined);
  } else if (m.type === "ready") {
    ready = true;
    fraction = null;
    working(busy);
    if (!busy) status(LIB.on ? "Ready. Open a book or add one." : "Ready. Choose a book.");
  } else if (m.type === "boards") {
    // the board libraries load after the worker is ready (a stored book needs none to show)
    if (!m.ok) status("This browser could not load board reading, so the program reads only the " +
      "diagrams that the book prints in a chess font.");
  } else if (m.type === "outdated") {
    // the stored reading's state for corrections could not be loaded once the book showed
    outdated(m.why);
    if (openChapter && openChapter !== "index.html") $("note").textContent = outdatedNote;
  } else if (m.type === "index") {
    // the chapters are known: the book opens at its first page (a new book), or where the
    // reader was (the library's place, the app coming back, Read again), while the reading
    // goes on (a book of the library opened from its stored reading is read already)
    busy = false;
    loading = !m.restored;
    bookChapters = m.chapters || [];
    PICS.book(LIB.on && LIB.current && !LIB.current.ephemeral ? LIB.current.id : null, m.pages);
    prepared = {};
    // the top bar names the book (the library has taken the reading's title by now)
    bookTitle(LIB.on && LIB.current ? LIB.titleOf(LIB.current.book)
                                    : m.title || lastName.replace(/\\.pdf$/i, "").replace(/_+/g, " ").trim());
    // the words of the work: a book opened from the library has none, and the body's data-book
    // says how it came (for the tests)
    $("took").textContent = m.restored ? "" : "Reading the book";
    document.body.dataset.book = m.restored ? "opened" : "reading";
    outdated(m.outdated);
    const words = resuming ? resumed(m) : null;
    let place = againPlace || (LIB.on ? LIB.takePlace() : null) || (words !== null || resumeOwn ? SESSION.place() : null);
    againPlace = null; resumeOwn = false;
    let name = place && place.page ? chapterOf(place.page) || place.chapter : null;
    if (!name) { place = { page: 1 }; name = m.first || chapterOf(1); }
    openChapter = "";
    status("Opening the book.");
    workSay("Opening the book", null);
    wantOpen = name;
    worker.postMessage({ type: "chapter", name,
                         hash: place.node || place.view ? placeHash(place) : "#page=" + place.page });
  } else if (m.type === "status") {
    if (loading) $("took").textContent = (resumeWords ? resumeWords + ". " : "") + m.text;
    workSay(m.text);
    if ($("start").style.display !== "none") status(m.text);
  } else if (m.type === "thumbs") {
    if (openChapter === "index.html") toView({ thumbs: m.thumbs });
  } else if (m.type === "done") {
    loading = false;
    prepared = {};
    if (!m.restored) {
      $("took").textContent = resumeWords;
      document.body.dataset.book = "read";
      document.body.dataset.seconds = String(Math.round(m.seconds));
    }
    resumeWords = "";
    working(false);
    if (m.html && openChapter === "index.html") show("index.html", "", m.html);
  } else if (m.type === "reopen") {
    prepared = {};
    // the final reading changed the chapters: the open one opens again
    wantOpen = m.chapter;
    worker.postMessage({ type: "chapter", name: m.chapter, small: window.matchMedia("(max-width: 700px)").matches });
  } else if (m.type === "patch") {
    prepared = {};
    patched(m);
  } else if (m.type === "drawn") {
    PICS.drawn(m);
  } else if (m.type === "page") {
    if (m.prepared) { if (!loading) prepared[m.name] = m.html; return; }
    if (m.quiet) return;
    // a page asked for before the last request (the reader turned on meanwhile) does not show
    if (wantOpen && m.name !== wantOpen) return;
    working(false);
    $("note").textContent = resumeNote || outdatedNote || "";
    resumeNote = "";
    if (m.name !== "index.html") hideBack();
    openChapter = m.name;
    show(m.name, m.hash, m.html);
    if (resumeTip) { tip(resumeTip); resumeTip = ""; }
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
// The chapters of the open book ({file, start, end}), the chapters built ahead of the page turn
// that reaches them (file -> HTML), the place to open after Read again, and the words of a
// stored reading that other reading code made.
let bookChapters = [], prepared = {}, againPlace = null, resumeOwn = false, outdatedNote = "", wantOpen = "";
function chapterOf(p) {
  const c = bookChapters.find((c) => c.start <= p && p <= c.end);
  return c ? c.file : null;
}
// The reader is near the end (or the start) of its chapter: the next (or previous) chapter is
// built now, so that the page turn shows it at once. Not while the book is read: its reading
// changes from one moment to the next.
let prepareTimer = 0;
function prepare(w) {
  clearTimeout(prepareTimer);
  if (loading || !w || !w.page) return;
  // the pictures of the page shown come first: the worker does one thing at a time
  if (PICS.busy()) { prepareTimer = setTimeout(() => prepare(w), 400); return; }
  const near = w.page >= w.end - 1 ? w.end + 1 : w.page <= w.start + 1 ? w.start - 1 : 0;
  const name = near ? chapterOf(near) : null;
  if (!name || prepared[name] || name === openChapter) return;
  prepared[name] = "";
  worker.postMessage({ type: "chapter", name, prepare: true });
}
// "Back to page 31" under the top bar's line while the contents show
let backPlace = null;
function showBack() {
  let v = null;
  try { const w = $("view").contentWindow; v = w && w.readerView ? w.readerView() : null; } catch (e) { v = null; }
  if (!v || !v.page || !/^ch\d+\.html$/.test(openChapter)) return;
  backPlace = { chapter: openChapter, page: v.page, node: v.node || null, view: v };
  $("backbtn").textContent = "Back to page " + (v.label || v.page);
  $("backbtn").hidden = false;
}
function hideBack() { $("backbtn").hidden = true; backPlace = null; }
function goBack() {
  if (!backPlace) return;
  const p = backPlace;
  hideBack();
  working(true);
  wantOpen = p.chapter;
  worker.postMessage({ type: "chapter", name: p.chapter, hash: placeHash(p) });
}
$("backbtn").addEventListener("click", () => {
  if (history.state && history.state.contents) history.back(); else goBack();
});
window.addEventListener("popstate", () => { if (openChapter === "index.html" && backPlace) goBack(); });
// A stored reading that other reading code made opens all the same; Read again reads the book
// with the program of today, keeping the corrections, the bookmarks and the place.
function outdated(why) {
  outdatedNote = why === "state"
    ? "This copy of the book was read by an earlier version of the program: it shows the book, and corrections need it read again."
    : why === "code" ? "An improved reading is available." : "";
  if (why) $("again").hidden = false;
}

// The pictures of the pages, ten pages at a time (a window: pages 1 to 10, 11 to 20, ...). The
// reader says which page it shows; the window of that page comes first, then the one ahead and
// the one behind. Each picture comes from the device's store when it holds it, and is drawn by
// the worker otherwise (one request per window), then kept in the store for the next time. The
// page keeps the pictures of those three windows only.
const PICS = (() => {
  const WIN = 10;
  let id = null, pages = 0, size = "large", cache = new Map(), want = null, client = null;
  let queue = [], busyWin = null, busyFull = false, gen = 0, drawT0 = 0;
  const win = (p) => Math.floor((p - 1) / WIN);
  const range = (w) => { const out = []; for (let p = w * WIN + 1; p <= Math.min(pages, w * WIN + WIN); p++) out.push(p); return out; };
  const stats = { draws: 0, drawn: 0, stored: 0, delivered: 0, drawMs: 0, storeMs: 0, storeReads: 0 };
  window.pictureStats = stats;
  function deliver(got) {
    if (!client || !want) return;
    const out = {};
    let n = 0;
    for (const p in got) if (p >= want.start && p <= want.end) { out[p] = got[p]; n++; }
    if (!n) return;
    stats.delivered += n;
    try { client.postMessage({ pictures: out }, "*"); } catch (e) { /* the frame is gone */ }
  }
  function trim() {
    if (!want) return;
    const w = win(want.page);
    for (const p of [...cache.keys()]) if (Math.abs(win(p) - w) > 1) cache.delete(p);
  }
  // a job is a window (a number), or the page shown alone ({page}): drawn before the rest of
  // its window, so that it shows as soon as it can
  async function pump() {
    if (busyWin !== null || !queue.length) return;
    const job = queue.shift();
    const w = typeof job === "number" ? job : win(job.page);
    const todo = (typeof job === "number" ? range(w) : [job.page]).filter((p) => !cache.has(p));
    if (!todo.length) return pump();
    busyWin = w;
    busyFull = typeof job === "number";
    const g = gen;
    let kept = {};
    const t0 = performance.now();
    if (id) { try { kept = await LIB.pagesGet(id, size, todo); } catch (e) { kept = {}; } }
    if (Object.keys(kept).length) { stats.storeMs += performance.now() - t0; stats.storeReads++; }
    if (g !== gen) { busyWin = null; return pump(); }
    const got = {};
    for (const p in kept) { cache.set(+p, kept[p]); got[p] = kept[p]; stats.stored++; }
    deliver(got);
    const missing = todo.filter((p) => !kept[p]);
    if (!missing.length) { busyWin = null; return pump(); }
    stats.draws++;
    drawT0 = performance.now();
    indicate();
    worker.postMessage({ type: "draw", pages: missing, size, window: w, gen: g });
  }
  return {
    busy: () => busyWin !== null,
    drawing: () => (busyWin === null ? null : [busyWin * WIN + 1, Math.min(pages, busyWin * WIN + WIN)]),
    book(bookId, pageCount) {
      id = bookId; pages = pageCount || 0; cache = new Map(); queue = []; busyWin = null; gen++;
      size = window.matchMedia("(max-width: 700px)").matches ? "small" : "large";
    },
    want(w, source) {
      if (!pages || !w || !w.page) return;
      client = source;
      want = w;
      const c = win(w.page), last = win(pages);
      const order = [c, c + 1, c - 1].filter((x) => x >= 0 && x <= last);
      const now = {};
      for (const x of order) for (const p of range(x)) if (cache.has(p)) now[p] = cache.get(p);
      deliver(now);
      queue = order.filter((x) => !(busyFull && x === busyWin) && range(x).some((p) => !cache.has(p)));
      if (!cache.has(w.page) && busyWin !== c) queue.unshift({ page: w.page });
      trim();
      pump();
    },
    drawn(m) {
      const got = {};
      for (const p in m.pages) got[p] = new Blob([m.pages[p]], { type: "image/jpeg" });
      if (m.gen !== gen) return;
      busyWin = null;
      stats.drawMs += performance.now() - drawT0;
      if (m.size === size) {
        for (const p in got) { cache.set(+p, got[p]); stats.drawn++; }
        deliver(got);
        if (id) LIB.pagesPut(id, size, got);
      }
      trim();
      pump();
      indicate();
    },
  };
})();
// The app comes back to where the reader was (SESSION): resuming holds the
// record while the book opens; resumeNote is said under the top bar's line once
// the chapter shows, and resumeTip in the slip under the bar for a few seconds.
let resuming = null, resumeNote = "", resumeWords = "", resumeTip = "";
function resumeStart(r) {
  resuming = r;
  document.body.classList.add("resuming");
  $("resume").querySelector("span").textContent = backTo(r) + ".";
  $("resume").hidden = false;
}
// the contents page of the resumed book showed: the chapter follows (the
// library posts it); the slip under the top bar says where the app came back to
function resumed(m) {
  const r = resuming;
  resuming = null;
  document.body.classList.remove("resuming");
  $("resume").hidden = true;
  if (m.title) SESSION.title(m.title);
  const words = backTo(SESSION.record() || r);
  if (m.restored) { $("took").textContent = words; resumeTip = words + "."; }
  else {
    // the book is read again: the words of the work start with them meanwhile
    resumeWords = words;
    $("took").textContent = words + ". Reading the book";
    resumeNote = words + (LIB.on ? ". The book is read again, because the app was closed before its reading was finished."
                                 : ". The book is read again, because this browser keeps no library.");
  }
  // the place itself opens with the book (the index message)
  return words;
}
$("resume").querySelector("button").addEventListener("click", () => { SESSION.clear(true); location.reload(); });
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
// On a phone, and a tablet held upright (the reader's compact layout), the top bar goes away
// while the reader scrolls down the page, and comes back only when the page is scrolled all the
// way to the top, or a new page shows at its top: a scroll up part of the way, to read a line
// again, leaves the reader's frame the room. A failure in the bar keeps it shown. Wider screens
// keep it: their reader has a panel beside the page, sized to the window.
const TOPBAR = (() => {
  // the top: within a few pixels of it, where a flick up may come to rest
  const TOP = 4;
  let lastY = 0, away = false;
  const phone = window.matchMedia("(max-width: 700px), (max-width: 1100px) and (orientation: portrait)");
  function set(a) {
    if (a === away) return;
    away = a;
    document.body.classList.toggle("topaway", a);
    $("top").style.marginTop = a ? -$("top").offsetHeight + "px" : "";
  }
  // a tablet turned sideways leaves the compact layout: the bar comes back at once, without
  // waiting for the next scroll
  phone.addEventListener && phone.addEventListener("change", () => { if (!phone.matches) set(false); });
  return {
    scrolled(y) {
      const d = y - lastY;
      if (!phone.matches) { set(false); lastY = y; return; }
      if (y <= TOP) set(false);
      else if (Math.abs(d) < 8) return;           // a small move changes nothing
      else if (d > 0 && y > 60 && !$("note").classList.contains("error")) set(true);
      lastY = y;
    },
    show() { set(false); lastY = 0; },
    away: () => away,
  };
})();
window.TOPBAR = TOPBAR;
window.addEventListener("message", (e) => {
  if (e.data && typeof e.data.scrollY === "number") {
    if (e.source === $("view").contentWindow) TOPBAR.scrolled(e.data.scrollY);
    return;
  }
  if (e.data && e.data.pictures) {
    // the reader shows a page: the pictures of its window and of the windows next to it
    PICS.want(e.data.pictures, e.source);
    prepare(e.data.pictures);
    return;
  }
  if (e.data && e.data.pictureShown) {
    if (swapping && e.source === swapping.frame.contentWindow) swapping.swap();
    return;
  }
  LIB.fromReader(e.data);
  if (e.data && (e.data.position || e.data.view)) { SESSION.soon(); return; }
  if (e.data && e.data.open === "index.html") {
    // the contents, on request: one tap (or the browser's back) comes back to the page
    showBack();
    openChapter = "index.html";
    SESSION.contents();
    if (!e.data.back) history.pushState({ contents: true }, "");
  }
  if (e.data && e.data.open && e.data.open !== "index.html" && prepared[e.data.open]) {
    // the chapter the reader turns to is built already: it shows at once
    const html = prepared[e.data.open];
    delete prepared[e.data.open];
    openChapter = e.data.open;
    hideBack();
    $("note").textContent = resumeNote || outdatedNote || "";
    resumeNote = "";
    show(e.data.open, e.data.hash, html);
    wantOpen = e.data.open;
    worker.postMessage({ type: "chapter", name: e.data.open, quiet: true });
    return;
  }
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
  wantOpen = e.data.open;
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
// partial: the gzipped parts of an earlier reading of the book that was cut short (the library's)
async function read(file, fileName, partial) {
  if (!file || busy) return;
  if (!ready) { status("The reader is still starting. Try again in a moment."); return; }
  busy = true;
  lastFile = file;
  lastName = fileName;
  $("again").hidden = true;
  working(true);
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
  const p = partial instanceof Uint8Array ? partial : null;
  worker.postMessage({ type: "process", name, bytes, selection: storedSelection(name),
    corrections: storedCorrections(name), partial: p }, p ? [bytes, p.buffer] : [bytes]);
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
$("another").addEventListener("click", () => { SESSION.clear(true); location.reload(); });
$("again").addEventListener("click", () => {
  if (!lastFile || busy) return;
  // the book opens again where the reader is now
  if (openChapter === "index.html") againPlace = backPlace;
  else {
    let v = null;
    try { const w = $("view").contentWindow; v = w && w.readerView ? w.readerView() : null; } catch (e) { v = null; }
    againPlace = v && v.page ? { chapter: openChapter, page: v.page, node: v.node || null } : null;
  }
  outdatedNote = "";
  hideBack();
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
SW.then(() => worker.postMessage({ type: "init", cfg: CFG }));
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


# Added to the Home Screen of an iPhone or iPad, the app opens on its own
# (without Safari's bars) and keeps its library apart from Safari, which may
# clear the storage of a site left unused for a week.
# The icons are the open book with two chequered pages (tools/make_icons.py
# renders them from web/icon.svg).
MANIFEST = {"name": "Chess Book Reader", "short_name": "Chess books", "start_url": "./", "scope": "./",
            "display": "standalone", "background_color": "#fbfbfa", "theme_color": "#fbfbfa",
            "icons": [{"src": "icon-180.png", "sizes": "180x180", "type": "image/png"},
                      {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
                       "purpose": "maskable"}]}
ICONS = ("icon-32.png", "icon-180.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png",
         "favicon.svg")


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
    for name in ICONS:
        shutil.copyfile(ROOT / "web" / "icons" / name, out / name)
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
    # The service worker (web/sw.js) keeps the libraries on the device: Pyodide's
    # folder and the wheels, whose names change with their versions.
    keep = [index_url] + ["wheels/"]
    digest = hashlib.sha256(json.dumps([index_url] + wheels).encode("utf-8")).hexdigest()[:12]
    sw = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
    keep_js = "[" + ", ".join(f"new URL({k!r}, self.registration.scope).href" for k in keep) + "]"
    (out / "sw.js").write_text(sw.replace("__CACHE__", "chessbook-libs-" + digest)
                               .replace("__KEEP__", keep_js), encoding="utf-8")
    # Wheel paths are made absolute against the site, because the worker
    # resolves them from its own location.
    cfg = ("{indexURL: new URL(%r, location.href).href, appZip: new URL('app.zip', location.href).href, "
           "wheels: %s.map(w => new URL(w, location.href).href), packages: %s, engine: %s}") % (
               index_url, wheels, PYODIDE_PACKAGES, engine)
    text = (SHELL.replace("__CSS__", style.page_css() + style.BOOK_CSS).replace("__CFG__", cfg)
            .replace("__BOOK_SMALL__", style.book_svg())
            .replace("__BOOK__", style.book_svg(label="The program is at work")))
    (out / "index.html").write_text(text, encoding="utf-8")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"Site written to {out} ({size / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
