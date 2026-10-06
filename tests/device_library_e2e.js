// End-to-end test of the library in the browser (web/library.js with its
// IndexedDB store), on the static site with no server, in Chromium
// (tests/test_device_library.py serves the site and runs this).
//
// Usage:
//   NODE_PATH=/opt/node22/lib/node_modules node tests/device_library_e2e.js SITE_URL BOOK1 BOOK2 WORK_DIR SCREENS_DIR
//
// The test:
//   - in a browser profile kept on disk (WORK_DIR/profile-a), finds the
//     library empty, adds BOOK1: it is read in the browser as before (the
//     contents page shows while it is read), and its PDF, reading, cover and
//     title are kept in IndexedDB; the browser is asked to keep the storage;
//   - names a piece symbol of a chapter (a correction) and chooses a move;
//   - adds BOOK2 too, for the library's pictures;
//   - closes the browser and starts it again on the same profile: the
//     library lists BOOK1 with its place, and opens it from the stored
//     reading without reading it again, with the correction, at the stored
//     page and move;
//   - saves both books as book files (.chessbook) from the library;
//   - in a fresh profile (another device), adds BOOK1's file: the book opens
//     without being read, with the correction, at the stored place; adding
//     the file again says the library holds the book already;
//   - takes pictures of the library with both books (added from their
//     files) on an iPhone 13 and an iPad in landscape, light and dark;
//   - removes the book after its confirmation: its files, its record, its
//     corrections and its place are gone.
// Prints one JSON object {ok, checks, errors, timings, screenshots, notes};
// the exit code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [siteUrl, book1, book2, work, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], timings: {}, screenshots: [], notes: [], storage: {} };
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

// A browser on a profile directory (kept between launches) or a fresh one.
async function device(name, opts, profile) {
  mode = name;
  const share = !!opts.share;
  opts = Object.assign({}, opts);
  delete opts.share;
  let ctx, browser = null;
  if (profile) ctx = await chromium.launchPersistentContext(profile, Object.assign({}, LAUNCH, opts, { acceptDownloads: true }));
  else {
    browser = await chromium.launch(LAUNCH);
    ctx = await browser.newContext(Object.assign({}, opts, { acceptDownloads: true }));
  }
  // Safari on an iPhone or iPad shares files (Chromium on Linux does not): its share sheet, for the pictures
  if (share) await ctx.addInitScript(() => {
    navigator.canShare = () => true;
    navigator.share = () => Promise.resolve();
  });
  const page = ctx.pages()[0] || await ctx.newPage();
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource: the server responded with a status of 404/.test(m.text()))
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
  const instrument = () => page.evaluate(() => {
    window.__sent = [];
    const post = worker.postMessage.bind(worker);
    worker.postMessage = (m, t) => { window.__sent.push(m.type); return post(m, t); };
    window.__said = [];
    const on = worker.onmessage;
    worker.onmessage = (e) => { if (e.data && e.data.type === "status") window.__said.push(e.data.text); return on(e); };
  });
  // the library's IndexedDB, read directly
  const stored = () => page.evaluate(() => new Promise((resolve, reject) => {
    const r = indexedDB.open("chessbook-library");
    r.onsuccess = () => {
      const db = r.result;
      const t = db.transaction(["books", "files"]);
      const q1 = t.objectStore("books").getAll(), q2 = t.objectStore("files").getAllKeys();
      t.oncomplete = () => {
        const books = q1.result.map((b) => ({ id: b.id, title: b.title, pages: b.pages, size: b.size,
          reading: b.reading, position: b.position, cover: b.coverBlob ? b.coverBlob.size : 0, opened: b.opened }));
        db.close();
        resolve({ books, files: q2.result });
      };
      t.onerror = () => reject(t.error);
    };
    r.onerror = () => reject(r.error);
  }));
  const shot = async (file) => {
    const p = path.join(screens, file);
    await page.screenshot({ path: p });
    out.screenshots.push(p);
  };
  const close = async () => { await ctx.close(); if (browser) await browser.close(); };
  return { ctx, page, frame, inFrame, waitFrame, until, instrument, stored, shot, close };
}

