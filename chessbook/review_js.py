"""The Review view of the chapter reader and the reader's corrections.

CORRECTIONS_JS is the store of corrections shared by the contents page and
the chapter readers (browser storage, one entry per book). REVIEW_JS runs
inside the chapter reader's script and uses its functions: it lists the
chapter's uncertainties, and its editors correct a diagram, a move, a
sequence that found no place, or a piece symbol that the text recognition
could not name. REVIEW_CSS styles both, following DESIGN.md.
"""

CORRECTIONS_JS = r"""
function makeCorrections(applied, opts){
  // applied: the corrections the build used ({diagrams, moves, unattached, glyphs}).
  const key = "chessbook-corrections:" + opts.pdf + ":" + opts.pageCount;
  const PARTS = ["diagrams", "moves", "unattached", "glyphs", "connect", "disconnect", "gaps"];
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
.pencil .mark,.pencil .diag{outline:1px dotted color-mix(in srgb,var(--accent) 60%,transparent)}
.joining .mark[data-node]:hover{outline:1.5px solid var(--accent)}
.legend .penk{display:none}
.pencil .legend .penk{display:inline-flex}
.pencil .legend{visibility:visible}
.pencil .key .help{visibility:hidden}
.k.pen{border:1px dotted var(--accent)}
.lineacts{display:grid;gap:6px;border-top:1px solid var(--line);padding-top:8px}
.lineacts p{margin:0}
#diagpick[hidden]{display:none}
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
  else openSymbol(it.sym);
}

/* ---------------- the editor */
function fixNav(){
  if (!RV.on || RV.cur < 0) return "<div class=fixnav><button class=tb id=fixclose>Close</button></div>";
  return "<div class=fixnav><button class=tb id=fixprev" + (RV.cur <= 0 ? " disabled" : "") + ">Previous item</button>" +
    "<button class=tb id=fixnext" + (RV.cur >= RV.items.length - 1 ? " disabled" : "") + ">Next item</button>" +
    "<span class=gap></span><button class=tb id=fixclose>Close</button></div>";
}
function showFix(html, kind){
  const box = $("fix");
  box.innerHTML = "<div class=fix>" + html + fixNav() + "</div>";
  box.hidden = false;
  RV.edit = Object.assign(RV.edit || {}, {kind});
  $("panel").classList.toggle("editing-diagram", kind === "diagram");
  $("fixclose").addEventListener("click", () => closeFix());
  if ($("fixprev")) $("fixprev").addEventListener("click", () => openItem(RV.cur - 1));
  if ($("fixnext")) $("fixnext").addEventListener("click", () => openItem(RV.cur + 1));
  renderMini();
  placeSheet();
  // on a wide screen the editor sits below the board at the top of the panel
  if (!SMALL.matches) $("panel").scrollTop = 0;
}
function closeFix(){
  const box = $("fix");
  box.hidden = true; box.innerHTML = "";
  RV.edit = null;
  S.preview = null;
  $("panel").classList.remove("editing-diagram");
  for (const el of document.querySelectorAll(".mark.seqcur")) el.classList.remove("seqcur");
  placeSheet();
  renderBoard();
}
function placeSheet(){
  // on a phone the editor sits above the bar at the foot of the window
  const box = $("fix"), bar = $("mbar");
  if (SMALL.matches && !box.hidden) {
    box.style.bottom = bar.offsetHeight + "px";
    // leave room above the editor for the page, so that the item stays in view
    box.style.maxHeight = Math.max(220, window.innerHeight - bar.offsetHeight - 200) + "px";
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
  S.node = null;
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
    if (t) attachTo(key, t.dataset.to);
  });
  $("fixdismiss").addEventListener("click", () => {
    FIX.set("unattached", key, {attach_to: "dismiss"}); afterFix();
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
  setMsg("You placed the moves as a variation of " + moveText(id, true) + ". The board shows the position " +
    "before that move. " + applyWords() + " The program places them there when they are legal.", "good");
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
    const [p, , m] = pick;
    if (m.node) selectNode(m.node, {scrollPage: false});
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
    const fixed = !!(m.corrected || (n && n.corrected) || (n && n.key && (FIX.get("moves", n.key) ||
      FIX.get("connect", n.key) || FIX.get("disconnect", n.key) || FIX.get("gaps", n.key))) ||
      (m.seq && (FIX.get("unattached", m.seq) || FIX.get("connect", m.seq))));
    el.classList.toggle("fixed", fixed);
  }
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
}
/* ---------------- the pencil: correct anything on the page, and join or split lines */
const PEN = {on: false, connect: null};
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
  afterFix();
  const said = "You joined " + c.label + " to the line after " + moveText(target, true) + ". " + applyWords();
  say(said); setMsg(said, "good");
}
function setPencil(on){
  PEN.on = on;
  if (!on) stopConnect();
  document.body.classList.toggle("pencil", on);
  for (const b of [$("penbtn"), $("mpen")]) if (b) b.setAttribute("aria-pressed", String(on));
  say(on ? "Pencil on: a tap on a move, a diagram or a sequence on the page opens its correction. " +
    "A second tap on the pencil ends it." : "");
  if (!on && RV.edit && !RV.on) closeFix();
}
function penClick(b){
  // the pencil's tap on the page: true when it handled the tap
  if (PEN.connect && b.dataset.node) { finishConnect(b.dataset.node); return true; }
  if (!PEN.on || b.dataset.eye) return false;
  if (b.dataset.node) { const id = b.dataset.node; selectNode(id, {fromPage: true}); openMove(id); return true; }
  if (b.dataset.seq) { openSeq(b.dataset.seq); return true; }
  if (b.dataset.diagram) { openDiagramFix(b.dataset.diagram); return true; }
  return false;
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
  // a renamed move wins: a new reading may give the same id to another move
  const ren = p.renamed || {};
  if (S.node && (ren[S.node] || !D.nodes[S.node])) S.node = ren[S.node] || null;
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
  const pgn = $("pgnbtn");
  if (pgn) pgn.disabled = !D.pgn;
  if (S.node) history.replaceState(null, "", "#node=" + S.node);
  setState();
  // a new reading speaks only in reading mode; the top bar already says how far the app has come
  if (!reread || reading()) say(p.progress || "Your correction is applied.");
  else say("");
  // corrections stored in this browser that the new reading does not hold yet
  if (reread && inApp() && FIX.anyPending()) liveApply();
}
window.applyPatch = applyPatch;
function initPencil(){
  for (const b of [$("penbtn"), $("mpen")]) if (b) b.addEventListener("click", () => setPencil(!PEN.on));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && PEN.connect) { stopConnect(); say(""); } });
  window.addEventListener("message", (e) => {
    if (e.source !== window.parent || e.source === window) return;
    const m = e.data || {};
    if (m.patch) applyPatch(m.patch);
    else if (m.progress) say(m.progress);
    else if (m.failed) say(m.failed);
  });
}

function initReview(){
  $("reviewbtn").addEventListener("click", () => setReview(!RV.on));
  initPencil();
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
