// End-to-end test of the inverted page (white print on black) in Chromium
// (Playwright), on the reader of the generated test book (tests/test_reader.py
// runs this).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/invert_e2e.js READER_DIR SCREENS_DIR
//
// On a desktop window: checks that the invert button sits beside the bookmark
// icon, that a tap turns the page picture dark with light print, that the
// diagrams are inverted with the rest of the page, that the line under the current move and the
// ribbon keep the bookmark's yellow, that the choice survives a reload and that a second tap turns it off. Then
// on an iPhone 13 and an iPad held sideways: the button lies within the
// screen, the tap works, and no sideways scroll appears. Prints one JSON
// object with the results; the exit code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [dir, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], screenshots: [] };
let mode = "desktop";

function check(name, cond, detail) {
  out.checks.push({ mode, name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed [" + mode + "]: " + name + (detail !== undefined ? " (" + JSON.stringify(detail).slice(0, 800) + ")" : ""));
}
const EXE = process.env.CHROMIUM || "/opt/pw-browsers/chromium";
const LAUNCH = fs.existsSync(EXE) ? { executablePath: EXE } : {};
const PHONE = Object.assign({}, devices["iPhone 13"]);
const IPAD = Object.assign({}, devices["iPad Pro 11 landscape"]);
delete PHONE.defaultBrowserType;
delete IPAD.defaultBrowserType;
const DESK = { viewport: { width: 1280, height: 900 } };

async function openReader(ctx) {
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") out.errors.push("[" + mode + "] " + m.text()); });
  page.on("pageerror", (e) => out.errors.push("[" + mode + "] " + String(e)));
  await page.goto("file://" + path.resolve(dir, "ch01.html"));
  await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
  return page;
}
// the first page of the chapter that shows a diagram region
const diagramPage = (page) => page.evaluate(() => {
  const D = window.READER;
  for (const p of Object.keys(D.pages).map(Number).sort((a, b) => a - b))
    if (D.pages[p].diagrams.length) return p;
  return null;
});
async function goPage(page, p) {
  await page.evaluate((p) => { location.hash = "#page=" + p; }, p);
  await page.waitForFunction((p) => window.readerState.page === p, p);
  await page.waitForFunction(() => { const i = document.getElementById("pageimg"); return i.complete && i.naturalWidth > 0; });
}
// the mean brightness (0 to 255) of a screenshot of the element, and its
// pixels on a coarse grid, read by drawing the screenshot in the page
async function look(page, sel) {
  await page.evaluate((sel) => document.querySelector(sel).scrollIntoView({ block: "center" }), sel);
  await page.waitForTimeout(150);
  const png = (await page.locator(sel).first().screenshot()).toString("base64");
  return page.evaluate(async (png) => {
    const img = new Image();
    img.src = "data:image/png;base64," + png;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0);
    const px = g.getImageData(0, 0, c.width, c.height).data;
    let sum = 0;
    for (let i = 0; i < px.length; i += 4) sum += (px[i] + px[i + 1] + px[i + 2]) / 3;
    const grid = [];
    for (let y = 0; y < 12; y++) for (let x = 0; x < 12; x++) {
      const i = (Math.floor((y + 0.5) * c.height / 12) * c.width + Math.floor((x + 0.5) * c.width / 12)) * 4;
      grid.push((px[i] + px[i + 1] + px[i + 2]) / 3);
    }
    return { mean: sum / (px.length / 4), grid };
  }, png);
}
// the share of the pixels of a part of the screen in the bookmark's yellow (#f2b705) and in its
// inverse (#0d48fa), each within a small distance
async function hues(page, clip) {
  const png = (await page.screenshot({ clip })).toString("base64");
  return page.evaluate(async (png) => {
    const img = new Image();
    img.src = "data:image/png;base64," + png;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0);
    const px = g.getImageData(0, 0, c.width, c.height).data;
    const near = (i, r, gg, b) => Math.abs(px[i] - r) + Math.abs(px[i + 1] - gg) + Math.abs(px[i + 2] - b) < 60;
    let yellow = 0, blue = 0;
    for (let i = 0; i < px.length; i += 4) { if (near(i, 242, 183, 5)) yellow++; if (near(i, 13, 72, 250)) blue++; }
    const n = px.length / 4;
    return { yellow: yellow / n, blue: blue / n, n };
  }, png);
}
const pressed = (page) => page.evaluate(() => ({
  on: document.body.classList.contains("inverted"),
  pressed: document.getElementById("invbtn").getAttribute("aria-pressed"),
  stored: (() => { try { return localStorage.getItem("chessbook-invert"); } catch (e) { return null; } })(),
}));

