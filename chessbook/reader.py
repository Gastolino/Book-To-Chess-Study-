"""The interactive book reader: a contents page and one page per chapter.

build_reader(book, pdf_path, out_dir) writes, from an assembled book
(assemble.build_book) and its PDF:

    out_dir/index.html    the contents: every chapter with its counts and a
                          picture of each of its pages, with boxes to include
                          or leave out chapters and pages, diagram outlines
                          that switch a diagram on or off, and the selection
                          to copy back into the chat
    out_dir/chNN.html     one self-contained reader per chapter: the book page
                          with clickable boxes over every move and diagram,
                          and a live board with the move tree beside it

Every file is self-contained: the fonts and page images are embedded as
base64, the board is drawn as SVG with python-chess's piece drawings, and no
file loads anything from the network. The look follows DESIGN.md through
chessbook.style.

Changes to the selection made on the contents page or in a chapter reader
are kept in the browser (localStorage, one entry per book) until the reader
copies them into the chat; both kinds of page read and write the same entry,
so a change survives moving between them. The entry is dropped when the
program has since been run with another selection.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path

import chess.svg
import pymupdf

from . import pgnout, style
from .selection import EXCLUDED_KINDS

PAGE_DPI = 120
PAGE_QUALITY = 60
THUMB_DPI = 40
THUMB_QUALITY = 50
MAX_BYTES = 15 * 1024 * 1024
TARGET_BYTES = 14 * 1024 * 1024

# The status of a move, in words. The chapter reader shows these beside the
# current move and in the legend of the outlines.
STATUS_WORDS = {
    "ok": "Read without doubt",
    "guessed": "Chosen from several readings",
    "ambiguous": "Chosen from several equal readings",
    "failed": "Not read",
    "inserted": "Supplied by the program",
    "waiting": "Waits for board reading (Stage 3)",
    "unattached": "Placed in no line",
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


def _folios(book):
    """The printed page number of every PDF page (None where the book prints
    none), as a list indexed by PDF page minus one."""
    by_page = {p["page"]: p.get("folio") for p in book["pages"]}
    return [by_page.get(p) for p in range(1, book["page_count"] + 1)]


def page_label(folios, p):
    """'249' for a page with a printed number and 'PDF 1' for one without; a
    book that prints no page numbers at all is counted in PDF pages."""
    f = folios[p - 1] if 0 < p <= len(folios) else None
    if f is not None:
        return str(f)
    return f"PDF {p}" if any(x is not None for x in folios) else str(p)


def page_range(folios, a, b):
    """'pages 241 to 260' in printed numbers where the book prints them; pages
    without a printed number at either end are named by their PDF page:
    'PDF page 1, pages 1 to 12'."""
    if not any(x is not None for x in folios):
        return f"page {a}" if a == b else f"pages {a} to {b}"
    x, y = a, b
    while x <= b and folios[x - 1] is None:
        x += 1
    while y >= x and folios[y - 1] is None:
        y -= 1
    parts = []
    if x > a:
        parts.append(f"PDF page {a}" if x - 1 == a else f"PDF pages {a} to {x - 1}")
    if x <= y:
        f, g = folios[x - 1], folios[y - 1]
        parts.append(f"page {f}" if x == y else f"pages {f} to {g}")
    if y < b and x <= b:
        parts.append(f"PDF page {b}" if y + 1 == b else f"PDF pages {y + 1} to {b}")
    return ", ".join(parts)


# The selection model shared by the contents page and the chapter readers.
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
.bar{display:flex;align-items:center;gap:8px 28px;padding:14px 24px;border-bottom:1px solid var(--line)}
.where{flex:1 1 auto;min-width:0;display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 16px}
.where .book{color:var(--muted);min-width:0;overflow-wrap:anywhere}
.where h1{font-size:17px;line-height:1.35;min-width:0;overflow-wrap:anywhere}
.tools{display:flex;align-items:center;gap:24px;flex:none}
#showread{min-width:6.6em;text-align:left}
.pnav{display:flex;align-items:center}
.pnav .ib{padding:4px 6px}
.pnav .ib svg{width:16px;height:16px}
#pagenum{width:3.6em}
.notes{padding:8px 24px;border-bottom:1px solid var(--line)}
.notes p:empty,.notes:not(:has(p:not(:empty))){display:none}
.reader{display:grid;grid-template-columns:minmax(0,1fr) clamp(400px,33vw,520px);align-items:start}
.pagecol{min-width:0;padding:24px 32px 40px 24px}
.offpage{margin:0 0 16px;padding-left:12px;border-left:1px solid var(--doubt)}
.offpage:empty,.diagnote:empty{display:none}
.diagnote{margin:0 0 16px}
.key{display:grid;margin:0 0 16px}
.key > *{grid-area:1/1}
.legend{visibility:hidden;display:flex;flex-wrap:wrap;align-content:start;gap:4px 20px}
.reading .legend{visibility:visible}
.reading .key .help{visibility:hidden}
.legend > span{display:inline-flex;align-items:center;gap:8px;white-space:nowrap}
.legend .ls{white-space:normal}
.legend .dot{margin:0}
.legend .u{display:inline-block;width:14px;height:9px;border-bottom:1px dotted var(--muted)}
.k{position:relative;display:inline-block;flex:none;width:14px;height:9px;border:1px solid var(--doubt)}
.k.fail{border-color:var(--fail)}
.k.fail::after,.reading .mark.st-failed::after{content:"";position:absolute;right:-5px;top:-1px;width:9px;
height:0;border-top:1px solid var(--fail);transform:rotate(-45deg)}
.k.wait{border:1px dotted var(--muted)}
.k.unatt{border:1px dashed var(--muted)}
.k.off{width:12px;height:12px;border:1px dashed var(--muted)}
.pagescroll{width:100%;overflow-x:auto}
.pagebox{position:relative;width:100%;outline:1px solid var(--line)}
.pagescroll.zoom .pagebox{width:200%}
.pagebox img{display:block;width:100%;height:auto;user-select:none;-webkit-user-select:none}
.ov{position:absolute;inset:0}
.mark,.diag{position:absolute;padding:0;margin:0;border:0;border-radius:0;background:none;
cursor:pointer;min-width:0;min-height:0;overflow:visible;outline:0 solid transparent;outline-offset:0}
.diag{z-index:1}
.mark{z-index:2}
.diag.excluded{outline:1px dashed var(--muted)}
.reading .mark.st-guessed,.reading .mark.st-ambiguous,.reading .mark.st-inserted{outline:1px solid var(--doubt)}
.reading .mark.st-failed{outline:1px solid var(--fail)}
.reading .mark.st-waiting{outline:1px dotted var(--muted)}
.reading .mark.st-unattached{outline:1px dashed var(--muted)}
.mark:hover,.diag:hover,.reading .mark:hover{outline:1px solid var(--accent)}
.mark.current,.diag.current,.reading .mark.current{outline:1.5px solid var(--accent);z-index:3}
.mark:focus-visible,.diag:focus-visible,.reading .mark:focus-visible{outline:1.5px solid var(--accent);
outline-offset:1px;z-index:4}
.pagefoot{margin-top:16px;display:grid;gap:8px}
.pagefoot .row{display:flex;flex-wrap:wrap;align-items:center;gap:8px 24px}
.onpage{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 16px}
.onpage .lab{color:var(--muted);font-weight:500}
.onpage .none{color:var(--muted)}
.onlines{display:contents}
.tl{background:none;border:0;border-radius:0;padding:0;margin:0;text-align:left;color:var(--muted);
cursor:pointer;font:inherit;text-underline-offset:3px;text-decoration-thickness:1px}
.tl:hover{color:var(--fg);text-decoration:underline}
.tl.on{color:var(--fg)}
label.use{display:inline-flex;align-items:center;gap:8px;cursor:pointer}
.chnav{display:flex;gap:24px}
.chnav:empty{display:none}
.pgn{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 16px;margin-top:16px;padding-top:16px;
border-top:1px solid var(--line)}
.panel{position:sticky;top:0;height:100vh;overflow:auto;border-left:1px solid var(--line);
padding:16px 24px;min-width:0;display:flex;flex-direction:column}
.panel > *{flex:none}
.panel > .treesec{flex:0 1 auto;min-height:0;display:flex;flex-direction:column}
.panel > .treesec .tree{flex:1 1 auto;min-height:0;overflow:auto}
.panel > #infosec{max-height:36vh;overflow:auto}
.sec{border-top:1px solid var(--line);padding:12px 0}
.sec:last-child{padding-bottom:0}
.sec[hidden]{display:none}
.boardwrap svg{display:block;width:100%;height:auto}
.boardwrap,.dpanel canvas.pic{margin:0;max-width:min(100%,max(240px,calc(100vh - 400px)))}
svg.board .sl{fill:var(--board-light)}
svg.board .sd{fill:var(--board-dark)}
svg.board .lm{fill:none;stroke:var(--accent);stroke-width:1.5px;vector-effect:non-scaling-stroke}
svg.board .bo{fill:none;stroke:var(--line);stroke-width:1px}
svg.board .co{fill:var(--muted);font-family:"DM Sans",system-ui,sans-serif}
canvas.pic{display:block;width:100%;height:auto;outline:1px solid var(--line)}
.boardnote{margin:8px 0 0}
.boardnote:empty{display:none}
.boardarea.diagram #board,.boardarea.diagram #boardnote{display:none}
.dpanel{display:grid;gap:8px}
.dpanel[hidden]{display:none}
.dhead{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-top:8px}
.links{list-style:none;margin:0;padding:0}
.links li{margin:2px 0}
.controls{display:flex;align-items:center;margin:8px -8px 4px}
.controls .gap{flex:1}
.ltitle{font-size:17px;line-height:1.35}
#linemeta{margin-top:2px}
#linemeta:empty{display:none}
.tree{position:relative;font-family:"Geist Mono",ui-monospace,Menlo,Consolas,monospace;font-size:15px;
line-height:1.7;overflow-wrap:anywhere;font-variant-ligatures:none}
.tree .mv{background:none;border:0;border-radius:0;padding:0;margin:0;font:inherit;cursor:pointer;
color:var(--fg);font-weight:500;text-align:left;vertical-align:baseline}
.tree .mn{color:var(--muted);font-weight:400}
.tree .san{text-underline-offset:3px;text-decoration-thickness:1px}
.tree .mv:hover .san{text-decoration-line:underline}
.tree .mv.cur .san,.tree .mv.cur:hover .san{color:var(--accent);text-decoration-line:none}
.tree .var{display:block;margin:0;padding:0 0 0 12px;border-left:1px solid var(--line)}
.tree .var .mv{color:var(--muted);font-weight:400}
.tree .mv.raw .san{font-weight:400;color:var(--muted);text-decoration:underline dotted 1px var(--muted)}
.tree .mv.raw:hover .san{text-decoration-style:solid}
.tree .mv.raw.cur .san{color:var(--accent);text-decoration:underline dotted 1px var(--accent)}
.tree .mv .dot{margin-right:4px}
.tree .pair{white-space:nowrap}
.tree .start{font-family:"DM Sans",system-ui,sans-serif;font-size:13px;color:var(--muted);
font-weight:400;margin-right:6px}
.tree .start.cur{color:var(--accent)}
.tree .none{font-family:"DM Sans",system-ui,sans-serif;font-size:13px;color:var(--muted)}
.info{display:grid;gap:8px}
.comment{white-space:pre-wrap}
.status{display:grid;gap:4px}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:8px;vertical-align:2px;
background:var(--muted)}
.dot.st-ok{background:var(--ok)}
.dot.st-guessed,.dot.st-ambiguous,.dot.st-inserted{background:var(--doubt)}
.dot.st-failed{background:var(--fail)}
.mbar,.mini,.touch{display:none}
@media (hover:none) and (pointer:coarse){.touch{display:block}.mouse{display:none}
.mark{border-bottom:1px solid color-mix(in srgb,var(--accent) 45%,transparent)}}
@media (max-width:900px){
.bar{flex-wrap:wrap;padding:12px 16px}
.where{flex-basis:100%;white-space:normal;flex-wrap:wrap;gap:0 12px}
.where h1{white-space:normal}
.tools{width:100%;justify-content:space-between;gap:12px}
.notes{padding-left:16px;padding-right:16px}
.reader{grid-template-columns:minmax(0,1fr)}
.pagecol{padding:16px 16px 24px}
.key > *{grid-area:auto}
.legend{display:none;visibility:visible}
.reading .legend{display:flex}
.reading .key .help{display:none}
.panel{position:static;height:auto;display:block;overflow:visible;border-left:0;
border-top:1px solid var(--line);padding:16px 16px 32px}
.panel > .treesec .tree,.panel > #infosec{overflow:visible;max-height:none}
.boardwrap,.dpanel canvas.pic{max-width:none}
body{padding-bottom:64px}
.mbar{display:flex;align-items:center;gap:16px;position:fixed;left:0;right:0;bottom:0;z-index:10;
padding:8px 16px;background:var(--bg);border-top:1px solid var(--line)}
.mside{flex:1;min-width:0;display:flex;align-items:center;gap:4px 12px}
.mtxt{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mbtns{display:flex;align-items:center;gap:0 12px;flex:none}
.mbar .ib{padding:8px 6px}
#mboard[aria-pressed="true"]{color:var(--accent)}
.mini.on{display:block;flex:none;width:144px}
.mbar.withboard{align-items:stretch}
.mbar.withboard .mside{flex-direction:column;align-items:stretch;justify-content:space-between}
.mbar.withboard .mtxt{flex:none;padding-top:4px}
.mbar.withboard .mbtns{justify-content:flex-start;margin-left:-6px}
.mini svg,.mini canvas{display:block;width:100%;height:auto}
.mini .co{display:none}}
"""

