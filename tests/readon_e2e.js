// End-to-end test of reading on where the program needs the reader, in the browser app
// (tools/build_web.py), in Chromium, with Python running through Pyodide in the page's worker
// (chessbook/review_js.py, "the thread", and driver.read_on).
//
// Usage:
//   NODE_PATH=/opt/node22/lib/node_modules node tests/readon_e2e.js SITE_URL BOOK_PDF SCREENS_DIR
//
// BOOK_PDF is the generated book of tests/test_read_on.py (make_long): tests/test_thread.py's
// Wells - Shirov book carried to the end of the game, "10.Ne2 Qxa1 11.Nc3 Qb2", "12.d6", a diagram
// and "13.Qe3 1-0" on page 6; the text lacks 12...Qc2, and the app reads no position from the
// diagram's picture. On an iPad held sideways, in the dark scheme, the test:
//   - has the worker fail the first reading on: the sheet says "Not read on: <why>.", the correction
//     stays as the reader made it and is applied without reading on, and the sheet asks for Black's
//     5th move, offering f5 (Part C's step); Undo takes the move back;
//   - turns reading on, taps the "'it'et" box and makes 5.Qc1 on the board: the program reads on
//     by itself, supplies 5...f5 and joins the game through 12.d6, and stops where Black's 12th move
//     is missing: the sheet says "Read on to page 6: 14 moves joined." and "Black's 12th move is
//     missing before 13.Qe3. Play it on the board." (no Play: the program is not sure of a move),
//     the page turned forward to 13.Qe3, which is outlined;
//   - makes 12...Qc2 on the board: the sheet offers "Next: 13.Qe3" to join; Join stores the join
//     with Qc2 before it (the reader's) and reads on: the line holds the whole game, and the sheet
//     says that it reads to its end.
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
  const ctx = await browser.newContext({ viewport: { width: 1194, height: 834 }, hasTouch: true, colorScheme: "dark" });
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
  // (the offer in a sheet's first place waits a moment after the sheet changes)
  const tapOffer = async (sel) => { await page.waitForTimeout(450); await tapIn(sel); };
  const sheet = () => inFrame(() => { const f = document.getElementById("fix");
    return f.hidden ? null : { note: (f.querySelector(".thr") || { innerText: "" }).innerText.trim(),
      line: (f.querySelector(".thl") || f).innerText.trim(),
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
  const fix = () => inFrame(() => JSON.parse(window.correctionsText()));
  const keyOf = (raw) => inFrame((raw) => { for (const p in READER.pages) for (const m of READER.pages[p].marks)
    if (m.raw === raw) return m.key; return null; }, raw);
  const markSel = (key) => inFrame((key) => {
    const i = READER.pages[readerState.page].marks.findIndex((m) => m.key === key);
    return i >= 0 ? "#ov .mark[data-mark='" + i + "']" : null; }, key);
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
    let t0 = Date.now(), s0 = null;
    await page.goto(siteUrl);
    await page.waitForFunction(() => /Ready/.test(document.getElementById("status").textContent), null, { timeout: 300000 });
    await page.setInputFiles("#file", bookPdf);
    await page.waitForSelector("#view", { state: "visible", timeout: 1800000 });
    await page.waitForFunction(() => document.body.dataset.book === "read", null, { timeout: 1800000 });
    out.timings["book read (s)"] = (Date.now() - t0) / 1000;
    await page.waitForTimeout(1000);
    await inFrame(() => { location.hash = "#page=4"; });
    await waitFrame(() => window.READER && window.readerState && window.readerState.page === 4 &&
      Object.values(READER.pages[4].marks).some((m) => m.raw === "'it'et"), null, 300000);
    d4Key = await keyOf("d4");
    const itet = await keyOf("'it'et"), qe3 = await keyOf("Qe3"), d6 = await keyOf("d6");
    check("the generated book reads to 4...Qb6", JSON.stringify(await gameNow()) === JSON.stringify(GAME.slice(0, 8)),
          await gameNow());

    // ---------------------------------------------------------------- a reading on that fails
    // (the worker answers the first {readOn} with an error, as when it runs out of memory)
    await page.evaluate(() => {
      const post = worker.postMessage.bind(worker);
      worker.postMessage = (m, t) => {
        if (m && m.type === "readOn" && !window.__failedOnce) {
          window.__failedOnce = true;
          setTimeout(() => worker.onmessage({ data: { type: "error", during: "readOn", id: m.id,
            text: "the browser ran out of memory" } }), 300);
          return undefined;
        }
        return post(m, t);
      };
    });
    await tapIn("#showread");
    await tapIn(await markSel(itet));
    await play("d1", "c1");
    await lineIs(/is missing/);
    s0 = await sheet();
    const f0 = await fix();
    check("a reading on that fails says why in one line, keeps the correction as made, and goes on without reading on",
          s0.msg === "Not read on: the browser ran out of memory." && f0.moves[itet] && f0.moves[itet].san === "Qc1" &&
          JSON.stringify(f0.connect[itet]) === JSON.stringify({ after: await keyOf("Qb6") }) &&
          s0.line === "Black's 5th move is missing before 6.c4." && s0.buttons[0] === "Play f5" &&
          JSON.stringify(await gameNow()) === JSON.stringify(GAME.slice(0, 9)), { s0, connect: f0.connect });
    await shot("readon_0_failed");
    await tapIn("#thundo");
    await lineIs(/play this move/);
    check("Undo takes the move back", JSON.stringify((await fix()).moves) === "{}" &&
          JSON.stringify(await gameNow()) === JSON.stringify(GAME.slice(0, 8)), await gameNow());
    await tapIn("#thcancel");

    // ---------------------------------------------------------------- 5.Qc1: read on to the missing move
    await tapIn(await markSel(itet));
    t0 = Date.now();
    await play("d1", "c1");
    await lineIs(/is missing/);
    out.timings["Qc1 made until the program has read on (s)"] = (Date.now() - t0) / 1000;
    let s = await sheet();
    check("the program read on to Black's 12th move, which it leaves to the reader",
          s.note === "Read on to page 6: 14 moves joined." &&
          s.line === "Black's 12th move is missing before 13.Qe3. Play it on the board." &&
          s.buttons.indexOf("Undo 5.Qc1") >= 0 && !s.buttons.some((b) => /^Play /.test(b)), s);
    check("the line holds the game through 12.d6", JSON.stringify(await gameNow()) === JSON.stringify(GAME.slice(0, 23)),
          await gameNow());
    const lit = await inFrame((k) => { const el = document.querySelector("#ov .mark.seqcur");
      return { page: readerState.page, box: el ? READER.pages[readerState.page].marks[+el.dataset.mark].key === k : false }; }, qe3);
    check("the page turned forward to 13.Qe3, which is outlined", lit.page === 6 && lit.box, lit);
    await shot("readon_1_stop");

    // ---------------------------------------------------------------- 12...Qc2, then the join
    await play("b2", "c2");
    await lineIs(/^Next:/);
    s = await sheet();
    check("after 12...Qc2 the sheet offers 13.Qe3 to join", /^Next: 13\.Qe3$/.test(s.line) &&
          s.buttons[0] === "Join", s);
    await shot("readon_2_next");
    t0 = Date.now();
    await tapOffer("#thjoin");
    await lineIs(/reads to its end/);
    out.timings["Join until the program has read on (s)"] = (Date.now() - t0) / 1000;
    s = await sheet();
    const f = await fix();
    check("the join is stored with Qc2 before it, as the reader's, and the line holds the whole game",
          JSON.stringify(f.connect[qe3]) === JSON.stringify({ after: d6, before: ["Qc2"] }) &&
          JSON.stringify(await gameNow()) === JSON.stringify(GAME) && s.line === "The line reads to its end.",
          { connect: f.connect, game: await gameNow(), s });
    await shot("readon_3_done");
    out.ok = true;
  } catch (e) {
    out.failure = String(e && e.stack || e);
    await shot("readon_failure").catch(() => null);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
