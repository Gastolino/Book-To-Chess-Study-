// End-to-end test of the thread in the browser app (tools/build_web.py), in Chromium, with Python
// running through Pyodide in the page's worker: the reader corrects a line move by move on the
// board, and the program reads on by itself from each move (chessbook/review_js.py, "the thread").
//
// Usage:
//   NODE_PATH=/opt/node22/lib/node_modules node tests/thread_e2e.js SITE_URL BOOK_PDF SCREENS_DIR
//
// BOOK_PDF is the generated book of tests/test_thread.py (make_wells): Wells - Shirov reads to
// 4...Qb6; White's fifth move is printed as "5.'it'et" and stands in no line; Black's fifth move
// is missing from the text; "6.c4 Bh6 7.e3 f4 8.exf4 Bxf4 9.Qxf4 Qxb2" stands in no line on the
// next page, and the game ends there. On an iPad held upright, in the dark scheme, the test:
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
//     the join after 4...Qb6) is stored and sent with {readOn}; the sheet says "Reading on…", the
//     board keeps the position after 5.Qc1 and the small book of the top bar turns its pages; the
//     program then reads on by itself: it supplies 5...f5 and joins 6.c4 ... 9...Qxb2, the whole
//     game, with no further tap; the sheet says "Read on to page 5: 9 moves joined." and "The line
//     reads to its end.", the page turns forward to the line's end, the program's join is stored as
//     its own ("auto") and shows so (a dashed outline, the legend's "Joined by the program"), and f5
//     as supplied by the program in the move list;
//   - Undo takes back 5.Qc1 and the program's join after it, and the sheet asks for the move again;
//     made again with the worker slowed down, a move made on the board while the program reads on
//     is not taken, and a box tapped meanwhile is taken once it has answered; the line holds the
//     whole game; Cancel leaves no thread and no joining;
//   - the page is loaded again: the program's join is still stored and the line holds the game;
//   - a tap on the program's join opens the usual sheet, whose "Remove join" removes it and stores
//     the removal (corrections.py "declined"): the line ends at 5.Qc1 again.
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
    for (let i = 0; ; i++) {
      try {
        const f = await frame();
        const el = await f.$(sel);
        if (!el) throw new Error("nothing at " + sel);
        await el.scrollIntoViewIfNeeded();
        await el.tap();
        return;
      } catch (e) {
        // (the app may show the chapter again, as after a reload)
        if (i > 20 || !/detached/.test(String(e))) throw e;
        await page.waitForTimeout(250);
      }
    }
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

    // ---------------------------------------------------------------- 5.Qc1, made on the board: the app reads on
    // (what the sheet said meanwhile, line by line, and whether the small book showed the work)
    await inFrame(() => {
      window.__said = [];
      const note = () => {
        const f = document.getElementById("fix");
        if (f.hidden) return;
        const t = [...f.querySelectorAll(".thr, .thl")].map((p) => p.innerText.trim()).join(" | ");
        if (t && window.__said[window.__said.length - 1] !== t) window.__said.push(t);
      };
      new MutationObserver(note).observe(document.getElementById("fix"), { childList: true, subtree: true, characterData: true });
    });
    await page.evaluate(() => {
      window.__busy = false;
      new MutationObserver(() => { if (document.getElementById("busy").classList.contains("on") && /Reading on/.test(workWords)) window.__busy = true; })
        .observe(document.getElementById("busy"), { attributes: true });
    });
    await tapIn(await markSel(itet));
    t0 = Date.now();
    await play("d1", "c1");
    const f1 = await fix();
    check("the move made on the board stores the box's move and its join after 4...Qb6, at once",
          f1.moves[itet] && f1.moves[itet].san === "Qc1" && JSON.stringify(f1.connect[itet]) === JSON.stringify({ after: qb6 }),
          { moves: f1.moves, connect: f1.connect });
    s = await sheet();
    const held = await inFrame(() => {
      const svg = [...document.querySelectorAll("svg.board")].find((x) => x.getBoundingClientRect().width > 0);
      return { fen: svg ? svg.getAttribute("aria-label").replace("Chess board: ", "") : "" };
    });
    check("while the program reads on the sheet says so and the board keeps the position after 5.Qc1",
          s.line === "Reading on…" && JSON.stringify(s.buttons) === JSON.stringify(["Cancel"]) &&
          held.fen.split(" ").slice(0, 2).join(" ") === "rnb1kb1r/pp1ppp1p/1q3p2/2pP4/8/8/PPP1PPPP/RNQ1KBNR b", { s, held });
    await shot("04_reading_on");
    await waitFrame(() => { const l = document.querySelector("#fix .thl"); return l && /reads to its end/.test(l.innerText); },
                    null, 180000);
    out.timings["Qc1 made until the program has read on (s)"] = (Date.now() - t0) / 1000;
    const all = await inFrame(() => window.__said), lines = all.slice(all.indexOf("Reading on…"));
    check("the sheet said, line by line: reading on, then how far it read and that the line reads to its end",
          lines.length === 2 && lines[0] === "Reading on…" &&
          lines[1] === "Read on to page 5: 9 moves joined. | The line reads to its end.", lines);
    check("the small book showed the work", await page.evaluate(() => window.__busy));
    check("the line holds the whole game, with no further tap", JSON.stringify(await gameNow()) === JSON.stringify(GAME),
          await gameNow());
    const f2 = await fix();
    check("the program's join is stored as its own, with the move it supplied before it, and the reader's as it was",
          f2.connect[c4] && f2.connect[c4].after === itet && JSON.stringify(f2.connect[c4].before) === JSON.stringify(["f5"]) &&
          f2.connect[c4].auto === true && JSON.stringify(f2.connect[itet]) === JSON.stringify({ after: qb6 }) &&
          f2.moves[itet].san === "Qc1", f2.connect);
    s = await sheet();
    check("Undo offers the reader's move, Close ends", JSON.stringify(s.buttons) === JSON.stringify(["Undo 5.Qc1", "Close"]), s);
    const shown = await inFrame((c4) => {
      const i = READER.pages[readerState.page].marks.findIndex((m) => m.key === c4);
      const el = i >= 0 ? document.querySelector("#ov .mark[data-mark='" + i + "']") : null;
      const f5 = [...document.querySelectorAll("#tree .mv[data-node]")].find((b) => READER.nodes[b.dataset.node].san === "f5");
      return { page: readerState.page, auto: !!el && el.classList.contains("auto"), fixed: !!el && el.classList.contains("fixed"),
        outline: el ? getComputedStyle(el).outlineStyle : null, f5dot: !!f5 && !!f5.querySelector(".dot.st-auto"),
        f5tip: f5 ? f5.title : null,
        legend: [...document.querySelectorAll(".legend > span")].some((x) => x.textContent === "Joined by the program") };
    }, c4);
    check("the page turned forward to the line's end, where the program's join shows as its own, and f5 as supplied",
          shown.page === 5 && shown.auto && !shown.fixed && shown.outline === "dashed" && shown.f5dot &&
          /^Supplied by the program/.test(shown.f5tip) && shown.legend, shown);
    await shot("05_read_on");

    // ---------------------------------------------------------------- Undo takes it all back
    await tapIn("#thundo");
    await waitFrame(() => { const l = document.querySelector("#fix .thl"); return l && /play this move/.test(l.innerText); },
                    null, 120000);
    const f3 = await fix();
    s = await sheet();
    check("Undo takes back the reader's move and the program's join after it, and asks for the move again",
          !f3.moves[itet] && !f3.connect[itet] && !f3.connect[c4] && JSON.stringify(f3.declined) === "{}" &&
          JSON.stringify(await gameNow()) === JSON.stringify(GAME.slice(0, 8)) && s.line === "After 4…Qb6, play this move.",
          { fix: f3, game: await gameNow(), s });
    await shot("06_undone");
    await tapIn("#thcancel");
    // made again, with the worker slowed down: while it reads on, a move made on the board is not
    // taken, and a tap on a box waits for the answer, which then takes it
    await page.evaluate(() => {
      const post = worker.postMessage.bind(worker);
      worker.postMessage = (m, t) => {
        if (m && m.type === "readOn") { setTimeout(() => post(m, t), 1500); return undefined; }
        return post(m, t);
      };
    });
    await tapIn(await markSel(itet));
    await play("d1", "c1");
    await page.waitForTimeout(200);
    await play("b6", "b5");
    const nf6 = await keyOf("Nf6");
    await tapIn(await markSel(nf6));
    const waiting = await sheet();
    await waitFrame(() => { const l = document.querySelector("#fix .thl"); return l && l.innerText === "Play this move."; },
                    null, 180000);
    const after = await inFrame((k) => { const el = document.querySelector("#ov .mark.seqcur");
      return { page: readerState.page, box: el ? READER.pages[readerState.page].marks[+el.dataset.mark].key === k : false }; }, nf6);
    const fw = await fix();
    check("while the program reads on, the board takes no move and a tap waits; then the tap is taken",
          waiting.line === "Reading on…" && after.page === 4 && after.box && JSON.stringify(fw.added) === "{}" &&
          JSON.stringify(Object.keys(fw.moves)) === JSON.stringify([itet]), { waiting, after, added: fw.added, moves: fw.moves });
    check("made again, the line holds the whole game", JSON.stringify(await gameNow()) === JSON.stringify(GAME), await gameNow());
    await tapIn("#thcancel");
    st = await state();
    check("Cancel leaves no sheet, no thread and no joining", !st.open && !st.joining &&
          !(await inFrame(() => !!document.querySelector("#ov .mark.seqcur"))), st);

    // ---------------------------------------------------------------- a reload keeps the program's entries
    await page.waitForFunction(() => !saving, null, { timeout: 300000 });
    await page.waitForTimeout(1000);
    await page.reload();
    // (the app comes back to the book, or its library lists it)
    const shelf = () => { const b = document.querySelector("#books li.book .open"); return !!b && !!b.offsetParent; };
    await page.waitForFunction((shelf) => document.getElementById("view").style.display === "block" || eval(shelf)(),
                               shelf.toString(), { timeout: 600000 });
    if (await page.evaluate(() => document.getElementById("view").style.display !== "block"))
      await page.click("#books li.book .open");
    await waitFrame(() => window.READER && window.readerState && !!readerState.page, null, 600000);
    await waitFrame((k) => { const D = READER, id = Object.keys(D.nodes).find((x) => D.nodes[x].key === k);
      if (!id) return false;
      let n = 0;
      for (let cur = D.lines[D.nodes[id].line].root; ;) { const c = D.nodes[cur].children.find((x) => D.nodes[x].main);
        if (!c) break; n++; cur = c; }
      return n === 18; }, d4Key, 300000);
    const f4 = await fix();
    check("after a reload the program's entries are kept, and the line holds the whole game",
          f4.connect[c4] && f4.connect[c4].auto === true && JSON.stringify(await gameNow()) === JSON.stringify(GAME) &&
          (await inFrame((c4) => READER.corrections.connect[c4] && READER.corrections.connect[c4].auto === true, c4)),
          { connect: f4.connect });

    // ---------------------------------------------------------------- the reader removes the program's join
    // (the app may show the chapter again meanwhile: the page is asked for until it shows)
    for (let i = 0; !(await inFrame(() => readerState.page === 5)); i++) {
      if (i > 60) throw new Error("page 5 does not show");
      await inFrame(() => { location.hash = "#page=5"; });
      await page.waitForTimeout(500);
    }
    if (!(await state()).pencil) await tapIn("#showread");
    await tapIn(await markSel(c4));
    s = await sheet();
    check("a tap on the program's join opens the usual sheet, which can remove it",
          s && s.line === "Play this move." && s.buttons.indexOf("Remove join") >= 0, s);
    await shot("07_programs_join");
    await tapIn("#thauto");
    for (let t = Date.now(); (await gameNow() || []).length !== 9 && Date.now() - t < 120000;) await page.waitForTimeout(200);
    const f5 = await fix();
    check("removing it stores it as declined, and the line ends at 5.Qc1 again",
          !f5.connect[c4] && JSON.stringify(f5.declined[c4]) === JSON.stringify({ part: "connect" }) &&
          JSON.stringify(await gameNow()) === JSON.stringify(GAME.slice(0, 9)), { fix: f5, game: await gameNow() });
    await shot("08_declined");
    out.ok = true;
  } catch (e) {
    out.failure = String(e && e.stack || e);
    await shot("failure").catch(() => null);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
