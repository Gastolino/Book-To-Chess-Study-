// End-to-end test of reading a section of the page that the program missed, in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/region_e2e.js CHAPTER_HTML SCREENS_DIR
//
// Opens a chapter reader of the generated test book (tests/test_reader.py builds it, with the note
// "White can also try Qe4 here." after 7...Ke6, whose move the program reads in no line, and the
// game ending with 8.Nc3), opened from a file, so without the browser app's worker. On a desktop,
// with the mouse: the "Read a section" button shows in reading mode only; it arms the tool, a drag
// on the page draws the section, a drag of a corner handle makes it larger, and the sheet says
// that this reader cannot read the page's text; a typed move that is not legal is refused with the
// reason; a legal one, attached after 8.Nc3 (the move chosen) as the continuation of the main line,
// shows in the move list as a main-line move and as a box on the page, and is chosen; it is kept
// after a reload; the pencil's tap on its box opens the section again, and "Remove these moves"
// removes it; with the pencil on, a tap where no move box stands starts a section there, about 60
// by 16 points around the tap; a section before a move adds alternatives to it. On an iPhone 13
// (touch): the bar's button, a drag by touch that neither scrolls nor turns the page, a corner
// moved by touch, and the move attached; no sideways scroll at 390 px. On an iPad held upright and
// sideways: the sheet with a section. Screenshots in the light and dark schemes. Prints one JSON
// object; the exit code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [file, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], screenshots: [] };
function check(name, cond, detail) {
  out.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed: " + name + (detail !== undefined ? " (" + JSON.stringify(detail) + ")" : ""));
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
  const both = async (page, name) => {
    await shot(page, name + "_light.png");
    await page.emulateMedia({ colorScheme: "dark" });
    await shot(page, name + "_dark.png");
    await page.emulateMedia({ colorScheme: "light" });
  };
  // a point of the page, in PDF points, on the screen
  const at = (page, x, y) => page.evaluate(([x, y]) => {
    const r = document.getElementById("pagebox").getBoundingClientRect(), P = READER.pages[window.readerState.page];
    return [r.left + x * r.width / P.w, r.top + y * r.height / P.h];
  }, [x, y]);
  // the section drawn on the page, in PDF points (from its outline on the screen)
  const section = (page) => page.evaluate(() => {
    const el = document.getElementById("rgsel");
    if (!el) return null;
    const r = document.getElementById("pagebox").getBoundingClientRect(), b = el.getBoundingClientRect();
    const P = READER.pages[window.readerState.page];
    const k = P.w / r.width;
    return [(b.left - r.left) * k, (b.top - r.top) * k, (b.right - r.left) * k, (b.bottom - r.top) * k].map(v => Math.round(v * 10) / 10);
  });
  const near = (a, b, tol) => a && b && a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) <= (tol || 1));
  // the middle of a corner handle of the section on the screen, and the pixels of a PDF point
  const handle = (page, c) => page.evaluate((c) => { const b = document.querySelector("#rgsel .rgh." + c).getBoundingClientRect();
    return [b.left + b.width / 2, b.top + b.height / 2]; }, c);
  const scale = (page) => page.evaluate(() => document.getElementById("pagebox").getBoundingClientRect().width /
    READER.pages[window.readerState.page].w);
  const state = (page) => page.evaluate(() => {
    const n = READER.nodes[window.readerState.nodeId];
    const fix = JSON.parse(window.correctionsText());
    return { id: window.readerState.nodeId, san: n ? n.san : null, main: n ? n.main : null,
      corrected: n ? n.corrected || null : null, region: n ? n.region || null : null, added: fix.added,
      open: !document.getElementById("fix").hidden, fixText: document.getElementById("fix").innerText,
      check: (document.getElementById("rgcheck") || {}).textContent || "",
      msg: document.getElementById("pagemsg").textContent, page: window.readerState.page,
      pressed: (document.getElementById("regionbtn") || {}).getAttribute
        ? document.getElementById("regionbtn").getAttribute("aria-pressed") : null };
  });
  const ids = (page) => page.evaluate(() => {
    const N = READER.nodes, find = (f) => Object.keys(N).find(k => f(N[k]));
    const nc3 = find(n => n.san === "Nc3" && n.main), ke6 = find(n => n.san === "Ke6" && n.main);
    return { nc3, ke6, nc3key: N[nc3].key, ke6key: N[ke6].key };
  });
  const goNode = async (page, id) => {
    await page.evaluate((id) => { location.hash = "#node=" + id; }, id);
    await page.waitForFunction((id) => window.readerState.nodeId === id, id);
  };
  // the reader in reading mode, with no correction stored, at the move chosen
  const fresh = async (page, hash) => {
    await page.goto(url);
    await page.evaluate(() => { localStorage.clear(); localStorage.setItem("chessbook-reading", "1"); });
    await page.goto(url + (hash || ""));
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState && document.body.classList.contains("reading"));
  };
  const treeMoves = (page) => page.evaluate(() => Array.from(document.querySelectorAll("#tree .mv[data-node]")).map(b => ({
    id: b.dataset.node, text: b.textContent, inVar: !!b.closest(".var") })));
  // the word "Qe4" of the note on page 4, and the line under it ("White has a strong attack.")
  const QE4 = [308.5, 66.5, 325.2, 79.8];
  try {
    // ---------------------------------------------------------------- desktop, with the mouse
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    watch(page);
    await page.goto(url);
    await page.waitForFunction(() => window.READER && window.readerState);
    let I = await ids(page);
    await fresh(page, "#node=" + I.nc3);
    I = await ids(page);
    await page.waitForFunction((id) => window.readerState.nodeId === id, I.nc3);

    // the button shows in reading mode only
    check("the Read a section button shows in reading mode", await page.isVisible("#regionbtn"));
    await page.evaluate(() => document.body.classList.remove("reading"));
    check("outside reading mode the button is hidden", !(await page.isVisible("#regionbtn")));
    await page.evaluate(() => document.body.classList.add("reading"));

    // the button arms the tool; a drag draws the section
    await page.click("#regionbtn");
    let s = await state(page);
    check("the button arms the tool", s.pressed === "true" && await page.evaluate(() => document.body.classList.contains("rgdraw")), s);
    let [x0, y0] = await at(page, 305, 64), [x1, y1] = await at(page, 318, 76);
    await page.mouse.move(x0, y0);
    await page.mouse.down();
    await page.mouse.move(x1, y1, { steps: 8 });
    await page.mouse.up();
    let r = await section(page);
    check("a drag draws the section, in PDF points", near(r, [305, 64, 318, 76], 1.2), r);
    s = await state(page);
    check("the sheet opens for the section", s.open && /Read a section of page 4/.test(s.fixText), s.fixText);
    check("the reader opened from a file says it cannot read the page's text",
      /cannot read the text of the page/.test(s.fixText), s.fixText);
    check("the moves go after the move chosen by default", /After 8\.Nc3/.test(s.fixText) && /Continue the main line/.test(s.fixText), s.fixText);

    // a corner handle makes the section larger: the corner follows the pointer (9 and 5 points here)
    const h = await handle(page, "se");
    let k = await scale(page);
    await page.mouse.move(h[0], h[1]);
    await page.mouse.down();
    await page.mouse.move(h[0] + 9 * k, h[1] + 5 * k, { steps: 6 });
    await page.mouse.up();
    r = await section(page);
    check("a drag of a corner handle resizes the section", near(r, [305, 64, 327, 81], 1.2), r);
    // a drag inside it moves it, and back
    const mid = await at(page, 316, 72), to = await at(page, 318, 74);
    await page.mouse.move(mid[0], mid[1]);
    await page.mouse.down();
    await page.mouse.move(to[0], to[1], { steps: 4 });
    await page.mouse.up();
    r = await section(page);
    check("a drag inside the section moves it", near(r, [307, 66, 329, 83], 1.2), r);
    check("the section stays open after it moves", (await state(page)).open);
    await page.screenshot({ path: path.join(screens, "region_sheet_1280_light.png") });
    out.screenshots.push(path.join(screens, "region_sheet_1280_light.png"));

    // a move that is not legal is refused with the reason
    await page.fill("#rgsan", "Qe4");
    s = await state(page);
    check("a move of the wrong side is refused with the reason",
      /Qe4 is not legal\. It is Black's move here, and Qe4 is a move for White\./.test(s.check), s.check);
    check("the confirm button waits for legal moves", await page.isDisabled("#rgok"));
    await page.fill("#rgsan", "8...Nb4 9.Bxf7");
    s = await state(page);
    check("a later move that is not legal is named, after the legal ones",
      /After 8…Nb4, Bxf7 is not legal\. /.test(s.check) && /bishop/.test(s.check), s.check);
    await page.fill("#rgsan", "8...Nb4");
    s = await state(page);
    check("a legal move is said to be legal", /The move 8…Nb4 is legal here\./.test(s.check), s.check);
    const board = await page.evaluate(() => document.getElementById("boardnote").textContent);
    check("the board shows the position after the moves", /after the moves you read/.test(board), board);
    await both(page, "region_sheet_1280");
    await page.click("#rgok");
    s = await state(page);
    check("the moves are stored as an added entry with the section",
      s.added[I.nc3key] && s.added[I.nc3key].length === 1 && JSON.stringify(s.added[I.nc3key][0].san) === '["Nb4"]' &&
      s.added[I.nc3key][0].page === 4 && near(s.added[I.nc3key][0].rect, [307, 66, 329, 83], 1.2) &&
      s.added[I.nc3key][0].main === true, s.added);
    check("the sheet closes and the section goes", !s.open && !(await section(page)), s);
    check("the new move is chosen", s.san === "Nb4" && s.main === true && s.corrected === "added" && s.region, s);
    let moves = await treeMoves(page);
    let nb4 = moves.find(m => /Nb4/.test(m.text));
    check("the move list shows the move in the main line", nb4 && !nb4.inVar, moves);
    let box = await page.evaluate((id) => {
      const el = document.querySelector(".mark[data-node='" + id + "']");
      return el ? { cls: el.className, ok: true } : null;
    }, s.id);
    check("the page shows a box for the move", box && /current/.test(box.cls), box);
    await both(page, "region_added_1280");

    // kept after a reload
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState);
    await goNode(page, I.nc3);
    moves = await treeMoves(page);
    nb4 = moves.find(m => /Nb4/.test(m.text));
    check("after a reload the move is still in the move list", nb4 && !nb4.inVar, moves);
    const markId = await page.evaluate(() => { const m = READER.pages[4].marks.find(x => x.corrected === "added");
      return m ? m.node : null; });
    check("after a reload the page still shows its box", !!markId && await page.isVisible(".mark[data-node='" + markId + "']"), markId);
    await page.click(".mark[data-node='" + markId + "']");
    s = await state(page);
    check("a tap on the box chooses the move", s.san === "Nb4", s);

    // the pencil opens the section again; Remove these moves removes it
    await page.click("#penbtn");
    await page.click(".mark[data-node='" + markId + "']");
    s = await state(page);
    check("the pencil's tap on the box opens the section", s.open && /Change the moves you read/.test(s.fixText) &&
      await page.inputValue("#rgsan") === "8…Nb4" && near(await section(page), [307, 66, 329, 83], 1.2), s.fixText);
    await page.click("#rgremove");
    s = await state(page);
    moves = await treeMoves(page);
    check("Remove these moves removes them", !s.added[I.nc3key] && !moves.some(m => /Nb4/.test(m.text)) &&
      !(await page.evaluate(() => READER.pages[4].marks.some(m => m.corrected === "added"))), { s, moves });

    // with the pencil on, a tap where no box stands starts a section there; Before adds alternatives
    await goNode(page, I.nc3);
    const tap = await at(page, 360, 140);
    await page.mouse.click(tap[0], tap[1]);
    r = await section(page);
    check("the pencil's tap on the page starts a section of about 60 by 16 points", near(r, [330, 132, 390, 148], 1.2), r);
    await page.click("#rgwhere button[data-where=before]");
    await page.fill("#rgsan", "8.Qe4");
    s = await state(page);
    check("before the move the moves start from the position before it", /The move 8\.Qe4 is legal here\./.test(s.check), s.check);
    await page.click("#rgok");
    s = await state(page);
    check("a section before a move is stored with before", s.added[I.nc3key] && s.added[I.nc3key][0].before === true &&
      !s.added[I.nc3key][0].main, s.added);
    check("the alternative is chosen as a variation", s.san === "Qe4" && s.main === false, s);
    moves = await treeMoves(page);
    const qe4 = moves.find(m => /Qe4/.test(m.text));
    check("the move list shows the alternative as a variation", qe4 && qe4.inVar, moves);
    // Escape and Cancel take the section away
    await page.click("#penbtn");
    await page.click("#regionbtn");
    [x0, y0] = await at(page, 230, 300); [x1, y1] = await at(page, 300, 320);
    await page.mouse.move(x0, y0); await page.mouse.down(); await page.mouse.move(x1, y1, { steps: 5 }); await page.mouse.up();
    check("a second section opens its sheet", (await state(page)).open);
    await page.click("#rgcancel");
    s = await state(page);
    check("Cancel removes the section", !s.open && !(await section(page)) && s.pressed === "false", s);
    await ctx.close();

    // ---------------------------------------------------------------- iPhone 13, by touch
    const phone = await browser.newContext({ ...devices["iPhone 13"] });
    const pp = await phone.newPage();
    watch(pp);
    await pp.goto(url);
    await pp.waitForFunction(() => window.READER && window.readerState);
    I = await ids(pp);
    await fresh(pp, "#node=" + I.nc3);
    await pp.waitForFunction((id) => window.readerState.nodeId === id, I.nc3);
    // at 390 px the bar keeps its room for the current move, and the top bar holds the button
    check("at 390 px the button is in the top bar", await pp.isVisible("#regionbtn") && !(await pp.isVisible("#mregion")));
    const fit = await pp.evaluate(() => { const t = document.getElementById("mtxt"); return [t.scrollWidth, t.clientWidth, t.textContent]; });
    check("the bar keeps room for the current move", fit[0] <= fit[1] + 1, fit);
    let sw = await pp.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    check("no sideways scroll at 390 px with the button", sw[0] <= sw[1], sw);
    await pp.evaluate(() => window.scrollTo(0, 0));
    await pp.tap("#regionbtn");
    await pp.evaluate(() => window.scrollTo(0, 0));
    await pp.waitForTimeout(200);
    check("while the section is drawn the board leaves the page", await pp.evaluate(() =>
      !document.body.classList.contains("stickboard") && document.body.classList.contains("rgdraw")));
    await both(pp, "region_draw_390");
    const cdp = await phone.newCDPSession(pp);
    const touchDrag = async (a, b) => {
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: a[0], y: a[1] }] });
      for (let i = 1; i <= 8; i++)
        await cdp.send("Input.dispatchTouchEvent", { type: "touchMove",
          touchPoints: [{ x: a[0] + (b[0] - a[0]) * i / 8, y: a[1] + (b[1] - a[1]) * i / 8 }] });
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
      await pp.waitForTimeout(150);
    };
    // a drag mostly sideways, which on the page would otherwise turn it (a page that scrolled
    // under the finger would give another section than the one asked for)
    await touchDrag(await at(pp, 250, 64), await at(pp, 330, 80));
    s = await state(pp);
    r = await section(pp);
    check("a drag by touch draws the section", near(r, [250, 64, 330, 80], 1.5), r);
    check("the drag neither scrolls nor turns the page", s.page === 4, s.page);
    const place = await pp.evaluate(() => { const b = document.getElementById("rgsel").getBoundingClientRect(),
      f = document.getElementById("fix").getBoundingClientRect(), bar = document.getElementById("mbar").getBoundingClientRect();
      return { top: b.top, bottom: b.bottom, sheet: f.top, sheetBottom: f.bottom, bar: bar.top }; });
    check("the sheet opens above the bar, with the section in view above it", s.open && place.top >= 0 &&
      place.bottom <= place.sheet && Math.abs(place.sheetBottom - place.bar) < 2, place);
    // the top left corner, 50 points to the right and 2 up
    const hp = await handle(pp, "nw"), kp = await scale(pp);
    await touchDrag(hp, [hp[0] + 50 * kp, hp[1] - 2 * kp]);
    r = await section(pp);
    check("a corner moved by touch resizes the section", near(r, [300, 62, 330, 80], 1.5), r);
    sw = await pp.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    check("no sideways scroll at 390 px with the sheet", sw[0] <= sw[1], sw);
    await pp.fill("#rgsan", "Nb4");
    await both(pp, "region_sheet_390");
    await pp.tap("#rgok");
    s = await state(pp);
    check("on a phone the move is attached and chosen", s.san === "Nb4" && s.main === true, s);
    await pp.tap("#mmoves");
    await pp.waitForTimeout(300);
    await both(pp, "region_added_390");
    await phone.close();

    // ---------------------------------------------------------------- iPad, upright and sideways
    for (const [w, hh] of [[820, 1180], [1180, 820]]) {
      const pad = await browser.newContext({ viewport: { width: w, height: hh }, deviceScaleFactor: 2,
        isMobile: true, hasTouch: true });
      const tp = await pad.newPage();
      watch(tp);
      await tp.goto(url);
      await tp.waitForFunction(() => window.READER && window.readerState);
      I = await ids(tp);
      await fresh(tp, "#node=" + I.nc3);
      await tp.waitForFunction((id) => window.readerState.nodeId === id, I.nc3);
      const btn = await tp.isVisible("#regionbtn") ? "#regionbtn" : "#mregion";
      await tp.tap(btn);
      // (a tap close to a move box goes to the box, as the browser adjusts a finger's tap to what it can press)
      const p = await at(tp, 360, 140);
      await tp.touchscreen.tap(p[0], p[1]);
      s = await state(tp);
      r = await section(tp);
      check("on a tablet (" + w + " px) a tap makes a section and opens the sheet", s.open && near(r, [330, 132, 390, 148], 1.5),
        { s, r });
      const seen = await tp.evaluate(() => { const b = document.getElementById("rgsel").getBoundingClientRect(),
        f = document.getElementById("fix").getBoundingClientRect();
        return { top: b.top, bottom: b.bottom, sheetTop: f.top, sheetBottom: f.bottom, h: window.innerHeight,
          fixed: getComputedStyle(document.getElementById("fix")).position }; });
      // upright, the sheet stands above the bar with the section in view above it; sideways it heads the panel
      check("on a tablet (" + w + " px) the sheet and the section are both in view", seen.top >= 0 && seen.bottom <= seen.h &&
        seen.sheetTop < seen.h && (w > hh || (seen.fixed === "fixed" && seen.bottom <= seen.sheetTop)), seen);
      await tp.fill("#rgsan", "Nb4");
      await both(tp, "region_sheet_" + w);
      await pad.close();
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
