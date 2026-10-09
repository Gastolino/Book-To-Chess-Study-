// End-to-end test of the bookmarks in Chromium (Playwright), on the reader of
// the generated test book (tests/test_reader.py runs this).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/bookmark_e2e.js READER_DIR SCREENS_DIR
//
// On a desktop window: opens the chapter reader on a page with moves, chooses
// a move and sets a bookmark with the icon in the top bar; checks that the
// icon fills in the warm yellow, that the ribbon hangs on that page only,
// inside the page picture and over no move box, that the bookmark keeps the
// page, the move and the time, that it survives a reload, that a tap on the
// ribbon removes it with "Bookmark removed. Undo" and that Undo brings it
// back, that the contents page lists it as a link that opens the chapter at
// that page and move, and that the warm yellow colours no element but the
// icon, the ribbon and the line under the current move on the page. Then the same on an iPhone 13 (the icon in the bar at
// the foot of the screen) and an iPad held sideways, with no sideways scroll.
// Takes screenshots in the light and dark schemes, checks that no console
// errors occur, and prints one JSON object with the results; the exit code
// is 1 when a check fails.
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

// the colour of the bookmark token as the browser computes it
const tokenRgb = (page) => page.evaluate(() => {
  const v = getComputedStyle(document.documentElement).getPropertyValue("--bookmark").trim();
  const probe = document.createElement("i"); probe.style.color = v; document.body.appendChild(probe);
  const rgb = getComputedStyle(probe).color; probe.remove(); return rgb;
});
// every element whose computed colours hold the given colour, apart from the
// bookmark icons and the ribbon (and what is inside them) and the box of the
// current move on the page, which reading mode off underlines in that colour
const yellowElsewhere = (page, rgb) => page.evaluate((rgb) => {
  const props = ["color", "background-color", "border-top-color", "border-right-color", "border-bottom-color",
                 "border-left-color", "outline-color", "fill", "stroke", "text-decoration-color"];
  const found = [];
  for (const el of document.querySelectorAll("*")) {
    if (el.closest("#bmbtn, #mbm, #ribbon") || el.matches("#ov .mark.current")) continue;
    const cs = getComputedStyle(el);
    for (const p of props) if (cs.getPropertyValue(p) === rgb) found.push(el.tagName + "#" + el.id + "." + el.className + ":" + p);
  }
  return found;
}, rgb);
const rect = (page, sel) => page.evaluate((sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height, right: r.right, bottom: r.bottom };
}, sel);
const state = (page) => page.evaluate(() => ({
  page: window.readerState.page, node: window.readerState.nodeId,
  pressed: document.getElementById("bmbtn").getAttribute("aria-pressed"),
  mpressed: document.getElementById("mbm").getAttribute("aria-pressed"),
  ribbon: !document.getElementById("ribbon").hidden && getComputedStyle(document.getElementById("ribbon")).display !== "none",
  note: document.getElementById("bmnote").textContent,
  undo: !!document.getElementById("bmundo"),
  msg: document.getElementById("pagemsg").textContent,
}));
const stored = (page) => page.evaluate(() => {
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k.startsWith("chessbook-bookmarks:")) return { key: k, value: JSON.parse(localStorage.getItem(k)) };
  }
  return null;
});
async function shot(page, name) {
  await page.screenshot({ path: path.join(screens, name) });
  out.screenshots.push(name);
}
async function openReader(ctx, hash) {
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") out.errors.push("[" + mode + "] " + m.text()); });
  page.on("pageerror", (e) => out.errors.push("[" + mode + "] " + String(e)));
  await page.goto("file://" + path.resolve(dir, "ch01.html") + (hash || ""));
  await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
  return page;
}
// a page of the chapter that holds move boxes, and one of its moves
const target = (page) => page.evaluate(() => {
  const D = window.READER;
  for (const p of Object.keys(D.pages).map(Number).sort((a, b) => a - b)) {
    const m = D.pages[p].marks.find((x) => x.node && D.nodes[x.node] && D.nodes[x.node].fen);
    if (m) return { page: p, node: m.node };
  }
  return null;
});
async function goTo(page, t) {
  await page.evaluate((t) => { location.hash = "#node=" + t.node; }, t);
  await page.waitForFunction((t) => window.readerState.page === t.page && window.readerState.nodeId === t.node, t);
}
// the ribbon lies inside the page picture and over no move box or diagram
const ribbonFits = (page) => page.evaluate(() => {
  const r = document.getElementById("ribbon").getBoundingClientRect();
  const p = document.getElementById("pageimg").getBoundingClientRect();
  const inside = r.left >= p.left - 0.5 && r.right <= p.right + 0.5 && r.top >= p.top - 0.5 && r.bottom <= p.bottom + 0.5;
  const hit = [];
  for (const b of document.querySelectorAll("#ov .mark, #ov .diag")) {
    const q = b.getBoundingClientRect();
    if (q.left < r.right && q.right > r.left && q.top < r.bottom && q.bottom > r.top) hit.push(b.title);
  }
  return { inside, hit, ribbon: { w: r.width, h: r.height, top: r.top - p.top, rightGap: p.right - r.right }, page: { w: p.width } };
});

