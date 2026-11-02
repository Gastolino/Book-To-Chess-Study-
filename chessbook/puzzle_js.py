"""Puzzle books in the chapter reader.

PUZZLE_CSS and PUZZLE_JS are joined into the chapter page by
chessbook/reader.py, beside the board, the move tree and the board moves
they talk to (boardFor, moveSource, boardMove, hidden, hideRefresh,
judgeMove of review_js.py).

The data come from assemble.puzzle_index through reader.chapter_data:
D.puzzles (the chapter's puzzles, each with its solution: a line, a
sentence or none), D.puzzleBook (whether the book is likely a puzzle book)
and D.solNodes (the moves of the solution lines in the chapter, each with
its puzzle's diagram).

Puzzle mode, once the reader turns it on (or answers the question the
reader asks of a likely puzzle book), keeps the solution of every puzzle
whose answer the reader has not checked hidden, with the cover of Hide next
moves (hidden(), in the move list and on the page). A tap on a puzzle's
diagram opens the puzzle in the diagram panel under the board: the reader
plays an answer on the board, for both sides, notes it, and later checks
it against the book's solution (by the line's moves, as Hide next moves
judges a move: judgeMove), or, for a solution in words or none, marks it
right or wrong. The answers are kept in this browser's storage under
"chessbook-puzzles:<pdf>:<page count>" (the contents page reads the same
key for the tally of the whole book):

    {"mode": "puzzles" | "book" | null,
     "answers": {<diagram id>: {"moves": [[san, uci]], "tries", "noted" (ISO time), "side",
                               "check": null | "right" | "alt" | "wrong" | "own-right" | "own-wrong"}}}
"""

PUZZLE_CSS = r"""
#bpuzzle[aria-pressed="true"],#mpuzzle[aria-pressed="true"],#pzbtn[aria-pressed="true"]{color:var(--accent)}
#bpuzzle[hidden],#mpuzzle[hidden],#pzbtn[hidden]{display:none}
body.puzzling .mark.hid{background:var(--page);outline:1px dotted var(--muted);cursor:pointer}
body.puzzling .mark.hid::after,body.puzzling .eye.hid{display:none}
.notes .pzask{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 16px}
.notes .pzask .tb{color:var(--accent)}
.pzp{display:grid;gap:8px}
.pzp .pzmoves{font-family:"Geist Mono",ui-monospace,Menlo,Consolas,monospace;font-variant-ligatures:none;
font-weight:500;overflow-wrap:anywhere}
.pzp .pzside{display:flex;flex-wrap:wrap;gap:4px 16px}
.pzp .pzside .tb[aria-checked="true"]{color:var(--accent);text-decoration:underline}
.pzp .boardacts{display:flex;flex-wrap:wrap;gap:6px 16px}
.pzres{display:grid;gap:6px}
.pzres:empty{display:none}
.pzst{white-space:nowrap}
.pzst .dot,.pzdot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;
vertical-align:1px;border:1.5px solid var(--muted);background:none;box-sizing:border-box}
.pzdot.ok{border-color:var(--ok)}
.pzdot.alt{border-color:var(--doubt)}
.pzdot.fail{border-color:var(--fail)}
.pzdot.none{border-style:dotted}
#pzsec[hidden]{display:none}
/* (on a phone the top bar has no room for the words: the puzzle's panel offers them) */
@media (max-width:700px){.tools #pzbtn{display:none}}
@media (max-width:360px){#mpuzzle{display:none}}
.puzzlesopen .lsec,.puzzlesopen .treesec,.puzzlesopen #infosec{display:none}
.pzrows{list-style:none;margin:8px 0 0;padding:0}
.pzrows li{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:baseline;gap:4px 12px;
padding:6px 0;border-top:1px solid var(--line)}
.pzrows li:last-child{border-bottom:1px solid var(--line)}
.pzrows .pp{color:var(--muted)}
.pzrows .tb{text-align:left}
.pzsum{display:grid;gap:6px}
.pzsum .acts{display:flex;flex-wrap:wrap;gap:4px 16px}
"""

