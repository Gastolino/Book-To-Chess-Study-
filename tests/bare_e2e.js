// End-to-end test of the pencil join of a move printed without its move
// number, in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/bare_e2e.js CHAPTER_HTML PATCH_JSON SCREENS_DIR
//
// Opens a chapter reader of a generated book (tests/test_reader.py builds
// it) whose notes print a reply without its number after a comment
// ("7.Nf3 ... retreats. Nbd7 8.Qc2 ..."), where the moves after it do not
// read on from it, so that the bare move stands in no line, and checks: the
// Review list lists it; with the pencil (on with reading mode), a tap on it
// asks for its move after 7.Nf3 and offers Nbd7, and More opens its corrector
// with "Continue the line after 7.Nf3"; that button stores the join, and
// the patch (computed by chessbook/live.py for that join) applied through
// the page's applyPatch hook makes the move and the moves after it part of
// the variation; no console errors. Prints one JSON object; the exit code
// is 1 when a check fails.
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
    const u = await page.evaluate(() => READER.unattached.find(x => x.text === "Nbd7") || null);
    check("the bare move stands in no line, with the move it follows", u && u.after, u);
    const afterId = await page.evaluate((k) => { for (const id in READER.nodes) if (READER.nodes[id].key === k) return id; }, u.after);
    check("the move it follows is 7.Nf3", await page.evaluate((id) => READER.nodes[id].san === "Nf3" && READER.nodes[id].number === 7, afterId));
    await page.evaluate((p) => { location.hash = "#page=" + p; }, u.page);
    await page.waitForFunction((p) => window.readerState.page === p, u.page);

    // the Review list lists it (Review and the pencil show in reading mode)
    await page.click("#showread");
    await page.click("#reviewbtn");
    await page.waitForSelector("#revlist button[data-kind='seq']");
    const item = await page.evaluate(() => {
      const b = [...document.querySelectorAll("#revlist button[data-kind='seq']")].find(x => /Nbd7/.test(x.innerText));
      return b ? b.innerText : null;
    });
    check("the Review list shows the bare move", item && /Nbd7/.test(item), item);
    await page.click("#reviewbtn");

    // the pencil (on with reading mode): a tap on the bare move asks for it after 7.Nf3, and More
    // opens its corrector with the join after 7.Nf3
    await page.click(".mark[data-seq='" + u.key + "']");
    const asks = await page.evaluate(() => ({ line: document.querySelector("#fix .thl").innerText,
      buttons: [...document.querySelectorAll("#fix button")].map((b) => b.textContent) }));
    check("the pencil's tap asks for the move after 7.Nf3 and offers it",
          asks.line === "After 7.Nf3, play this move." && asks.buttons[0] === "Play Nbd7", asks);
    await page.click("#thmore");
    await page.waitForSelector("#fixafter");
    const words = await page.evaluate(() => document.getElementById("fixafter").innerText);
    check("the corrector offers the line after 7.Nf3", /Continue the line after 7\.Nf3/.test(words), words);
    check("the corrector explains the item", await page.evaluate(() => /no move number/.test(document.getElementById("fix").innerText)));
    await shot("bare_item_1280_light.png");
    await page.click("#fixafter");
    const fix = await page.evaluate(() => JSON.parse(window.correctionsText()));
    check("the join is stored", fix.connect[u.key] && fix.connect[u.key].after === u.after, fix.connect);
    check("the corrector says so", await page.evaluate(() => /joined this move to the line after 7\.Nf3/.test(document.getElementById("fix").innerText)));

    // the patch of the browser app: the move and the moves after it join the variation
    await page.evaluate((p) => window.applyPatch(p), patch);
    const res = await page.evaluate((k) => {
      let id = null;
      for (const i in READER.nodes) if (READER.nodes[i].key === k) id = i;
      const n = id ? READER.nodes[id] : null;
      const par = n ? READER.nodes[n.parent] : null;
      const next = n && n.children.length ? READER.nodes[n.children[0]] : null;
      return { san: n && n.san, corrected: n && n.corrected, parent: par && par.san, next: next && next.san,
               gone: !READER.unattached.some(x => x.key === k) };
    }, u.key);
    check("the bare move is part of the variation", res.san === "Nbd7" && res.parent === "Nf3" && res.corrected === "connected", res);
    check("the moves after it go on from it", res.next === "Qc2", res);
    check("it is no longer an item", res.gone, res);
    await shot("bare_joined_1280_light.png");
    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (err) {
    out.failure = String(err && err.message ? err.message : err);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