(async () => {
  fs.mkdirSync(screens, { recursive: true });
  const browser = await chromium.launch(LAUNCH);
  try {
    // ---------------------------------------------------------------- a desktop window
    let ctx = await browser.newContext(DESK);
    let page = await openReader(ctx);
    const rgb = await tokenRgb(page);
    check("the page defines the bookmark colour", /^rgb\(/.test(rgb), rgb);
    const t = await target(page);
    check("the chapter holds a page with move boxes", t, t);
    await goTo(page, t);
    let st = await state(page);
    check("a page without a bookmark shows the plain icon and no ribbon",
          st.pressed === "false" && !st.ribbon && (await stored(page)) === null, st);
    check("the warm yellow colours nothing before a bookmark is set", (await yellowElsewhere(page, rgb)).length === 0);
    const under = await page.evaluate(() => {
      const el = document.querySelector("#ov .mark.current"), cs = el && getComputedStyle(el);
      return cs && { width: cs.borderBottomWidth, style: cs.borderBottomStyle, color: cs.borderBottomColor };
    });
    check("the current move on the page is underlined in the warm yellow",
          under && under.width === "2px" && under.style === "solid" && under.color === rgb, { under, rgb });
    const plain = await page.evaluate(() => ({
      color: getComputedStyle(document.getElementById("bmbtn")).color,
      fill: getComputedStyle(document.querySelector("#bmbtn svg")).fill }));
    check("the plain icon is an outline in the text colour", plain.color !== rgb && plain.fill === "none", plain);

    const before = Date.now();
    await page.click("#bmbtn");
    st = await state(page);
    check("a tap on the icon sets a bookmark on the page shown", st.pressed === "true" && st.ribbon &&
          /^Bookmark set on page \d+, at /.test(st.msg), st);
    const icon = await page.evaluate(() => ({
      color: getComputedStyle(document.getElementById("bmbtn")).color,
      fill: getComputedStyle(document.querySelector("#bmbtn svg")).fill }));
    check("the icon fills in the warm yellow", icon.color === rgb && icon.fill === rgb, { icon, rgb });
    const kept = await stored(page);
    check("the bookmark keeps the page, the move, the chapter and the time",
          kept && kept.key === "chessbook-bookmarks:little.pdf:" + (await page.evaluate(() => window.READER.pageCount)) &&
          kept.value.bookmarks.length === 1 && kept.value.bookmarks[0].page === t.page &&
          kept.value.bookmarks[0].node === t.node && kept.value.bookmarks[0].chapter === "ch01.html" &&
          kept.value.bookmarks[0].at >= before && kept.value.bookmarks[0].at <= Date.now(), kept);
    const fit = await ribbonFits(page);
    check("the ribbon hangs from the top edge inside the page picture", fit.inside && fit.ribbon.top <= 1 &&
          fit.ribbon.h > fit.ribbon.w * 2.5, fit);
    check("the ribbon covers no move box or diagram", fit.hit.length === 0, fit);
    check("the ribbon is drawn in the warm yellow without a shadow", await page.evaluate((rgb) => {
      const poly = document.querySelector("#ribbon polygon");
      const cs = getComputedStyle(document.getElementById("ribbon"));
      return getComputedStyle(poly).fill === rgb && cs.boxShadow === "none" && cs.backgroundColor === "rgba(0, 0, 0, 0)";
    }, rgb));
    const only = await yellowElsewhere(page, rgb);
    check("the warm yellow colours no element but the icon, the ribbon and the current move", only.length === 0, only);
    await shot(page, "bookmark_1280_light.png");
    await page.emulateMedia({ colorScheme: "dark" });
    const dark = await tokenRgb(page);
    check("the bookmark keeps its colour in the dark scheme", dark === rgb, { dark, rgb });
    check("the warm yellow colours no other element in the dark scheme", (await yellowElsewhere(page, rgb)).length === 0);
    await shot(page, "bookmark_1280_dark.png");
    await page.emulateMedia({ colorScheme: "light" });

    // the ribbon shows on the bookmarked page only
    await page.click("#nextpage");
    await page.waitForFunction((p) => window.readerState.page === p + 1, t.page);
    st = await state(page);
    check("the next page shows no ribbon and the plain icon", !st.ribbon && st.pressed === "false", st);
    await page.click("#prevpage");
    await page.waitForFunction((p) => window.readerState.page === p, t.page);
    st = await state(page);
    check("back on the bookmarked page the ribbon and the filled icon return", st.ribbon && st.pressed === "true", st);
    // a reload: the bookmark persists
    await page.reload();
    await page.waitForFunction((p) => window.readerState && window.readerState.page === p, t.page);
    st = await state(page);
    check("the bookmark persists after a reload", st.ribbon && st.pressed === "true", st);

    // the ribbon removes the bookmark, with Undo for a few seconds
    await page.click("#ribbon");
    st = await state(page);
    check("a tap on the ribbon removes the bookmark", !st.ribbon && st.pressed === "false", st);
    check("one quiet line says so, with Undo", /^Bookmark removed\.\s*Undo$/.test(st.note.replace(/\s+/g, " ")) && st.undo, st);
    check("the removed bookmark is gone from the storage", (await stored(page)).value.bookmarks.length === 0);
    const noteBox = await rect(page, "#bmnote"), pageBox = await rect(page, "#pageimg");
    check("the line lies over the corner of the page", noteBox.x >= pageBox.x && noteBox.right <= pageBox.right + 0.5 &&
          noteBox.y >= pageBox.y && noteBox.y < pageBox.y + pageBox.h * 0.15, { noteBox, pageBox });
    await shot(page, "bookmark_removed_1280_light.png");
    await page.click("#bmundo");
    st = await state(page);
    check("Undo brings the bookmark back", st.ribbon && st.pressed === "true" && st.note === "" &&
          (await stored(page)).value.bookmarks[0].page === t.page, st);
    // the line goes by itself after a few seconds
    await page.click("#ribbon");
    await page.waitForFunction(() => document.getElementById("bmnote").textContent === "", null, { timeout: 12000 });
    check("the line goes away after a few seconds", true);
    // the move chosen again (the reload kept the page only), so that the bookmark names it
    await goTo(page, t);
    await page.click("#bmbtn");
    st = await state(page);
    check("the icon sets the bookmark again", st.ribbon && st.pressed === "true", st);
    // a second bookmark on another page: several per book, one per page at most
    await page.click("#nextpage");
    await page.waitForFunction((p) => window.readerState.page === p + 1, t.page);
    await page.click("#bmbtn");
    await page.click("#bmbtn");
    await page.click("#bmbtn");
    const two = await stored(page);
    check("a book holds several bookmarks, one per page at most",
          two.value.bookmarks.map((b) => b.page).join(",") === t.page + "," + (t.page + 1), two);
    const yellowSecond = await yellowElsewhere(page, rgb);
    check("on a page with no move chosen the yellow still colours nothing else", yellowSecond.length === 0, yellowSecond);

    // the contents page lists the bookmarks, each a link to the page and move
    await page.goto("file://" + path.resolve(dir, "index.html"));
    await page.waitForSelector("#bmlist");
    const list = await page.evaluate(() => ({
      text: document.getElementById("bmlist").textContent,
      links: Array.from(document.querySelectorAll("#bmlist a")).map((a) => a.getAttribute("href")) }));
    // (the link to the page with a move carries the key of the move's box: "#at=PAGE:NODE:KEY")
    const key = two.value.bookmarks[0].key;
    check("the contents page lists the bookmarks", list.text === "Bookmarks: page " + t.page + ", page " + (t.page + 1) + "." &&
          !!key && list.links[0] === "ch01.html#at=" + t.page + ":" + t.node + ":" + encodeURIComponent(key) &&
          list.links[1] === "ch01.html#at=" + (t.page + 1) + ":", { list, key });
    await shot(page, "bookmark_index_1280_light.png");
    await Promise.all([page.waitForURL(/ch01\.html#at=/), page.click("#bmlist a")]);
    await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
    st = await state(page);
    check("the link opens the chapter at the bookmarked page and move", st.page === t.page && st.node === t.node && st.ribbon, st);
    // the contents page of a build given bookmarks lists them before the browser stores any
    await page.evaluate(() => localStorage.clear());
    await page.goto("file://" + path.resolve(dir, "index.html"));
    const given = await page.evaluate(() => ({
      text: document.getElementById("bmlist").textContent,
      built: window.READER_INDEX_BOOKMARKS || null }));
    check("without stored bookmarks the contents page lists none", given.text === "", given);
    mode = "";
    check("no console errors on the desktop", out.errors.length === 0, out.errors);
    await ctx.close();

    // ---------------------------------------------------------------- an iPhone and an iPad
    for (const [name, opts, width] of [["iphone13", PHONE, 390], ["ipad_landscape", IPAD, 1194]]) {
      mode = name;
      ctx = await browser.newContext(opts);
      page = await openReader(ctx);
      await goTo(page, t);
      const phone = name === "iphone13";
      const bar = await page.evaluate(() => getComputedStyle(document.getElementById("mbar")).display !== "none");
      check(phone ? "the phone shows the bar at the foot of the screen" : "the tablet shows no phone bar", bar === phone, bar);
      if (phone) {
        const mb = await rect(page, "#mbm");
        check("the phone bar holds the bookmark icon within the screen", mb && mb.x >= 0 && mb.right <= width && mb.w >= 24, mb);
        await page.click("#mbm");
      } else await page.click("#bmbtn");
      st = await state(page);
      check("a tap sets the bookmark", st.ribbon && st.pressed === "true" && st.mpressed === "true", st);
      const f = await ribbonFits(page);
      check("the ribbon lies inside the page and over no move box", f.inside && f.hit.length === 0 && f.ribbon.w >= 12, f);
      const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check("no sideways scroll", wide <= 0, wide);
      const found = await yellowElsewhere(page, rgb);
      check("the warm yellow colours no element but the icons, the ribbon and the current move", found.length === 0, found);
      await page.evaluate(() => document.getElementById("pagebox").scrollIntoView({ block: "start" }));
      await page.waitForTimeout(300);
      await shot(page, "bookmark_" + width + "_light.png");
      await page.emulateMedia({ colorScheme: "dark" });
      await shot(page, "bookmark_" + width + "_dark.png");
      await page.emulateMedia({ colorScheme: "light" });
      await page.click("#ribbon");
      st = await state(page);
      check("a tap on the ribbon removes the bookmark with Undo", !st.ribbon && st.undo && st.mpressed === "false", st);
      if (phone) await shot(page, "bookmark_removed_390_light.png");
      await page.click("#bmundo");
      st = await state(page);
      check("Undo brings it back", st.ribbon && st.mpressed === "true", st);
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
