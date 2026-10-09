// End-to-end test of moving pieces on the board, in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/boardmove_e2e.js CHAPTER_HTML PATCHES_JSON SCREENS_DIR
//
// Opens a chapter reader of the generated test book (tests/test_reader.py
// builds it, with the diagram on page 5 read as a position where White's pawn
// on a7 can promote, and the three patches that chessbook/live.py makes when
// the reader adds 2...d6 after 2.Nf3, makes it 2...d6 3.d4, and removes it).
// On a desktop, with the mouse: a drag of the book's move steps to it; a tap on
// a piece marks it and its squares, a second tap lets it go; a drop on a square
// the piece cannot reach puts it back; a move the line does not hold opens the
// chooser, which outside reading mode only adds a variation and in reading
// mode also corrects (correct the main line, add a variation, cancel), whose Cancel brings
// the board back; "Add a new variation" stores it ("added"), and the patch
// chooses the new move, marked "Added by you"; a move from the end of that
// variation makes it longer without a question; the Review list names it; its
// corrector removes it; "Correct the main line" and "Correct this variation"
// store a "moves" correction; a pawn that reaches the last rank asks for the
// piece; the board of the diagram view takes the line's first move; the
// diagram corrector still takes taps. On an iPhone 13 (touch): taps on the
// board that stays at the foot of the window, a drag on the board in its place
// below the page (after Moves) that does not scroll the
// page, and a swipe that still turns the page. On an iPad held sideways: a tap
// on a piece and on its square. Screenshots of the chooser and of an added
// variation in the light and dark schemes. Prints one JSON object; the exit
// code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [file, patchFile, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], screenshots: [] };
function check(name, cond, detail) {
  out.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed: " + name + (detail ? " (" + JSON.stringify(detail) + ")" : ""));
}