(async () => {
  fs.mkdirSync(screens, { recursive: true });
  const browser = await chromium.launch(LAUNCH);
  try {
    // ---------------------------------------------------------------- a desktop window
    let ctx = await browser.newContext(DESK);
    let page = await openReader(ctx);
    const next = await page.evaluate(() => document.getElementById("bmbtn").nextElementSibling.id);
    check("the invert button sits beside the bookmark icon", next === "invbtn", next);
    let st = await pressed(page);
    check("the page starts in its own colours", !st.on && st.pressed === "false", st);
    const p = await diagramPage(page);
    check("the chapter holds a page with a diagram", p !== null, p);
    await goPage(page, p);
    const pageBefore = await look(page, "#pageimg");
    const diagBefore = await look(page, "#ov .diag");
    check("the page picture is light before the tap", pageBefore.mean > 160, pageBefore.mean);

    await page.click("#invbtn");
    st = await pressed(page);
    check("a tap inverts the page", st.on && st.pressed === "true" && st.stored === "1", st);
    const pageAfter = await look(page, "#pageimg");
    check("the page picture turns dark with light print", pageAfter.mean < 100, pageAfter.mean);
    const diagAfter = await look(page, "#ov .diag");
    check("the diagram is inverted with the page", Math.abs(diagAfter.mean - (255 - diagBefore.mean)) < 12,
          { before: diagBefore.mean, after: diagAfter.mean });
    // the bookmark's yellow stays yellow on the inverted page: the line under the current move
    // (outside reading mode) and the ribbon, read from the screen's pixels
    const mark = await page.evaluate(() => {
      const el = [...document.querySelectorAll("#ov .mark[data-node]")].find((e) => e.getBoundingClientRect().width > 8);
      return el ? el.dataset.mark : null;
    });
    check("the page holds a move to choose", !!mark, mark);
    await page.click("#ov .mark[data-mark='" + mark + "']");
    await page.mouse.move(2, 2);
    const foot = await page.evaluate((i) => {
      const r = document.querySelector("#ov .mark[data-mark='" + i + "']").getBoundingClientRect();
      return { x: r.left + 2, y: r.bottom - 2, width: r.width - 4, height: 2 };
    }, mark);
    const line = await hues(page, foot);
    check("on the inverted page the current move is underlined in the bookmark's yellow, not its inverse",
          line.yellow > 0.6 && line.blue === 0, line);
    await page.click("#bmbtn");
    const rib = await page.evaluate(() => { const r = document.querySelector("#ribbon svg").getBoundingClientRect();
      return { x: r.left + r.width * 0.2, y: r.top + 2, width: r.width * 0.6, height: r.height * 0.5 }; });
    const ribbon = await hues(page, rib);
    check("on the inverted page the ribbon stays yellow", ribbon.yellow > 0.6 && ribbon.blue === 0, ribbon);
    await page.click("#bmbtn");
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(screens, "invert_1280_light.png") });
    out.screenshots.push("invert_1280_light.png");
    await page.emulateMedia({ colorScheme: "dark" });
    await page.screenshot({ path: path.join(screens, "invert_1280_dark.png") });
    out.screenshots.push("invert_1280_dark.png");
    await page.emulateMedia({ colorScheme: "light" });

    await page.reload();
    await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
    st = await pressed(page);
    check("the inverted page survives a reload", st.on && st.pressed === "true", st);
    await page.click("#invbtn");
    st = await pressed(page);
    check("a second tap turns the page back", !st.on && st.pressed === "false" && st.stored === "0", st);
    await goPage(page, p);
    const pageBack = await look(page, "#pageimg");
    check("the page picture is light again", Math.abs(pageBack.mean - pageBefore.mean) < 4, { back: pageBack.mean, before: pageBefore.mean });
    mode = "";
    check("no console errors on the desktop", out.errors.length === 0, out.errors);
    await ctx.close();

    // ---------------------------------------------------------------- an iPhone and an iPad
    for (const [name, opts, width] of [["iphone13", PHONE, 390], ["ipad_landscape", IPAD, 1194]]) {
      mode = name;
      ctx = await browser.newContext(opts);
      page = await openReader(ctx);
      await goPage(page, p);
      const b = await page.evaluate(() => {
        const r = document.getElementById("invbtn").getBoundingClientRect();
        return { x: r.left, right: r.right, w: r.width, h: r.height, shown: getComputedStyle(document.getElementById("invbtn")).display !== "none" };
      });
      check("the invert button shows within the screen", b.shown && b.x >= 0 && b.right <= width && b.w >= 24, b);
      await page.tap("#invbtn");
      st = await pressed(page);
      check("a tap inverts the page", st.on && st.pressed === "true", st);
      const after = await look(page, "#pageimg");
      check("the page picture turns dark", after.mean < 100, after.mean);
      const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check("no sideways scroll", wide <= 0, wide);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(screens, "invert_" + width + "_light.png") });
      out.screenshots.push("invert_" + width + "_light.png");
      await ctx.close();
    }
    mode = "";
    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (e) {
    out.failure = String(e && e.stack || e);
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
