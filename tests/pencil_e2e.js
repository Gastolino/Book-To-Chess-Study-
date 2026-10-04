// End-to-end test of the pencil in the chapter reader, in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/pencil_e2e.js CHAPTER_HTML PATCH_JSON SCREENS_DIR
//
// Opens a chapter reader of the generated test book (tests/test_reader.py
// builds it, with a patch that tests/test_reader.py computed with
// chessbook/live.py for a correction of the move printed "Zq9"), and checks:
// the pencil in the top bar (and in the bar at the foot of a phone screen) is
// a thin line icon with no background; with the pencil on, a tap on a move
// that the program read without doubt opens its corrector, which takes
// another legal move; "Continue a line…" on a sequence placed in no line
// joins it after a move tapped on the page; "Start a new line here" and "Not
// part of this line" store their corrections; the patch applied through the
// page's applyPatch hook (as the browser app's worker sends it) turns the
// failed move and the moves after it into decoded moves without leaving the
// page or the move; a page that opens in the middle of a line shows that
// line's position at the top of the page; screenshots at 1280 and 390 px in
// the light and dark schemes; no console errors. Prints one JSON object; the
// exit code is 1 when a check fails.
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
  try {
    await page.goto(url);
    await page.waitForFunction(() => window.READER && window.readerState);
    // the page of the game
    const gamePage = await page.evaluate(() => {
      for (const p in READER.pages) for (const m of READER.pages[p].marks) if (m.raw === "Zq9") return +p;
    });
    await page.evaluate((p) => { location.hash = "#page=" + p; }, gamePage);
    await page.waitForFunction((p) => window.readerState.page === p, gamePage);

    // the pencil: a thin line icon without a background, always in the top bar
    const pen = await page.evaluate(() => {
      const b = document.getElementById("penbtn"), svg = b.querySelector("svg"), r = b.getBoundingClientRect();
      return { visible: r.width > 0 && r.height > 0, stroke: getComputedStyle(svg).strokeWidth,
               fill: getComputedStyle(svg).fill, bg: getComputedStyle(b).backgroundColor };
    });
    check("pencil shows in the top bar", pen.visible, pen);
    check("pencil is a 1.25 px line icon", pen.stroke === "1.25px" && pen.fill === "none", pen);
    check("pencil has no background", pen.bg === "rgba(0, 0, 0, 0)", pen.bg);
    await page.click("#penbtn");
    check("pencil turns on", await page.evaluate(() => document.body.classList.contains("pencil") &&
      document.getElementById("penbtn").getAttribute("aria-pressed") === "true"));

    // a move read without doubt: its corrector opens and takes another legal move
    const e5 = await page.evaluate(() => {
      for (const m of READER.pages[window.readerState.page].marks)
        if (m.node && READER.nodes[m.node].san === "e5" && READER.nodes[m.node].status === "ok") return m.node;
    });
    await page.click(".mark[data-node='" + e5 + "']");
    await page.waitForSelector("#fix:not([hidden]) #fixsan");
    const editor = await page.evaluate(() => document.getElementById("fix").innerText);
    check("a move read without doubt opens its corrector", /Correct 1…e5/.test(editor) || /Correct 1\.\.\.e5/.test(editor), editor.slice(0, 80));
    check("the corrector lists the legal moves", await page.evaluate(() =>
      document.querySelectorAll("#fixlist button[data-san]").length === 20));
    await shot("pencil_move_1280_light.png");
    await page.fill("#fixsan", "e6");
    await page.press("#fixsan", "Enter");
    const stored = await page.evaluate((id) => JSON.parse(window.correctionsText()).moves[READER.nodes[id].key], e5);
    check("the correction of a move read without doubt is stored", stored && stored.san === "e6", stored);
    await page.click(".mark[data-node='" + e5 + "']");
    await page.click("#fixundo");

    // disconnect: a new line from 6.Nxf7
    const nxf7 = await page.evaluate(() => {
      for (const id in READER.nodes) if (READER.nodes[id].raw === "tLlxf7") return id;
    });
    await page.click(".mark[data-node='" + nxf7 + "']");
    await page.waitForSelector("#splithere");
    await page.emulateMedia({ colorScheme: "dark" });
    await shot("pencil_line_1280_dark.png");
    await page.emulateMedia({ colorScheme: "light" });
    await page.click("#splithere");
    let fix = await page.evaluate(() => JSON.parse(window.correctionsText()));
    const kx = await page.evaluate((id) => READER.nodes[id].key, nxf7);
    check("Start a new line here is stored", fix.disconnect[kx] && fix.disconnect[kx].start === "here", fix.disconnect);
    await page.click("#notpart");
    fix = await page.evaluate(() => JSON.parse(window.correctionsText()));
    check("Not part of this line is stored", fix.disconnect[kx] && fix.disconnect[kx].remove === true, fix.disconnect);
    await page.click("#lineundo");

    // connect: the sequence placed in no line continues the line after a move tapped on the page
    const seq = await page.evaluate(() => READER.unattached.length ? READER.unattached[0].key : null);
    check("the book has a sequence placed in no line", !!seq);
    const seqPage = await page.evaluate((k) => READER.unattached.find(u => u.key === k).page, seq);
    await page.evaluate((p) => { location.hash = "#page=" + p; }, seqPage);
    await page.waitForFunction((p) => window.readerState.page === p, seqPage);
    await page.click(".mark[data-seq='" + seq + "']");
    await page.waitForSelector("#fixjoin");
    await page.click("#fixjoin");
    check("joining asks for a move", await page.evaluate(() => document.body.classList.contains("joining")));
    await page.evaluate((p) => { location.hash = "#page=" + p; }, gamePage);
    await page.waitForFunction((p) => window.readerState.page === p, gamePage);
    const ke6 = await page.evaluate(() => { for (const id in READER.nodes) if (READER.nodes[id].san === "Ke6") return id; });
    await page.click(".mark[data-node='" + ke6 + "']");
    fix = await page.evaluate(() => JSON.parse(window.correctionsText()));
    const after = await page.evaluate((id) => READER.nodes[id].key, ke6);
    check("Continue a line stores the join", fix.connect[seq] && fix.connect[seq].after === after, fix.connect);
    check("joining ends after the tap", await page.evaluate(() => !document.body.classList.contains("joining")));

    // the patch of the browser app: applied in place
    const zq9 = await page.evaluate(() => { for (const id in READER.nodes) if (READER.nodes[id].raw === "Zq9") return id; });
    await page.click(".mark[data-node='" + zq9 + "']");
    const before = await page.evaluate(() => ({ page: window.readerState.page, node: window.readerState.nodeId,
      status: READER.nodes[window.readerState.nodeId].status }));
    check("the move printed Zq9 is not read before the patch", before.status === "failed", before);
    await page.evaluate((p) => window.applyPatch(p), patch);
    const res = await page.evaluate(() => {
      const id = window.readerState.nodeId, n = READER.nodes[id];
      const next = READER.nodes[n.children[0]];
      const tree = document.getElementById("tree").innerText;
      const box = document.querySelector(".mark[data-node='" + id + "']");
      return { page: window.readerState.page, san: n.san, status: n.status, next: next && next.san,
               nextStatus: next && next.status, tree, cls: box ? box.className : null,
               fen: window.readerState.fen };
    });
    check("the patch keeps the page", res.page === before.page, res);
    check("the patch keeps the move", res.san === "Nxd5", res);
    check("the following moves are decoded", res.nextStatus === "ok" && res.next === "Nxf7", res);
    check("the move list shows the corrected move", /Nxd5/.test(res.tree), res.tree.slice(0, 200));
    check("the board shows the position after it", !!res.fen && res.fen.indexOf("3n") >= 0, res.fen);
    await shot("pencil_patched_1280_light.png");

    // a page that opens in the middle of a line
    const mid = await page.evaluate(() => {
      for (const id of READER.lineOrder) { const L = READER.lines[id]; if (L.end_page > L.page) return L.end_page; }
      return null;
    });
    if (mid !== null) {
      await page.goto(url + "#page=" + mid);
      await page.reload();
      await page.waitForFunction((p) => window.readerState && window.readerState.page === p, mid);
      const g = await page.evaluate(() => ({ node: window.readerState.nodeId, chips: document.getElementById("chips").innerText,
        msg: document.getElementById("pagemsg").textContent }));
      check("a page opening mid-line shows the line's position", !!g.node && /goes on here/.test(g.msg), g);
    }

    // the phone: the pencil in the bar at the foot, no sideways scroll, the board in view
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(url + "#page=" + gamePage);
    await page.reload();
    await page.waitForFunction((p) => window.readerState && window.readerState.page === p, gamePage);
    const mpen = await page.evaluate(() => { const r = document.getElementById("mpen").getBoundingClientRect();
      return r.width > 0 && r.top >= window.innerHeight - 120; });
    check("the phone bar holds the pencil", mpen);
    await page.click("#mpen");
    await page.click(".mark[data-node='" + e5 + "']");
    await page.waitForSelector("#fix:not([hidden])");
    const phone = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, w: window.innerWidth,
      mini: document.getElementById("mini").classList.contains("on") }));
    check("no sideways scroll at 390 px with the pencil", phone.sw <= phone.w, phone);
    check("the small board stays in view while correcting", phone.mini, phone);
    await shot("pencil_move_390_light.png");
    await page.emulateMedia({ colorScheme: "dark" });
    await shot("pencil_move_390_dark.png");
    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (err) {
    out.failure = String(err && err.message ? err.message : err);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
