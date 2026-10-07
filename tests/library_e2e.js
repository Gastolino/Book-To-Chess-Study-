// End-to-end test of the library (web/library.js and server/app.js) in
// Chromium, against the Cloudflare site run locally by `wrangler pages dev`
// with DEV_USER set (tests/test_library.py starts it).
//
// Usage:
//   NODE_PATH=/opt/node22/lib/node_modules node tests/library_e2e.js SITE_URL BOOK1 BOOK2 SCREENS_DIR
//
// The test, with SITE_URL serving a site built with --local:
//   - on a first device (a desktop browser), finds the library empty, adds
//     BOOK1: the book is uploaded, read in the browser as before, and its
//     reading, cover and title reach the library;
//   - names a piece symbol of a chapter (a correction) and chooses a move;
//     the correction and the place reach the server;
//   - adds BOOK2 as well, and takes pictures of the library with two books
//     on an iPhone 13 and an iPad in landscape, light and dark;
//   - on a second device (a fresh browser profile, an iPad in landscape)
//     opens BOOK1 from the library: it opens from the stored reading without
//     being read again, with the correction, at the stored page and move;
//   - removes both books, the first after its confirmation.
// Prints one JSON object {ok, checks, errors, timings, screenshots, notes};
// the exit code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [siteUrl, book1, book2, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], timings: {}, screenshots: [], notes: [] };
let mode = "";
function check(name, cond, detail) {
  out.checks.push({ mode, name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed [" + mode + "]: " + name + (detail !== undefined ? " (" + JSON.stringify(detail).slice(0, 600) + ")" : ""));
}
function note(text) { out.notes.push("[" + mode + "] " + text); }
function timing(name, seconds) { out.timings[name] = Math.round(seconds * 10) / 10; }
const now = () => Date.now() / 1000;

const PHONE = Object.assign({}, devices["iPhone 13"]);
const IPAD = Object.assign({}, devices["iPad Pro 11 landscape"]);
delete PHONE.defaultBrowserType;
delete IPAD.defaultBrowserType;

async function device(browser, name, opts) {
  mode = name;
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
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
  const api = (p, method, body) => page.evaluate(async ([p, method, body]) => {
    const r = await fetch("api/" + p, { method: method || "GET", body: body || undefined, cache: "no-store" });
    return { status: r.status, json: await r.json().catch(() => null) };
  }, [p, method, body]);
  const until = async (fn, what, timeout) => {
    const t0 = Date.now();
    for (;;) {
      const v = await fn();
      if (v) return v;
      if (Date.now() - t0 > (timeout || 60000)) throw new Error("timed out waiting for " + what);
      await page.waitForTimeout(250);
    }
  };
  // the messages the page sends the worker
  const instrument = () => page.evaluate(() => {
    window.__sent = [];
    const post = worker.postMessage.bind(worker);
    worker.postMessage = (m, t) => { window.__sent.push(m.type); return post(m, t); };
    window.__said = [];
    const on = worker.onmessage;
    worker.onmessage = (e) => { if (e.data && e.data.type === "status") window.__said.push(e.data.text); return on(e); };
  });
  const shot = async (file) => {
    const p = path.join(screens, file);
    await page.screenshot({ path: p });
    out.screenshots.push(p);
  };
  return { ctx, page, frame, inFrame, waitFrame, api, until, instrument, shot };
}

async function openLibrary(d) {
  // the library, not the book that was open (the app goes back to it otherwise, as after the
  // system closed it): the Library button forgets that record first, and so does this, on the
  // site's own page (a window that has not loaded the site yet cannot reach the record)
  if (!/^https?:/.test(d.page.url())) await d.page.goto(siteUrl);
  await d.page.evaluate(() => {
    // as the Library button does: the record in the page as well, or the page writes it back as it unloads
    try { SESSION.clear(true); } catch (e) { /* no page yet */ }
    try { localStorage.removeItem("chessbook-session"); } catch (e) { /* no page yet */ }
  }).catch(() => {});
  await d.page.goto(siteUrl);
  await d.page.waitForFunction(() => document.body.classList.contains("library") &&
                               !document.body.classList.contains("resuming"), null, { timeout: 60000 });
}

async function addBook(d, file) {
  const t = now();
  await d.page.waitForFunction(() => window.ready === true || /Ready/.test(document.getElementById("status").textContent),
                               null, { timeout: 300000 });
  await d.page.setInputFiles("#file", file);
  await d.page.waitForSelector("#view", { state: "visible", timeout: 1800000 });
  await d.page.waitForFunction(() => document.body.dataset.book === "read",
                               null, { timeout: 3600000 });
  const read = now() - t;
  const took = await d.page.evaluate(() => document.getElementById("took").textContent);
  // the reading, the cover and the title reach the library
  const id = await d.page.evaluate(() => LIB.current.id);
  const rec = await d.until(async () => {
    const r = await d.api("books/" + id);
    const b = r.json && r.json.book;
    return b && b.reading && b.cover && b.title ? b : null;
  }, "the stored reading of " + path.basename(file), 600000);
  return { id, rec, read, took };
}

async function run() {
  fs.mkdirSync(screens, { recursive: true });
  const browser = await chromium.launch();
  try {
    // ---------------------------------------------------------------- the first device
    const a = await device(browser, "first device", { viewport: { width: 1280, height: 900 } });
    await openLibrary(a);
    let list = await a.api("books");
    check("the library starts empty", list.status === 200 && list.json.books.length === 0, list);
    check("the start page is the library", await a.page.evaluate(() =>
      !document.getElementById("lib").hidden && /Your library/.test(document.querySelector("#start h1").textContent) &&
      !document.getElementById("libempty").hidden));
    await a.instrument();
    const one = await addBook(a, book1);
    timing("first device: adding and reading " + path.basename(book1) + " (s)", one.read);
    note("book 1: " + one.took + "; stored reading " + one.rec.reading.stored + " bytes (gzip), " +
         one.rec.reading.size + " bytes before gzip; title " + JSON.stringify(one.rec.title));
    check("the book was read in the browser", (await a.page.evaluate(() => window.__sent)).includes("process"));
    const pdfBack = await a.page.evaluate(async (id) => {
      const r = await fetch("api/books/" + id + "/pdf");
      const b = new Uint8Array(await r.arrayBuffer());
      const d = new Uint8Array(await crypto.subtle.digest("SHA-256", b));
      return Array.from(d, (x) => x.toString(16).padStart(2, "0")).join("");
    }, one.id);
    check("the stored PDF is the book (its SHA-256 is its id)", pdfBack === one.id);

    // a correction: a piece symbol named in the first chapter that prints one
    let sym = null, chapter = null;
    const chapters = await a.page.evaluate(() => bookChapters.map((c) => c.file));
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
    // the pencil on: a tap on a move opens its corrector
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
    const fixed = await a.until(async () => {
      const r = await a.api("books/" + one.id + "/corrections");
      const c = r.json && r.json.data && r.json.data.corrections;
      return c && c.glyphs && c.glyphs[sym.sym] === piece ? r.json : null;
    }, "the correction on the server", 60000);
    check("the correction reaches the server", fixed.updated > 0);

    // the place: a move further on in the chapter
    const place = await a.inFrame(() => {
      const D = window.READER, ids = Object.keys(D.nodes).filter((id) => D.nodes[id].page && D.nodes[id].parent != null);
      const id = ids[Math.floor(ids.length * 2 / 3)];
      location.hash = "#node=" + id;
      return { node: id, page: D.nodes[id].page };
    });
    await a.waitFrame((p) => window.readerState.nodeId === p.node, place);
    const placed = await a.until(async () => {
      const r = await a.api("books/" + one.id);
      const p = r.json.book.position;
      return p && p.node === place.node ? p : null;
    }, "the place on the server", 60000);
    const finalPlace = await a.inFrame(() => ({ node: window.readerState.nodeId, page: window.readerState.page }));
    check("the page and the move last read reach the server",
      placed.chapter === chapter && placed.node === finalPlace.node && placed.page === finalPlace.page, { placed, finalPlace });

    // the second book, for the library's pictures
    await openLibrary(a);
    const two = await addBook(a, book2);
    timing("first device: adding and reading " + path.basename(book2) + " (s)", two.read);
    await a.ctx.close();

    // ---------------------------------------------------------------- pictures of the library
    for (const [name, opts] of [["iphone13", PHONE], ["ipad_landscape", IPAD]]) {
      for (const scheme of ["light", "dark"]) {
        const s = await device(browser, "pictures " + name + " " + scheme, Object.assign({}, opts, { colorScheme: scheme }));
        await openLibrary(s);
        await s.page.waitForFunction(() => document.querySelectorAll("#books li.book").length === 2);
        await s.page.waitForFunction(() => Array.from(document.querySelectorAll("#books img")).every((i) => i.complete && i.naturalWidth > 0));
        const wide = await s.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        check("the library does not scroll sideways", wide <= 0, wide);
        await s.shot("library_" + name + "_" + scheme + ".png");
        if (name === "iphone13" && scheme === "light") {
          await s.page.click("#books li.book:last-child .remove");
          await s.shot("library_" + name + "_remove_" + scheme + ".png");
        }
        await s.ctx.close();
      }
    }

    // ---------------------------------------------------------------- the second device
    const b = await device(browser, "second device", IPAD);
    await openLibrary(b);
    const row = await b.page.evaluate((id) => {
      const li = document.querySelector("#books li.book[data-id='" + id + "']");
      return li ? li.querySelector(".meta").textContent : null;
    }, one.id);
    check("the library lists the book with its place", row && new RegExp("^Page " + finalPlace.page + " of \\d+").test(row), row);
    await b.instrument();
    const t = now();
    await b.page.click("#books li.book[data-id='" + one.id + "'] .open");
    await b.page.waitForFunction(() => document.body.dataset.book === "opened",
                                 null, { timeout: 600000 });
    timing("second device: opening " + path.basename(book1) + " from the library, until the reading opens (s)", now() - t);
    note("second device: the driver opened the stored reading in " +
         (await b.page.evaluate(() => LIB.last && LIB.last.seconds)) + " s");
    const atPlace = await b.waitFrame((p) => window.READER && window.READER.chapter.file === p.chapter &&
      window.readerState.page === p.page && window.readerState.nodeId === p.node && window.readerState, placed, 300000);
    timing("second device: opening " + path.basename(book1) + " from the library, until the chapter at the place (s)", now() - t);
    const sent = await b.page.evaluate(() => window.__sent);
    const said = await b.page.evaluate(() => window.__said);
    check("the second device opens the book without reading it again",
      sent.includes("restore") && !sent.includes("process") && !said.some((s) => /Reading the moves/.test(s)), { sent, said });
    check("the second device opens at the stored page and move", atPlace.nodeId === placed.node, atPlace);
    const there = await b.inFrame((s) => {
      const D = window.READER;
      const ns = Object.values(D.nodes).filter((n) => n.symbol === s);
      return { glyph: D.corrections.glyphs[s] || null, moves: ns.length,
               corrected: ns.filter((n) => n.corrected === "symbol").length };
    }, sym.sym);
    check("the second device holds the correction", there.glyph === piece, there);
    note("second device: " + (await b.page.evaluate(() => document.getElementById("took").textContent)) +
         "; moves with the symbol in the chapter: " + there.moves + ", corrected: " + there.corrected);
    const stored = await b.page.evaluate((id) => localStorage.getItem("chessbook-library:" + id), one.id);
    check("the second device keeps the server's corrections in its storage", stored && /corrections/.test(stored), stored);

    // ---------------------------------------------------------------- closed by the system, and back
    // a step forward, then the page hidden and dropped at once (as an iPhone
    // drops a page in the background): the place reaches the server without
    // the usual wait, and the page loaded again comes back to the book there
    // (a step back when the move ends its line, since forward then has nowhere to go)
    await b.inFrame(() => {
      const id = window.readerState.nodeId, n = id && window.READER.nodes[id];
      document.getElementById(n && n.children && n.children.length ? "bfwd" : "bback").click();
    });
    const moved = await b.waitFrame((p) => window.readerState.nodeId !== p && window.readerState, placed.node);
    await b.page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: false }));
    });
    const prompt = await b.until(async () => {
      const r = await b.api("books/" + one.id);
      const p = r.json.book.position;
      return p && p.node === moved.nodeId ? p : null;
    }, "the place on the server after the page was hidden", 3000);
    check("the place reaches the server at once when the page is hidden", prompt.page === moved.page, { prompt, moved });
    await b.page.evaluate(() => { window.__sent = []; });
    await b.page.addInitScript(() => {
      window.__sent = [];
      const post = Worker.prototype.postMessage;
      Worker.prototype.postMessage = function (m, t) { window.__sent.push(m && m.type); return t === undefined ? post.call(this, m) : post.call(this, m, t); };
    });
    const tb = now();
    await b.page.reload();
    await b.page.waitForFunction(() => /^Back to /.test(document.getElementById("took").textContent), null, { timeout: 600000 });
    const backAt = await b.waitFrame((p) => window.READER && window.READER.chapter.file === p.chapter &&
      window.readerState.nodeId === p.nodeId && window.readerState, Object.assign({ chapter: placed.chapter }, moved), 300000);
    timing("second device: back in the book after the page loaded again (s)", now() - tb);
    const tookBack = await b.page.evaluate(() => document.getElementById("took").textContent);
    check("the page loaded again comes back to the book at the move, from the server's library",
      /^Back to .*, page /.test(tookBack) && backAt.page === moved.page &&
      (await b.page.evaluate(() => window.__sent.includes("restore") && !window.__sent.includes("process"))),
      { tookBack, backAt });
    check("the library page did not show on the way back", await b.page.evaluate(() => document.getElementById("start").style.display === "none"));

    // ---------------------------------------------------------------- removing
    await b.page.click("#another");
    await b.page.waitForFunction(() => document.body.classList.contains("library") &&
      document.querySelectorAll("#books li.book").length === 2);
    await b.page.click("#books li.book[data-id='" + one.id + "'] .remove");
    check("removing asks first", await b.page.evaluate((id) =>
      /Remove this book/.test(document.querySelector("#books li.book[data-id='" + id + "'] .confirm").textContent), one.id));
    await b.page.click("#books li.book[data-id='" + one.id + "'] .confirm .yes");
    await b.page.waitForFunction(() => document.querySelectorAll("#books li.book").length === 1);
    await b.page.click("#books li.book .remove");
    await b.page.click("#books li.book .confirm .yes");
    await b.page.waitForFunction(() => document.querySelectorAll("#books li.book").length === 0 &&
      !document.getElementById("libempty").hidden);
    list = await b.api("books");
    check("removed books are gone from the library", list.json.books.length === 0, list.json);
    const gone = await b.api("books/" + one.id + "/pdf");
    check("a removed book's file is gone", gone.status === 404, gone.status);
    await b.ctx.close();
    out.ok = true;
  } catch (e) {
    out.failure = String(e && e.stack || e);
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
}

run();