async function openLibrary(d) {
  // the library, not the book that was open (the app goes back to it otherwise, as after the
  // system closed it): the Library button forgets that record first, and so does this
  await d.page.evaluate(() => { try { localStorage.removeItem("chessbook-session"); } catch (e) { /* no page yet */ } }).catch(() => {});
  await d.page.goto(siteUrl);
  await d.page.waitForFunction(() => document.body.classList.contains("library"), null, { timeout: 60000 });
}
async function whenReady(d) {
  // the page's own flag: the worker said "ready"
  await d.page.waitForFunction(() => typeof ready !== "undefined" && ready === true, null, { timeout: 300000 });
}

// Add a PDF: it is read as before, then its reading is kept.
async function addBook(d, file) {
  const t = now();
  await whenReady(d);
  await d.page.setInputFiles("#file", file);
  await d.page.waitForSelector("#view", { state: "visible", timeout: 1800000 });
  const contents = now() - t;
  await d.page.waitForFunction(() => /read in \d+ seconds/.test(document.getElementById("took").textContent),
                               null, { timeout: 3600000 });
  const read = now() - t;
  const id = await d.page.evaluate(() => LIB.current.id);
  const rec = await d.until(async () => {
    const s = await d.stored();
    const b = s.books.find((x) => x.id === id);
    return b && b.reading && b.cover && b.title && s.files.includes(id + ":reading") ? b : null;
  }, "the stored reading of " + path.basename(file), 600000);
  const saved = now() - t;
  const took = await d.page.evaluate(() => document.getElementById("took").textContent);
  return { id, rec, contents, read, saved, took };
}

// Open a book of the library from its stored reading; returns the seconds
// until the contents page and until the chapter at the stored place.
async function openStored(d, id, place) {
  await d.instrument();
  const t = now();
  await d.page.click("#books li.book[data-id='" + id + "'] .open");
  await d.page.waitForFunction(() => /opened from your library/.test(document.getElementById("took").textContent),
                               null, { timeout: 600000 });
  const contents = now() - t;
  const at = await d.waitFrame((p) => window.READER && window.READER.chapter.file === p.chapter &&
    window.readerState.page === p.page && window.readerState.nodeId === p.node && window.readerState, place, 300000);
  return { contents, chapter: now() - t, at };
}
async function notReadAgain(d) {
  const sent = await d.page.evaluate(() => window.__sent);
  const said = await d.page.evaluate(() => window.__said);
  return { ok: sent.includes("restore") && !sent.includes("process") && !said.some((s) => /Reading the moves/.test(s)), sent, said };
}
async function glyphOf(d, sym) {
  return d.inFrame((s) => {
    const D = window.READER;
    const ns = Object.values(D.nodes).filter((n) => n.symbol === s);
    return { glyph: D.corrections.glyphs[s] || null, moves: ns.length,
             corrected: ns.filter((n) => n.corrected === "symbol").length };
  }, sym);
}
async function saveFile(d, id, dest) {
  const [dl] = await Promise.all([
    d.page.waitForEvent("download", { timeout: 120000 }),
    d.page.click("#books li.book[data-id='" + id + "'] .save"),
  ]);
  await dl.saveAs(dest);
  await d.page.waitForFunction(() => /The book file .* holds the book/.test(document.getElementById("status").textContent));
  return { name: dl.suggestedFilename(), size: fs.statSync(dest).size };
}
// the names of the files in a zip (its central directory)
function zipNames(file) {
  const b = fs.readFileSync(file);
  let e = b.length - 22;
  while (e >= 0 && b.readUInt32LE(e) !== 0x06054b50) e--;
  const n = b.readUInt16LE(e + 10);
  let p = b.readUInt32LE(e + 16);
  const names = [];
  for (let i = 0; i < n; i++) {
    const nl = b.readUInt16LE(p + 28), el = b.readUInt16LE(p + 30), cl = b.readUInt16LE(p + 32);
    names.push(b.toString("utf8", p + 46, p + 46 + nl));
    p += 46 + nl + el + cl;
  }
  return names;
}
// Add a book file; resolves when the book shows (opened) or the status says why not.
async function addFile(d, file) {
  await whenReady(d);
  await d.page.setInputFiles("#file", file);
}