PUZZLE_JS = r"""
/* ---------------------------------------------------------------- puzzles */
// the reader's answers to the book's puzzles, in this browser's storage (see chessbook/puzzle_js.py)
const PZKEY = "chessbook-puzzles:" + D.book.pdf + ":" + D.pageCount;
// on: puzzle mode; id: the puzzle open (its diagram); moves: the answer played on the board, [san, uci];
// start and fen: the puzzle's position and the board's now; uci: the last move played; items: the
// puzzles by diagram; lineOf: the puzzle of each solution line here; sides: the side to move the reader
// chose where the book does not say; res: what the panel says of the answer; solution: the book's
// solution listed in the panel
const PZ = {on: false, id: null, moves: [], start: null, fen: null, uci: null, items: {}, lineOf: {}, sides: {},
  res: "", solution: false, store: {mode: null, answers: {}}};
const PZ_WORDS = {right: "Matches", alt: "Side line", wrong: "Differs", "own-right": "Matches", "own-wrong": "Differs"};
const PZ_DOTS = {right: "ok", alt: "alt", wrong: "fail", "own-right": "ok", "own-wrong": "fail"};
function pzRead(){
  let v = null;
  try { v = JSON.parse(localStorage.getItem(PZKEY) || "null"); } catch (e) { v = null; }
  if (!v || typeof v !== "object") v = {};
  return {mode: v.mode === "puzzles" || v.mode === "book" ? v.mode : null,
    answers: v.answers && typeof v.answers === "object" ? v.answers : {}};
}
function pzWrite(){
  try { localStorage.setItem(PZKEY, JSON.stringify(PZ.store)); } catch (e) { /* no storage */ }
}
function pzIndex(){
  PZ.items = {}; PZ.lineOf = {};
  for (const it of D.puzzles || []) {
    PZ.items[it.diagram] = it;
    const s = it.solution;
    if (s && s.line && D.lines[s.line]) PZ.lineOf[s.line] = it.diagram;
  }
}
function pzHere(){ return (D.puzzles || []).filter(it => it.here); }
function pzAnswer(did){
  const a = PZ.store.answers[did];
  return a && typeof a === "object" && Array.isArray(a.moves) ? a : null;
}
function pzChecked(did){ const a = pzAnswer(did); return !!(a && a.check); }
// a move of a puzzle's solution while puzzle mode is on and the reader has not checked an answer
// (hidden() covers it, as Hide next moves covers the next moves)
function pzHidden(id){
  if (!PZ.on) return false;
  const did = (D.solNodes || {})[id];
  return !!did && !pzChecked(did);
}
function pzHiddenRoot(id){
  const n = D.nodes[id];
  if (!PZ.on || !n || n.parent != null) return null;
  const did = PZ.lineOf[n.line];
  return did && !pzChecked(did) ? did : null;
}
// selectNode asks first: a hidden solution is not chosen (the puzzle opens instead, when it is here)
function pzBlocks(id){
  const did = pzHidden(id) ? D.solNodes[id] : pzHiddenRoot(id);
  if (!did) return false;
  puzzleHiddenClick(did);
  return true;
}
function puzzleHiddenClick(did){
  const it = PZ.items[did];
  const name = it ? "puzzle " + it.label : "a puzzle";
  if (it && it.here) puzzleOpen(did);
  say("These moves are the book's solution to " + name + ". They stay hidden until you check your answer.");
}
function pzName(it){ return "Puzzle " + it.label; }
function withTurn(fen, side){
  const p = fen.split(" ");
  if (p[1] === side) return fen;
  p[1] = side; if (p.length > 3) p[3] = "-";
  return p.join(" ");
}
// the side to move is known: printed with the diagram, or given by the numbers of the solution line
function pzSideKnown(it){ return it.side === "w" || it.side === "b" || !!(it.solution && it.solution.line && it.start_fen); }
function pzStart(it){
  const d = diagramInfo(it.diagram)[1];
  let f = (it.solution && it.solution.line && it.start_fen) || (d && d.fen) || it.start_fen || null;
  if (!f) return null;
  if (it.side === "w" || it.side === "b") return it.solution && it.solution.line ? f : withTurn(f, it.side);
  const a = pzAnswer(it.diagram);
  const chosen = PZ.sides[it.diagram] || (a && a.side) || null;
  return chosen && !pzSideKnown(it) ? withTurn(f, chosen) : f;
}
// "1.Rd8+ Kh7 2.Rd7" (or "1...Kh7 2.Rd7") from the position fen
function pzLine(fen, moves){
  const p = String(fen || "- w - - 0 1").split(" ");
  let black = p[1] === "b", num = parseInt(p[5], 10) || 1;
  const out = [];
  moves.forEach((m, i) => {
    out.push(!black ? num + "." + m[0] : i === 0 ? num + "..." + m[0] : m[0]);
    if (black) num++;
    black = !black;
  });
  return out.join(" ");
}
function pzSan(s){ return String(s || "").replace(/[+#!?]+$/, ""); }
function pzSame(a, b){ return !!a && !!b && (a[1] && b[1] ? a[1] === b[1] : pzSan(a[0]) === pzSan(b[0])); }
function pzStatus(it){
  const a = pzAnswer(it.diagram);
  if (!a) return it.solution ? ["none", "Not tried"] : ["none", "No solution"];
  if (!a.check) return ["", "Noted"];
  return [PZ_DOTS[a.check] || "", PZ_WORDS[a.check] || "Noted"];
}
function pzStatusHtml(it){
  const [k, w] = pzStatus(it);
  return "<span class='pzst small'><i class='pzdot " + k + "'></i>" + esc(w) + "</span>";
}

/* the puzzle open in the panel under the board */
function puzzleOpen(did){
  const it = PZ.items[did];
  if (!it) return;
  if (RV.edit) closeFix();
  if (S.diagram) closeDiagram();
  if (TH.on) threadEnd();
  if (PZ.id !== did) { PZ.res = ""; PZ.solution = false; }
  PZ.id = did;
  PZ.start = pzStart(it); PZ.fen = PZ.start; PZ.moves = []; PZ.uci = null;
  S.preview = null; BM.pick = null;
  if (it.page !== S.page && (it.page in D.pages)) showPage(it.page);
  for (const el of document.querySelectorAll(".diag.current")) el.classList.remove("current");
  const el = document.querySelector(".diag[data-diagram='" + did + "']");
  if (el) el.classList.add("current");
  renderBoard();
  puzzleShow();
  layoutPanel(false);
  setState();
}
function puzzleClose(quiet){
  if (!PZ.id) return;
  PZ.id = null; PZ.moves = []; PZ.fen = PZ.start = PZ.uci = null; PZ.res = ""; PZ.solution = false;
  $("dpanel").hidden = true; $("dpanel").innerHTML = ""; $("dpanel").classList.remove("pzp");
  for (const el of document.querySelectorAll(".diag.current")) el.classList.remove("current");
  if (!quiet) { renderBoard(); layoutPanel(false); setState(); }
}
function pzBoardNote(){
  if (!PZ.fen) return "The program could not read this position.";
  const side = PZ.fen.split(" ")[1] === "b" ? "Black" : "White";
  return PZ.moves.length ? side + " to play." : "";
}
function puzzleShow(){
  const it = PZ.items[PZ.id];
  if (!it) return;
  const box = $("dpanel"), a = pzAnswer(it.diagram);
  let h = "<div class=dhead><h3>" + esc(pzName(it) + ", " + pageName(it.page)) + "</h3><button class=tb id=pzclose>Close</button></div>";
  if (!PZ.start) {
    h += "<p class='small muted'>The program could not read this position.</p>" +
      "<p class=small><button class=tb id=pzfix>Correct the position</button></p>";
  } else {
    const side = PZ.start.split(" ")[1] === "b" ? "b" : "w";
    if (pzSideKnown(it)) h += "<p>" + (side === "b" ? "Black" : "White") + " to play.</p>";
    else {
      const opt = (v, t) => "<button class=tb role=radio data-pzside=" + v + " aria-checked='" + String(side === v) + "'>" + t + "</button>";
      h += "<p class=pzside role=radiogroup aria-label='The side to move'>" + opt("w", "White to play") + opt("b", "Black to play") + "</p>";
    }
    h += "<p class='small muted'>Play your answer on the board, for both sides, then note it.</p>";
    h += "<p class=pzmoves>" + (PZ.moves.length ? esc(pzLine(PZ.start, PZ.moves)) : "<span class=muted>No moves yet</span>") + "</p>";
    if (a) h += "<p class=small>Your noted answer: <span class=n>" + esc(pzLine(pzFenOf(it, a), a.moves)) + "</span> " + pzStatusHtml(it) + "</p>";
    h += "<div class=boardacts><button class=tb id=pznote" + (PZ.moves.length ? "" : " aria-disabled=true") + ">Note this answer</button>" +
      "<button class=tb id=pzagain>Start again</button>" + (a ? "<button class=tb id=pzcheck>Check my answer</button>" : "") +
      "<button class=tb id=pzmine>My answers</button></div>";
    if (reading()) h += "<p class='small rtool'><button class=tb id=pzfix>Correct the position</button></p>";
  }
  h += "<div class='pzres small' id=pzres role=status>" + PZ.res + pzSolutionHtml(it) + "</div>";
  box.innerHTML = h;
  box.classList.add("pzp");
  box.hidden = false;
  $("pzclose").addEventListener("click", () => puzzleClose());
  if ($("pzfix")) $("pzfix").addEventListener("click", () => { const did = it.diagram; puzzleClose(true); openDiagramFix(did); });
  if ($("pznote")) $("pznote").addEventListener("click", puzzleNote);
  if ($("pzagain")) $("pzagain").addEventListener("click", puzzleRestart);
  if ($("pzcheck")) $("pzcheck").addEventListener("click", () => puzzleCheck(it.diagram));
  if ($("pzmine")) $("pzmine").addEventListener("click", () => setAnswers(true));
  for (const b of box.querySelectorAll("[data-pzside]")) b.addEventListener("click", () => {
    PZ.sides[it.diagram] = b.dataset.pzside;
    PZ.start = PZ.fen = pzStart(it); PZ.moves = []; PZ.uci = null;
    renderBoard(); puzzleShow();
  });
  for (const b of box.querySelectorAll("[data-pzown]")) b.addEventListener("click", () => pzOwn(it.diagram, b.dataset.pzown === "1"));
  if ($("pzsol")) $("pzsol").addEventListener("click", () => puzzleSolution(it.diagram));
  for (const l of box.querySelectorAll("a[data-page]")) l.addEventListener("click", (e) => { e.preventDefault(); goPage(l.dataset.page); });
}
// the position an answer starts from: the one it was noted in
function pzFenOf(it, a){
  const f = pzStart(it);
  return f && a && a.side && !pzSideKnown(it) ? withTurn(f, a.side) : f;
}
// the book's solution in the panel, after a check (Show the solution, for a line in another chapter)
function pzSolutionHtml(it){
  if (!PZ.solution || !pzChecked(it.diagram)) return "";
  const s = it.solution;
  if (!s) return "";
  const at = "<a href='#page=" + s.page + "' data-page='" + s.page + "'>" + esc(pageName(s.page)) + "</a>";
  if (s.note) return "<p>The book's solution, on " + at + ": " + esc(s.note) + "</p>";
  return "<p>The book's solution, on " + at + ": <span class=n>" + esc(pzLine(it.start_fen, s.main)) + "</span></p>";
}
function puzzleMove(m){
  if (!PZ.id || !PZ.fen) return;
  PZ.moves.push([m[0], m[1]]);
  PZ.fen = CJ.after(PZ.fen, m[1]);
  PZ.uci = m[1];
  BM.pick = null;
  renderBoard();
  puzzleShow();
  setState();
}
function puzzleStep(dir){
  // the left arrow takes back the last move of the answer; Home starts it again
  if (dir < 0 && PZ.moves.length) {
    PZ.moves.pop();
    PZ.fen = PZ.start;
    for (const m of PZ.moves) PZ.fen = CJ.after(PZ.fen, m[1]);
    PZ.uci = PZ.moves.length ? PZ.moves[PZ.moves.length - 1][1] : null;
    renderBoard(); puzzleShow(); setState();
  }
}
function puzzleRestart(){
  PZ.moves = []; PZ.fen = PZ.start; PZ.uci = null; BM.pick = null;
  renderBoard(); puzzleShow(); setState();
}
function puzzleNote(){
  const it = PZ.items[PZ.id];
  if (!it || !PZ.moves.length) return;
  const prev = pzAnswer(it.diagram);
  PZ.store.answers[it.diagram] = {moves: PZ.moves.map(m => [m[0], m[1]]), tries: ((prev && prev.tries) || 0) + 1,
    noted: new Date().toISOString(), check: null, side: PZ.start.split(" ")[1] || "w"};
  pzWrite();
  PZ.solution = false;
  PZ.res = "<p>" + esc("Your answer " + pzLine(PZ.start, PZ.moves) + " is noted. The book's solution stays hidden.") + "</p>";
  hideRefresh();
  puzzleShow();
  pzRefresh();
}
// the reader's answer against the book's solution line: by the moves of the line here, as Hide next
// moves judges a move on the board (judgeMove), else by the moves the puzzle's data gives
function pzMatch(it, moves){
  const s = it.solution, L = s && s.line ? D.lines[s.line] : null;
  if (L && D.nodes[L.root] && moves.length) {
    let at = L.root, k = 0, first = null;
    for (const m of moves) {
      const j = judgeMove(at, m[1]);
      if (first === null) first = j.verdict;
      if (j.verdict !== "book") break;
      k++; at = j.hit;
    }
    if (first === "book" || first === "variation" || first === "wrong") return {first, k};
  }
  let k = 0;
  while (k < moves.length && k < s.main.length && pzSame(moves[k], s.main[k])) k++;
  const first = k > 0 ? "book" : !s.main.length ? "unread" : (s.alts || []).some(x => pzSame(moves[0], x)) ? "variation" : "wrong";
  return {first, k};
}
// the check of one answer: {check, words} (check null: the reader marks it, words then ask)
function pzJudge(it){
  const a = pzAnswer(it.diagram), s = it.solution;
  if (!a) return null;
  if (!s) return {check: null, words: "The program found no solution for this puzzle in the book."};
  if (s.note) return {check: null, words: "The book's solution, on " + pageName(s.page) + ": " + s.note};
  const fen = pzFenOf(it, a), j = pzMatch(it, a.moves);
  const mine = pzLine(fen, a.moves.slice(0, 1)), book = s.main.length ? pzLine(it.start_fen || fen, s.main.slice(0, 1)) : "";
  if (j.first === "book")
    return {check: "right", words: "Your first move matches the book." + (j.k > 1 ? " The first " + j.k + " moves match." : "")};
  if (j.first === "variation") return {check: "alt", words: "The book gives " + mine + " as a side line and plays " + book + "."};
  if (j.first === "wrong") return {check: "wrong", words: "The book plays " + book + ". You noted " + mine + "."};
  return {check: null, words: "The program could not read the book's solution on " + pageName(s.page) + "."};
}
function puzzleCheck(did){
  const it = PZ.items[did], j = it ? pzJudge(it) : null;
  if (!j) return;
  if (j.check) {
    pzAnswer(did).check = j.check;
    pzWrite();
    PZ.res = "<p>" + esc(j.words) + " " + pzStatusHtml(it) + "</p>" + pzShowHtml(it);
  } else {
    PZ.res = "<p>" + esc(j.words) + "</p><p>Was your answer right?</p><div class=boardacts>" +
      "<button class=tb data-pzown=1>Yes</button><button class=tb data-pzown=0>No</button></div>";
  }
  PZ.solution = false;
  hideRefresh();
  if (PZ.id === did) puzzleShow();
  pzRefresh();
}
function pzShowHtml(it){ return it.solution ? "<p><button class=tb id=pzsol>Show the solution</button></p>" : ""; }
function pzOwn(did, right){
  const it = PZ.items[did], a = pzAnswer(did);
  if (!it || !a) return;
  a.check = right ? "own-right" : "own-wrong";
  pzWrite();
  PZ.res = "<p>" + esc(right ? "You marked your answer right." : "You marked your answer wrong.") + " " + pzStatusHtml(it) + "</p>";
  hideRefresh();
  if (PZ.id === did) puzzleShow();
  pzRefresh();
}
function puzzleSolution(did){
  const it = PZ.items[did], s = it && it.solution;
  if (!s) return;
  const L = s.line ? D.lines[s.line] : null;
  if (L) { puzzleClose(true); selectNode(L.root, {at: null, page: L.page, scrollPage: true}); return; }
  PZ.solution = true;
  puzzleShow();
}

/* the mode, the question to a likely puzzle book, and the list of answers */
function setPuzzles(on, quiet){
  PZ.on = on;
  document.body.classList.toggle("puzzling", on);
  for (const b of [$("bpuzzle"), $("mpuzzle")]) {
    if (!b) continue;
    b.setAttribute("aria-pressed", String(on));
    const t = on ? "Puzzles: on. A tap turns puzzle mode off" : "Puzzles: work the book's puzzles on the board";
    b.title = t; b.setAttribute("aria-label", t);
  }
  if (!on) { puzzleClose(true); setAnswers(false); }
  // (a solution move that puzzle mode now hides is chosen no longer)
  if (on && S.node && (pzHidden(S.node) || pzHiddenRoot(S.node))) {
    S.node = null; S.at = null;
    renderTree(); renderBoard(); renderInfo(); setState();
  }
  hideRefresh();
  pzRefresh();
  if (!quiet) say(on ? "Puzzle mode is on. A tap on a puzzle's diagram opens it, and the book's solutions stay hidden until you check your answers." :
    "Puzzle mode is off. The program keeps your answers.");
}
function pzMode(mode){
  PZ.store.mode = mode;
  pzWrite();
  setPuzzles(mode === "puzzles");
}
function pzAsk(){
  const el = $("pzask");
  if (!el) return;
  const B = D.puzzleBook || {}, R = B.reasons || {};
  if (!B.likely || PZ.store.mode !== null) { el.innerHTML = ""; return; }
  const sent = R.tied >= R.puzzles / 2 ?
    "In this book " + R.tied + " of " + R.boards + " diagrams have their solutions on later pages." :
    "In this book " + R.puzzles + " of " + R.boards + " diagrams are positions that no line plays from on their page.";
  el.innerHTML = "<span>" + esc(sent + " Do you want to work them as puzzles? The program keeps the solutions hidden and notes your answers.") +
    "</span><button class=tb id=pzyes>Work them as puzzles</button><button class=tb id=pzno>Read it as a book</button>";
  $("pzyes").addEventListener("click", () => { pzMode("puzzles"); pzAsk(); });
  $("pzno").addEventListener("click", () => { pzMode("book"); pzAsk(); });
}
function pzTally(items){
  const noted = items.filter(it => pzAnswer(it.diagram));
  const match = noted.filter(it => ["right", "own-right"].includes(pzAnswer(it.diagram).check));
  const none = items.filter(it => !it.solution);
  const n = items.length;
  let t = "You noted " + noted.length + (noted.length === 1 ? " answer" : " answers") + " for the " +
    (n === 1 ? "one puzzle" : n + " puzzles") + " in this chapter.";
  if (noted.length) t += " " + match.length + " of " + noted.length + (noted.length === 1 && match.length === 1 ? " matches" : " match") + " the book.";
  if (none.length) t += " The program found no solution for " + (none.length === 1 ? "one puzzle." : none.length + " puzzles.");
  return t;
}
function setAnswers(on){
  const sec = $("pzsec");
  if (!sec) return;
  sec.hidden = !on;
  document.body.classList.toggle("puzzlesopen", on);
  $("pzbtn").setAttribute("aria-pressed", String(on));
  if (on) { renderAnswers(); if (SMALL.matches) sec.scrollIntoView({block: "start"}); }
  layoutPanel(false);
}
function renderAnswers(){
  const sec = $("pzsec");
  if (!sec || sec.hidden) return;
  const items = pzHere();
  let h = "<div class=revhead><h2 class=ltitle>My answers</h2><button class=tb id=pzlclose>Close</button></div>";
  if (!items.length) {
    h += "<p class='small muted'>This chapter prints no puzzles. The book's solutions on its pages stay hidden until you check your answers.</p>";
  } else {
    h += "<div class='pzsum small'><p id=pztally>" + esc(pzTally(items)) + "</p>" +
      "<div class=acts><button class=tb id=pzall>Check all my answers</button></div></div><ul class='pzrows small'>";
    for (const it of items)
      h += "<li><button class=tb data-pzopen='" + esc(it.diagram) + "'>" + esc(pzName(it)) + "</button>" +
        "<a class=pp href='#page=" + it.page + "' data-page='" + it.page + "'>" + esc(pageName(it.page)) + "</a>" + pzStatusHtml(it) + "</li>";
    h += "</ul>";
  }
  sec.innerHTML = h;
  $("pzlclose").addEventListener("click", () => setAnswers(false));
  if ($("pzall")) $("pzall").addEventListener("click", checkAll);
  for (const b of sec.querySelectorAll("[data-pzopen]")) b.addEventListener("click", () => puzzleOpen(b.dataset.pzopen));
  for (const l of sec.querySelectorAll("a[data-page]")) l.addEventListener("click", (e) => { e.preventDefault(); goPage(l.dataset.page); });
}
function checkAll(){
  let k = 0;
  for (const it of pzHere()) {
    const a = pzAnswer(it.diagram);
    if (!a || !it.solution || !it.solution.line) continue;
    const j = pzJudge(it);
    if (j && j.check) { a.check = j.check; k++; }
  }
  pzWrite();
  hideRefresh();
  if (PZ.id) puzzleShow();
  pzRefresh();
  say(k ? "The program checked " + (k === 1 ? "one answer" : k + " answers") + " against the book's solutions." :
    "You have noted no answer that the program can check against a line of the book.");
}
// the buttons, the question and the list after a change
function pzRefresh(){
  const show = (D.puzzleBook && D.puzzleBook.count >= 3) || PZ.on;
  for (const b of [$("bpuzzle"), $("mpuzzle")]) if (b) b.hidden = !show;
  const pb = $("pzbtn");
  if (pb) pb.hidden = !PZ.on;
  pzAsk();
  renderAnswers();
}
// a new reading from the app: the puzzles of the chapter again
function puzzlePatched(p){
  for (const k of ["puzzles", "puzzleBook", "solNodes"]) if (p[k] !== undefined) D[k] = p[k];
  pzIndex();
  if (PZ.id && !PZ.items[PZ.id]) puzzleClose(true);
  else if (PZ.id) { const keep = PZ.moves; puzzleOpen(PZ.id); for (const m of keep) if (CJ.legalMoves(PZ.fen).some(x => x[1] === m[1])) puzzleMove(m); }
  pzRefresh();
}
function initPuzzles(){
  PZ.store = pzRead();
  pzIndex();
  for (const b of [$("bpuzzle"), $("mpuzzle")]) if (b) b.addEventListener("click", () => pzMode(PZ.on ? "book" : "puzzles"));
  $("pzbtn").addEventListener("click", () => setAnswers($("pzsec").hidden));
  // an answer noted in another page of this book (the contents page, another tab)
  window.addEventListener("storage", (e) => {
    if (e.key !== PZKEY) return;
    PZ.store = pzRead();
    if (PZ.on !== (PZ.store.mode === "puzzles")) setPuzzles(PZ.store.mode === "puzzles", true);
    hideRefresh(); pzRefresh();
    if (PZ.id) puzzleShow();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && PZ.id && !RV.edit) puzzleClose(); });
  setPuzzles(PZ.store.mode === "puzzles", true);
}
"""

