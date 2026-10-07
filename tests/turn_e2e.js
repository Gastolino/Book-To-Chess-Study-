// End-to-end test of the page turn in the book reader, in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/turn_e2e.js READER_DIR PAGE SCREENS_DIR
//
// Opens the chapter reader of READER_DIR that holds PDF page PAGE (the chapter must hold the page
// before PAGE and the two after it) on an iPhone 13 (390x844) and an iPad held upright (820x1180)
// and sideways (1180x820), all by touch, and on a desktop (1280x900) by the page arrows and the
// Page Up and Page Down keys, and checks that:
//   - during a swipe to the left the page box moves with the finger (its transform changes while
//     the finger moves); on release the next page slides in, the reader lands on it, and the
//     slide ends (no stage, no transform and no animation left);
//   - a short swipe springs back and stays on the page;
//   - a vertical scroll that starts on the page scrolls the window and does not turn the page;
//   - an enlarged page that can still scroll sideways scrolls first, and at its edge follows the
//     finger;
//   - on an enlarged page a turn forward ends at the new page's top left (its sideways scroll at
//     0, the page's top at the top of the space the reader sees), and a turn back at its bottom
//     right (the sideways scroll at its end, the page's bottom at the bottom of the visible space,
//     above the board that stays at the foot of the window and the bar);
//   - the arrows and the keys turn with the same slide;
//   - with reduced motion the page changes at once, with no slide;
//   - on the iPhone and the desktop, a note above the page that goes with a turn leaves the page
//     coming in level with the page going out, and a second turn during a slide goes on from where
//     the page stands.
// When READER_DIR holds a chapter and the chapter after it, it also turns from the last page of
// the one into the other on the iPhone, with the page enlarged: the page goes out and the place
// of the next page comes in, and the next chapter's reader shows that page at its top left; a turn
// back shows the previous chapter's last page at its bottom right.
// Screenshots of the page following the finger, of a slide half done and of the pages where they
// land go to SCREENS_DIR. Prints one JSON object {ok, checks, errors, notes, screenshots}; the
// exit code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [dir, pageArg, screens] = process.argv.slice(2);
const PAGE = parseInt(pageArg, 10);
const out = { ok: false, checks: [], errors: [], notes: [], screenshots: [] };
let mode = "";
function check(name, cond, detail) {
  out.checks.push({ mode, name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed [" + mode + "]: " + name + (detail !== undefined ? " (" + JSON.stringify(detail).slice(0, 800) + ")" : ""));
}
function note(text) { out.notes.push("[" + mode + "] " + text); }

// the chapter files of the reader, with the pages each holds
function chapters() {
  const list = [];
  for (const f of fs.readdirSync(dir).filter((f) => /^ch\d+\.html$/.test(f)).sort()) {
    const text = fs.readFileSync(path.join(dir, f), "utf8");
    const m = /<script type="application\/json" id="data">([\s\S]*?)<\/script>/.exec(text);
    if (!m) continue;
    const D = JSON.parse(m[1].replace(/<\\\//g, "</"));
    list.push({ file: f, start: D.chapter.start, end: D.chapter.end, pages: Object.keys(D.pages).map(Number) });
  }
  return list;
}

const MODES = [
  { name: "iphone13", opts: Object.assign({}, devices["iPhone 13"], { viewport: { width: 390, height: 844 } }), touch: true },
  { name: "ipad_upright", opts: Object.assign({}, devices["iPad Pro 11"] || {}, { viewport: { width: 820, height: 1180 },
    isMobile: true, hasTouch: true }), touch: true },
  { name: "ipad_sideways", opts: Object.assign({}, devices["iPad Pro 11 landscape"] || {}, { viewport: { width: 1180, height: 820 },
    isMobile: true, hasTouch: true }), touch: true },
  { name: "desktop", opts: { viewport: { width: 1280, height: 900 } }, touch: false },
];

// how the page stands: its number, its slide, its sideways scroll and its place in the window,
// with the space the reader sees (below a top bar that stays on the screen, above the board at
// the foot of the window, the bar of the current move or the window's foot)
const STATE = () => {
  const ps = document.getElementById("pagescroll"), box = document.getElementById("pagebox");
  const r = box.getBoundingClientRect(), head = document.querySelector("header.bar");
  const pos = getComputedStyle(head).position;
  const top = pos === "fixed" || pos === "sticky" ? Math.max(0, head.getBoundingClientRect().bottom) : 0;
  const bar = document.getElementById("mbar"), barShown = getComputedStyle(bar).display !== "none";
  const stuck = document.body.classList.contains("stickboard");
  const bottom = stuck ? document.getElementById("boardblock").getBoundingClientRect().top :
    barShown ? bar.getBoundingClientRect().top : window.innerHeight;
  const anims = document.getAnimations().filter((a) => a.playState === "running" && a.effect && a.effect.target &&
    (a.effect.target === box || a.effect.target.closest(".turnstage")));
  return { page: window.readerState.page, file: window.READER.chapter.file, transform: getComputedStyle(box).transform,
           left: r.left, top: r.top, bottom: r.bottom, viewTop: top, viewBottom: bottom, stuck,
           stage: !!document.querySelector(".turnstage"), turning: ps.classList.contains("turning"),
           anims: anims.length, zoom: ps.classList.contains("zoom"), sl: ps.scrollLeft,
           max: ps.scrollWidth - ps.clientWidth, y: window.scrollY, waiting: box.classList.contains("waiting") };
};
const tx = (t) => { const m = /matrix\(([^)]+)\)/.exec(t || ""); return m ? parseFloat(m[1].split(",")[4]) : 0; };

async function settle(page) {
  await page.waitForFunction(() => !document.querySelector(".turnstage") &&
    !document.getElementById("pagescroll").classList.contains("turning") &&
    getComputedStyle(document.getElementById("pagebox")).transform === "none", null, { timeout: 5000 });
  await page.waitForTimeout(80);
}

// a touch that moves in steps (CDP touch events, as a finger sends them), with a look at the
// page before it lifts
async function swipe(page, cdp, from, to, opts) {
  opts = opts || {};
  const steps = opts.steps || 10;
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: from[0], y: from[1] }] });
  let mid = null;
  for (let i = 1; i <= steps; i++) {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove",
      touchPoints: [{ x: from[0] + (to[0] - from[0]) * i / steps, y: from[1] + (to[1] - from[1]) * i / steps }] });
    await page.waitForTimeout(opts.wait || 16);
    if (i === Math.ceil(steps / 2) || (opts.lookLast && i === steps)) {
      mid = await page.evaluate(STATE);
      if (opts.shot) await shot(page, opts.shot);
    }
  }
  if (opts.rest) await page.waitForTimeout(opts.rest);
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  const after = await page.evaluate(STATE);
  return { mid, after };
}

