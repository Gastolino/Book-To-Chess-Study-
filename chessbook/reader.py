"""The interactive book reader: an index page and one page per chapter.

build_reader(book, pdf_path, out_dir) writes, from an assembled book
(assemble.build_book) and its PDF:

    out_dir/index.html    contents, page thumbnails with checkboxes to include
                          or exclude chapters, pages and diagrams, a larger
                          preview of every diagram, the counts of what was
                          extracted, and the selection to copy back
    out_dir/chNN.html     one self-contained reader per chapter: the book page
                          with clickable boxes over every move and diagram,
                          and a live board with the move tree beside it

Every file is self-contained: page images are embedded as base64 JPEG, the
board is drawn as SVG with python-chess's piece drawings, and no file loads
anything from the network.

Changes to the selection made on the index or in a chapter reader are kept
in the browser (localStorage, one entry per book) until the reader copies
them into the chat; both kinds of page read and write the same entry, so a
change survives moving between them. The entry is dropped when the program
has since been run with another selection.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path

import chess.svg
import pymupdf

from . import pgnout
from .selection import EXCLUDED_KINDS

PAGE_DPI = 120
PAGE_QUALITY = 60
THUMB_DPI = 40
THUMB_QUALITY = 50
CROP_DPI = 60
CROP_QUALITY = 45
MAX_BYTES = 15 * 1024 * 1024
TARGET_BYTES = 14 * 1024 * 1024

STATUS_WORDS = {
    "ok": "read with no doubt",
    "guessed": "chosen by the moves that follow",
    "ambiguous": "one of several equally good readings",
    "failed": "not readable",
    "inserted": "missing from the text and supplied by the program",
    "waiting": "waiting for the diagram position (Stage 3)",
    "unattached": "not placed in any line",
}

# What each kind of picture is, in words for the reader.
KIND_WORDS = {
    "board": "a whole board",
    "board_plus": "a board with text or another board printed in the same picture",
    "partial": "part of a board only",
    "illustration": "a drawing rather than a board",
    "icon": "an ornament rather than a board",
    "front": "a picture before the first chapter",
}
NOT_A_POSITION = ("illustration", "icon", "front")


# ---------------------------------------------------------------- images

def page_jpeg(doc, page, dpi, quality, clip=None):
    pix = doc[page - 1].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY,
                                   clip=pymupdf.Rect(clip) if clip else None)
    return pix.tobytes("jpg", jpg_quality=quality)


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _plural(k, one, many=None):
    return f"{k} {one if k == 1 else (many or one + 's')}"


def _selection_base(book):
    """A short fingerprint of the selection a build used: an edit stored in
    the browser applies only to the build it was made against."""
    sel = book.get("selection") or {}
    text = json.dumps({"pages": sel.get("pages"), "diagrams": sel.get("diagrams")},
                      sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- shared style

BASE_CSS = r"""
:root{--bg:#f7f5f0;--fg:#1f2328;--muted:#555e68;--card:#ffffff;--line:#d5d0c4;
--accent:#1f5bc4;--ok:#1e7f43;--amber:#9a6200;--bad:#c62828;--wait:#5f6b76;--unatt:#7d3c98;
--diag:#2f6fdf;--labelbg:#2457b8;--hl:#ffe08a;--light:#f0d9b5;--dark:#b58863;--coord:#6b5a43;
--btn:#ece7dc;--btnfg:#1f2328;--warnbg:#fff1c2;--shadow:0 1px 3px rgba(0,0,0,.12)}
@media (prefers-color-scheme:dark){:root{--bg:#16181b;--fg:#e4e6e8;--muted:#a9b1ba;
--card:#202328;--line:#3a3f46;--accent:#8ab4ff;--ok:#4cd486;--amber:#f5c04a;--bad:#ff7b7b;
--wait:#aab3bd;--unatt:#cf9cf0;--diag:#7aa7ff;--labelbg:#2f5fbf;--hl:#6b5a1a;--light:#d9c4a0;
--dark:#a07a55;--coord:#c9b79a;--btn:#2c3036;--btnfg:#e4e6e8;--warnbg:#4a3d10;
--shadow:0 1px 3px rgba(0,0,0,.5)}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
overflow-x:hidden}
a{color:var(--accent)}
button,select,input{font:inherit;color:var(--btnfg)}
button{background:var(--btn);border:1px solid var(--line);border-radius:6px;padding:5px 10px;
cursor:pointer}
button:hover{border-color:var(--accent)}
button:disabled{opacity:.55;cursor:default}
button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--accent);
outline-offset:1px}
select,input[type=number]{background:var(--card);border:1px solid var(--line);border-radius:6px;
padding:4px 6px}
.wrap{max-width:1500px;margin:0 auto;padding:12px 16px 40px}
h1{font-size:1.5rem;margin:.2em 0 .4em;line-height:1.25}
h2{font-size:1.2rem;margin:1.2em 0 .4em}
.muted{color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:.85rem;color:var(--muted);margin:6px 0}
.legend span{display:inline-flex;align-items:center;gap:5px}
.sw{display:inline-block;width:14px;height:10px;border:2px solid;border-radius:2px}
.sw.ok{border-color:var(--ok)}.sw.amber{border-color:var(--amber)}.sw.bad{border-color:var(--bad)}
.sw.wait{border-color:var(--wait)}.sw.dg{border-color:var(--diag)}
.sw.unatt{border-color:var(--unatt);border-style:dashed}
.notice{background:var(--warnbg);border:1px solid var(--line);border-radius:6px;padding:6px 10px;
margin:6px 0;font-size:.9rem}
.touch{display:none}
@media (hover:none) and (pointer:coarse){.touch{display:block}.mouse{display:none}}
"""

# The selection model shared by the index and the chapter readers.
SELECTION_JS = r"""
function makeSelection(S0, opts){
  // S0: the selection the build used ({pages:{exclude}, diagrams:{exclude, include}}).
  const key = "chessbook-selection:" + opts.pdf + ":" + opts.pageCount;
  const kinds = opts.kinds || {};
  const offKinds = opts.excludedKinds || [];
  function fresh(src){
    return {pagesOff: (src.pages && src.pages.exclude || []).map(r => [r[0], r[1]]),
            exclude: new Set(src.diagrams && src.diagrams.exclude || []),
            include: new Set(src.diagrams && src.diagrams.include || [])};
  }
  let st = fresh(S0), stored = false;
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const v = JSON.parse(raw);
      if (v && v.base === opts.base && v.selection) { st = fresh(v.selection); stored = true; }
      else localStorage.removeItem(key);
    }
  } catch (e) { stored = false; }
  function idKey(id){
    const m = /^p(\d+)-(\d+)([a-z]?)$/.exec(id) || [0, 1e9, 0, ""];
    return [parseInt(m[1], 10), parseInt(m[2], 10), m[3]];
  }
  function cmp(a, b){
    const x = idKey(a), y = idKey(b);
    return x[0] - y[0] || x[1] - y[1] || (x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0);
  }
  function parentOf(id){ const m = /^(p\d+-\d+)[a-z]$/.exec(id); return m ? m[1] : null; }
  const api = {
    pageOn(p){ return !st.pagesOff.some(r => r[0] <= p && p <= r[1]); },
    diagOwn(id){
      if (st.include.has(id)) return true;
      const par = parentOf(id);
      return !(st.exclude.has(id) || (par && st.exclude.has(par)));
    },
    diagOn(id){ const m = /^p(\d+)-/.exec(id); return api.pageOn(parseInt(m[1], 10)) && api.diagOwn(id); },
    setPages(a, b, on){
      const off = new Set();
      for (const r of st.pagesOff) for (let p = r[0]; p <= r[1]; p++) off.add(p);
      for (let p = a; p <= b; p++) { if (on) off.delete(p); else off.add(p); }
      const list = Array.from(off).sort((x, y) => x - y), out = [];
      for (const p of list) {
        if (out.length && out[out.length - 1][1] === p - 1) out[out.length - 1][1] = p;
        else out.push([p, p]);
      }
      st.pagesOff = out; api.save();
    },
    setDiag(id, on){
      if (on) {
        st.exclude.delete(id);
        const par = parentOf(id);
        if (offKinds.indexOf(kinds[id]) >= 0 || (par && st.exclude.has(par))) st.include.add(id);
      } else { st.include.delete(id); st.exclude.add(id); }
      api.save();
    },
    object(note){
      return {version: 1, pages: {exclude: st.pagesOff.map(r => [r[0], r[1]])},
              diagrams: {exclude: Array.from(st.exclude).sort(cmp),
                         include: Array.from(st.include).sort(cmp)},
              note: note || ("Selection made in the book reader of " + opts.title + ".")};
    },
    text(){ return JSON.stringify(api.object(), null, 1); },
    changed(){
      const a = api.object(""), b = makeSelection.canon(S0);
      return JSON.stringify(a.pages) !== JSON.stringify(b.pages) ||
        JSON.stringify(a.diagrams) !== JSON.stringify(b.diagrams);
    },
    save(){
      stored = api.changed();
      try {
        if (stored) localStorage.setItem(key, JSON.stringify({base: opts.base, selection: api.object()}));
        else localStorage.removeItem(key);
      } catch (e) { /* the browser keeps no storage: the change lives in this page only */ }
    },
    reset(){ st = fresh(S0); api.save(); },
    stored(){ return stored; },
    cmp: cmp
  };
  return api;
}
makeSelection.canon = function(S0){
  const sortIds = (l) => Array.from(l || []).sort((a, b) => {
    const k = (id) => { const m = /^p(\d+)-(\d+)([a-z]?)$/.exec(id) || [0, 1e9, 0, ""];
      return [parseInt(m[1], 10), parseInt(m[2], 10), m[3]]; };
    const x = k(a), y = k(b);
    return x[0] - y[0] || x[1] - y[1] || (x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0);
  });
  return {pages: {exclude: (S0.pages && S0.pages.exclude || []).map(r => [r[0], r[1]])},
          diagrams: {exclude: sortIds(S0.diagrams && S0.diagrams.exclude),
                     include: sortIds(S0.diagrams && S0.diagrams.include)}};
};
"""

# ---------------------------------------------------------------- chapter page

CHAPTER_CSS = r"""
.top{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px;margin-bottom:6px}
.top h1{flex:1 1 300px;margin:0}
.top .book{flex-basis:100%;font-size:.9rem;color:var(--muted)}
.help{font-size:.9rem;color:var(--muted);margin:0 0 8px;max-width:80ch}
.help p{margin:.3em 0}
.reader{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(330px,.85fr);gap:16px;
align-items:start}
.pagecol{min-width:0}
.pagenav{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:8px}
.pagenav input[type=number]{width:5.5em}
.pagenav .pinfo{font-size:.85rem;color:var(--muted)}
.pagenav label.use{font-size:.85rem;display:inline-flex;align-items:center;gap:4px}
.pagescroll{width:100%;overflow-x:auto}
.pagebox{position:relative;width:100%;background:#fff;box-shadow:var(--shadow);
border:1px solid var(--line)}
.pagescroll.zoom .pagebox{width:200%}
.pagebox img{display:block;width:100%;height:auto;user-select:none}
.ov{position:absolute;inset:0}
.mark,.diag{position:absolute;padding:0;margin:0;border-radius:2px;background:transparent;
cursor:pointer;min-width:0;min-height:0}
.diag{border:2px solid var(--diag);background:rgba(47,111,223,.04);z-index:1}
.mark{border:2px solid var(--wait);background:rgba(125,133,143,.08);z-index:2}
.mark.st-ok{border-color:var(--ok);background:rgba(30,158,74,.08)}
.mark.st-guessed,.mark.st-ambiguous,.mark.st-inserted{border-color:var(--amber);
background:rgba(208,138,0,.10)}
.mark.st-failed{border-color:var(--bad);background:rgba(211,58,58,.10)}
.mark.st-unattached{border:2px dashed var(--unatt);background:rgba(155,89,182,.06)}
.mark.current{background:rgba(255,200,0,.22);outline:2px solid var(--accent);outline-offset:1px;
z-index:3}
.diag.excluded{border-color:var(--wait);
background:repeating-linear-gradient(45deg,rgba(125,133,143,.32) 0 6px,transparent 6px 12px)}
.diag.current{outline:3px solid var(--accent)}
.diag .dl{position:absolute;left:0;top:-1.5em;font-size:11px;line-height:1.2;
background:var(--labelbg);color:#fff;padding:1px 4px;border-radius:3px;white-space:nowrap}
.diag.excluded .dl{background:#4b545d}
.offpage{display:none}
.offpage.on{display:block}
.panel{position:sticky;top:8px;max-height:calc(100vh - 16px);overflow:auto;background:var(--card);
border:1px solid var(--line);border-radius:8px;padding:10px;box-shadow:var(--shadow);min-width:0}
.panel h2{font-size:1.05rem;margin:2px 0 6px}
.linepick{display:flex;gap:6px;align-items:center}
.linepick select{flex:1;min-width:0;max-width:100%}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0}
#chips{max-height:96px;overflow:auto}
.chip{font-size:.8rem;padding:2px 8px;border-radius:12px}
.chip.on{border-color:var(--accent);background:var(--hl)}
.badge{display:inline-block;font-size:.75rem;padding:1px 7px;border-radius:10px;
border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.badge.st-ok{color:var(--ok);border-color:var(--ok)}
.badge.st-failed{color:var(--bad);border-color:var(--bad)}
.badge.st-guessed,.badge.st-ambiguous,.badge.st-inserted{color:var(--amber);border-color:var(--amber)}
.boardwrap{position:relative;width:100%;max-width:440px;margin:6px auto}
.boardwrap svg{display:block;width:100%;height:auto}
.boardwrap canvas{display:block;width:100%;height:auto;border:1px solid var(--line)}
.boardnote{font-size:.85rem;color:var(--muted);margin:4px 0 0;text-align:center}
.controls{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin:6px 0}
.controls button{min-width:44px}
.info{font-size:.92rem;border-top:1px solid var(--line);padding-top:6px;margin-top:4px}
.info .cur{font-weight:600}
.comment{white-space:pre-wrap;margin:4px 0}
.tree{font-size:.95rem;line-height:1.7;border-top:1px solid var(--line);margin-top:6px;
padding-top:6px;max-height:40vh;overflow:auto;overflow-wrap:anywhere}
.mv{cursor:pointer;padding:0 2px;border-radius:3px;white-space:nowrap}
.mv:hover{background:var(--btn)}
.mv.ml{font-weight:700}
.mv.cur{background:var(--hl);outline:1px solid var(--accent)}
.mv.st-guessed,.mv.st-ambiguous,.mv.st-inserted{color:var(--amber)}
.mv.st-failed{color:var(--bad);text-decoration:underline dotted}
.mv.st-waiting{color:var(--wait)}
.mv.hc{border-bottom:1px dotted var(--muted)}
.var{color:var(--muted)}
.var .mv{color:var(--fg)}
.var .mv.st-waiting{color:var(--wait)}
.varblock{display:block;margin:2px 0 2px 1.1em;padding-left:.5em;border-left:2px solid var(--line)}
.dpanel{border:1px solid var(--line);border-radius:6px;padding:8px;margin:8px 0;background:var(--bg)}
.dpanel canvas{display:block;max-width:100%;margin:6px auto;border:1px solid var(--line)}
.dpanel .x{float:right}
.foot{margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.mbar,.mini{display:none}
@media (max-width:900px){.reader{grid-template-columns:minmax(0,1fr)}
.panel{position:static;max-height:none}.tree{max-height:60vh}
body{padding-bottom:60px}
.mbar{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:10;gap:6px;align-items:center;
padding:6px 10px;background:var(--card);border-top:1px solid var(--line);box-shadow:var(--shadow)}
.mbar .mtxt{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
font-weight:600}
.mini.on{display:block;position:fixed;right:8px;bottom:58px;z-index:9;width:min(46vw,240px);
background:var(--card);border:1px solid var(--line);border-radius:6px;box-shadow:var(--shadow);
padding:3px}
.mini svg,.mini canvas{display:block;width:100%;height:auto}
.mini .mnote{font-size:.75rem;color:var(--muted);text-align:center;margin:2px 0 0}}
@media (max-width:600px){.mark,.mark.st-unattached{border-width:1px;background:transparent}
.mark.current{background:rgba(255,200,0,.18)}}
"""

CHAPTER_JS = r"""
(function(){
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const IMG = JSON.parse(document.getElementById("images").textContent);
window.READER = D;
const $ = (id) => document.getElementById(id);
const S = {page: null, node: null, line: null, flip: false, diagram: null, mini: null};
const imgCache = {};
const SMALL = window.matchMedia("(max-width:900px)");
window.readerState = {fen: null, nodeId: null, page: null};
const kinds = {};
for (const p in D.pages) for (const d of D.pages[p].diagrams) kinds[d.id] = d.kind;
const SEL = makeSelection(D.selection, {pdf: D.book.pdf, pageCount: D.pageCount, base: D.selBase,
  kinds: kinds, excludedKinds: D.excludedKinds, title: D.book.title});

function esc(t){ return String(t == null ? "" : t).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }
function shown(raw){ return String(raw || "").replace(/[\u0000-\u001f]/g, "▫"); }
function cap(t){ t = String(t || ""); return t.charAt(0).toUpperCase() + t.slice(1); }
function pageImage(p){
  if (!imgCache[p]) { const im = new Image(); im.src = "data:image/jpeg;base64," + IMG[p]; imgCache[p] = im; }
  return imgCache[p];
}
function pageName(p){
  const P = D.pages[p];
  return P && P.folio ? "page " + P.folio : "PDF page " + p;
}
function nodeFen(id){ const n = D.nodes[id]; return n && n.fen ? n.fen : null; }
function moveLabel(id){
  const n = D.nodes[id];
  return n.parent == null ? "Start position" : moveText(id, true);
}
function setState(){
  window.readerState = {fen: S.node ? nodeFen(S.node) : null, nodeId: S.node, page: S.page};
  if (S.diagram) window.readerState.diagram = S.diagram;
  const t = $("mtxt");
  if (t) t.textContent = S.node ? moveLabel(S.node) + (S.line ? " · " + D.lines[S.line].title : "") :
    "No move chosen";
}

/* ---------------------------------------------------------------- page */
function chapterFor(p){
  for (const c of D.chapters) if (p >= c.start && p <= c.end) return c;
  return null;
}
function say(msg){ const el = $("pagemsg"); el.textContent = msg || ""; }
function goPage(p, keepHash){
  p = parseInt(p, 10);
  if (isNaN(p) || p < 1 || p > D.pageCount) {
    say("The book has PDF pages 1 to " + D.pageCount + ", so the program shows page " + S.page + " again.");
    $("pagenum").value = S.page;
    return;
  }
  say("");
  if (!(p in D.pages)) {
    const c = chapterFor(p);
    if (c && c.file && !c.empty) { location.href = c.file + "#page=" + p; }
    return;
  }
  showPage(p);
  if (!keepHash) history.replaceState(null, "", "#page=" + p);
}
function pct(v, total){ return (100 * v / total).toFixed(3) + "%"; }
function diagramName(d, p){
  if (d.label) return "Diagram " + d.label;
  const k = (d.id.split("-")[1] || "");
  return "Unnumbered diagram " + k + " on " + pageName(p);
}
function showPage(p){
  const P = D.pages[p];
  S.page = p;
  const img = $("pageimg");
  img.src = "data:image/jpeg;base64," + IMG[p];
  img.alt = "Page " + p + " of the book";
  $("pagebox").style.aspectRatio = P.w + " / " + P.h;
  const ov = $("ov");
  ov.innerHTML = "";
  for (const d of P.diagrams) {
    const b = document.createElement("button");
    const on = SEL.diagOn(d.id);
    b.className = "diag" + (on ? "" : " excluded");
    b.dataset.diagram = d.id;
    const r = d.rect;
    b.style.left = pct(r[0], P.w); b.style.top = pct(r[1], P.h);
    b.style.width = pct(r[2] - r[0], P.w); b.style.height = pct(r[3] - r[1], P.h);
    b.title = diagramName(d, p) + (on ? "" : ", left out of the selection");
    b.innerHTML = "<span class=dl>" + esc(d.label || "no number") + "</span>";
    b.setAttribute("aria-label", b.title);
    ov.appendChild(b);
  }
  P.marks.forEach((m, i) => {
    const b = document.createElement("button");
    b.className = "mark st-" + m.status;
    const x = m.bbox;
    const pad = 1.0;
    b.style.left = pct(x[0] - pad, P.w); b.style.top = pct(x[1] - pad, P.h);
    b.style.width = pct(x[2] - x[0] + 2 * pad, P.w); b.style.height = pct(x[3] - x[1] + 2 * pad, P.h);
    if (m.node) b.dataset.node = m.node;
    b.dataset.mark = i;
    const n = m.node ? D.nodes[m.node] : null;
    let t = n ? (n.san || n.assumed || "“" + shown(m.raw) + "”") : "“" + shown(m.raw) + "”";
    t += ": " + (D.words[m.status] || m.status);
    if (m.reason) t += ", because " + m.reason;
    t += ".";
    b.title = t;
    b.setAttribute("aria-label", t);
    ov.appendChild(b);
  });
  $("pagenum").value = p;
  $("pageinfo").textContent = (P.folio ? "Printed page " + P.folio + ". " : "") +
    "This chapter holds PDF pages " + D.chapter.start + " to " + D.chapter.end + ".";
  $("prevpage").disabled = p <= 1;
  $("nextpage").disabled = p >= D.pageCount;
  $("usepage").checked = SEL.pageOn(p);
  $("offpage").classList.toggle("on", !SEL.pageOn(p) || !P.selected);
  $("offpage").textContent = !P.selected ?
    "The program left this page out when it read the book, so it shows no moves here. " +
    (SEL.pageOn(p) ? "You have ticked it again; the next run will read it." : "") :
    (SEL.pageOn(p) ? "" : "You have left this page out. The program still shows what it read here, " +
     "and the next run will leave the page out.");
  renderChips();
  highlightMark(false);
  if (S.diagram && !P.diagrams.some(d => d.id === S.diagram)) closeDiagram();
  setState();
}

function renderChips(){
  const box = $("chips");
  const ids = D.lineOrder.filter(id => {
    const L = D.lines[id]; return L.page <= S.page && S.page <= L.end_page;
  });
  box.innerHTML = ids.length ? "<span class=muted style='font-size:.8rem'>Lines on this page:</span>" : "";
  for (const id of ids) {
    const L = D.lines[id];
    const b = document.createElement("button");
    b.className = "chip" + (S.line === id ? " on" : "");
    b.textContent = L.title;
    b.title = "Show the line " + L.title;
    b.addEventListener("click", () => selectNode(L.root, {}));
    box.appendChild(b);
  }
}

function highlightMark(scroll){
  for (const el of document.querySelectorAll(".mark.current")) el.classList.remove("current");
  if (!S.node) return;
  let first = null;
  for (const el of document.querySelectorAll(".mark[data-node='" + S.node + "']")) {
    el.classList.add("current"); if (!first) first = el;
  }
  if (first && scroll) first.scrollIntoView({block: "nearest", inline: "nearest"});
}

/* ---------------------------------------------------------------- board */
const SQ = 45, M = 16;
function boardSvg(fen, flip, uci){
  const rows = fen.split(" ")[0].split("/");
  const size = 8 * SQ + 2 * M;
  let s = "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' " +
    "viewBox='0 0 " + size + " " + size + "' role='img' aria-label='Chess board: " + esc(fen) + "'>";
  s += "<rect x='0' y='0' width='" + size + "' height='" + size + "' fill='var(--card)'/>";
  let hl = {};
  if (uci && uci.length >= 4) { hl[uci.slice(0, 2)] = 1; hl[uci.slice(2, 4)] = 1; }
  for (let i = 0; i < 8; i++) {
    for (let f = 0; f < 8; f++) {
      const rank = 7 - i;
      const x = M + (flip ? 7 - f : f) * SQ, y = M + (flip ? 7 - i : i) * SQ;
      const name = "abcdefgh"[f] + (rank + 1);
      const light = (f + rank) % 2 === 1;
      s += "<rect x='" + x + "' y='" + y + "' width='" + SQ + "' height='" + SQ + "' fill='" +
        (light ? "var(--light)" : "var(--dark)") + "'/>";
      if (hl[name]) s += "<rect x='" + x + "' y='" + y + "' width='" + SQ + "' height='" + SQ +
        "' fill='rgba(255,210,0,.45)'/>";
    }
  }
  const names = {p:"pawn", n:"knight", b:"bishop", r:"rook", q:"queen", k:"king"};
  rows.forEach((row, i) => {
    let f = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) { f += parseInt(ch, 10); continue; }
      const color = ch === ch.toUpperCase() ? "white" : "black";
      const x = M + (flip ? 7 - f : f) * SQ, y = M + (flip ? 7 - i : i) * SQ;
      s += "<use href='#" + color + "-" + names[ch.toLowerCase()] + "' xlink:href='#" + color + "-" +
        names[ch.toLowerCase()] + "' transform='translate(" + x + "," + y + ")'/>";
      f += 1;
    }
  });
  for (let k = 0; k < 8; k++) {
    const file = "abcdefgh"[flip ? 7 - k : k];
    const rank = flip ? k + 1 : 8 - k;
    s += "<text x='" + (M + k * SQ + SQ / 2) + "' y='" + (size - 4) + "' font-size='11' " +
      "text-anchor='middle' fill='var(--coord)'>" + file + "</text>";
    s += "<text x='" + (M / 2) + "' y='" + (M + k * SQ + SQ / 2 + 4) + "' font-size='11' " +
      "text-anchor='middle' fill='var(--coord)'>" + rank + "</text>";
  }
  return s + "</svg>";
}
function diagramInfo(id){
  for (const p in D.pages) for (const d of D.pages[p].diagrams) if (d.id === id) return [parseInt(p, 10), d];
  return [null, null];
}
function cropInto(canvas, id, maxW){
  const [p, d] = diagramInfo(id);
  if (!d) return false;
  const P = D.pages[p];
  const im = pageImage(p);
  const draw = () => {
    const k = im.naturalWidth / P.w;
    const r = d.rect;
    const sw = (r[2] - r[0]) * k, sh = (r[3] - r[1]) * k;
    canvas.width = Math.round(sw); canvas.height = Math.round(sh);
    canvas.getContext("2d").drawImage(im, r[0] * k, r[1] * k, sw, sh, 0, 0, sw, sh);
    if (maxW) canvas.style.maxWidth = maxW;
  };
  if (im.complete && im.naturalWidth) draw(); else im.addEventListener("load", draw, {once: true});
  return true;
}
function diagramLabel(id){
  const [p, d] = diagramInfo(id);
  if (!d) return id;
  return d.label ? "Diagram " + d.label : "the unnumbered diagram on " + pageName(p);
}
function boardFor(){
  // [kind, html or diagram id, note]
  const n = S.node ? D.nodes[S.node] : null;
  const fen = n ? nodeFen(S.node) : null;
  if (fen) return ["svg", boardSvg(fen, S.flip, n.uci),
    (fen.split(" ")[1] === "w" ? "White" : "Black") + " is to move."];
  const L = S.line ? D.lines[S.line] : null;
  if (n && n.reason) return ["empty", null, n.reason];
  if (L && L.diagram) return ["crop", L.diagram, "This line starts from " + diagramLabel(L.diagram) +
    ". Board reading (Stage 3) has not run yet, so the picture from the book stands in for the board. " +
    "Stage 3 will read the pieces from the diagram picture."];
  return ["empty", null, "The board shows a position once you choose a move on the page or in the list."];
}
function renderBoard(){
  const [kind, x, note] = boardFor();
  const box = $("board");
  if (kind === "svg") box.innerHTML = x;
  else if (kind === "crop") {
    box.innerHTML = "<canvas aria-label='Diagram picture from the book'></canvas>";
    cropInto(box.querySelector("canvas"), x);
  } else box.innerHTML = boardSvg("8/8/8/8/8/8/8/8 w - - 0 1", S.flip, null);
  $("boardnote").textContent = note;
  renderMini(kind, x);
}
function renderMini(kind, x){
  const mini = $("mini");
  if (!SMALL.matches) { mini.classList.remove("on"); return; }
  const want = S.mini === null ? !!S.node : S.mini;
  mini.classList.toggle("on", want && kind !== "empty");
  $("mboard").setAttribute("aria-pressed", String(want));
  if (!want) return;
  const box = $("minibox");
  if (kind === "svg") box.innerHTML = x;
  else if (kind === "crop") {
    box.innerHTML = "<canvas aria-label='Diagram picture from the book'></canvas>";
    cropInto(box.querySelector("canvas"), x);
  } else box.innerHTML = "";
  $("mininote").textContent = S.node ? moveLabel(S.node) : "";
}

/* ---------------------------------------------------------------- moves */
function cont(id){
  // the move that continues the line from this node
  const n = D.nodes[id];
  if (!n) return null;
  if (n.main) { for (const c of n.children) if (D.nodes[c].main) return c; return null; }
  return n.children.length ? n.children[0] : null;
}
function siblings(id){
  const n = D.nodes[id];
  return n && n.parent != null ? D.nodes[n.parent].children : [id];
}
function moveText(id, needNumber){
  const n = D.nodes[id];
  let num = "";
  if (n.number != null && (needNumber || !n.black)) num = n.number + (n.black ? "..." : ".");
  let t;
  if (n.san) t = n.san;
  else if (n.status === "failed") t = n.assumed ? n.assumed + "?" : (n.raw ? shown(n.raw) + "?" : "…");
  else t = shown(n.raw);
  return num + t;
}
function mvSpan(id, needNumber, mainline){
  const n = D.nodes[id];
  let cls = "mv st-" + n.status + (mainline ? " ml" : "") + (n.comment ? " hc" : "");
  let title = cap(D.words[n.status] || n.status);
  if (n.status === "failed" && n.assumed) title += "; the program assumed " + n.assumed;
  if (n.raw) title += "; the text recognition read “" + shown(n.raw) + "”";
  if (n.reason) title += ". " + n.reason;
  return "<span class='" + cls + "' data-node='" + id + "' title='" + esc(title) + "'>" +
    esc(moveText(id, needNumber)) + "</span>";
}
function renderLine(nodeId, needNumber, mainline, depth){
  let out = [];
  let id = nodeId;
  let need = needNumber;
  while (id) {
    const c = cont(id);
    const others = D.nodes[id].children.filter(x => x !== c);
    if (c) { out.push(mvSpan(c, need, mainline)); need = false; }
    for (const v of others) {
      const body = mvSpan(v, true, false) + " " + renderLine(v, false, false, depth + 1);
      out.push(depth === 0 ? "<span class='var varblock'>" + body + "</span>" :
        "<span class=var>(" + body + ")</span>");
      need = true;
    }
    id = c;
  }
  return out.join(" ");
}
function renderTree(){
  const L = S.line ? D.lines[S.line] : null;
  const box = $("tree");
  if (!L) { box.innerHTML = "<span class=muted>No line is chosen yet.</span>"; return; }
  const root = D.nodes[L.root];
  const first = root.children.length ? "" : "<span class=muted>This line holds no moves.</span>";
  box.innerHTML = "<span class='mv" + (S.node === L.root ? " cur" : "") + "' data-node='" + L.root +
    "' title='Start position'>Start</span> " + renderLine(L.root, true, true, 0) + first;
  $("linetitle").textContent = L.title;
  const st = $("linestatus");
  st.className = "badge st-" + L.status;
  st.textContent = D.lineWords[L.status] || L.status;
  $("linesel").value = L.id;
  const meta = [];
  if (L.section) meta.push(L.section);
  const a = pageName(L.page), b = pageName(L.end_page);
  meta.push(L.end_page !== L.page ? "from " + a + " to " + b : "on " + a);
  if (L.diagram) meta.push("starts from " + diagramLabel(L.diagram));
  if (L.result) meta.push("result " + L.result);
  $("linemeta").textContent = cap(meta.join(" · "));
}
function markTreeCurrent(scroll){
  for (const el of document.querySelectorAll("#tree .mv.cur")) el.classList.remove("cur");
  const el = document.querySelector("#tree .mv[data-node='" + S.node + "']");
  if (!el) return;
  el.classList.add("cur");
  if (!scroll) return;
  // scroll the move list inside its own box, never the window
  const box = $("tree");
  if (box.scrollHeight > box.clientHeight) {
    const top = el.offsetTop - box.offsetTop;
    if (top < box.scrollTop || top > box.scrollTop + box.clientHeight - 24)
      box.scrollTop = Math.max(0, top - box.clientHeight / 3);
  }
}
function renderInfo(){
  const n = S.node ? D.nodes[S.node] : null;
  const box = $("info");
  if (!n) { box.innerHTML = ""; return; }
  const L = D.lines[n.line];
  let h = "";
  if (S.node === L.root || n.parent == null) {
    h += "<div class=cur>Start position" + (L.start_fen ? "" : " (from the diagram)") + "</div>";
  } else {
    h += "<div class=cur>" + esc(moveText(S.node, true)) + " <span class='badge st-" + esc(n.status) +
      "'>" + esc(D.words[n.status] || n.status) + "</span></div>";
    if (n.raw) h += "<div class=muted>The text recognition read “" + esc(shown(n.raw)) + "”.</div>";
    if (n.status === "failed" && n.raw)
      h += "<div class=muted>" + (n.assumed ? "The program assumed " + esc(n.assumed) +
        " here so that the line could go on." : "The program could not read this move.") + "</div>";
    if (n.reason) h += "<div class=muted>" + esc(n.reason) + "</div>";
    if (n.alternatives && n.alternatives.length && n.status !== "ok")
      h += "<div class=muted>The other possible readings are " + esc(n.alternatives.join(", ")) + ".</div>";
    const sib = siblings(S.node);
    if (sib.length > 1) h += "<div class=muted>The book gives " + sib.length +
      " moves here; the up and down arrow keys switch between them.</div>";
  }
  if (n.comment) h += "<div class=comment>" + esc(n.comment) + "</div>";
  box.innerHTML = h;
}

function selectNode(id, opts){
  opts = opts || {};
  const n = D.nodes[id];
  if (!n) return;
  const lineChanged = S.line !== n.line;
  S.node = id; S.line = n.line;
  const L = D.lines[n.line];
  const target = n.page || L.page;
  if (target && target !== S.page && (target in D.pages)) showPage(target);
  if (lineChanged) { renderTree(); renderChips(); }
  markTreeCurrent(opts.scrollTree !== false);
  renderBoard();
  renderInfo();
  highlightMark(!!opts.scrollPage);
  history.replaceState(null, "", "#node=" + id);
  setState();
}
function firstLineHere(){
  return D.lineOrder.find(id => D.lines[id].page <= S.page && S.page <= D.lines[id].end_page) ||
    D.lineOrder[0];
}
function step(dir){
  if (!S.node) {
    const lid = S.line || firstLineHere();
    if (lid) selectNode(D.lines[lid].root, {scrollPage: true});
    return;
  }
  const n = D.nodes[S.node];
  if (dir < 0 && n.parent != null) selectNode(n.parent, {scrollPage: true});
  if (dir > 0) { const c = cont(S.node); if (c) selectNode(c, {scrollPage: true}); }
}
function sideStep(dir){
  if (!S.node) return;
  const sib = siblings(S.node);
  const k = sib.indexOf(S.node);
  const j = k + dir;
  if (j >= 0 && j < sib.length) selectNode(sib[j], {scrollPage: true});
}
function toEnd(dir){
  if (!S.line) S.line = firstLineHere();
  if (!S.line) return;
  if (dir < 0) { selectNode(D.lines[S.line].root, {scrollPage: true}); return; }
  let id = S.node || D.lines[S.line].root;
  let c;
  while ((c = cont(id))) id = c;
  selectNode(id, {scrollPage: true});
}

/* ---------------------------------------------------------------- diagrams */
function showDiagram(id){
  const [p, d] = diagramInfo(id);
  if (!d) return;
  S.diagram = id;
  for (const el of document.querySelectorAll(".diag.current")) el.classList.remove("current");
  const el = document.querySelector(".diag[data-diagram='" + id + "']");
  if (el) el.classList.add("current");
  // the board shows this diagram's first line, or nothing
  S.node = null;
  S.line = (d.lines && d.lines.find(l => D.lines[l])) || null;
  if (S.line) { renderTree(); renderChips(); } else { $("tree").innerHTML = "";
    $("linetitle").textContent = "No line chosen"; $("linestatus").textContent = "";
    $("linestatus").className = "badge"; $("linemeta").textContent = ""; }
  renderBoard(); renderInfo(); highlightMark(false);
  const box = $("dpanel");
  const on = SEL.diagOn(id);
  let h = "<button class=x id=dclose aria-label='Close the diagram panel'>Close</button>";
  h += "<h2>" + esc(d.label ? "Diagram " + d.label : "Unnumbered diagram") + " <span class=muted>(" +
    esc(pageName(p)) + ")</span></h2>";
  h += "<canvas aria-label='Diagram picture from the book'></canvas>";
  h += "<p><label><input type=checkbox id=usediag" + (on ? " checked" : "") + "> Use this diagram</label> " +
    "<span class=muted>" + esc(cap(D.kindWords[d.kind] || "")) + ".</span></p>";
  if (!d.selected) h += "<p>The program left this diagram out when it read the book.</p>";
  if (D.notPosition.indexOf(d.kind) >= 0) {
    h += "<p>The program takes this picture for something other than a chess position, so no line " +
      "starts from it.</p>";
  } else if (d.fen) h += "<p>Stage 3 read this position as <code>" + esc(d.fen) + "</code>.</p>";
  else h += "<p>Board reading (Stage 3) has not run yet, so the program does not know the position " +
    "on this diagram. Stage 3 will read the pieces from the picture, and lines that start from it " +
    "wait for that stage.</p>";
  if (d.after_node && D.nodes[d.after_node]) {
    h += "<p>The program guesses that this diagram shows the position after the move " +
      "<button class=chip data-goto='" + d.after_node + "'>" + esc(moveText(d.after_node, true)) +
      "</button>. Stage 3 will check this guess against the picture.</p>";
  }
  if (d.lines && d.lines.length) {
    h += "<p>These lines start from this diagram:</p><div class=chips>";
    for (const lid of d.lines) if (D.lines[lid])
      h += "<button class=chip data-goto='" + D.lines[lid].root + "'>" + esc(D.lines[lid].title) + "</button>";
    h += "</div>";
  }
  box.innerHTML = h;
  box.hidden = false;
  cropInto(box.querySelector("canvas"), id, "260px");
  $("dclose").addEventListener("click", closeDiagram);
  $("usediag").addEventListener("change", (e) => {
    SEL.setDiag(id, e.target.checked);
    const fr = document.querySelector(".diag[data-diagram='" + id + "']");
    if (fr) fr.classList.toggle("excluded", !SEL.diagOn(id));
    selNote();
  });
  for (const b of box.querySelectorAll("[data-goto]"))
    b.addEventListener("click", () => selectNode(b.dataset.goto, {scrollPage: true}));
  setState();
}
function closeDiagram(){
  S.diagram = null;
  $("dpanel").hidden = true;
  for (const el of document.querySelectorAll(".diag.current")) el.classList.remove("current");
  setState();
}
function selNote(){
  $("selnote").textContent = SEL.stored() ?
    "You have changed the selection. The contents page shows it and lets you copy it into the chat." : "";
}

/* ---------------------------------------------------------------- wiring */
function fromHash(){
  const h = location.hash.replace(/^#/, "");
  const m = /^(page|node|line)=(.+)$/.exec(h);
  if (!m) return false;
  if (m[1] === "page") { goPage(m[2], true); return true; }
  if (m[1] === "node" && D.nodes[m[2]]) { if (S.node !== m[2]) selectNode(m[2], {scrollPage: true}); return true; }
  if (m[1] === "line" && D.lines[m[2]]) { selectNode(D.lines[m[2]].root, {scrollPage: true}); return true; }
  return false;
}
function init(){
  const sel = $("linesel");
  let group = null, lastSection = null;
  for (const id of D.lineOrder) {
    const L = D.lines[id];
    if (L.section !== lastSection) {
      group = document.createElement("optgroup");
      group.label = L.section || D.chapter.title;
      sel.appendChild(group);
      lastSection = L.section;
    }
    const o = document.createElement("option");
    o.value = id;
    o.textContent = L.title + " (" + pageName(L.page) + (L.status === "waiting" ? ", waiting" : "") + ")";
    (group || sel).appendChild(o);
  }
  if (!D.lineOrder.length) { $("linepick").hidden = true; $("linestatus").hidden = true; }
  sel.addEventListener("change", () => { selectNode(D.lines[sel.value].root, {scrollPage: true}); sel.blur(); });
  $("ov").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.node) { selectNode(b.dataset.node, {}); return; }
    if (b.dataset.diagram) { showDiagram(b.dataset.diagram); return; }
    if (b.dataset.mark) {
      const m = D.pages[S.page].marks[parseInt(b.dataset.mark, 10)];
      $("info").innerHTML = "<div class=cur>“" + esc(shown(m.raw)) + "”</div><div class=muted>" +
        "The program found this move in the text but placed it in no line" +
        (m.reason ? ", because " + esc(m.reason) : "") + ".</div>";
    }
  });
  $("tree").addEventListener("click", (e) => {
    const t = e.target.closest(".mv");
    if (t && t.dataset.node) selectNode(t.dataset.node, {scrollTree: false, scrollPage: true});
  });
  $("bstart").addEventListener("click", () => toEnd(-1));
  $("bback").addEventListener("click", () => step(-1));
  $("bfwd").addEventListener("click", () => step(1));
  $("bend").addEventListener("click", () => toEnd(1));
  $("bflip").addEventListener("click", () => { S.flip = !S.flip; renderBoard(); });
  $("mback").addEventListener("click", () => step(-1));
  $("mfwd").addEventListener("click", () => step(1));
  $("mboard").addEventListener("click", () => {
    S.mini = !(S.mini === null ? !!S.node : S.mini); renderBoard();
  });
  $("mmoves").addEventListener("click", () => $("panel").scrollIntoView({block: "start"}));
  $("prevpage").addEventListener("click", () => goPage(S.page - 1));
  $("nextpage").addEventListener("click", () => goPage(S.page + 1));
  $("gopage").addEventListener("click", () => goPage($("pagenum").value));
  $("pagenum").addEventListener("keydown", (e) => { if (e.key === "Enter") { goPage($("pagenum").value); e.preventDefault(); } });
  $("pagenum").addEventListener("blur", () => { $("pagenum").value = S.page; });
  $("zoom").addEventListener("click", () => {
    const z = $("pagescroll").classList.toggle("zoom");
    $("zoom").textContent = z ? "Fit the page" : "Enlarge the page";
  });
  $("usepage").addEventListener("change", (e) => { SEL.setPages(S.page, S.page, e.target.checked); showPage(S.page); selNote(); });
  const pgn = $("pgnbtn");
  if (!D.pgn) pgn.disabled = true;
  pgn.addEventListener("click", () => {
    const blob = new Blob([D.pgn], {type: "application/x-chess-pgn"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = D.pgnName;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  });
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || e.altKey || e.ctrlKey || e.metaKey) return;
    if (tag === "select" && (e.key === "ArrowUp" || e.key === "ArrowDown")) return;
    if (e.key === "ArrowRight") { step(1); e.preventDefault(); }
    else if (e.key === "ArrowLeft") { step(-1); e.preventDefault(); }
    else if (e.key === "ArrowDown") { sideStep(1); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sideStep(-1); e.preventDefault(); }
    else if (e.key === "Home") { toEnd(-1); e.preventDefault(); }
    else if (e.key === "End") { toEnd(1); e.preventDefault(); }
    else if (e.key === "PageDown") { goPage(S.page + 1); e.preventDefault(); }
    else if (e.key === "PageUp") { goPage(S.page - 1); e.preventDefault(); }
  });
  window.addEventListener("hashchange", fromHash);
  SMALL.addEventListener && SMALL.addEventListener("change", renderBoard);
  let start = D.chapter.start;
  while (!(start in D.pages) && start <= D.chapter.end) start++;
  showPage(start);
  if (!fromHash()) {
    const first = D.lineOrder.find(id => D.lines[id].page <= S.page && S.page <= D.lines[id].end_page);
    if (first) { S.line = first; S.node = null; renderTree(); renderChips(); }
    renderBoard(); renderInfo(); setState();
  }
  selNote();
}
init();
})();
"""

CHAPTER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__BASE_CSS____CHAPTER_CSS__</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>__PIECES__</defs></svg>
<div class="wrap">
<div class="top">
<span class="book">__BOOK__</span>
<h1>__H1__</h1>
<a href="index.html">Contents and selection</a>
__CHNAV__
</div>
<div class="help">
<p class="mouse">The book page is shown with a box over every move that the program found in the text.
A click on a green, amber or red box shows the position after that move on the board. A grey box
marks a move of a line that starts from a diagram: until board reading (Stage 3) has read the
pieces from the diagram picture, the board shows that picture instead. A purple dashed box marks a
move that the program placed in no line, and a click on it says why. A click on a blue frame shows
the diagram, the lines that start from it and a box to use or leave out that diagram. The left and
right arrow keys and the buttons under the board step through the line, the up and down arrow keys
switch between the moves the book gives at the same point, and the Page Up and Page Down keys turn
the pages.</p>
<p class="touch">The book page is shown with a box over every move that the program found in the
text. A tap on a green, amber or red box shows the position after that move on the small board in
the corner. A grey box marks a move of a line that starts from a diagram, which board reading
(Stage 3) has not read yet; a purple dashed box marks a move that the program placed in no line. A
tap on a blue frame shows the diagram below the page. The buttons in the bar at the bottom step
through the line, show or hide the small board, and lead to the move list.</p>
<p>A ▫ sign stands for a sign that the text recognition could not name, such as a chess
figurine.</p>
</div>
<div class="legend">
<span><i class="sw ok"></i>read with no doubt</span>
<span><i class="sw amber"></i>chosen among several readings</span>
<span><i class="sw bad"></i>not readable</span>
<span><i class="sw wait"></i>waiting for the diagram position (Stage 3)</span>
<span><i class="sw unatt"></i>not placed in any line</span>
<span><i class="sw dg"></i>diagram</span>
</div>
<div class="reader">
<section class="pagecol" aria-label="Book page">
<div class="pagenav">
<button id="prevpage" aria-label="Previous page">&#9664; Previous</button>
<label>PDF page <input id="pagenum" type="number" min="1" max="__PAGECOUNT__"></label>
<button id="gopage">Go</button>
<button id="nextpage" aria-label="Next page">Next &#9654;</button>
<button id="zoom">Enlarge the page</button>
<label class="use"><input type="checkbox" id="usepage"> Use this page</label>
<span id="pageinfo" class="pinfo"></span>
<span id="pagemsg" class="pinfo" role="status"></span>
</div>
<div class="notice offpage" id="offpage"></div>
<div class="pagescroll" id="pagescroll">
<div class="pagebox" id="pagebox"><img id="pageimg" alt=""><div class="ov" id="ov"></div></div>
</div>
<p class="muted" id="selnote" style="font-size:.85rem" role="status"></p>
</section>
<aside class="panel" id="panel" aria-label="Board and moves">
<div class="linepick" id="linepick"><label for="linesel" class="muted" style="font-size:.85rem">Line</label>
<select id="linesel"></select></div>
<div class="chips" id="chips"></div>
<h2><span id="linetitle">No line chosen</span> <span id="linestatus" class="badge"></span></h2>
<div id="linemeta" class="muted" style="font-size:.85rem"></div>
<div class="dpanel" id="dpanel" hidden></div>
<div class="boardwrap" id="board"></div>
<p class="boardnote" id="boardnote"></p>
<div class="controls">
<button id="bstart" title="Start of the line (Home)" aria-label="Start of the line">&#9198;</button>
<button id="bback" title="Previous move (left arrow)" aria-label="Previous move">&#9664;</button>
<button id="bfwd" title="Next move (right arrow)" aria-label="Next move">&#9654;</button>
<button id="bend" title="End of the line (End)" aria-label="End of the line">&#9197;</button>
<button id="bflip" title="Turn the board round" aria-label="Turn the board round">Flip</button>
</div>
<div class="info" id="info"></div>
<div class="tree" id="tree" aria-label="Moves of the line"></div>
<div class="foot">
<button id="pgnbtn">Download PGN</button>
<span class="muted" style="font-size:.85rem">__PGNNOTE__</span>
</div>
</aside>
</div>
</div>
<div class="mini" id="mini" aria-label="Small board"><div id="minibox"></div><p class="mnote" id="mininote"></p></div>
<div class="mbar" aria-label="Current move">
<span class="mtxt" id="mtxt">No move chosen</span>
<button id="mback" aria-label="Previous move">&#9664;</button>
<button id="mfwd" aria-label="Next move">&#9654;</button>
<button id="mboard" aria-pressed="false">Board</button>
<button id="mmoves">Moves</button>
</div>
<script type="application/json" id="data">__DATA__</script>
<script type="application/json" id="images">__IMAGES__</script>
<script>__SELJS__</script>
<script>__JS__</script>
</body>
</html>
"""

