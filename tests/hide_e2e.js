// End-to-end test of Hide next moves, in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/hide_e2e.js CHAPTER_HTML SCREENS_DIR MAIN_SAN_JSON
//
// Opens the first chapter of the generated test book (tests/test_reader.py) at the start of its
// first game, on a desktop. The eye struck through turns the mode on and stores it; every move of
// the game is then a dotted blank in the move list, whose text names none of the game's moves, and
// a box in the paper colour on the page. A move on the board that the book does not play (1.a3) is
// refused: the sheet offers Try again, the line stays at its start and the covers stay; Try again
// brings the board back. The book's move (1.e4) steps to it and uncovers it, and the book's reply
// (1...e5) is played and uncovered after a moment. The right arrow shows the book's next move; End
// stops at the last move shown; a click on a covered move, in the move list or on the page, goes to
// the position before it and says why; the arrow key then steps the moves, not the page. The
// covered moves keep their numbers; the legend says what a cover is; the focus stays in the move
// list as the arrows uncover moves; a new reading of the chapter (a patch) keeps the moves reached.
// A book's move the program could not read is never named while it is covered. "You play" in the
// gear's sheet is stored. The mode outlasts
// a reload, the covers a turn of the page; on the inverted page the covers are inverted with it;
// with the analysis on, the engine's moves are hidden; turning the mode off shows every move. On an
// iPhone 13 the bar's button turns the mode on, the page does not scroll sideways and the bar's
// current move has room for "23…Qxf7+". Screenshots
// in the light and dark schemes and on the phone. Prints one JSON object; the exit code is 1 when
// a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [file, screens, mainJson] = process.argv.slice(2);
const MAIN_SAN = JSON.parse(mainJson);
const out = { ok: false, checks: [], errors: [], screenshots: [] };
function check(name, cond, detail) {
  out.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed: " + name + (detail ? " (" + JSON.stringify(detail) + ")" : ""));
}