async function run() {
  fs.mkdirSync(screens, { recursive: true });
  fs.mkdirSync(work, { recursive: true });
  const profileA = path.join(work, "profile-a");
  const file1 = path.join(work, "book1.chessbook"), file2 = path.join(work, "book2.chessbook");
  try {
    // ---------------------------------------------------------------- adding, on a device
    let a = await device("first visit", DESK, profileA);
    await openLibrary(a);
    check("the start page is the library in this browser", await a.page.evaluate(() =>
      LIB.on && LIB.kind === "device" && !document.getElementById("lib").hidden &&
      /Your library/.test(document.querySelector("#start h1").textContent) &&
      !document.getElementById("libempty").hidden && document.querySelectorAll("#books li").length === 0));
    await a.instrument();
    const one = await addBook(a, book1);
    timing("adding " + path.basename(book1) + ": until the contents page (s)", one.contents);
    timing("adding " + path.basename(book1) + ": until read (s)", one.read);
    timing("adding " + path.basename(book1) + ": until its reading is kept (s)", one.saved);
    note("book 1: " + one.took + "; stored reading " + one.rec.reading.stored + " bytes (gzip), " +
         one.rec.reading.size + " bytes before gzip; PDF " + one.rec.size + " bytes; title " + JSON.stringify(one.rec.title));
    check("the book was read in the browser", (await a.page.evaluate(() => window.__sent)).includes("process"));
    const st1 = await a.stored();
    check("the PDF, the reading and the record are kept in IndexedDB",
      st1.files.includes(one.id + ":pdf") && st1.files.includes(one.id + ":reading") && st1.books.length === 1, st1);
    const pdfBack = await a.page.evaluate(async (id) => {
      const db = await new Promise((r) => { const q = indexedDB.open("chessbook-library"); q.onsuccess = () => r(q.result); });
      const blob = await new Promise((r) => { const q = db.transaction("files").objectStore("files").get(id + ":pdf"); q.onsuccess = () => r(q.result); });
      db.close();
      const d = new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()));
      return Array.from(d, (x) => x.toString(16).padStart(2, "0")).join("");
    }, one.id);
    check("the stored PDF is the book (its SHA-256 is its id)", pdfBack === one.id);
    const persisted = await a.until(() => a.page.evaluate(() => LIB.persisted !== null ? { asked: true, granted: LIB.persisted } : null),
                                    "the answer to persist()", 10000).catch(() => ({ asked: false }));
    note("navigator.storage.persist(): " + JSON.stringify(persisted));

    // a correction: a piece symbol named in the first chapter that prints one
    let sym = null, chapter = null;
    const chapters = await a.inFrame(() => Array.from(document.querySelectorAll("a[href^='ch']"))
      .map((x) => x.getAttribute("href").replace(/#.*/, "")).filter((h, i, l) => l.indexOf(h) === i));
    for (const ch of chapters) {
      await a.page.evaluate((ch) => window.postMessage({ open: ch, hash: "" }, "*"), ch);
      await a.waitFrame((ch) => window.READER && window.READER.chapter.file === ch, ch, 300000);
      sym = await a.inFrame(() => {
        const D = window.READER;
        for (const id in D.nodes) {
          const n = D.nodes[id];
          if (n.symbol && n.key && n.page && n.bbox && D.symbols[n.symbol]) return { id, sym: n.symbol, page: n.page, san: n.san || n.assumed || "" };
        }
        return null;
      });
      if (sym) { chapter = ch; break; }
    }
    check("a chapter holds a piece symbol to correct", sym, chapters);
    await a.inFrame((p) => { location.hash = "#page=" + p; }, sym.page);
    await a.waitFrame((p) => window.readerState.page === p, sym.page);
    await a.inFrame(() => document.getElementById("penbtn").click());
    await a.waitFrame(() => document.body.classList.contains("pencil"));
    await a.inFrame((sel) => document.querySelector(sel).scrollIntoView({ block: "center" }), ".mark[data-node='" + sym.id + "']");
    await (await a.frame()).click(".mark[data-node='" + sym.id + "']");
    await a.waitFrame(() => !!document.getElementById("fixsymbol"));
    await (await a.frame()).click("#fixsymbol");
    await a.waitFrame(() => !!document.getElementById("fixsym"));
    const piece = /^[KQRBN]/.test(sym.san) && sym.san[0] !== "N" ? sym.san[0] : "N";
    await (await a.frame()).click("#fixsym button[data-piece='" + piece + "']");
    await a.waitFrame((s) => window.READER.corrections.glyphs[s.sym] === s.piece, { sym: sym.sym, piece }, 300000);
    note("named the piece symbol " + JSON.stringify(sym.sym) + " " + piece + " in " + chapter);

    // the place: a move further on in the chapter
    const place = await a.inFrame(() => {
      const D = window.READER, ids = Object.keys(D.nodes).filter((id) => D.nodes[id].page && D.nodes[id].parent != null);
      const id = ids[Math.floor(ids.length * 2 / 3)];
      location.hash = "#node=" + id;
      return { node: id, page: D.nodes[id].page };
    });
    await a.waitFrame((p) => window.readerState.nodeId === p.node, place);
    const finalPlace = await a.inFrame(() => ({ node: window.readerState.nodeId, page: window.readerState.page }));
    const kept = await a.until(async () => {
      const b = (await a.stored()).books.find((x) => x.id === one.id);
      return b && b.position && b.position.node === finalPlace.node ? b.position : null;
    }, "the place in the book's record", 60000);
    check("the page and the move last read are kept in the book's record",
      kept.chapter === chapter && kept.page === finalPlace.page, { kept, finalPlace });
    const placed = { chapter, page: finalPlace.page, node: finalPlace.node };
    // the second book, for the library's pictures
    await openLibrary(a);
    const two = await addBook(a, book2);
    timing("adding " + path.basename(book2) + ": until read (s)", two.read);
    const est = await a.page.evaluate(async () => {
      const e = await navigator.storage.estimate();
      return { usage: e.usage, quota: e.quota, details: e.usageDetails || null };
    });
    out.storage.afterAdding = est;
    await a.close();

    // ---------------------------------------------------------------- the same device, later
    a = await device("later visit", DESK, profileA);
    await openLibrary(a);
    const row = await a.page.evaluate((id) => {
      const li = document.querySelector("#books li.book[data-id='" + id + "']");
      return li ? li.querySelector(".meta").textContent : null;
    }, one.id);
    check("the library lists the book with its place", row && new RegExp("^Page " + placed.page + " of \\d+").test(row), row);
    const space = await a.page.evaluate(() => document.getElementById("libspace").hidden ? null : document.getElementById("libspace").textContent);
    check("the library says how much room it takes", space && /^The library takes [\d.]+ MB on this device\.$/.test(space), space);
    note("space line: " + space);
    await whenReady(a);
    const re = await openStored(a, one.id, placed);
    timing("opening " + path.basename(book1) + " from the library: until the contents (s)", re.contents);
    timing("opening " + path.basename(book1) + " from the library: until the chapter at the place (s)", re.chapter);
    note("the driver opened the stored reading in " + (await a.page.evaluate(() => LIB.last && LIB.last.seconds)) + " s; " +
         (await a.page.evaluate(() => document.getElementById("took").textContent)));
    const nr = await notReadAgain(a);
    check("the book opens without being read again", nr.ok, nr);
    check("the book opens at the stored page and move", re.at.nodeId === placed.node && re.at.page === placed.page, re.at);
    const g1 = await glyphOf(a, sym.sym);
    check("the book holds the correction", g1.glyph === piece, g1);

    // ---------------------------------------------------------------- saving the books as files
    await a.page.click("#another");
    await a.page.waitForFunction(() => document.body.classList.contains("library") &&
      document.querySelectorAll("#books li.book").length === 2);
    const s1 = await saveFile(a, one.id, file1);
    const s2 = await saveFile(a, two.id, file2);
    note("book files: " + s1.name + " (" + s1.size + " bytes), " + s2.name + " (" + s2.size + " bytes)");
    check("the book file is named after the book", /\.chessbook$/.test(s1.name) && s1.name.startsWith(one.rec.title.slice(0, 10)), s1.name);
    const names = zipNames(file1);
    check("the book file holds the book, its reading, its cover and its record",
      ["book.json", "book.pdf", "reading.gz", "cover.jpg"].every((n) => names.includes(n)), names);
    await a.close();

    // ---------------------------------------------------------------- another device
    const b = await device("another device", IPAD);
    await openLibrary(b);
    check("the other device's library starts empty", await b.page.evaluate(() => document.querySelectorAll("#books li").length === 0));
    await b.instrument();
    const t = now();
    await addFile(b, file1);
    await b.page.waitForFunction(() => /opened from your library/.test(document.getElementById("took").textContent),
                                 null, { timeout: 600000 });
    timing("adding the book file of " + path.basename(book1) + ": until the contents (s)", now() - t);
    const atB = await b.waitFrame((p) => window.READER && window.READER.chapter.file === p.chapter &&
      window.readerState.page === p.page && window.readerState.nodeId === p.node && window.readerState, placed, 300000);
    timing("adding the book file of " + path.basename(book1) + ": until the chapter at the place (s)", now() - t);
    const nrB = await notReadAgain(b);
    check("the book from the file opens without being read", nrB.ok, nrB);
    check("the book from the file opens at the stored page and move", atB.nodeId === placed.node, atB);
    const g2 = await glyphOf(b, sym.sym);
    check("the book from the file holds the correction", g2.glyph === piece, g2);
    const stB = await b.stored();
    check("the book from the file is kept in this browser's library",
      stB.books.length === 1 && stB.books[0].reading && stB.books[0].cover > 0 && stB.files.length === 2, stB);
    // the same file again: the library holds the book already
    await b.page.click("#another");
    await b.page.waitForFunction(() => document.body.classList.contains("library") &&
      document.querySelectorAll("#books li.book").length === 1);
    await addFile(b, file1);
    await b.page.waitForFunction(() => /already in your library/.test(document.getElementById("status").textContent),
                                 null, { timeout: 60000 });
    const dup = await b.page.evaluate(() => document.getElementById("status").textContent);
    check("adding a book the library holds says so", /The file holds the same corrections\./.test(dup), dup);
    // a file with newer corrections replaces those of the device
    const newer = await b.page.evaluate(async (s) => {
      // the reader stores the corrections under chessbook-corrections:<file>:<pages>
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k.startsWith("chessbook-corrections:")) {
          const v = JSON.parse(localStorage.getItem(k));
          delete v.corrections.glyphs[s];
          localStorage.setItem(k, JSON.stringify(v));
          return k;
        }
      }
      return null;
    }, sym.sym);
    check("the device holds the corrections in its storage", !!newer);
    // the change was made "earlier" than the file's: the file's corrections win
    await b.page.evaluate((id) => {
      const m = JSON.parse(localStorage.getItem("chessbook-library:" + id));
      for (const k in localStorage) if (k.startsWith("chessbook-corrections:")) m.corrections = { updated: 1, sent: 0, seen: localStorage.getItem(k) };
      localStorage.setItem("chessbook-library:" + id, JSON.stringify(m));
    }, one.id);
    await b.page.evaluate(() => { document.getElementById("status").textContent = ""; });
    await addFile(b, file1);
    await b.page.waitForFunction(() => /already in your library/.test(document.getElementById("status").textContent),
                                 null, { timeout: 60000 });
    const won = await b.page.evaluate((k) => ({ said: document.getElementById("status").textContent,
                                                  fix: JSON.parse(localStorage.getItem(k)) }), newer);
    check("the newer corrections of a book file win, and the user is told",
      /corrections in the file are newer/.test(won.said) && won.fix.corrections.glyphs[sym.sym] === piece, won);

    // ---------------------------------------------------------------- removing
    await b.page.click("#books li.book[data-id='" + one.id + "'] .remove");
    check("removing asks first", await b.page.evaluate((id) =>
      /Remove this book/.test(document.querySelector("#books li.book[data-id='" + id + "'] .confirm").textContent), one.id));
    await b.page.click("#books li.book[data-id='" + one.id + "'] .confirm .yes");
    await b.page.waitForFunction(() => document.querySelectorAll("#books li.book").length === 0 &&
      !document.getElementById("libempty").hidden);
    const gone = await b.stored();
    const left = await b.page.evaluate(() => Object.keys(localStorage).filter((k) =>
      /^chessbook-(library|corrections|selection):/.test(k)));
    check("a removed book leaves nothing behind", gone.books.length === 0 && gone.files.length === 0 && left.length === 0,
          { gone, left });
    await b.close();

    // ---------------------------------------------------------------- pictures of the library
    for (const [name, opts] of [["iphone13", PHONE], ["ipad_landscape", IPAD]]) {
      for (const scheme of ["light", "dark"]) {
        const s = await device("pictures " + name + " " + scheme, Object.assign({}, opts, { colorScheme: scheme, share: true }));
        await openLibrary(s);
        for (const f of [file2, file1]) {
          await addFile(s, f);
          await s.page.waitForFunction(() => /opened from your library/.test(document.getElementById("took").textContent),
                                       null, { timeout: 600000 });
          await s.page.click("#another");
          await s.page.waitForFunction(() => document.body.classList.contains("library"));
        }
        await s.page.waitForFunction(() => document.querySelectorAll("#books li.book").length === 2 &&
          !document.getElementById("libspace").hidden);
        await s.page.waitForFunction(() => Array.from(document.querySelectorAll("#books img")).every((i) => i.complete && i.naturalWidth > 0));
        await s.page.evaluate(() => { document.getElementById("status").textContent = ""; });
        const wide = await s.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        check("the library does not scroll sideways", wide <= 0, wide);
        if (name === "iphone13") {
          check("an iPhone outside the Home Screen is told to add the page there",
            await s.page.evaluate(() => !document.getElementById("libhint").hidden));
        }
        await s.shot("device_library_" + name + "_" + scheme + ".png");
        if (scheme === "light") {
          await s.page.click("#books li.book:last-child .remove");
          await s.shot("device_library_" + name + "_remove_" + scheme + ".png");
          await s.page.click("#books li.book:last-child .confirm .tb:not(.yes)");
          if (name === "iphone13") {
            await s.page.click("#libhint button");
            check("the Home Screen note can be hidden", await s.page.evaluate(() => document.getElementById("libhint").hidden));
            await s.page.reload();
            await s.page.waitForFunction(() => document.body.classList.contains("library"));
            check("the hidden note stays hidden", await s.page.evaluate(() => document.getElementById("libhint").hidden));
          }
        }
        await s.close();
      }
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
