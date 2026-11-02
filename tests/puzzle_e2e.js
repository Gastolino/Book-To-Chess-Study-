// End-to-end test of puzzle mode, in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/puzzle_e2e.js READER_DIR SCREENS_DIR
//
// READER_DIR holds the reader of the puzzle book of tests/test_puzzles.py: ten puzzles in its first
// chapter (ch01.html, pages 3 to 5), their solutions in the second (ch02.html, page 6). The first
// chapter asks whether the book is a puzzle book; the answer is stored and the question does not
// come again. In the chapter of solutions the moves of the solutions are covered on the page (their
// boxes name no move) and in the move list. A tap on a puzzle's diagram stays on its page and opens
// the puzzle under the board; an answer played on the board and noted is checked against the book's
// solution: 1.h3 for puzzle 1 differs, 1.Rd7 is the book's side line, 1.Ra8# for puzzle 2 matches,
// and the answer to puzzle 9 (a solution in words) is marked by the reader. My answers lists the
// puzzles and the tally; the answers outlast a reload; the solution of a checked puzzle shows; the
// contents page gives the tally of the book; the switch turns the mode off and the covers go.
// The review of the mode: the question's two answers stay on one line; in the chapter of solutions
// the solution in words is covered too, a covered move offers to open its puzzle, My answers lists
// the puzzles solved there and leaves when a move is chosen, and the arrow stays on the page; the
// engine's arrow is off with Stockfish on; an answer in progress outlasts a second tap and a
// reload; the focus stays on the button pressed; an answer that leaves the solution after its
// first move partly matches and says where; turning the mode off with a puzzle open leaves it. On
// an iPhone 13 the page does not scroll sideways and the bar names the puzzle whole, nor on a
// 360px phone. Screenshots in the light and dark schemes, on a
// desktop and on the phone. Prints one JSON object; the exit code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [dir, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], screenshots: [] };
function check(name, cond, detail) {
  out.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed: " + name + (detail ? " (" + JSON.stringify(detail) + ")" : ""));
}
const KEY_PREFIX = "chessbook-puzzles:";