CHAPTER_JS = r"""
(function(){
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const IMG = JSON.parse(document.getElementById("images").textContent);
window.READER = D;
const $ = (id) => document.getElementById(id);
const S = {page: null, node: null, line: null, flip: false, diagram: null, mini: null, panelSeen: false};
const imgCache = {};
const SMALL = window.matchMedia("(max-width:900px)");
const ROW = 25.5;  // the height of one row of the move list: 15px type at line height 1.7
window.readerState = {fen: null, nodeId: null, page: null};
const kinds = {};
for (const p in D.pages) for (const d of D.pages[p].diagrams) kinds[d.id] = d.kind;
const SEL = makeSelection(D.selection, {pdf: D.book.pdf, pageCount: D.pageCount, base: D.selBase,
  kinds: kinds, excludedKinds: D.excludedKinds, title: D.book.title});
const NUMBER_WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
// moves and squares inside running text: 12.Nf3, 3...Bd3+, exd5, e4, O-O, e1-h4
const SAN_RE = new RegExp("(\\b\\d{1,3}\\.(?:\\.\\.)?\\s?)?(?:\\b(?:[KQRBN][a-h]?[1-8]?x?[a-h][1-8]" +
  "(?:=[QRBN])?|[a-h]x[a-h][1-8](?:=[QRBN])?|[a-h][1-8](?:-[a-h][1-8])?(?:=[QRBN])?)|" +
  "\\b(?:O-O(?:-O)?|0-0(?:-0)?)(?![\\w-]))[+#]?(?:[!?]{1,2})?", "g");
const PLACEHOLDER = "<i class=ph role=img aria-label='a sign the text recognition could not name'></i>";

function esc(t){ return String(t == null ? "" : t).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }
// the text recognition's reading of a move: as plain text (for tooltips) and as HTML, where a
// sign it could not name is drawn as a small box
function shown(raw){ return String(raw || "").replace(/[\u0000-\u001f]/g, "▫"); }
function shownHtml(raw){ return esc(raw).replace(/[\u0000-\u001f]/g, PLACEHOLDER); }
function cap(t){ t = String(t || ""); return t.charAt(0).toUpperCase() + t.slice(1); }
function lcfirst(t){ t = String(t || ""); return t.charAt(0).toLowerCase() + t.slice(1); }
function words(k){ return k < NUMBER_WORDS.length ? NUMBER_WORDS[k] : String(k); }
// player names and the parts of a heading are joined by an en dash, as the book prints them
function title(t){ return String(t || "").replace(/\s+-\s*|\s*-\s+/g, " – ").replace(/\s+,/g, ","); }

/* ---------------------------------------------------------------- notation in running text */
// A printed move, read cleanly or garbled by the text recognition ("E:a7t", "<it>h6", "lt:\c3",
// "ltlxc8"): it holds a square, or is castling, and apart from its squares it holds at most eight
// signs, no run of five lowercase letters and no hyphen joined to a word ("h3-pawn"). After a
// move number, or after x, a square may end in l, the recognition's reading of 1 ("26.zadl", "xfl").
function moveLike(t, numbered){
  if (/^(?:O-O(?:-O)?|0-0(?:-0)?)[+#t!?]*$/.test(t)) return true;
  let rest = t.replace(/[a-h][1-8]/g, "");
  if (rest === t) {
    const l = numbered ? /[a-h]l(?![a-z])/g : /(?<=x)[a-h]l(?![a-z])/g;
    rest = t.replace(l, "");
    if (rest === t) return false;
  }
  if (/[a-z]{3,}-|-[a-z]{3,}/.test(t)) return false;
  return rest.length <= 8 && !/[a-z]{5,}/.test(rest);
}
// a short run of signs that is not a word: the reading of a figurine move after a move number
function garbled(t){
  return t.length <= 8 && /[A-Za-z0-9]/.test(t) && !/^[A-Za-z]+$/.test(t) && !/[a-z]{3,}/.test(t);
}
function split(tok){
  // [opening signs, the token, closing signs]
  const m = /^([(\[“"‘]*)(.*?)([,;)\]”"’.]*)$/.exec(tok);
  return m ? [m[1], m[2], m[3]] : ["", tok, ""];
}
function wrapN(t){ return "<span class=n>" + esc(t) + "</span>"; }
// short words that the text recognition glues to the move that follows them
const GLUED = /^(and|by|for|of|or|to|then|with|after|if|while)(?=[^a-z])(.+)$/;
function token(tok){
  const [lead, core, tail] = split(tok);
  const g = GLUED.exec(core);
  if (g) {
    const inner = token(g[2] + tail);
    if (inner.indexOf("<span class=n>") === 0) return esc(lead + g[1]) + inner;
  }
  const m = /^(\d{1,3}\.{1,4})?(.*)$/.exec(core);
  if (m[2] && (moveLike(m[2], !!m[1]) || (m[1] && garbled(m[2]))))
    return esc(lead) + wrapN(core) + esc(tail);
  // squares and moves inside a word: "h3-pawn"
  return esc(tok).replace(SAN_RE, (x) => "<span class=n>" + x + "</span>");
}
function notation(text){
  // every move of the text is set as notation in one piece, with its move number
  const parts = String(text == null ? "" : text).split(/(\s+)/);
  let out = "";
  for (let i = 0; i < parts.length; i += 2) {
    const tok = parts[i], sp = parts[i + 1] || "";
    // a move number standing alone before its move: "3... Bd3+", "2... c;!;>"
    const m = /^([(\[“"‘]*)(\d{1,3})(\.{1,4})$/.exec(tok);
    if (m && sp === " " && i + 2 < parts.length) {
      const [lead2, core, tail] = split(parts[i + 2]);
      if (!lead2 && core && (moveLike(core, true) || (m[3].length >= 3 && garbled(core)))) {
        out += esc(m[1]) + wrapN(m[2] + m[3] + " " + core) + esc(tail) + esc(parts[i + 3] || "");
        i += 2;
        continue;
      }
    }
    out += token(tok) + esc(sp);
  }
  return out;
}

function pageImage(p){
  if (!imgCache[p]) { const im = new Image(); im.src = "data:image/jpeg;base64," + IMG[p]; imgCache[p] = im; }
  return imgCache[p];
}
function folio(p){ const f = D.folios[p - 1]; return f == null ? null : String(f); }
const HAS_FOLIOS = D.folios.some(f => f != null);
// the number of a page as the reader types it: the printed number, or "PDF 1" for a page without one
function label(p){ const f = folio(p); return f ? f : (HAS_FOLIOS ? "PDF " + p : String(p)); }
function pageName(p){ const f = folio(p); return f ? "page " + f : (HAS_FOLIOS ? "PDF page " : "page ") + p; }
function nodeFen(id){ const n = D.nodes[id]; return n && n.fen ? n.fen : null; }
function setState(){
  window.readerState = {fen: S.node ? nodeFen(S.node) : null, nodeId: S.node, page: S.page};
  if (S.diagram) window.readerState.diagram = S.diagram;
  const t = $("mtxt");
  if (!t) return;
  if (S.node) t.innerHTML = D.nodes[S.node].parent == null ? "Start position" :
    "<span class=n>" + moveHtml(S.node, true) + "</span>";
  else if (S.diagram) t.textContent = cap(diagramLabel(S.diagram));
  else t.innerHTML = "<span class=muted>No move chosen</span>";
}

/* ---------------------------------------------------------------- page */
function chapterFor(p){
  for (const c of D.chapters) if (p >= c.start && p <= c.end) return c;
  return null;
}
function say(msg){ $("pagemsg").textContent = msg || ""; }
function pageFromInput(v){
  v = String(v || "").trim().toLowerCase();
  if (!v) return null;
  const pdf = /^pdf\s*(?:page\s*)?(\d+)$/.exec(v);
  if (pdf) { const k = parseInt(pdf[1], 10); return k >= 1 && k <= D.pageCount ? k : null; }
  for (let i = 0; i < D.folios.length; i++)
    if (D.folios[i] != null && String(D.folios[i]).toLowerCase() === v) return i + 1;
  const k = /^\d+$/.test(v) ? parseInt(v, 10) : NaN;
  if (!HAS_FOLIOS && k >= 1 && k <= D.pageCount) return k;
  return null;
}
function typedPage(){
  const v = String($("pagenum").value).trim();
  if (!v || v.toLowerCase() === label(S.page).toLowerCase()) { $("pagenum").value = label(S.page); return; }
  const p = pageFromInput(v);
  if (p === null) { say("The book has no page " + v + "."); $("pagenum").value = label(S.page); return; }
  if (p !== S.page) goPage(p);
}
// Inside the browser app the page has no address of its own, so it asks the
// app to open another file; on its own it follows the link.
function openFile(href){
  if (window.CHESSBOOK_APP) {
    const m = /^([^#]+)(#.*)?$/.exec(href);
    parent.postMessage({open: m[1], hash: m[2] || ""}, "*");
  } else {
    location.href = href;
  }
}
function goPage(p, keepHash){
  p = parseInt(p, 10);
  if (isNaN(p) || p < 1 || p > D.pageCount) { $("pagenum").value = label(S.page); return; }
  say("");
  if (!(p in D.pages)) {
    const c = chapterFor(p);
    if (c && c.file && !c.empty) { openFile(c.file + "#page=" + p); }
    return;
  }
  showPage(p);
  if (!keepHash) history.replaceState(null, "", "#page=" + p);
}
function pct(v, total){ return (100 * v / total).toFixed(3) + "%"; }
function diagramName(d, p){
  if (d.label) return "Diagram " + d.label;
  return "Unnumbered diagram on " + pageName(p);
}
function showPage(p){
  const P = D.pages[p];
  S.page = p;
  const img = $("pageimg");
  img.src = "data:image/jpeg;base64," + IMG[p];
  img.alt = cap(pageName(p)) + " of the book";
  $("pagebox").style.aspectRatio = P.w + " / " + P.h;
  const ov = $("ov");
  ov.innerHTML = "";
  for (const d of P.diagrams) {
    const b = document.createElement("button");
    b.className = "diag" + (S.diagram === d.id ? " current" : "");
    b.dataset.diagram = d.id;
    const r = d.rect;
    b.style.left = pct(r[0], P.w); b.style.top = pct(r[1], P.h);
    b.style.width = pct(r[2] - r[0], P.w); b.style.height = pct(r[3] - r[1], P.h);
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
    t += ": " + lcfirst(D.words[m.status] || m.status);
    if (m.reason) t += ", because " + m.reason;
    t += ".";
    b.title = t;
    b.setAttribute("aria-label", t);
    ov.appendChild(b);
  });
  $("pagenum").value = label(p);
  $("pagenum").title = "PDF page " + p;
  $("prevpage").disabled = p <= 1;
  $("nextpage").disabled = p >= D.pageCount;
  pageState();
  renderChips();
  highlightMark(false);
  if (S.diagram && !P.diagrams.some(d => d.id === S.diagram)) closeDiagram();
  setState();
}
function pageState(){
  // the page's place in the selection: the box under the page, the notes above it and the
  // dashed outline of each diagram that the selection leaves out
  const p = S.page, P = D.pages[p], on = SEL.pageOn(p);
  $("usepage").checked = on;
  $("offpage").textContent = !P.selected ?
    "The program left this page out when it read the book, so it shows no moves here." +
    (on ? " You have ticked it again, and the next run reads it." : "") :
    (on ? "" : "You have left this page out. The next run skips it.");
  $("offpage").classList.toggle("on", !on || !P.selected);
  const off = [];
  for (const d of P.diagrams) {
    const dOn = SEL.diagOn(d.id);
    const b = document.querySelector(".diag[data-diagram='" + d.id + "']");
    if (b) {
      b.classList.toggle("excluded", !dOn);
      b.title = diagramName(d, p) + (dOn ? "" : ", left out of the selection");
      b.setAttribute("aria-label", b.title);
    }
    if (!dOn) off.push(d);
  }
  let note = "";
  if (on && off.length) {
    const named = off.filter(d => d.label);
    if (off.length === 1)
      note = (named.length ? "Diagram " + off[0].label : "The picture in the dashed outline") +
        " is left out of the selection.";
    else if (named.length === off.length)
      note = "Diagrams " + named.slice(0, -1).map(d => d.label).join(", ") + " and " +
        named[named.length - 1].label + " are left out of the selection.";
    else note = "The pictures in dashed outlines are left out of the selection.";
  }
  $("diagnote").textContent = note;
}

function linesHere(){
  return D.lineOrder.filter(id => { const L = D.lines[id]; return L.page <= S.page && S.page <= L.end_page; });
}
function renderChips(){
  const box = $("chips");
  const ids = linesHere();
  box.innerHTML = "";
  if (!ids.length) {
    box.innerHTML = "<span class=none>" + (D.lineOrder.length ? "The program found no line on this page." :
      "The program found no line in this chapter.") + "</span>";
    return;
  }
  for (const id of ids) {
    const b = document.createElement("button");
    b.className = "tl" + (S.line === id ? " on" : "");
    b.dataset.line = id;
    b.textContent = title(D.lines[id].title);
    if (S.line === id) b.setAttribute("aria-current", "true");
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
const SQ = 45, M = 14, TOP = 1, BW = M + 8 * SQ + 1;
const EMPTY = "8/8/8/8/8/8/8/8 w - - 0 1";
function boardSvg(fen, flip, uci){
  const rows = fen.split(" ")[0].split("/");
  const W = BW, H = TOP + 8 * SQ + M;
  let s = "<svg class='board' xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' " +
    "viewBox='0 0 " + W + " " + H + "' role='img' aria-label='Chess board: " + esc(fen) + "'>";
  const hl = [];
  for (let i = 0; i < 8; i++) {
    for (let f = 0; f < 8; f++) {
      const rank = 7 - i;
      const x = M + (flip ? 7 - f : f) * SQ, y = TOP + (flip ? 7 - i : i) * SQ;
      const name = "abcdefgh"[f] + (rank + 1);
      const light = (f + rank) % 2 === 1;
      s += "<rect class='" + (light ? "sl" : "sd") + "' x='" + x + "' y='" + y + "' width='" + SQ +
        "' height='" + SQ + "'/>";
      if (uci && uci.length >= 4 && (uci.slice(0, 2) === name || uci.slice(2, 4) === name)) hl.push([x, y]);
    }
  }
  s += "<rect class='bo' x='" + (M - 0.5) + "' y='" + (TOP - 0.5) + "' width='" + (8 * SQ + 1) +
    "' height='" + (8 * SQ + 1) + "' vector-effect='non-scaling-stroke'/>";
  const names = {p:"pawn", n:"knight", b:"bishop", r:"rook", q:"queen", k:"king"};
  rows.forEach((row, i) => {
    let f = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) { f += parseInt(ch, 10); continue; }
      const color = ch === ch.toUpperCase() ? "white" : "black";
      const x = M + (flip ? 7 - f : f) * SQ, y = TOP + (flip ? 7 - i : i) * SQ;
      s += "<use href='#" + color + "-" + names[ch.toLowerCase()] + "' xlink:href='#" + color + "-" +
        names[ch.toLowerCase()] + "' transform='translate(" + x + "," + y + ")'/>";
      f += 1;
    }
  });
  // the last move: an outline inside each of its two squares, like the current move on the page
  for (const [x, y] of hl)
    s += "<rect class='lm' x='" + (x + 1.5) + "' y='" + (y + 1.5) + "' width='" + (SQ - 3) + "' height='" +
      (SQ - 3) + "'/>";
  for (let k = 0; k < 8; k++) {
    const file = "abcdefgh"[flip ? 7 - k : k];
    const rank = flip ? k + 1 : 8 - k;
    s += "<text class='co' font-size='11' x='" + (M + k * SQ + SQ / 2) + "' y='" + (H - 2.5) +
      "' text-anchor='middle'>" + file + "</text>";
    s += "<text class='co' font-size='11' x='" + (M / 2 - 0.5) + "' y='" + (TOP + k * SQ + SQ / 2 + 3.5) +
      "' text-anchor='middle'>" + rank + "</text>";
  }
  return s + "</svg>";
}
function sizeCoords(root){
  // the coordinates come out at 10px on screen, whatever the size of the board
  for (const svg of (root || document).querySelectorAll("svg.board")) {
    const w = svg.getBoundingClientRect().width;
    if (!w) continue;
    const size = (10 * BW / w).toFixed(2);
    for (const t of svg.querySelectorAll(".co")) t.setAttribute("font-size", size);
  }
}
function diagramInfo(id){
  for (const p in D.pages) for (const d of D.pages[p].diagrams) if (d.id === id) return [parseInt(p, 10), d];
  return [null, null];
}
function cropInto(canvas, id){
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
  };
  if (im.complete && im.naturalWidth) draw(); else im.addEventListener("load", draw, {once: true});
  return true;
}
const PIC = "<canvas class='pic scan' aria-label='Diagram picture from the book'></canvas>";
function diagramLabel(id){
  const [p, d] = diagramInfo(id);
  if (!d) return "a diagram";
  return d.label ? "Diagram " + d.label : "the unnumbered diagram on " + pageName(p);
}
function boardFor(){
  // [kind, html or diagram id, note]
  const n = S.node ? D.nodes[S.node] : null;
  const fen = n ? nodeFen(S.node) : null;
  if (fen) return ["svg", boardSvg(fen, S.flip, n.uci), ""];
  const L = S.line ? D.lines[S.line] : null;
  if (n && n.reason) return ["empty", null, n.reason];
  if (L && L.diagram) return ["crop", L.diagram, "This line starts from " + diagramLabel(L.diagram) +
    ". Board reading (Stage 3) has not run yet, so the picture from the book stands in for the board."];
  // a line chosen but no move yet: the line's starting position
  if (!n && L && nodeFen(L.root)) return ["svg", boardSvg(nodeFen(L.root), S.flip, null), ""];
  return ["empty", null, "The board shows a position once you choose a move on the page."];
}
function renderBoard(){
  const [kind, x, note] = boardFor();
  const box = $("board");
  if (kind === "svg") box.innerHTML = x;
  else if (kind === "crop") { box.innerHTML = PIC; cropInto(box.querySelector("canvas"), x); }
  else box.innerHTML = boardSvg(EMPTY, S.flip, null);
  sizeCoords(box);
  $("boardnote").textContent = note;
  renderMini();
}
function renderMini(){
  // on a phone the small board sits in the bar at the foot of the window while the page is in
  // view, and steps aside when the panel with the large board comes into view
  const mini = $("mini"), bar = $("mbar");
  let [kind, x] = boardFor();
  if (S.diagram && !S.node) { kind = "crop"; x = S.diagram; }
  const want = S.mini === null ? !!(S.node || S.diagram) : S.mini;
  $("mboard").setAttribute("aria-pressed", String(want));
  const show = SMALL.matches && want && kind !== "empty" && !S.panelSeen;
  mini.classList.toggle("on", show);
  bar.classList.toggle("withboard", show);
  const box = $("minibox");
  if (!show) { box.innerHTML = ""; return; }
  if (kind === "svg") box.innerHTML = x;
  else { box.innerHTML = PIC; cropInto(box.querySelector("canvas"), x); }
}

/* ---------------------------------------------------------------- moves */
function cont(id){
  // the move that continues the line from this node in the move list (main moves follow main moves)
  const n = D.nodes[id];
  if (!n) return null;
  if (n.main) { for (const c of n.children) if (D.nodes[c].main) return c; return null; }
  return n.children.length ? n.children[0] : null;
}
function nextMove(id){
  // the move the right arrow goes to: the continuation, or else the first variation
  const c = cont(id);
  if (c) return c;
  const n = D.nodes[id];
  return n && n.children.length ? n.children[0] : null;
}
function siblings(id){
  const n = D.nodes[id];
  return n && n.parent != null ? D.nodes[n.parent].children : [id];
}
function moveNumber(id, needNumber){
  const n = D.nodes[id];
  return n.number != null && (needNumber || !n.black) ? n.number + (n.black ? "…" : ".") : "";
}
function decoded(n){ return !!(n.san || (n.status === "failed" && n.assumed)); }
function moveBody(id){
  const n = D.nodes[id];
  if (n.san) return n.san;
  if (n.status === "failed" && n.assumed) return n.assumed;
  return n.raw ? shown(n.raw) : "…";
}
function moveBodyHtml(id){
  const n = D.nodes[id];
  return decoded(n) || !n.raw ? esc(moveBody(id)) : shownHtml(n.raw);
}
function moveText(id, needNumber){ return moveNumber(id, needNumber) + moveBody(id); }
function moveHtml(id, needNumber){ return esc(moveNumber(id, needNumber)) + moveBodyHtml(id); }
function mvHtml(id, needNumber){
  const n = D.nodes[id];
  let tip = D.words[n.status] || n.status;
  if (n.status === "failed" && n.assumed) tip += "; the program assumed " + n.assumed;
  if (n.raw && n.status !== "ok") tip += "; the text recognition read “" + shown(n.raw) + "”";
  const num = moveNumber(id, needNumber);
  const cls = "mv" + (decoded(n) ? "" : " raw");
  return "<button class='" + cls + "' tabindex='-1' data-node='" + id + "' title='" + esc(tip) + "'>" +
    (n.status === "failed" ? "<i class='dot st-failed'></i>" : "") +
    (num ? "<span class=mn>" + esc(num) + "</span>" : "") + "<span class=san>" + moveBodyHtml(id) +
    "</span></button>";
}
function renderLine(id, need){
  // the moves that follow node id, each variation on its own indented line; a white move and the
  // black reply that follows it stay together on one line
  let out = "";
  while (id) {
    const c = cont(id);
    const others = D.nodes[id].children.filter(x => x !== c);
    if (!c) { for (const v of others) out += variation(v); break; }
    const r = cont(c);
    if (!others.length && !D.nodes[c].black && r && D.nodes[r].black) {
      out += "<span class=pair>" + mvHtml(c, need) + " " + mvHtml(r, false) + "</span> ";
      need = false;
      for (const v of D.nodes[c].children.filter(x => x !== r)) { out += variation(v); need = true; }
      id = r;
    } else {
      out += mvHtml(c, need) + " ";
      need = false;
      for (const v of others) { out += variation(v); need = true; }
      id = c;
    }
  }
  return out;
}
function variation(v){
  const n = D.nodes[v], r = cont(v);
  if (!n.black && r && D.nodes[r].black) {
    const rOthers = n.children.filter(x => x !== r);
    let out = "<span class=pair>" + mvHtml(v, true) + " " + mvHtml(r, false) + "</span> ";
    for (const w of rOthers) out += variation(w);
    return "<span class=var>" + out + renderLine(r, rOthers.length > 0) + "</span>";
  }
  return "<span class=var>" + mvHtml(v, true) + " " + renderLine(v, false) + "</span>";
}
function lineMeta(L){
  // one sentence: where the line starts, from which position, and how it ends
  let from = "";
  if (L.diagram) {
    const [p, d] = diagramInfo(L.diagram);
    from = d && !d.label && p === L.page ? "the unnumbered diagram" : diagramLabel(L.diagram);
  } else if (L.start_fen && L.start_fen.split(" ")[0] === "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")
    from = "the initial position";
  else if (L.start_fen) from = "a set position";
  let s = "The line starts" + (from ? " from " + esc(from) : "") + " on " + esc(pageName(L.page));
  const parts = [];
  if (L.end_page !== L.page) parts.push("runs to " + esc(pageName(L.end_page)));
  if (L.result) parts.push("ends <span class=n>" + esc(L.result) + "</span>");
  if (parts.length) s += (parts.length > 1 ? ", " + parts[0] + " and " + parts[1] : " and " + parts[0]);
  s += ".";
  if (L.event && L.title.indexOf(L.event) < 0) s = "The book names the event as " + esc(L.event) + ". " + s;
  return s;
}
function renderTree(){
  const L = S.line ? D.lines[S.line] : null;
  const box = $("tree");
  if (!L) {
    box.innerHTML = "<span class=none>No line is chosen. A click on a move on the page chooses its line.</span>";
    $("linetitle").textContent = "No line chosen"; $("linemeta").innerHTML = "";
    return;
  }
  const root = D.nodes[L.root];
  const first = root.children.length ? "" : "<span class=none>This line holds no moves.</span>";
  box.innerHTML = "<button class='mv start" + (S.node === L.root ? " cur" : "") + "' tabindex='-1' data-node='" +
    L.root + "' title='Start position'>Start</button>" + renderLine(L.root, true) + first;
  $("linetitle").textContent = title(L.title);
  $("linemeta").innerHTML = lineMeta(L);
}
function fitTree(){
  // on wide screens the move list gives way to the comment, but keeps at least three rows, and it
  // is cut at a whole row so that no row shows only in part
  const box = $("tree"), sec = box.parentElement;
  box.style.height = ""; sec.style.minHeight = "";
  if (SMALL.matches) return;
  sec.style.minHeight = (Math.min(3 * ROW, box.scrollHeight) + 24) + "px";
  const h = box.clientHeight;
  if (box.scrollHeight > h + 1) box.style.height = Math.max(ROW, Math.floor(h / ROW) * ROW) + "px";
}
function markTreeCurrent(scroll){
  const box = $("tree");
  for (const el of box.querySelectorAll(".mv.cur")) { el.classList.remove("cur"); el.removeAttribute("aria-current"); }
  for (const el of box.querySelectorAll(".mv[tabindex='0']")) el.tabIndex = -1;
  const el = S.node ? box.querySelector(".mv[data-node='" + S.node + "']") : null;
  const stop = el || box.querySelector(".mv");
  if (stop) stop.tabIndex = 0;  // the move list is one stop for the Tab key; the arrow keys move inside it
  if (!el) return;
  el.classList.add("cur");
  el.setAttribute("aria-current", "true");
  if (!scroll || box.scrollHeight <= box.clientHeight + 1) return;
  // scroll the move list inside its own box, never the window, and stop at a whole row
  const r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
  if (r.top < b.top || r.bottom > b.bottom) {
    const top = r.top - b.top + box.scrollTop;
    box.scrollTop = Math.max(0, Math.floor((top - box.clientHeight / 3) / ROW) * ROW);
  }
}
function layoutPanel(scroll){ fitTree(); markTreeCurrent(scroll); }
function readings(n){
  const all = [n.san || n.assumed].concat(n.alternatives || []).filter(Boolean);
  return all.map(x => "<span class=n>" + esc(x) + "</span>").join(", ");
}
function statusLines(n){
  // the status of a move in words: [dot class, label html, [detail sentences]]
  const out = [];
  const k = 1 + (n.alternatives ? n.alternatives.length : 0);
  let lab = esc(D.words[n.status] || n.status);
  if ((n.status === "guessed" || n.status === "ambiguous") && n.alternatives && n.alternatives.length)
    lab = "Chosen from " + words(k) + (n.status === "ambiguous" ? " equal" : "") + " readings: " + readings(n);
  if (n.raw && n.status !== "ok")
    out.push("The text recognition read “<span class=n>" + shownHtml(n.raw) + "</span>”.");
  if (n.status === "failed" && n.raw)
    out.push(n.assumed ? "The program assumed <span class=n>" + esc(n.assumed) +
      "</span> here so that the line goes on." : "The program could not read this move.");
  if (n.reason) out.push(esc(n.reason));
  if (/[\u0000-\u001f]/.test(n.raw || ""))
    out.push("The box " + PLACEHOLDER + " stands for a sign that the text recognition could not name, " +
      "such as a figurine.");
  return [n.status, lab, out];
}
function reading(){ return document.body.classList.contains("reading"); }
function renderInfo(){
  const n = S.node ? D.nodes[S.node] : null;
  const box = $("info");
  let h = "";
  if (n) {
    const L = D.lines[n.line];
    if (n.comment) h += "<p class=comment>" + notation(n.comment) + "</p>";
    if (S.node === L.root || n.parent == null) {
      if (L.diagram && !L.start_fen)
        h += "<div class='status small muted'><p><i class=dot></i>" + esc(D.words.waiting) + "</p></div>";
    } else if (n.status !== "ok" || reading()) {
      // a move read without doubt needs no word, except while Show reading is on
      const [st, lab, more] = statusLines(n);
      h += "<div class='status small muted'><p><i class='dot st-" + esc(st) + "'></i>" + lab + "</p>" +
        more.map(x => "<p>" + x + "</p>").join("") + "</div>";
    }
  }
  box.innerHTML = h;
  $("infosec").hidden = !h;
}

function selectNode(id, opts){
  opts = opts || {};
  const n = D.nodes[id];
  if (!n) return;
  const treeFocus = $("tree").contains(document.activeElement);
  if (S.diagram) closeDiagram();
  const lineChanged = S.line !== n.line;
  S.node = id; S.line = n.line;
  const L = D.lines[n.line];
  const target = n.page || L.page;
  // a click on a box keeps its page, even when the move belongs to another page as well
  if (!opts.fromPage && target && target !== S.page && (target in D.pages)) showPage(target);
  if (lineChanged) { renderTree(); renderChips(); }
  renderBoard();
  renderInfo();
  layoutPanel(opts.scrollTree !== false);
  highlightMark(!!opts.scrollPage);
  if (treeFocus) { const el = $("tree").querySelector(".mv.cur"); if (el) el.focus({preventScroll: true}); }
  history.replaceState(null, "", "#node=" + id);
  setState();
}
function firstLineHere(){
  return linesHere()[0] || D.lineOrder[0];
}
function step(dir){
  if (!S.node) {
    const lid = S.line || firstLineHere();
    if (lid) selectNode(D.lines[lid].root, {scrollPage: true});
    return;
  }
  const n = D.nodes[S.node];
  if (dir < 0 && n.parent != null) selectNode(n.parent, {scrollPage: true});
  if (dir > 0) { const c = nextMove(S.node); if (c) selectNode(c, {scrollPage: true}); }
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
  while ((c = nextMove(id))) id = c;
  selectNode(id, {scrollPage: true});
}
function defaultView(){
  // no move chosen: the first line on the page, at its starting position
  S.node = null;
  S.line = linesHere()[0] || null;
  renderChips(); renderTree(); renderBoard(); renderInfo(); layoutPanel(false); highlightMark(false);
  setState();
}

/* ---------------------------------------------------------------- diagrams */
function showDiagram(id){
  const [p, d] = diagramInfo(id);
  if (!d) return;
  S.diagram = id;
  for (const el of document.querySelectorAll(".diag.current")) el.classList.remove("current");
  const el = document.querySelector(".diag[data-diagram='" + id + "']");
  if (el) el.classList.add("current");
  // the move list shows this diagram's first line, with no move chosen
  S.node = null;
  S.line = (d.lines && d.lines.find(l => D.lines[l])) || null;
  renderTree(); renderChips();
  renderBoard(); renderInfo(); highlightMark(false);
  $("board").innerHTML = "";  // the diagram view takes the board's place
  const box = $("dpanel");
  let h = PIC;
  h += "<div class=dhead><h3>" + esc((d.label ? "Diagram " + d.label : "Unnumbered diagram") + ", " +
    pageName(p)) + "</h3><button class=tb id=dclose>Close</button></div>";
  const lines = [];
  if (D.notPosition.indexOf(d.kind) >= 0)
    lines.push("The program takes this picture for " + esc(D.kindWords[d.kind]) + ", so no line starts from it.");
  else {
    if (d.kind !== "board" && D.kindWords[d.kind])
      lines.push("The program takes this picture for " + esc(D.kindWords[d.kind]) + ".");
    lines.push(d.fen ? "Board reading (Stage 3) read this position as <code>" + esc(d.fen) + "</code>." :
      "Board reading (Stage 3) has not run yet, so the program does not know this position.");
  }
  if (!d.selected) lines.push("The program left this diagram out when it read the book.");
  if (d.after_node && D.nodes[d.after_node])
    lines.push("The program places this diagram after <a href='#node=" + esc(d.after_node) + "' data-goto='" +
      esc(d.after_node) + "' class=n>" + moveHtml(d.after_node, true) + "</a>.");
  lines.push("<span id=dpageoff></span>");
  h += "<div class='small muted'>" + lines.map(x => "<p>" + x + "</p>").join("") + "</div>";
  h += "<label class=use><input type=checkbox id=usediag autocomplete=off> Use this diagram</label>";
  // the lines that start from the diagram, except the one the panel already names
  const others = (d.lines || []).filter(l => D.lines[l] && l !== S.line);
  if (others.length) {
    h += "<div><p class='small muted'>" + (others.length === 1 ? "Another line starts from the diagram:" :
      "Other lines start from the diagram:") + "</p><ul class=links>";
    for (const lid of others)
      h += "<li><a href='#line=" + esc(lid) + "' data-goto='" + esc(D.lines[lid].root) + "'>" +
        esc(title(D.lines[lid].title)) + "</a></li>";
    h += "</ul></div>";
  }
  box.innerHTML = h;
  box.hidden = false;
  $("boardarea").classList.add("diagram");
  cropInto(box.querySelector("canvas"), id);
  diagramState(id);
  $("dclose").addEventListener("click", () => { closeDiagram(); renderBoard(); layoutPanel(false); });
  $("usediag").addEventListener("change", (e) => {
    // ticking a diagram on a page that is left out uses the page again, as on the contents page
    if (e.target.checked && !SEL.pageOn(p)) SEL.setPages(p, p, true);
    SEL.setDiag(id, e.target.checked);
    pageState(); diagramState(id); selNote();
  });
  for (const b of box.querySelectorAll("[data-goto]"))
    b.addEventListener("click", (e) => { e.preventDefault(); selectNode(b.dataset.goto, {scrollPage: true}); });
  layoutPanel(false);
  setState();
}
function diagramState(id){
  const [p] = diagramInfo(id);
  const u = $("usediag");
  if (!u) return;
  u.checked = SEL.diagOn(id);
  $("dpageoff").textContent = SEL.pageOn(p) ? "" :
    "You have left this page out, so the diagram is left out as well. A tick uses the page and the diagram again.";
  $("dpageoff").parentElement.hidden = SEL.pageOn(p);
}
function closeDiagram(){
  S.diagram = null;
  $("dpanel").hidden = true;
  $("dpanel").innerHTML = "";
  $("boardarea").classList.remove("diagram");
  for (const el of document.querySelectorAll(".diag.current")) el.classList.remove("current");
  setState();
}
function selNote(){
  $("selnote").textContent = SEL.stored() ?
    "You have changed the selection. The contents page shows the change and copies it for the chat." : "";
}
function setReading(on){
  document.body.classList.toggle("reading", on);
  const b = $("showread");
  b.setAttribute("aria-pressed", String(on));
  b.textContent = on ? "Hide reading" : "Show reading";
  try { localStorage.setItem("chessbook-reading", on ? "1" : "0"); } catch (e) { /* no storage */ }
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
  $("ov").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.node) { selectNode(b.dataset.node, {fromPage: true}); return; }
    if (b.dataset.diagram) { showDiagram(b.dataset.diagram); return; }
    if (b.dataset.mark) {
      const m = D.pages[S.page].marks[parseInt(b.dataset.mark, 10)];
      $("info").innerHTML = "<p class=comment>“<span class=n>" + shownHtml(m.raw) + "</span>”</p>" +
        "<div class='status small muted'><p><i class=dot></i>" + esc(D.words.unattached) + "</p><p>" +
        "The program found this move in the text but placed it in no line" +
        (m.reason ? ", because " + esc(m.reason) : "") + ".</p></div>";
      $("infosec").hidden = false;
      layoutPanel(false);
    }
  });
  $("chips").addEventListener("click", (e) => {
    const b = e.target.closest("[data-line]");
    if (b) selectNode(D.lines[b.dataset.line].root, {scrollPage: true});
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
    S.mini = !(S.mini === null ? !!(S.node || S.diagram) : S.mini); renderMini();
  });
  $("mmoves").addEventListener("click", () => $("panel").scrollIntoView({block: "start"}));
  if ("IntersectionObserver" in window)
    new IntersectionObserver((es) => {
      const seen = es[es.length - 1].isIntersecting;
      if (seen !== S.panelSeen) { S.panelSeen = seen; renderMini(); }
    }, {rootMargin: "0px 0px -64px 0px"}).observe($("panel"));
  $("prevpage").addEventListener("click", () => goPage(S.page - 1));
  $("nextpage").addEventListener("click", () => goPage(S.page + 1));
  $("pagenum").addEventListener("keydown", (e) => { if (e.key === "Enter") { typedPage(); e.preventDefault(); } });
  $("pagenum").addEventListener("change", typedPage);
  $("pagenum").addEventListener("focus", () => $("pagenum").select());
  $("showread").addEventListener("click", () => {
    setReading(!reading()); renderInfo(); layoutPanel(false);
  });
  $("zoom").addEventListener("click", () => {
    const z = $("pagescroll").classList.toggle("zoom");
    $("zoom").textContent = z ? "Fit page" : "Enlarge page";
  });
  $("usepage").addEventListener("change", (e) => {
    SEL.setPages(S.page, S.page, e.target.checked); pageState();
    if (S.diagram) diagramState(S.diagram);
    selNote();
  });
  const pgn = $("pgnbtn");
  if (!D.pgn) pgn.disabled = true;
  pgn.addEventListener("click", () => {
    if (!D.pgn) return;
    const blob = new Blob([D.pgn], {type: "application/x-chess-pgn"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = D.pgnName;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  });
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || e.altKey || e.ctrlKey || e.metaKey) return;
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
  let resizing = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(resizing);
    resizing = requestAnimationFrame(() => { sizeCoords(document); layoutPanel(false); });
  });
  SMALL.addEventListener && SMALL.addEventListener("change", () => { renderBoard(); layoutPanel(false); });
  // the browser may restore the state of the boxes when the reader comes back to this page: the
  // stored selection wins
  window.addEventListener("pageshow", () => { if (S.page) pageState(); if (S.diagram) diagramState(S.diagram); });
  let rd = false;
  try { rd = localStorage.getItem("chessbook-reading") === "1"; } catch (e) { rd = false; }
  setReading(rd);
  let start = D.chapter.start;
  while (!(start in D.pages) && start <= D.chapter.end) start++;
  showPage(start);
  // a link to a page (from the contents page, or the page arrows at the end of a chapter) shows
  // the first line on that page, as an opening without a link does
  if (!fromHash() || (!S.node && !S.diagram)) defaultView();
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
<style>__STYLE____CHAPTER_CSS__</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>__PIECES__</defs></svg>
<header class="bar">
<div class="where"><span class="book">__BOOK__</span><h1>__H1__</h1></div>
<nav class="tools" aria-label="Pages">
<span class="pnav"><button class="ib" id="prevpage" aria-label="Previous page" title="Previous page (Page Up)">__ICON_BACK__</button>
<input id="pagenum" type="text" inputmode="numeric" autocomplete="off" spellcheck="false" aria-label="Page number">
<button class="ib" id="nextpage" aria-label="Next page" title="Next page (Page Down)">__ICON_FWD__</button></span>
<button class="tb" id="showread" aria-pressed="false">Show reading</button>
<a class="nav" href="index.html">Contents</a>
</nav>
</header>
<div class="notes small"><p id="pagemsg" role="status"></p><p class="muted" id="selnote" role="status"></p></div>
<main class="reader">
<section class="pagecol" aria-label="Book page">
<p class="offpage small" id="offpage"></p>
<p class="diagnote small muted" id="diagnote"></p>
<div class="key small muted">
<div class="help"><p class="mouse">A click on a move or a diagram shows it in the panel. The left and right arrow keys step through the moves, the up and down arrow keys switch between the moves the book gives at a branch, and Page Up and Page Down turn the pages.</p>
<p class="touch">A tap on a move or a diagram shows it on the small board and in the panel below the page.</p></div>
<div class="legend" aria-label="What the outlines and marks mean">
<span class="ls">A move with no outline is read without doubt.</span>
<span><i class="k doubt"></i>Chosen from several readings</span>
<span><i class="k fail"></i><i class="dot st-failed"></i>Not read</span>
<span><i class="k wait"></i><i class="u"></i>Waits for board reading (Stage 3)</span>
<span><i class="k unatt"></i>Placed in no line</span>
<span><i class="k off"></i>Diagram left out</span>
</div>
</div>
<div class="pagescroll" id="pagescroll">
<div class="pagebox" id="pagebox"><img class="scan" id="pageimg" alt=""><div class="ov" id="ov"></div></div>
</div>
<div class="pagefoot small">
<div class="onpage" aria-label="Lines on this page"><span class="lab">On this page</span><span class="onlines" id="chips"></span></div>
<div class="row"><label class="use"><input type="checkbox" id="usepage" autocomplete="off"> Use this page</label>
<button class="tb" id="zoom">Enlarge page</button></div>
<nav class="chnav" aria-label="Chapters">__CHNAV__</nav>
<div class="pgn">__PGN__</div>
</div>
</section>
<aside class="panel" id="panel" aria-label="Board and moves">
<div class="boardarea" id="boardarea">
<div class="boardwrap" id="board"></div>
<p class="boardnote small muted" id="boardnote"></p>
<div class="dpanel" id="dpanel" hidden></div>
</div>
<div class="controls" role="group" aria-label="Moves">
<button class="ib" id="bstart" title="Start of the line (Home)" aria-label="Start of the line">__ICON_START__</button>
<button class="ib" id="bback" title="Previous move (left arrow)" aria-label="Previous move">__ICON_BACK__</button>
<button class="ib" id="bfwd" title="Next move (right arrow)" aria-label="Next move">__ICON_FWD__</button>
<button class="ib" id="bend" title="End of the line (End)" aria-label="End of the line">__ICON_END__</button>
<span class="gap"></span>
<button class="ib" id="bflip" title="Turn the board round" aria-label="Turn the board round">__ICON_FLIP__</button>
</div>
<section class="sec">
<h2 class="ltitle" id="linetitle">No line chosen</h2>
<p class="small muted" id="linemeta"></p>
</section>
<section class="sec treesec"><div class="tree" id="tree" aria-label="Moves of the line"></div></section>
<section class="sec" id="infosec" hidden><div class="info" id="info"></div></section>
</aside>
</main>
<div class="mbar" id="mbar" aria-label="Current move">
<div class="mini" id="mini" aria-label="Small board"><div id="minibox"></div></div>
<div class="mside"><span class="mtxt" id="mtxt"></span>
<span class="mbtns"><button class="ib" id="mback" aria-label="Previous move">__ICON_BACK__</button>
<button class="ib" id="mfwd" aria-label="Next move">__ICON_FWD__</button>
<button class="tb" id="mboard" aria-pressed="false">Board</button>
<button class="tb" id="mmoves">Moves</button></span></div>
</div>
<script type="application/json" id="data">__DATA__</script>
<script type="application/json" id="images">__IMAGES__</script>
<script>__SELJS__</script>
<script>__JS__</script>
</body>
</html>
"""


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
            lines[L["id"]]["event"] = (L.get("header") or {}).get("event")
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
        "chapters": chapters, "pageCount": book["page_count"], "folios": _folios(book),
        "pages": pages, "lines": lines,
        "lineOrder": order, "nodes": nodes, "pgn": pgn_text, "pgnName": ch["pgn"],
        "words": STATUS_WORDS, "kindWords": KIND_WORDS,
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


