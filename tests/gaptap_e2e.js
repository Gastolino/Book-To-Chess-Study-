// End-to-end test of a tap on a move after a gap in the text, in the browser app
// (tools/build_web.py), in Chromium, with Python running through Pyodide in the page's worker
// (chessbook/review_js.py, "the thread", and driver.read_on).
//
// Usage:
//   NODE_PATH=/opt/node22/lib/node_modules node tests/gaptap_e2e.js SITE_URL BOOK_PDF SCREENS_DIR
//
// BOOK_PDF is the generated book of tests/test_read_on.py made with make_long(lacking=True): the game's
// own text prints "5.Qc1" and goes on with "6.c4 Bh6 7.e3 f4" on the next page, lacking 5...f5 (a gap
// in the line), so that the position of 6.c4 and of the moves after it is unknown. On an iPad held
// sideways, the test:
//   - taps 6...Bh6, a move after the gap: the thread asks for the move the text lacks, as for any
//     other box ("Black's 5th move is missing before 6.c4.", with Play f5), with 6.c4 outlined and the board, on
//     the position after 5.Qc1, taking a move; the gap's own editor is under More;
//   - taps 6.c4 and makes 5...f5 on the board: the move is stored as the gap's ("gaps") and the
//     program reads on from it by itself, joining the game through 12.d6, and the sheet asks for
//     Black's 12th move, which the text lacks too.
// Prints one JSON object {ok, checks, errors, screenshots, timings}; the exit code is 1 when a check
// fails.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const [siteUrl, bookPdf, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], screenshots: [], timings: {} };
function check(name, cond, detail) {
  out.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed: " + name + (detail !== undefined ? " (" + JSON.stringify(detail).slice(0, 800) + ")" : ""));
}
const GAME = ("d4 Nf6 Bg5 c5 Bxf6 gxf6 d5 Qb6 Qc1 f5 c4 Bh6 e3 f4 exf4 Bxf4 Qxf4 Qxb2 Ne2 Qxa1 Nc3 Qb2 d6 Qc2 " +
  "Qe3").split(" ");

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1194, height: 834 }, hasTouch: true });
  const page = await ctx.newPage();
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource: the server responded with a status of 404/.test(m.text()))
      out.errors.push(m.text());
  });
  page.on("pageerror", (e) => out.errors.push(String(e)));
  fs.mkdirSync(screens, { recursive: true });
  const shot = async (name) => {
    const p = path.join(screens, name + ".png");
    await page.screenshot({ path: p });
    out.screenshots.push(p);
  };
  const frame = async () => (await page.$("#view")).contentFrame();
  const inFrame = async (fn, arg) => {
    for (let i = 0; ; i++) {
      try { return await (await frame()).evaluate(fn, arg); }
      catch (e) { if (i > 40) throw e; await page.waitForTimeout(250); }
    }
  };
  const waitFrame = async (fn, arg, timeout) => {
    const t0 = Date.now();
    for (;;) {
      let v = null;
      try { v = await (await frame()).evaluate(fn, arg); } catch (e) { v = null; }
      if (v) return v;
      if (Date.now() - t0 > (timeout || 120000)) {
        const sheet = await inFrame(() => document.getElementById("fix").innerText).catch(() => "");
        throw new Error("timed out waiting in the reader: " + fn.toString().slice(0, 200) + " | sheet: " + sheet);
      }
      await page.waitForTimeout(100);
    }
  };
  const tapIn = async (sel) => {
    const el = await (await frame()).$(sel);
    if (!el) throw new Error("nothing at " + sel);
    await el.scrollIntoViewIfNeeded();
    await el.tap();
  };
  const sheet = () => inFrame(() => { const f = document.getElementById("fix");
    return f.hidden ? null : { note: (f.querySelector(".thr") || { innerText: "" }).innerText.trim(),
      line: (f.querySelector(".thl") || f).innerText.trim(),
      head: (f.querySelector("h3") || { innerText: "" }).innerText.trim(),
      msg: (f.querySelector("#fixmsg") || { innerText: "" }).innerText.trim(),
      buttons: [...f.querySelectorAll("button")].map((b) => b.textContent.trim()) }; });
  const lineIs = (re) => waitFrame((src) => { const l = document.querySelector("#fix .thl");
    return l && new RegExp(src).test(l.innerText); }, re.source, 180000);
  // a move on the board: a tap on the piece, then on its square (the board the window shows)
  const play = async (from, to) => {
    for (const sq of [from, to]) {
      const xy = await inFrame((sq) => {
        const svg = [document.querySelector("#minibox svg.board"), document.querySelector("#board svg.board")]
          .find((s) => s && s.getBoundingClientRect().width > 0);
        const r = svg.getBoundingClientRect(), flip = svg.dataset.flip === "1";
        const f = "abcdefgh".indexOf(sq[0]), row = 8 - parseInt(sq[1], 10);
        const c = flip ? 7 - f : f, rr = flip ? 7 - row : row, k = r.width / 375;
        return [r.left + (14 + (c + 0.5) * 45) * k, r.top + (1 + (rr + 0.5) * 45) * k];
      }, sq);
      const box = await (await page.$("#view")).boundingBox();
      await page.touchscreen.tap(box.x + xy[0], box.y + xy[1]);
      await page.waitForTimeout(150);
    }
  };
  // the board the window shows: does it take a move, and from which position
  const board = () => inFrame(() => {
    const svg = [document.querySelector("#minibox svg.board"), document.querySelector("#board svg.board")]
      .find((s) => s && s.getBoundingClientRect().width > 0);
    const at = (sq) => svg ? svg.querySelector("use[data-at='" + sq + "']") : null;
    return { movable: !!svg && svg.classList.contains("movable"),
      mine: svg ? svg.querySelectorAll("use[data-mine]").length : 0,
      f6: !!at("f6") && at("f6").hasAttribute("data-mine"), c1: !!at("c1"), d1: !!at("d1") };
  });
  const fix = () => inFrame(() => JSON.parse(window.correctionsText()));
  const keyOf = (raw) => inFrame((raw) => { for (const p in READER.pages) for (const m of READER.pages[p].marks)
    if (m.raw === raw) return m.key; return null; }, raw);
  const markSel = (key) => inFrame((key) => {
    const i = READER.pages[readerState.page].marks.findIndex((m) => m.key === key);
    return i >= 0 ? "#ov .mark[data-mark='" + i + "']" : null; }, key);
  const outlined = () => inFrame(() => { const el = document.querySelector("#ov .mark.seqcur");
    return el ? READER.pages[readerState.page].marks[+el.dataset.mark].key : null; });
  let d4Key = null;
  const gameNow = () => inFrame((k) => {
    const D = READER, id = Object.keys(D.nodes).find((x) => D.nodes[x].key === k);
    if (!id) return null;
    const out = [];
    for (let cur = D.lines[D.nodes[id].line].root; ;) {
      const c = D.nodes[cur].children.find((x) => D.nodes[x].main);
      if (!c) break;
      out.push(D.nodes[c].san || "?");
      cur = c;
    }
    return out;
  }, d4Key);

  try {
    let t0 = Date.now();
    await page.goto(siteUrl);
    await page.waitForFunction(() => /Ready/.test(document.getElementById("status").textContent), null, { timeout: 300000 });
    await page.setInputFiles("#file", bookPdf);
    await page.waitForSelector("#view", { state: "visible", timeout: 1800000 });
    await page.waitForFunction(() => document.body.dataset.book === "read", null, { timeout: 1800000 });
    out.timings["book read (s)"] = (Date.now() - t0) / 1000;
    await page.waitForTimeout(1000);
    // (6.c4 and the moves after it are printed on page 5)
    await inFrame(() => { location.hash = "#page=5"; });
    await waitFrame(() => window.READER && window.readerState && window.readerState.page === 5 &&
      READER.pages[5].marks.some((m) => m.raw === "Bh6"), null, 300000);
    d4Key = await keyOf("d4");
    const c4 = await keyOf("c4"), bh6 = await keyOf("Bh6"), qe3 = await keyOf("Qe3");
    const g0 = await gameNow();
    check("the generated book reads to 5.Qc1, and the text lacks 5...f5",
          JSON.stringify(g0.slice(0, 9)) === JSON.stringify(GAME.slice(0, 9)) && g0[9] === "?" &&
          await inFrame((k) => { const n = Object.values(READER.nodes).find((x) => x.gap && !x.san); return !!n && n.gap === k; }, c4),
          g0);

    // ---------------------------------------------------------------- a move after the gap
    await tapIn("#showread");
    await tapIn(await markSel(bh6));
    // (the worker names the box after the gap, and offers the move it is sure of)
    await lineIs(/is missing before 6\.c4/);
    let s = await sheet(), b = await board();
    check("a tap on a move after the gap asks for the move the text lacks, as the thread does",
          s.line === "Black's 5th move is missing before 6.c4." && s.buttons[0] === "Play f5" && s.buttons.indexOf("More") >= 0 &&
          s.buttons.indexOf("Cancel") >= 0 && await outlined() === c4, { s, outlined: await outlined() });
    check("the board takes Black's move, from the position after 5.Qc1", b.movable && b.mine > 0 && b.f6 && b.c1 &&
          !b.d1, b);
    await shot("gaptap_0_after_gap");
    await tapIn("#thmore");
    s = await sheet();
    check("More opens the gap's own editor", /Give Black's move 5/.test(s.head), s);
    await tapIn("#fixclose");

    // ---------------------------------------------------------------- 6.c4, then 5...f5 on the board
    // (the messages the reader sends the app's worker)
    await page.evaluate(() => {
      const post = worker.postMessage.bind(worker);
      window.__sent = [];
      worker.postMessage = (m, t) => { if (m && m.type) window.__sent.push(m.type); return post(m, t); };
    });
    await tapIn(await markSel(c4));
    await lineIs(/is missing before 6\.c4/);
    t0 = Date.now();
    await play("f6", "f5");
    await lineIs(/is missing before 13|reads to its end/);
    out.timings["f5 made until the program has read on (s)"] = (Date.now() - t0) / 1000;
    s = await sheet();
    const f = await fix();
    check("the move made is stored as the gap's", f.gaps[c4] && JSON.stringify(f.gaps[c4].san) === '["f5"]', f.gaps);
    // (the moves after the gap stand in the line already: the gap's move reads them, and the program
    // reads on from there to where the text lacks a move again)
    const sent = await page.evaluate(() => window.__sent);
    check("the program read on from the gap by itself, through 12.d6",
          sent.indexOf("readOn") >= 0 && sent.indexOf("correct") < 0 &&
          s.line === "Black's 12th move is missing before 13.Qe3. Play it on the board." &&
          JSON.stringify(await gameNow()) === JSON.stringify(GAME.slice(0, 23)) && await outlined() === qe3,
          { sent, line: s.line, game: (await gameNow()).join(" "), outlined: await outlined() });
    check("the move made can be undone", s.buttons.some((x) => /^Undo/.test(x)), s.buttons);
    await shot("gaptap_1_read_on");
    out.ok = true;
  } catch (e) {
    out.failure = String(e && e.stack || e);
    await shot("gaptap_failure").catch(() => null);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
