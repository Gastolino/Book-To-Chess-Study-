// End-to-end test of a tap on a red move and of filling a gap in the text, in
// Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/gap_e2e.js CHAPTER_HTML PATCH_JSON SCREENS_DIR
//
// Opens a chapter reader of the generated test book whose game lacks Black's
// fifth move and White's sixth (tests/test_reader.py builds it, with the patch
// that chessbook/live.py makes once the reader gives both moves), and checks,
// with the pencil that comes on with reading mode: outside reading mode a tap on a red move only chooses
// it; in reading mode a tap on a red move on the page opens its corrector,
// which says that the position is unknown because the text lacks a move
// before it and offers the gap's corrector; the board shows the position
// before the gap; the gap's corrector is titled "Give Black's move 5", lists
// the legal moves, takes a typed move and then the next missing move, and
// stores them as the "gaps" correction; a tap on the gap or on a red move in
// the move list opens its corrector; the Review list names the gap; the
// patch of the browser app turns the gap into the moves given and the moves
// after it into decoded moves; on a phone the corrector opens as the sheet
// above the bar. Prints one JSON object; the exit code is 1 when a check
// fails.
const { chromium } = require("playwright");
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
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") out.errors.push(m.text()); });
  page.on("pageerror", (e) => out.errors.push(String(e)));
  const url = "file://" + path.resolve(file);
  const patch = JSON.parse(fs.readFileSync(patchFile, "utf-8"));
  fs.mkdirSync(screens, { recursive: true });
  const shot = async (name) => { const p = path.join(screens, name); await page.screenshot({ path: p }); out.screenshots.push(p); };
  const fixText = () => page.evaluate(() => document.getElementById("fix").innerText);
  try {
    await page.goto(url);
    await page.waitForFunction(() => window.READER && window.readerState);
    const info = await page.evaluate(() => {
      for (const id in READER.nodes) {
        const n = READER.nodes[id];
        if (n.gap && !n.san) return { hole: id, key: n.gap, page: n.page,
          after: Object.keys(READER.nodes).find(k => READER.nodes[k].key === n.gap) };
      }
      return null;
    });
    check("the book has a gap", info && info.after, info);
    await page.evaluate((p) => { location.hash = "#page=" + p; }, info.page);
    await page.waitForFunction((p) => window.readerState.page === p, info.page);
    check("the pencil is off", await page.evaluate(() => !document.body.classList.contains("pencil")));

    // the Review list names the gap, and its item opens the gap's corrector (Review shows in
    // reading mode)
    await page.click("#showread");
    await page.click("#reviewbtn");
    const rev = await page.evaluate(() => document.getElementById("revlist").innerText);
    check("the Review list names the gap", /Black's move 5, missing from the text/.test(rev), rev);
    await page.click("#revlist button[data-kind='gap']");
    await page.waitForFunction(() => /Give Black's move 5/.test((document.querySelector("#fix h3") || {}).textContent || ""));
    await page.click("#reviewbtn");
    check("closing Review closes the corrector", await page.evaluate(() => document.getElementById("fix").hidden));

    // outside reading mode a tap on the red move only chooses it (the correction tools are hidden)
    await page.click("#showread");
    await page.click(".mark[data-node='" + info.after + "']");
    check("outside reading mode a tap on a red move only chooses it", await page.evaluate((id) =>
      window.readerState.nodeId === id && document.getElementById("fix").hidden &&
      !document.body.classList.contains("reading"), info.after));

    // in reading mode a tap on the red move after the gap opens its corrector at once
    await page.click("#showread");
    await page.click(".mark[data-node='" + info.after + "']");
    await page.waitForSelector("#fix:not([hidden])");
    let t = await fixText();
    check("a tap on a red move opens its corrector", /Correct 6…Kxf7/.test(t), t.slice(0, 120));
    check("the corrector says that the position is unknown", /position before this move is unknown/.test(t), t);
    check("the move stays chosen", await page.evaluate((id) => window.readerState.nodeId === id, info.after));
    const note = await page.evaluate(() => document.getElementById("boardnote").textContent);
    check("the board shows the position before the gap", /position before the gap, after 5\.exd5/.test(note), note);
    check("the board is not empty", await page.evaluate(() =>
      document.querySelectorAll("#board svg use").length > 20));
    await shot("gap_move_1280_light.png");

    // the gap's corrector
    await page.click("#fixgap");
    await page.waitForFunction(() => /Give Black's move 5/.test(document.querySelector("#fix h3").textContent));
    check("the gap's corrector lists the legal moves", await page.evaluate(() =>
      [...document.querySelectorAll("#fixlist button[data-san]")].some(b => b.dataset.san === "Nxd5")));
    await page.fill("#fixsan", "nxd5");
    await page.press("#fixsan", "Enter");
    let fix = await page.evaluate(() => JSON.parse(window.correctionsText()));
    check("the move given is stored", fix.gaps[info.key] && fix.gaps[info.key].san.join() === "Nxd5", fix.gaps);
    t = await fixText();
    check("the corrector asks for the next missing move", /Give White's move 6/.test(t) && /You gave 5…Nxd5/.test(t), t);
    await page.click("#fixlist button[data-san='Nxf7']");
    fix = await page.evaluate(() => JSON.parse(window.correctionsText()));
    check("the moves given are stored in order", fix.gaps[info.key].san.join() === "Nxd5,Nxf7", fix.gaps);
    t = await fixText();
    check("the corrector shows the moves given", /The moves you gave for the gap/.test(t) && /Remove the moves you gave/.test(t), t);
    await shot("gap_filled_1280_light.png");
    await page.click("#fixclose");

    // the move list: a tap on the gap, or on a red move, opens its corrector
    await page.click("#tree .mv[data-node='" + info.hole + "']");
    await page.waitForSelector("#fix:not([hidden])");
    t = await fixText();
    check("a tap on the gap in the move list opens its corrector", /The moves you gave for the gap/.test(t), t.slice(0, 80));
    await page.click("#fixclose");
    await page.click("#tree .mv[data-node='" + info.after + "']");
    await page.waitForSelector("#fix:not([hidden])");
    check("a tap on a red move in the move list opens its corrector", /Correct 6…Kxf7/.test(await fixText()));
    // a move read without doubt only selects
    await page.click("#fixclose");
    const e4 = await page.evaluate(() => Object.keys(READER.nodes).find(k => READER.nodes[k].san === "e4"));
    await page.click("#tree .mv[data-node='" + e4 + "']");
    check("a move read without doubt opens no corrector", await page.evaluate(() => document.getElementById("fix").hidden));

    // the patch of the browser app
    await page.click("#tree .mv[data-node='" + info.hole + "']");
    await page.evaluate((p) => window.applyPatch(p), patch);
    const res = await page.evaluate((key) => {
      const tree = document.getElementById("tree").innerText;
      // (node ids are handed out anew: the printed move keeps its key)
      const n = Object.values(READER.nodes).find(x => x.key === key);
      const gap = Object.values(READER.nodes).find(x => x.gap && !x.san);
      return { tree, after: n && n.san, status: n && n.status, gap: !!gap, fen: window.readerState.fen };
    }, info.key);
    check("the patch removes the gap", !res.gap, res);
    check("the move after the gap is read", res.after === "Kxf7" && res.status === "ok", res);
    check("the move list shows the moves given", /5\.exd5 Nxd5/.test(res.tree.replace(/\s+/g, " ")) && /6\.Nxf7 Kxf7/.test(res.tree), res.tree);
    check("the board shows a position", !!res.fen, res);
    await shot("gap_patched_1280_light.png");

    // the phone: the corrector of a red move is the sheet above the bar
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => localStorage.clear());
    await page.goto(url + "#page=" + info.page);
    await page.reload();
    await page.waitForFunction((p) => window.readerState && window.readerState.page === p, info.page);
    const after = await page.evaluate((key) => Object.keys(READER.nodes).find(k => READER.nodes[k].key === key), info.key);
    await page.click("#showread");
    await page.click(".mark[data-node='" + after + "']");
    await page.waitForSelector("#fix:not([hidden])");
    const phone = await page.evaluate(() => {
      const f = document.getElementById("fix"), bar = document.getElementById("mbar");
      return { pos: getComputedStyle(f).position, bottom: f.getBoundingClientRect().bottom,
               barTop: bar.getBoundingClientRect().top, sw: document.documentElement.scrollWidth, w: window.innerWidth };
    });
    check("on a phone the corrector is the sheet above the bar", phone.pos === "fixed" && Math.abs(phone.bottom - phone.barTop) < 2, phone);
    check("no sideways scroll at 390 px", phone.sw <= phone.w, phone);
    await shot("gap_move_390_light.png");
    await page.click("#fixgap");
    await page.waitForFunction(() => /Give Black's move 5/.test(document.querySelector("#fix h3").textContent));
    await shot("gap_fill_390_light.png");
    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (err) {
    out.failure = String(err && err.message ? err.message : err);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