async function shot(page, what) {
  const name = "turn_" + mode + "_" + what + ".png";
  await page.screenshot({ path: path.join(screens, name) });
  out.screenshots.push(name);
}

// a point on the page for a swipe: across the part of it in view, above the board and the bar
async function across(page) {
  const g = await page.evaluate(() => {
    const ps = document.getElementById("pagescroll").getBoundingClientRect();
    const r = document.getElementById("pagebox").getBoundingClientRect();
    const blk = document.getElementById("boardblock").getBoundingClientRect();
    const bar = document.getElementById("mbar");
    let foot = getComputedStyle(bar).display !== "none" ? bar.getBoundingClientRect().top : window.innerHeight;
    if (blk.top > Math.max(r.top, 0) && blk.top < foot && blk.left < ps.right && blk.right > ps.left) foot = blk.top;
    return { l: ps.left, w: ps.width, top: Math.max(r.top, 0), bottom: Math.min(r.bottom, foot) };
  });
  const y = Math.round((g.top + g.bottom) / 2);
  return { right: [g.l + g.w * 0.85, y], left: [g.l + g.w * 0.15, y], mid: [g.l + g.w * 0.5, y], g };
}

// the enlarged page at its bottom right, its foot just above the board or the bar
async function toBottomRight(page) {
  await page.evaluate(() => {
    const ps = document.getElementById("pagescroll");
    ps.scrollLeft = ps.scrollWidth;
    const r = document.getElementById("pagebox").getBoundingClientRect(), bar = document.getElementById("mbar");
    const foot = getComputedStyle(bar).display !== "none" ? bar.getBoundingClientRect().top : window.innerHeight;
    const blk = document.getElementById("boardblock").getBoundingClientRect();
    const board = document.body.classList.contains("stickboard") ? blk.height : 0;
    window.scrollBy(0, r.bottom - (foot - board) + 40);
  });
  await page.waitForTimeout(150);
}

