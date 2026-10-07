// End-to-end test of coming back to the open book after the system closed
// the app (SESSION in tools/build_web.py, LIB.start and LIB.leaving in
// web/library.js, readerView in chessbook/reader.py), on the static site
// with the library in the browser, in Chromium (tests/test_resume.py serves
// the site and runs this).
//
// Usage:
//   NODE_PATH=/opt/node22/lib/node_modules node tests/resume_e2e.js SITE_URL BOOK WORK_DIR SCREENS_DIR
//
// The test:
//   - in a browser profile kept on disk, adds BOOK (read in the browser, its
//     reading kept), opens its second chapter at a later page, chooses a move
//     there, scrolls the page and the move list, and checks that the session
//     record holds the chapter, page, move and view;
//   - closes the page the way an iPhone does (the page hidden, then pagehide)
//     and loads it again: the app skips the library, says "Back to <title>,
//     page N" with a Library link, and opens the book from the stored reading
//     at the same chapter, page, move and scroll, without reading it again;
//   - makes the record a day old and loads the page again: the library shows;
//   - adds a second book with the reading slowed down (?pace=MS), opens a
//     chapter while the book is still read, closes and loads the page again:
//     the app reads the book again and opens the chapter at the same page,
//     saying so, and the reading arrives;
//   - without IndexedDB (no library), reads BOOK, closes and loads the page
//     again: the start page says that the book has to be chosen again, and
//     choosing it opens it at the place;
//   - takes pictures of the "Back to" line on an iPhone 13 and an iPad in
//     landscape.
// Prints one JSON object {ok, checks, errors, timings, screenshots, notes};
// the exit code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [siteUrl, book, work, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], timings: {}, screenshots: [], notes: [] };
let mode = "";
function check(name, cond, detail) {
  out.checks.push({ mode, name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed [" + mode + "]: " + name + (detail !== undefined ? " (" + JSON.stringify(detail).slice(0, 600) + ")" : ""));
}
function note(text) { out.notes.push("[" + mode + "] " + text); }
function timing(name, seconds) { out.timings[name] = Math.round(seconds * 10) / 10; }
const now = () => Date.now() / 1000;
const EXE = process.env.CHROMIUM || "/opt/pw-browsers/chromium";
const LAUNCH = fs.existsSync(EXE) ? { executablePath: EXE } : {};

const PHONE = Object.assign({}, devices["iPhone 13"]);
const IPAD = Object.assign({}, devices["iPad Pro 11 landscape"]);
delete PHONE.defaultBrowserType;
delete IPAD.defaultBrowserType;
const DESK = { viewport: { width: 1280, height: 900 } };

// A browser on a profile directory (kept between launches), with the worker's
// messages counted from the first script on (window.__sent), and without
// IndexedDB when noLibrary is set.
async function device(name, opts, profile, noLibrary) {
  mode = name;
  const ctx = await chromium.launchPersistentContext(profile, Object.assign({}, LAUNCH, opts));
  await ctx.addInitScript(() => {
    window.__sent = [];
    const post = Worker.prototype.postMessage;
    Worker.prototype.postMessage = function (m, t) {
      try { window.__sent.push(m && m.type); } catch (e) { /* not ours */ }
      return t === undefined ? post.call(this, m) : post.call(this, m, t);
    };
  });
  if (noLibrary) await ctx.addInitScript(() => { Object.defineProperty(window, "indexedDB", { value: undefined }); });
  const page = ctx.pages()[0] || await ctx.newPage();
  page.on("console", (m) => {
    // (the manifest and its icon are fetched while the page is closed and loaded again: a fetch cut
    // short reads as an empty manifest; tests/test_device_library.py checks the manifest itself)
    if (m.type() === "error" && !/Failed to load resource: the server responded with a status of 404/.test(m.text()) &&
        !/^Manifest: Line: 1, column: 1, Syntax error\.$/.test(m.text()) && !/icon from the Manifest/.test(m.text()))
      out.errors.push("[" + name + "] " + m.text());
  });
  page.on("pageerror", (e) => out.errors.push("[" + name + "] " + String(e)));
  const frame = async () => (await page.$("#view")).contentFrame();
  const inFrame = async (fn, arg) => {
    for (let i = 0; ; i++) {
      try { return await (await frame()).evaluate(fn, arg); }
      catch (e) { if (i > 80) throw e; await page.waitForTimeout(250); }
    }
  };
  const waitFrame = async (fn, arg, timeout) => {
    const t0 = Date.now();
    for (;;) {
      let v = null;
      try { v = await (await frame()).evaluate(fn, arg); } catch (e) { v = null; }
      if (v) return v;
      if (Date.now() - t0 > (timeout || 120000)) {
        const said = await page.evaluate(() => document.getElementById("note").textContent + " | " +
          document.getElementById("status").textContent).catch(() => "");
        throw new Error("timed out waiting in the reader: " + fn.toString().slice(0, 200) + " | " + said);
      }
      await page.waitForTimeout(150);
    }
  };
  const until = async (fn, what, timeout) => {
    const t0 = Date.now();
    for (;;) {
      const v = await fn();
      if (v) return v;
      if (Date.now() - t0 > (timeout || 60000)) throw new Error("timed out waiting for " + what);
      await page.waitForTimeout(250);
    }
  };
  const shot = async (file) => {
    const p = path.join(screens, file);
    await page.screenshot({ path: p });
    out.screenshots.push(p);
  };
  const session = () => page.evaluate(() => { try { return JSON.parse(localStorage.getItem("chessbook-session")); } catch (e) { return null; } });
  const sent = () => page.evaluate(() => window.__sent.slice());
  const close = async () => { await ctx.close(); };
  return { ctx, page, frame, inFrame, waitFrame, until, shot, session, sent, close };
}

async function whenReady(d) {
  await d.page.waitForFunction(() => typeof ready !== "undefined" && ready === true, null, { timeout: 300000 });
}
async function openLibrary(d, url) {
  await d.page.goto(url || siteUrl);
  await d.page.waitForFunction(() => document.body.classList.contains("library"), null, { timeout: 60000 });
}
// Add a PDF: it is read as before, then its reading is kept.
async function addBook(d, file) {
  const t = now();
  await whenReady(d);
  await d.page.setInputFiles("#file", file);
  await d.page.waitForSelector("#view", { state: "visible", timeout: 1800000 });
  await d.page.waitForFunction(() => document.body.dataset.book === "read",
                               null, { timeout: 3600000 });
  const id = await d.page.evaluate(() => LIB.current.id);
  await d.page.waitForFunction(() => document.body.dataset.saved === LIB.current.id, null, { timeout: 600000 });
  return { id, read: now() - t };
}
// The chapter files of the open book, in order (the app's list of them).
const chapterList = (d) => d.page.evaluate(() => bookChapters.map((c) => c.file));
// Open chapter ch and choose a move on a page after its first, scroll the
// window and the move list; returns the place and the view the reader reports.
async function settle(d, ch) {
  await d.page.evaluate((ch) => window.postMessage({ open: ch, hash: "" }, "*"), ch);
  await d.waitFrame((ch) => window.READER && window.READER.chapter.file === ch && !!window.readerState.page, ch, 300000);
  const place = await d.inFrame(() => {
    const D = window.READER, first = D.chapter.start;
    const ids = Object.keys(D.nodes).filter((id) => D.nodes[id].page && D.nodes[id].parent != null);
    const later = ids.filter((id) => D.nodes[id].page > first);
    const pool = later.length ? later : ids;
    const id = pool[Math.floor(pool.length / 2)];
    location.hash = "#node=" + id;
    return { node: id, page: D.nodes[id].page };
  });
  await d.waitFrame((p) => window.readerState.nodeId === p.node && window.readerState.page === p.page, place);
  await d.inFrame(() => {
    window.scrollTo(0, 150);
    const tree = document.getElementById("tree");
    if (tree) tree.scrollTop = 51;
  });
  await d.page.waitForTimeout(100);
  const view = await d.inFrame(() => window.readerView());
  return { chapter: ch, place, view };
}
// The page closed as an iPhone closes it: hidden, then pagehide; then loaded again.
async function evictAndReload(d) {
  await d.page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: false }));
  });
  await d.page.waitForTimeout(600);
  await d.page.reload();
}
// Wait for the reader at the place after the page loads again; returns what it shows.
async function backAt(d, want, timeout) {
  const t = now();
  await d.page.waitForFunction(() => /^Back to /.test(document.getElementById("took").textContent) ||
    /^Back to /.test(document.getElementById("note").textContent), null, { timeout: timeout || 600000 });
  const at = await d.waitFrame((p) => window.READER && window.READER.chapter.file === p.chapter &&
    window.readerState.page === p.page && (p.node === null || window.readerState.nodeId === p.node) &&
    Object.assign({ view: window.readerView() }, window.readerState), want, timeout || 300000);
  const took = await d.page.evaluate(() => document.getElementById("took").textContent);
  const noteText = await d.page.evaluate(() => document.getElementById("note").textContent);
  return { seconds: now() - t, at, took, note: noteText };
}