def pgn_block(games, waiting):
    """The PGN link under the book page, with one sentence about it."""
    if not games:
        return ('<button class="tb" id="pgnbtn" disabled>Download PGN</button>'
                '<span class="muted">No line of this chapter is decoded yet, so there is no '
                'PGN file.</span>')
    note = f"The file holds the {_plural(games, 'decoded line')} of this chapter"
    if waiting:
        note += (f" and leaves out the {_plural(waiting, 'line')} that "
                 f"{'waits' if waiting == 1 else 'wait'} for board reading")
    return (f'<button class="tb" id="pgnbtn">Download PGN</button>'
            f'<span class="muted">{html.escape(note)}.</span>')


def chapter_html(book, ch, images, pgn_text, pgn_info):
    data = chapter_data(book, ch, pgn_text)
    chs = [c for c in book["chapters"] if c["end"] >= c["start"]]
    pos = next(i for i, c in enumerate(chs) if c["index"] == ch["index"])
    nav = []
    if pos > 0:
        nav.append(f'<a class="nav" href="{chs[pos - 1]["file"]}">Previous chapter</a>')
    if pos + 1 < len(chs):
        nav.append(f'<a class="nav" href="{chs[pos + 1]["file"]}">Next chapter</a>')
    games, waiting = pgn_info
    rep = {
        "__TITLE__": html.escape(f"{ch['label']} Reader"),
        "__BOOK__": html.escape(book["title"]),
        "__H1__": html.escape(chapter_heading(ch)),
        "__CHNAV__": "".join(nav),
        "__PGN__": pgn_block(games, waiting),
        "__STYLE__": style.page_css(),
        "__CHAPTER_CSS__": CHAPTER_CSS,
        "__ICON_START__": style.icon("start"),
        "__ICON_BACK__": style.icon("back"),
        "__ICON_FWD__": style.icon("forward"),
        "__ICON_END__": style.icon("end"),
        "__ICON_FLIP__": style.icon("flip"),
        "__PIECES__": _pieces_defs(),
        "__SELJS__": SELECTION_JS,
        "__JS__": CHAPTER_JS,
        # the data last, so that no placeholder inside the book's text is replaced
        "__DATA__": _json_script(data),
        "__IMAGES__": _json_script(images),
    }
    out = CHAPTER_HTML
    for k, v in rep.items():
        out = out.replace(k, v)
    return out