(async () => {
  const browser = await chromium.launch();
  const url = (name) => "file://" + path.resolve(dir, name);
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
  const at = (page, sq) => page.evaluate((sq) => {
    const svg = document.querySelector("#board svg.board");
    const r = svg.getBoundingClientRect(), flip = svg.dataset.flip === "1";
    const f = "abcdefgh".indexOf(sq[0]), row = 8 - parseInt(sq[1], 10);
    const c = flip ? 7 - f : f, rr = flip ? 7 - row : row;
    const k = r.width / 375;
    return [r.left + (14 + (c + 0.5) * 45) * k, r.top + (1 + (rr + 0.5) * 45) * k];
  }, sq);
  const drag = async (page, from, to) => {
    await page.locator("#board svg.board").scrollIntoViewIfNeeded();
    let [x, y] = await at(page, from);
    await page.mouse.move(x, y);
    await page.mouse.down();
    [x, y] = await at(page, to);
    await page.mouse.move(x, y, { steps: 6 });
    await page.mouse.up();
  };
  const stored = (page) => page.evaluate((pre) => {
    const k = Object.keys(localStorage).find(x => x.indexOf(pre) === 0);
    return k ? JSON.parse(localStorage.getItem(k)) : null;
  }, KEY_PREFIX);
  const panel = (page) => page.evaluate(() => {
    const p = document.getElementById("dpanel");
    return { shown: !p.hidden, text: p.innerText, page: window.readerState.page, puzzle: window.readerState.puzzle || null,
      fen: window.readerState.fen, msg: document.getElementById("pagemsg").textContent };
  });
  const openPuzzle = async (page, id) => {
    await page.click("#ov .diag[data-diagram='" + id + "']");
    await page.waitForFunction((id) => window.readerState.puzzle === id, id);
  };
  const noteAndCheck = async (page) => {
    await page.click("#pznote");
    const noted = await panel(page);
    await page.click("#pzcheck");
    return [noted, await panel(page)];
  };
  // every SAN of the solutions, as the printed words show them
  const SOLUTION_SAN = ["Rd8+", "Kh7", "Rd7", "Ra8#"];
  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    watch(page);
    await page.goto(url("ch01.html"));
    await page.waitForFunction(() => window.READER && window.readerState);
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState);

    // the question to a likely puzzle book, once; the answer is stored
    const ask = await page.evaluate(() => ({ text: document.getElementById("pzask").innerText,
      shown: getComputedStyle(document.getElementById("pzask")).display !== "none",
      toggle: !document.getElementById("bpuzzle").hidden, on: document.body.classList.contains("puzzling") }));
    check("prompt shows", ask.shown && ask.text.indexOf("In this book 9 of 10 diagrams have their solutions on later pages.") === 0 &&
      ask.text.indexOf("Do you want to work them as puzzles?") > 0 && ask.toggle && !ask.on, ask);
    const tops = await page.evaluate(() => ["pzyes", "pzno"].map(id => Math.round(document.getElementById(id).getBoundingClientRect().top)));
    check("the two answers on one line", tops[0] === tops[1], tops);
    await page.click("#pzyes");
    let st = await stored(page);
    const on = await page.evaluate(() => ({ on: document.body.classList.contains("puzzling"),
      pressed: document.getElementById("bpuzzle").getAttribute("aria-pressed"), ask: document.getElementById("pzask").innerText,
      answers: !document.getElementById("pzbtn").hidden }));
    check("prompt answer stored", st && st.mode === "puzzles" && on.on && on.pressed === "true" && !on.ask && on.answers, { st, on });
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState);
    const again = await page.evaluate(() => ({ ask: document.getElementById("pzask").innerText,
      on: document.body.classList.contains("puzzling") }));
    check("prompt shows once", !again.ask && again.on, again);

    // the chapter of solutions: the solutions' moves are covered, on the page and in the move list
    await page.goto(url("ch02.html"));
    await page.waitForFunction(() => window.READER && window.readerState);
    const cover = await page.evaluate(() => {
      const hid = [...document.querySelectorAll("#ov .mark.hid")];
      return { n: hid.length, labels: hid.map(el => (el.getAttribute("aria-label") || "") + "|" + (el.title || "")),
        bg: hid.length ? getComputedStyle(hid[0]).backgroundColor : null, tree: document.getElementById("tree").innerText,
        treeHid: document.querySelectorAll("#tree .mv.hid").length, sol: Object.keys(READER.solNodes).length };
    });
    check("solution covered on the page", cover.n >= 8 && cover.labels.every(l => !SOLUTION_SAN.some(s => l.indexOf(s) >= 0)) &&
      cover.bg && cover.bg !== "rgba(0, 0, 0, 0)", cover);
    check("no solution SAN in the tree", cover.treeHid > 0 && !SOLUTION_SAN.some(s => cover.tree.indexOf(s) >= 0), cover);
    // a tap on a covered move names the puzzle and chooses no move
    const firstHid = await page.evaluate(() => document.querySelector("#ov .mark.hid").dataset.node);
    await page.click("#ov .mark[data-node='" + firstHid + "']");
    const tapped = await panel(page);
    check("covered move says why", tapped.msg.indexOf("the book's solution to puzzle") > 0 &&
      (await page.evaluate(() => window.readerState.nodeId)) !== firstHid, tapped);
    // the solution in words is covered as the moves are, and says nothing of itself
    const note = await page.evaluate(() => {
      const el = document.querySelector("#ov .mark[data-seq='6:50,272:Nf6+']");
      return el ? { hid: el.classList.contains("hid"), title: el.title, label: el.getAttribute("aria-label") } : null;
    });
    check("solution in words covered", note && note.hid && note.title === "A hidden move" && note.label === "A hidden move", note);
    // the arrow reads on through the page of solutions: the page stays
    await page.mouse.move(5, 5);
    await page.keyboard.press("ArrowRight");
    check("the arrow stays on the page of solutions", (await page.evaluate(() => window.readerState.page)) === 6);
    // My answers lists the puzzles that the chapter solves, each with its page
    await page.click("#pzbtn");
    const sols = await page.evaluate(() => ({ text: document.getElementById("pzsec").innerText,
      rows: document.querySelectorAll("#pzsec .pzrows li").length }));
    check("my answers in the chapter of solutions", sols.text.indexOf("Solutions on these pages") >= 0 && sols.rows === 9 &&
      sols.text.indexOf("Puzzle 9") >= 0, sols);
    await page.click("#pzlclose");
    // the message's button opens the puzzle in the chapter that prints it
    await page.click("#ov .mark[data-node='" + firstHid + "']");
    const go = await page.evaluate(() => (document.querySelector("#pagemsg [data-pzgo]") || {}).textContent || null);
    check("a covered move offers its puzzle", /^Open puzzle \d+$/.test(go || ""), go);
    const want = await page.evaluate(() => document.querySelector("#pagemsg [data-pzgo]").dataset.pzgo);
    await page.click("#pagemsg [data-pzgo]");
    await page.waitForFunction((id) => window.READER && window.readerState && window.readerState.puzzle === id, want);
    check("the puzzle opens in its chapter", /ch01\.html/.test(page.url()), page.url());

    // a puzzle's diagram stays on its page and opens the puzzle
    await page.goto(url("ch01.html"));
    await page.waitForFunction(() => window.READER && window.readerState && window.readerState.page === 3);
    await openPuzzle(page, "p3-1");
    let pv = await panel(page);
    check("diagram opens the puzzle", pv.shown && pv.page === 3 && /^Puzzle 1, page /.test(pv.text) &&
      pv.text.indexOf("White to play.") >= 0 && pv.text.indexOf("Note this answer") >= 0 &&
      pv.text.indexOf("Check my answer") < 0 && pv.fen === "6k1/5pp1/7p/8/8/8/5PPP/3R2K1 w - - 0 1", pv);
    // the engine's arrow and lines are off while a puzzle is open, with Stockfish on
    await page.click("#bcpu");
    await page.waitForFunction(() => /Stockfish's moves are hidden while a puzzle is open\./.test(
      document.getElementById("evlines").innerText), null, { timeout: 60000 });
    await page.waitForTimeout(1500);
    check("engine arrow off", await page.evaluate(() => !document.querySelector("#board .eva") &&
      window.readerState.puzzle === "p3-1"));
    await page.click("#bcpu");

    // a wrong answer differs from the book
    await drag(page, "h2", "h3");
    pv = await panel(page);
    check("move noted on the board", pv.text.indexOf("1.h3") >= 0 && pv.fen.indexOf(" b ") > 0, pv);
    // the answer in progress outlasts a second tap on the diagram, and a reload
    await openPuzzle(page, "p3-1");
    pv = await panel(page);
    check("a second tap keeps the answer", pv.text.indexOf("1.h3") >= 0 && pv.fen.indexOf(" b ") > 0, pv);
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState && window.readerState.puzzle === "p3-1");
    pv = await panel(page);
    check("a reload keeps the answer", pv.text.indexOf("1.h3") >= 0 && pv.fen.indexOf(" b ") > 0, pv);
    check("forward arrows off in a puzzle", await page.evaluate(() =>
      document.getElementById("bfwd").getAttribute("aria-disabled") === "true"));
    let [noted, checked] = await noteAndCheck(page);
    check("note says noted", noted.text.indexOf("Your answer 1.h3 is noted. The book's solution stays hidden.") >= 0, noted);
    check("wrong answer differs", checked.text.indexOf("The book plays 1.Rd8+. You noted 1.h3.") >= 0 &&
      checked.text.indexOf("Differs") >= 0, checked);
    // again, with the book's side line; the button pressed keeps the focus
    await page.focus("#pzagain");
    await page.keyboard.press("Enter");
    check("the focus stays on the button pressed", (await page.evaluate(() => document.activeElement.id)) === "pzagain");
    await drag(page, "d1", "d7");
    [noted, checked] = await noteAndCheck(page);
    check("side line", checked.text.indexOf("The book gives 1.Rd7 as a side line and plays 1.Rd8+.") >= 0 &&
      checked.text.indexOf("Side line") >= 0, checked);
    st = await stored(page);
    check("tries counted", st.answers["p3-1"].tries === 2 && st.answers["p3-1"].check === "alt" &&
      st.answers["p3-1"].moves[0][1] === "d1d7", st.answers["p3-1"]);
    // the solution of a checked puzzle, in another chapter: its moves and a link to its page
    await page.click("#pzsol");
    pv = await panel(page);
    check("solution shown", pv.text.indexOf("1.Rd8+ Kh7 2.Rd7") >= 0 &&
      (await page.evaluate(() => !!document.querySelector("#pzres a[data-page='6']"))), pv);

    // a right answer matches
    await openPuzzle(page, "p3-2");
    await drag(page, "a1", "a8");
    [noted, checked] = await noteAndCheck(page);
    check("right answer matches", checked.text.indexOf("Your first move matches the book.") >= 0 &&
      checked.text.indexOf("Matches") >= 0, checked);
    await shot(page, "puzzle_1280_light.png");
    await page.emulateMedia({ colorScheme: "dark" });
    await shot(page, "puzzle_1280_dark.png");
    await page.emulateMedia({ colorScheme: "light" });

    // My answers: a row for each puzzle, and the tally
    await page.click("#pzbtn");
    const list = await page.evaluate(() => ({ shown: !document.getElementById("pzsec").hidden,
      text: document.getElementById("pzsec").innerText, rows: document.querySelectorAll("#pzsec .pzrows li").length,
      tally: (document.getElementById("pztally") || {}).textContent }));
    check("my answers list", list.shown && list.rows === 10 && list.text.indexOf("Side line") >= 0 &&
      list.text.indexOf("Matches") >= 0 && list.text.indexOf("Not tried") >= 0 && list.text.indexOf("No solution") >= 0, list);
    check("tally", list.tally === "You noted 2 answers for the 10 puzzles in this chapter. 1 of 2 match the book. " +
      "The program found no solution for one puzzle.", list.tally);

    // a solution in words: the reader marks the answer
    await page.click("#pzsec [data-pzopen='p5-1']");
    await page.waitForFunction(() => window.readerState.puzzle === "p5-1" && window.readerState.page === 5);
    await drag(page, "g5", "h7");
    [noted, checked] = await noteAndCheck(page);
    check("note solution asks", checked.text.indexOf("9. Nf6+") >= 0 && checked.text.indexOf("Was your answer right?") >= 0, checked);
    await page.click("#pzres [data-pzown='1']");
    st = await stored(page);
    check("own mark stored", st.answers["p5-1"].check === "own-right", st.answers["p5-1"]);
    // Check all my answers: puzzle 3 noted in full, not yet checked
    await page.click("#pzsec [data-pzopen='p3-3']");
    await page.waitForFunction(() => window.readerState.puzzle === "p3-3" && window.readerState.page === 3);
    await drag(page, "d1", "d8");
    await drag(page, "g8", "h7");
    await drag(page, "d8", "d7");
    await page.click("#pznote");
    await page.click("#pzall");
    st = await stored(page);
    const tally2 = await page.evaluate(() => (document.getElementById("pztally") || {}).textContent);
    check("check all", st.answers["p3-3"].check === "right" && st.answers["p3-3"].moves.length === 3 &&
      tally2.indexOf("3 of 4 match the book.") > 0, { a: st.answers["p3-3"], tally2 });

    // the answers outlast a reload
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState);
    await page.click("#pzbtn");
    const after = await page.evaluate(() => (document.getElementById("pztally") || {}).textContent);
    check("answers survive reload", after === tally2, { after, tally2 });

    // the chapter of solutions: the checked puzzles' solutions show, the others stay covered
    await page.goto(url("ch02.html"));
    await page.waitForFunction(() => window.READER && window.readerState);
    const part = await page.evaluate(() => {
      const hid = new Set([...document.querySelectorAll("#ov .mark.hid")].map(el => el.dataset.node));
      const of = (did) => Object.keys(READER.solNodes).filter(n => READER.solNodes[n] === did);
      return { p1: of("p3-1").filter(n => hid.has(n)).length, p4: of("p3-4").filter(n => hid.has(n)).length, n4: of("p3-4").length };
    });
    check("checked solutions uncovered", part.p1 === 0 && part.p4 === part.n4 && part.n4 > 0, part);
    // a move chosen while My answers is open brings the move list back
    await page.click("#pzbtn");
    const shownMove = await page.evaluate(() => Object.keys(READER.solNodes).find(n => READER.solNodes[n] === "p3-1" &&
      document.querySelector("#ov .mark[data-node='" + n + "']:not(.hid)")));
    await page.click("#ov .mark[data-node='" + shownMove + "']");
    const back = await page.evaluate(() => ({ list: !document.getElementById("pzsec").hidden,
      tree: getComputedStyle(document.querySelector(".treesec")).display, node: window.readerState.nodeId }));
    check("a move chosen closes my answers", !back.list && back.tree !== "none" && back.node === shownMove, back);

    // the contents page: the tally of the whole book
    await page.goto(url("index.html"));
    const idx = await page.evaluate(() => ({ text: document.getElementById("pzline").innerText,
      pressed: (document.getElementById("pztoggle") || {}).getAttribute && document.getElementById("pztoggle").getAttribute("aria-pressed") }));
    check("index tally", idx.pressed === "true" && idx.text.indexOf("You noted 4 answers for the 10 puzzles in this book. 3 of 4 match the book.") >= 0, idx);

    // the switch turns the mode off: the answers stay, the covers go
    await page.goto(url("ch02.html"));
    await page.waitForFunction(() => window.READER && window.readerState);
    await page.click("#bpuzzle");
    st = await stored(page);
    const offv = await page.evaluate(() => ({ on: document.body.classList.contains("puzzling"),
      pressed: document.getElementById("bpuzzle").getAttribute("aria-pressed"), hid: document.querySelectorAll("#ov .mark.hid").length,
      answersBtn: !document.getElementById("pzbtn").hidden }));
    check("toggle turns the mode off", st.mode === "book" && Object.keys(st.answers).length === 4 && !offv.on &&
      offv.pressed === "false" && offv.hid === 0 && !offv.answersBtn, { st, offv });

    // an answer that leaves the book's solution after its first moves partly matches, and says where
    await page.click("#bpuzzle");
    await page.goto(url("ch01.html#page=4"));
    await page.waitForFunction(() => window.READER && window.readerState && window.readerState.page === 4);
    await openPuzzle(page, "p4-1");
    await drag(page, "d1", "d8");
    await drag(page, "g8", "h7");
    await drag(page, "h2", "h3");
    [noted, checked] = await noteAndCheck(page);
    st = await stored(page);
    check("partly matches", checked.text.indexOf("Your first 2 moves match the book. Your move 2.h3 differs: the book plays 2.Rd7.") >= 0 &&
      checked.text.indexOf("Partly matches") >= 0 && st.answers["p4-1"].check === "part", { checked, a: st.answers["p4-1"] });
    // turning the mode off with the puzzle open leaves the puzzle: the board, the bar and the state
    await page.click("#bpuzzle");
    const closed = await page.evaluate(() => ({ puzzle: window.readerState.puzzle || null, panel: !document.getElementById("dpanel").hidden,
      bar: document.getElementById("mtxt").textContent }));
    check("off with a puzzle open", !closed.puzzle && !closed.panel && closed.bar.indexOf("Puzzle") < 0, closed);
    await ctx.close();

    // ---------------------------------------------------------------- a 360px phone
    {
      const narrow = await browser.newContext({ viewport: { width: 360, height: 664 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
      const np = await narrow.newPage();
      watch(np);
      await np.goto(url("ch01.html"));
      await np.waitForFunction(() => window.READER && window.readerState);
      const w = await np.evaluate(() => ({ sw: document.documentElement.scrollWidth, vw: window.visualViewport.width,
        controls: Math.round(document.querySelector(".controls").getBoundingClientRect().right) }));
      check("no sideways scroll at 360px", w.sw <= 360 && w.controls <= 360, w);
      await narrow.close();
    }

    // ---------------------------------------------------------------- iPhone 13
    for (const scheme of ["light", "dark"]) {
      const phone = await browser.newContext({ ...devices["iPhone 13"], colorScheme: scheme });
      const pp = await phone.newPage();
      watch(pp);
      await pp.goto(url("ch01.html"));
      await pp.waitForFunction(() => window.READER && window.readerState);
      await pp.evaluate(() => localStorage.clear());
      await pp.reload();
      await pp.waitForFunction(() => window.READER && window.readerState);
      await pp.tap("#pzyes");
      await pp.tap("#ov .diag[data-diagram='p3-2']");
      await pp.waitForFunction(() => window.readerState.puzzle === "p3-2");
      const ph = await pp.evaluate(() => ({ sw: document.documentElement.scrollWidth, w: window.innerWidth,
        mp: !document.getElementById("mpuzzle").hidden && document.getElementById("mpuzzle").getAttribute("aria-pressed"),
        panel: !document.getElementById("dpanel").hidden, bar: document.getElementById("mtxt").textContent,
        fits: document.getElementById("mtxt").scrollWidth <= document.getElementById("mtxt").clientWidth }));
      check("phone " + scheme, ph.sw <= ph.w && ph.mp === "true" && ph.panel && ph.bar === "Puzzle 2" && ph.fits, ph);
      await pp.locator("#dpanel").scrollIntoViewIfNeeded();
      await shot(pp, "puzzle_390_" + scheme + ".png");
      await phone.close();
    }

    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (err) {
    out.failure = String(err && err.message ? err.message : err);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
