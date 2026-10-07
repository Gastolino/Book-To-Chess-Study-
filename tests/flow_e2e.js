// End-to-end test of the book flow in the browser app (tools/build_web.py), in Chromium:
// the sign of work, opening a book at its first page, the pages as one book drawn ten at a
// time, and a stored reading that other reading code made.
//
// Usage:
//   NODE_PATH=/opt/node22/lib/node_modules node tests/flow_e2e.js SITE_URL BOOK_PDF WORK_DIR SCREENS_DIR [STATIC_DIR]
//
// SITE_URL serves a site built with --local; STATIC_DIR, when given, holds the reader of the same
// book written to disk (reader.build_reader). For an iPhone 13 and an iPad held sideways, in a
// browser profile kept on disk, the test:
//   - loads the site (slowed down with ?pace=MS) and finds, while the app starts, the revolving
//     book (four pages of a 3 by 3 chequer fanned about the spine, and four more that turn a
//     quarter turn each about the centre, clockwise, one at a time, then rest) above a thin
//     bar, the words under it; with reduced motion the pages do not turn and the book stands whole;
//   - adds BOOK_PDF: the book opens at its first page in the reader while it is read, with the
//     small book at the right of the top bar, just left of Library, which leaves the page where
//     it is when it shows and goes; a tap on it says what the program does, in a slip under the
//     bar that a tap puts away; it is gone when the work is done;
//   - finds the top bar on one line (on the phone, and on the iPad held sideways and upright): the
//     book's name, the small book, then Library in the right-hand corner, without the words of the
//     work; the reader's own bar shows the chapter without the book's name, which the reader on
//     disk keeps; on the phone and the upright iPad the bar goes away as the page scrolls down,
//     stays away while it scrolls up part of the way and comes back at the top; held sideways it
//     stays, and an upright iPad turned sideways brings it back;
//   - turns the pages (on the phone and the upright iPad): a swipe on the enlarged last page of a
//     chapter, read down so that the top bar has gone, slides the page out and the place of the
//     next page in, and the next chapter's reader shows that page enlarged, at its top left, with
//     the bar still away; a swipe back from there with the bar shown lands on the chapter before's
//     last page at its bottom right, just above the board or the bar, and the bar does not come
//     back and go again as the chapters change;
//     typing a page number goes to that page in whatever chapter holds it; the pictures come
//     ten pages at a time, and a page whose picture has not come shows a light placeholder of
//     its size that fills in when it comes;
//   - (on the iPad) marks the stored reading as made by other reading code: the book opens from
//     it all the same, with "An improved reading is available." and Read again, and is not read
//     again until Read again is pressed, which reads it and opens it where the reader was.
// Screenshots (light and dark) of the start page at work, the book just opened, the top bar's
// small book, the top bar's line at each size and away, the bar of the reader on disk and a
// placeholder filling in go to SCREENS_DIR. Prints one JSON object {ok,
// checks, errors, timings, screenshots, notes}; the exit code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [siteUrl, bookPdf, work, screens, staticDir] = process.argv.slice(2);
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
    const leaves = svg ? [...svg.querySelectorAll(".leaf")] : [];
    // a page is drawn as its face, its dark squares and its edge (the one path without a fill)
    const dark = svg ? [...svg.querySelectorAll('path[fill="var(--book-dark)"]')] : [];
    return { shown: document.getElementById("loader").classList.contains("on") &&
               getComputedStyle(document.getElementById("loader")).display !== "none",
             width: svg ? svg.getBoundingClientRect().width : 0,
             pages: svg ? svg.querySelectorAll('path[fill="none"]').length : 0, turning: leaves.length,
             inLeaf: leaves.map((g) => g.querySelectorAll("path").length),
             squares: dark.map((p) => (p.getAttribute("d").match(/M/g) || []).length),
             anim: leaves.map((g) => getComputedStyle(g).animationName),
             bar: getComputedStyle(document.getElementById("bar")).height,
             words: document.getElementById("status").textContent };
  });
  // six pages, each turning in on its own; each page's face carries dark squares of the chequer
  check("while the app starts, the start page shows the revolving book: six chequered pages, each turning in",
    loader.shown && loader.pages === 6 && loader.turning === 6 && loader.inLeaf.every((n) => n === 3) &&
    loader.squares.length === 6 && loader.squares.every((n) => n >= 2) &&
    loader.anim.every((a) => a === "leaf"), loader);
  check("the book is about 72 to 96 pixels wide, over a 2 pixel bar, with the words under it",
    loader.width >= 72 && loader.width <= 96 && loader.bar === "2px" && loader.words.length > 0, loader);
  // the book's animations held at moments of a round: where each page's pivot lands on the screen,
  // which way the page's own "up" points (clockwise from the top, in degrees) and how opaque it is
  const turns = await page.evaluate(() => {
    const svg = document.querySelector("#loader .bookicon"), box = svg.getBoundingClientRect();
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2, r = svg.viewBox.baseVal.width / 2;
    const anims = svg.getAnimations({ subtree: true });
    const leaves = [...svg.querySelectorAll(".leaf")];
    const round = parseFloat(getComputedStyle(leaves[0]).animationDuration);
    const offsets = anims[0].effect.getKeyframes().map((k) => k.offset);
    const at = (t) => {
      for (const a of anims) { a.pause(); a.currentTime = t * 1000; }
      return leaves.map((g) => {
        const m = g.getScreenCTM(), o = new DOMPoint(0, 0).matrixTransform(m);
        const top = new DOMPoint(0, -r).matrixTransform(m);
        return { off: Math.hypot(o.x - cx, o.y - cy), opacity: parseFloat(getComputedStyle(g).opacity),
                 angle: Math.round((Math.atan2(top.x - o.x, o.y - top.y) * 180 / Math.PI + 360) % 360) };
      });
    };
    const delays = leaves.map((g) => parseFloat(getComputedStyle(g).animationDelay));
    const res = { round, offsets, n: anims.length, delays, start: [], middle: [], landed: [], gone: [], whole: null,
                  where: [] };
    const land = offsets[1] * round, leave = offsets[3] * round;
    delays.forEach((d, i) => {
      res.start.push(at(d + 0.001)[i]);
      res.middle.push(at(d + land / 2)[i]);
      res.landed.push(at(d + land)[i]);
      res.gone.push(at(d + leave)[i]);
    });
    // a moment when every page has come in and none has gone on yet: the whole book
    res.whole = at(Math.max(...delays) + land + 0.02);
    // where each page lies about the middle of the spine (clockwise from the top, in degrees)
    res.where = leaves.map((g) => {
      const b = g.getBBox(), x = b.x + b.width / 2, y = b.y + b.height / 2;
      return Math.round((Math.atan2(x, -y) * 180 / Math.PI + 360) % 360);
    });
    for (const a of anims) a.play();
    return res;
  });
  {
    const order = turns.delays.map((d, i) => [d, i]).sort((a, b) => a[0] - b[0]).map((x) => x[1]);
    const ok = turns.n === 6 && turns.round >= 1.6 && turns.round <= 3 &&
      // one after the other, 0.2 s apart, and in the order of their places clockwise round the spine
      order.every((i, k) => Math.abs(turns.delays[i] - 0.2 * k) < 0.01) &&
      order.every((i, k) => k === 0 || (turns.where[i] - turns.where[order[0]] + 360) % 360 >
                                       (turns.where[order[k - 1]] - turns.where[order[0]] + 360) % 360) &&
      // each turns about the middle of the spine
      [...turns.start, ...turns.middle, ...turns.landed, ...turns.gone, ...turns.whole].every((p) => p.off < 0.5) &&
      // it comes in from a quarter turn back, turning clockwise, and fades in as it comes
      turns.start.every((p) => p.angle === 270 && p.opacity < 0.05) &&
      turns.middle.every((p) => p.angle > 280 && p.angle < 350 && p.opacity > 0.2 && p.opacity < 0.95) &&
      turns.landed.every((p) => p.angle === 0 && p.opacity > 0.99) &&
      // it goes on clockwise by another quarter turn, fading out
      turns.gone.every((p) => p.angle === 90 && p.opacity < 0.05) &&
      // and for a moment the whole book stands
      turns.whole.every((p) => p.angle === 0 && p.opacity > 0.99);
    check("the pages turn in one after the other about the middle of the spine, all clockwise, and the book stands whole",
      ok, turns);
  }
  await both("flow_start_loading");
  await page.emulateMedia({ reducedMotion: "reduce" });
  const still = await page.evaluate(() => {
    const svg = document.querySelector("#loader .bookicon"), leaves = [...svg.querySelectorAll(".leaf")];
    return { anim: leaves.map((g) => getComputedStyle(g).animationName),
             whole: leaves.every((g) => getComputedStyle(g).visibility === "visible" &&
                                        parseFloat(getComputedStyle(g).opacity) === 1 &&
                                        ["none", "matrix(1, 0, 0, 1, 0, 0)"].includes(getComputedStyle(g).transform)) };
  });
  check("with reduced motion the pages do not turn and the book stands whole",
    still.anim.length === 6 && still.anim.every((a) => a === "none") && still.whole, still);
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
    const lib = document.getElementById("another").getBoundingClientRect();
    return { on: b.classList.contains("on"), vis: getComputedStyle(b).visibility, w: r.width,
             gap: lib.left - r.right, libRight: window.innerWidth - lib.right,
             leaf: b.querySelectorAll(".leaf").length, loading };
  });
  check("while the book is read, the small book shows at the right of the top bar, just left of Library",
    busy.on && busy.vis === "visible" && busy.leaf === 6 && busy.w <= 30 && busy.gap >= 0 && busy.gap <= 20 &&
    busy.libRight <= 17, busy);
  // the small book takes its room whether it shows or not: the page does not move
  const shift = await page.evaluate(async () => {
    const b = document.getElementById("busy"), v = () => document.getElementById("view").getBoundingClientRect().top;
    const t1 = v(); b.classList.remove("on"); await new Promise((r) => requestAnimationFrame(r));
    const t2 = v(); b.classList.add("on"); await new Promise((r) => requestAnimationFrame(r));
    return { on: t1, off: t2 };
  });
  check("the small book appears and goes without moving the reader", shift.on === shift.off, shift);
  const h0 = await page.evaluate(() => document.getElementById("top").getBoundingClientRect().height);
  // the words of the work just before the tap and just after it (they may change in between)
  const words0 = await page.evaluate(() => document.getElementById("took").textContent);
  await page.click("#busy");
  const said = await page.evaluate(() => {
    const tip = document.getElementById("tip"), top = document.getElementById("top").getBoundingClientRect();
    return { tip: tip.hidden ? "" : tip.textContent, words: document.getElementById("took").textContent, loading,
             note: document.getElementById("note").textContent, h: top.height,
             under: tip.getBoundingClientRect().top >= top.bottom - 2 };
  });
  check("a tap on the small book says what the program does, under the bar, moving nothing",
    said.tip.length > 0 && (!said.loading || (said.words && said.tip.startsWith(said.words)) || (words0 && said.tip.startsWith(words0))) &&
    said.note === "" && said.under && Math.abs(said.h - h0) < 1, { said, words0, h0 });
  await inFrame(() => document.getElementById("pageimg").decode().catch(() => null));
  await both("flow_book_opened");
  const topH = await page.evaluate(() => document.getElementById("top").getBoundingClientRect().height);
  await both("flow_topbar_busy", { x: 0, y: 0, width: opts.viewport.width, height: Math.ceil(topH) + 2 });
  await page.click("#tip");
  check("a tap on the slip puts it away", await page.evaluate(() => document.getElementById("tip").hidden));
  await page.evaluate(() => { document.getElementById("note").textContent = ""; });

  // ---------------------------------------------------------------- the reader's own bar names the chapter only
  const own = await inFrame(() => {
    const b = document.querySelector(".where .book"), h = document.querySelector(".where h1");
    return { book: b ? b.textContent : null, shown: !!b && b.getClientRects().length > 0,
             chapter: h ? h.textContent : "", chapterShown: !!h && h.getClientRects().length > 0 };
  });
  check("in the app the reader's bar shows the chapter without the book's name",
    !!own.book && !own.shown && own.chapter.length > 0 && own.chapterShown, own);
  if (staticDir) {
    // the same book's reader opened from disk keeps the name beside the chapter
    const sp = await ctx.newPage();
    const file = fs.readdirSync(staticDir).filter((f) => /^ch\d+\.html$/.test(f)).sort()[0];
    await sp.goto("file://" + path.resolve(staticDir, file));
    const st = await sp.evaluate(() => {
      const b = document.querySelector(".where .book");
      return { book: b ? b.textContent : null, shown: !!b && b.getClientRects().length > 0 && getComputedStyle(b).visibility === "visible" };
    });
    check("the reader opened from disk names the book in its bar", st.shown && st.book === own.book, { st, own });
    const p = path.join(screens, "flow_static_reader_bar_" + which + ".png");
    await sp.screenshot({ path: p, clip: { x: 0, y: 0, width: opts.viewport.width, height: 160 } });
    out.screenshots.push(p);
    await sp.close();
  } else note("no reader on disk to compare with");

  // ---------------------------------------------------------------- the top bar: one line, and away while the page scrolls
  // the book's name on the left (one line, cut short with an ellipsis), the small book, then Library
  // in the right-hand corner; the words of the work are not in the bar
  const barLine = () => page.evaluate(() => {
    const el = (id) => document.getElementById(id), r = (id) => el(id).getBoundingClientRect();
    const t = r("booktitle"), b = r("busy"), l = r("another"), mid = (x) => (x.top + x.bottom) / 2;
    const name = el("booktitle"), took = el("took");
    return { title: name.textContent, known: LIB.on && LIB.current ? LIB.titleOf(LIB.current.book) : null,
             left: Math.round(t.left), right: Math.round(window.innerWidth - l.right), h: r("top").height,
             order: t.left < t.right && t.right <= b.left && b.right <= l.left,
             line: Math.abs(mid(t) - mid(l)) <= 3 && Math.abs(mid(b) - mid(l)) <= 4,
             oneLine: name.scrollHeight <= name.clientHeight + 1 && getComputedStyle(name).whiteSpace === "nowrap",
             // the buttons to tap, a finger's size (24 px at least each way)
             taps: [b, l].map((x) => [Math.round(x.width), Math.round(x.height)]),
             loading, words: took.textContent,
             wordsShown: took.getClientRects().length > 0 || (took.textContent !== "" && el("top").innerText.includes(took.textContent)) };
  });
  const barAt = () => page.evaluate(() => ({ top: document.getElementById("top").getBoundingClientRect().bottom,
                                             view: document.getElementById("view").getBoundingClientRect().top,
                                             y: document.getElementById("view").contentWindow.scrollY,
                                             away: TOPBAR.away() }));
  // compact: a phone, or a tablet held upright, where the bar goes away
  const scrolling = async (compact, tag) => {
    await inFrame(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
    const shown0 = await barAt();
    // the slip under the bar (a tap on the small book) goes with the bar
    await page.evaluate(() => tip("The words of the work."));
    await inFrame(() => window.scrollBy(0, 150));
    await page.waitForTimeout(150);
    await inFrame(() => window.scrollBy(0, 250));
    await page.waitForTimeout(500);
    const gone = await barAt();
    if (!compact) {
      check("on a wider screen the top bar stays", !gone.away && Math.abs(gone.view - shown0.view) <= 1, { shown0, gone, tag });
      return;
    }
    check("the top bar goes away as the page scrolls down, and the reader takes its room",
          gone.away && gone.top <= 1 && Math.abs(gone.view) <= 1 && shown0.view > 20, { shown0, gone, tag });
    check("the slip under the bar goes away with it", await page.evaluate(() => document.getElementById("tip").hidden));
    // a line that comes under the bar while it is away (a note, Read again), or goes, leaves the
    // bar out of sight and the reader where it was
    await page.evaluate(() => status("A note under the bar."));
    await page.waitForTimeout(100);
    const noted = await barAt();
    await page.evaluate(() => { document.getElementById("again").hidden = false; });
    await page.waitForTimeout(100);
    const again = await barAt();
    await page.evaluate(() => { document.getElementById("again").hidden = true; status(""); });
    await page.waitForTimeout(100);
    const cleared = await barAt();
    check("while the bar is away, a line that comes under it or goes leaves it out of sight and the reader in its place",
          [noted, again, cleared].every((b) => b.away && b.top <= 1 && Math.abs(b.view) <= 1), { noted, again, cleared, tag });
    await both("flow_topbar_away_" + tag);
    await inFrame(() => window.scrollBy(0, -40));
    await page.waitForTimeout(500);
    const up1 = await barAt();
    await inFrame(() => window.scrollBy(0, -200));
    await page.waitForTimeout(500);
    const up2 = await barAt();
    check("it stays away while the page scrolls up part of the way",
          up1.away && up2.away && up2.y > 60 && up2.y < gone.y && Math.abs(up2.view) <= 1, { gone, up1, up2, tag });
    await inFrame(() => window.scrollTo(0, 0));
    await page.waitForTimeout(500);
    const back = await barAt();
    check("it comes back when the page is scrolled all the way to the top",
          !back.away && Math.abs(back.view - shown0.view) <= 1, { back, shown0, tag });
  };
  // the phone's whole screen (390 by 844); the iPad held sideways, then upright
  const sizes = which === "iphone13" ? [{ width: 390, height: 844 }] : [{ width: 1180, height: 820 }, { width: 820, height: 1180 }];
  for (const size of sizes) {
    const tag = size.width + "x" + size.height;
    await page.setViewportSize(size);
    await page.waitForTimeout(500);
    const bar = await barLine();
    check("the top bar is one line: the book's name, the small book, then Library in the right-hand corner",
      bar.title.length > 0 && bar.title === bar.known && bar.order && bar.line && bar.left <= 17 && bar.right <= 17 &&
      bar.oneLine && bar.h < 50, Object.assign({ tag }, bar));
    check("the words of the work do not show in the top bar", (!bar.loading || bar.words.length > 0) && !bar.wordsShown,
      Object.assign({ tag }, bar));
    check("the small book and Library are a finger's size to tap", bar.taps.every(([w, h]) => w >= 24 && h >= 24),
      Object.assign({ tag }, bar));
    await both("flow_topbar_line_" + tag, { x: 0, y: 0, width: size.width, height: Math.ceil(bar.h) + 2 });
    await scrolling(size.width <= 700 || size.height > size.width, tag);
  }
  if (which !== "iphone13") {
    // an upright tablet turned sideways while the bar is away: the bar comes back at once
    await inFrame(() => window.scrollBy(0, 150));
    await page.waitForTimeout(150);
    await inFrame(() => window.scrollBy(0, 250));
    await page.waitForTimeout(500);
    const away = await barAt();
    await page.setViewportSize({ width: 1180, height: 820 });
    await page.waitForTimeout(500);
    const turned = await barAt();
    check("an upright tablet turned sideways brings the top bar back", away.away && !turned.away && turned.view > 20, { away, turned });
  }
  await page.setViewportSize(opts.viewport);
  await page.waitForTimeout(500);
  await inFrame(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);

  // ---------------------------------------------------------------- one book, page after page
  const ch = await inFrame(() => window.READER.chapter);
  if (ch.end < first.count) {
    // (on the compact layouts, where the top bar goes away: the phone, and the tablet held upright)
    if (which !== "iphone13") { await page.setViewportSize({ width: 820, height: 1180 }); await page.waitForTimeout(500); }
    await inFrame((p) => { location.hash = "#page=" + p; }, ch.end);
    await waitFrame((p) => window.readerState.page === p, ch.end);
    // the page enlarged and at its right edge, so that a swipe to the left turns it
    await inFrame(() => {
      const bar = document.getElementById("mbar");
      (getComputedStyle(bar).display !== "none" ? document.getElementById("mzoom") : document.getElementById("zoom")).click();
      const ps = document.getElementById("pagescroll");
      ps.scrollLeft = ps.scrollWidth;
    });
    // read down the page, so that the top bar goes away
    await inFrame(() => window.scrollBy(0, 150));
    await page.waitForTimeout(150);
    await inFrame(() => window.scrollBy(0, 250));
    await page.waitForTimeout(500);
    const awayBefore = await barAt();
    // a swipe from right to left on the last page of the chapter
    const turned = await inFrame(() => {
      const box = document.getElementById("pagescroll"), r = box.getBoundingClientRect();
      const y = r.top + Math.min(r.height / 2, 200);
      const touch = (x) => new Touch({ identifier: 1, target: box, clientX: x, clientY: y });
      box.dispatchEvent(new TouchEvent("touchstart", { touches: [touch(r.right - 20)], changedTouches: [touch(r.right - 20)], bubbles: true }));
      box.dispatchEvent(new TouchEvent("touchend", { touches: [], changedTouches: [touch(r.left + 20)], bubbles: true }));
      return { turning: box.classList.contains("turning"), stage: !!document.querySelector(".turnstage"),
               sheet: document.getElementById("pagebox").classList.contains("waiting") };
    });
    check("on a chapter's last page a swipe slides the page out and the place of the next page in",
          turned.turning && turned.stage && turned.sheet, turned);
    const nx = await waitFrame((c) => window.READER && window.READER.chapter.file !== c.file && window.readerState.page &&
      { page: window.readerState.page, file: window.READER.chapter.file }, ch, 300000);
    check("a swipe on the last page of a chapter shows the first page of the next chapter", nx.page === ch.end + 1, { nx, ch });
    // the next chapter's reader shows that page enlarged, at its top left
    await waitFrame(() => !document.getElementById("pagebox").classList.contains("waiting"), null, 300000);
    await page.waitForTimeout(600);
    const at = await inFrame(() => {
      const ps = document.getElementById("pagescroll");
      return { zoom: ps.classList.contains("zoom"), sl: ps.scrollLeft, hash: location.hash,
               top: document.getElementById("pagebox").getBoundingClientRect().top };
    });
    check("the next chapter's reader shows the page enlarged where the turn left it, at its top left",
          at.zoom && at.sl === 0 && Math.abs(at.top) <= 1.5 && /turn=1/.test(at.hash), at);
    const awayAfter = await barAt();
    check("a turn into the next chapter keeps the top bar away, and the page at the top of the screen",
          awayBefore.away && awayAfter.away && Math.abs(awayAfter.view) <= 1, { awayBefore, awayAfter, at });
    await shot("flow_chapter_turn");
    // back into the chapter before, with the top bar shown: the page lands at its bottom right,
    // its foot just above the board or the bar at the foot of the screen, and the bar, once it
    // goes as the page scrolls down to that place, does not come back and go again
    // (after the reader has settled on its landing: until then it lands again when its window
    // changes size, as the bar coming back would make it)
    await page.waitForTimeout(1600);
    await inFrame(() => window.scrollTo(0, 0));
    await page.waitForTimeout(500);
    const shownBack = await barAt();
    await page.evaluate(() => {
      window.__bar = [];
      const tick = () => { window.__bar.push(TOPBAR.away()); if (window.__bar.length < 600) requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
    });
    await inFrame(() => {
      const box = document.getElementById("pagescroll"), r = box.getBoundingClientRect();
      const y = r.top + Math.min(r.height / 2, 200);
      const touch = (x) => new Touch({ identifier: 1, target: box, clientX: x, clientY: y });
      box.dispatchEvent(new TouchEvent("touchstart", { touches: [touch(r.left + 20)], changedTouches: [touch(r.left + 20)], bubbles: true }));
      box.dispatchEvent(new TouchEvent("touchend", { touches: [], changedTouches: [touch(r.right - 20)], bubbles: true }));
    });
    await waitFrame((c) => window.READER && window.READER.chapter.file === c.file && window.readerState.page === c.end, ch, 300000);
    await waitFrame(() => !document.getElementById("pagebox").classList.contains("waiting"), null, 300000);
    await page.waitForTimeout(800);
    const back = await inFrame(() => {
      const ps = document.getElementById("pagescroll"), r = document.getElementById("pagebox").getBoundingClientRect();
      const bar = document.getElementById("mbar"), stuck = document.body.classList.contains("stickboard");
      const foot = stuck ? document.getElementById("boardblock").getBoundingClientRect().top :
        getComputedStyle(bar).display !== "none" ? bar.getBoundingClientRect().top : window.innerHeight;
      return { zoom: ps.classList.contains("zoom"), sl: ps.scrollLeft, max: ps.scrollWidth - ps.clientWidth,
               bottom: r.bottom, foot, hash: location.hash };
    });
    const flips = await page.evaluate(() => {
      const a = window.__bar, first = a.indexOf(true);
      return { first, back: first < 0 ? 0 : a.slice(first).filter((v, i, x) => i > 0 && v !== x[i - 1]).length };
    });
    check("a turn back into the chapter before lands its last page enlarged at its bottom right, above the board and the bar",
          !shownBack.away && back.zoom && back.max > 0 && Math.abs(back.sl - back.max) <= 1 &&
          Math.abs(back.bottom - back.foot) <= 1.5 && /turn=-1/.test(back.hash), { shownBack, back });
    check("the top bar does not come back and go again as the chapters change", flips.back === 0, flips);
    await shot("flow_chapter_turn_back");
    await inFrame(() => {
      const bar = document.getElementById("mbar");
      (getComputedStyle(bar).display !== "none" ? document.getElementById("mzoom") : document.getElementById("zoom")).click();
    });
    if (which !== "iphone13") { await page.setViewportSize(opts.viewport); await page.waitForTimeout(500); }
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
  // the words of the opening are the small book's, not a line in the bar
  const opening = await page.evaluate(() => ({ note: document.getElementById("note").textContent,
    h: document.getElementById("top").getBoundingClientRect().height, words: workWords }));
  check("opening another chapter adds no line to the top bar; the small book has the words", !/Opening/.test(opening.note) &&
    opening.h < 50, opening);
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
  check("its pages rest while it is gone", await page.evaluate(() =>
    document.getElementById("busy").getAnimations({ subtree: true }).every((a) => a.playState !== "running")));

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
