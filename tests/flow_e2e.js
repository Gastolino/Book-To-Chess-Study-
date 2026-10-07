// End-to-end test of the book flow in the browser app (tools/build_web.py), in Chromium:
// the sign of work, opening a book at its first page, the pages as one book drawn ten at a
// time, and a stored reading that other reading code made.
//
// Usage:
//   NODE_PATH=/opt/node22/lib/node_modules node tests/flow_e2e.js SITE_URL BOOK_PDF WORK_DIR SCREENS_DIR
//
// SITE_URL serves a site built with --local. For an iPhone 13 and an iPad held sideways, in a
// browser profile kept on disk, the test:
//   - loads the site (slowed down with ?pace=MS) and finds, while the app starts, the open book
//     with two pages of a 3 by 4 chequer and a turning page above a thin bar, the words under it;
//     with reduced motion the page does not turn;
//   - adds BOOK_PDF: the book opens at its first page in the reader while it is read, with the
//     small book at the top right of the top bar, which leaves the page where it is when it shows
//     and goes; a tap on it says what the program does; it is gone when the work is done;
//   - turns the pages: a swipe on the last page of a chapter shows the first page of the next;
//     typing a page number goes to that page in whatever chapter holds it; the pictures come
//     ten pages at a time, and a page whose picture has not come shows a light placeholder of
//     its size that fills in when it comes;
//   - (on the iPad) marks the stored reading as made by other reading code: the book opens from
//     it all the same, with "An improved reading is available." and Read again, and is not read
//     again until Read again is pressed, which reads it and opens it where the reader was.
// Screenshots (light and dark) of the start page at work, the book just opened, the top bar's
// small book and a placeholder filling in go to SCREENS_DIR. Prints one JSON object {ok,
// checks, errors, timings, screenshots, notes}; the exit code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [siteUrl, bookPdf, work, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], timings: {}, screenshots: [], notes: [] };
let mode = "";
function check(name, cond, detail) {
  out.checks.push({ mode, name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed [" + mode + "]: " + name + (detail !== undefined ? " (" + JSON.stringify(detail).slice(0, 600) + ")" : ""));
}
function note(text) { out.notes.push("[" + mode + "] " + text); }
const now = () => Date.now() / 1000;
const PHONE = Object.assign({}, devices["iPhone 13"]);
const IPAD = Object.assign({}, devices["iPad Pro 11 landscape"] || devices["iPad (gen 7) landscape"]);
const paced = siteUrl + (siteUrl.includes("?") ? "&" : "?") + "pace=1500";

async function run(browser, which) {
  mode = which;
  const opts = which === "iphone13" ? PHONE : IPAD;
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource: the server responded with a status of 404/.test(m.text()))
      out.errors.push("[" + which + "] " + m.text());
  });
  page.on("pageerror", (e) => out.errors.push("[" + which + "] " + String(e)));
  const shot = async (name, clip) => {
    const p = path.join(screens, name + "_" + which + ".png");
    await page.screenshot(clip ? { path: p, clip } : { path: p });
    out.screenshots.push(p);
  };
  const both = async (name, clip) => {
    await shot(name + "_light", clip);
    await page.emulateMedia({ colorScheme: "dark" });
    await page.waitForTimeout(200);
    await shot(name + "_dark", clip);
    await page.emulateMedia({ colorScheme: "light" });
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
      if (Date.now() - t0 > (timeout || 120000)) throw new Error("timed out waiting in the reader: " + fn.toString().slice(0, 200));
      await page.waitForTimeout(100);
    }
  };

  // ---------------------------------------------------------------- the start page at work
  await page.goto(paced);
  const loader = await page.evaluate(() => {
    const svg = document.querySelector("#loader .bookicon");
    const leaf = svg && svg.querySelector(".leaf");
    const all = svg ? svg.querySelectorAll("rect").length : 0;
    const inLeaf = leaf ? leaf.querySelectorAll("rect").length : 0;
    return { shown: document.getElementById("loader").classList.contains("on") &&
               getComputedStyle(document.getElementById("loader")).display !== "none",
             width: svg ? svg.getBoundingClientRect().width : 0, squares: all - inLeaf, inLeaf,
             anim: leaf ? getComputedStyle(leaf).animationName : null,
             bar: getComputedStyle(document.getElementById("bar")).height,
             words: document.getElementById("status").textContent };
  });
  // each page: 12 squares and its outline; the leaf the same
  check("while the app starts, the start page shows the book with two pages of 3 by 4 squares and a turning page",
    loader.shown && loader.squares === 2 * 13 && loader.inLeaf === 13 && loader.anim === "leaf", loader);
  check("the book is about 72 to 96 pixels wide, over a 2 pixel bar, with the words under it",
    loader.width >= 72 && loader.width <= 96 && loader.bar === "2px" && loader.words.length > 0, loader);
  await both("flow_start_loading");
  await page.emulateMedia({ reducedMotion: "reduce" });
  const still = await page.evaluate(() => getComputedStyle(document.querySelector("#loader .leaf")).animationName);
  check("with reduced motion the page does not turn", still === "none", still);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.waitForFunction(() => typeof ready !== "undefined" && ready === true, null, { timeout: 300000 });
  check("the book and the bar go when the app is ready", await page.evaluate(() =>
    !document.getElementById("loader").classList.contains("on")));

  // ---------------------------------------------------------------- a new book opens at its first page
  const t0 = now();
  await page.setInputFiles("#file", bookPdf);
  await page.waitForFunction(() => document.getElementById("loader").classList.contains("on"), null, { timeout: 60000 });
  await waitFrame(() => window.READER && window.readerState && window.readerState.page, null, 1800000);
  out.timings[which + ": add until the first page shows (s)"] = Math.round((now() - t0) * 10) / 10;
  const first = await inFrame(() => ({ page: window.readerState.page, file: window.READER.chapter.file,
    total: document.getElementById("pagetotal").textContent, count: window.READER.pageCount }));
  check("a new book opens at its first page", first.page === 1, first);
  await waitFrame(() => !document.getElementById("pagebox").classList.contains("waiting"), null, 300000);
  const busy = await page.evaluate(() => {
    const b = document.getElementById("busy"), r = b.getBoundingClientRect();
    return { on: b.classList.contains("on"), vis: getComputedStyle(b).visibility, w: r.width, right: window.innerWidth - r.right,
             leaf: b.querySelectorAll(".leaf").length, loading };
  });
  check("while the book is read, the small book shows at the top right of the top bar",
    busy.on && busy.vis === "visible" && busy.leaf === 1 && busy.w <= 30 && busy.right <= 24, busy);
  // the small book takes its room whether it shows or not: the page does not move
  const shift = await page.evaluate(async () => {
    const b = document.getElementById("busy"), v = () => document.getElementById("view").getBoundingClientRect().top;
    const t1 = v(); b.classList.remove("on"); await new Promise((r) => requestAnimationFrame(r));
    const t2 = v(); b.classList.add("on"); await new Promise((r) => requestAnimationFrame(r));
    return { on: t1, off: t2 };
  });
  check("the small book appears and goes without moving the reader", shift.on === shift.off, shift);
  const h0 = await page.evaluate(() => document.getElementById("top").getBoundingClientRect().height);
  await page.click("#busy");
  const said = await page.evaluate(() => {
    const tip = document.getElementById("tip"), took = document.getElementById("took");
    return { tip: tip.hidden ? "" : tip.textContent, note: document.getElementById("note").textContent,
             h: document.getElementById("top").getBoundingClientRect().height,
             oneLine: took.scrollHeight <= took.clientHeight + 1 && getComputedStyle(took).whiteSpace === "nowrap" };
  });
  check("a tap on the small book says what the program does, under the bar, moving nothing; the status keeps one line",
    said.tip.length > 0 && said.note === "" && Math.abs(said.h - h0) < 1 && said.oneLine, { said, h0 });
  await inFrame(() => document.getElementById("pageimg").decode().catch(() => null));
  await both("flow_book_opened");
  const topH = await page.evaluate(() => document.getElementById("top").getBoundingClientRect().height);
  await both("flow_topbar_busy", { x: 0, y: 0, width: opts.viewport.width, height: Math.ceil(topH) + 2 });
  await page.evaluate(() => { document.getElementById("note").textContent = ""; document.getElementById("tip").hidden = true; });

  // ---------------------------------------------------------------- the top bar while scrolling
  const barAt = () => page.evaluate(() => ({ top: document.getElementById("top").getBoundingClientRect().bottom,
                                             view: document.getElementById("view").getBoundingClientRect().top,
                                             away: TOPBAR.away() }));
  await inFrame(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  const shown0 = await barAt();
  await inFrame(() => window.scrollBy(0, 150));
  await page.waitForTimeout(150);
  await inFrame(() => window.scrollBy(0, 250));
  await page.waitForTimeout(500);
  const gone = await barAt();
  if (which === "iphone13") {
    check("the top bar goes away as the page scrolls down, and the reader takes its room",
          gone.away && gone.top <= 1 && Math.abs(gone.view) <= 1 && shown0.view > 20, { shown0, gone });
    await both("flow_topbar_away");
    await inFrame(() => window.scrollBy(0, -40));
    await page.waitForTimeout(500);
    const back = await barAt();
    check("it comes back as soon as the page scrolls up", !back.away && Math.abs(back.view - shown0.view) <= 1, { back, shown0 });
  } else {
    check("on a wider screen the top bar stays", !gone.away && Math.abs(gone.view - shown0.view) <= 1, { shown0, gone });
  }
  await inFrame(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);

  // ---------------------------------------------------------------- one book, page after page
  const ch = await inFrame(() => window.READER.chapter);
  if (ch.end < first.count) {
    await inFrame((p) => { location.hash = "#page=" + p; }, ch.end);
    await waitFrame((p) => window.readerState.page === p, ch.end);
    // a swipe from right to left on the last page of the chapter
    await inFrame(() => {
      const box = document.getElementById("pagescroll"), r = box.getBoundingClientRect();
      const y = r.top + Math.min(r.height / 2, 200);
      const touch = (x) => new Touch({ identifier: 1, target: box, clientX: x, clientY: y });
      box.dispatchEvent(new TouchEvent("touchstart", { touches: [touch(r.right - 20)], changedTouches: [touch(r.right - 20)], bubbles: true }));
      box.dispatchEvent(new TouchEvent("touchend", { touches: [], changedTouches: [touch(r.left + 20)], bubbles: true }));
    });
    const nx = await waitFrame((c) => window.READER && window.READER.chapter.file !== c.file && window.readerState.page &&
      { page: window.readerState.page, file: window.READER.chapter.file }, ch, 300000);
    check("a swipe on the last page of a chapter shows the first page of the next chapter", nx.page === ch.end + 1, { nx, ch });
  } else note("one chapter only: no swipe across chapters");
  // a page number typed: the page, in whatever chapter holds it, with a placeholder until its picture comes
  await page.evaluate(() => {
    // the pictures come late now, so that the placeholder can be seen
    const on = worker.onmessage;
    worker.onmessage = (e) => { if (e.data && e.data.type === "drawn") setTimeout(() => on(e), 2500); else on(e); };
  });
  // a page of another chapter (whose reader holds no pictures yet), with the app's pictures
  // forgotten, so that it waits for its picture
  const cur = await inFrame(() => window.READER.chapter);
  const far = cur.start <= 1 ? first.count : 1;
  await page.evaluate((n) => PICS.book(null, n), first.count);
  const label = await inFrame((p) => { const f = window.READER.folios[p - 1]; return f != null ? String(f) : String(p); }, far);
  await inFrame((v) => { const i = document.getElementById("pagenum"); i.value = v; i.dispatchEvent(new Event("change")); }, label);
  const held = await waitFrame((p) => window.READER && window.readerState.page === p &&
    { waiting: document.getElementById("pagebox").classList.contains("waiting"),
      h: document.getElementById("pagebox").getBoundingClientRect().height,
      w: document.getElementById("pagebox").getBoundingClientRect().width, file: window.READER.chapter.file }, far, 300000);
  check("a typed page number goes to that page", true, held);
  if (held.waiting) {
    check("a page whose picture has not come shows a placeholder of its size", held.h > held.w * 0.8, held);
    await shot("flow_placeholder");
    await waitFrame(() => !document.getElementById("pagebox").classList.contains("waiting"), null, 300000);
    await inFrame(() => document.getElementById("pageimg").decode().catch(() => null));
    await shot("flow_placeholder_filled");
    check("the placeholder fills in when the picture comes", true);
  } else note("the picture of page " + far + " was there already");
  const stats = await page.evaluate(() => Object.assign({}, window.pictureStats));
  check("the pictures come ten pages at a time", stats.draws >= 1 && stats.drawn <= 10 * stats.draws, stats);
  note("pictures: " + JSON.stringify(stats));
  const kept = await inFrame(() => Object.keys(window.READER ? JSON.parse(document.getElementById("images").textContent) : {}).length);
  note("pictures embedded in the chapter file: " + kept);
  check("the chapter files of the app hold no pictures", kept === 0, kept);

  // ---------------------------------------------------------------- the work ends
  await page.waitForFunction(() => document.body.dataset.book === "read", null, { timeout: 3600000 });
  await page.waitForFunction(() => !document.getElementById("busy").classList.contains("on"), null, { timeout: 600000 });
  check("the small book is gone when the work is done", await page.evaluate(() =>
    getComputedStyle(document.getElementById("busy")).visibility === "hidden"));

  // ---------------------------------------------------------------- a reading of other reading code
  if (which === "ipad") {
    const id = await page.evaluate(() => LIB.current.id);
    await page.waitForFunction(() => document.body.dataset.saved === LIB.current.id, null, { timeout: 600000 });
    const place = await inFrame(() => ({ page: window.readerState.page }));
    // the stored reading's header names other reading code
    await page.evaluate(async (id) => {
      const db = await new Promise((r) => { const q = indexedDB.open("chessbook-library"); q.onsuccess = () => r(q.result); });
      const blob = await new Promise((r) => { const q = db.transaction("files").objectStore("files").get(id + ":reading"); q.onsuccess = () => r(q.result); });
      const raw = new Uint8Array(await new Response(blob.stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer());
      const text = new TextDecoder("latin1").decode(raw.subarray(0, 400));
      const m = /"version": "([0-9a-f]{16})"/.exec(text);
      const at = text.indexOf(m[1]);
      raw.set(new TextEncoder().encode("0000000000000000"), at);
      const gz = await new Response(new Blob([raw]).stream().pipeThrough(new CompressionStream("gzip"))).blob();
      await new Promise((r) => { const t = db.transaction("files", "readwrite"); t.objectStore("files").put(gz, id + ":reading"); t.oncomplete = r; });
      db.close();
    }, id);
    await page.evaluate(() => { SESSION.clear(true); });
    await page.goto(siteUrl);
    await page.waitForFunction(() => document.body.classList.contains("library") && typeof ready !== "undefined" && ready, null, { timeout: 300000 });
    await page.evaluate(() => {
      window.__sent = [];
      const post = worker.postMessage.bind(worker);
      worker.postMessage = (m, t) => { window.__sent.push(m.type); return post(m, t); };
    });
    await page.click("#books li.book[data-id='" + id + "'] .open");
    await waitFrame((p) => window.READER && window.readerState.page === p, place.page, 300000);
    await page.waitForFunction(() => /An improved reading is available/.test(document.getElementById("note").textContent), null, { timeout: 60000 });
    const offer = await page.evaluate(() => ({ again: !document.getElementById("again").hidden, sent: window.__sent.slice(),
      note: document.getElementById("note").textContent }));
    check("a reading of other reading code opens without being read again, and offers Read again",
      offer.again && offer.sent.includes("restore") && !offer.sent.includes("process"), offer);
    await shot("flow_improved_reading");
    await page.click("#again");
    await page.waitForFunction(() => window.__sent.includes("process"), null, { timeout: 60000 });
    await waitFrame((p) => window.READER && window.readerState.page === p, place.page, 1800000);
    check("Read again reads the book and opens it where the reader was", true, place);
  }
  await ctx.close();
}

(async () => {
  fs.mkdirSync(screens, { recursive: true });
  fs.mkdirSync(work, { recursive: true });
  const exe = process.env.CHROMIUM || "/opt/pw-browsers/chromium";
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  try {
    for (const m of ["iphone13", "ipad"]) await run(browser, m);
    mode = "";
    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (err) {
    out.failure = String(err && err.stack ? err.stack : err);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