LINE_WORDS = {
    "ok": "every move read with no doubt",
    "guessed": "some moves chosen by the moves that follow",
    "ambiguous": "some moves with several equal readings",
    "failed": "some moves not readable",
    "waiting": "waiting for the diagram position (Stage 3)",
}


def _json_script(obj):
    """JSON safe inside a <script> element."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _pieces_defs():
    return "".join(chess.svg.PIECES[k] for k in "PNBRQKpnbrqk")


def chapter_data(book, ch, pgn_text):
    idx = ch["index"]
    pages = {}
    for pg in book["pages"]:
        if ch["start"] <= pg["page"] <= ch["end"]:
            pages[pg["page"]] = {
                "w": pg["width"], "h": pg["height"], "selected": pg["selected"],
                "folio": pg.get("folio"),
                "diagrams": pg["diagrams"],
                "marks": [{k: m[k] for k in ("bbox", "node", "status", "raw", "line", "reason")
                           if k in m} for m in pg["marks"]]}
    lines = {}
    order = []
    for L in book["lines"]:
        if L["chapter"] == idx:
            lines[L["id"]] = {k: L[k] for k in ("id", "title", "kind", "page", "end_page",
                                                "start_fen", "root", "status", "diagram",
                                                "section", "result", "moves")}
            order.append(L["id"])
    nodes = {}
    for nid, n in book["nodes"].items():
        if n["line"] in lines:
            nn = {k: n.get(k) for k in ("san", "fen", "parent", "children", "number", "black",
                                         "page", "bbox", "status", "raw", "comment", "main",
                                         "assumed", "uci", "line")}
            if n.get("alternatives"):
                nn["alternatives"] = n["alternatives"]
            if n.get("reason"):
                nn["reason"] = n["reason"]
            nn["id"] = nid
            nodes[nid] = nn
    chapters = [{"index": c["index"], "title": c["title"], "start": c["start"], "end": c["end"],
                 "file": c["file"], "empty": c["end"] < c["start"]} for c in book["chapters"]]
    sel = book.get("selection") or {}
    return {
        "book": {"title": book["title"], "pdf": book["pdf"]},
        "chapter": {"index": idx, "title": ch["title"], "start": ch["start"], "end": ch["end"],
                    "file": ch["file"]},
        "chapters": chapters, "pageCount": book["page_count"], "pages": pages, "lines": lines,
        "lineOrder": order, "nodes": nodes, "pgn": pgn_text, "pgnName": ch["pgn"],
        "words": STATUS_WORDS, "lineWords": LINE_WORDS, "kindWords": KIND_WORDS,
        "notPosition": list(NOT_A_POSITION), "excludedKinds": list(EXCLUDED_KINDS),
        "selection": {"pages": sel.get("pages", {"exclude": []}),
                      "diagrams": sel.get("diagrams", {"exclude": [], "include": []})},
        "selBase": _selection_base(book),
    }


def chapter_heading(ch):
    """'Chapter 7, How to Begin a Game' (no colon between the parts)."""
    sub = (ch.get("subtitle") or "").strip()
    label = ch.get("label") or ch["title"]
    return f"{label}, {sub}" if sub and label != sub else (label or ch["title"])


def chapter_html(book, ch, images, pgn_text, pgn_info):
    data = chapter_data(book, ch, pgn_text)
    chs = [c for c in book["chapters"] if c["end"] >= c["start"]]
    pos = next(i for i, c in enumerate(chs) if c["index"] == ch["index"])
    nav = []
    if pos > 0:
        nav.append(f'<a href="{chs[pos - 1]["file"]}">Previous chapter</a>')
    if pos + 1 < len(chs):
        nav.append(f'<a href="{chs[pos + 1]["file"]}">Next chapter</a>')
    games, waiting = pgn_info
    if games:
        pgn_note = f"The PGN file holds the {_plural(games, 'decoded line')} of this chapter."
    else:
        pgn_note = ("No line of this chapter is decoded yet, so there is no PGN file to "
                    "download.")
    if waiting:
        pgn_note += (f" It leaves out the {_plural(waiting, 'line')} that "
                     f"{'waits' if waiting == 1 else 'wait'} for Stage 3.")
    title = f"{ch['label']} Reader"
    rep = {
        "__TITLE__": html.escape(title),
        "__BOOK__": html.escape(book["title"]),
        "__H1__": html.escape(chapter_heading(ch)),
        "__CHNAV__": " ".join(nav),
        "__PAGECOUNT__": str(book["page_count"]),
        "__PGNNOTE__": html.escape(pgn_note),
        "__BASE_CSS__": BASE_CSS,
        "__CHAPTER_CSS__": CHAPTER_CSS,
        "__PIECES__": _pieces_defs(),
        "__DATA__": _json_script(data),
        "__IMAGES__": _json_script(images),
        "__SELJS__": SELECTION_JS,
        "__JS__": CHAPTER_JS,
    }
    out = CHAPTER_HTML
    for k, v in rep.items():
        out = out.replace(k, v)
    return out


# ---------------------------------------------------------------- index page

INDEX_CSS = r"""
.intro{max-width:80ch}
.intro p{margin:.4em 0}
.actions{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);
padding:8px 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.actions .msg{font-size:.85rem;color:var(--muted)}
details.sel{margin:8px 0}
details.sel pre{white-space:pre-wrap;word-break:break-all;background:var(--card);
border:1px solid var(--line);border-radius:6px;padding:8px;font-size:.8rem;max-height:240px;
overflow:auto}
.chapter{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;
margin:14px 0;box-shadow:var(--shadow)}
.chhead{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline}
.chhead h2{margin:0;font-size:1.15rem;flex:1 1 260px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px;margin:8px 0}
.tile{border:1px solid var(--line);border-radius:6px;padding:4px 8px;background:var(--bg);
font-size:.8rem;line-height:1.3;display:flex;flex-direction:column}
.tile b{font-size:1.1rem}
.tile span{color:var(--muted)}
.sections{columns:2 280px;font-size:.85rem;margin:6px 0;padding-left:1.2em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(118px,1fr));gap:10px;margin-top:8px}
.pg{font-size:.78rem;border:1px solid var(--line);border-radius:6px;padding:4px;background:var(--bg);
min-width:0}
.pg.off{opacity:.55}
.thumb{position:relative;width:100%;background:#fff;border:1px solid var(--line)}
.thumb img{display:block;width:100%;height:auto}
.thumb .d{position:absolute;padding:0;border:2px solid var(--diag);background:rgba(47,111,223,.06);
border-radius:2px;cursor:zoom-in;min-width:0}
.thumb .d.off{border-color:var(--wait);
background:repeating-linear-gradient(45deg,rgba(125,133,143,.45) 0 4px,transparent 4px 8px)}
.pg label{display:flex;align-items:center;gap:4px;cursor:pointer}
.dl{display:flex;flex-wrap:wrap;gap:0 8px;margin-top:2px}
.dl label{font-size:.75rem}
.dl label.pageoff{color:var(--muted);text-decoration:line-through}
.pgtop{display:flex;justify-content:space-between;align-items:center;gap:4px}
.pgtop a{font-size:.75rem}
.lightbox{position:fixed;inset:0;z-index:20;background:rgba(0,0,0,.55);display:flex;
align-items:center;justify-content:center;padding:16px}
.lightbox[hidden]{display:none}
.lbcard{background:var(--card);color:var(--fg);border-radius:8px;padding:12px;max-width:min(520px,100%);
max-height:100%;overflow:auto;box-shadow:var(--shadow)}
.lbcard img{display:block;width:100%;max-width:360px;margin:8px auto;border:1px solid var(--line);
image-rendering:auto;background:#fff}
.lbcard .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between}
"""

INDEX_JS = r"""
(function(){
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const CROPS = JSON.parse(document.getElementById("crops").textContent);
const kinds = {}, info = {};
for (const p of D.pages) for (const d of p.diagrams) { kinds[d.id] = d.kind; info[d.id] = Object.assign({page: p.page, folio: p.folio}, d); }
const SEL = makeSelection(D.selection, {pdf: D.pdf, pageCount: D.pageCount, base: D.selBase,
  kinds: kinds, excludedKinds: D.excludedKinds, title: D.title});
const $ = (id) => document.getElementById(id);
function refresh(){
  for (const el of document.querySelectorAll(".pg")) {
    const p = parseInt(el.dataset.page, 10);
    el.classList.toggle("off", !SEL.pageOn(p));
    el.querySelector(".pcb").checked = SEL.pageOn(p);
  }
  for (const el of document.querySelectorAll(".dcb")) {
    const id = el.dataset.id, p = parseInt(el.dataset.page, 10);
    el.checked = SEL.diagOn(id);
    el.parentElement.classList.toggle("pageoff", !SEL.pageOn(p));
  }
  for (const el of document.querySelectorAll(".thumb .d")) el.classList.toggle("off", !SEL.diagOn(el.dataset.id));
  for (const el of document.querySelectorAll(".ccb")) {
    const a = parseInt(el.dataset.start, 10), b = parseInt(el.dataset.end, 10);
    let on = 0, n = 0;
    for (let p = a; p <= b; p++) { n++; if (SEL.pageOn(p)) on++; }
    el.checked = on === n && n > 0; el.indeterminate = on > 0 && on < n;
  }
  $("seljson").textContent = SEL.text();
  $("msg").textContent = SEL.stored() ?
    "You have changed the selection. This browser keeps your changes on this page and in the " +
    "chapter readers until you copy them into the chat." :
    "The selection matches the one the program used for this run.";
}
document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.classList.contains("pcb")) { const p = parseInt(t.dataset.page, 10); SEL.setPages(p, p, t.checked); }
  else if (t.classList.contains("dcb")) {
    const p = parseInt(t.dataset.page, 10);
    if (t.checked && !SEL.pageOn(p)) SEL.setPages(p, p, true);
    SEL.setDiag(t.dataset.id, t.checked);
  }
  else if (t.classList.contains("ccb")) SEL.setPages(parseInt(t.dataset.start, 10), parseInt(t.dataset.end, 10), t.checked);
  else if (t.id === "lbuse") {
    const id = t.dataset.id, p = info[id].page;
    if (t.checked && !SEL.pageOn(p)) SEL.setPages(p, p, true);
    SEL.setDiag(id, t.checked);
  } else return;
  refresh();
});
function esc(t){ return String(t == null ? "" : t).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }
function openBox(id){
  const d = info[id];
  const page = d.folio ? "page " + d.folio + " (PDF page " + d.page + ")" : "PDF page " + d.page;
  const name = d.label ? "Diagram " + d.label : "Unnumbered diagram " + id.split("-")[1];
  let h = "<div class=row><h2 style='margin:0'>" + esc(name) + "</h2><button id=lbclose>Close</button></div>";
  h += "<p class=muted>On " + esc(page) + ". The program takes this picture for " + esc(D.kindWords[d.kind] || "a picture") + ".</p>";
  if (CROPS[id]) h += "<img alt='" + esc(name) + "' src='data:image/jpeg;base64," + CROPS[id] + "'>";
  h += "<p><label><input type=checkbox id=lbuse data-id='" + esc(id) + "'" + (SEL.diagOn(id) ? " checked" : "") +
    "> Use this diagram</label></p>";
  if (d.reader) h += "<p><a href='" + esc(d.reader) + "'>Open this page in the chapter reader</a></p>";
  $("lbcard").innerHTML = h;
  $("lightbox").hidden = false;
  $("lbclose").addEventListener("click", closeBox);
  $("lbclose").focus();
}
function closeBox(){ $("lightbox").hidden = true; }
document.addEventListener("click", (e) => {
  const b = e.target.closest(".thumb .d");
  if (b) { openBox(b.dataset.id); return; }
  if (e.target.id === "lightbox") closeBox();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeBox(); });