# ---------------------------------------------------------------- contents page

INDEX_CSS = r"""
.wrap{max-width:1080px;margin:0 auto;padding:48px 32px 64px}
.head,.summary{max-width:64ch}
.lede{margin-top:8px}
.how{margin-top:8px;color:var(--muted)}
.actions{position:sticky;top:0;z-index:5;background:var(--bg);display:flex;flex-wrap:wrap;
align-items:center;gap:8px 16px;margin-top:32px;padding:12px 0;border-top:1px solid var(--line);
border-bottom:1px solid var(--line)}
.acts{display:flex;flex-wrap:wrap;row-gap:8px}
.acts .tb{padding:0 16px;border-left:1px solid var(--line)}
.acts .tb:first-child{padding-left:0;border-left:0}
.actions .msg{flex:1 1 280px;text-align:right}
.actions .msg:empty{display:none}
.summary{margin:24px 0 0}
.cols,.chapter summary{display:grid;grid-template-columns:24px minmax(0,1fr) repeat(5,72px);align-items:baseline}
.cols{margin:24px 0 0;padding:0 64px 8px 30px}
.cols span{text-align:right}
.chapters{list-style:none;margin:0;padding:0;border-bottom:1px solid var(--line)}
.cols + .chapters{margin-top:0}
.summary + .chapters{margin-top:24px}
.chapter{position:relative;border-top:1px solid var(--line);scroll-margin-top:64px}
.chapter .ccb{position:absolute;left:0;top:21px}
.chapter .read{position:absolute;right:0;top:16px}
.chapter .noread{position:absolute;right:0;top:18px}
.chapter summary{list-style:none;cursor:pointer;padding:16px 64px 16px 30px}
.chapter summary::-webkit-details-marker{display:none}
.chapter summary::marker{content:""}
.chev{width:14px;height:14px;fill:none;stroke:var(--muted);stroke-width:1.25;stroke-linecap:round;
stroke-linejoin:round;transition:transform .15s;align-self:start;margin-top:4.5px;grid-row:1}
details[open] > summary .chev{transform:rotate(90deg)}
.ctitle{grid-column:2;display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 16px}
.ctitle h2{font-size:17px}
.cn{text-align:right}
.ccount{grid-column:2;grid-row:2;margin-top:2px;position:absolute;width:1px;height:1px;overflow:hidden;
clip:rect(0 0 0 0);white-space:nowrap}
.chapter summary:hover h2{color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(112px,1fr));gap:24px 16px;
padding:8px 0 32px 30px}
.pg{min-width:0}
.thumb{position:relative;width:100%;outline:1px solid var(--line)}
.thumb img{display:block;width:100%;height:auto}
.pg.off .thumb img{opacity:.3}
.thumb .d{position:absolute;padding:0;margin:0;border:1px solid color-mix(in srgb,var(--fg) 40%,transparent);
border-radius:0;background:none;cursor:pointer;min-width:0}
.thumb .d::before{content:"";position:absolute;left:50%;top:50%;width:max(100%,24px);height:max(100%,24px);
transform:translate(-50%,-50%)}
.thumb .d.off{border:1px dashed var(--muted)}
.thumb .d:hover,.thumb .d.off:hover{border:1px solid var(--accent)}
.cap{display:flex;align-items:center;gap:8px;margin-top:8px;font-size:13px}
.pg.off .cap a{color:var(--muted)}
.pgnote{margin-top:2px}
.pgnote:empty{display:none}
@media (max-width:859px){
.cols,.cn{display:none}
.chapter summary{grid-template-columns:24px minmax(0,1fr)}
.ccount{position:static;width:auto;height:auto;overflow:visible;clip:auto;white-space:normal}}
@media (max-width:700px){
.wrap{padding:32px 16px 48px}
.actions{position:static}
.actions .msg{flex-basis:100%;text-align:left}
.acts{column-gap:24px}
.acts .tb{padding:0;border-left:0}
.chapter summary{padding-right:48px}
.grid{grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:16px 12px;padding-left:0}}
"""