async function zoom(page, on) {
  await page.evaluate((on) => {
    const ps = document.getElementById("pagescroll");
    if (ps.classList.contains("zoom") === on) return;
    const bar = document.getElementById("mbar");
    (getComputedStyle(bar).display !== "none" ? document.getElementById("mzoom") : document.getElementById("zoom")).click();
  }, on);
  await page.waitForTimeout(150);
}

async function open(ctx, file, p) {
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") out.errors.push("[" + mode + "] " + m.text()); });
  page.on("pageerror", (e) => out.errors.push("[" + mode + "] " + String(e)));
  await page.goto("file://" + path.resolve(dir, file) + "#page=" + p);
  await page.waitForFunction((p) => window.readerState && window.readerState.page === p, p);
  await page.evaluate(() => document.getElementById("pageimg").decode().catch(() => null));
  await page.waitForTimeout(250);
  return page;
}

// a move of the page chosen, so that on a phone the board stays at the foot of the window
async function chooseMove(page) {
  return page.evaluate(() => {
    const m = document.querySelector("#ov .mark[data-node]");
    if (m) m.click();
    return !!m;
  });
}

// Two turns back by the page arrow, each from a page whose place in the window changes: a note set
// above the page (a bookmark's) that goes with the turn, and a second turn while the first still
// slides. The page coming in starts level with the page going out, and the second slide goes on
// from where the page stands, with no jump back.
async function quickTurns(page, p0) {
  await settle(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(100);
  const lv = await page.evaluate(() => {
    document.getElementById("bmbtn").click();
    const note = document.getElementById("pagemsg").textContent;
    const before = document.getElementById("pagebox").getBoundingClientRect().top;
    document.getElementById("prevpage").click();
    const part = document.querySelector(".turnstage .turnpart");
    return { note, before, out: part ? part.getBoundingClientRect().top : null,
             inc: document.getElementById("pagebox").getBoundingClientRect().top,
             msg: document.getElementById("pagemsg").textContent, page: window.readerState.page };
  });
  check("a note above the page goes with the turn, and the page coming in starts level with the page going out",
        /Bookmark set/.test(lv.note) && !lv.msg && lv.page === p0 - 1 && lv.out !== null &&
        Math.abs(lv.out - lv.inc) < 1 && Math.abs(lv.out - lv.before) < 1, lv);
  await settle(page);
  await page.waitForTimeout(250);
  const after = await page.evaluate(() => ({ margin: document.getElementById("pagescroll").style.marginTop,
    anims: document.getAnimations().filter((a) => a.playState === "running").length }));
  check("after the slide nothing is held over the page", !after.margin && after.anims === 0, after);
  const r = await page.evaluate(async () => {
    const box = document.getElementById("pagebox"), p = window.readerState.page;
    document.getElementById("prevpage").click();
    // (well into the slide)
    await new Promise((done) => { const t0 = performance.now(); const f = () => {
      if (document.getAnimations().some((a) => a.effect && a.effect.target === box && a.currentTime > 70) ||
          performance.now() - t0 > 2000) done(); else requestAnimationFrame(f); }; f(); });
    const at = box.getBoundingClientRect().left;
    document.getElementById("prevpage").click();
    // (where each copied page stands: its part on the stage is clipped to the page's place)
    const parts = [...document.querySelectorAll(".turnstage .turnpart")].map((q) => q.querySelector(".pagebox").getBoundingClientRect().left);
    return { from: p, page: window.readerState.page, at, parts, rest: document.getElementById("pagescroll").getBoundingClientRect().left };
  });
  check("a second turn while the first slides goes on from where the page stands",
        r.page === r.from - 2 && r.parts.length === 2 && Math.abs(r.at - r.rest) > 20 && Math.abs(r.parts[1] - r.at) <= 2, r);
  await settle(page);
  const end = await page.evaluate(STATE);
  check("the second slide ends on its page", end.page === r.from - 2 && end.transform === "none" && !end.stage, end);
}

async function byTouch(browser, m, ch) {
  const ctx = await browser.newContext(m.opts);
  const page = await open(ctx, ch.file, PAGE);
  const cdp = await ctx.newCDPSession(page);
  let s, a;

  // a swipe to the left: the page follows the finger, and the next page slides in
  a = await across(page);
  s = await swipe(page, cdp, a.right, a.left, { shot: "finger" });
  check("during a swipe the page box moves with the finger", tx(s.mid.transform) < -20 && !s.mid.stage, s.mid);
  check("on release the next page slides in", s.after.page === PAGE + 1 && s.after.stage && s.after.turning, s.after);
  await settle(page);
  s = await page.evaluate(STATE);
  check("the slide ends on the next page", s.page === PAGE + 1 && s.transform === "none" && !s.stage && s.anims === 0, s);

  // a short swipe springs back
  a = await across(page);
  s = await swipe(page, cdp, a.mid, [a.mid[0] - 30, a.mid[1]], { steps: 3, wait: 40, rest: 250, lookLast: true });
  check("a short swipe moves the page a little", tx(s.mid.transform) < -5 && tx(s.mid.transform) > -40, s.mid);
  check("on release it springs back", s.after.page === PAGE + 1 && s.after.turning && !s.after.stage, s.after);
  await settle(page);
  s = await page.evaluate(STATE);
  check("a short swipe stays on the page", s.page === PAGE + 1 && s.transform === "none", s);

  // up and down: the window scrolls, the page does not turn
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(100);
  a = await across(page);
  const y0 = await page.evaluate(() => window.scrollY);
  s = await swipe(page, cdp, [a.mid[0], a.g.bottom - 10], [a.mid[0] + 6, a.g.bottom - 260]);
  await page.waitForTimeout(400);
  const v = await page.evaluate(STATE);
  check("a vertical scroll that starts on the page scrolls the window and does not turn the page",
        v.page === PAGE + 1 && v.y > y0 + 50 && s.mid.transform === "none" && !v.stage, { mid: s.mid, v, y0 });

  // enlarged: the page scrolls sideways first, then turns at its edge
  await page.evaluate(() => window.scrollTo(0, 0));
  const moved = await chooseMove(page);
  await zoom(page, true);
  a = await across(page);
  s = await swipe(page, cdp, a.right, [a.right[0] - 150, a.right[1]]);
  // until the scroll has come to rest
  await page.waitForFunction(() => new Promise((done) => {
    const ps = document.getElementById("pagescroll"), x = ps.scrollLeft;
    setTimeout(() => done(ps.scrollLeft === x), 250);
  }), null, { timeout: 10000 });
  const sideways = await page.evaluate(STATE);
  check("an enlarged page that can still scroll sideways scrolls first", sideways.zoom && sideways.page === PAGE + 1 &&
        sideways.sl > 20 && s.mid.transform === "none", { mid: s.mid, sideways });
  await toBottomRight(page);
  a = await across(page);
  const before = await page.evaluate(STATE);
  s = await swipe(page, cdp, a.right, a.left, { shot: "zoom_finger" });
  check("at its edge the enlarged page follows the finger", tx(s.mid.transform) < -20 &&
        s.mid.left < before.left - 20 && s.mid.sl === before.sl, { before, mid: s.mid });
  await settle(page);
  s = await page.evaluate(STATE);
  await shot(page, "zoom_forward");
  check("enlarged, a turn forward ends at the next page's top left",
        s.page === PAGE + 2 && s.zoom && s.sl === 0 && Math.abs(s.top - s.viewTop) <= 1.5, s);
  // back: the new page is at its left edge, so a swipe to the right turns back
  a = await across(page);
  s = await swipe(page, cdp, a.left, a.right);
  await settle(page);
  s = await page.evaluate(STATE);
  await shot(page, "zoom_back");
  check("enlarged, a turn back ends at the previous page's bottom right, above the board and the bar",
        s.page === PAGE + 1 && s.zoom && Math.abs(s.sl - s.max) <= 1 && s.max > 0 && Math.abs(s.bottom - s.viewBottom) <= 1.5 &&
        (m.name === "ipad_sideways" || !moved || s.stuck), s);
  await zoom(page, false);

  // reduced motion: no movement, the page changes at once
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.evaluate(() => window.scrollTo(0, 0));
  a = await across(page);
  s = await swipe(page, cdp, a.right, a.left);
  check("with reduced motion the page does not move with the finger", s.mid.transform === "none", s.mid);
  check("with reduced motion the page changes at once", s.after.page === PAGE + 2 && !s.after.stage && !s.after.turning &&
        s.after.anims === 0 && s.after.transform === "none", s.after);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  if (m.name === "iphone13") await quickTurns(page, PAGE + 2);
  await ctx.close();
}

async function byKeys(browser, m, ch) {
  const ctx = await browser.newContext(m.opts);
  const page = await open(ctx, ch.file, PAGE);
  let s;
  await page.click("#nextpage");
  s = await page.evaluate(STATE);
  check("the page arrow turns with the slide", s.page === PAGE + 1 && s.stage && s.turning, s);
  await settle(page);
  await page.keyboard.press("PageUp");
  s = await page.evaluate(STATE);
  check("Page Up turns back with the slide", s.page === PAGE && s.stage && s.turning, s);
  await settle(page);
  s = await page.evaluate(STATE);
  check("the slide ends", s.transform === "none" && !s.stage && s.anims === 0, s);
  // a slide half done, slowed down for the picture
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Animation.enable");
  await cdp.send("Animation.setPlaybackRate", { playbackRate: 0.1 });
  await page.keyboard.press("PageDown");
  await page.waitForTimeout(1100);
  await shot(page, "slide");
  await cdp.send("Animation.setPlaybackRate", { playbackRate: 1 });
  await settle(page);
  // enlarged: Page Down lands at the top left of the next page, Page Up at the bottom right
  await zoom(page, true);
  await toBottomRight(page);
  await page.keyboard.press("PageDown");
  await settle(page);
  s = await page.evaluate(STATE);
  await shot(page, "zoom_forward");
  check("enlarged, Page Down ends at the next page's top left", s.page === PAGE + 2 && s.sl === 0 &&
        Math.abs(s.top - s.viewTop) <= 1.5, s);
  await page.keyboard.press("PageUp");
  await settle(page);
  s = await page.evaluate(STATE);
  await shot(page, "zoom_back");
  check("enlarged, Page Up ends at the previous page's bottom right", s.page === PAGE + 1 && s.max > 0 &&
        Math.abs(s.sl - s.max) <= 1 && Math.abs(s.bottom - s.viewBottom) <= 1.5, s);
  await zoom(page, false);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.keyboard.press("PageDown");
  s = await page.evaluate(STATE);
  check("with reduced motion the arrow keys change the page at once", s.page === PAGE + 2 && !s.stage && !s.turning &&
        s.anims === 0 && s.transform === "none", s);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await quickTurns(page, PAGE + 2);
  await ctx.close();
}

// from the last page of a chapter into the next chapter's reader, and back
async function intoNextChapter(browser, a, b) {
  const ctx = await browser.newContext(MODES[0].opts);
  const page = await open(ctx, a.file, a.end);
  const cdp = await ctx.newCDPSession(page);
  await chooseMove(page);
  await zoom(page, true);
  await toBottomRight(page);
  let g = await across(page);
  let s = await swipe(page, cdp, g.right, g.left);
  check("past the chapter's last page, the place of the next page slides in", s.after.stage && s.after.waiting &&
        s.after.file === a.file, s.after);
  await page.waitForFunction((f) => window.READER && window.READER.chapter.file === f && window.readerState.page,
    b.file, { timeout: 15000 });
  await page.evaluate(() => document.getElementById("pageimg").decode().catch(() => null));
  await page.waitForTimeout(400);
  s = await page.evaluate(STATE);
  const hash = await page.evaluate(() => location.hash);
  await shot(page, "chapter_forward");
  check("the next chapter's reader shows its first page enlarged, at its top left",
        s.page === b.start && s.zoom && s.sl === 0 && Math.abs(s.top - s.viewTop) <= 1.5 && /turn=1/.test(hash), { s, hash });
  g = await across(page);
  s = await swipe(page, cdp, g.left, g.right);
  // the place of the page comes in where the page's foot is above the board and the bar
  const sheet = s.after;
  check("before the first page of a chapter, the place of the previous page slides in", sheet.stage && sheet.waiting &&
        Math.abs(sheet.bottom - sheet.viewBottom) <= 1.5, sheet);
  await page.waitForFunction((f) => window.READER && window.READER.chapter.file === f && window.readerState.page,
    a.file, { timeout: 15000 });
  await page.evaluate(() => document.getElementById("pageimg").decode().catch(() => null));
  await page.waitForTimeout(400);
  s = await page.evaluate(STATE);
  const back = await page.evaluate(() => location.hash);
  await shot(page, "chapter_back");
  // where the place was, unless a board at the foot of this window would cover it
  const foot = Math.min(sheet.viewBottom, s.viewBottom);
  check("a turn back shows the previous chapter's last page enlarged, at its bottom right where its place was",
        s.page === a.end && s.zoom && Math.abs(s.sl - s.max) <= 1 && s.max > 0 && Math.abs(s.bottom - foot) <= 1.5 &&
        /turn=-1/.test(back), { s, sheet, back });
  await ctx.close();
}

(async () => {
  fs.mkdirSync(screens, { recursive: true });
  const exe = process.env.CHROMIUM || "/opt/pw-browsers/chromium";
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  try {
    const chs = chapters();
    const ch = chs.find((c) => c.pages.includes(PAGE));
    check("the reader holds the page and the pages around it",
          ch && [PAGE - 1, PAGE, PAGE + 1, PAGE + 2].every((p) => ch.pages.includes(p)), { PAGE, chs: chs.map((c) => [c.file, c.start, c.end]) });
    for (const m of MODES) {
      mode = m.name;
      if (m.touch) await byTouch(browser, m, ch); else await byKeys(browser, m, ch);
    }
    mode = "chapters";
    // the last chapter followed by another (the first is often the front matter)
    const pair = chs.map((c) => [c, chs.find((d) => d.start === c.end + 1 && d.pages.includes(d.start))])
      .filter((x) => x[1] && x[0].pages.includes(x[0].end)).pop();
    if (pair) await intoNextChapter(browser, pair[0], pair[1]);
    else note("the reader holds no chapter followed by the next: no turn into another chapter");
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