$("copybtn").addEventListener("click", async () => {
  const t = SEL.text();
  let ok = false;
  try { await navigator.clipboard.writeText(t); ok = true; } catch (err) { ok = false; }
  if (!ok) {
    const ta = document.createElement("textarea");
    ta.value = t; document.body.appendChild(ta); ta.select();
    try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
    ta.remove();
  }
  $("msg").textContent = ok ?
    "The selection is on the clipboard, and you can paste it into the chat." :
    "The browser refused to copy, so you need to open the selection text below and copy it by hand.";
});
$("dlbtn").addEventListener("click", () => {
  const blob = new Blob([SEL.text() + "\n"], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "selection.json";
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
});
$("resetbtn").addEventListener("click", () => { SEL.reset(); refresh(); });
window.selectionText = SEL.text;
refresh();
})();
"""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__BASE_CSS____INDEX_CSS__</style>
</head>
<body>
<div class="wrap">
<h1>__H1__</h1>
<div class="intro">__INTRO__</div>
<div class="legend">
<span><i class="sw dg"></i>diagram the program uses</span>
<span><i class="sw wait" style="background:repeating-linear-gradient(45deg,var(--wait) 0 2px,transparent 2px 4px)"></i>diagram left out</span>
</div>
<div class="actions">
<button id="copybtn">Copy selection</button>
<button id="dlbtn">Download selection.json</button>
<button id="resetbtn">Undo my changes</button>
<span class="msg" id="msg" role="status"></span>
</div>
<details class="sel"><summary>Show the selection text</summary><pre id="seljson"></pre></details>
__SUMMARY__
__CHAPTERS__
</div>
<div class="lightbox" id="lightbox" hidden><div class="lbcard" id="lbcard" role="dialog" aria-modal="true"></div></div>
<script type="application/json" id="data">__DATA__</script>
<script type="application/json" id="crops">__CROPS__</script>
<script>__SELJS__</script>
<script>__JS__</script>
</body>
</html>
"""