# the contents page: the question, the switch and the tally of the whole book, from the same key
INDEX_PUZZLE_JS = r"""
(function(){
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const $ = (id) => document.getElementById(id);
const KEY = "chessbook-puzzles:" + D.pdf + ":" + D.pageCount;
const B = D.puzzleBook || {}, R = B.reasons || {};
function read(){
  let v = null;
  try { v = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { v = null; }
  if (!v || typeof v !== "object") v = {};
  return {mode: v.mode === "puzzles" || v.mode === "book" ? v.mode : null,
    answers: v.answers && typeof v.answers === "object" ? v.answers : {}};
}
function write(st){ try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) { /* no storage */ } }
function esc(t){ return String(t == null ? "" : t).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c])); }
function render(){
  const el = $("pzline");
  if (!el) return;
  const st = read(), items = D.puzzles || [];
  let h = "";
  if (B.likely && st.mode === null) {
    const sent = R.tied >= R.puzzles / 2 ?
      "In this book " + R.tied + " of " + R.boards + " diagrams have their solutions on later pages." :
      "In this book " + R.puzzles + " of " + R.boards + " diagrams are positions that no line plays from on their page.";
    h += "<span>" + esc(sent + " Do you want to work them as puzzles? The program keeps the solutions hidden and notes your answers.") +
      "</span> <button class=tb data-mode=puzzles>Work them as puzzles</button> <button class=tb data-mode=book>Read it as a book</button>";
  } else if (items.length >= 3 || st.mode === "puzzles") {
    const on = st.mode === "puzzles";
    h += "<button class=tb id=pztoggle aria-pressed='" + String(on) + "' data-mode='" + (on ? "book" : "puzzles") + "'>Puzzles</button> ";
    if (on) {
      // (an answer to a diagram that a new reading no longer holds stays stored, out of the tally)
      const noted = items.filter(it => st.answers[it.diagram] && Array.isArray(st.answers[it.diagram].moves));
      const match = noted.filter(it => ["right", "own-right"].includes(st.answers[it.diagram].check));
      const none = items.filter(it => !it.solution);
      let t = "You noted " + noted.length + (noted.length === 1 ? " answer" : " answers") + " for the " +
        (items.length === 1 ? "one puzzle" : items.length + " puzzles") + " in this book.";
      if (noted.length) t += " " + match.length + " of " + noted.length + (noted.length === 1 && match.length === 1 ? " matches" : " match") + " the book.";
      if (none.length) t += " The program found no solution for " + (none.length === 1 ? "one puzzle." : none.length + " puzzles.");
      h += "<span id=pztally>" + esc(t) + "</span>";
    } else h += "<span class=muted>Puzzle mode is off. A tap on Puzzles keeps the book's solutions hidden while you work its puzzles.</span>";
  }
  el.innerHTML = h;
  el.hidden = !h;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("#pzline [data-mode]");
  if (!b) return;
  const st = read();
  st.mode = b.dataset.mode;
  write(st);
  render();
});
window.addEventListener("storage", (e) => { if (e.key === KEY) render(); });
window.addEventListener("pageshow", render);
render();
})();
"""
