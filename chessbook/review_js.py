"""The Review view of the chapter reader and the reader's corrections.

CORRECTIONS_JS is the store of corrections shared by the contents page and
the chapter readers (browser storage, one entry per book). REVIEW_JS runs
inside the chapter reader's script and uses its functions: it lists the
chapter's uncertainties, and its editors correct a diagram, a move, a
sequence that found no place, or a piece symbol that the text recognition
could not name; a piece moved on the board goes on with the line, or
corrects the main line or a variation, or adds a variation of the reader's
own (corrections.py "added"); with the pencil, the move printed in a box is
made on the board, and the line is woven on from it through what the
program could not read (the thread). REVIEW_CSS styles both, following
DESIGN.md.
"""

CORRECTIONS_JS = r"""
function makeCorrections(applied, opts){
  // applied: the corrections the build used ({diagrams, moves, unattached, glyphs}).
  const key = "chessbook-corrections:" + opts.pdf + ":" + opts.pageCount;
  const PARTS = ["diagrams", "moves", "unattached", "glyphs", "connect", "disconnect", "gaps", "added"];
  function canon(src){
    const o = {version: 1};
    for (const p of PARTS) {
      const part = (src && src[p]) || {}, keys = Object.keys(part).sort(), out = {};
      for (const k of keys) out[k] = part[k];
      o[p] = out;
    }
    return o;
  }
  const same = (a, b) => JSON.stringify(a === undefined ? null : a) === JSON.stringify(b === undefined ? null : b);
  let st = canon(applied), stored = false;
  try {
    const raw = localStorage.getItem(key);
    if (raw) { const v = JSON.parse(raw); if (v && v.corrections) { st = canon(v.corrections); stored = true; } }
  } catch (e) { stored = false; }
  const api = {
    get(part, k){ return st[part][k]; },
    set(part, k, v){
      if (v == null) delete st[part][k]; else st[part][k] = v;
      st = canon(st); api.save();
    },
    all(part){ return st[part]; },
    object(){ return Object.assign(canon(st), {note: "Corrections made in the book reader of " + opts.title + "."}); },
    text(){ return JSON.stringify(api.object(), null, 1); },
    count(){ let n = 0; for (const p of PARTS) n += Object.keys(st[p]).length; return n; },
    // a correction stored in this browser that the build did not use yet
    pending(part, k){ return !same((applied && applied[part] || {})[k], st[part][k]); },
    anyPending(){ return JSON.stringify(canon(st)) !== JSON.stringify(canon(applied)); },
    save(){
      try { localStorage.setItem(key, JSON.stringify({corrections: canon(st)})); stored = true; }
      catch (e) { /* the browser keeps no storage: the corrections live in this page only */ }
    },
    reset(){ st = canon(applied); try { localStorage.removeItem(key); } catch (e) { /* no storage */ } stored = false; },
    // the book now holds these corrections (the browser app applied them at once)
    rebase(now){ applied = now; },
    stored(){ return stored; }
  };
  return api;
}
"""

REVIEW_CSS = r"""
#reviewbtn[aria-pressed="true"]{color:var(--accent)}
.eye{position:absolute;z-index:5;padding:0;margin:0;border:0;background:none;cursor:pointer;width:16px;height:12px;
line-height:0;color:var(--doubt);display:none}
.eye svg{width:100%;height:100%;fill:none;stroke:currentColor;stroke-width:1.25;stroke-linecap:round;stroke-linejoin:round}
.eye.fixed{color:var(--ok)}
.eye:hover{color:var(--accent)}
.eye::before{content:"";position:absolute;left:50%;top:50%;width:32px;height:28px;transform:translate(-50%,-50%)}
/* with the pencil on, a tap on a move opens its corrector, which also names the symbol: the eye
   then takes only the taps on its own drawing, and the rest of the move is the pencil's */
.pencil .eye::before{display:none}
.reading .eye{display:block}
.reading .mark.fixed,.k.fixed{outline:1px solid var(--ok)}
.k.fixed{border-color:var(--ok)}
.legend .eyek{display:inline-block;width:16px;height:12px;line-height:0;color:var(--doubt)}
.legend .eyek svg{width:16px;height:12px;fill:none;stroke:currentColor;stroke-width:1.25}
.mark.seqcur,.reading .mark.seqcur{outline:1.5px solid var(--accent);z-index:3}
.symmenu{position:fixed;z-index:12;min-width:150px;background:var(--bg);border:1px solid var(--line);
margin:0;padding:4px 0;list-style:none}
.symmenu[hidden]{display:none}
.symmenu .head{padding:4px 12px 6px;color:var(--muted);border-bottom:1px solid var(--line);margin-bottom:4px}
.symmenu button{display:flex;align-items:center;gap:10px;width:100%;padding:4px 12px;background:none;border:0;
text-align:left;cursor:pointer;color:var(--fg)}
.symmenu button:hover,.symmenu button[aria-checked="true"]{color:var(--accent)}
svg.pc{width:24px;height:24px;flex:none;display:block}
svg.pc .sq{fill:var(--board-light)}
.reviewing .lsec,.reviewing .treesec,.reviewing #infosec{display:none}
#review[hidden],#fix[hidden]{display:none}
.revhead{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.revlist{list-style:none;margin:8px 0 0;padding:0}
.revlist .grp{margin:12px 0 4px;color:var(--muted)}
.revlist li{border-top:1px solid var(--line)}
.revlist li:last-child{border-bottom:1px solid var(--line)}
.revlist button{display:grid;grid-template-columns:14px minmax(0,1fr) auto;align-items:baseline;width:100%;
padding:6px 0;background:none;border:0;text-align:left;cursor:pointer;color:var(--fg)}
.revlist button:hover .rl{text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:1px}
.revlist button[aria-current="true"] .rl{color:var(--accent)}
.revlist .rl{min-width:0;overflow-wrap:anywhere}
.revlist .rp{color:var(--muted);padding-left:12px}
.revlist .rd{grid-column:2/4;color:var(--muted)}
.revlist .dot{margin:0}
.dot.st-corrected,.dot.st-fixed{background:var(--ok)}
.dot.st-unattached{background:var(--muted)}
.fix{display:grid;gap:10px}
.fix .fh{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.fix h3{font-size:17px}
.fix .lab{color:var(--muted)}
.choices{display:flex;flex-wrap:wrap;gap:4px 16px;font-family:"Geist Mono",ui-monospace,Menlo,Consolas,monospace;
font-variant-ligatures:none}
.choices button{background:none;border:0;padding:2px 0;margin:0;cursor:pointer;color:var(--fg);font:inherit;
text-underline-offset:3px;text-decoration-thickness:1px}
.choices button:hover{color:var(--accent);text-decoration:underline}
.choices button[aria-pressed="true"]{color:var(--accent)}
.choices .sub{font-family:"DM Sans",system-ui,sans-serif;color:var(--muted);font-size:13px;margin-left:6px}
.choices.lines{display:grid;gap:2px}
.fix input[type=text]{width:10em;text-align:left;font-family:"Geist Mono",ui-monospace,Menlo,Consolas,monospace}
.fix .typed{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.fixmsg:empty{display:none}
.fixmsg.bad{color:var(--fail)}
.fixmsg.good{color:var(--ok)}
.pieces{display:grid;grid-template-columns:repeat(13,minmax(0,1fr));gap:2px;max-width:420px}
.pieces.six{grid-template-columns:repeat(3,minmax(0,1fr));gap:4px 12px;max-width:none}
.pieces button{background:none;border:0;border-bottom:1px solid transparent;padding:2px 0;margin:0;cursor:pointer;
display:flex;flex-direction:column;align-items:center;color:var(--fg);min-width:0}
.pieces.six button{flex-direction:row;gap:8px;justify-content:flex-start}
.pieces button svg.pc{width:100%;height:auto;max-width:30px}
.pieces.six button svg.pc{width:28px;max-width:28px}
.pieces button:hover{border-bottom-color:var(--accent)}
.pieces button[aria-pressed="true"]{border-bottom-color:var(--accent);color:var(--accent)}
.pieces .none{display:block;width:70%;aspect-ratio:1;border:1px solid var(--muted);margin:15%}
.side{display:flex;gap:20px}
.side .tb[aria-pressed="true"]{color:var(--accent);text-decoration:underline}
.fixacts{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:baseline}
.fixnav{display:flex;gap:20px;border-top:1px solid var(--line);padding-top:8px}
.fixboard svg{display:block;width:100%;height:auto;max-width:min(100%,max(240px,calc(100vh - 420px)))}
svg.board .sel{fill:none;stroke:var(--accent);stroke-width:2px;vector-effect:non-scaling-stroke}
svg.board .hit{fill:transparent;cursor:pointer}
.fix canvas.pic{max-width:min(100%,max(240px,calc(100vh - 420px)))}
.editing-diagram #boardarea,.editing-diagram .controls{display:none}
#penbtn[aria-pressed="true"],#mpen[aria-pressed="true"]{color:var(--accent)}
/* (the pencil comes on with reading mode: the boxes keep the outlines of reading mode, which show what
   needs attention; a diagram shows that a tap corrects it) */
.pencil .diag{outline:1px dotted color-mix(in srgb,var(--accent) 60%,transparent)}
.joining .mark[data-node]:hover{outline:1.5px solid var(--accent)}
.legend .penk{display:none}
.pencil .legend .penk{display:inline-flex}
.pencil .legend{visibility:visible}
.pencil .key .help{visibility:hidden}
.k.pen{border:1px dotted var(--accent)}
.lineacts{display:grid;gap:6px;border-top:1px solid var(--line);padding-top:8px}
.lineacts p{margin:0}
#diagpick[hidden]{display:none}
.dot.st-added{background:var(--ok)}
.boardacts{display:grid;justify-items:start;gap:6px}
/* the thread's sheet: one line, then its buttons */
.fix .thl{margin:0}
.boardacts .n{font-family:"Geist Mono",ui-monospace,Menlo,Consolas,monospace;font-variant-ligatures:none}
svg.board.movable use[data-mine]{cursor:grab}
svg.board use.lifted{opacity:.35}
svg.board .ghost{cursor:grabbing}
svg.board .pk{fill:none;stroke:var(--accent);stroke-width:1.5px;vector-effect:non-scaling-stroke}
svg.board .tg{fill:var(--accent);fill-opacity:.45}
svg.board .tgc{fill:none;stroke:var(--accent);stroke-opacity:.55;stroke-width:1.5px;vector-effect:non-scaling-stroke}
@media (max-width:700px){
.pencil .legend{display:flex}
.tools{flex-wrap:wrap;row-gap:4px}
#fix:not([hidden]){position:fixed;left:0;right:0;z-index:9;max-height:62vh;overflow:auto;background:var(--bg);
border-top:1px solid var(--line);padding:12px 16px}
.fixboard svg{max-width:min(100%,32vh);margin:0 auto}
.fix canvas.pic{display:none}
.pieces{max-width:none}
.editing-diagram #boardarea,.editing-diagram .controls{display:block}}
"""

EYE_SVG = ("<svg viewBox='0 0 20 14' aria-hidden='true'><path d='M1.5 7C3.7 3.4 6.6 1.6 10 1.6S16.3 3.4 18.5 7"
           "C16.3 10.6 13.4 12.4 10 12.4S3.7 10.6 1.5 7z'/><circle cx='10' cy='7' r='2.4'/></svg>")