def _counts_table(c):
    m = c["moves"]
    rows = [(c["lines"], "line", None), (c["games"], "game", None),
            (c["fragments"], "fragment", None),
            (m.get("ok", 0), "move read with no doubt", "moves read with no doubt"),
            (m.get("guessed", 0), "move chosen by the moves that follow",
             "moves chosen by the moves that follow"),
            (m.get("ambiguous", 0), "move with several equal readings",
             "moves with several equal readings"),
            (m.get("failed", 0), "move not readable", "moves not readable"),
            (m.get("waiting", 0), "move waiting for Stage 3", "moves waiting for Stage 3"),
            (c["variations"], "variation placed", "variations placed"),
            (c["unattached"], "move sequence not placed", "move sequences not placed"),
            (c["waiting"], "line waiting for a diagram position",
             "lines waiting for a diagram position")]
    if m.get("inserted"):
        rows.insert(7, (m["inserted"], "move supplied by the program", "moves supplied by the program"))
    cells = "".join(f"<div class=tile><b>{k}</b><span>{html.escape(one if k == 1 else (many or one + 's'))}"
                    "</span></div>" for k, one, many in rows)
    return f"<div class=tiles aria-label='What the program extracted'>{cells}</div>"


def index_html(book, thumbs, sizes, crops=None):
    e = html.escape
    crops = crops or {}
    sel = book["selection"]
    saved = book.get("selection_from_file")
    total = book["stats"]
    intro = [
        f"<p>This page lists every page of <i>{e(book['title'])}</i> ({e(book['pdf'])}) with what "
        "the program extracted from it. Each chapter shows its sections, its page range, its counts "
        "and a small picture of every page.</p>",
        "<p>A line is a game or a fragment: a game has a header with the players or starts from the "
        "first move, and a fragment is a shorter sequence of moves, usually from a diagram. Board "
        "reading (Stage 3) is the stage that will read the pieces from each diagram picture; until "
        "it runs, the lines that start from a diagram wait for it.</p>",
        "<p>A tick in the box under a page picture means that the program reads that page. Blue "
        "frames on a page picture mark the diagrams, and the boxes under the picture list them by "
        "their printed number. A click on a frame opens a larger picture of that diagram with a box "
        "to use it or leave it out. The box beside a chapter title includes or excludes all its "
        "pages at once. You should leave out pictures that are not chess positions, such as "
        "ornaments, pictures that show only part of a board, and pages that hold no chess "
        "content.</p>",
        "<p>This browser keeps your changes, here and in the chapter readers, until you copy them. "
        "When you have finished, you press <b>Copy selection</b> and paste the copied text into the "
        "chat. The program saves it and uses it on its next run. <b>Download selection.json</b> "
        "saves the same text as a file.</p>",
        "<p>The link <b>Open the reader</b> beside each chapter opens the book reader. The reader "
        "shows the book page with a box over every move the program found and a live board beside "
        "it. Page numbers on this page are PDF page numbers"
        + (" (the printed page number is one lower)" if book.get("folio_offset") == 1 else "")
        + ".</p>",
    ]
    if saved:
        intro.append(f"<p>This run used the selection saved in <code>{e(book.get('selection_file') or '')}"
                     "</code>.</p>")
    else:
        intro.append("<p>No saved selection exists for this book yet, so this run used the "
                     "program's default selection. " + e(sel.get("note") or "") + "</p>")
    m = total["moves"]
    waiting_lines = total["line_status"].get("waiting", 0)
    summary = (
        "<h2>Summary</h2><p>The program assembled "
        f"{_plural(total['lines'], 'line')}: {_plural(total['games'], 'game')} and "
        f"{_plural(total['fragments'], 'fragment')}. Of these, {waiting_lines} "
        f"{'waits' if waiting_lines == 1 else 'wait'} for the diagram positions that Stage 3 will "
        "read. The decoded lines hold "
        f"{_plural(m.get('ok', 0), 'move')} read with no doubt, "
        f"{_plural(m.get('guessed', 0) + m.get('ambiguous', 0), 'move')} chosen among several "
        f"readings and {_plural(m.get('failed', 0), 'move')} that the program could not read. It "
        f"placed {_plural(total['variations'], 'variation')}, and "
        f"{_plural(total['unattached'], 'move sequence')} found no place in any line.</p>")
    parts = []
    by_page = {p["page"]: p for p in book["pages"]}
    reader_of = {}
    for ch in book["chapters"]:
        if ch["end"] < ch["start"]:
            continue
        c = ch["counts"]
        size = sizes.get(ch["index"])
        link = (f'<a href="{e(ch["file"])}">Open the reader</a>'
                + (f' <span class=muted>({size / 1048576:.1f} MB)</span>' if size else "")
                if size else "<span class=muted>No reader was built for this chapter in this run.</span>")
        secs = "".join(f"<li>p. {s['page']}: {e(_title(s['title']))}</li>" for s in ch["sections"])
        cards = []
        for p in range(ch["start"], ch["end"] + 1):
            pg = by_page[p]
            ds = []
            boxes = []
            for d in pg["diagrams"]:
                r = d["rect"]
                if size:
                    reader_of[d["id"]] = f'{ch["file"]}#page={p}'
                style = (f"left:{100 * r[0] / pg['width']:.2f}%;top:{100 * r[1] / pg['height']:.2f}%;"
                         f"width:{100 * (r[2] - r[0]) / pg['width']:.2f}%;"
                         f"height:{100 * (r[3] - r[1]) / pg['height']:.2f}%")
                k = d["id"].split("-")[1]
                lab = d["label"] or f"unnumbered {k}"
                name = f"Diagram {d['label']}" if d["label"] else f"Unnumbered diagram {k}"
                tip = f"{name} on PDF page {p}: {KIND_WORDS.get(d['kind'], 'a picture')}"
                ds.append(f'<button class="d" data-id="{d["id"]}" data-page="{p}" style="{style}" '
                          f'title="{e(tip)}" aria-label="{e("Show " + name)}"></button>')
                boxes.append(f'<label title="{e(tip)}"><input type="checkbox" class="dcb" '
                             f'data-id="{d["id"]}" data-page="{p}">{e(lab)}</label>')
            reader = (f'<a href="{e(ch["file"])}#page={p}">read</a>' if size else "")
            cards.append(
                f'<div class="pg" data-page="{p}"><div class="thumb" '
                f'style="aspect-ratio:{pg["width"]}/{pg["height"]}">'
                f'<img loading="lazy" alt="Page {p}" src="data:image/jpeg;base64,{thumbs[p]}">'
                f'{"".join(ds)}</div><div class="pgtop"><label><input type="checkbox" class="pcb" '
                f'data-page="{p}">p. {p}</label>{reader}</div>'
                + (f'<div class="dl">{"".join(boxes)}</div>' if boxes else "") + "</div>")
        parts.append(
            f'<section class="chapter" id="ch{ch["index"]:02d}"><div class="chhead">'
            f'<label><input type="checkbox" class="ccb" data-start="{ch["start"]}" '
            f'data-end="{ch["end"]}" aria-label="Include all pages of {e(ch["title"])}"></label>'
            f'<h2>{e(chapter_heading(ch))}</h2><span class=muted>pages {ch["start"]} to {ch["end"]}</span> '
            f'{link}</div>'
            + (f'<ul class="sections">{secs}</ul>' if secs else "")
            + _counts_table(c)
            + f'<div class="grid">{"".join(cards)}</div></section>')
    data = {
        "title": book["title"], "pdf": book["pdf"], "pageCount": book["page_count"],
        "excludedKinds": list(EXCLUDED_KINDS), "kindWords": KIND_WORDS,
        "selection": {"pages": sel.get("pages", {"exclude": []}),
                      "diagrams": sel.get("diagrams", {"exclude": [], "include": []})},
        "selBase": _selection_base(book),
        "pages": [{"page": p["page"], "selected": p["selected"], "folio": p.get("folio"),
                   "diagrams": [{"id": d["id"], "kind": d["kind"], "label": d.get("label"),
                                 "reader": reader_of.get(d["id"])} for d in p["diagrams"]]}
                  for p in book["pages"]],
    }
    rep = {
        "__TITLE__": e(f"{book['title']} Contents"),
        "__H1__": e(f"{book['title']}, contents and selection"),
        "__INTRO__": "".join(intro),
        "__SUMMARY__": summary,
        "__CHAPTERS__": "".join(parts),
        "__BASE_CSS__": BASE_CSS,
        "__INDEX_CSS__": INDEX_CSS,
        "__DATA__": _json_script(data),
        "__CROPS__": _json_script(crops),
        "__SELJS__": SELECTION_JS,
        "__JS__": INDEX_JS,
    }
    out = INDEX_HTML
    for k, v in rep.items():
        out = out.replace(k, v)
    return out


