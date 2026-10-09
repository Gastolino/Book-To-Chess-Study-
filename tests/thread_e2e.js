// End-to-end test of the thread in the browser app (tools/build_web.py), in Chromium, with Python
// running through Pyodide in the page's worker: the reader corrects a line move by move on the
// board, and the program reads on from each move (chessbook/review_js.py, "the thread").
//
// Usage:
//   NODE_PATH=/opt/node22/lib/node_modules node tests/thread_e2e.js SITE_URL BOOK_PDF SCREENS_DIR
//
// BOOK_PDF is the generated book of tests/test_thread.py (make_wells): Wells - Shirov reads to
// 4...Qb6; White's fifth move is printed as "5.'it'et" and stands in no line; Black's fifth move
// is missing from the text; "6.c4 Bh6 7.e3 f4 8.exf4 Bxf4 9.Qxf4 Qxb2" stands in no line on the
// next page. On an iPad held upright, in the dark scheme, the test:
//   - finds Show reading in the row under the board, between End (#bend) and Turn the board round
//     (#bflip), on a 375 px phone, an upright iPad, a sideways iPad and a desktop, and a Show reading
//     on screen there with no move chosen (on the phone and the upright iPad, in the bar at the foot);
//   - turns reading on from there: the pencil comes on with it;
//   - taps the "'it'et" box: one line asks for the move printed there after 4...Qb6; Cancel leaves
//     no sheet and no joining; More opens the box's Place sheet, whose "Continue a line..." starts a
//     join that its Close ends; while joining, the sheet's list joins (never "in its place"), and the
//     join the program refuses says why in the sheet;
//   - taps the box again: the move is made on the full board, which stays in view under the sheet
//     (the small board of the bar is not shown); makes 5.Qc1 there: the correction (its move, and
//     the join after 4...Qb6) is stored, the line holds 5.Qc1, and the sheet says that Black's 5th
//     move is missing before 6.c4, with f5 offered and 5.Qc1 to undo;
//   - makes 5...f5 on the board: the sheet offers the moves read on from there, 6.c4 Bh6 7.e3 ...;
//   - joins them: the line holds the whole game, the join stores f5 as the move given before it,
//     and the sheet says the line reads to its end; Undo takes the join back and offers the moves
//     again, and Join joins them again; Close leaves no thread and no joining.
// Prints one JSON object {ok, checks, errors, screenshots}; the exit code is 1 when a check fails.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const [siteUrl, bookPdf, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], screenshots: [], timings: {} };
function check(name, cond, detail) {
  out.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed: " + name + (detail !== undefined ? " (" + JSON.stringify(detail).slice(0, 800) + ")" : ""));
}
const GAME = "d4 Nf6 Bg5 c5 Bxf6 gxf6 d5 Qb6 Qc1 f5 c4 Bh6 e3 f4 exf4 Bxf4 Qxf4 Qxb2".split(" ");
const SIZES = [["a 375 px phone", 375, 812], ["an upright iPad", 834, 1194], ["a sideways iPad", 1194, 834],
  ["a desktop", 1280, 900]];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 834, height: 1194 }, hasTouch: true, colorScheme: "dark" });
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
  // (the offer in a sheet's first place waits a moment after the sheet changes: a double tap's second
  // tap does not take it)
  const tapOffer = async (sel) => { await page.waitForTimeout(450); await tapIn(sel); };
  const tapIn = async (sel) => {
    const f = await frame();
    const el = await f.$(sel);
    if (!el) throw new Error("nothing at " + sel);
    await el.scrollIntoViewIfNeeded();
    await el.tap();
  };
  const sheet = () => inFrame(() => { const f = document.getElementById("fix");
    return f.hidden ? null : { line: (f.querySelector(".thl") || f).innerText.trim(),
      buttons: [...f.querySelectorAll("button")].map((b) => b.textContent.trim()) }; });
  const state = () => inFrame(() => ({ reading: document.body.classList.contains("reading"),
    pencil: document.body.classList.contains("pencil"), joining: document.body.classList.contains("joining"),
    open: !document.getElementById("fix").hidden, pressed: document.getElementById("showread").getAttribute("aria-pressed"),
    pen: document.getElementById("penbtn").getAttribute("aria-pressed") }));
  // a move on the board: a tap on the piece, then on its square (the board the window shows)
  const play = async (from, to) => {
    for (const sq of [from, to]) {
      const xy = await inFrame((sq) => {
        const svg = [document.querySelector("#minibox svg.board"), document.querySelector("#board svg.board")]
          .find((s) => s && s.getBoundingClientRect().width > 0);
        const r = svg.getBoundingClientRect(), flip = svg.dataset.flip === "1";
        const f = "abcdefgh".indexOf(sq[0]), row = 8 - parseInt(sq[1], 10);
        const c = flip ? 7 - f : f, rr = flip ? 7 - row : row, k = r.width / 375;
        return [r.left + (14 + (c + 0.5) * 45) * k, r.top + (1 + (rr + 0.5) * 45) * k, r.top, r.bottom];
      }, sq);
      const box = await (await page.$("#view")).boundingBox();
      await page.touchscreen.tap(box.x + xy[0], box.y + xy[1]);
      await page.waitForTimeout(150);
    }
  };
  const fix = () => inFrame(() => JSON.parse(window.correctionsText()));
  const keyOf = (raw) => inFrame((raw) => { for (const p in READER.pages) for (const m of READER.pages[p].marks)
    if (m.raw === raw) return m.key; return null; }, raw);
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
    await inFrame(() => { location.hash = "#page=4"; });
    await waitFrame(() => window.READER && window.readerState && window.readerState.page === 4 &&
      Object.values(READER.pages[4].marks).some((m) => m.raw === "'it'et"), null, 300000);
    var d4Key = await keyOf("d4");
    const itet = await keyOf("'it'et"), qb6 = await keyOf("Qb6"), c4 = await keyOf("c4");
    check("the generated book reads to 4...Qb6 and places 5.'it'et and 6.c4 in no line",
          JSON.stringify(await gameNow()) === JSON.stringify(GAME.slice(0, 8)) &&
          (await inFrame((ks) => ks.every((k) => READER.unattached.some((u) => u.key === k)), [itet, c4])),
          { game: await gameNow(), itet, c4 });

    // ---------------------------------------------------------------- the toggle under the board
    for (const [name, w, h] of SIZES) {
      await page.setViewportSize({ width: w, height: h });
      await page.waitForTimeout(400);
      const r = await inFrame(() => Object.fromEntries(["bend", "showread", "bflip"].map((id) => {
        const b = document.getElementById(id).getBoundingClientRect();
        return [id, { left: b.left, right: b.right, mid: (b.top + b.bottom) / 2, w: b.width,
          row: document.getElementById(id).parentElement.className }];
      })));
      check("Show reading sits under the board between End and Turn the board round on " + name,
            r.showread.w > 0 && r.bend.right <= r.showread.left && r.showread.right <= r.bflip.left &&
            Math.abs(r.showread.mid - r.bend.mid) < 3 && Math.abs(r.showread.mid - r.bflip.mid) < 3 &&
            r.showread.row === "controls", r);
      // with no move chosen, as a chapter opens: a Show reading the reader can tap without scrolling
      const seen = await inFrame(() => {
        const hit = ["showread", "mread"].map((id) => {
          const el = document.getElementById(id), b = el.getBoundingClientRect();
          const x = (b.left + b.right) / 2, y = (b.top + b.bottom) / 2;
          const top = b.width ? document.elementFromPoint(x, y) : null;
          return { id, x, y, on: b.width > 0 && y > 0 && y < innerHeight && x > 0 && x < innerWidth && !!top && el.contains(top) };
        });
        return { node: readerState.nodeId, hit };
      });
      check("a Show reading is on screen with no move chosen on " + name, !seen.node && seen.hit.some((h) => h.on), seen);
      await shot("toggle_" + w + "x" + h);
    }
    await page.setViewportSize({ width: 834, height: 1194 });
    await page.waitForTimeout(400);
    await shot("01_page");

    // ---------------------------------------------------------------- reading on, the pencil with it
    await tapIn("#showread");
    let st = await state();
    check("turning reading on under the board turns the pencil on", st.reading && st.pencil && st.pressed === "true" &&
          st.pen === "true" && !st.open, st);
    await shot("02_reading_on");

    // ---------------------------------------------------------------- the box in no line
    const itetSel = "#ov .mark[data-seq='" + itet.replace(/'/g, "\\'") + "']";
    const markSel = async (key) => inFrame((key) => {
      const i = READER.pages[readerState.page].marks.findIndex((m) => m.key === key);
      return i >= 0 ? "#ov .mark[data-mark='" + i + "']" : null; }, key);
    await tapIn(await markSel(itet));
    let s = await sheet();
    check("a tap on the box in no line asks for its move after 4...Qb6, in one line",
          s && s.line === "After 4…Qb6, play this move." &&
          JSON.stringify(s.buttons) === JSON.stringify(["More", "Cancel"]), s);
    const boards = await inFrame(() => {
      const svg = document.querySelector("#board svg.board"), r = svg.getBoundingClientRect();
      const sheet = document.getElementById("fix").getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width * 0.3, r.top + r.height * 0.9);
      return { mini: document.querySelectorAll("#minibox svg.board").length, top: r.top, bottom: r.bottom, vh: innerHeight,
        sheetBottom: sheet.bottom, square: Math.round(r.width / 8.3), free: !!top && svg.contains(top) };
    });
    check("one board while the move is asked for: the full board, in view under the sheet",
          boards.mini === 0 && boards.top >= boards.sheetBottom - 1 && boards.bottom <= boards.vh && boards.free &&
          boards.square >= 40, boards);
    const lit = await inFrame((k) => { const el = document.querySelector("#ov .mark.seqcur");
      return el ? READER.pages[readerState.page].marks[+el.dataset.mark].key === k : false; }, itet);
    check("the box asked about is outlined", lit);
    await shot("03_asks_for_the_move");
    await tapIn("#thcancel");
    st = await state();
    check("Cancel closes the sheet and leaves no joining", !st.open && !st.joining && st.pencil, st);
    // the old Place sheet, behind More: its join ends with its Close
    await tapIn(await markSel(itet));
    await tapIn("#thmore");
    await tapIn("#fixjoin");
    st = await state();
    check("More opens the Place sheet, whose Continue a line starts a join", st.open && st.joining, st);
    await tapIn("#fixclose");
    st = await state();
    check("Close ends the join", !st.open && !st.joining, st);
    check("nothing was stored meanwhile", JSON.stringify((await fix()).connect) === "{}", (await fix()).connect);
    // while joining, the Place sheet's list joins (it never means "in its place"); the program refuses
    // the join (the box does not read after 4...Qb6), and the sheet says why
    await tapIn(await markSel(itet));
    await tapIn("#thmore");
    await tapIn("#fixjoin");
    await tapIn("#fix button[data-to='" + qb6 + "']");
    const f0 = await fix();
    check("while joining, the Place list stores a join, not a placement in its place",
          JSON.stringify(f0.connect[itet]) === JSON.stringify({ after: qb6 }) && !f0.unattached[itet] && !(await state()).joining,
          { connect: f0.connect, unattached: f0.unattached });
    await waitFrame(() => /^Not placed/.test((document.getElementById("fixmsg") || {}).textContent || ""), null, 120000);
    const said = await inFrame(() => document.getElementById("fixmsg").textContent);
    check("a join the program refuses says why in the sheet", /not a legal move for White after 4\.\.\.Qb6/.test(said), said);
    await shot("03b_refused");
    await tapIn("#fixundo");
    await waitFrame((k) => !READER.corrections.connect[k], itet, 120000);
    await tapIn("#fixclose");

    // ---------------------------------------------------------------- 5.Qc1, made on the board
    await tapIn(await markSel(itet));
    t0 = Date.now();
    await play("d1", "c1");
    const f1 = await fix();
    check("the move made on the board stores the box's move and its join after 4...Qb6, at once",
          f1.moves[itet] && f1.moves[itet].san === "Qc1" && JSON.stringify(f1.connect[itet]) === JSON.stringify({ after: qb6 }),
          { moves: f1.moves, connect: f1.connect });
    await shot("04_applying");
    await waitFrame(() => { const f = document.getElementById("fix"), l = f.querySelector(".thl");
      return !f.hidden && l && /missing/.test(l.innerText); }, null, 120000);
    out.timings["Qc1 made until the next step shows (s)"] = (Date.now() - t0) / 1000;
    s = await sheet();
    check("the line holds 5.Qc1", JSON.stringify(await gameNow()) === JSON.stringify(GAME.slice(0, 9)), await gameNow());
    check("the sheet says Black's 5th move is missing before 6.c4 and offers f5, and 5.Qc1 to undo",
          s.line === "Black's 5th move is missing before 6.c4." && s.buttons[0] === "Play f5" &&
          s.buttons.indexOf("Undo 5.Qc1") >= 0 && s.buttons.indexOf("Cancel") >= 0, s);
    await shot("05_missing_move");

    // ---------------------------------------------------------------- 5...f5, then the moves read on
    await play("f6", "f5");
    await waitFrame(() => { const l = document.querySelector("#fix .thl"); return l && /^Next:/.test(l.innerText); }, null, 120000);
    s = await sheet();
    check("after f5 the sheet offers the moves read on from there",
          /^Next: 6\.c4 Bh6 7\.e3 f4 8\.exf4 Bxf4 …( \(page \d+\))?$/.test(s.line) &&
          JSON.stringify(s.buttons) === JSON.stringify(["Join", "Skip", "Undo 5.Qc1", "Cancel"]), s);
    await shot("06_next");
    t0 = Date.now();
    await tapOffer("#thjoin");
    await waitFrame(() => { const l = document.querySelector("#fix .thl"); return l && /reads to its end/.test(l.innerText); }, null, 120000);
    out.timings["Join until the line reads to its end (s)"] = (Date.now() - t0) / 1000;
    const f2 = await fix();
    check("Join stores the join of 6.c4 after 5.Qc1 with f5 given before it (after, then before)",
          JSON.stringify(f2.connect[c4]) === JSON.stringify({ after: itet, before: ["f5"] }), f2.connect);
    check("the line holds the whole game", JSON.stringify(await gameNow()) === JSON.stringify(GAME), await gameNow());
    s = await sheet();
    check("the sheet says the line reads to its end", s.line === "The line reads to its end." &&
          JSON.stringify(s.buttons) === JSON.stringify(["Undo", "Close"]), s);
    await shot("07_done");
    // Undo takes the join back: the moves are offered again, and Join joins them again
    await tapIn("#thundo");
    await waitFrame(() => { const l = document.querySelector("#fix .thl"); return l && /^Next:/.test(l.innerText); }, null, 120000);
    check("Undo takes the join back and offers the moves again",
          !(await fix()).connect[c4] && JSON.stringify(await gameNow()) === JSON.stringify(GAME.slice(0, 9)),
          { connect: (await fix()).connect, game: await gameNow() });
    await tapOffer("#thjoin");
    await waitFrame(() => { const l = document.querySelector("#fix .thl"); return l && /reads to its end/.test(l.innerText); }, null, 120000);
    check("Join after Undo joins them again", JSON.stringify(await gameNow()) === JSON.stringify(GAME), await gameNow());
    await tapIn("#thclose");
    st = await state();
    check("Close leaves no sheet, no thread and no joining", !st.open && !st.joining &&
          !(await inFrame(() => !!document.querySelector("#ov .mark.seqcur"))), st);
    await shot("08_closed");
    out.ok = true;
  } catch (e) {
    out.failure = String(e && e.stack || e);
    await shot("failure").catch(() => null);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
