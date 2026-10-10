"""Reading a section of the page that the program missed, in the chapter reader.

The reader marks a section of a page where the book prints moves that the
program found in no line: with the "Read a section" button (a dashed
rectangle) it drags a rectangle across them, or taps a word; with the pencil
on, a tap on the page where no move or diagram box stands does the same. The
rectangle stays on the page in PDF points, so that it keeps its place when
the page is enlarged; its corners change its size and a drag inside it moves
it. A sheet (the correction sheet, #fix) then says what the program reads
there (the browser app's worker reads the text layer with the book's own
decoder, web/driver.py read_region), offers its readings, and takes the
moves typed in standard notation, checked move by move as they are typed.
The moves go after the chosen move or before it (as alternatives to it),
and continue the main line when the chosen move ends it, or form a
variation. They are stored as an "added" correction with the section
(corrections.py), which the app applies at once; the reader opened from a
file shows them until the next run of the program writes them into the book.

REGION_JS runs inside the chapter reader's script, after REVIEW_JS, and uses
the functions of both (showFix, closeFix, preview, matchSan, sanKey, FIX,
storeAdded, addedPath, anchorOf, selectNode, pct ...). REGION_CSS styles the
rectangle and the button, following DESIGN.md: an accent outline with no
fill, square handles, no shadow.
"""

REGION_CSS = r"""
#regionbtn[aria-pressed="true"],#mregion[aria-pressed="true"]{color:var(--accent)}
/* the button is a correction tool (class rtool), which the chapter's own style shows in reading
   mode only */
.rgdraw .pagebox{cursor:crosshair;touch-action:none}
.rgsel{position:absolute;z-index:7;outline:1.5px solid var(--accent);outline-offset:0;background:none;
cursor:move;touch-action:none}
/* the handles stand just outside the corners, and take a finger's width outside them, so that a
   section as small as one word stays readable and still moves by a drag inside it */
.rgh{position:absolute;width:9px;height:9px;border:1px solid var(--accent);background:none;touch-action:none}
.rgh::before{content:"";position:absolute;width:28px;height:28px}
.rgh.nw{right:100%;bottom:100%;margin:0 -1px -1px 0;cursor:nwse-resize}
.rgh.ne{left:100%;bottom:100%;margin:0 0 -1px -1px;cursor:nesw-resize}
.rgh.sw{right:100%;top:100%;margin:-1px -1px 0 0;cursor:nesw-resize}
.rgh.se{left:100%;top:100%;margin:-1px 0 0 -1px;cursor:nwse-resize}
.rgh.nw::before{right:-1px;bottom:-1px}
.rgh.ne::before{left:-1px;bottom:-1px}
.rgh.sw::before{right:-1px;top:-1px}
.rgh.se::before{left:-1px;top:-1px}
/* Nothing over the page reaches past its edges: the page's overlay clips what stands outside it (a
   handle's reach), so that a section at the edge neither widens the page's scroll nor moves it
   sideways. At an edge of the page the handles stand inside the corners instead (regionPaint). */
.ov{overflow:hidden;overflow:clip}
.rgsel.atl .rgh.nw,.rgsel.atl .rgh.sw{right:auto;left:0;margin-left:0;margin-right:0}
.rgsel.atr .rgh.ne,.rgsel.atr .rgh.se{left:auto;right:0;margin-left:0;margin-right:0}
.rgsel.att .rgh.nw,.rgsel.att .rgh.ne{bottom:auto;top:0;margin-top:0;margin-bottom:0}
.rgsel.atb .rgh.sw,.rgsel.atb .rgh.se{top:auto;bottom:0;margin-top:0;margin-bottom:0}
.rgsel.atl .rgh.nw::before,.rgsel.atl .rgh.sw::before{right:auto;left:-1px}
.rgsel.atr .rgh.ne::before,.rgsel.atr .rgh.se::before{left:auto;right:-1px}
.rgsel.att .rgh.nw::before,.rgsel.att .rgh.ne::before{bottom:auto;top:-1px}
.rgsel.atb .rgh.sw::before,.rgsel.atb .rgh.se::before{top:auto;bottom:-1px}
/* the legal moves to tap: a few rows that scroll on a wide screen, one row that scrolls sideways on
   a phone, where the sheet has little room above the bar */
.rglist{display:grid;gap:4px}
.rglist[hidden]{display:none}
.rglist .choices{max-height:5.6em;overflow:auto}
@media (max-width:700px){.rglist .choices{flex-wrap:nowrap;overflow:auto hidden;max-height:none;white-space:nowrap}}
.rgread{display:grid;gap:4px}
.rgread .said{overflow-wrap:anywhere}
.fix input#rgsan{width:100%;max-width:24em}
.rgwhere{display:grid;gap:6px}
.rgopts{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 20px}
.rgopts .tb{text-align:left}
.rgopts .tb[aria-pressed="true"]{color:var(--accent);text-decoration:underline}
.rgopts .sub{color:var(--muted);font-size:13px;margin-left:6px}
@media (hover:none) and (pointer:coarse){.rgh{width:12px;height:12px}.rgh::before{width:36px;height:36px}}
/* a phone: the bar holds the button only where it leaves room for the current move (the button
   in the top bar serves the narrower windows) */
@media (max-width:480px){#mregion{display:none}}
/* a tablet held upright has the compact layout: the correction sheet (this one and every other
   editor's) stands above the bar as on a phone, where placeSheet() and revealMark() expect it,
   instead of in the panel below the page, out of sight */
@media (min-width:701px) and (max-width:1100px) and (orientation:portrait){
#fix:not([hidden]){position:fixed;left:0;right:0;z-index:9;max-height:62vh;overflow:auto;background:var(--bg);
border-top:1px solid var(--line);padding:12px 24px}
/* (the diagram editor's board as on a phone, a third of the height, so that the pieces and the
   buttons under it show in the sheet with it) */
.fixboard svg{max-width:min(100%,32vh);margin:0 auto}}
"""