REVIEW_JS = r"""
/* ---------------------------------------------------------------- review and corrections */
const FIX = makeCorrections(D.corrections, {pdf: D.book.pdf, pageCount: D.pageCount, title: D.book.title});
window.correctionsText = FIX.text;
const EYE = "__EYE__";
const RV = {on: false, items: [], cur: -1, edit: null, wasReading: false};
const PIECES = {K: "king", Q: "queen", R: "rook", B: "bishop", N: "knight", P: "pawn"};
const REVIEW = ["guessed", "ambiguous", "failed"];

function inApp(){ return !!window.CHESSBOOK_APP; }
function applyWords(){
  return inApp() ? "The reader applies it at once." :
    "The next run of the program applies it once you copy the corrections on the contents page into the chat.";
}
function pieceSvg(letter, white){
  if (!letter) return "<span class=none aria-hidden='true'></span>";
  const name = (white ? "white-" : "black-") + PIECES[letter.toUpperCase()];
  // drawn on a light square, so that black pieces stay visible in the dark scheme
  return "<svg class=pc viewBox='0 0 45 45' aria-hidden='true'><rect class=sq width='45' height='45'/><use href='#" + name +
    "' xlink:href='#" + name + "'/></svg>";
}
function sideOf(n){
  if (n && n.before) return n.before.split(" ")[1] === "b" ? "b" : "w";
  return n && n.black ? "b" : "w";
}
/* positions: a board as 8 rows of 8 squares, row 0 holding rank 8 */
function fenRows(fen){
  return fen.split(" ")[0].split("/").map(r => {
    const out = [];
    for (const ch of r) { if (/\d/.test(ch)) for (let i = 0; i < +ch; i++) out.push(""); else out.push(ch); }
    return out;
  });
}
function rowsFen(rows, turn){
  const place = rows.map(r => {
    let s = "", e = 0;
    for (const ch of r) { if (!ch) { e++; continue; } if (e) { s += e; e = 0; } s += ch; }
    return s + (e ? e : "");
  }).join("/");
  // castling rights where king and rook stand on their first squares
  let c = "";
  if (rows[7][4] === "K") { if (rows[7][7] === "R") c += "K"; if (rows[7][0] === "R") c += "Q"; }
  if (rows[0][4] === "k") { if (rows[0][7] === "r") c += "k"; if (rows[0][0] === "r") c += "q"; }
  return place + " " + turn + " " + (c || "-") + " - 0 1";
}
function sqRC(name){ return [8 - parseInt(name[1], 10), "abcdefgh".indexOf(name[0])]; }
function applyUci(fen, uci){
  // the position after a legal move, for showing it on the board
  const rows = fenRows(fen), turn = fen.split(" ")[1] || "w";
  const [r0, c0] = sqRC(uci.slice(0, 2)), [r1, c1] = sqRC(uci.slice(2, 4));
  let p = rows[r0][c0];
  if (p.toLowerCase() === "k" && Math.abs(c1 - c0) === 2) {
    const rf = c1 > c0 ? 7 : 0, rt = c1 > c0 ? 5 : 3;
    rows[r0][rt] = rows[r0][rf]; rows[r0][rf] = "";
  }
  if (p.toLowerCase() === "p" && c1 !== c0 && !rows[r1][c1]) rows[r0][c1] = "";
  if (uci.length > 4) p = turn === "w" ? uci[4].toUpperCase() : uci[4].toLowerCase();
  rows[r0][c0] = ""; rows[r1][c1] = p;
  return rowsFen(rows, turn === "w" ? "b" : "w");
}
function positionProblem(rows){
  let K = 0, k = 0, pawn = false;
  rows.forEach((r, i) => r.forEach(ch => {
    if (ch === "K") K++; if (ch === "k") k++;
    if ((ch === "P" || ch === "p") && (i === 0 || i === 7)) pawn = true;
  }));
  if (K !== 1 || k !== 1)
    return "A position needs one king of each colour. This one has " + words(K) + " white " +
      (K === 1 ? "king" : "kings") + " and " + words(k) + " black " + (k === 1 ? "king" : "kings") + ".";
  if (pawn) return "A pawn cannot stand on the first or the last rank.";
  return "";
}
/* SAN as the reader types it: the book's letters become English ones, and check signs,
   annotations and zeros of castling do not count */
function sanKey(t, loose){
  t = String(t || "").trim().replace(/[+#!?]+$/g, "").replace(/0/g, "O").replace(/[–—]/g, "-");
  if (/^[A-Z]/.test(t) && D.letters[t[0]] && !/^O-O/.test(t)) t = D.letters[t[0]] + t.slice(1);
  if (loose) t = t.replace(/[x:\-=]/g, "").toLowerCase();
  return t;
}
function matchSan(typed, legal){
  const a = sanKey(typed), exact = legal.filter(m => sanKey(m[0]) === a);
  if (exact.length === 1) return exact[0];
  const b = sanKey(typed, true), loose = legal.filter(m => sanKey(m[0], true) === b);
  return loose.length === 1 ? loose[0] : null;
}

/* ---------------- the list */
function moveLabel(id){ return "<span class=n>" + moveHtml(id, true) + "</span>"; }
function seqInfo(key){
  for (const u of D.unattached) if (u.key === key) return u;
  for (const u of D.dismissed) if (u.key === key) return Object.assign({dismissed: true}, u);
  return null;
}
function diagInfo2(id){ const [p, d] = diagramInfo(id); return {p, d}; }
function symbolsHere(){
  // the chapter's unreadable piece symbols on moves that need a check, most frequent in the book first
  const seen = {};
  for (const p in D.pages) for (const m of D.pages[p].marks) {
    if (!m.symbol || !symbolNeeded(m)) continue;
    const s = seen[m.symbol] || (seen[m.symbol] = {kind: "symbol", sym: m.symbol, here: 0,
      book: D.symbols[m.symbol] || 0, page: parseInt(p, 10), y: m.bbox[1]});
    s.here++;
  }
  return Object.values(seen).sort((a, b) => b.book - a.book || b.here - a.here);
}
function symbolNeeded(m){
  // (a symbol the book taught well is not what a doubt about its move is about)
  const n = m.node ? D.nodes[m.node] : null;
  if (n && n.corrected === "symbol") return true;
  if (m.known) return false;
  return n ? REVIEW.indexOf(n.status) >= 0 : m.status === "unattached";
}
function buildItems(){
  const out = [];
  for (const p in D.pages) {
    const P = D.pages[p], page = parseInt(p, 10);
    if (!P.selected) continue;
    for (const d of P.diagrams) {
      if (!d.selected) continue;
      const R0 = d.reading;
      const board = d.kind === "board" || d.kind === "board_plus";
      const unread = d.status === "unread" && board && ((d.lines || []).length || (R0 && R0.fen));
      if (d.status === "doubtful" || unread || d.corrected || FIX.get("diagrams", d.id))
        out.push({kind: "diagram", id: d.id, page, order: -1, y: d.rect[1]});
    }
    const seen = new Set();
    P.marks.forEach((m, i) => {
      if (m.node) {
        const n = D.nodes[m.node];
        if (!n || seen.has(m.node) || n.page !== page) return;
        seen.add(m.node);
        const need = (REVIEW.indexOf(n.status) >= 0 && n.legal) || n.corrected === "move" ||
          n.corrected === "placed" || n.corrected === "connected" || n.corrected === "split" ||
          (n.key && (FIX.get("moves", n.key) || FIX.get("connect", n.key) || FIX.get("disconnect", n.key)));
        if (need) out.push({kind: "move", node: m.node, page, order: i, y: m.bbox[1]});
      } else if (m.seq && !seen.has(m.seq)) {
        seen.add(m.seq);
        out.push({kind: "seq", key: m.seq, page, order: i, y: m.bbox[1]});
      }
    });
  }
  for (const u of D.dismissed)
    if (u.page in D.pages) out.push({kind: "seq", key: u.key, page: u.page, order: 1e6, y: u.bbox ? u.bbox[1] : 0});
  // gaps in the text: moves the book lacks, before the first printed move after them
  const gaps = new Set();
  for (const id in D.nodes) {
    const n = D.nodes[id];
    if (!n.gap || gaps.has(n.gap) || !(n.page in D.pages) || !D.pages[n.page].selected) continue;
    gaps.add(n.gap);
    const i = D.pages[n.page].marks.findIndex(m => m.key === n.gap);
    out.push({kind: "gap", key: n.gap, page: n.page, order: i >= 0 ? i - 0.5 : 1e5, y: 0});
  }
  // the variations the reader added on the board, at the printed move they branch from
  const added = new Set(Object.keys(FIX.all("added")));
  for (const id in D.nodes) if (D.nodes[id].added) added.add(D.nodes[id].added);
  for (const key of added) {
    const at = nodeByKey(key), n = at ? D.nodes[at] : null;
    if (!n || !(n.page in D.pages) || !D.pages[n.page].selected) continue;
    const i = D.pages[n.page].marks.findIndex(m => m.key === key);
    out.push({kind: "added", key, page: n.page, order: i >= 0 ? i + 0.5 : 1e5, y: 0});
  }
  out.sort((a, b) => a.page - b.page || a.order - b.order);
  return symbolsHere().concat(out);
}
function itemState(it){
  // [dot class, words] of an item: what the program made of it, or the reader's correction
  const pend = applyWords();
  if (it.kind === "symbol") {
    const g = FIX.get("glyphs", it.sym), a = (D.corrections.glyphs || {})[it.sym];
    if (g) return ["corrected", "Corrected by you: " + PIECES[g] + (g !== a ? ". " + pend : "")];
    return ["guessed", "Unreadable piece symbol, printed " + words(it.book) + (it.book === 1 ? " time" : " times") +
      " in the book"];
  }
  if (it.kind === "diagram") {
    const {d} = diagInfo2(it.id);
    const f = FIX.get("diagrams", it.id);
    if (f && FIX.pending("diagrams", it.id)) return ["corrected", "Corrected by you. " + pend];
    if (d.corrected) return ["corrected", "Corrected by you"];
    const dq = (d.reading && d.reading.doubtful) || [];
    if (d.status === "doubtful")
      return ["guessed", "Board reading is unsure of " + words(dq.length) + (dq.length === 1 ? " square" : " squares")];
    return ["failed", "Board reading could not read this position"];
  }
  if (it.kind === "gap") {
    const g = gapInfo(it.key), f = FIX.get("gaps", it.key);
    if (FIX.pending("gaps", it.key))
      return f ? ["corrected", "You gave " + f.san.join(" ") + ". " + pend] : ["failed", "You removed the moves you gave. " + pend];
    if (g.hole && D.nodes[g.hole].fill && D.nodes[g.hole].fill.length < (f ? f.san.length : 0))
      return ["failed", "The moves you gave are not legal here"];
    if (g.hole) return ["failed", "The book's text lacks " + (g.missing === 1 ? "this move" : words(g.missing) + " moves here")];
    return ["corrected", "Given by you"];
  }
  if (it.kind === "added") {
    const f = FIX.get("added", it.key), at = nodeByKey(it.key);
    const how = f && f.every(e => e.rect) ? "Read by you on the page" : "Added by you";
    if (FIX.pending("added", it.key))
      return f ? ["corrected", how + ". " + pend] : ["corrected", "You removed your variation. " + pend];
    if (at && D.nodes[at].added_stale) return ["failed", D.nodes[at].added_stale];
    return ["corrected", how];
  }
  if (it.kind === "move") {
    const n = D.nodes[it.node];
    if (n.key && FIX.get("moves", n.key) && FIX.pending("moves", n.key))
      return ["corrected", "Corrected by you to " + FIX.get("moves", n.key).san + ". " + pend];
    if (n.key && !FIX.get("moves", n.key) && FIX.pending("moves", n.key))
      return [n.status, "You removed your correction. " + pend];
    for (const part of ["connect", "disconnect"])
      if (n.key && FIX.pending(part, n.key))
        return FIX.get(part, n.key) ? ["corrected", lineFixWords(part, FIX.get(part, n.key)) + " " + pend] :
          [n.status, "You removed your correction. " + pend];
    if (n.corrected === "move") return ["corrected", "Corrected by you"];
    if (n.corrected === "placed") return ["corrected", "Placed by you"];
    if (n.corrected === "connected") return ["corrected", "Joined to the line by you"];
    if (n.corrected === "split") return ["corrected", "A new line starts here, as you said"];
    return [n.status, D.words[n.status]];
  }
  const u = seqInfo(it.key) || {};
  const f = FIX.get("unattached", it.key);
  if (f && FIX.pending("unattached", it.key))
    return ["corrected", (f.attach_to === "dismiss" ? "Dismissed by you. " : "Placed by you. ") + pend];
  if (u.dismissed) return ["corrected", "Dismissed by you as no variation"];
  return ["unattached", D.words.unattached];
}
function itemLabel(it){
  if (it.kind === "symbol") return "Piece symbol “<span class=n>" + shownHtml(it.sym) + "</span>”";
  if (it.kind === "diagram") { const {p, d} = diagInfo2(it.id); return esc(cap(diagramName(d, p))); }
  if (it.kind === "move") return moveLabel(it.node);
  if (it.kind === "gap") return esc(gapTitle(it.key, true));
  if (it.kind === "added") return esc(addedTitle(it.key));
  const u = seqInfo(it.key);
  return "“<span class=n>" + shownHtml(u ? u.text : "") + "</span>”";
}
function renderReview(){
  RV.items = buildItems();
  const box = $("revlist");
  let h = "", grp = null;
  RV.items.forEach((it, i) => {
    const g = it.kind === "symbol" ? "Piece symbols the text recognition could not name" : "On the pages, in page order";
    if (g !== grp) { h += "<li class='grp small' role=presentation>" + g + "</li>"; grp = g; }
    const [st, w] = itemState(it);
    h += "<li><button data-item='" + i + "' data-kind='" + it.kind + "'" +
      (it.kind === "symbol" ? " data-sym='" + esc(it.sym) + "'" : "") + (i === RV.cur ? " aria-current='true'" : "") + ">" +
      "<i class='dot st-" + esc(st) + "'></i><span class=rl>" + itemLabel(it) + "</span>" +
      "<span class='rp small num'>" + esc(it.kind === "symbol" ? it.here + " in chapter" : label(it.page)) +
      "</span><span class='rd small'>" + esc(w) + "</span></button></li>";
  });
  box.innerHTML = h || "<li class='grp small'>The program found nothing to check in this chapter.</li>";
  const open = RV.items.filter(it => itemState(it)[0] !== "corrected").length;
  $("revsum").textContent = RV.items.length ?
    cap(words(RV.items.length)) + (RV.items.length === 1 ? " item" : " items") + " in this chapter, of which " +
    words(open) + (open === 1 ? " needs" : " need") + " your check. A click on an item shows it on the page " +
    "and on the board, with the choices to correct it." :
    "The program read every move and diagram of this chapter without doubt.";
}
function setReview(on){
  RV.on = on;
  document.body.classList.toggle("reviewing", on);
  $("reviewbtn").setAttribute("aria-pressed", String(on));
  $("review").hidden = !on;
  if (on) {
    RV.wasReading = reading();
    if (!RV.wasReading) setReading(true);
    renderReview();
    if (SMALL.matches) $("review").scrollIntoView({block: "start"});
  } else {
    closeFix();
    if (!RV.wasReading) setReading(false);
  }
  renderInfo(); layoutPanel(false);
}
function openItem(i){
  const it = RV.items[i];
  if (!it) return;
  RV.cur = i;
  for (const b of $("revlist").querySelectorAll("button[data-item]"))
    if (parseInt(b.dataset.item, 10) === i) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
  if (it.kind === "move") { openMove(it.node); }
  else if (it.kind === "diagram") { openDiagramFix(it.id); }
  else if (it.kind === "seq") { openSeq(it.key); }
  else if (it.kind === "gap") { openGap(it.key); }
  else if (it.kind === "added") { openAddedAt(it.key); }
  else openSymbol(it.sym);
}

/* ---------------- the editor */
function fixNav(){
  if (!RV.on || RV.cur < 0) return "<div class=fixnav><button class=tb id=fixclose>Close</button></div>";
  return "<div class=fixnav><button class=tb id=fixprev" + (RV.cur <= 0 ? " disabled" : "") + ">Previous item</button>" +
    "<button class=tb id=fixnext" + (RV.cur >= RV.items.length - 1 ? " disabled" : "") + ">Next item</button>" +
    "<span class=gap></span><button class=tb id=fixclose>Close</button></div>";
}
function showFix(html, kind, nav){
  const box = $("fix");
  box.innerHTML = "<div class=fix>" + html + (nav === false ? "" : fixNav()) + "</div>";
  box.hidden = false;
  RV.edit = Object.assign(RV.edit || {}, {kind});
  $("panel").classList.toggle("editing-diagram", kind === "diagram");
  if ($("fixclose")) $("fixclose").addEventListener("click", () => closeSheet());
  if ($("fixprev")) $("fixprev").addEventListener("click", () => openItem(RV.cur - 1));
  if ($("fixnext")) $("fixnext").addEventListener("click", () => openItem(RV.cur + 1));
  renderMini();
  placeSheet();
  // on a wide screen the editor sits below the board at the top of the panel
  if (!SMALL.matches) $("panel").scrollTop = 0;
}
// Close and Cancel: the sheet goes, and nothing it started waits for a tap (a join of lines)
function closeSheet(){
  if (PEN.connect) { stopConnect(); say(""); }
  closeFix();
}
function closeFix(){
  const box = $("fix");
  box.hidden = true; box.innerHTML = "";
  RV.edit = null;
  S.preview = null;
  // (the thread ends with its sheet; a join of lines started from a sheet outlasts it while the
  // reader turns to the page of the move, and ends with Close, Escape or Hide reading)
  threadEnd();
  $("panel").classList.remove("editing-diagram");
  for (const el of document.querySelectorAll(".mark.seqcur")) el.classList.remove("seqcur");
  // a section of the page being read goes with its sheet
  if (RG.sel || RG.draw) regionClosed();
  placeSheet();
  renderBoard();
}
function placeSheet(){
  // on a phone the editor sits above the bar at the foot of the window
  const box = $("fix"), bar = $("mbar");
  if (SMALL.matches && !box.hidden) {
    box.style.bottom = bar.offsetHeight + "px";
    // leave room above the editor for the page, so that the item stays in view: on a tablet held
    // upright the diagram editor takes half the window at most, so that the diagram it corrects,
    // taller than a move, stands whole above it
    const room = TABLET.matches && RV.edit && RV.edit.kind === "diagram" ? Math.round(window.innerHeight * 0.5) :
      window.innerHeight - bar.offsetHeight - 200;
    box.style.maxHeight = Math.max(220, room) + "px";
    document.body.style.paddingBottom = (bar.offsetHeight + box.offsetHeight) + "px";
  } else { box.style.bottom = ""; box.style.maxHeight = ""; document.body.style.paddingBottom = ""; }
}
function bottomCover(){
  const box = $("fix");
  return SMALL.matches && box && !box.hidden ? box.offsetHeight : 0;
}
function setMsg(text, kind){
  const m = $("fixmsg");
  if (!m) return;
  m.textContent = text || "";
  m.className = "fixmsg small" + (kind ? " " + kind : "");
}
function preview(fen, uci, note){ S.preview = fen ? {fen, uci: uci || null, note: note || ""} : null; renderBoard(); }

/* a move */
function beforeFen(n){
  if (n.before) return n.before;
  const par = n.parent != null ? D.nodes[n.parent] : null;
  return par && par.fen ? par.fen : null;
}
function legalOf(n){
  if (n.legal) return n.legal;
  const f = beforeFen(n);
  return f ? CJ.legalMoves(f) : [];
}
function openMove(id){
  const n = D.nodes[id];
  if (!n) return;
  // a gap in the text, or a move the reader gave for one: the gap's own editor
  if (n.gap) { openGap(n.gap); return; }
  // a move the reader added on the board: the editor of the variation
  if (n.corrected === "added") { openAdded(id); return; }
  if (S.node !== id) selectNode(id, {scrollPage: false});
  RV.edit = {kind: "move", node: id};
  const legal = legalOf(n);
  n.before = n.before || beforeFen(n);
  const fixed = n.key ? FIX.get("moves", n.key) : null;
  const now = n.san || n.assumed;
  const first = [];
  for (const s of [now].concat(n.alternatives || [])) {
    const m = s && legal.find(x => x[0] === s);
    if (m && !first.some(x => x[0] === m[0])) first.push(m);
  }
  let h = "<div class=fh><h3>Correct " + moveLabel(id) + "</h3></div>";
  h += "<p class='small muted'>The text recognition read “<span class=n>" + shownHtml(n.raw) + "</span>”. " +
    (n.corrected === "move" ? "You corrected this move." : esc(D.words[n.status] || "") + ".") + "</p>";
  if (!legal.length) {
    const gk = gapKeyOf(id);
    if (gk) {
      const t = gapTitle(gk);
      h += "<p class='small muted'>The position before this move is unknown, because the book's text lacks a " +
        "move before it. The board shows the position before the gap. Once you give the missing move, the program " +
        "reads this move from there.</p><div class=fixacts><button class=tb id=fixgap>" + esc(t) + "</button></div>";
    } else
      h += "<p class='small muted'>The program does not know the position before this move, so it cannot " +
        "offer the moves that are legal there.</p>";
    h += "<p class='fixmsg small' id=fixmsg role=status></p>" + lineActions(id);
    showFix(h, "move");
    wireLineActions(id);
    if ($("fixgap")) $("fixgap").addEventListener("click", () => openGap(gk));
    highlightMark(true);
    return;
  }
  if (first.length) {
    h += "<p class='lab small'>" + (n.status === "failed" ? "The move the program assumed" :
      "The readings the program considered") + "</p><div class=choices>" +
      first.map(m => "<button data-san='" + esc(m[0]) + "' aria-pressed='" + String(!!fixed && fixed.san === m[0]) +
        "'>" + esc(m[0]) + "</button>").join("") + "</div>";
  }
  h += "<div class=typed><label class='lab small' for=fixsan>" + (first.length ? "Or type the move" : "Type the move") +
    "</label><input type=text id=fixsan autocomplete=off autocapitalize=off spellcheck=false placeholder='such as Nf3'" +
    " aria-describedby=fixmsg></div>";
  h += "<div class=choices id=fixlist aria-label='Legal moves'></div>";
  h += "<p class='fixmsg small' id=fixmsg role=status></p>";
  if (fixed) h += "<div class=fixacts><button class=tb id=fixundo>Remove your correction</button></div>";
  if (n.symbol) h += "<p class=small><button class=tb id=fixsymbol>Name the piece symbol “<span class=n>" +
    shownHtml(n.symbol) + "</span>” throughout the book</button></p>";
  h += lineActions(id);
  showFix(h, "move");
  wireLineActions(id);
  if ($("fixsymbol")) $("fixsymbol").addEventListener("click", () => openSymbol(n.symbol));
  highlightMark(true);
  const list = () => {
    const t = $("fixsan").value, a = sanKey(t, true);
    const hits = legal.filter(m => !a || sanKey(m[0], true).indexOf(a) === 0);
    $("fixlist").innerHTML = hits.slice(0, 40).map(m => "<button data-san='" + esc(m[0]) + "'>" + esc(m[0]) +
      "</button>").join("") + (hits.length > 40 ? "<span class=sub>and " + (hits.length - 40) + " more</span>" : "") +
      (hits.length ? "" : "<span class=sub>No legal move begins like this.</span>");
  };
  list();
  $("fixsan").addEventListener("input", list);
  $("fixsan").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const m = matchSan($("fixsan").value, legal);
    if (m) chooseMove(id, m);
    else setMsg("“" + $("fixsan").value + "” is not a legal move in this position. The moves below are legal.", "bad");
  });
  for (const b of $("fix").querySelectorAll(".choices")) b.addEventListener("click", (e) => {
    const t = e.target.closest("button[data-san]");
    if (t) chooseMove(id, legal.find(x => x[0] === t.dataset.san));
  });
  if ($("fixundo")) $("fixundo").addEventListener("click", () => {
    FIX.set("moves", n.key, null); afterFix(); openMove(id);
    setMsg("Your correction is removed. " + applyWords());
  });
  if (fixed) {
    const m = legal.find(x => x[0] === fixed.san);
    if (m) preview(applyUci(n.before, m[1]), m[1]);
  }
}
function chooseMove(id, m){
  const n = D.nodes[id];
  if (!m || !n.key) return;
  FIX.set("moves", n.key, {san: m[0]});
  preview(applyUci(n.before, m[1]), m[1]);
  for (const b of $("fix").querySelectorAll("button[data-san]")) b.setAttribute("aria-pressed", String(b.dataset.san === m[0]));
  setMsg("You chose " + m[0] + ". The board shows the position after it. " + applyWords() +
    " The program then reads the rest of the line from this move.", "good");
  afterFix();
}

/* a gap in the text: moves the book's text lacks */
function gapKeyOf(id){
  // the gap a move belongs to (the gap itself, or a move the reader gave for it) or follows
  // (a printed move whose position is unknown because of it), else null
  let cur = id;
  while (cur != null && D.nodes[cur]) {
    const n = D.nodes[cur];
    if (n.gap) return n.gap;
    if (n.fen || n.parent == null) return null;
    cur = n.parent;
  }
  return null;
}
function gapInfo(key){
  // {hole: the gap node (null once the reader gave every move), filled: the moves the reader gave,
  //  in order, base: the position before the gap, missing: the moves the text lacks there}
  let hole = null;
  const filled = [];
  for (const id in D.nodes) {
    const n = D.nodes[id];
    if (n.gap !== key) continue;
    if (n.san) filled.push(id); else hole = id;
  }
  let first = filled.find(id => filled.indexOf(D.nodes[id].parent) < 0) || null;
  const order = [];
  for (let id = first; id && filled.indexOf(id) >= 0; id = cont(id)) order.push(id);
  const start = first || hole;
  const par = start ? D.nodes[D.nodes[start].parent] : null;
  const missing = order.length + (hole ? (D.nodes[hole].missing || 1) : 0);
  return {hole, filled: order, base: par && par.fen ? par.fen : null, before: par ? D.nodes[start].parent : null,
    missing};
}
function sideWords(fen){
  const f = fen.split(" ");
  return (f[1] === "b" ? "Black" : "White") + "'s move " + (f[5] || "1");
}
function gapMoves(key){
  // [the position after the moves the reader gave, [[number, SAN, UCI]...], the first move that is not legal]
  const g = gapInfo(key), f = FIX.get("gaps", key);
  let fen = g.base;
  const done = [];
  for (const s of (f ? f.san : [])) {
    const legal = fen ? CJ.legalMoves(fen) : [];
    const m = legal.find(x => x[0] === s) || matchSan(s, legal);
    if (!m) return [fen, done, s];
    const b = fen.split(" ");
    done.push([b[5] + (b[1] === "b" ? "…" : "."), m[0], m[1]]);
    // (applyUci keeps no move number)
    const a = applyUci(fen, m[1]).split(" ");
    a[5] = String(parseInt(b[5] || "1", 10) + (b[1] === "b" ? 1 : 0));
    fen = a.join(" ");
  }
  return [fen, done, null];
}
function gapTitle(key, list){
  const g = gapInfo(key), [fen, done, bad] = gapMoves(key);
  if (!g.base) return "Moves missing from the text";
  if (!bad && fen && done.length < g.missing) return list ? cap(sideWords(fen)) + ", missing from the text" :
    "Give " + sideWords(fen);
  if (list) return done.length ? done.map(d => d[0] + d[1]).join(" ") + ", given by you" : "Moves missing from the text";
  return "The moves you gave for the gap";
}
function openGap(key){
  const g = gapInfo(key);
  if (!g.hole && !g.filled.length) return;
  if (!(S.node && gapKeyOf(S.node) === key)) selectNode(g.hole || g.filled[g.filled.length - 1], {scrollPage: false});
  RV.edit = {kind: "gap", key};
  const f = FIX.get("gaps", key), [fen, done, bad] = gapMoves(key);
  const room = g.missing - done.length;
  const after = nodeByKey(key);
  let h = "<div class=fh><h3>" + esc(gapTitle(key)) + "</h3></div>";
  const where = (g.missing === 1 ? "a move" : words(g.missing) + " moves") + " here" +
    (after ? ", before <span class=n>" + moveHtml(after, true) + "</span>" : "");
  h += "<p class='small muted'>" + (room > 0 || bad ? "The book's text lacks " + where +
    ", so the program cannot follow the line on its own. It never supplies such a move itself: " +
    (g.missing === 1 ? "choose the move that was played." : "choose the moves that were played, one at a time.") :
    "The book's text lacks " + where + ". The program reads the line on from the moves you gave.") + "</p>";
  if (done.length) h += "<p class=small>You gave <span class=n>" + esc(done.map(d => d[0] + d[1]).join(" ")) + "</span>." +
    (FIX.pending("gaps", key) ? " " + esc(applyWords()) : "") + "</p>";
  let legal = [];
  if (!g.base) h += "<p class='small muted'>The position before the gap is unknown, so the program cannot offer " +
    "the moves that are legal there.</p>";
  else if (bad) h += "<p class='small fixmsg bad'>The move you gave, <span class=n>" + esc(bad) + "</span>, is not legal " +
    "here, so the program ignores the moves you gave.</p>";
  else if (room > 0) {
    legal = CJ.legalMoves(fen);
    h += "<div class=typed><label class='lab small' for=fixsan>Type the move</label><input type=text id=fixsan " +
      "autocomplete=off autocapitalize=off spellcheck=false placeholder='such as Nf3' aria-describedby=fixmsg></div>";
    h += "<div class=choices id=fixlist aria-label='Legal moves'></div>";
  }
  h += "<p class='fixmsg small' id=fixmsg role=status></p>";
  if (f) h += "<div class=fixacts><button class=tb id=fixundo>Remove the moves you gave</button></div>";
  showFix(h, "gap");
  highlightMark(true);
  if (fen && done.length) preview(fen, done[done.length - 1][2], "The board shows the position after the moves you gave.");
  else if (g.base) preview(g.base, null, "The board shows the position before the gap.");
  if ($("fixundo")) $("fixundo").addEventListener("click", () => {
    FIX.set("gaps", key, null); afterFix(); openGap(key);
    setMsg("The moves you gave are removed. " + applyWords());
  });
  if (!legal.length) return;
  const list = () => {
    const a = sanKey($("fixsan").value, true);
    const hits = legal.filter(m => !a || sanKey(m[0], true).indexOf(a) === 0);
    $("fixlist").innerHTML = hits.slice(0, 40).map(m => "<button data-san='" + esc(m[0]) + "'>" + esc(m[0]) +
      "</button>").join("") + (hits.length > 40 ? "<span class=sub>and " + (hits.length - 40) + " more</span>" : "") +
      (hits.length ? "" : "<span class=sub>No legal move begins like this.</span>");
  };
  list();
  $("fixsan").addEventListener("input", list);
  $("fixsan").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const m = matchSan($("fixsan").value, legal);
    if (m) chooseGap(key, m);
    else setMsg("“" + $("fixsan").value + "” is not a legal move in this position. The moves below are legal.", "bad");
  });
  $("fixlist").addEventListener("click", (e) => {
    const t = e.target.closest("button[data-san]");
    if (t) chooseGap(key, legal.find(x => x[0] === t.dataset.san));
  });
}
function chooseGap(key, m){
  if (!m) return;
  const [, done] = gapMoves(key);
  const san = done.map(d => d[1]).concat([m[0]]);
  FIX.set("gaps", key, {san});
  const left = gapInfo(key).missing - san.length;
  afterFix();
  openGap(key);
  setMsg("You gave " + m[0] + ". " + (left > 0 ? "The text lacks " + (left === 1 ? "one more move" : words(left) +
    " more moves") + " here: give the next one, or leave the rest. " : "The program then reads the line on from it. ") +
    applyWords(), "good");
}

/* a diagram */
function openDiagramFix(id){
  const {p, d} = diagInfo2(id);
  if (!d) return;
  if (S.page !== p) showPage(p);
  if (S.diagram) closeDiagram();
  S.node = null; S.at = null;
  for (const el of document.querySelectorAll(".diag.current")) el.classList.remove("current");
  const el = document.querySelector(".diag[data-diagram='" + id + "']");
  if (el) el.classList.add("current");
  const R0 = d.reading || {};
  const fixed = FIX.get("diagrams", id);
  const start = (fixed && fixed.fen) || d.fen || R0.fen || "8/8/8/8/8/8/8/8 w - - 0 1";
  const ed = {kind: "diagram", id, rows: fenRows(start), turn: (start.split(" ")[1] || "w"), sel: null,
    flip: !!R0.flipped, doubt: (R0.doubtful || [])};
  RV.edit = ed;
  let h = "<div class=fh><h3>Correct " + esc(diagramName(d, p)) + "</h3></div>";
  h += "<p class='small muted'>A tap on a square chooses it, and a tap on a piece below puts that piece there. " +
    (ed.doubt.length ? "The squares with a dashed outline are the ones board reading is unsure of." : "") + "</p>";
  h += "<div class=fixboard id=fixboard></div>";
  h += "<div class=pieces id=fixpieces role=group aria-label='Pieces'>";
  for (const c of "KQRBNP") h += "<button data-put='" + c + "' aria-label='White " + PIECES[c] + "' title='White " +
    PIECES[c] + "'>" + pieceSvg(c, true) + "</button>";
  for (const c of "KQRBNP") h += "<button data-put='" + c.toLowerCase() + "' aria-label='Black " + PIECES[c] +
    "' title='Black " + PIECES[c] + "'>" + pieceSvg(c, false) + "</button>";
  h += "<button data-put='' aria-label='Empty square' title='Empty square'>" + pieceSvg("", true) + "</button></div>";
  h += "<div class='side small' role=group aria-label='Side to move'><button class=tb data-turn=w>White to move</button>" +
    "<button class=tb data-turn=b>Black to move</button></div>";
  h += "<p class='fixmsg small' id=fixmsg role=status></p>";
  h += "<div class=fixacts><button class=tb id=fixsave>Save the position</button>" +
    "<button class=tb id=fixagain>Start again from the reading</button>" +
    (fixed ? "<button class=tb id=fixundo>Remove your correction</button>" : "") + "</div>";
  h += PIC;
  showFix(h, "diagram");
  if (el) revealMark(el);
  cropInto($("fix").querySelector("canvas"), id);
  drawEditBoard();
  $("fixboard").addEventListener("click", (e) => {
    const t = e.target.closest("[data-sq]");
    if (t) { ed.sel = t.dataset.sq; drawEditBoard(); }
  });
  $("fixpieces").addEventListener("click", (e) => {
    const t = e.target.closest("button[data-put]");
    if (!t) return;
    if (!ed.sel) { setMsg("Choose a square on the board first."); return; }
    const [r, c] = sqRC(ed.sel);
    ed.rows[r][c] = t.dataset.put;
    drawEditBoard();
  });
  for (const b of $("fix").querySelectorAll("[data-turn]"))
    b.addEventListener("click", () => { ed.turn = b.dataset.turn; drawEditBoard(); });
  $("fixsave").addEventListener("click", () => {
    const bad = positionProblem(ed.rows);
    if (bad) { setMsg(bad, "bad"); return; }
    FIX.set("diagrams", id, {fen: rowsFen(ed.rows, ed.turn)});
    afterFix();
    setMsg("The position is saved. " + applyWords() + " Lines that start from this diagram then start from it.", "good");
  });
  $("fixagain").addEventListener("click", () => {
    const f = d.fen || R0.fen || "8/8/8/8/8/8/8/8 w - - 0 1";
    ed.rows = fenRows(f); ed.turn = f.split(" ")[1] || "w"; ed.sel = null; drawEditBoard(); setMsg("");
  });
  if ($("fixundo")) $("fixundo").addEventListener("click", () => {
    FIX.set("diagrams", id, null); afterFix(); openDiagramFix(id);
    setMsg("Your correction is removed. " + applyWords());
  });
  setState();
}
function drawEditBoard(){
  const ed = RV.edit;
  if (!ed || ed.kind !== "diagram") return;
  const fen = rowsFen(ed.rows, ed.turn);
  let s = boardSvg(fen, ed.flip, null, ed.doubt);
  let extra = "";
  for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) {
    const name = "abcdefgh"[c] + (8 - r);
    const x = M + (ed.flip ? 7 - c : c) * SQ, y = TOP + (ed.flip ? 7 - r : r) * SQ;
    const piece = ed.rows[r][c];
    const what = piece ? (piece === piece.toUpperCase() ? "white " : "black ") + PIECES[piece.toUpperCase()] : "empty";
    extra += "<rect class=hit data-sq='" + name + "' x='" + x + "' y='" + y + "' width='" + SQ + "' height='" + SQ +
      "'><title>" + name + ", " + what + "</title></rect>";
    if (ed.sel === name) extra += "<rect class=sel x='" + (x + 1.5) + "' y='" + (y + 1.5) + "' width='" + (SQ - 3) +
      "' height='" + (SQ - 3) + "' pointer-events='none'/>";
  }
  s = s.replace(/<\/svg>$/, extra + "</svg>");
  $("fixboard").innerHTML = s;
  sizeCoords($("fixboard"));
  for (const b of $("fix").querySelectorAll("[data-turn]")) b.setAttribute("aria-pressed", String(b.dataset.turn === ed.turn));
  if (ed.sel) {
    const [r, c] = sqRC(ed.sel);
    for (const b of $("fixpieces").querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.put === ed.rows[r][c]));
  }
  const bad = positionProblem(ed.rows);
  $("fixsave").disabled = !!bad;
  if (bad) setMsg(bad, "bad"); else if ($("fixmsg").classList.contains("bad")) setMsg("");
}

/* a sequence placed in no line */
function openSeq(key){
  const u = seqInfo(key);
  if (!u) return;
  if (S.page !== u.page && (u.page in D.pages)) showPage(u.page);
  for (const el of document.querySelectorAll(".mark.seqcur")) el.classList.remove("seqcur");
  let first = null;
  for (const el of document.querySelectorAll(".mark[data-seq='" + CSS.escape(key) + "']")) { el.classList.add("seqcur"); if (!first) first = el; }
  RV.edit = {kind: "seq", key};
  const fixed = FIX.get("unattached", key);
  const joined = FIX.get("connect", key);
  const num = /^(\d{1,3})/.exec(u.text || "");
  const want = num ? parseInt(num[1], 10) : null;
  // the main-line moves on this page and the page before it, those with the sequence's move number first
  const mains = Object.values(D.nodes).filter(n => n.main && n.parent != null && n.key && n.fen && n.page);
  let cands = mains.filter(n => n.page === u.page || n.page === u.page - 1);
  if (cands.length < 3) cands = mains.filter(n => Math.abs(n.page - u.page) <= 3);
  const at = u.bbox || [0, 0];
  const dist = (n) => n.page !== u.page || !n.bbox ? 1e6 : Math.hypot(n.bbox[0] - at[0], 2 * (n.bbox[1] - at[1]));
  cands.sort((a, b) => ((b.number === want) - (a.number === want)) || dist(a) - dist(b) ||
    Math.abs(a.page - u.page) - Math.abs(b.page - u.page) ||
    parseInt(b.id.slice(1), 10) - parseInt(a.id.slice(1), 10));
  let h = "<div class=fh><h3>Place “<span class=n>" + shownHtml(u.text) + "</span>”</h3></div>";
  h += "<p class='small muted'>The program placed these moves in no line" + (u.reason ? ", because " + esc(u.reason) : "") +
    ". Choose the move of the line that they replace, or tap that move on the page.</p>";
  // a move printed without its number after a comment: the move the text prints it after is the natural join
  const afterId = u.after ? nodeByKey(u.after) : null;
  if (afterId && !joined)
    h += "<div class=fixacts><button class=tb id=fixafter>Continue the line after " + esc(moveText(afterId, true)) +
      "</button></div>";
  if (cands.length)
    h += "<div class='choices lines'>" + cands.slice(0, 12).map(n => "<button data-to='" + esc(n.key) + "' aria-pressed='" +
      String(!!fixed && fixed.attach_to === n.key) + "'>" + esc(moveText(n.id, true)) + "<span class=sub>" +
      esc(title(D.lines[n.line] ? D.lines[n.line].title : "")) + ", " + esc(pageName(n.page)) + "</span></button>").join("") + "</div>";
  h += "<p class='fixmsg small' id=fixmsg role=status></p>";
  h += "<div class=fixacts><button class=tb id=fixdismiss>Not a variation</button>" +
    "<button class=tb id=fixjoin>Continue a line…</button>" +
    (fixed || joined ? "<button class=tb id=fixundo>Remove your correction</button>" : "") + "</div>";
  h += "<p class='small muted'>Continue a line… joins these moves to a line: you then tap the move after which they follow.</p>";
  showFix(h, "seq");
  $("fixjoin").addEventListener("click", () => startConnect(key, "these moves"));
  if ($("fixafter")) $("fixafter").addEventListener("click", () => {
    PEN.connect = {key, label: "this move"};
    finishConnect(afterId);
    if (FIX.get("connect", key)) { const said = $("fixmsg").textContent; openSeq(key); setMsg(said, "good"); }
  });
  if (first) revealMark(first);
  $("fix").querySelector(".fix").addEventListener("click", (e) => {
    const t = e.target.closest("button[data-to]");
    if (!t) return;
    // while joining, the list's move is the one the moves follow, as a tap on the page is
    if (PEN.connect) { const id = nodeByKey(t.dataset.to); if (id) finishConnect(id); return; }
    attachTo(key, t.dataset.to);
  });
  $("fixdismiss").addEventListener("click", () => {
    FIX.set("unattached", key, {attach_to: "dismiss"}); RV.edit.sent = true; afterFix();
    setMsg("You marked these moves as no variation. " + applyWords(), "good");
  });
  if ($("fixundo")) $("fixundo").addEventListener("click", () => {
    FIX.set("unattached", key, null); FIX.set("connect", key, null); afterFix(); openSeq(key);
    setMsg("Your correction is removed. " + applyWords());
  });
}
function nodeByKey(key){ for (const id in D.nodes) if (D.nodes[id].key === key) return id; return null; }
function attachTo(key, target){
  const id = nodeByKey(target);
  if (!id) return;
  FIX.set("unattached", key, {attach_to: target});
  for (const b of $("fix").querySelectorAll("button[data-to]")) b.setAttribute("aria-pressed", String(b.dataset.to === target));
  const par = D.nodes[id].parent;
  if (par && D.nodes[par].fen) preview(D.nodes[par].fen, null);
  setMsg("A variation of " + moveText(id, true) + ", in its place. " + applyWords(), "good");
  if (RV.edit) RV.edit.sent = true;
  afterFix();
}

/* a piece symbol */
function symbolPlaces(sym){
  const out = [];
  for (const p in D.pages) D.pages[p].marks.forEach((m, i) => { if (m.symbol === sym) out.push([parseInt(p, 10), i, m]); });
  return out;
}
function symbolSide(m){ const n = m && m.node ? D.nodes[m.node] : null; return n ? sideOf(n) : "w"; }
function symbolChoices(sym, white){
  const cur = FIX.get("glyphs", sym);
  return "KQRBNP".split("").map(c => "<button data-piece='" + c + "' role=menuitemradio aria-checked='" +
    String(cur === c) + "' aria-pressed='" + String(cur === c) + "'>" + pieceSvg(c, white) + "<span>" +
    esc(D.pieceWords[c]) + "</span></button>").join("");
}
function symbolSaid(sym){
  const n = D.symbols[sym] || 0;
  return "This symbol appears " + words(n) + (n === 1 ? " time" : " times") + " in the book; " +
    (inApp() ? "the reader applies your choice to all of them now, this chapter first." :
      "the next run of the program applies your choice to all of them once you copy the corrections into the chat.");
}
function chooseSymbol(sym, piece){
  FIX.set("glyphs", sym, piece);
  afterFix();
  return "You chose the " + D.pieceWords[piece].toLowerCase() + " for the symbol “" + shown(sym) + "”. " + symbolSaid(sym);
}
function openSymbol(sym){
  const places = symbolPlaces(sym);
  const pick = places.find(([, , m]) => m.node && REVIEW.indexOf(D.nodes[m.node].status) >= 0) || places[0];
  if (pick) {
    const [p, i, m] = pick;
    // (the box printed with the symbol)
    if (m.node) selectNode(m.node, {at: SPOT[p + ":" + i] || null, page: p, scrollPage: false});
    else { if (S.page !== p) showPage(p); }
  }
  RV.edit = {kind: "symbol", sym};
  const white = symbolSide(pick ? pick[2] : null) === "w";
  let h = "<div class=fh><h3>Piece symbol “<span class=n>" + shownHtml(sym) + "</span>”</h3></div>";
  h += "<p class='small muted'>The text recognition could not name this piece symbol. It appears " +
    words(D.symbols[sym] || 0) + ((D.symbols[sym] || 0) === 1 ? " time" : " times") +
    " in the book. Choose the piece it stands for; the choice applies to every move printed with it.</p>";
  h += "<div class='pieces six' id=fixsym role=group aria-label='Pieces'>" + symbolChoices(sym, white) + "</div>";
  h += "<p class='fixmsg small' id=fixmsg role=status></p>";
  if (FIX.get("glyphs", sym)) h += "<div class=fixacts><button class=tb id=fixundo>Remove your correction</button></div>";
  showFix(h, "symbol");
  highlightMark(true);
  $("fixsym").addEventListener("click", (e) => {
    const t = e.target.closest("button[data-piece]");
    if (!t) return;
    const said = chooseSymbol(sym, t.dataset.piece);
    for (const b of $("fixsym").querySelectorAll("button")) {
      b.setAttribute("aria-pressed", String(b === t)); b.setAttribute("aria-checked", String(b === t));
    }
    setMsg(said, "good");
  });
  if ($("fixundo")) $("fixundo").addEventListener("click", () => {
    FIX.set("glyphs", sym, null); afterFix(); openSymbol(sym);
    setMsg("Your correction is removed. " + applyWords());
  });
}
/* the menu of an eye on the page */
function openSymMenu(btn){
  const sym = btn.dataset.sym, m = D.pages[S.page].marks[parseInt(btn.dataset.eye, 10)];
  const menu = $("symmenu");
  menu.innerHTML = "<li class='head small' role=presentation>Which piece is “<span class=n>" + shownHtml(sym) +
    "</span>”?</li>" + symbolChoices(sym, symbolSide(m) === "w").replace(/<button/g, "<li role=none><button").replace(/<\/button>/g, "</button></li>");
  menu.hidden = false;
  menu.dataset.sym = sym;
  // below the eye, or above it when the window has no room below
  const r = btn.getBoundingClientRect(), W = document.documentElement.clientWidth;
  const free = window.innerHeight - ($("mbar").offsetHeight || 0) - bottomCover();
  menu.style.left = Math.max(8, Math.min(r.left, W - menu.offsetWidth - 8)) + "px";
  menu.style.top = (r.bottom + 2 + menu.offsetHeight > free ? Math.max(8, r.top - 2 - menu.offsetHeight) : r.bottom + 2) + "px";
  const first = menu.querySelector("button");
  if (first) first.focus({preventScroll: true});
}
function closeSymMenu(){ const m = $("symmenu"); if (m) { m.hidden = true; m.innerHTML = ""; } }

function afterFix(){
  // (the reader opened from a file shows the sections read on its pages at once)
  regionRefresh();
  liveApply();
  if (RV.on) {
    const keep = RV.cur;
    renderReview();
    RV.cur = keep;
    const b = $("revlist").querySelector("button[data-item='" + keep + "']");
    if (b) b.setAttribute("aria-current", "true");
  }
  paintFixes();
  renderInfo();
  placeSheet();
}
function paintFixes(){
  // the boxes and eyes of the page show the corrections stored in this browser
  if (!S.page) return;
  for (const el of document.querySelectorAll("#ov .eye"))
    el.classList.toggle("fixed", !!FIX.get("glyphs", el.dataset.sym));
  for (const el of document.querySelectorAll("#ov .mark")) {
    const m = D.pages[S.page].marks[parseInt(el.dataset.mark, 10)];
    const n = m.node ? D.nodes[m.node] : null;
    // a box shows a correction that placed something, or one still waiting to be applied (a
    // correction the book holds that left the box as it was placed nothing)
    const mine = (part, k) => !!(k && FIX.get(part, k) && FIX.pending(part, k));
    const fixed = !!(m.corrected || (n && n.corrected) ||
      (n && ["moves", "connect", "disconnect", "gaps"].some((part) => mine(part, n.key))) ||
      (m.seq && (mine("unattached", m.seq) || mine("connect", m.seq))));
    el.classList.toggle("fixed", fixed);
  }
  threadPaint();
}
function pageEyes(){
  // an eye at each piece symbol that the program could not name, on moves that need a check
  const P = D.pages[S.page], ov = $("ov");
  P.marks.forEach((m, i) => {
    if (!m.symbol || !symbolNeeded(m)) return;
    const b = document.createElement("button");
    b.className = "eye";
    b.dataset.eye = i; b.dataset.sym = m.symbol;
    // as tall as half the printed move, on its top left corner, so that it
    // marks the symbol without covering the words around it at any zoom
    const h = (m.bbox[3] - m.bbox[1]) * 0.5, w = h * 4 / 3;
    b.style.left = pct(m.bbox[0] - w * 0.15, P.w); b.style.top = pct(m.bbox[1] - h * 0.35, P.h);
    b.style.width = pct(w, P.w); b.style.height = pct(h, P.h);
    b.innerHTML = EYE;
    const t = "Unreadable piece symbol “" + shown(m.symbol) + "”: choose the piece it stands for";
    b.title = t; b.setAttribute("aria-label", t); b.setAttribute("aria-haspopup", "menu");
    ov.appendChild(b);
  });
  paintFixes();
  // the section of the page being read, when it is on this page
  regionPaint();
}
/* ---------------- the pencil: correct anything on the page, and join or split lines */
const PEN = {on: false, connect: null, wasReading: null};  // wasReading: reading mode was on when the pencil came on
function lineFixWords(part, v){
  if (part === "connect") return "Joined by you to a line after another move.";
  if (v && v.remove) return "Taken out of the line by you.";
  return v && v.start && v.start !== "here" ? "A new line starts here from a diagram, as you said." :
    "A new line starts here, as you said.";
}
function lineStartOf(id){
  // the first move of the run a move belongs to: the first move of its line's main line, or of its variation
  const n = D.nodes[id];
  if (!n) return null;
  if (n.main) {
    const root = D.nodes[D.lines[n.line].root];
    return root.children.find(x => D.nodes[x] && D.nodes[x].main) || id;
  }
  let cur = id;
  for (;;) {
    const par = D.nodes[cur].parent;
    if (par == null || D.nodes[par].main || cont(par) !== cur) return cur;
    cur = par;
  }
}
function diagramsNear(page){
  const out = [];
  for (const p of [page - 1, page]) if (D.pages[p]) for (const d of D.pages[p].diagrams)
    if (d.selected && D.notPosition.indexOf(d.kind) < 0) out.push([p, d]);
  return out;
}
function lineActions(id){
  const n = D.nodes[id];
  if (!n || n.parent == null || !n.key) return "";
  const first = lineStartOf(id), isFirst = first === id, src = D.nodes[first];
  let h = "<div class=lineacts><p class='lab small'>The line</p><div class=fixacts>";
  if (n.main && !isFirst) h += "<button class=tb id=splithere>Start a new line here</button>";
  if (n.main) h += "<button class=tb id=splitdiag>" + (isFirst ? "Start this line from a diagram" :
    "Start a new line here from a diagram") + "</button>";
  h += "<button class=tb id=notpart>Not part of this line</button>";
  if (src && src.key) h += "<button class=tb id=joinline>Continue the line…</button>";
  h += "</div><div class='choices lines' id=diagpick hidden></div>";
  if (FIX.get("disconnect", n.key) || (src && src.key && FIX.get("connect", src.key)))
    h += "<div class=fixacts><button class=tb id=lineundo>Remove your change to the line</button></div>";
  h += "<p class='small muted'>" + (src && src.key ? "Continue the line… joins the moves from " +
    esc(moveText(first, true)) + " on to another line: you then tap the move after which they follow. " : "") +
    "Not part of this line takes the moves from " + esc(moveText(id, true)) + " to the end of the line out of it.</p>";
  return h + "</div>";
}
function wireLineActions(id){
  const n = D.nodes[id], first = lineStartOf(id), src = D.nodes[first];
  const on = (x, f) => { if ($(x)) $(x).addEventListener("click", f); };
  // the editor shows the change at once (with the button that removes it)
  const done = (msg) => { afterFix(); if (D.nodes[id]) openMove(id); setMsg(msg, "good"); };
  on("splithere", () => {
    FIX.set("disconnect", n.key, {start: "here"});
    done("A new line starts with " + moveText(id, true) + ", from the position before it. " + applyWords());
  });
  on("splitdiag", () => {
    const box = $("diagpick"), ds = diagramsNear(n.page || S.page);
    box.hidden = false;
    box.innerHTML = ds.length ? "<p class='lab small'>The diagram the line starts from</p>" + ds.map(([p, d]) =>
      "<button data-did='" + esc(d.id) + "'>" + esc(cap(diagramName(d, p))) + "<span class=sub>" +
      esc(d.fen ? "read" : "not read yet") + "</span></button>").join("") :
      "<p class='small muted'>No diagram stands on this page or the page before it.</p>";
    box.addEventListener("click", (e) => {
      const t = e.target.closest("button[data-did]");
      if (!t) return;
      FIX.set("disconnect", n.key, {start: t.dataset.did});
      done("The line from " + moveText(id, true) + " now starts from " + diagramLabel(t.dataset.did) + ". " +
        applyWords());
    });
  });
  on("notpart", () => {
    FIX.set("disconnect", n.key, {remove: true});
    done("The moves from " + moveText(id, true) + " to the end of the line now stand in no line. " + applyWords() +
      " The pencil can then join them to another line.");
  });
  on("joinline", () => startConnect(src.key, moveText(first, true)));
  on("lineundo", () => {
    FIX.set("disconnect", n.key, null);
    if (src && src.key) FIX.set("connect", src.key, null);
    done("Your change to the line is removed. " + applyWords());
  });
}
function startConnect(key, label){
  PEN.connect = {key, label};
  document.body.classList.add("joining");
  const t = "Tap the move, on the page or in the move list, after which " + label +
    " follows. The page arrows lead to other pages first. Escape stops.";
  setMsg(t);
  say(t);
}
function stopConnect(){ PEN.connect = null; document.body.classList.remove("joining"); }
function finishConnect(target){
  const c = PEN.connect;
  stopConnect();
  const t = D.nodes[target];
  if (!t || !t.key) { say("That move cannot take a continuation, because the program has no printed move for it."); return; }
  if (t.key === c.key) { say("A move cannot continue itself."); return; }
  // when the program has read the first move of the run, it checks it at once
  const sid = nodeByKey(c.key), s = sid ? D.nodes[sid] : null;
  if (s && s.san && t.fen) {
    if (!matchSan(s.san, CJ.legalMoves(t.fen))) {
      const side = t.fen.split(" ")[1] === "w" ? "White" : "Black";
      const why = s.san + " is not a legal move for " + side + " after " + moveText(target, true) +
        ", so the line cannot go on from there.";
      say(why); setMsg(why, "bad");
      return;
    }
  }
  FIX.set("connect", c.key, {after: t.key});
  if (RV.edit) RV.edit.sent = true;
  afterFix();
  const said = "You joined " + c.label + " to the line after " + moveText(target, true) + ". " + applyWords();
  say(said); setMsg(said, "good");
}
function setPencil(on, quiet){
  PEN.on = on;
  if (!on) stopConnect();
  document.body.classList.toggle("pencil", on);
  for (const b of [$("penbtn"), $("mpen")]) if (b) b.setAttribute("aria-pressed", String(on));
  // (reading mode turns it on without a word: it is the tool reading mode starts with)
  if (!quiet) say(on ? "Pencil on: a tap on a move, a diagram or a sequence on the page opens its correction. " +
    "A second tap on the pencil ends it." : "");
  if (!on && RV.edit && !RV.on) closeFix();
  // the pencil is a tool of reading mode, as Review is: on, it shows the reading; off, it leaves
  // the page as it found it
  if (on) {
    PEN.wasReading = reading();
    if (!PEN.wasReading) { setReading(true); renderInfo(); layoutPanel(false); }
  } else if (PEN.wasReading === false) {
    PEN.wasReading = null;
    setReading(false); renderInfo(); layoutPanel(false);
  }
}
function penClick(b){
  // the pencil's tap on the page: true when it handled the tap
  if (PEN.connect && b.dataset.node) { finishConnect(b.dataset.node); return true; }
  // while a section of the page is read, a tap on a move chooses the move its moves go with
  if (regionOpen() && b.dataset.node) { selectNode(b.dataset.node, {at: markBox(b)}); return true; }
  if (!PEN.on || b.dataset.eye) return false;
  // a move or a box in no line: its move is made on the board (the thread, below)
  if (threadTap(b)) return true;
  if (b.dataset.node) { const id = b.dataset.node; selectNode(id, {at: markBox(b)}); openMove(id); return true; }
  if (b.dataset.seq) { openSeq(b.dataset.seq); return true; }
  if (b.dataset.diagram) { openDiagramFix(b.dataset.diagram); return true; }
  return false;
}

/* ---------------- the thread: a line corrected move by move on the board */
// With the pencil, a tap on a move the program misread, or on a box it placed in no line, asks for
// the move printed there: the reader makes it on the board, from the position after the line's move
// before it. The correction is stored at once (corrections.py "moves", with "connect" for a box in
// no line, and the moves the text lacks before it as the join's "before"); once the book holds it
// the app's worker says what follows (driver.suggest): the next printed moves to join, a move the
// numbering says is missing, or a box that does not read, whose move the reader makes in turn. So
// the reader weaves the line through what the program could not read, until it reads on its own.
// TH.step: "own" (the move printed in the box), "gap" (a move missing before it), "next" (moves the
// program reads on, to join or skip), "wait" (the worker applies or reads), "tap" (nothing found:
// the reader taps the next box), "done". TH.kind: what a move made stores: "seq" (a box in no line:
// its move and the join), "line" (a move of a line: its move), "join" (the moves read on: the join),
// "gap" (a gap in the text: the moves given for it).
const TH = {on: false, step: null, kind: null, key: null, box: null, seq: null, page: null, node: null,
  anchor: null, fen: null, uci: null, before: [], need: 0, made: 0, cand: null, next: null, skip: [],
  req: 0, probe: 0, seqn: 0, wait: null, sent: null, prev: null, stored: false, self: false, said: "",
  promo: null, offer: null, raw: null};
function threadEnd(){
  if (!TH.on && !TH.step) return;
  Object.assign(TH, {on: false, step: null, kind: null, key: null, box: null, seq: null, page: null, node: null,
    anchor: null, fen: null, uci: null, before: [], need: 0, made: 0, cand: null, next: null, skip: [],
    req: 0, probe: 0, wait: null, sent: null, prev: null, stored: false, said: "", promo: null, offer: null, raw: null});
  for (const el of document.querySelectorAll("#ov .mark.seqcur")) el.classList.remove("seqcur");
}
function threadSource(){
  // the position a move on the board starts from while the thread asks for one, or null
  if (!TH.fen || TH.promo || (TH.step === "done" && !inApp())) return null;
  return {id: TH.anchor, at: TH.anchor, fen: TH.fen, gap: null, thread: true};
}
// a move chosen by the thread: the page and the board stay with the thread's sheet
function threadSelect(id, opts){
  if (id == null || !D.nodes[id]) return;
  TH.self = true;
  try { selectNode(id, opts); } finally { TH.self = false; }
}
function ordinal(k){
  const t = k % 100;
  return k + (t >= 11 && t <= 13 ? "th" : ["th", "st", "nd", "rd"][k % 10] || "th");
}
function fenPly(fen){ const f = fen.split(" "); return 2 * (parseInt(f[5] || "1", 10) - 1) + (f[1] === "b" ? 1 : 0); }
// "Black's 5th move": the move the side to move makes in a position
function plyWords(fen){
  const f = fen.split(" ");
  return (f[1] === "b" ? "Black" : "White") + "'s " + ordinal(parseInt(f[5] || "1", 10)) + " move";
}
// the move a SAN names in a position, as [SAN, UCI], or null
function sanIn(fen, san){ const legal = CJ.legalMoves(fen); return legal.find(x => x[0] === san) || matchSan(san, legal); }
// the position after the thread's anchor and the moves made after it
function threadFen(){
  let fen = TH.anchor != null ? nodeFen(TH.anchor) : null;
  TH.uci = TH.anchor != null && D.nodes[TH.anchor] ? D.nodes[TH.anchor].uci || null : null;
  const ok = [];
  for (const s of TH.before) {
    const m = fen ? sanIn(fen, s) : null;
    if (!m) break;
    fen = CJ.after(fen, m[1]); TH.uci = m[1]; ok.push(m[0]);
  }
  TH.before = ok;
  return fen;
}
// the last move the board shows, in words: "5…f5", or the anchor's
function lastText(){
  if (!TH.before.length) return TH.anchor != null && D.nodes[TH.anchor] && D.nodes[TH.anchor].parent != null ?
    moveText(TH.anchor, true) : "the start";
  let fen = nodeFen(TH.anchor), t = "";
  for (const s of TH.before) {
    const f = fen.split(" "), m = sanIn(fen, s);
    t = f[5] + (f[1] === "b" ? "…" : ".") + s;
    fen = CJ.after(fen, m[1]);
  }
  return t;
}
// the printed box of a suggestion, as "6.c4"
function boxText(r){ return (r.number != null ? r.number + (r.black ? "…" : ".") : "") + shown(r.raw); }
// the moves the program reads on, numbered from the thread's position: "6.c4 Bh6 7.e3 f4 …"
function nextText(r){
  let fen = TH.fen, out = [];
  for (const d of r.decoded.slice(0, 6)) {
    const m = fen ? sanIn(fen, d.san) : null;
    if (!m) break;
    const f = fen.split(" ");
    out.push((!out.length || f[1] === "w" ? f[5] + (f[1] === "b" ? "…" : ".") : "") + m[0]);
    fen = CJ.after(fen, m[1]);
  }
  return out.join(" ") + (r.decoded.length > out.length ? " …" : "");
}
// where moves after node id are joined: {after: the key of the printed move at or before it, before:
// the moves from there to id}, or null at the start of a line
function anchorSpec(id){
  const san = [];
  for (let cur = id; cur != null && D.nodes[cur]; cur = D.nodes[cur].parent) {
    const n = D.nodes[cur];
    if (n.parent == null) return null;
    if (n.key) return {after: n.key, before: san};
    san.unshift(n.san);
  }
  return null;
}
// the last move of the branch node id is on, as the worker follows it (driver.suggest)
function branchEnd(id){
  for (let cur = id; ;) {
    const n = D.nodes[cur];
    const nx = n.children.find(c => D.nodes[c] && D.nodes[c].line === n.line && !!D.nodes[c].main === !!n.main);
    if (!nx || !D.nodes[nx].san || D.nodes[nx].status === "waiting") return cur;
    cur = nx;
  }
}
// the move printed before a box in reading order: the nearest box with a move, on its page or the one
// before, with a position after it
function boxBefore(page, pos){
  for (let k = ORD.length - 1; k >= 0; k--) {
    const b = ORD[k];
    if (b.pos >= pos) continue;
    if (b.page < page - 1) break;
    const n = D.nodes[b.node];
    if (n && n.fen && n.parent != null) return b;
  }
  return null;
}
// the ply the number printed before a box in no line names (null when none is printed there)
function printedPly(key){
  const u = D.unattached.find(x => x.key === key);
  const m = u && /^\s*(\d{1,3})\s*(\.\s*\.\s*\.|…)?/.exec(u.text || "");
  return m ? 2 * (parseInt(m[1], 10) - 1) + (m[2] ? 1 : 0) : null;
}
// a box in no line whose printed number lies ahead of the position: the moves the text lacks first
function threadNeed(){
  TH.need = 0; TH.made = 0; TH.cand = null; TH.step = "own";
  const want = TH.fen ? printedPly(TH.key) : null;
  const k = want != null ? want - fenPly(TH.fen) : 0;
  if (k > 0 && k <= 4) {
    TH.need = k; TH.step = "gap";
    // the worker offers the moves the words between may stand for
    if (inApp()) threadPost(true);
  }
}
function threadPost(probe){
  const n = D.nodes[TH.anchor], id = ++TH.seqn;
  if (probe) TH.probe = id; else TH.req = id;
  parent.postMessage({suggest: {after: n && n.key ? n.key : TH.anchor, before: TH.before.slice(), skip: TH.skip.slice(),
    id}}, "*");
}
// the pencil's tap on a box: true when the thread takes it
function threadTap(b){
  const m = b.dataset.mark != null ? D.pages[S.page].marks[parseInt(b.dataset.mark, 10)] : null;
  if (!m) return false;
  const id = b.dataset.node;
  if (id) {
    const n = D.nodes[id];
    // (a gap, a move whose position the gap before it leaves unknown, a move the reader added or
    // read, a start: their own editors)
    if (!n || n.parent == null || !n.key || n.gap || !beforeFen(n) || n.corrected === "added" || n.region) return false;
    // while the move of a box in no line is asked for, a move tapped is the one it follows
    if (TH.on && TH.kind === "seq" && (TH.step === "own" || TH.step === "gap")) {
      if (n.fen) threadAnchor(id, markBox(b));
      return true;
    }
    threadBegin({kind: "line", key: n.key, box: m.key, page: S.page, node: id, at: markBox(b)});
    return true;
  }
  if (b.dataset.seq && m.key) {
    threadBegin({kind: "seq", key: m.key, seq: b.dataset.seq, raw: m.raw, page: S.page,
      pos: S.page * 1e5 + parseInt(b.dataset.mark, 10)});
    return true;
  }
  return false;
}
// a tap on a move in the move list: the move a box in no line follows, while its move is asked for
function threadTree(id){
  if (!(TH.on && TH.kind === "seq" && (TH.step === "own" || TH.step === "gap"))) return false;
  const n = D.nodes[id];
  if (n && n.fen && n.parent != null) threadAnchor(id, null);
  return true;
}
function threadAnchor(id, box){
  TH.anchor = id; TH.before = []; TH.said = "";
  threadSelect(id, box ? {at: box} : {fromPage: true});
  TH.fen = threadFen();
  threadNeed();
  threadShow();
}
function threadBegin(o){
  // a thread under way goes on from its line's last move and the moves made after it
  const going = TH.on && TH.anchor != null && D.nodes[TH.anchor] && (TH.stored || TH.next) && o.kind === "seq" ?
    {anchor: TH.anchor, before: TH.before.slice(), skip: TH.skip.slice(), stored: TH.stored} : null;
  if (RV.edit && RV.edit.kind !== "thread") closeFix();
  threadEnd();
  Object.assign(TH, {on: true, kind: o.kind, key: o.key, box: o.box || o.key, seq: o.seq || null, page: o.page,
    node: o.node || null, raw: o.raw || null}, going || {});
  if (o.kind === "line") {
    // the position before the move: the board shows it, and the move list the move
    TH.anchor = D.nodes[o.node].parent;
    threadSelect(o.node, {at: o.at});
    TH.fen = threadFen();
    TH.step = "own";
  } else {
    // (a move printed without its number after a comment follows the move the text prints it after)
    const u = seqInfo(o.seq), after = u && u.key === o.key && u.after ? nodeByKey(u.after) : null;
    if (going) threadSelect(TH.anchor, {fromPage: true});
    else if (after && D.nodes[after].fen) { TH.anchor = after; threadSelect(after, {fromPage: true}); }
    else {
      const b = boxBefore(o.page, o.pos);
      TH.anchor = b ? b.node : null;
      if (b) threadSelect(b.node, b.page === S.page ? {at: b} : {fromPage: true});
    }
    TH.fen = threadFen();
    threadNeed();
  }
  threadShow();
  threadReveal();
}
// the box asked about, outlined (the page's boxes are drawn again on each page shown)
function threadPaint(){
  if (!TH.on) return;
  for (const el of document.querySelectorAll("#ov .mark")) {
    const m = D.pages[S.page].marks[parseInt(el.dataset.mark, 10)];
    el.classList.toggle("seqcur", !!m && TH.page === S.page && m.key === TH.box && TH.step !== "done");
  }
}
function threadReveal(){
  const el = document.querySelector("#ov .mark.seqcur");
  if (el) revealMark(el);
}
function threadShow(){
  if (!TH.on) return;
  const B = [];
  let line = "";
  // the move offered: the one the worker read there, or a box in no line that reads as a legal move
  const cand = TH.step === "gap" && TH.cand ? TH.cand[TH.made] : TH.step === "own" && TH.cand ? TH.cand[0] :
    TH.step === "own" && TH.kind === "seq" && TH.raw ? TH.raw : null;
  const play = cand && TH.fen ? sanIn(TH.fen, cand) : null;
  if (TH.promo) {
    line = "Promote the pawn to";
    B.push(...TH.promo.map(m => ["thpro" + m[1][4], D.pieceWords[m[1][4].toUpperCase()], () => { TH.promo = null; threadMove(m); }]));
    B.push(["thback", "Cancel", () => { TH.promo = null; threadShow(); }]);
  } else if (TH.step === "own") {
    const n = TH.kind === "line" ? D.nodes[TH.node] : null;
    if (!TH.fen) line = "Tap the move these moves follow.";
    else if (n && n.san && n.status !== "failed") line = "Make the move printed here on the board.";
    else line = "After <span class=n>" + esc(lastText()) + "</span>, make the move printed here on the board.";
    if (play) B.push(["thplay", "Play " + play[0], () => threadMove(play)]);
    if (TH.kind === "seq") B.push(["thnot", "Not a move", threadDismiss]);
    B.push(["thmore", "More", threadMore]);
  } else if (TH.step === "gap") {
    line = esc(plyWords(TH.fen)) + " is missing " + (TH.next ? "before <span class=n>" + esc(boxText(TH.next)) +
      "</span>" : "here") + ". Make it on the board.";
    if (play) B.push(["thplay", "Play " + play[0], () => threadMove(play)]);
    if (TH.next) B.push(["thskip", "Skip", threadSkip]);
  } else if (TH.step === "next") {
    line = "Next: <span class=n>" + esc(nextText(TH.next)) + "</span> (" + esc(pageName(TH.next.page)) + ")";
    B.push(["thjoin", "Join", () => threadStore(null)], ["thskip", "Skip", threadSkip]);
  } else if (TH.step === "wait") {
    line = TH.wait === "patch" ? "Applying your move." : "Looking for what follows.";
  } else if (TH.step === "tap") {
    line = "Tap the next move on the page.";
  } else if (TH.step === "done") {
    line = inApp() ? "The line reads to its end." : "Stored. Copy the corrections on the contents page into the chat.";
  }
  B.push(TH.step === "done" ? ["thclose", "Close", closeSheet] : ["thcancel", "Cancel", closeSheet]);
  let h = "<p class=thl>" + line + "</p><p class='fixmsg small' id=fixmsg role=status></p>";
  h += "<div class=fixacts>" + B.map(b => "<button class=tb id=" + b[0] + ">" + esc(b[1]) + "</button>").join("") + "</div>";
  showFix(h, "thread", false);
  for (const b of B) $(b[0]).addEventListener("click", b[2]);
  if (TH.said) setMsg(TH.said, "bad");
  // the board shows the thread's position, with the move offered drawn on it
  TH.offer = play ? play[1] : null;
  renderBoard();
  threadPaint();
  keepChooserInView();
}
function threadMore(){
  // the box's full editor: the place of a box in no line, or the move's own corrections
  const seq = TH.seq, node = TH.kind === "line" ? TH.node : null;
  closeFix();
  if (node) openMove(node); else if (seq) openSeq(seq);
}
function threadDismiss(){
  const seq = TH.seq || TH.key, key = TH.key;
  FIX.set("unattached", seq, {attach_to: "dismiss"});
  afterFix();
  if (inApp() && TH.stored) { TH.skip.push(key); TH.said = ""; threadAsk(); }
  else { closeFix(); say("Marked as no move."); }
}
function threadSkip(){
  TH.skip.push(TH.key);
  TH.said = "";
  threadAsk();
}
// a move made on the board while the thread asks for one
function threadMove(m){
  if (!TH.on || !TH.fen) return;
  TH.said = "";
  TH.fen = CJ.after(TH.fen, m[1]); TH.uci = m[1];
  if (TH.step === "own") { threadStore(m[0]); return; }
  TH.before.push(m[0]);
  if (TH.step === "gap") {
    if (TH.cand && TH.cand[TH.made] !== m[0]) TH.cand = null;
    TH.made++; TH.need--;
    if (TH.need > 0) { threadShow(); return; }
    TH.cand = null;
    // the box's own move next; a gap in the text is filled; moves read on are offered again from here
    if (TH.kind === "seq") { TH.step = "own"; threadShow(); return; }
    if (TH.kind === "gap") { threadStore(null); return; }
    threadAsk();
    return;
  }
  // a move of the reader's own after the line's last move: a move the text lacks before what follows
  TH.next = null;
  if (TH.step === "wait" && TH.wait === "patch") { threadShow(); return; }
  threadAsk();
}
// the correction a move (or Join) makes, stored and sent to the worker
function threadStore(san){
  TH.prev = {anchor: TH.anchor, before: TH.before.slice(), kind: TH.kind, key: TH.key, box: TH.box, seq: TH.seq,
    page: TH.page, next: TH.next, node: TH.node};
  const spec = TH.anchor != null ? anchorSpec(TH.anchor) : null;
  const join = () => {
    // (the keys in the order corrections.py writes them, as the store compares them)
    const c = {after: spec.after}, bf = spec.before.concat(TH.before);
    if (bf.length) c.before = bf;
    FIX.set("connect", TH.key, c);
  };
  if (TH.kind === "line") FIX.set("moves", TH.key, {san});
  else if (TH.kind === "gap") FIX.set("gaps", TH.key, {san: TH.before.slice()});
  else {
    if (!spec) { TH.said = "The line has no printed move to go on from."; TH.fen = threadFen(); threadShow(); return; }
    if (TH.kind === "seq") FIX.set("moves", TH.key, {san});
    join();
  }
  TH.sent = {kind: TH.kind, key: TH.key, san, after: spec ? spec.after : null};
  TH.stored = true; TH.before = []; TH.need = 0; TH.made = 0; TH.cand = null; TH.next = null;
  TH.step = "wait"; TH.wait = "patch";
  afterFix();
  // the reader opened from a file applies nothing: the corrections wait for the next run
  if (!inApp()) TH.step = "done";
  threadShow();
}
// the book holds the correction, or says why it does not
function threadPatched(p){
  if (TH.step !== "wait" || TH.wait !== "patch" || !TH.sent) return;
  const s = TH.sent, id = nodeByKey(s.key), n = id ? D.nodes[id] : null;
  let ok = !!n;
  if (ok && (s.kind === "seq" || s.kind === "join")) { const a = nodeByKey(s.after); ok = !!a && D.nodes[a].line === n.line; }
  if (ok && s.kind === "line") ok = !!n.san && sanKey(n.san) === sanKey(s.san);
  if (ok && s.kind === "gap") ok = !!n.fen;
  if (!ok) {
    // (a new reading of the chapter while the book is read is not the answer)
    if (p.reading !== undefined) return;
    const u = seqInfo(s.key) || seqInfo(TH.prev.seq);
    const why = (u && u.reason) || (n && n.reason) || "the program could not place it";
    const was = TH.prev;
    Object.assign(TH, {anchor: was.anchor, before: was.before, key: was.key, box: was.box, seq: was.seq, page: was.page,
      node: was.node, next: was.next, sent: null, said: "Not joined: " + why + "."});
    TH.fen = threadFen();
    if (was.kind === "gap") { TH.kind = "gap"; TH.need = TH.before.length || 1; TH.made = 0; TH.before = []; TH.fen = threadFen(); TH.step = "gap"; }
    else { TH.kind = was.kind === "join" ? "seq" : was.kind; TH.step = "own"; }
    threadShow();
    return;
  }
  TH.sent = null; TH.prev = null;
  // the reader is on the line's last move; moves made meanwhile go on from it when it is that move
  const end = branchEnd(id);
  if (end !== id) TH.before = [];
  TH.anchor = end;
  threadSelect(end, {fromPage: true});
  TH.fen = threadFen();
  threadAsk();
}
function threadAsk(){
  TH.next = null; TH.cand = null; TH.need = 0; TH.made = 0;
  if (!inApp()) { TH.step = "done"; threadShow(); return; }
  TH.step = "wait"; TH.wait = "suggest";
  threadPost(false);
  threadShow();
}
// what follows, from the worker: {done}, or the next box with what the program reads there
function threadSuggested(a){
  if (!TH.on || !a) return;
  const r = a.result || {};
  if (a.id === TH.probe) {
    TH.probe = 0;
    if (TH.step === "gap" && r.key === TH.key && r.between && r.between.length) { TH.cand = r.between[0]; threadShow(); }
    return;
  }
  if (a.id !== TH.req || TH.step !== "wait") return;
  TH.req = 0;
  if (r.done) { TH.step = "done"; threadShow(); return; }
  const from = r.after_node && D.nodes[r.after_node] ? r.after_node : r.after ? nodeByKey(r.after) : null;
  if (from && from !== TH.anchor) { TH.anchor = from; threadSelect(from, {fromPage: true}); }
  TH.fen = threadFen();
  Object.assign(TH, {key: r.key, box: r.key, seq: r.kind === "run" ? r.key : null, page: r.page, next: r, made: 0,
    cand: null, need: 0, node: null, raw: r.raw || null});
  if (r.kind === "gap" || r.number_gap > 0) {
    TH.kind = r.kind === "gap" ? "gap" : "join";
    TH.step = "gap"; TH.need = Math.max(1, r.number_gap || 0);
    TH.cand = r.between && r.between.length ? r.between[0] : null;
  } else if (r.kind !== "failed" && r.decoded && r.decoded.length) {
    TH.kind = "join"; TH.step = "next";
  } else {
    // a box that does not read from here: its move is the reader's to make
    TH.kind = r.kind === "failed" ? "line" : "seq";
    if (TH.kind === "line") TH.node = nodeByKey(r.key);
    TH.step = "own";
    TH.cand = r.decoded && r.decoded.length ? [r.decoded[0].san] : null;
  }
  // the page turns to the box when the box is on another page
  if (r.page !== S.page && (r.page in D.pages)) showPage(r.page);
  threadShow();
  threadReveal();
}
function threadNoSuggestion(id, text){
  if (!TH.on) return;
  if (id === TH.probe) { TH.probe = 0; return; }
  if (id !== TH.req) return;
  TH.req = 0; TH.step = "tap"; TH.said = text || "";
  threadShow();
}
function threadFailed(text){
  if (!(TH.on && TH.step === "wait" && TH.wait === "patch")) return;
  TH.step = "tap"; TH.said = text; TH.sent = null;
  threadShow();
}

/* ---------------- corrections applied at once (the browser app) */
function liveApply(){
  if (!inApp()) return;
  say("Applying your correction.");
  parent.postMessage({correct: FIX.text(), chapter: D.chapter.file}, "*");
}
function applyPatch(p){
  // the changes the app's worker made to this chapter's data: the page and the move stay put
  for (const id of p.removed || []) delete D.nodes[id];
  Object.assign(D.nodes, p.nodes || {});
  if (p.lines) { D.lines = p.lines; D.lineOrder = p.lineOrder; }
  for (const k in (p.pages || {})) if (D.pages[k]) {
    Object.assign(D.pages[k], p.pages[k]);
    for (const d of D.pages[k].diagrams || []) kinds[d.id] = d.kind;
  }
  for (const k of ["unattached", "dismissed", "symbols", "pgn"]) if (p[k] !== undefined) D[k] = p[k];
  if (p.corrections) { D.corrections = p.corrections; FIX.rebase(p.corrections); }
  // a new reading of the chapter while the app reads the book (see progressive.py)
  const reread = p.reading !== undefined;
  if (reread) { D.reading = p.reading; readingState(); }
  indexBoxes();
  // the reader's box keeps its place by its key, with the move the new reading prints there; else
  // a renamed move wins: a new reading may give the same id to another move
  const ren = p.renamed || {};
  const box = boxAt(S.at);
  if (box && S.node) S.node = box.node;
  else {
    S.at = null;
    if (S.node && (ren[S.node] || !D.nodes[S.node])) S.node = ren[S.node] || null;
  }
  const edit = RV.edit;
  if (edit && edit.node && (ren[edit.node] || !D.nodes[edit.node])) edit.node = ren[edit.node] || null;
  if (S.node) S.line = D.nodes[S.node].line;
  else if (S.line && !D.lines[S.line]) S.line = null;
  showPage(S.page);
  renderTree(); renderBoard(); renderInfo(); layoutPanel(false); highlightMark(false);
  if (RV.on) { const keep = RV.cur; renderReview(); RV.cur = keep; }
  if (edit && edit.kind === "move" && !$("fix").hidden) {
    if (edit.node) { openMove(edit.node); setMsg("Your correction is applied.", "good"); }
    else closeFix();
  }
  if (edit && edit.kind === "gap" && !$("fix").hidden) {
    const g = gapInfo(edit.key);
    if (g.hole || g.filled.length) { openGap(edit.key); setMsg("Your correction is applied.", "good"); }
    else closeFix();
  }
  if (edit && edit.kind === "added" && !$("fix").hidden) {
    if (edit.node) { openAdded(edit.node); setMsg("Your correction is applied.", "good"); }
    else closeFix();
  }
  // a sequence placed, joined or dismissed from its sheet: what became of it (a refusal says why)
  let said = null;
  if (edit && edit.kind === "seq" && edit.sent && p.corrections && !$("fix").hidden) {
    const u = seqInfo(edit.key);
    if (u && !u.dismissed) {
      openSeq(edit.key);
      said = "Not placed" + (u.reason ? ": " + u.reason : "") + ".";
      setMsg(said, "bad");
    } else { closeFix(); said = u ? "Marked as no variation." : "Placed in the line."; }
  }
  // the thread goes on once the book holds the move made on the board
  const thread = !!(edit && edit.kind === "thread" && TH.on);
  if (thread && p.corrections) threadPatched(p);
  // the move made on the board: it is chosen once the book holds it
  if (p.corrections) boardMoveApplied();
  const pgn = $("pgnbtn");
  if (pgn) pgn.disabled = !D.pgn;
  // the place the app came back to, now that this reading holds it, on the page shown only
  const w = S.wanted;
  if (w && w.page === S.page) {
    const wb = w.key ? BOX[w.key] : null;
    if (wb && wb.page === S.page) selectNode(wb.node, {at: wb, scrollPage: false});
    else if (w.node && D.nodes[w.node] && boxesOn(w.node, S.page).length) selectNode(w.node, {fromPage: true, scrollPage: false});
  }
  placeHash();
  setState();
  // a new reading speaks only in reading mode; the top bar already says how far the app has come
  if (thread) say("");
  else if (!reread || reading()) say(said || p.progress || "Your correction is applied.");
  else say("");
  // corrections stored in this browser that the new reading does not hold yet
  if (reread && inApp() && FIX.anyPending()) liveApply();
}
window.applyPatch = applyPatch;
function initPencil(){
  for (const b of [$("penbtn"), $("mpen")]) if (b) b.addEventListener("click", () => setPencil(!PEN.on));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (PEN.connect) { stopConnect(); say(""); }
    // Escape ends the thread; the corrections made stay
    if (TH.on) closeFix();
  });
  window.addEventListener("message", (e) => {
    if (e.source !== window.parent || e.source === window) return;
    const m = e.data || {};
    if (m.patch) applyPatch(m.patch);
    else if (m.progress) say(m.progress);
    else if (m.failed) { say(m.failed); threadFailed(m.failed); }
    else if (m.suggested) threadSuggested(m.suggested);
    else if (m.suggestFailed !== undefined) threadNoSuggestion(m.id, m.suggestFailed);
  });
}

/* ---------------- moving pieces on the board */
// A piece moved on the board (dragged, or tapped and then its square tapped) is a move from the
// position the board shows. The move the line already holds there is stepped to; a move into a
// gap in the text fills it; any other move asks whether it corrects the main line or the
// variation, or adds a variation of the reader's own (corrections.py "added").
const BM = {pick: null, down: null, want: null};
function samePos(a, b){ return !!a && !!b && a.split(" ").slice(0, 2).join(" ") === b.split(" ").slice(0, 2).join(" "); }
function moveSource(box){
  // what a move on the board in box starts from: {id: the node shown, at: the node whose position it
  // is, fen, gap: the gap in the text the move fills, or null}, or null when the board takes no move
  // while a move is asked for (the thread) the board takes it from the position the thread shows
  if (TH.on && box.id !== "dpanel") return threadSource();
  if (S.preview || (RV.edit && RV.edit.kind === "diagram")) return null;
  if (box.id === "dpanel") {
    // the diagram view: its position, when it starts the line the panel names
    const L = S.diagram && S.line ? D.lines[S.line] : null, d = S.diagram ? diagramInfo(S.diagram)[1] : null;
    const fen = L ? nodeFen(L.root) : null;
    return fen && d && d.fen && d.fen.split(" ")[0] === fen.split(" ")[0] ? {id: L.root, at: L.root, fen, gap: null} : null;
  }
  if (S.diagram) return null;
  const id = S.node || (S.line && D.lines[S.line] ? D.lines[S.line].root : null);
  const n = id ? D.nodes[id] : null;
  if (!n) return null;
  if (n.fen && n.status !== "waiting") {
    const c = cont(id), hole = c && D.nodes[c].gap && !D.nodes[c].san ? D.nodes[c].gap : null;
    return {id, at: id, fen: n.fen, gap: hole};
  }
  // a gap in the text, or a move after it: the board shows the position before the gap
  const known = beforeGap(id);
  return known ? {id, at: known, fen: nodeFen(known), gap: gapKeyOf(id)} : null;
}
function boardBoxes(){ return [$("board"), $("minibox"), $("dpanel")].filter(Boolean); }
function srcSig(src){ return src ? src.at + "|" + src.fen : ""; }
function squareAt(svg, x, y){
  const r = svg.getBoundingClientRect(), H = TOP + 8 * SQ + M;
  if (!r.width) return null;
  const c = Math.floor(((x - r.left) * BW / r.width - M) / SQ), row = Math.floor(((y - r.top) * H / r.height - TOP) / SQ);
  if (c < 0 || c > 7 || row < 0 || row > 7) return null;
  const flip = svg.dataset.flip === "1";
  return "abcdefgh"[flip ? 7 - c : c] + (flip ? row + 1 : 8 - row);
}
function pieceOn(fen, sq){ const [r, c] = sqRC(sq); return fenRows(fen)[r][c]; }
function ownPiece(fen, sq){
  const p = pieceOn(fen, sq);
  return !!p && (p === p.toUpperCase()) === ((fen.split(" ")[1] || "w") === "w");
}
function targetsOf(fen, from){ return CJ.legalMoves(fen).filter(m => m[1].slice(0, 2) === from); }
function boardSvgOf(box){ return box.id === "dpanel" ? box.querySelector(".boardwrap svg.board") : box.querySelector("svg.board"); }
function sqXY(svg, sq){
  const flip = svg.dataset.flip === "1", f = "abcdefgh".indexOf(sq[0]), r = 8 - parseInt(sq[1], 10);
  return [M + (flip ? 7 - f : f) * SQ, TOP + (flip ? 7 - r : r) * SQ];
}
function paintBoards(){
  // the piece chosen and the squares it can go to, on each board that shows the position
  for (const box of boardBoxes()) {
    const svg = boardSvgOf(box);
    if (!svg) continue;
    for (const el of svg.querySelectorAll(".bmx")) el.remove();
    const src = moveSource(box);
    svg.classList.toggle("movable", !!src);
    for (const u of svg.querySelectorAll("use[data-at]"))
      if (src && ownPiece(src.fen, u.dataset.at)) u.setAttribute("data-mine", ""); else u.removeAttribute("data-mine");
    if (!src || !BM.pick || BM.pick.sig !== srcSig(src)) continue;
    const NS = "http://www.w3.org/2000/svg";
    const add = (tag, attrs) => {
      const el = document.createElementNS(NS, tag);
      for (const k in attrs) el.setAttribute(k, attrs[k]);
      el.setAttribute("pointer-events", "none");
      svg.insertBefore(el, svg.querySelector("use"));
      return el;
    };
    const [x, y] = sqXY(svg, BM.pick.sq);
    add("rect", {class: "bmx pk", x: x + 1.5, y: y + 1.5, width: SQ - 3, height: SQ - 3});
    const seen = new Set();
    for (const m of targetsOf(src.fen, BM.pick.sq)) {
      const to = m[1].slice(2, 4);
      if (seen.has(to)) continue;
      seen.add(to);
      const [tx, ty] = sqXY(svg, to);
      if (pieceOn(src.fen, to)) add("circle", {class: "bmx tgc", cx: tx + SQ / 2, cy: ty + SQ / 2, r: SQ / 2 - 3});
      else add("circle", {class: "bmx tg", cx: tx + SQ / 2, cy: ty + SQ / 2, r: 5});
    }
  }
}
function pathOf(id){
  // the moves from the start of the line to node id: a printed move by its key, another by its SAN
  const out = [];
  for (let cur = id; cur != null && D.nodes[cur] && D.nodes[cur].parent != null; cur = D.nodes[cur].parent)
    out.unshift(D.nodes[cur].key ? {key: D.nodes[cur].key} : {san: D.nodes[cur].san});
  return out;
}
function nodeAt(line, steps){
  const L = D.lines[line];
  let cur = L ? L.root : null;
  for (const st of steps) {
    if (!cur) return null;
    const kids = D.nodes[cur].children;
    cur = (st.key ? kids.find(c => D.nodes[c].key === st.key) : kids.find(c => D.nodes[c].san === st.san)) || null;
  }
  return cur;
}
function boardMoveApplied(){
  const w = BM.want;
  BM.want = null;
  const id = w ? nodeAt(w.line, w.steps) : null;
  if (id && id !== S.node) selectNode(id, {scrollPage: false});
}
function addedTop(id){
  // the first move of the variation (as the move list shows it) that a move the reader added belongs to
  let cur = id;
  for (;;) {
    const par = D.nodes[cur].parent;
    if (par == null || D.nodes[par].corrected !== "added" || cont(par) !== cur) return cur;
    cur = par;
  }
}
function addedPath(id){
  // where a move the reader added is stored: {key, before, san: the moves from the branch to it}
  const san = [];
  let cur = id;
  while (cur != null && D.nodes[cur].corrected === "added") { san.unshift(D.nodes[cur].san); cur = D.nodes[cur].parent; }
  return {key: D.nodes[id].added, before: !!D.nodes[id].added_before, san};
}
function anchorOf(at){
  // where a new variation from the position after node at is stored, or null
  const n = D.nodes[at];
  if (n.corrected === "added") return addedPath(at);
  if (n.key && n.parent != null && n.fen) return {key: n.key, before: false, san: []};
  // no printed move here (the start of the line, or a move given for a gap): before the next printed move
  const c = n.children.find(x => D.nodes[x].key && D.nodes[x].main) || n.children.find(x => D.nodes[x].key);
  return c ? {key: D.nodes[c].key, before: true, san: []} : null;
}
const isPrefix = (a, b) => a.length <= b.length && a.every((x, i) => x === b[i]);
function storeAdded(key, entries){
  // the variations stored at one printed move: no duplicates, and none that another one holds whole;
  // the moves read from a section of a page keep their own entry (with the section), and one whose
  // own moves are all gone is no entry
  const out = [];
  const section = (e) => e.rect ? e.page + ":" + e.rect.join(",") : "";
  for (const e of entries) {
    if (!e.san.length || (e.first && e.first >= e.san.length)) continue;
    const before = !!e.before;
    if (!e.rect && entries.some(o => o !== e && !o.rect && !!o.before === before && o.san.length > e.san.length &&
        isPrefix(e.san, o.san))) continue;
    if (out.some(o => !!o.before === before && section(o) === section(e) && o.san.join(" ") === e.san.join(" "))) continue;
    out.push(e);
  }
  FIX.set("added", key, out.length ? out : null);
}
function entry(san, before, note){
  const e = {san};
  if (before) e.before = true;
  if (note) e.note = note;
  return e;
}
function addVariation(anchor, san){
  // a new variation, or the one it goes on from made longer
  const path = anchor.san.concat([san]);
  const list = (FIX.get("added", anchor.key) || []).map(e => Object.assign({}, e));
  // (a section read on the page keeps its own moves: a move played after them is a variation of the reader's)
  const i = list.findIndex(e => !e.rect && !!e.before === anchor.before && isPrefix(e.san, path));
  if (i >= 0) list[i].san = path; else list.push(entry(path, anchor.before));
  storeAdded(anchor.key, list);
}
function changeAdded(next, san){
  // a move the reader added, replaced by another: the variations through it now play that move
  const p = addedPath(next), path = p.san.slice(0, -1).concat([san]);
  const list = (FIX.get("added", p.key) || []).map(e => Object.assign({}, e));
  let done = false;
  const out = [];
  for (const e of list) {
    if (!!e.before === p.before && isPrefix(p.san, e.san)) {
      // a section read on the page keeps its place while it holds moves of its own
      if (e.rect && path.length > (e.first || 0)) out.push(Object.assign({}, e, {san: path}));
      else if (!done) { out.push(entry(path, p.before, e.note)); done = true; }
    } else out.push(e);
  }
  if (!done) out.push(entry(path, p.before));
  storeAdded(p.key, out);
}
function removeAdded(id){
  // the moves the reader added from node id to the end of every variation through it
  const p = addedPath(id), cut = p.san.slice(0, -1);
  const list = (FIX.get("added", p.key) || []).map(e => (!!e.before === p.before && isPrefix(p.san, e.san)) ?
    Object.assign({}, e, {san: cut}) : e);
  storeAdded(p.key, list);
}
function addedTitle(key){
  const at = nodeByKey(key), f = FIX.get("added", key) || [];
  const before = f.length ? !!f[0].before : Object.values(D.nodes).some(n => n.added === key && n.added_before);
  const read = f.length ? f.every(e => e.rect) : Object.values(D.nodes).some(n => n.added === key && n.region);
  return (read ? "The moves you read " : "Your variation ") + (before ? "before " : "after ") +
    (at ? moveText(at, true) : "a move");
}
function openAddedAt(key){
  // the Review list's item: the first move the reader added there, or the move it branches from
  const id = Object.keys(D.nodes).find(k => D.nodes[k].added === key &&
    D.nodes[D.nodes[k].parent].corrected !== "added");
  if (id) { openAdded(id); return; }
  const at = nodeByKey(key);
  if (!at) return;
  selectNode(at, {scrollPage: false});
  RV.edit = {kind: "addedkey", key};
  const f = FIX.get("added", key) || [];
  let h = "<div class=fh><h3>" + esc(addedTitle(key)) + "</h3></div>";
  h += "<p class='small muted'>" + (f.length ? (f.every(e => e.rect) ? "You read <span class=n>" : "You added <span class=n>") +
    esc(f.map(e => e.san.join(" ")).join("; ")) + "</span> here " + (f.every(e => e.rect) ? "on the page. " : "on the board. ") +
    esc(D.nodes[at].added_stale || applyWords()) :
    "You removed your variation. " + esc(applyWords())) + "</p>";
  h += "<p class='fixmsg small' id=fixmsg role=status></p>";
  if (f.length) h += "<div class=fixacts><button class=tb id=fixundo>Remove this variation</button></div>";
  showFix(h, "addedkey");
  if ($("fixundo")) $("fixundo").addEventListener("click", () => {
    FIX.set("added", key, null); afterFix(); openAddedAt(key);
    setMsg("Your variation is removed. " + applyWords(), "good");
  });
}
function openAdded(id){
  const n = D.nodes[id];
  if (!n) return;
  // a move read from a section of the page: the sheet of that section
  if (n.region && openRegionNode(id)) return;
  if (S.node !== id) selectNode(id, {scrollPage: false});
  RV.edit = {kind: "added", node: id};
  const top = addedTop(id), at = nodeByKey(n.added);
  let moves = [], cur = top;
  while (cur) { moves.push(moveText(cur, cur === top || !D.nodes[cur].black)); cur = cont(cur); }
  let h = "<div class=fh><h3>Your variation</h3></div>";
  h += "<p class='small muted'>You added <span class=n>" + esc(moves.join(" ")) + "</span> on the board" +
    (at ? ", " + (n.added_before ? "before " : "after ") + "<span class=n>" + moveHtml(at, true) + "</span>" : "") +
    ". A move on the board from one of its positions goes on with it or changes it.</p>";
  h += "<p class='fixmsg small' id=fixmsg role=status></p>";
  h += "<div class=fixacts><button class=tb id=addrm>Remove this variation</button>" +
    (top !== id ? "<button class=tb id=addrmhere>Remove from <span class=n>" + esc(moveText(id, true)) +
      "</span> on</button>" : "") + "</div>";
  showFix(h, "added");
  const gone = (from, what) => {
    const par = D.nodes[from].parent;
    BM.want = {line: n.line, steps: pathOf(par)};
    removeAdded(from);
    afterFix();
    closeFix();
    if (inApp()) say(what + " " + applyWords());
    else { selectNode(par, {scrollPage: false}); say(what + " " + applyWords()); }
  };
  $("addrm").addEventListener("click", () => gone(top, "Your variation is removed."));
  if ($("addrmhere")) $("addrmhere").addEventListener("click", () =>
    gone(id, "Your variation is removed from " + moveText(id, true) + " on."));
}
function playedText(src, m){
  const f = src.fen.split(" ");
  return f[5] + (f[1] === "b" ? "…" : ".") + m[0];
}
function boardDone(src, m, steps, said){
  // the change is stored: the board shows the position after the move until the book holds it
  const at = D.nodes[src.at];
  BM.want = {line: at.line, steps: pathOf(src.at).concat(steps)};
  afterFix();
  closeFix();
  if (inApp()) preview(CJ.after(src.fen, m[1]), m[1], said);
  else preview(CJ.after(src.fen, m[1]), m[1], said + " " + applyWords());
  say(said + " " + applyWords());
}
function boardMove(src, m){
  BM.pick = null;
  // a move on the board of the diagram view: the panel shows the line's board again
  if (S.diagram) { closeDiagram(); renderBoard(); }
  // the move the thread asked for
  if (src.thread) { threadMove(m); return; }
  const at = D.nodes[src.at];
  // the move the line holds here: a step, as the arrow makes it
  const hit = at.children.find(c => D.nodes[c].uci === m[1] && decoded(D.nodes[c]));
  if (hit) { stepTo(hit); openIfFailed(hit); return; }
  // a gap in the text: the move fills it (a correction, so in reading mode only)
  const gapHere = !!src.gap && samePos(gapMoves(src.gap)[0], src.fen);
  if (gapHere && reading()) {
    BM.want = {line: at.line, steps: pathOf(src.at).concat([{san: m[0]}])};
    chooseGap(src.gap, m);
    return;
  }
  const text = playedText(src, m);
  // the end of a variation the reader added: it goes on
  if (at.corrected === "added" && !at.children.length) {
    addVariation(anchorOf(src.at), m[0]);
    boardDone(src, m, [{san: m[0]}], "Your variation goes on with " + text + ".");
    return;
  }
  const next = cont(src.at) ? D.nodes[cont(src.at)] : null;
  const opts = [];
  if (next && next.parent != null) {
    const what = next.main ? "Correct the main line" : "Correct this variation";
    const instead = ": <span class=n>" + esc(text) + "</span> instead of <span class=n>" + esc(moveText(next.id, true)) + "</span>";
    if (next.corrected === "added")
      opts.push(["bmvar", what + instead, () => { changeAdded(next.id, m[0]);
        boardDone(src, m, [{san: m[0]}], "Your variation now plays " + text + " instead of " + moveText(next.id, true) + "."); }]);
    else if (next.key && (next.main || !at.main))
      opts.push([next.main ? "bmmain" : "bmvar", what + instead, () => { FIX.set("moves", next.key, {san: m[0]});
        boardDone(src, m, [{key: next.key}], (next.main ? "The main line" : "The variation") + " now plays " + text +
          " instead of " + moveText(next.id, true) + ". The program reads the rest of the line from this move."); }]);
    else if (next.gap && next.san && next.main) {
      // a move the reader gave for a gap: the moves given are changed from it on
      const g = gapInfo(next.gap), k = g.filled.indexOf(next.id);
      opts.push(["bmmain", what + instead, () => {
        FIX.set("gaps", next.gap, {san: g.filled.slice(0, k).map(x => D.nodes[x].san).concat([m[0]])});
        boardDone(src, m, [{san: m[0]}], "The main line now plays " + text + " instead of " + moveText(next.id, true) + "."); }]);
    }
  }
  // correcting the book's line is a tool of reading mode: outside it a move on the board only adds
  // a variation, and the chooser says where the corrections are
  const fixable = gapHere || opts.length > 0;
  if (!reading()) opts.length = 0;
  const anchor = anchorOf(src.at);
  if (anchor) opts.push(["bmadd", "Add a new variation", () => { addVariation(anchor, m[0]);
    boardDone(src, m, [{san: m[0]}], "You added " + text + " as a new variation."); }]);
  let h = "<div class=fh><h3>Your move <span class=n>" + esc(text) + "</span></h3></div>";
  h += "<p class='small muted'>" + (next ? (next.main ? "The book's line plays" : "The variation plays") +
    " <span class=n>" + esc(moveText(next.id, true)) + "</span> here." : "The line ends here.") +
    (opts.length ? " Choose what your move does." : " The program has no printed move here to keep your move with.") +
    (fixable && !reading() ? " Show reading (the two squares under the board) offers to correct the book's line with it." : "") + "</p>";
  h += "<div class=boardacts>" + opts.map(o => "<button class=tb id=" + o[0] + ">" + o[1] + "</button>").join("") +
    "<button class=tb id=bmcancel>Cancel</button></div>";
  h += "<p class='fixmsg small' id=fixmsg role=status></p>";
  RV.edit = {kind: "boardmove"};
  showFix(h, "boardmove", false);
  preview(CJ.after(src.fen, m[1]), m[1], "");
  for (const o of opts) $(o[0]).addEventListener("click", o[2]);
  $("bmcancel").addEventListener("click", () => closeFix());
  keepChooserInView();
}
function keepChooserInView(){
  // on a wide screen the chooser sits below the board: the panel scrolls until it shows whole
  if (SMALL.matches) return;
  const panel = $("panel"), f = $("fix").getBoundingClientRect(), p = panel.getBoundingClientRect();
  const bottom = Math.min(p.bottom, window.innerHeight);
  if (f.bottom > bottom) panel.scrollTop += Math.min(f.bottom - bottom + 16, f.top - Math.max(p.top, 0));
}
function askPromotion(src, moves){
  const white = (src.fen.split(" ")[1] || "w") === "w";
  let h = "<div class=fh><h3>Promote the pawn</h3></div>";
  h += "<div class='pieces six' id=bmpromo role=group aria-label='Pieces'>" + "QRBN".split("").map(c =>
    "<button data-piece='" + c + "'>" + pieceSvg(c, white) + "<span>" + esc(D.pieceWords[c]) + "</span></button>").join("") +
    "</div><div class=boardacts><button class=tb id=bmcancel>Cancel</button></div>";
  RV.edit = {kind: "boardmove"};
  showFix(h, "boardmove", false);
  $("bmcancel").addEventListener("click", () => closeFix());
  keepChooserInView();
  $("bmpromo").addEventListener("click", (e) => {
    const t = e.target.closest("button[data-piece]");
    if (!t) return;
    const m = moves.find(x => x[1][4] === t.dataset.piece.toLowerCase());
    closeFix();
    if (m) boardMove(src, m);
  });
}
function playFrom(src, from, to){
  const moves = targetsOf(src.fen, from).filter(m => m[1].slice(2, 4) === to);
  BM.pick = null;
  if (!moves.length) { paintBoards(); return; }
  if (moves.length > 1) {
    // (the thread asks for the piece in its own sheet)
    if (src.thread) { TH.promo = moves; threadShow(); return; }
    renderBoard(); askPromotion(src, moves); return;
  }
  boardMove(src, moves[0]);
}
function viewXY(svg, x, y){
  const r = svg.getBoundingClientRect(), H = TOP + 8 * SQ + M;
  return [(x - r.left) * BW / r.width, (y - r.top) * H / r.height];
}
function initBoardMoves(){
  for (const box of boardBoxes()) {
    box.addEventListener("pointerdown", (e) => {
      if (e.button > 0 || !e.isPrimary) return;
      const svg = e.target.closest("svg.board");
      const src = svg && boardSvgOf(box) === svg ? moveSource(box) : null;
      const sq = src ? squareAt(svg, e.clientX, e.clientY) : null;
      if (!sq) return;
      const own = ownPiece(src.fen, sq);
      const picked = BM.pick && BM.pick.sig === srcSig(src) ? BM.pick.sq : null;
      if (!own && !picked) return;
      BM.down = {box, svg, src, sq, own, was: picked === sq, x: e.clientX, y: e.clientY, id: e.pointerId, ghost: null};
      if (own) {
        BM.pick = {sq, sig: srcSig(src)};
        paintBoards();
        try { svg.setPointerCapture(e.pointerId); } catch (err) { /* the pointer is gone */ }
        e.preventDefault();
      }
    });
    box.addEventListener("pointermove", (e) => {
      const d = BM.down;
      if (!d || d.box !== box || e.pointerId !== d.id || !d.own) return;
      if (!d.ghost) {
        if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 6) return;
        const piece = d.svg.querySelector("use[data-at='" + d.sq + "']");
        if (!piece) return;
        d.ghost = piece.cloneNode(true);
        d.ghost.removeAttribute("data-at");
        d.ghost.setAttribute("class", "bmx ghost");
        d.ghost.setAttribute("pointer-events", "none");
        piece.classList.add("lifted");
        d.svg.appendChild(d.ghost);
      }
      const [x, y] = viewXY(d.svg, e.clientX, e.clientY);
      d.ghost.setAttribute("transform", "translate(" + (x - SQ / 2) + "," + (y - SQ / 2) + ")");
      e.preventDefault();
    });
    const up = (e, cancel) => {
      const d = BM.down;
      if (!d || d.box !== box || e.pointerId !== d.id) return;
      BM.down = null;
      const dragged = !!d.ghost;
      if (d.ghost) { d.ghost.remove(); const p = d.svg.querySelector("use.lifted"); if (p) p.classList.remove("lifted"); }
      if (cancel) { paintBoards(); return; }
      const sq = squareAt(d.svg, e.clientX, e.clientY);
      if (d.own && dragged) {
        // a drop on a square the piece can reach plays the move; any other drop puts it back
        if (sq && sq !== d.sq && targetsOf(d.src.fen, d.sq).some(m => m[1].slice(2, 4) === sq)) playFrom(d.src, d.sq, sq);
        else { if (sq !== d.sq) BM.pick = null; paintBoards(); }
      } else if (d.own) {
        if (d.was) BM.pick = null;
        paintBoards();
      } else if (sq === d.sq && targetsOf(d.src.fen, BM.pick.sq).some(m => m[1].slice(2, 4) === sq)) {
        playFrom(d.src, BM.pick.sq, sq);
      } else { BM.pick = null; paintBoards(); }
    };
    box.addEventListener("pointerup", (e) => up(e, false));
    box.addEventListener("pointercancel", (e) => up(e, true));
    // a touch on a piece that can move moves it, and does not scroll the page
    box.addEventListener("touchstart", (e) => {
      if (e.touches.length !== 1) return;
      const svg = e.target.closest && e.target.closest("svg.board");
      const src = svg && boardSvgOf(box) === svg ? moveSource(box) : null;
      const t = e.touches[0], sq = src ? squareAt(svg, t.clientX, t.clientY) : null;
      if (sq && ownPiece(src.fen, sq)) e.preventDefault();
    }, {passive: false});
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && BM.pick) { BM.pick = null; paintBoards(); } });
}

function initReview(){
  $("reviewbtn").addEventListener("click", () => setReview(!RV.on));
  initPencil();
  initBoardMoves();
  initRegion();
  // corrections stored in this browser that the book does not hold yet (made
  // while the worker was busy elsewhere, or that never reached it) are applied
  // now, without reading the book again
  if (inApp() && FIX.anyPending()) liveApply();
  $("revlist").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-item]");
    if (b) openItem(parseInt(b.dataset.item, 10));
  });
  $("symmenu").addEventListener("click", (e) => {
    const t = e.target.closest("button[data-piece]");
    if (!t) return;
    const sym = $("symmenu").dataset.sym;
    say(chooseSymbol(sym, t.dataset.piece));
    closeSymMenu();
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#symmenu") && !e.target.closest(".eye")) closeSymMenu();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSymMenu(); });
  window.addEventListener("scroll", closeSymMenu, {passive: true});
  window.addEventListener("resize", placeSheet);
}
"""