async function run() {
  fs.mkdirSync(screens, { recursive: true });
  fs.mkdirSync(work, { recursive: true });
  const profile = path.join(work, "profile");
  try {
    // ---------------------------------------------------------------- the book, read and kept
    let d = await device("reading", DESK, profile);
    await openLibrary(d);
    const one = await addBook(d, book);
    timing("adding the book: until read and kept (s)", one.read);
    const title = await d.page.evaluate(() => LIB.titleOf(LIB.current.book));
    const chapters = await chapterList(d);
    check("the book has a second chapter", chapters.length >= 2, chapters);
    const settled = await settle(d, chapters[1]);
    check("the page scrolled", settled.view.y > 0 && settled.view.t > 0, settled.view);
    const rec = await d.until(async () => {
      const r = await d.session();
      return r && r.chapter === settled.chapter && r.node === settled.place.node && r.view && r.view.y === settled.view.y ? r : null;
    }, "the session record with the view", 20000);
    check("the session record holds the book, chapter, page, move and view",
      rec.id === one.id && rec.kind === "device" && rec.page === settled.place.page && rec.title === title &&
      rec.view.t === settled.view.t && rec.label, rec);
    note("record: " + JSON.stringify(rec).slice(0, 300));

    // ---------------------------------------------------------------- closed, and back
    const t0 = now();
    await evictAndReload(d);
    const seen = await d.page.waitForFunction(() => !document.getElementById("resume").hidden &&
      document.getElementById("resume").textContent, null, { timeout: 60000 });
    const resumeLine = await d.page.evaluate(() => document.getElementById("resume").querySelector("span").textContent);
    check("the start page says where the app goes back to, with a Library link",
      resumeLine === "Back to " + title + ", page " + rec.label + "." &&
      await d.page.evaluate(() => document.body.classList.contains("resuming") &&
        getComputedStyle(document.getElementById("lib")).display === "none" &&
        document.getElementById("resume").querySelector("button").textContent === "Library"), resumeLine);
    const back = await backAt(d, { chapter: settled.chapter, page: settled.place.page, node: settled.place.node });
    timing("back in the chapter after the page loaded again (s)", now() - t0);
    check("the top bar says where the app came back to", back.took === "Back to " + title + ", page " + rec.label, back.took);
    const sent = await d.sent();
    check("the book opened from the stored reading, not read again", sent.includes("restore") && !sent.includes("process"), sent);
    check("the reader is at the same scroll, in the page and in the move list",
      Math.abs(back.at.view.y - settled.view.y) <= 2 && Math.abs(back.at.view.t - settled.view.t) <= 2, { back: back.at.view, want: settled.view });
    check("the library page did not show", !(await d.page.evaluate(() => document.getElementById("start").style.display !== "none")));
    check("the Library button is there", await d.page.evaluate(() => document.getElementById("another").textContent === "Library"));
    // the record goes on: the view after a move
    await d.inFrame(() => document.getElementById("bfwd").click());
    const after = await d.until(async () => { const r = await d.session(); return r && r.node !== settled.place.node ? r : null; },
                                "the record after a step", 20000);
    check("the record follows the reader", after.chapter === settled.chapter && after.node, after.node);
    // "Library" forgets the record
    await d.page.click("#another");
    await d.page.waitForFunction(() => document.body.classList.contains("library") &&
      document.querySelectorAll("#books li.book").length === 1, null, { timeout: 60000 });
    check("Library shows the library and forgets the record", (await d.session()) === null);

    // ---------------------------------------------------------------- a record a day old
    await d.page.evaluate((r) => { r.time = Date.now() - 25 * 3600 * 1000; localStorage.setItem("chessbook-session", JSON.stringify(r)); }, after);
    await d.page.reload();
    await d.page.waitForFunction(() => document.body.classList.contains("library") && typeof ready !== "undefined" && ready === true,
                                 null, { timeout: 300000 });
    await d.page.waitForTimeout(1500);
    check("a record older than a day shows the library", await d.page.evaluate(() =>
      !document.body.classList.contains("resuming") && document.getElementById("resume").hidden &&
      getComputedStyle(document.getElementById("lib")).display !== "none" && document.getElementById("view").style.display !== "block"));
    check("the old record is forgotten", (await d.session()) === null);

    // ---------------------------------------------------------------- closed while the book is still read
    const paced = siteUrl + (siteUrl.includes("?") ? "&" : "?") + "pace=1500";
    await openLibrary(d, paced);
    await whenReady(d);
    // the same book again is not read again; its reading is dropped from the library first
    await d.page.evaluate(async (id) => {
      const db = await new Promise((r) => { const q = indexedDB.open("chessbook-library"); q.onsuccess = () => r(q.result); });
      await new Promise((r) => {
        const t = db.transaction(["books", "files"], "readwrite");
        const q = t.objectStore("books").get(id);
        q.onsuccess = () => { const b = q.result; b.reading = null; t.objectStore("books").put(b); };
        t.objectStore("files").delete(id + ":reading");
        t.oncomplete = r;
      });
      db.close();
    }, one.id);
    await d.page.reload();
    await openLibrary(d, paced);
    await whenReady(d);
    await d.page.click("#books li.book[data-id='" + one.id + "'] .open");
    await d.page.waitForSelector("#view", { state: "visible", timeout: 600000 });
    await d.page.waitForFunction(() => /Reading the book|Reading the/.test(document.getElementById("took").textContent), null, { timeout: 120000 });
    await d.page.waitForFunction(() => bookChapters.length > 0, null, { timeout: 600000 });
    const where = await chapterList(d);
    const chRead = where[0];
    await d.page.evaluate((ch) => window.postMessage({ open: ch, hash: "" }, "*"), chRead);
    const early = await d.waitFrame((ch) => window.READER && window.READER.chapter.file === ch && !!window.readerState.page &&
      { page: window.readerState.page, reading: window.READER.reading }, chRead, 300000);
    const stillReading = await d.page.evaluate(() => loading === true);
    check("the chapter opened while the book was still read", stillReading, { early, took: await d.page.evaluate(() => document.getElementById("took").textContent) });
    const recR = await d.until(async () => { const r = await d.session(); return r && r.chapter === chRead && r.page === early.page ? r : null; },
                               "the record while the book is read", 20000);
    await evictAndReload(d);
    const readAgain = d.page.waitForFunction(() =>
      /^Back to .*\. The book is read again, because the app was closed before its reading was finished\.$/.test(document.getElementById("note").textContent),
      null, { timeout: 600000 }).then(() => true).catch(() => false);
    const backR = await backAt(d, { chapter: chRead, page: early.page, node: null }, 600000);
    check("closed while the book was read: the chapter opens at the page, and the app says the book is read again",
      /^Back to .*, page .*\. /.test(backR.took) && (await readAgain) &&
      backR.at.page === early.page && (await d.sent()).includes("process"), backR);
    await d.page.waitForFunction(() => document.body.dataset.book === "read", null, { timeout: 1800000 });
    check("the reading arrives in the resumed chapter", await d.waitFrame(() => window.READER.reading !== "pages" && window.readerState.page, null, 300000));
    await d.page.click("#another");
    await d.page.waitForFunction(() => document.body.classList.contains("library"), null, { timeout: 60000 });
    await d.close();

    // ---------------------------------------------------------------- no library (no IndexedDB)
    d = await device("no library", DESK, path.join(work, "profile-nolib"), true);
    await d.page.goto(siteUrl);
    await whenReady(d);
    check("without IndexedDB the start page is not a library", !(await d.page.evaluate(() => document.body.classList.contains("library"))));
    await d.page.setInputFiles("#file", book);
    await d.page.waitForSelector("#view", { state: "visible", timeout: 1800000 });
    await d.page.waitForFunction(() => document.body.dataset.book === "read", null, { timeout: 3600000 });
    const chs = await chapterList(d);
    const s2 = await settle(d, chs[1]);
    const recN = await d.until(async () => { const r = await d.session(); return r && r.chapter === s2.chapter && r.node === s2.place.node ? r : null; },
                               "the record without a library", 20000);
    check("the record without a library names the file", !recN.id && recN.name && recN.title, recN);
    await evictAndReload(d);
    await whenReady(d);
    const line = await d.page.evaluate(() => document.getElementById("resume").hidden ? null :
      document.getElementById("resume").querySelector("span").textContent);
    check("without a library the start page says the book has to be chosen again",
      line && /^The app was closed while you read .* at page .*\. This browser keeps no library, so the book has to be chosen again; it then opens at that place\.$/.test(line),
      line);
    check("the library page did not show", !(await d.page.evaluate(() => document.body.classList.contains("library"))));
    await d.page.setInputFiles("#file", book);
    const backN = await backAt(d, { chapter: s2.chapter, page: s2.place.page, node: s2.place.node }, 1800000);
    check("the book chosen again opens at the place", /^Back to .*, page /.test(backN.took) && Math.abs(backN.at.view.y - s2.view.y) <= 2, backN);
    await d.close();

    // ---------------------------------------------------------------- pictures
    for (const [name, opts] of [["iphone13", PHONE], ["ipad_landscape", IPAD]]) {
      const s = await device("pictures " + name, opts, path.join(work, "profile-" + name));
      await openLibrary(s);
      const b = await addBook(s, book);
      const chs2 = await chapterList(s);
      const st = await settle(s, chs2[1]);
      const t = await s.page.evaluate(() => LIB.titleOf(LIB.current.book));
      await s.until(async () => { const r = await s.session(); return r && r.node === st.place.node && r.view ? r : null; }, "the record", 20000);
      await evictAndReload(s);
      await s.page.waitForFunction(() => !document.getElementById("resume").hidden, null, { timeout: 60000 });
      await s.shot("resume_start_" + name + ".png");
      const bk = await backAt(s, { chapter: st.chapter, page: st.place.page, node: st.place.node });
      check("the top bar says where the app came back to", bk.took === "Back to " + t + ", page " + (await s.session()).label, bk.took);
      check("the reader is at the same scroll", Math.abs(bk.at.view.y - st.view.y) <= 2, { back: bk.at.view, want: st.view });
      await s.page.waitForTimeout(500);
      await s.shot("resume_" + name + ".png");
      const wide = await s.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check("the page does not scroll sideways", wide <= 0, wide);
      note(name + ": " + bk.took + " (book " + b.id.slice(0, 8) + ")");
      await s.close();
    }
    mode = "";
    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (e) {
    out.failure = String(e && e.stack || e);
  }
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
}

run();