def _title(t):
    from .assemble import display_title
    return display_title(t)


# ---------------------------------------------------------------- build

def build_reader(book, pdf_path, out_dir, chapters=None, progress=None):
    """Write index.html and chNN.html into out_dir. chapters limits the chapter
    readers to those indices (the index page always covers the whole book).
    Returns {"files": {name: bytes}, "pgn": pgnout report, "sizes": {index: bytes}}."""
    say = progress or (lambda *_: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf_path)
    pgn_dir = out_dir.parent / "pgn"
    pgn_report = pgnout.write_pgn(book, pgn_dir)
    sizes = {}
    files = {}
    for ch in book["chapters"]:
        if ch["end"] < ch["start"]:
            continue
        if chapters is not None and ch["index"] not in chapters:
            old = out_dir / ch["file"]
            if old.exists():
                sizes[ch["index"]] = old.stat().st_size
            continue
        pgn_text = (pgn_dir / ch["pgn"]).read_text(encoding="utf-8")
        info = pgn_report.get(ch["index"], {})
        quality, dpi = PAGE_QUALITY, PAGE_DPI
        while True:
            images = {p: _b64(page_jpeg(doc, p, dpi, quality))
                      for p in range(ch["start"], ch["end"] + 1)}
            text = chapter_html(book, ch, images, pgn_text,
                                (info.get("games", 0), info.get("waiting", 0)))
            data = text.encode("utf-8")
            if len(data) <= TARGET_BYTES or quality <= 30:
                break
            quality -= 10
            if quality <= 40:
                dpi = 100
        path = out_dir / ch["file"]
        path.write_bytes(data)
        sizes[ch["index"]] = len(data)
        files[ch["file"]] = len(data)
        say(f"{ch['file']}: {len(data) / 1048576:.1f} MB (JPEG quality {quality}, {dpi} dpi)")
    thumbs = {p: _b64(page_jpeg(doc, p, THUMB_DPI, THUMB_QUALITY))
              for p in range(1, doc.page_count + 1)}
    crops = {}
    for pg in book["pages"]:
        for d in pg["diagrams"]:
            r = d["rect"]
            crops[d["id"]] = _b64(page_jpeg(doc, pg["page"], CROP_DPI, CROP_QUALITY,
                                            clip=(r[0] - 2, r[1] - 2, r[2] + 2, r[3] + 2)))
    text = index_html(book, thumbs, sizes, crops)
    data = text.encode("utf-8")
    (out_dir / "index.html").write_bytes(data)
    files["index.html"] = len(data)
    say(f"index.html: {len(data) / 1048576:.1f} MB")
    return {"files": files, "pgn": pgn_report, "sizes": sizes}