INDEX_JS = r"""
(function(){
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const kinds = {}, info = {};
for (const p of D.pages) for (const d of p.diagrams) {
  kinds[d.id] = d.kind; info[d.id] = Object.assign({page: p.page, folio: p.folio}, d);
}
const SEL = makeSelection(D.selection, {pdf: D.pdf, pageCount: D.pageCount, base: D.selBase,
  kinds: kinds, excludedKinds: D.excludedKinds, title: D.title});
const $ = (id) => document.getElementById(id);
const NUMBER_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
function pageName(p, folio){ return folio != null ? "page " + folio : (D.hasFolios ? "PDF page " : "page ") + p; }
function diagName(id){
  const d = info[id];
  return d.label ? "Diagram " + d.label : "The unnumbered diagram on " + pageName(d.page, d.folio);
}
function offNote(ids){
  // which diagrams of a page are left out, in one sentence
  if (!ids.length) return "";
  const named = ids.every(id => info[id].label);
  if (ids.length === 1) return (named ? "Diagram " + info[ids[0]].label : "One diagram") + " is left out.";
  if (named) {
    const labs = ids.map(id => info[id].label);
    return "Diagrams " + labs.slice(0, -1).join(", ") + " and " + labs[labs.length - 1] + " are left out.";
  }
  return (ids.length < NUMBER_WORDS.length ? NUMBER_WORDS[ids.length] : ids.length) + " diagrams are left out.";
}
function defaultMsg(){
  return SEL.stored() ? "You have changed the selection. This browser keeps the change until you copy it." :
    "The selection is the one the program used for this run.";
}
function refresh(){
  for (const el of document.querySelectorAll(".pg")) {
    const p = parseInt(el.dataset.page, 10), on = SEL.pageOn(p);
    el.classList.toggle("off", !on);
    el.querySelector(".pcb").checked = on;
    const off = [];
    for (const b of el.querySelectorAll(".thumb .d")) {
      const id = b.dataset.id, dOn = SEL.diagOn(id);
      b.classList.toggle("off", !dOn);
      b.setAttribute("aria-pressed", String(dOn));
      b.title = diagName(id) + (dOn ? " is used. A click leaves it out." : " is left out. A click uses it.");
      b.setAttribute("aria-label", diagName(id));
      if (!dOn) off.push(id);
    }
    const note = el.querySelector(".pgnote");
    note.textContent = on ? offNote(off) : "The page is left out.";
  }
  for (const el of document.querySelectorAll(".ccb")) {
    const a = parseInt(el.dataset.start, 10), b = parseInt(el.dataset.end, 10);
    let on = 0, n = 0;
    for (let p = a; p <= b; p++) { n++; if (SEL.pageOn(p)) on++; }
    el.checked = on === n && n > 0; el.indeterminate = on > 0 && on < n;
  }
}
function say(text){ $("msg").textContent = text || defaultMsg(); }
document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.classList.contains("pcb")) { const p = parseInt(t.dataset.page, 10); SEL.setPages(p, p, t.checked); }
  else if (t.classList.contains("ccb")) SEL.setPages(parseInt(t.dataset.start, 10), parseInt(t.dataset.end, 10), t.checked);
  else return;
  refresh(); say();
});
document.addEventListener("click", (e) => {
  const b = e.target.closest(".thumb .d");
  if (!b) return;
  const id = b.dataset.id, p = info[id].page, on = !SEL.diagOn(id);
  if (on && !SEL.pageOn(p)) SEL.setPages(p, p, true);
  SEL.setDiag(id, on);
  refresh();
  say(diagName(id) + (info[id].label ? " on " + pageName(p, info[id].folio) : "") +
    (on ? " is now used." : " is now left out."));
});
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
  say(ok ? "The selection is on the clipboard, ready to paste into the chat." :
    "The browser refused to copy, so you need to download selection.json and paste its text into the chat.");
});
$("dlbtn").addEventListener("click", () => {
  const blob = new Blob([SEL.text() + "\n"], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "selection.json";
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  say("The browser saves the selection as selection.json.");
});
$("resetbtn").addEventListener("click", () => {
  SEL.reset(); refresh(); say("The selection is again the one the program used for this run.");
});
window.selectionText = SEL.text;
refresh(); say();
// the browser may restore the ticks of the boxes when the reader comes back to this page: the
// stored selection wins
window.addEventListener("pageshow", () => { refresh(); });
})();
"""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__STYLE____INDEX_CSS__</style>
</head>
<body>
<main class="wrap">
<header class="head">
<h1>__H1__</h1>
<p class="lede">__LEDE__</p>
<p class="how">__HOW__</p>
</header>
<div class="actions" role="group" aria-label="Selection">
<div class="acts"><button class="tb" id="copybtn">Copy selection</button><button class="tb" id="dlbtn">Download selection.json</button><button class="tb" id="resetbtn">Undo changes</button></div>
<span class="msg small muted" id="msg" role="status"></span>
</div>
<p class="summary">__SUMMARY__</p>
__COLS__
<ol class="chapters">
__CHAPTERS__
</ol>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>__SELJS__</script>
<script>__JS__</script>
</body>
</html>
"""


def _n(k):
    """A figure in tabular numerals, with thousands separated."""
    return f'<span class="num">{k:,}</span>'


COUNT_COLUMNS = ("Lines", "Read", "Chosen", "Not read", "Waiting")


def _counts(c):
    """A chapter's counts: [(figure, words), ...] in the order of COUNT_COLUMNS."""
    m = c["moves"]
    doubt = m.get("guessed", 0) + m.get("ambiguous", 0) + m.get("inserted", 0)
    return [(c["lines"], "line" if c["lines"] == 1 else "lines"),
            (m.get("ok", 0), "move read" if m.get("ok", 0) == 1 else "moves read"),
            (doubt, "chosen from several readings"),
            (m.get("failed", 0), "not read"),
            (m.get("waiting", 0), "waiting for board reading")]