REGION_JS = r"""
/* ---------------------------------------------------------------- reading a section of the page */
// RG.draw: the next drag on the page draws the section (the button, or "Select again");
// sel: the section, {page, rect: [x0, y0, x1, y1] in PDF points}; drag: a drag under way;
// anchor: the move the section's moves go with, where: "after" or "before" it, how: "main"
// (continue the main line, when the move ends it) or "var"; read: the program's reading of the
// section (the app); edit: the stored entry the sheet changes ({key, entry}); local: the moves the
// reader opened from a file shows for sections the book does not hold yet.
const RG = {draw: false, sel: null, drag: null, anchor: null, where: "after", how: "main", read: null,
  req: 0, snap: 0, snapVersion: -1, edit: null, local: [], seq: 0, swallow: -1e9, version: 0};
const R1 = (v) => Math.round(v * 10) / 10;
function regionOpen(){ return !!(RV.edit && RV.edit.kind === "region"); }
function regionButtons(){
  const on = RG.draw || regionOpen();
  for (const b of [$("regionbtn"), $("mregion")]) if (b) b.setAttribute("aria-pressed", String(on));
  const was = document.body.classList.contains("rgdraw");
  document.body.classList.toggle("rgdraw", RG.draw);
  // on a phone the board at the foot of the window gives the page room to draw on (renderMini)
  if (was !== RG.draw) renderMini();
}
function pagePoint(x, y){
  // a point of the window as PDF points on the page shown
  const r = $("pagebox").getBoundingClientRect(), P = D.pages[S.page];
  return [(x - r.left) * P.w / r.width, (y - r.top) * P.h / r.height];
}
function fitRect(r, page){
  // the rectangle with its corners in order, inside the page, at least a few points each way
  const P = D.pages[page];
  let [x0, y0, x1, y1] = [Math.min(r[0], r[2]), Math.min(r[1], r[3]), Math.max(r[0], r[2]), Math.max(r[1], r[3])];
  x0 = Math.max(0, x0); y0 = Math.max(0, y0); x1 = Math.min(P.w, x1); y1 = Math.min(P.h, y1);
  if (x1 - x0 < 6) { x1 = Math.min(P.w, x0 + 6); x0 = Math.max(0, x1 - 6); }
  if (y1 - y0 < 6) { y1 = Math.min(P.h, y0 + 6); y0 = Math.max(0, y1 - 6); }
  return [R1(x0), R1(y0), R1(x1), R1(y1)];
}
function regionPaint(){
  // the section over the page: an outline with a handle at each corner (it lives in the page's
  // overlay, which showPage draws again, and pageEyes paints it back)
  let box = $("rgsel");
  if (RG.sel && !regionOpen() && !RG.drag && !RG.draw) RG.sel = null;
  if (!RG.sel || RG.sel.page !== S.page) { if (box) box.remove(); return; }
  if (!box || box.parentElement !== $("ov")) {
    if (box) box.remove();
    box = document.createElement("div");
    box.id = "rgsel"; box.className = "rgsel";
    box.setAttribute("aria-label", "The section to read");
    box.innerHTML = ["nw", "ne", "sw", "se"].map(c => "<span class='rgh " + c + "' data-corner='" + c + "'></span>").join("");
    $("ov").appendChild(box);
  }
  const P = D.pages[S.page], r = RG.sel.rect;
  box.style.left = pct(r[0], P.w); box.style.top = pct(r[1], P.h);
  box.style.width = pct(r[2] - r[0], P.w); box.style.height = pct(r[3] - r[1], P.h);
  // a side of the section near the page's edge: its handles stand inside the corners there, where
  // the page's overlay does not cut them off
  const k = $("pagebox").getBoundingClientRect().width / P.w, near = 16;
  box.classList.toggle("atl", r[0] * k < near);
  box.classList.toggle("atr", (P.w - r[2]) * k < near);
  box.classList.toggle("att", r[1] * k < near);
  box.classList.toggle("atb", (P.h - r[3]) * k < near);
}
function setRegionTool(on){
  if (!on) { regionCancel(); say(""); return; }
  if (RV.edit && !regionOpen()) closeFix();
  RG.draw = true;
  regionButtons();
  // (on a phone the bar at the foot of the screen has no room for the button, and the top bar
  // scrolls away with the page: the pencil there reads a section with a tap)
  say("Drag across the moves that the program missed, or tap a word of them. A second tap on the button ends it." +
    ($("mregion") && !$("mregion").offsetParent && $("mpen") && $("mpen").offsetParent ?
      " Further down the page, the pencil in the bar below reads a section with a tap where no move is read." : ""));
}
function regionCancel(){
  RG.draw = false; RG.drag = null; RG.sel = null; RG.edit = null; RG.read = null;
  if (regionOpen()) closeFix();
  regionButtons();
  regionPaint();
}
function regionClosed(){
  // closeFix closed the sheet: the section goes with it
  RG.draw = false; RG.drag = null; RG.sel = null; RG.edit = null; RG.read = null;
  regionButtons();
  regionPaint();
}

/* the pointer: a drag draws the section, a tap takes the word under it; the handles and the inside
   of the section change it */
function regionDown(e){
  if (e.button > 0 || !e.isPrimary || !S.page || !(S.page in D.pages)) return;
  const t = e.target, corner = t.closest("[data-corner]"), inside = t.closest("#rgsel");
  const [x, y] = pagePoint(e.clientX, e.clientY);
  if (RG.sel && (corner || inside)) {
    RG.drag = {kind: corner ? corner.dataset.corner : "move", x, y, rect: RG.sel.rect.slice(), id: e.pointerId,
      moved: false, cx: e.clientX, cy: e.clientY};
    try { $("pagebox").setPointerCapture(e.pointerId); } catch (err) { /* the pointer is gone */ }
    e.preventDefault();
    e.stopPropagation();
    return;
  }
  // a drag of the mouse redraws the section while the sheet is open; by touch only after the button
  // or "Select again", so that a finger still scrolls the page
  if (!(RG.draw || (regionOpen() && e.pointerType === "mouse"))) return;
  if (t.closest(".eye,.ribbon,.bmnote,.symmenu")) return;
  RG.drag = {kind: "new", x, y, id: e.pointerId, moved: false, cx: e.clientX, cy: e.clientY,
    on: !!t.closest(".mark,.diag"), armed: RG.draw};
  // (the gesture is the section's: whatever turns the page by a swipe does not see it)
  if (RG.draw) e.stopPropagation();
}
function regionMove(e){
  const d = RG.drag;
  if (!d || e.pointerId !== d.id) return;
  if (d.kind === "pan") {
    // a finger that went up or down scrolls the page, as it would without the tool (the tool holds
    // the page's own scrolling while it is on, so it scrolls the page itself)
    window.scrollBy(0, d.py - e.clientY);
    $("pagescroll").scrollLeft += d.px - e.clientX;
    d.px = e.clientX; d.py = e.clientY;
    e.preventDefault();
    return;
  }
  if (!d.moved) {
    // (a new section needs a drag, not the slip of a tap; a handle follows the pointer at once)
    if (d.kind === "new" && Math.hypot(e.clientX - d.cx, e.clientY - d.cy) < 6) return;
    // by touch, a first movement up or down is a scroll: moves run along the lines of the page, so
    // a section is drawn across them
    if (d.kind === "new" && e.pointerType !== "mouse" && Math.abs(e.clientY - d.cy) > 2.5 * Math.abs(e.clientX - d.cx)) {
      Object.assign(d, {kind: "pan", px: e.clientX, py: e.clientY});
      regionMove(e);
      return;
    }
    d.moved = true;
    if (d.kind === "new") {
      try { $("pagebox").setPointerCapture(e.pointerId); } catch (err) { /* the pointer is gone */ }
      RG.sel = {page: S.page, rect: [d.x, d.y, d.x, d.y]};
    }
  }
  const [x, y] = pagePoint(e.clientX, e.clientY), P = D.pages[S.page];
  let r;
  if (d.kind === "new") r = [d.x, d.y, x, y];
  else if (d.kind === "move") {
    const w = d.rect[2] - d.rect[0], h = d.rect[3] - d.rect[1];
    const x0 = Math.max(0, Math.min(P.w - w, d.rect[0] + x - d.x)), y0 = Math.max(0, Math.min(P.h - h, d.rect[1] + y - d.y));
    r = [x0, y0, x0 + w, y0 + h];
  } else {
    // the corner follows the pointer from where it was taken (the handle stands beside the corner)
    r = d.rect.slice();
    r[d.kind[1] === "w" ? 0 : 2] += x - d.x;
    r[d.kind[0] === "n" ? 1 : 3] += y - d.y;
  }
  RG.sel.rect = fitRect(r, RG.sel.page);
  RG.version++;
  regionPaint();
  e.preventDefault();
  e.stopPropagation();
}
function regionUp(e, cancel){
  const d = RG.drag;
  if (!d || e.pointerId !== d.id) return;
  RG.drag = null;
  if (d.moved || d.kind !== "new") e.stopPropagation();
  try { $("pagebox").releasePointerCapture(e.pointerId); } catch (err) { /* not captured */ }
  if (cancel) { regionPaint(); return; }
  // (a scroll leaves the tool as it was, and its click goes nowhere)
  if (d.kind === "pan") { RG.swallow = performance.now(); return; }
  if (d.kind === "new" && !d.moved) {
    // a tap on a move box: its own click does the rest (it chooses the move); elsewhere a tap takes
    // the word under it while the tool waits for a section (with the sheet open, a click of the
    // mouse elsewhere changes nothing, as a tap does not: only a drag draws the section again)
    if (d.on || !d.armed) return;
    RG.swallow = performance.now();
    regionAt(d.x, d.y);
    return;
  }
  if (!d.moved) {
    // a tap on the section or its handles that moved nothing: the move printed under it, or beside
    // it under a handle's reach, is chosen, as a tap on that move would choose it
    RG.swallow = performance.now();
    const hit = markUnder(e.clientX, e.clientY);
    if (hit) selectNode(hit.node, {at: hit});
    return;
  }
  RG.swallow = performance.now();
  const w = RG.sel ? RG.sel.rect[2] - RG.sel.rect[0] : 0, h = RG.sel ? RG.sel.rect[3] - RG.sel.rect[1] : 0;
  if (d.kind === "new" && RG.sel && w < 12 && h > 2.5 * w) {
    // a tall sliver narrower than a printed move is no section: the tool waits for a drag across the moves
    RG.sel = null;
    regionPaint();
    say("A drag across the moves, from one corner of the section to the other, marks it.");
    return;
  }
  regionSelected();
}
function markUnder(x, y){
  // the move box (indexBoxes) that lies under a point of the window, beneath the section drawn over
  // the page
  const box = $("rgsel");
  if (box) box.style.pointerEvents = "none";
  const el = document.elementsFromPoint(x, y).find(t => t.matches && t.matches("#ov .mark[data-node]"));
  if (box) box.style.pointerEvents = "";
  return el ? markBox(el) : null;
}
function regionClick(e){
  // (the capture phase of the page's clicks) the click after a drag or a tap that made a section
  if (performance.now() - RG.swallow < 600) { RG.swallow = -1e9; e.stopPropagation(); e.preventDefault(); return; }
  if (e.target.closest("#rgsel")) { e.stopPropagation(); return; }
  // the pencil: a tap where no move or diagram box stands reads a section there
  const blank = e.target === $("ov") || e.target === $("pageimg") || e.target === $("pagebox");
  if (blank && PEN.on && reading() && !PEN.connect && !regionOpen()) {
    e.stopPropagation();
    const [x, y] = pagePoint(e.clientX, e.clientY);
    regionAt(x, y);
  }
}
function regionTouch(e){
  // touches that draw or change the section neither scroll the page nor turn it
  if (RG.drag || RG.draw || (e.target.closest && e.target.closest("#rgsel"))) {
    if (e.type === "touchmove" && e.cancelable) e.preventDefault();
    e.stopPropagation();
  }
}
function regionAt(x, y){
  // a tap: a box of about one word around the point, which the app's worker snaps to the word there
  RG.sel = {page: S.page, rect: fitRect([x - 30, y - 8, x + 30, y + 8], S.page)};
  RG.version++;
  regionSelected();
  if (!inApp()) return;
  RG.snap = ++RG.req;
  RG.snapVersion = RG.version;
  parent.postMessage({words: {id: RG.snap, page: S.page, rect: [x - 40, y - 24, x + 40, y + 24], near: 0}}, "*");
}
function snapped(m){
  // the words around the tap: the section becomes the word under it (or the nearest one), unless
  // the reader has moved the section meanwhile
  if (!RG.sel || m.id !== RG.snap || m.page !== RG.sel.page || RG.version !== RG.snapVersion) return;
  const r = RG.sel.rect, x = (r[0] + r[2]) / 2, y = (r[1] + r[3]) / 2;
  let best = null;
  for (const w of m.words || []) {
    const b = w.box, dx = Math.max(b[0] - x, 0, x - b[2]), dy = Math.max(b[1] - y, 0, y - b[3]);
    const d = Math.hypot(dx, dy);
    if (d <= 12 && (!best || d < best[0])) best = [d, b];
  }
  if (!best || RG.drag) return;
  RG.sel.rect = fitRect([best[1][0] - 1.5, best[1][1] - 1, best[1][2] + 1.5, best[1][3] + 1], RG.sel.page);
  RG.version++;
  regionPaint();
  regionRead();
}

/* the sheet */
function regionSelected(){
  RG.draw = false;
  // (the sheet says what to do now)
  say("");
  if (!regionOpen()) {
    if (!RG.edit) {
      // the move chosen is where the moves go, unless the reader chooses another one
      RG.anchor = S.node && D.nodes[S.node] ? S.node : null;
      RG.where = "after"; RG.how = "main";
    }
    regionSheet();
  }
  regionButtons();
  regionPaint();
  regionRead();
  const el = $("rgsel");
  if (el) revealMark(el);
}
function regionSheet(){
  const page = RG.sel.page;
  let h = "<div class=fh><h3>" + (RG.edit ? "Change the moves you read" : "Read a section of " + esc(pageName(page))) + "</h3></div>";
  h += "<p class='small muted'>The outline on the page marks the section. A drag on a corner changes its size, and a " +
    "drag inside it moves it.</p>";
  h += "<div class=rgread id=rgread></div>";
  h += "<div class=typed><label class='lab small' for=rgsan>The moves printed there</label><input type=text id=rgsan " +
    "autocomplete=off autocapitalize=off spellcheck=false placeholder='such as 8…Nb4 9.Qe4' aria-describedby=rgcheck></div>";
  h += "<p class='fixmsg small' id=rgcheck role=status></p>";
  h += "<div class=rglist id=rglist hidden></div>";
  h += "<div class=rgwhere id=rgwhere></div>";
  h += "<div class=fixacts><button class=tb id=rgok disabled>" + (RG.edit ? "Save the change" : "Add these moves") + "</button>" +
    "<button class=tb id=rgagain>Select again</button>" + (RG.edit ? "<button class=tb id=rgremove>Remove these moves</button>" : "") +
    "<button class=tb id=rgcancel>Cancel</button></div>";
  h += "<p class='fixmsg small' id=fixmsg role=status></p>";
  // (another editor that was open gives way: its own state goes with it)
  if (RV.edit && !regionOpen()) { RV.edit = null; S.preview = null; }
  showFix(h, "region", false);
  if (RG.edit) $("rgsan").value = regionTyped(RG.edit.entry);
  $("rgsan").addEventListener("input", regionCheck);
  $("rgsan").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if (!$("rgok").disabled) regionConfirm(); } });
  $("rgok").addEventListener("click", regionConfirm);
  $("rgagain").addEventListener("click", () => {
    RG.draw = true; regionButtons();
    setMsg("Drag across the moves again, or tap a word of them.");
  });
  $("rgcancel").addEventListener("click", () => { regionCancel(); say(""); });
  if ($("rgremove")) $("rgremove").addEventListener("click", regionRemove);
  $("rgread").addEventListener("click", (e) => {
    const o = e.target.closest("button[data-other]");
    if (o && RG.read && RG.read.other) {
      const alt = RG.read.other;
      RG.where = alt.side;
      $("rgsan").value = regionLabels(alt.san, alt.fen);
      regionWhere(); regionCheck(); regionRead();
      return;
    }
    const t = e.target.closest("button[data-cand]");
    if (!t || !RG.read || !RG.read.candidates) return;
    $("rgsan").value = regionLabels(RG.read.candidates[parseInt(t.dataset.cand, 10)].san);
    regionCheck();
  });
  $("rglist").addEventListener("click", (e) => {
    const t = e.target.closest("button[data-legal]");
    if (!t) return;
    // the move tapped takes the place of a move half typed, or comes after the moves typed
    const p = regionParse();
    $("rgsan").value = regionLabels(p.moves.map(m => m[1]).concat([t.dataset.legal]));
    regionCheck();
  });
  $("rgwhere").addEventListener("click", (e) => {
    const w = e.target.closest("button[data-where]"), k = e.target.closest("button[data-how]");
    if (w) { RG.where = w.dataset.where; regionWhere(); regionCheck(); regionRead(); }
    if (k) { RG.how = k.dataset.how; regionWhere(); }
  });
  regionWhere();
  regionCheck();
  renderRead();
}
function regionTyped(e){
  // the moves of a stored entry as the field shows them, with their numbers
  const spot = RG.anchor ? regionSpot(RG.anchor, RG.where) : null;
  const fen = spot ? spot.fen : null;
  return fen ? regionLabels(e.san.slice(e.first || 0), fen) : e.san.slice(e.first || 0).join(" ");
}
function regionLabels(sans, fen){
  // moves in SAN with their numbers, as a book prints them: "8…Nb4 9.Qe4"
  fen = fen || regionFen();
  if (!fen) return sans.join(" ");
  const out = [];
  for (const s of sans) {
    const legal = CJ.legalMoves(fen), m = legal.find(x => x[0] === s) || matchSan(s, legal);
    if (!m) { out.push(s); fen = null; break; }
    const f = fen.split(" "), black = f[1] === "b";
    out.push(!black ? f[5] + "." + m[0] : (out.length ? m[0] : f[5] + "…" + m[0]));
    fen = CJ.after(fen, m[1]);
  }
  return out.join(" ");
}
function regionSpot(id, where){
  // where moves after (or before) node id are stored: {key, before, prefix: the reader's own moves
  // they go on from, fen: the position they start from}, or null when no printed move holds them
  const n = D.nodes[id];
  if (!n) return null;
  if (where === "before") {
    const par = n.parent != null ? D.nodes[n.parent] : null;
    if (!par || !par.fen || par.status === "waiting") return null;
    if (n.key) return {key: n.key, before: true, prefix: [], fen: par.fen};
    if (n.corrected === "added") { const p = addedPath(id); return {key: p.key, before: p.before, prefix: p.san.slice(0, -1), fen: par.fen}; }
    return null;
  }
  if (!n.fen || n.status === "waiting") return null;
  const a = anchorOf(id);
  return a ? {key: a.key, before: a.before, prefix: a.san, fen: n.fen} : null;
}
function regionFen(){ const s = RG.anchor ? regionSpot(RG.anchor, RG.where) : null; return s ? s.fen : null; }
function editedMove(id){
  // whether node id is one of the moves of the section whose sheet is open to change it
  const n = D.nodes[id], e = RG.edit && RG.edit.entry;
  return !!(e && n && n.region && n.added === RG.edit.key && n.region.page === e.page &&
    n.region.rect.map(R1).join(",") === e.rect.map(R1).join(","));
}
function endsMain(id){
  // whether the main line ends at node id (the moves of the section being changed aside: a section
  // that continues the main line still does so when it is changed)
  const n = D.nodes[id];
  if (!n || !n.main) return false;
  const c = cont(id);
  return !c || editedMove(c);
}
function regionWhere(){
  const box = $("rgwhere");
  if (!box) return;
  const id = RG.anchor, n = id ? D.nodes[id] : null;
  if (!n) {
    box.innerHTML = "<p class=small>Tap the move, on the page or in the move list, that these moves follow.</p>";
    return;
  }
  if (n.parent == null || !regionSpot(id, "before")) RG.where = "after";
  const name = n.parent == null ? "the start of the line" : "<span class=n>" + moveHtml(id, true) + "</span>";
  let h = "<p class='lab small'>Where the moves go</p><div class=rgopts role=group aria-label='Where the moves go'>";
  h += "<button class=tb data-where=after aria-pressed='" + String(RG.where === "after") + "'>" +
    (n.parent == null ? "At the start of the line" : "After " + name) + "</button>";
  if (n.parent != null && regionSpot(id, "before"))
    h += "<button class=tb data-where=before aria-pressed='" + String(RG.where === "before") + "'>Before " + name +
      "<span class=sub>as alternatives to it</span></button>";
  h += "</div>";
  if (RG.where === "after" && endsMain(id) && n.parent != null) {
    h += "<div class=rgopts role=group aria-label='How the moves go on'>" +
      "<button class=tb data-how=main aria-pressed='" + String(RG.how === "main") + "'>Continue the main line</button>" +
      "<button class=tb data-how=var aria-pressed='" + String(RG.how === "var") + "'>As a variation</button></div>";
  } else if (RG.where === "after" && n.parent != null) {
    h += "<p class='small muted'>" + (cont(id) ? "The line goes on after this move, so the moves form a variation." :
      "The moves continue this variation.") + "</p>";
  }
  if (!regionSpot(id, RG.where))
    h += "<p class='small fixmsg bad'>The program has no printed move here to keep the moves with, or the position " +
      "here is unknown. Tap another move.</p>";
  h += "<p class='small muted'>A tap on another move, on the page or in the move list, chooses it instead.</p>";
  box.innerHTML = h;
}
function regionFollow(id){
  // the reader chose another move while the sheet is open: the moves go with it
  if (!regionOpen()) return;
  RG.anchor = id;
  if (D.nodes[id] && D.nodes[id].parent == null) RG.where = "after";
  regionWhere();
  regionCheck();
  regionRead();
}
function regionParse(){
  // the typed moves checked one by one from the position they start from:
  // {moves: [[label, SAN, UCI]], fen: the position after them, bad, why}
  const fen0 = regionFen(), out = {moves: [], fen: fen0, bad: null, why: ""};
  const text = ($("rgsan") ? $("rgsan").value : "").replace(/…/g, "...");
  let fen = fen0;
  for (let t of text.split(/\s+/)) {
    t = t.replace(/^\d+\s*\.+/, "");
    // move numbers on their own, and the result of a game, are no moves
    if (!t || /^\d+$/.test(t) || /^(?:1-0|0-1|1\/2-1\/2|½-½|\*)$/.test(t)) continue;
    if (!fen) { out.wait = true; return out; }
    const legal = CJ.legalMoves(fen), m = matchSan(t, legal);
    if (!m) { out.bad = t; out.why = CJ.whyNot(fen, sanKey(t)) || t + " is not a legal move here."; return out; }
    const f = fen.split(" ");
    out.moves.push([f[5] + (f[1] === "b" ? "…" : "."), m[0], m[1]]);
    fen = CJ.after(fen, m[1]);
    out.fen = fen;
  }
  return out;
}
const movesText = (ms) => ms.map((m, i) => (i === 0 || m[0].slice(-1) === "." ? m[0] : "") + m[1]).join(" ");
function regionAhead(p){
  // the typed moves that the line plays itself from the place chosen (a section drawn across the
  // last move the program read and the missed ones after it): the moves go on after the last of
  // them. {anchor: that move, skip: the line's own moves, rest: the moves to add}, or null
  const n = RG.anchor ? D.nodes[RG.anchor] : null;
  if (!n || !p.moves.length) return null;
  let at = RG.where === "before" ? n.parent : RG.anchor, k = 0;
  while (at != null && k < p.moves.length) {
    const kid = D.nodes[at].children.find(c => D.nodes[c].uci === p.moves[k][2] && !editedMove(c));
    if (!kid) break;
    at = kid; k++;
  }
  return k ? {anchor: at, skip: p.moves.slice(0, k), rest: p.moves.slice(k)} : null;
}
function regionCheck(){
  const box = $("rgcheck");
  if (!box) return;
  const p = regionParse(), ahead = p.bad ? null : regionAhead(p);
  const spot = ahead ? regionSpot(ahead.anchor, "after") : RG.anchor ? regionSpot(RG.anchor, RG.where) : null;
  const list = movesText(p.moves);
  let text = "", kind = "", none = false;
  if (p.wait) {
    // (no position to check the moves against yet: nothing is wrong with them)
    text = "Choose the move that these moves follow first: a tap on it, on the page or in the move list.";
  } else if (p.bad) {
    text = (p.moves.length ? "After " + list + ", " : "") + p.bad + " is not legal. " + p.why;
    kind = "bad";
  } else if (ahead && !ahead.rest.length) {
    text = "The line plays " + list + " itself. Choose the move after which the missed moves stand, or type them.";
    kind = "bad"; none = true;
  } else if (ahead) {
    const rest = movesText(ahead.rest);
    text = "The line plays " + movesText(ahead.skip) + " itself, so " + (ahead.rest.length === 1 ? "the move " + rest +
      " goes" : "the moves " + rest + " go") + " after " + moveText(ahead.anchor, true) + (ahead.rest.length === 1 ?
      ", where it is legal." : ", where they are legal.");
    kind = "good";
  } else if (p.moves.length) {
    text = (p.moves.length === 1 ? "The move " + list + " is" : "The moves " + list + " are") + " legal here.";
    kind = "good";
  }
  box.textContent = text;
  box.className = "fixmsg small" + (kind ? " " + kind : "");
  $("rgok").disabled = !!p.bad || !!p.wait || none || !p.moves.length || !spot;
  regionList(p);
  if (p.moves.length) preview(p.fen, p.moves[p.moves.length - 1][2], "The board shows the position after the moves you read.");
  else if (spot) preview(spot.fen, null, "The board shows the position that the moves start from.");
  else { S.preview = null; renderBoard(); }
  // (on a wide screen the sheet under the board keeps its field and buttons in view as it grows)
  keepChooserInView();
}

function regionList(p){
  // the moves legal next, from the move chosen and the moves typed so far, as options to tap (a
  // missed move is then picked as on the pencil's move sheet), while the program offers no reading
  // without doubt
  const box = $("rglist");
  if (!box) return;
  const r = RG.read || {};
  const fen = p.wait ? null : p.fen;
  if (!fen || (r.candidates && r.candidates.some(c => !c.unsure)) || r.waiting) { box.innerHTML = ""; box.hidden = true; return; }
  const a = p.bad ? sanKey(p.bad, true) : "";
  const hits = CJ.legalMoves(fen).filter(m => !a || sanKey(m[0], true).indexOf(a) === 0);
  box.hidden = false;
  box.innerHTML = "<p class='lab small'>" + (p.moves.length ? "The moves legal next" : "The moves legal here") + "</p>" +
    "<div class=choices aria-label='Legal moves'>" + hits.map(m => "<button data-legal='" + esc(m[0]) + "'>" +
    esc(m[0]) + "</button>").join("") + (hits.length ? "" : "<span class=sub>No legal move begins like this.</span>") +
    "</div>";
}

/* the program's reading of the section (the app's worker) */
function regionRead(){
  if (!regionOpen() || !RG.sel) return;
  if (!inApp()) { RG.read = {local: true}; renderRead(); return; }
  const id = ++RG.req, fen = regionFen();
  RG.read = {id, waiting: true};
  renderRead();
  // without a move to start from, the words alone
  if (!fen) parent.postMessage({words: {id, page: RG.sel.page, rect: RG.sel.rect, near: 0}}, "*");
  else {
    // the other place the moves may go (before the move rather than after it, or the other way), whose
    // reading the program offers when nothing reads without doubt at this one
    const other = RG.anchor && D.nodes[RG.anchor].parent != null ?
      regionSpot(RG.anchor, RG.where === "after" ? "before" : "after") : null;
    parent.postMessage({region: {id, page: RG.sel.page, rect: RG.sel.rect, at: fen, side: RG.where,
      other: other ? other.fen : null}}, "*");
  }
}
function renderRead(){
  const box = $("rgread");
  if (!box) return;
  const r = RG.read || {};
  let h = "<p class='lab small'>What the program reads there</p>";
  if (r.local) h += "<p class='small muted'>The reader opened from a file cannot read the text of the page; the browser " +
    "app can. Type the moves printed in the section, or tap them among the legal moves.</p>";
  else if (r.waiting) h += "<p class='small muted'>Reading the section.</p>";
  else if (r.failed) h += "<p class='small muted'>The program could not read the section: " + esc(r.failed) +
    " Type the moves printed there.</p>";
  else if (!r.text) h += "<p class='small muted'>The page's text holds no words in this section. Type the moves printed " +
    "there, or tap them among the legal moves.</p>";
  else {
    h += "<p class='said'>“<span class=n>" + shownHtml(r.text) + "</span>”</p>";
    if (!r.candidates) h += "<p class='small muted'>Choose the move that these moves follow, and the program reads them " +
      "from there.</p>";
    else if (!r.candidates.length) h += "<p class='small muted'>The program reads no move there that is legal at the " +
      "move chosen. Type the moves printed there, or tap them among the legal moves.</p>";
    else h += "<div class=choices id=rgcands aria-label='The readings of the section'>" + r.candidates.map((c, i) =>
      "<button data-cand='" + i + "'>" + esc(regionLabels(c.san, r.fen)) + (c.unsure ? "<span class=sub>unsure</span>" : "") +
      "</button>").join("") + "</div>";
    if (r.other && RG.anchor && D.nodes[RG.anchor]) {
      // the section reads without doubt from the other place: a printed "Qe4" is White's move
      const side = r.other.fen.split(" ")[1] === "w" ? "White" : "Black", there = r.other.side + " " + moveText(RG.anchor, true);
      h += "<p class=small><span class=n>" + esc(regionLabels(r.other.san, r.other.fen)) + "</span>, " + side +
        (r.other.san.length > 1 ? "'s moves first" : "'s move") + ", reads without doubt " + esc(there) + ". " +
        "<button class=tb data-other='" + esc(r.other.side) + "'>Put the moves " + esc(there) + "</button></p>";
    }
  }
  box.innerHTML = h;
  regionList(regionParse());
  keepChooserInView();
}
function regionMessage(e){
  if (e.source !== window.parent || e.source === window) return;
  const m = e.data || {};
  if (m.words) {
    const w = m.words;
    if (w.id === RG.snap) { snapped(w); return; }
    if (RG.read && w.id === RG.read.id) {
      RG.read = {id: w.id, text: (w.words || []).filter(x => x.inside).map(x => x.text).join(" "), candidates: null};
      renderRead();
    }
  } else if (m.regionRead) {
    const a = m.regionRead;
    if (!RG.read || a.id !== RG.read.id) return;
    RG.read = Object.assign({id: a.id}, a.result);
    renderRead();
  } else if (m.regionFailed !== undefined) {
    if (!RG.read || m.id !== RG.read.id) return;
    RG.read = {id: m.id, failed: String(m.regionFailed || "")};
    renderRead();
  }
}

/* storing the moves */
function regionEntry(spot, moves){
  // the "added" entry of the section, its keys in the order corrections.py writes them
  const e = {san: spot.prefix.concat(moves)};
  if (spot.before) e.before = true;
  e.page = RG.sel.page;
  e.rect = RG.sel.rect.map(R1);
  // what the program read there: now, or when the section was stored (the reader opened from a file
  // cannot read the page again)
  const kept = RG.edit && RG.edit.entry.page === e.page && sameEntry(RG.edit.entry.rect, e.rect) ? RG.edit.entry.text : null;
  if ((RG.read && RG.read.text) || kept) e.text = (RG.read && RG.read.text) || kept;
  if (spot.prefix.length) e.first = spot.prefix.length;
  if (!spot.before && RG.where === "after" && RG.how === "main" && endsMain(RG.anchor)) e.main = true;
  return e;
}
const sameEntry = (a, b) => JSON.stringify(a) === JSON.stringify(b);
function dropEntry(key, entry){
  // the stored entry taken out of its printed move's list
  const list = (FIX.get("added", key) || []).filter(e => !sameEntry(e, entry));
  storeAdded(key, list);
}
function regionConfirm(){
  const p = regionParse();
  if (p.bad || p.wait || !p.moves.length) return;
  // the moves that the line plays itself are its own: the rest go on after the last of them
  const ahead = regionAhead(p);
  if (ahead) {
    if (!ahead.rest.length) return;
    RG.anchor = ahead.anchor; RG.where = "after";
    p.moves = ahead.rest;
  }
  const spot = RG.anchor ? regionSpot(RG.anchor, RG.where) : null;
  if (!spot) return;
  const sans = p.moves.map(m => m[1]), e = regionEntry(spot, sans);
  if (RG.edit) dropEntry(RG.edit.key, RG.edit.entry);
  const list = (FIX.get("added", spot.key) || []).map(x => Object.assign({}, x));
  list.push(e);
  storeAdded(spot.key, list);
  const base = RG.where === "before" ? D.nodes[RG.anchor].parent : RG.anchor;
  const at = D.nodes[RG.anchor];
  const where = (RG.where === "before" ? "before " : "after ") + (at.parent == null ? "the start of the line" : moveText(RG.anchor, true));
  const said = "You added " + movesText(p.moves) +
    " " + (at.parent == null ? "at the start of the line" : where) + (e.main ? ", where the main line goes on with them" : "") + ". ";
  BM.want = {line: at.line, steps: pathOf(base).concat([{san: sans[0]}])};
  RG.edit = null;
  regionCancel();
  afterFix();
  if (!inApp()) {
    boardMoveApplied();
    say(said + "The reader shows them now, and the next run of the program writes them into the book and its PGN once " +
      "you copy the corrections on the contents page into the chat.");
  } else say(said + applyWords());
}
function regionRemove(){
  if (!RG.edit) return;
  // the move the section's moves went with is chosen once they are gone (in the app when the book
  // holds the change), as when a variation added on the board is removed: the board keeps its place
  const a = RG.anchor && D.nodes[RG.anchor] ? RG.anchor : null;
  const base = a && RG.where === "before" ? D.nodes[a].parent : a;
  if (base != null && D.nodes[base]) BM.want = {line: D.nodes[base].line, steps: pathOf(base)};
  dropEntry(RG.edit.key, RG.edit.entry);
  RG.edit = null;
  regionCancel();
  afterFix();
  if (!inApp()) boardMoveApplied();
  say("The moves you read are removed. " + applyWords());
}
function regionEntryOf(id){
  // the stored entry a move read from a section belongs to: {key, entry}
  const n = D.nodes[id];
  if (!n || !n.region) return null;
  const e = (FIX.get("added", n.added) || []).find(x => x.rect && x.page === n.region.page &&
    x.rect.join(",") === n.region.rect.map(R1).join(","));
  return e ? {key: n.added, entry: e} : null;
}
function openRegionNode(id){
  // a move read from a section: the sheet of that section, to change or remove it
  const hit = regionEntryOf(id);
  if (!hit) return false;
  const e = hit.entry;
  let at = nodeByKey(hit.key);
  if (!at) return false;
  // the move the section's moves go on from: the printed move, or the last of the reader's moves before them
  let where = e.before ? "before" : "after";
  if (e.first) {
    let cur = e.before ? D.nodes[at].parent : at;
    for (const s of e.san.slice(0, e.first)) {
      const c = cur != null ? D.nodes[cur].children.find(x => D.nodes[x].san === s) : null;
      if (!c) break;
      cur = c;
    }
    at = cur; where = "after";
  }
  if (S.page !== e.page && (e.page in D.pages)) showPage(e.page);
  if (RV.edit) closeFix();
  RG.edit = hit; RG.anchor = at; RG.where = where; RG.how = e.main ? "main" : "var";
  RG.sel = {page: e.page, rect: e.rect.slice()};
  RG.read = e.text ? {text: e.text, candidates: null} : null;
  regionSheet();
  regionButtons();
  regionPaint();
  regionRead();
  const el = $("rgsel");
  if (el) revealMark(el);
  return true;
}

/* the reader opened from a file: the sections the book does not hold yet are shown at once */
function localRegions(){
  if (inApp()) return false;
  // (the moves take their names afresh, in the order of the stored entries, so that a move keeps
  // its name from one opening of the reader to the next, and an address such as #node=rg2 holds)
  RG.seq = 0;
  let changed = false;
  for (const id of RG.local) {
    const n = D.nodes[id];
    if (!n) continue;
    const par = D.nodes[n.parent];
    if (par) par.children = par.children.filter(c => c !== id);
    delete D.nodes[id];
    changed = true;
  }
  RG.local = [];
  for (const p in D.pages) {
    const ms = D.pages[p].marks;
    if (ms.some(m => m.local)) { D.pages[p].marks = ms.filter(m => !m.local); changed = true; }
  }
  const held = (D.corrections && D.corrections.added) || {}, all = FIX.all("added");
  for (const key in all) for (const e of all[key]) {
    if (!e.rect || (held[key] || []).some(h => sameEntry(h, e))) continue;
    if (playLocal(key, e)) changed = true;
  }
  if (S.node && !D.nodes[S.node]) { S.node = null; S.at = null; }
  return changed;
}
function playLocal(key, e){
  // the moves of one entry, played from the printed move its key names, as the program plays them
  const at = nodeByKey(key);
  if (!at) return false;
  const n = D.nodes[at], base = e.before ? n.parent : at;
  if (base == null || !D.nodes[base] || !D.nodes[base].fen) return false;
  const first = e.first || 0;
  let parent = base, fen = D.nodes[base].fen, marked = false, made = false;
  for (let i = 0; i < e.san.length; i++) {
    const legal = CJ.legalMoves(fen), m = legal.find(x => x[0] === e.san[i]) || matchSan(e.san[i], legal);
    if (!m) break;
    const P = D.nodes[parent], hit = P.children.find(c => D.nodes[c].uci === m[1]);
    if (hit) {
      if (D.nodes[hit].added !== key) break;
      parent = hit; fen = D.nodes[hit].fen;
      continue;
    }
    const f = fen.split(" "), id = "rg" + (++RG.seq), next = CJ.after(fen, m[1]);
    const main = !!e.main && !e.before && P.main && !P.children.some(c => D.nodes[c].main);
    D.nodes[id] = {id, san: m[0], fen: next, parent, children: [], number: parseInt(f[5], 10), black: f[1] === "b",
      page: i >= first ? e.page : n.page, bbox: null, status: "ok", raw: "", comment: "", main, assumed: null,
      uci: m[1], line: n.line, corrected: "added", added: key};
    if (e.before) D.nodes[id].added_before = true;
    if (i >= first) {
      D.nodes[id].region = {page: e.page, rect: e.rect.slice()};
      if (!marked && D.pages[e.page]) {
        D.pages[e.page].marks.push({bbox: e.rect.slice(), node: id, status: "ok", raw: m[0], line: n.line,
          corrected: "added", local: true});
        D.nodes[id].bbox = e.rect.slice();
        marked = true;
      }
    }
    P.children.push(id);
    RG.local.push(id);
    made = true;
    parent = id; fen = next;
  }
  return made;
}
function regionRefresh(){
  // the page, its lines and the move list after the shown sections changed
  if (!localRegions()) return;
  indexBoxes();
  if (S.page) showPage(S.page);
  renderTree(); renderBoard(); layoutPanel(false);
}

function initRegion(){
  for (const b of [$("regionbtn"), $("mregion")])
    if (b) b.addEventListener("click", () => setRegionTool(!(RG.draw || regionOpen())));
  const box = $("pagebox");
  // a new gesture: the click that a drag or tap may have left unsent is not waited for any longer
  box.addEventListener("pointerdown", () => { RG.swallow = -1e9; }, true);
  box.addEventListener("pointerdown", regionDown);
  box.addEventListener("pointermove", regionMove);
  box.addEventListener("pointerup", (e) => regionUp(e, false));
  box.addEventListener("pointercancel", (e) => regionUp(e, true));
  box.addEventListener("click", regionClick, true);
  for (const t of ["touchstart", "touchmove", "touchend"]) box.addEventListener(t, regionTouch, {passive: false});
  window.addEventListener("message", regionMessage);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && (RG.draw || regionOpen()) && !e.target.closest(".fix input")) { regionCancel(); say(""); }
  });
  // the tool belongs to reading mode: it ends when reading mode does
  new MutationObserver(() => { if (!reading() && (RG.draw || regionOpen())) regionCancel(); })
    .observe(document.body, {attributes: true, attributeFilter: ["class"]});
  regionButtons();
  // (the sections the book does not hold yet are on the pages already: init() played them before
  // it read the address, so that an address naming one of their moves finds it)
}
"""