(async () => {
  const browser = await chromium.launch();
  const url = "file://" + path.resolve(file);
  const patches = JSON.parse(fs.readFileSync(patchFile, "utf-8"));
  fs.mkdirSync(screens, { recursive: true });
  const watch = (page) => {
    page.on("console", (m) => { if (m.type() === "error") out.errors.push(m.text()); });
    page.on("pageerror", (e) => out.errors.push(String(e)));
  };
  const shot = async (page, name) => {
    const p = path.join(screens, name);
    await page.screenshot({ path: p });
    out.screenshots.push(p);
  };
  const both = async (page, name) => {
    await shot(page, name + "_light.png");
    await page.emulateMedia({ colorScheme: "dark" });
    await shot(page, name + "_dark.png");
    await page.emulateMedia({ colorScheme: "light" });
  };
  // the middle of a square of the board in sel, on the screen
  const at = (page, sel, sq) => page.evaluate(([sel, sq]) => {
    const svg = document.querySelector(sel);
    const r = svg.getBoundingClientRect(), flip = svg.dataset.flip === "1";
    const f = "abcdefgh".indexOf(sq[0]), row = 8 - parseInt(sq[1], 10);
    const c = flip ? 7 - f : f, rr = flip ? 7 - row : row;
    const k = r.width / 375;
    return [r.left + (14 + (c + 0.5) * 45) * k, r.top + (1 + (rr + 0.5) * 45) * k];
  }, [sel, sq]);
  const drag = async (page, sel, from, to) => {
    let [x, y] = await at(page, sel, from);
    await page.mouse.move(x, y);
    await page.mouse.down();
    [x, y] = await at(page, sel, to);
    await page.mouse.move(x, y, { steps: 6 });
    await page.mouse.up();
  };
  const click = async (page, sel, sq) => { const [x, y] = await at(page, sel, sq); await page.mouse.click(x, y); };
  const state = (page) => page.evaluate(() => {
    const n = READER.nodes[window.readerState.nodeId];
    return { id: window.readerState.nodeId, san: n ? n.san : null, corrected: n ? n.corrected || null : null,
      fix: JSON.parse(window.correctionsText()), open: !document.getElementById("fix").hidden,
      fixText: document.getElementById("fix").innerText, note: document.getElementById("boardnote").textContent,
      msg: document.getElementById("pagemsg").textContent };
  });
  const ids = (page) => page.evaluate(() => {
    const find = (f) => Object.keys(READER.nodes).find(k => f(READER.nodes[k]));
    const N = READER.nodes;
    const nf3 = find(n => n.san === "Nf3" && n.main), nc6 = find(n => n.san === "Nc6" && n.main);
    const bc5 = find(n => n.san === "Bc5" && !n.main), c3 = find(n => n.san === "c3" && !n.main);
    const rd8 = find(n => n.san === "Rd8+" && n.main);
    return { nf3, nc6, bc5, c3, rd8, nf3key: N[nf3].key, nc6key: N[nc6].key, c3key: N[c3].key,
      rd8key: N[rd8].key, diagLine: N[rd8].line };
  });
  const goNode = async (page, id) => {
    await page.evaluate((id) => { location.hash = "#node=" + id; }, id);
    await page.waitForFunction((id) => window.readerState.nodeId === id, id);
  };
  const fresh = async (page, hash) => {
    await page.evaluate(() => localStorage.clear());
    await page.goto(url + (hash || ""));
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState);
  };
  const B = "#board svg.board";
  try {
    // ---------------------------------------------------------------- desktop, with the mouse
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    watch(page);
    await page.goto(url);
    await page.waitForFunction(() => window.READER && window.readerState);
    await page.evaluate(() => localStorage.clear());
    let I = await ids(page);
    await goNode(page, I.nf3);

    // the book's move: a step, with no question
    await drag(page, B, "b8", "c6");
    let s = await state(page);
    check("a drag of the book's move steps to it", s.id === I.nc6 && !s.open, s);
    await page.click("#tree .mv[data-node='" + I.nf3 + "']");

    // a tap marks the piece and the squares it can reach; a second tap lets it go
    await click(page, B, "d7");
    let marks = await page.evaluate(() => ({ pick: document.querySelectorAll("#board .bmx.pk").length,
      to: document.querySelectorAll("#board .bmx.tg").length }));
    check("a tap marks the piece and its two squares", marks.pick === 1 && marks.to === 2, marks);
    await click(page, B, "d7");
    marks = await page.evaluate(() => document.querySelectorAll("#board .bmx").length);
    check("a second tap lets the piece go", marks === 0, marks);

    // a drop on a square the piece cannot reach puts it back
    await drag(page, B, "d7", "d4");
    s = await state(page);
    check("an illegal drop puts the piece back", s.id === I.nf3 && !s.open && !Object.keys(s.fix.moves).length &&
      !Object.keys(s.fix.added).length, s);
    check("the piece stands on its square again", await page.evaluate(() =>
      !!document.querySelector("#board use[data-at='d7']") && !document.querySelector("#board use.lifted") &&
      !document.querySelector("#board .ghost")));

    // another move outside reading mode: the chooser adds a variation only, and says where the
    // corrections of the book's line are
    await click(page, B, "d7");
    await click(page, B, "d6");
    s = await state(page);
    check("outside reading mode the chooser offers only a new variation and Cancel, and points to Show reading",
          s.open && /Your move 2…d6/.test(s.fixText) && /Add a new variation/.test(s.fixText) && /Cancel/.test(s.fixText) &&
          !/Correct the main line|Correct this variation/.test(s.fixText) && /Show reading/.test(s.fixText) &&
          !(await page.$("#bmmain")), s.fixText);
    await page.click("#bmcancel");

    // in reading mode another move opens the whole chooser, by a tap on the piece and a tap on its square
    await page.click("#showread");
    await click(page, B, "d7");
    await click(page, B, "d6");
    s = await state(page);
    check("another move opens the chooser", s.open && /Your move 2…d6/.test(s.fixText), s.fixText);
    check("the chooser offers to correct the main line", /Correct the main line: 2…d6 instead of 2…Nc6/.test(s.fixText), s.fixText);
    check("the chooser offers a new variation and Cancel", /Add a new variation/.test(s.fixText) && /Cancel/.test(s.fixText) &&
      !/Correct this variation/.test(s.fixText), s.fixText);
    check("the board shows the move while the chooser asks", await page.evaluate(() =>
      !!document.querySelector("#board use[data-at='d6']") && !document.querySelector("#board use[data-at='d7']")));
    const style = await page.evaluate(() => {
      const b = document.getElementById("bmadd"), cs = getComputedStyle(b);
      return { bg: cs.backgroundColor, border: cs.borderTopWidth, radius: cs.borderTopLeftRadius, shadow: cs.boxShadow,
        mono: getComputedStyle(document.querySelector("#bmmain .n")).fontFamily };
    });
    check("the choices are plain text buttons", (style.bg === "rgba(0, 0, 0, 0)" || style.bg === "transparent") &&
      style.border === "0px" && style.shadow === "none", style);
    check("the moves in the choices are set in Geist Mono", /Geist Mono/.test(style.mono), style);
    await both(page, "boardmove_chooser_1280");
    await page.click("#bmcancel");
    s = await state(page);
    check("Cancel brings the board back", !s.open && s.id === I.nf3 && !Object.keys(s.fix.added).length &&
      await page.evaluate(() => !!document.querySelector("#board use[data-at='d7']")), s);

    // a new variation, by a drag
    await drag(page, B, "d7", "d6");
    await page.waitForSelector("#bmadd");
    await page.click("#bmadd");
    s = await state(page);
    check("Add a new variation stores it under the move it branches from",
      JSON.stringify(s.fix.added) === JSON.stringify({ [I.nf3key]: [{ san: ["d6"] }] }), s.fix.added);
    check("the board shows the new position at once", !s.open && /You added 2…d6 as a new variation/.test(s.note) &&
      await page.evaluate(() => !!document.querySelector("#board use[data-at='d6']")), s);
    await page.evaluate((p) => window.applyPatch(p), patches[0]);
    s = await state(page);
    check("the patch chooses the new move", s.san === "d6" && s.corrected === "added", s);
    let view = await page.evaluate(() => ({ tree: document.getElementById("tree").innerText,
      dot: document.querySelectorAll("#tree .dot.st-added").length, info: document.getElementById("info").innerText }));
    check("the move list shows the variation with its dot", /2…d6/.test(view.tree) && view.dot === 1, view);
    check("the status says Added by you", /Added by you/.test(view.info) && /Change your variation/.test(view.info), view.info);

    // the end of the variation: a move makes it longer, with no question
    await drag(page, B, "d2", "d4");
    s = await state(page);
    check("a move at the end of an added variation makes it longer", !s.open &&
      JSON.stringify(s.fix.added) === JSON.stringify({ [I.nf3key]: [{ san: ["d6", "d4"] }] }), s);
    check("the board says so", /Your variation goes on with 3\.d4/.test(s.note), s.note);
    await page.evaluate((p) => window.applyPatch(p), patches[1]);
    s = await state(page);
    check("the patch chooses the move that makes it longer", s.san === "d4" && s.corrected === "added", s);
    await both(page, "boardmove_added_1280");

    // the Review list names the variation (Review shows in reading mode, which is on)
    await page.click("#reviewbtn");
    const rev = await page.evaluate(() => document.getElementById("revlist").innerText);
    check("the Review list names the variation", /Your variation after 2\.Nf3/.test(rev) && /Added by you/.test(rev), rev);
    await page.click("#revlist button[data-kind='added']");
    await page.waitForFunction(() => /Your variation/.test((document.querySelector("#fix h3") || {}).textContent || ""));
    s = await state(page);
    check("its item opens the variation's corrector", /You added 2…d6 3\.d4 on the board/.test(s.fixText) &&
      /Remove this variation/.test(s.fixText) && s.san === "d6", s.fixText);
    await page.click("#reviewbtn");

    // the corrector of a move of the variation removes it
    const d4 = await page.evaluate(() => Object.keys(READER.nodes).find(k => READER.nodes[k].corrected === "added" &&
      READER.nodes[k].san === "d4"));
    await page.click("#tree .mv[data-node='" + d4 + "']");
    await page.click("#fixadded");
    s = await state(page);
    check("the corrector of an added move offers both removals", /Remove this variation/.test(s.fixText) &&
      /Remove from 3\.d4 on/.test(s.fixText), s.fixText);
    await page.click("#addrm");
    s = await state(page);
    check("Remove this variation removes it from the corrections", !Object.keys(s.fix.added).length, s.fix);
    await page.evaluate((p) => window.applyPatch(p), patches[2]);
    s = await state(page);
    check("the patch removes the variation and chooses the move it branched from", s.san === "Nf3" &&
      await page.evaluate(() => !Object.values(READER.nodes).some(n => n.corrected === "added")), s);

    // correcting the main line
    I = await ids(page);
    await goNode(page, I.nf3);
    await drag(page, B, "d7", "d6");
    await page.click("#bmmain");
    s = await state(page);
    check("Correct the main line stores the move for the book's move", s.fix.moves[I.nc6key] &&
      s.fix.moves[I.nc6key].san === "d6", s.fix);
    check("the page says what changed", /The main line now plays 2…d6 instead of 2…Nc6/.test(s.msg), s.msg);

    // correcting a variation of the book (in reading mode, which a fresh page leaves off)
    await fresh(page);
    await page.click("#showread");
    I = await ids(page);
    await goNode(page, I.bc5);
    await drag(page, B, "d2", "d4");
    s = await state(page);
    check("inside a variation the chooser offers to correct it", /Correct this variation: 4\.d4 instead of 4\.c3/.test(s.fixText) &&
      !/Correct the main line/.test(s.fixText) && /Add a new variation/.test(s.fixText), s.fixText);
    await page.click("#bmvar");
    s = await state(page);
    check("Correct this variation stores the move for the variation's move", s.fix.moves[I.c3key] &&
      s.fix.moves[I.c3key].san === "d4", s.fix);

    // a pawn that reaches the last rank asks for the piece
    await fresh(page, "#line=" + I.diagLine);
    await page.waitForFunction(() => window.readerState.nodeId && READER.nodes[window.readerState.nodeId].parent == null);
    await page.click("#showread");
    await drag(page, B, "a7", "a8");
    s = await state(page);
    check("a promotion asks for the piece", /Promote the pawn/.test(s.fixText) &&
      await page.evaluate(() => document.querySelectorAll("#bmpromo button[data-piece]").length === 4), s.fixText);
    await shot(page, "boardmove_promotion_1280_light.png");
    await page.click("#bmpromo button[data-piece='N']");
    s = await state(page);
    check("the chooser names the piece chosen", /Your move 1\.a8=N/.test(s.fixText) &&
      /Correct the main line: 1\.a8=N instead of 1\.Rd8\+/.test(s.fixText), s.fixText);
    await page.click("#bmadd");
    s = await state(page);
    check("a variation at the start of a line is stored before its first move",
      JSON.stringify(s.fix.added) === JSON.stringify({ [I.rd8key]: [{ san: ["a8=N"], before: true }] }), s.fix.added);

    // a tap on the diagram sets up its line at the start, and the board takes the line's first move
    await fresh(page, "#page=5");
    await page.click(".diag[data-diagram='p5-1']");
    await page.waitForSelector("#dpanel[hidden]", { state: "attached" });
    await page.waitForSelector("#board svg.board");
    await drag(page, "#board svg.board", "d1", "d8");
    s = await state(page);
    check("from the diagram's line at its start, the board steps to the line's first move", s.id === I.rd8 && !s.open, s);

    // in reading mode, with the pencil it starts with turned off, the tap opens the diagram's panel,
    // whose corrector still takes taps on its squares
    await page.click("#showread");
    await page.click("#penbtn");
    await page.click(".diag[data-diagram='p5-1']");
    await page.waitForSelector("#dpanel:not([hidden]) .boardwrap svg.board");
    await page.click("#dfix");
    await page.waitForSelector("#fixboard svg");
    await page.click("#fixboard [data-sq='e4']");
    await page.click("#fixpieces button[data-put='N']");
    const ed = await page.evaluate(() => ({ sel: !!document.querySelector("#fixboard .sel"),
      knight: !!document.querySelector("#fixboard use[data-at='e4']") }));
    check("the diagram corrector still takes a tap and a piece", ed.sel && ed.knight, ed);
    await page.click("#fixclose");
    await ctx.close();

    // ---------------------------------------------------------------- iPhone 13, by touch
    const phone = await browser.newContext({ ...devices["iPhone 13"] });
    const pp = await phone.newPage();
    watch(pp);
    await pp.goto(url);
    await pp.waitForFunction(() => window.READER && window.readerState);
    await pp.evaluate(() => localStorage.clear());
    I = await ids(pp);
    await pp.goto(url + "#page=4");
    await pp.waitForFunction(() => window.readerState.page === 4);
    await pp.tap(".mark[data-node='" + I.nf3 + "']");
    // the board stays at the foot of the window, above the bar, while the page is in view
    await pp.waitForFunction(() => document.body.classList.contains("stickboard"));
    const foot = await pp.evaluate(() => [document.getElementById("boardblock").getBoundingClientRect().bottom,
      document.getElementById("mbar").getBoundingClientRect().top]);
    check("on a phone the board stays at the foot of the window, above the bar", Math.abs(foot[0] - foot[1]) <= 1.5, foot);
    const M = "#board svg.board";
    let [x, y] = await at(pp, M, "d7");
    await pp.touchscreen.tap(x, y);
    [x, y] = await at(pp, M, "d6");
    await pp.touchscreen.tap(x, y);
    s = await state(pp);
    check("taps on the board at the foot of the window make a move", s.open && /Your move 2…d6/.test(s.fixText), s.fixText);
    const sheet = await pp.evaluate(() => {
      const f = document.getElementById("fix"), bar = document.getElementById("mbar");
      return { pos: getComputedStyle(f).position, bottom: f.getBoundingClientRect().bottom,
        barTop: bar.getBoundingClientRect().top, sw: document.documentElement.scrollWidth, w: window.innerWidth };
    });
    check("on a phone the chooser is the sheet above the bar", sheet.pos === "fixed" && Math.abs(sheet.bottom - sheet.barTop) < 2, sheet);
    check("no sideways scroll at 390 px", sheet.sw <= sheet.w, sheet);
    await both(pp, "boardmove_chooser_390");
    await pp.tap("#bmadd");
    s = await state(pp);
    check("a tap on Add a new variation stores it", JSON.stringify(s.fix.added) === JSON.stringify({ [I.nf3key]: [{ san: ["d6"] }] }), s.fix);
    await pp.evaluate((p) => window.applyPatch(p), patches[0]);
    await pp.tap("#mmoves");
    await pp.waitForTimeout(400);
    await both(pp, "boardmove_added_390");

    // a drag on the large board moves the piece and does not scroll the page
    await fresh(pp, "#node=" + I.nf3);
    await pp.waitForFunction((id) => window.readerState.nodeId === id, I.nf3);
    await pp.tap("#mmoves");
    await pp.waitForTimeout(300);
    const cdp = await phone.newCDPSession(pp);
    const touchDrag = async (sel, from, to) => {
      const [x0, y0] = await at(pp, sel, from), [x1, y1] = await at(pp, sel, to);
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: x0, y: y0 }] });
      for (let i = 1; i <= 8; i++)
        await cdp.send("Input.dispatchTouchEvent", { type: "touchMove",
          touchPoints: [{ x: x0 + (x1 - x0) * i / 8, y: y0 + (y1 - y0) * i / 8 }] });
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
      await pp.waitForTimeout(150);
    };
    const y0 = await pp.evaluate(() => window.scrollY);
    await touchDrag(B, "g8", "f6");
    s = await state(pp);
    const y1 = await pp.evaluate(() => window.scrollY);
    check("a drag by touch on the large board makes a move", s.open && /Your move 2…Nf6/.test(s.fixText), s.fixText);
    check("the drag does not scroll the page", Math.abs(y1 - y0) < 2, { y0, y1 });
    await pp.tap("#bmcancel");
    await touchDrag(B, "b8", "c6");
    s = await state(pp);
    check("a drag by touch of the book's move steps to it", s.id === I.nc6 && !s.open, s);

    // a swipe across the page still turns it
    await pp.evaluate(() => window.scrollTo(0, 0));
    await pp.waitForTimeout(200);
    const p0 = await pp.evaluate(() => window.readerState.page);
    // (above the board at the foot of the window)
    const r = await pp.evaluate(() => { const b = document.getElementById("pagescroll").getBoundingClientRect();
      const bar = document.getElementById("boardblock").getBoundingClientRect();
      return [b.left + b.width * 0.8, b.left + b.width * 0.15, (Math.max(b.top, 0) + bar.top) / 2]; });
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: r[0], y: r[2] }] });
    for (let i = 1; i <= 6; i++)
      await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: r[0] + (r[1] - r[0]) * i / 6, y: r[2] }] });
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await pp.waitForFunction((p0) => window.readerState.page !== p0, p0, { timeout: 3000 });
    check("a swipe still turns the page", await pp.evaluate((p0) => window.readerState.page === p0 + 1, p0));
    await phone.close();

    // ---------------------------------------------------------------- iPad held sideways
    const pad = await browser.newContext({ viewport: { width: 1180, height: 820 }, deviceScaleFactor: 2,
      isMobile: true, hasTouch: true });
    const tp = await pad.newPage();
    watch(tp);
    await tp.goto(url);
    await tp.waitForFunction(() => window.READER && window.readerState);
    await tp.evaluate(() => localStorage.clear());
    I = await ids(tp);
    await goNode(tp, I.nf3);
    [x, y] = await at(tp, B, "d7");
    await tp.touchscreen.tap(x, y);
    [x, y] = await at(tp, B, "d6");
    await tp.touchscreen.tap(x, y);
    s = await state(tp);
    check("on a tablet a tap on a piece and on its square make a move", s.open && /Your move 2…d6/.test(s.fixText), s.fixText);
    await both(tp, "boardmove_chooser_1180");
    await tp.tap("#bmadd");
    await tp.evaluate((p) => window.applyPatch(p), patches[0]);
    s = await state(tp);
    check("on a tablet the patch chooses the new move", s.san === "d6" && s.corrected === "added", s);
    await both(tp, "boardmove_added_1180");
    await pad.close();

    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (err) {
    out.failure = String(err && err.message ? err.message : err);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