(async () => {
  const browser = await chromium.launch();
  const url = "file://" + path.resolve(file);
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
  // the middle of a square of the board on the screen
  const at = (page, sq) => page.evaluate((sq) => {
    const svg = document.querySelector("#board svg.board");
    const r = svg.getBoundingClientRect(), flip = svg.dataset.flip === "1";
    const f = "abcdefgh".indexOf(sq[0]), row = 8 - parseInt(sq[1], 10);
    const c = flip ? 7 - f : f, rr = flip ? 7 - row : row;
    const k = r.width / 375;
    return [r.left + (14 + (c + 0.5) * 45) * k, r.top + (1 + (rr + 0.5) * 45) * k];
  }, sq);
  const drag = async (page, from, to) => {
    let [x, y] = await at(page, from);
    await page.mouse.move(x, y);
    await page.mouse.down();
    [x, y] = await at(page, to);
    await page.mouse.move(x, y, { steps: 6 });
    await page.mouse.up();
  };
  // the first game: its line, its start and its main moves
  const game = (page) => page.evaluate(() => {
    const N = READER.nodes;
    const line = Object.keys(READER.lines).find(k => READER.lines[k].title.indexOf("Smith") === 0);
    const root = READER.lines[line].root, main = [];
    for (let id = root; ;) { const c = N[id].children.find(k => N[k].main); if (!c) break; main.push(c); id = c; }
    return { line, root, main, rootFen: N[root].fen || READER.lines[line].start_fen, page: READER.lines[line].page };
  });
  const view = (page) => page.evaluate(() => {
    const tree = document.getElementById("tree");
    return { id: window.readerState.nodeId, fen: window.readerState.fen, msg: document.getElementById("pagemsg").textContent,
      open: !document.getElementById("fix").hidden, fixText: document.getElementById("fix").innerText,
      tree: tree.innerText, hidTree: [...tree.querySelectorAll(".mv.hid")].map(el => el.dataset.node),
      hidPage: [...document.querySelectorAll("#ov .mark.hid")].map(el => el.dataset.node), page: window.readerState.page };
  });
  const markOf = (id) => "#ov .mark[data-node='" + id + "']";
  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    watch(page);
    await page.goto(url);
    await page.waitForFunction(() => window.READER && window.readerState);
    await page.evaluate(() => localStorage.clear());
    const G = await game(page);
    await page.goto(url + "#line=" + G.line);
    await page.reload();
    await page.waitForFunction((r) => window.readerState.nodeId === r, G.root);
    const [e4, e5, nf3, nc6] = G.main;

    // the button turns the mode on, and the choice is stored
    await page.click("#bhide");
    const btn = await page.evaluate(() => ({ pressed: document.getElementById("bhide").getAttribute("aria-pressed"),
      label: document.getElementById("bhide").getAttribute("aria-label"), stored: localStorage.getItem("chessbook-hide"),
      fwd: document.getElementById("bfwd").title, msg: document.getElementById("pagemsg").textContent }));
    const more = await page.evaluate(() => ({ title: document.getElementById("bhide").title,
      fwdLabel: document.getElementById("bfwd").getAttribute("aria-label"),
      key: (() => { const el = document.querySelector(".legend .coverkey"); return el && el.offsetParent ? el.textContent : null; })(),
      others: [...document.querySelectorAll(".legend > span:not(.coverkey)")].filter(el => el.offsetParent).length }));
    check("hide button", btn.pressed === "true" && btn.stored === "1" && btn.label === "Show next moves" &&
      btn.fwd === "Show the book's move (right arrow)" && /next moves are hidden\. You play White/.test(btn.msg) &&
      more.title === "Show next moves (H)" && more.fwdLabel === "Show the book's move" &&
      /hidden until you play it/.test(more.key || "") && more.others === 0, { btn, more });

    // every move of the game is a blank in the move list, and names no move
    let v = await view(page);
    const lineMoves = await page.evaluate((line) => [...document.querySelectorAll("#tree .mv[data-node]")]
      .filter(el => !el.classList.contains("start") && READER.nodes[el.dataset.node].line === line)
      .map(el => el.classList.contains("hid")), G.line);
    check("tree hidden", lineMoves.length >= MAIN_SAN.length && lineMoves.every(Boolean) &&
      !MAIN_SAN.some(san => v.tree.indexOf(san) >= 0), { lineMoves, tree: v.tree });
    // (each covered move keeps its number, which tells nothing of the move)
    const nums = await page.evaluate((ids) => ids.map(id => {
      const el = document.querySelector("#tree .mv.hid[data-node='" + id + "'] .mn"); return el ? el.textContent : null; }), [e4, nf3]);
    check("covered moves keep their numbers", nums[0] === "1." && nums[1] === "2.", nums);

    // on the page each printed move of the game is covered, in the paper colour, and says nothing of itself
    const cover = await page.evaluate((sel) => {
      const el = document.querySelector(sel), cs = getComputedStyle(el);
      return { title: el.title, label: el.getAttribute("aria-label"), bg: cs.backgroundColor, outline: cs.outlineStyle };
    }, markOf(nf3));
    check("page covers", cover.title === "A hidden move" && cover.label === "A hidden move" &&
      cover.bg !== "rgba(0, 0, 0, 0)" && cover.bg !== "transparent" && cover.outline === "dotted" &&
      v.hidPage.indexOf(e4) >= 0, cover);
    await shot(page, "hide_1280_light.png");
    await page.emulateMedia({ colorScheme: "dark" });
    const dark = await page.evaluate((sel) => getComputedStyle(document.querySelector(sel)).backgroundColor, markOf(nf3));
    await shot(page, "hide_1280_dark.png");
    await page.emulateMedia({ colorScheme: "light" });
    check("dark cover is the dimmed paper", dark === "rgb(214, 214, 214)", dark);

    // a move the book does not play is refused, and the covers stay
    const before = v.hidPage.length;
    await drag(page, "a2", "a3");
    await page.waitForSelector("#hmagain");
    v = await view(page);
    check("wrong move", v.id === G.root && v.open && /Your move 1\.a3/.test(v.fixText) &&
      /The book plays another move here/.test(v.fixText) && /Show the book's move/.test(v.fixText) &&
      !/Correct the book's move/.test(v.fixText) && v.hidPage.length === before &&
      await page.evaluate(() => !!document.querySelector("#board use[data-at='a3']")), v);
    await page.click("#hmagain");
    v = await view(page);
    check("try again", !v.open && v.id === G.root && v.fen === G.rootFen && await page.evaluate(() =>
      !!document.querySelector("#board use[data-at='a2']") && !document.querySelector("#board use[data-at='a3']")), v);
    // (Escape does what Try again does)
    await drag(page, "a2", "a3");
    await page.waitForSelector("#hmagain");
    await page.keyboard.press("Escape");
    v = await view(page);
    check("escape tries again", !v.open && v.id === G.root, v);

    // a book's move the program could not read: the sheet says so and names neither it nor the
    // text recognition's reading of it
    const keep = await page.evaluate((id) => {
      const n = READER.nodes[id], was = { san: n.san, status: n.status, raw: n.raw };
      n.san = null; n.status = "failed"; n.raw = "e4t";
      return was;
    }, e4);
    await drag(page, "a2", "a3");
    await page.waitForSelector("#hmagain");
    v = await view(page);
    check("an unread move stays hidden", v.open && /could not read the book's next move/.test(v.fixText) &&
      !/e4/.test(v.fixText) && /Try again/.test(v.fixText) && /Show the book's move/.test(v.fixText) &&
      !/Add a new variation/.test(v.fixText) && v.hidTree.indexOf(e4) >= 0, v);
    await page.click("#hmagain");
    await page.evaluate(([id, was]) => Object.assign(READER.nodes[id], was), [e4, keep]);

    // the book's move steps to it and uncovers it; the book's reply follows
    await drag(page, "e2", "e4");
    v = await view(page);
    check("right move", v.id === e4 && v.hidTree.indexOf(e4) < 0 && v.hidPage.indexOf(e4) < 0 &&
      v.msg === "Right: 1.e4 is the book's move.", v);
    await page.waitForFunction((id) => window.readerState.nodeId === id, e5, { timeout: 2000 });
    v = await view(page);
    // (the message names the reply, for those who do not watch the board)
    check("reply played", v.id === e5 && v.hidTree.indexOf(e5) < 0 && v.hidPage.indexOf(e5) < 0 &&
      v.hidTree.indexOf(nf3) >= 0 && v.msg === "Right: 1.e4 is the book's move. The book answers 1…e5.", v);

    // the right arrow shows the book's move; the focus stays on the move list as it does
    await page.focus("#tree .mv.cur");
    await page.keyboard.press("ArrowRight");
    v = await view(page);
    const focus = await page.evaluate(() => { const a = document.activeElement; return a.className + " " + (a.dataset.node || ""); });
    check("right arrow reveals", v.id === nf3 && v.hidTree.indexOf(nf3) < 0 && v.hidPage.indexOf(nf3) < 0 &&
      v.hidTree.indexOf(nc6) >= 0, v);
    check("focus stays in the move list", focus === "mv cur " + nf3, focus);
    await page.evaluate(() => document.activeElement.blur());

    // a new reading of the chapter (a patch from the app) keeps the moves reached, the ones after
    // the current move included
    await page.keyboard.press("ArrowLeft");
    const hidBefore = (await view(page)).hidTree.length;
    await page.evaluate(() => window.applyPatch({}));
    v = await view(page);
    check("a patch keeps the moves reached", v.id === e5 && v.hidTree.length === hidBefore && v.hidTree.indexOf(nf3) < 0,
      { hidBefore, v });
    await page.keyboard.press("ArrowRight");

    // End goes to the last move shown, not to the end of the game
    await page.click("#bstart");
    await page.click("#bend");
    v = await view(page);
    check("end stops at uncovered", v.id === nf3 && v.hidTree.indexOf(nc6) >= 0, v);

    // a click on a covered move goes to the position before it, in the move list and on the page
    await page.click("#bstart");
    await page.click("#tree .mv[data-node='" + nc6 + "']");
    v = await view(page);
    const said = "This move is hidden. Find it on the board, or use the Next move arrow under the board " +
      "(or the right arrow key) to see the book's move.";
    check("hidden click in the move list goes before", v.id === nf3 && v.msg === said && v.hidTree.indexOf(nc6) >= 0, v);
    await page.click("#bstart");
    await page.click(markOf(nc6));
    v = await view(page);
    check("hidden click goes before", v.id === nf3 && v.msg === said && v.hidPage.indexOf(nc6) >= 0, v);
    // the arrow key the message names steps the moves, though the pointer is still over the page
    const pg = v.page;
    await page.keyboard.press("ArrowRight");
    v = await view(page);
    check("the arrow after a covered box steps", v.id === nc6 && v.page === pg, v);
    await page.keyboard.press("ArrowLeft");
    await page.mouse.move(5, 5);

    // the side the reader plays, in the gear's sheet
    await page.click("#bgear");
    await page.click("#evset button[data-set='hideside'][data-value='both']");
    const side = await page.evaluate(() => ({ stored: localStorage.getItem("chessbook-hide-side"),
      checked: [...document.querySelectorAll("#evset [role=radio][aria-checked=true]")].map(b => b.textContent) }));
    check("you play", side.stored === "both" && side.checked.length === 1 && side.checked[0] === "Both sides", side);
    await page.click("#evset button[data-set='hideside'][data-value='first']");
    await page.click("#bgear");

    // a reload keeps the mode (the moves reached are covered again after the current one)
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState && window.readerState.nodeId);
    v = await view(page);
    const kept = await page.evaluate(() => ({ hiding: document.body.classList.contains("hiding"),
      pressed: document.getElementById("bhide").getAttribute("aria-pressed") }));
    check("reload keeps mode", kept.hiding && kept.pressed === "true" && v.id === nf3 && v.hidTree.indexOf(nc6) >= 0 &&
      v.hidTree.indexOf(e4) < 0 && v.hidPage.indexOf(nc6) >= 0, { kept, v });

    // a turn of the page: the next page's moves are covered too, and this page's again on the way back
    const p0 = v.page;
    await page.click("#nextpage");
    await page.waitForFunction((p0) => window.readerState.page === p0 + 1, p0);
    await page.waitForTimeout(600);
    const next = await page.evaluate(() => {
      const marks = [...document.querySelectorAll("#ov .mark[data-node]")].filter(el => READER.nodes[el.dataset.node].parent != null);
      return { all: marks.length, hid: marks.filter(el => el.classList.contains("hid")).length };
    });
    await page.click("#prevpage");
    await page.waitForFunction((p0) => window.readerState.page === p0, p0);
    await page.waitForTimeout(600);
    v = await view(page);
    check("page turn keeps covers", next.all > 0 && next.hid === next.all && v.hidPage.indexOf(nc6) >= 0 &&
      v.hidPage.indexOf(e4) < 0, { next, v });

    // the inverted page inverts the covers with it
    await page.click("#invbtn");
    const inv = await page.evaluate((sel) => ({ box: getComputedStyle(document.getElementById("pagebox")).filter,
      mark: getComputedStyle(document.querySelector(sel)).filter, bg: getComputedStyle(document.querySelector(sel)).backgroundColor }),
      markOf(nc6));
    check("inverted cover", inv.box === "invert(1)" && inv.mark === "none" && inv.bg === "rgb(255, 255, 255)", inv);
    await page.click("#invbtn");

    // the engine's moves are hidden while the mode is on
    await page.click("#bcpu");
    await page.waitForFunction(() => /Stockfish's moves are hidden while Hide next moves is on\./.test(
      document.getElementById("evlines").innerText));
    check("analysis off", await page.evaluate(() => !document.querySelector("#board .eva") &&
      !document.querySelector("#evlines .evline")));
    await page.click("#bcpu");

    // off: every move shows
    await page.click("#bhide");
    v = await view(page);
    const off = await page.evaluate(() => ({ pressed: document.getElementById("bhide").getAttribute("aria-pressed"),
      stored: localStorage.getItem("chessbook-hide"), title: document.querySelector("#ov .mark[data-node]").title }));
    check("off shows all", off.pressed === "false" && off.stored === "0" && !v.hidTree.length && !v.hidPage.length &&
      MAIN_SAN.slice(0, 6).every(san => v.tree.indexOf(san) >= 0) && off.title !== "A hidden move" &&
      v.msg === "Every move is shown.", { off, v });
    await ctx.close();

    // ---------------------------------------------------------------- iPhone 13
    const phone = await browser.newContext({ ...devices["iPhone 13"] });
    const pp = await phone.newPage();
    watch(pp);
    await pp.goto(url);
    await pp.waitForFunction(() => window.READER && window.readerState);
    await pp.evaluate(() => localStorage.clear());
    await pp.goto(url + "#line=" + G.line);
    await pp.reload();
    await pp.waitForFunction((r) => window.readerState.nodeId === r, G.root);
    await pp.tap("#mhide");
    const ph = await pp.evaluate(() => ({ pressed: document.getElementById("mhide").getAttribute("aria-pressed"),
      hid: document.querySelectorAll("#ov .mark.hid").length, sw: document.documentElement.scrollWidth, w: window.innerWidth }));
    check("phone button", ph.pressed === "true" && ph.hid > 0 && ph.sw <= ph.w, ph);
    // the bar's current move has room for an ordinary move
    const fits = await pp.evaluate(() => {
      const el = document.getElementById("mtxt");
      el.innerHTML = "<span class=n>23…Qxf7+</span>";
      return { sw: el.scrollWidth, cw: el.clientWidth };
    });
    check("the current move fits the bar", fits.sw <= fits.cw, fits);
    await shot(pp, "hide_390_light.png");
    await phone.close();

    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (err) {
    out.failure = String(err && err.message ? err.message : err);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