def _counts_line(c):
    """One muted line of a chapter's counts, leaving out every figure that is 0
    (on narrow screens, and for screen readers on wide ones)."""
    return " · ".join(f"{_n(k)} {html.escape(w)}" for k, w in _counts(c) if k)


def _count_cells(c):
    """The same counts as five right-aligned columns of figures (wide screens)."""
    return "".join(f'<span class="cn small num" aria-hidden="true" title="{k:,} {html.escape(w)}">{k:,}</span>'
                   for k, w in _counts(c))


def index_html(book, thumbs, sizes, app=False):
    e = html.escape
    sel = book["selection"]
    total = book["stats"]
    folios = _folios(book)
    m = total["moves"]
    doubt = m.get("guessed", 0) + m.get("ambiguous", 0) + m.get("inserted", 0)
    lines = total["lines"]
    summary = f"The program assembled {_n(lines)} {'line' if lines == 1 else 'lines'}"
    if total["games"] + total["fragments"] == lines and lines:
        summary += (f", of which {_n(total['games'])} {'is a game' if total['games'] == 1 else 'are games'} "
                    f"and {_n(total['fragments'])} "
                    f"{'is a fragment' if total['fragments'] == 1 else 'are fragments'}")
    summary += (f". Of their moves, {_n(m.get('ok', 0))} {'is' if m.get('ok', 0) == 1 else 'are'} read "
                f"without doubt, {_n(doubt)} {'is' if doubt == 1 else 'are'} chosen from several "
                f"readings, {_n(m.get('failed', 0))} {'is' if m.get('failed', 0) == 1 else 'are'} not "
                f"read and {_n(m.get('waiting', 0))} {'waits' if m.get('waiting', 0) == 1 else 'wait'} "
                f"for board reading (Stage 3).")
    parts = []
    by_page = {p["page"]: p for p in book["pages"]}
    for ch in book["chapters"]:
        if ch["end"] < ch["start"]:
            continue
        size = sizes.get(ch["index"])
        heading = chapter_heading(ch)
        link = (f'<a class="read nav" href="{e(ch["file"])}">Open</a>' if size or app else
                '<span class="noread small muted">No reader yet</span>')
        cards = []
        for p in range(ch["start"], ch["end"] + 1):
            pg = by_page[p]
            ds = []
            for d in pg["diagrams"]:
                r = d["rect"]
                pos = (f"left:{100 * r[0] / pg['width']:.2f}%;top:{100 * r[1] / pg['height']:.2f}%;"
                       f"width:{100 * (r[2] - r[0]) / pg['width']:.2f}%;"
                       f"height:{100 * (r[3] - r[1]) / pg['height']:.2f}%")
                ds.append(f'<button class="d" data-id="{d["id"]}" style="{pos}"></button>')
            lab = page_label(folios, p)
            name = f"PDF page {p}" if lab.startswith("PDF") else f"page {lab}"
            num = (f'<a class="num nav" href="{e(ch["file"])}#page={p}" title="Read {e(name)}">{e(lab)}</a>'
                   if size else f'<span class="num">{e(lab)}</span>')
            cards.append(
                f'<div class="pg" data-page="{p}"><div class="thumb" '
                f'style="aspect-ratio:{pg["width"]}/{pg["height"]}">'
                f'<img class="scan" loading="lazy" alt="{e(name.capitalize())}" '
                f'src="data:image/jpeg;base64,{thumbs[p]}">{"".join(ds)}</div>'
                f'<div class="cap"><input type="checkbox" class="pcb" data-page="{p}" autocomplete="off" '
                f'aria-label="Use {e(name)}">{num}</div><p class="pgnote small muted"></p></div>')
        has_lines = ch["counts"]["lines"] > 0
        counts = (f'<span class="ccount small muted">{_counts_line(ch["counts"])}</span>'
                  f'{_count_cells(ch["counts"])}' if has_lines else "")
        parts.append(
            f'<li class="chapter" id="ch{ch["index"]:02d}">'
            f'<input type="checkbox" class="ccb" data-start="{ch["start"]}" data-end="{ch["end"]}" '
            f'autocomplete="off" aria-label="Use every page of {e(heading)}">'
            f'<details><summary>{_chevron()}'
            f'<span class="ctitle"><h2>{e(heading)}</h2>'
            f'<span class="small muted num">{e(page_range(folios, ch["start"], ch["end"]))}</span></span>'
            f'{counts}</summary>'
            f'<div class="grid">{"".join(cards)}</div></details>{link}</li>')
    data = {
        "title": book["title"], "pdf": book["pdf"], "pageCount": book["page_count"],
        "hasFolios": any(f is not None for f in folios),
        "excludedKinds": list(EXCLUDED_KINDS),
        "selection": {"pages": sel.get("pages", {"exclude": []}),
                      "diagrams": sel.get("diagrams", {"exclude": [], "include": []})},
        "selBase": _selection_base(book),
        "pages": [{"page": p["page"], "folio": p.get("folio"),
                   "diagrams": [{"id": d["id"], "kind": d["kind"], "label": d.get("label")}
                                for d in p["diagrams"]]}
                  for p in book["pages"] if p["diagrams"]],
    }
    rep = {
        "__TITLE__": e(f"{book['title']} Contents"),
        "__H1__": e(book["title"]),
        "__LEDE__": ("This page lists the chapters, pages and diagrams of the book and shows "
                     "which of them the program reads."),
        "__HOW__": (("A tick includes a chapter or a page, and a click on an outlined diagram "
                     "includes it or leaves it out. Your choices take effect when you press "
                     "Read again at the top of the page.") if app else
                    ("A tick includes a chapter or a page, and a click on an outlined diagram "
                     "includes it or leaves it out. When you have finished, you copy the "
                     "selection and paste it into the chat. The program uses it on its next run.")),
        "__SUMMARY__": summary,
        "__COLS__": ('<div class="cols small muted" aria-hidden="true"><span></span><span></span>'
                     + "".join(f"<span>{w}</span>" for w in COUNT_COLUMNS) + "</div>"),
        "__CHAPTERS__": "\n".join(parts),
        "__STYLE__": style.page_css(),
        "__INDEX_CSS__": INDEX_CSS,
        "__SELJS__": SELECTION_JS,
        "__JS__": INDEX_JS,
        "__DATA__": _json_script(data),
    }
    out = INDEX_HTML
    for k, v in rep.items():
        out = out.replace(k, v)
    return out


def _chevron():
    return f"<svg class='chev' viewBox='0 0 20 20' aria-hidden='true'>{style.ICONS['chevron']}</svg>"


# ---------------------------------------------------------------- build

def build_reader(book, pdf_path, out_dir, chapters=None, progress=None, with_index=True,
                 app=False):
    """Write index.html and chNN.html into out_dir. chapters limits the chapter
    readers to those indices (the contents page always covers the whole book).
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
    if not with_index:
        return {"files": files, "pgn": pgn_report, "sizes": sizes}
    thumbs = {p: _b64(page_jpeg(doc, p, THUMB_DPI, THUMB_QUALITY))
              for p in range(1, doc.page_count + 1)}
    text = index_html(book, thumbs, sizes, app=app)
    data = text.encode("utf-8")
    (out_dir / "index.html").write_bytes(data)
    files["index.html"] = len(data)
    say(f"index.html: {len(data) / 1048576:.1f} MB")
    return {"files": files, "pgn": pgn_report, "sizes": sizes}
