// End-to-end test of the browser app (tools/build_web.py) in Chromium, with
// Python running through Pyodide in the page's worker.
//
// Usage:
//   NODE_PATH=/opt/node22/lib/node_modules node tests/app_e2e.js SITE_URL BOOK_PDF SCREENS_DIR [desktop,phone]
//
// SITE_URL serves a site built with --local (a Pyodide folder copied into the
// site). For each mode (desktop at 1280 x 900, and an iPhone at 390 x 844) the
// test, in a fresh browser profile:
//   - loads the site and waits for "Ready" (numpy and OpenCV may be missing:
//     the app then reads the book without board reading);
//   - uploads the book; it opens at its first page in the reader while the book
//     is still read (SITE_URL may carry ?pace=MS, which slows each step of the
//     reading down, so that a small book is read slowly enough for the
//     following): the front matter's page is ticked, the page counter counts
//     the whole book, the pictures of the pages come ten at a time, and the
//     page after a chapter's last page is the next chapter's first page;
//   - the Contents button opens the contents, which say that the book is
//     still read, and "Back to page N" (and the browser's back) come back;
//   - opens the first chapter before the reading finishes, waits for its first
//     reading and steps through its moves; reading mode says it is a first
//     reading;
//   - opens a later chapter, which is read before the chapters in between,
//     makes a correction there (a new line at a move) and chooses that move;
//   - waits for the final reading: it reaches the open chapter as a patch, the
//     page and the chosen move stay put, and the correction survives;
//   - opens a chapter with its Open link;
//   - turns the pencil on and corrects a move read without doubt to another
//     legal move: the patch arrives, the page and the move stay put, and the
//     moves after it change; removing the correction turns them back into
//     decoded moves, in window.readerState, READER and the outlines on the page,
//     without the page navigating; the correction is then made again and kept;
//   - adds a variation by taps on the board, makes it longer and removes it;
//   - corrects a diagram, joins a sequence to a line (connect) and starts a new
//     line at a move (disconnect), each answered by a patch;
//   - names a piece symbol and waits until the background batches ("Applying
//     your piece choice to the other chapters: i of n.") finish; meanwhile it
//     opens a chapter the batches have not reached and checks that the symbol
//     is already applied there, and corrects something in it;
//   - stores a diagram correction in the browser only (as a correction that
//     never reached the worker) and checks that it applies when its chapter
//     opens, without Read again;
//   - opens the contents page and checks that its counts show the corrections;
//   - goes back to the first chapter and checks every correction is still there;
//   - forgets the book in the browser's library (keeping the corrections),
//     loads the page again (without pace), uploads the book again, and checks
//     that the stored corrections are applied to the new reading.
// Screenshots of each step go to SCREENS_DIR (NAME_desktop.png, NAME_phone.png).
// Prints one JSON object {ok, checks, errors, timings, screenshots, notes};
// the exit code is 1 when a check fails.
const { chromium, devices } = require("playwright");
const path = require("path");
const fs = require("fs");

const [siteUrl, bookPdf, screens, modesArg] = process.argv.slice(2);
const MODES = (modesArg || "desktop,phone").split(",");
const out = { ok: false, checks: [], errors: [], timings: {}, screenshots: [], notes: [] };
let mode = "";
function check(name, cond, detail) {
  out.checks.push({ mode, name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed [" + mode + "]: " + name + (detail !== undefined ? " (" + JSON.stringify(detail).slice(0, 600) + ")" : ""));
}
function note(text) { out.notes.push("[" + mode + "] " + text); }
function timing(name, seconds) { out.timings[mode + ": " + name] = Math.round(seconds * 1000) / 1000; }
const now = () => Date.now() / 1000;

async function run(browser, which) {
  mode = which;
  const opts = which === "phone"
    ? Object.assign({}, devices["iPhone 13"], { viewport: { width: 390, height: 844 } })
    : { viewport: { width: 1280, height: 900 } };
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  page.on("console", (m) => {
    // the missing numpy and OpenCV files of a site without them, and the missing favicon
    if (m.type() === "error" && !/Failed to load resource: the server responded with a status of 404/.test(m.text()))
      out.errors.push("[" + which + "] " + m.text());
  });
  page.on("pageerror", (e) => out.errors.push("[" + which + "] " + String(e)));
  const shot = async (name) => {
    const p = path.join(screens, name + "_" + which + ".png");
    await page.screenshot({ path: p });
    out.screenshots.push(p);
  };
  const frame = async () => (await page.$("#view")).contentFrame();
  // evaluate in the reader frame, retrying while the frame navigates
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
      if (Date.now() - t0 > (timeout || 120000)) {
        const said = await page.evaluate(() => document.getElementById("note").textContent).catch(() => "");
        const msg = await (await frame()).evaluate(() => (document.getElementById("pagemsg") || {}).textContent).catch(() => "");
        throw new Error("timed out waiting in the reader: " + fn.toString().slice(0, 200) + " | top bar: " + said + " | page: " + msg);
      }
      await page.waitForTimeout(100);
    }
  };
  const note_ = () => page.evaluate(() => document.getElementById("note").textContent);
  const fixOf = () => inFrame(() => JSON.parse(window.correctionsText()));
  // the worker's messages, counted by the page shell
  const instrument = () => page.evaluate(() => {
    window.__sent = []; window.__inflight = 0; window.__maxInflight = 0;
    const post = worker.postMessage.bind(worker);
    worker.postMessage = (m, t) => {
      window.__sent.push({ type: m.type, chapters: m.chapters, chapter: m.chapter });
      if (m.type === "correct-more") { window.__inflight++; window.__maxInflight = Math.max(window.__maxInflight, window.__inflight); }
      return post(m, t);
    };
    const on = worker.onmessage;
    worker.onmessage = (e) => { if (e.data && e.data.type === "patch" && e.data.more) window.__inflight--; return on(e); };
  });

  // ---------------------------------------------------------------- start
  let t0 = now();
  await page.goto(siteUrl);
  await page.waitForFunction(() => /Ready/.test(document.getElementById("status").textContent), null, { timeout: 300000 });
  timing("start until Ready (s)", now() - t0);
  const startText = await page.evaluate(() => document.getElementById("status").textContent);
  // the start page is the library in this browser (web/library.js), empty in a fresh profile
  check("the app is ready", /Ready\. (Choose a book|Open a book or add one)\./.test(startText), startText);
  await shot("01_ready");
  await instrument();

  const goPage = async (p) => {
    await inFrame((p) => { location.hash = "#page=" + p; }, p);
    await waitFrame((p) => window.readerState.page === p, p);
  };
  const tapMark = async (sel) => {
    await inFrame((sel) => { const el = document.querySelector(sel); el.scrollIntoView({ block: "center" }); }, sel);
    const f = await frame();
    await f.click(sel);
  };
  // ---------------------------------------------------------------- upload
  // the contents page shows as soon as the chapters are known; the book is read on
  // a new book opens at its first page in the reader
  const upload = async () => {
    const t = now();
    await page.setInputFiles("#file", bookPdf);
    await page.waitForSelector("#view", { state: "visible", timeout: 1800000 });
    await waitFrame(() => window.READER && window.readerState && window.readerState.page, null, 1800000);
    return now() - t;
  };
  const tookText = () => page.evaluate(() => document.getElementById("took").textContent);
  const loading = async () => (await page.evaluate(() => document.body.dataset.book)) !== "read";
  // the final book: the body's data-book says the reading is done, and an open contents page shows the counts
  const waitFinal = async () => {
    await page.waitForFunction(() => document.body.dataset.book === "read",
      null, { timeout: 3600000 });
    if (await page.evaluate(() => openChapter === "index.html"))
      await waitFrame(() => !window.READER && !!document.querySelector("li.chapter") &&
        !/is reading the book/.test(document.querySelector("main").innerText), null, 300000);
  };
  const tUpload = now();
  let secs = await upload();
  timing("upload until the first page shows (s)", secs);
  const took0 = await tookText();
  const first0 = await inFrame(() => ({ page: window.readerState.page, chapter: window.READER.chapter,
    use: document.getElementById("usepage").checked, total: document.getElementById("pagetotal").textContent,
    pageCount: window.READER.pageCount, pages: Object.keys(window.READER.pages).map(Number) }));
  check("a new book opens at its first page in the reader", first0.page === 1, first0);
  check("the book opens while it is still read", await loading(), took0);
  check("the thin line under the top bar moves while the book is read",
    await page.evaluate(() => document.getElementById("topbar").classList.contains("on")));
  check("the small book at the top right shows that the program is at work",
    await page.evaluate(() => { const b = document.getElementById("busy"); return b.classList.contains("on") &&
      getComputedStyle(b).visibility === "visible" && b.querySelectorAll(".leaf").length === 1; }));
  // the words of the work stay out of the bar, which names the book: a tap on the small book shows them
  await page.click("#busy");
  const told = await page.evaluate(() => ({ tip: document.getElementById("tip").hidden ? "" : document.getElementById("tip").textContent,
    words: document.getElementById("took").textContent, name: document.getElementById("booktitle").textContent,
    inBar: document.getElementById("took").getClientRects().length > 0 }));
  check("a tap on the small book says how far the reading has come",
    /^Reading/.test(took0) && told.words.length > 0 && told.tip.startsWith(told.words) && !told.inBar && told.name.length > 0,
    Object.assign({ took0 }, told));
  await page.click("#tip");
  if (first0.chapter.index === 0)
    check("the front matter's pages are read by default: page 1 is ticked", first0.use, first0);
  check("the page counter counts the whole book", /^of \d+$/.test(first0.total), first0);
  // the pictures come ten pages at a time: the window of the page shown first
  await waitFrame(() => !document.getElementById("pagebox").classList.contains("waiting") &&
    document.getElementById("pageimg").naturalWidth > 0, null, 300000);
  const pics0 = await page.evaluate(() => Object.assign({}, window.pictureStats));
  check("the pictures of the pages come in windows of ten pages",
    pics0.draws >= 1 && pics0.drawn <= 10 * pics0.draws + 10 && pics0.delivered >= 1, pics0);
  await shot("02_first_page");
  // the next page after the last page of a chapter is the first page of the next chapter
  {
    const ch = first0.chapter;
    if (ch.end < first0.pageCount) {
      for (let p = 1; p <= ch.end; p++) {
        await inFrame(() => document.getElementById("nextpage").click());
        await waitFrame((q) => window.readerState && window.readerState.page === q, Math.min(p + 1, first0.pageCount), 300000);
      }
      const nx = await inFrame(() => ({ page: window.readerState.page, file: window.READER.chapter.file,
        start: window.READER.chapter.start, total: document.getElementById("pagetotal").textContent }));
      check("turning past a chapter's last page shows the next chapter's first page",
        nx.file !== ch.file && nx.page === ch.end + 1 && nx.start === ch.end + 1, { nx, ch });
      check("the page counter runs on over the chapters", nx.total === first0.total, { nx, first0 });
      await waitFrame(() => !document.getElementById("pagebox").classList.contains("waiting"), null, 300000);
      await shot("02b_next_chapter");
      await inFrame(() => document.getElementById("prevpage").click());
      await waitFrame((q) => window.READER.chapter.file === q.file && window.readerState.page === q.page,
        { file: ch.file, page: ch.end }, 300000);
      check("turning back from a chapter's first page shows the previous chapter's last page", true);
    } else note("the book has one chapter: no page turn across chapters");
  }
  // the contents, on request; one tap comes back
  await inFrame(() => document.querySelector("a.nav[href='index.html']").click());
  await waitFrame(() => !window.READER && !!document.querySelector("li.chapter"), null, 300000);
  const back0 = await page.evaluate(() => ({ hidden: document.getElementById("backbtn").hidden,
    text: document.getElementById("backbtn").textContent }));
  check("the contents show a way back to the page", !back0.hidden && /^Back to page /.test(back0.text), back0);
  check("the contents page says that the book is still read",
    /is reading the book/.test(await inFrame(() => document.querySelector("main").innerText)));
  await shot("02_contents_loading");
  const backAt = await page.evaluate(() => { const b = document.getElementById("backbtn"); b.click(); return b.textContent; });
  await waitFrame(() => window.READER && window.readerState && window.readerState.page, null, 300000);
  check("Back to page N comes back to that page",
    await inFrame((t) => ("Back to page " + document.getElementById("pagenum").value) === t, backAt), backAt);
  await inFrame(() => document.querySelector("a.nav[href='index.html']").click());
  await waitFrame(() => !window.READER && !!document.querySelector("li.chapter"), null, 300000);
  await page.goBack();
  await waitFrame(() => window.READER && window.readerState && window.readerState.page, null, 300000);
  check("the browser's back comes back from the contents to the page", true);
  await inFrame(() => document.querySelector("a.nav[href='index.html']").click());
  await waitFrame(() => !window.READER && !!document.querySelector("li.chapter"), null, 300000);
  const openLink = async (file) => {
    const t = now();
    await inFrame((f) => { const a = document.querySelector("li.chapter a.read[href='" + f + "']"); a.click(); }, file);
    await waitFrame((f) => window.READER && window.READER.chapter && window.READER.chapter.file === f &&
      window.readerState && window.readerState.page, file, 300000);
    return now() - t;
  };
  const backToContents = async () => {
    await inFrame(() => document.querySelector("a.nav[href='index.html']").click());
    await waitFrame(() => !window.READER && !!document.querySelector("li.chapter"), null, 300000);
  };
  const files0 = await inFrame(() => [...document.querySelectorAll("li.chapter a.read")].map((a) => a.getAttribute("href")));
  const first = files0.find((f) => f !== "ch00.html") || files0[0];
  const later = files0.filter((f) => f !== "ch00.html" && f !== first).pop() || null;

  // ---------------------------------------------------------------- the first chapter while the book is read
  secs = await openLink(first);
  timing("opening " + first + " while the book is read (s)", secs);
  const r1 = await inFrame(() => window.READER.reading);
  check("the first chapter opens before the reading finishes", await loading() && (r1 === "pages" || r1 === "first"), { r1 });
  await shot("03_first_chapter_loading");
  await waitFrame(() => window.READER.lineOrder.length > 0 && window.READER.reading === "first", null, 1800000);
  timing("upload until " + first + " shows its moves (s)", now() - tUpload);
  check("the first chapter shows its moves before the reading finishes", await loading());
  // step through the moves of its first line
  await inFrame(() => { const b = document.querySelector("#chips [data-line]"); if (b) b.click(); else {
    const D = window.READER; window.__sel = D.lines[D.lineOrder[0]].root; } });
  const stepped = [];
  for (let i = 0; i < 4; i++) {
    await inFrame(() => document.getElementById("bfwd").click());
    stepped.push(await inFrame(() => ({ node: window.readerState.nodeId, fen: window.readerState.fen })));
  }
  check("the moves of the first reading can be stepped through",
    new Set(stepped.map((x) => x.fen)).size >= 3 && stepped.every((x) => x.node), stepped);
  await inFrame(() => document.getElementById("showread").click());
  check("reading mode says that the moves are a first reading",
    await inFrame(() => { const n = document.getElementById("provnote"); return n.offsetParent !== null && /first reading/.test(n.textContent); }));
  await shot("04_first_reading_note");
  await inFrame(() => document.getElementById("showread").click());
  check("the note shows in reading mode only",
    await inFrame(() => document.getElementById("provnote").offsetParent === null));

  // ---------------------------------------------------------------- a later chapter jumps the queue
  let L = null;
  if (later && await loading()) {
    await backToContents();
    secs = await openLink(later);
    timing("opening " + later + " while the book is read (s)", secs);
    const r2 = await inFrame(() => window.READER.reading);
    const tOpen = now();
    await waitFrame(() => window.READER.lineOrder.length > 0 && window.READER.reading === "first", null, 1800000);
    timing("opening " + later + " until it shows its moves (s)", now() - tOpen);
    note(later + " opened in the state " + JSON.stringify(r2) + " and showed its moves " +
      (now() - tOpen).toFixed(1) + " s later");
    check("a later chapter opened during the reading shows its moves before the reading finishes", await loading(), r2);
    await shot("05_later_chapter_loading");
    // a move to keep chosen across the final reading, and a correction made while the book is read
    await inFrame(() => window.__stay = 2);
    L = await inFrame(() => {
      const D = window.READER;
      for (const id of D.lineOrder) {
        let cur = D.nodes[D.lines[id].root], k = 0;
        while (cur) {
          const next = (cur.children || []).map((c) => D.nodes[c]).find((n) => n && n.main);
          if (k >= 3 && cur.key && cur.page && cur.status === "ok" && next) return { id: cur.id, key: cur.key, page: cur.page };
          cur = next || null; k++;
        }
      }
      return null;
    });
    check("the later chapter has a move to correct", !!L);
    await goPage(L.page);
    await inFrame((phone) => document.getElementById(phone ? "mpen" : "penbtn").click(), which === "phone");
    await tapMark(".mark[data-node='" + L.id + "']");
    await waitFrame(() => !!document.getElementById("splithere"));
    const tFix = now();
    await (await frame()).click("#splithere");
    await waitFrame((k) => window.READER.corrections.disconnect[k] &&
      Object.values(window.READER.nodes).some((n) => n.key === k && n.corrected === "split"), L.key, 600000);
    timing("a correction while the book is read, to the patch (s)", now() - tFix);
    check("the correction applies while the book is still read", await loading());
    await inFrame((phone) => document.getElementById(phone ? "mpen" : "penbtn").click(), which === "phone");
    await inFrame(() => { const c = document.getElementById("fixclose"); if (c && !document.getElementById("fix").hidden) c.click(); });
    // choose the corrected move, which the final reading must keep chosen
    await inFrame((k) => { const n = Object.values(window.READER.nodes).find((x) => x.key === k);
      document.querySelector(".mark[data-node='" + n.id + "']").click(); }, L.key);
    L.page = await inFrame(() => window.readerState.page);
    await shot("06_correction_loading");
  } else note("the book has no second chapter with lines, or the reading finished before it could be opened");

  // ---------------------------------------------------------------- the final reading
  await waitFinal();
  timing("upload until the final book (s)", now() - tUpload);
  const tl = await page.evaluate(() => new Promise((resolve) => {
    const on = worker.onmessage;
    worker.onmessage = (e) => { if (e.data && e.data.type === "timeline") { worker.onmessage = on; resolve(e.data.timeline); } else on(e); };
    worker.postMessage({ type: "timeline" });
  }));
  note("the worker's timeline: " + JSON.stringify(tl));
  if (L) {
    await waitFrame(() => window.READER.reading === null, null, 120000);
    const fin = await inFrame((k) => {
      const D = window.READER, n = Object.values(D.nodes).find((x) => x.key === k);
      return { stay: window.__stay, page: window.readerState.page, node: window.readerState.nodeId,
               chosen: n ? n.id : null, corrected: n ? n.corrected : null, fix: !!D.corrections.disconnect[k],
               said: document.getElementById("pagemsg").textContent };
    }, L.key);
    check("the final reading reaches the open chapter as a patch", fin.stay === 2, fin);
    check("the final reading says nothing on the page outside reading mode", !/whole book/.test(fin.said), fin);
    check("the final reading keeps the page", fin.page === L.page, { fin, L });
    check("the final reading keeps the chosen move", fin.node && fin.node === fin.chosen, fin);
    check("the correction made while the book was read survives the final reading", fin.corrected === "split" && fin.fix, fin);
    await shot("07_final_reading");
    await backToContents();
  } else if (await page.evaluate(() => openChapter !== "index.html")) await backToContents();
  const took = await tookText(), secs0 = await page.evaluate(() => document.body.dataset.seconds);
  check("once the book is read the small book has no words of the work to show", took === "" && /^\d+$/.test(secs0 || ""), { took, secs0 });
  await shot("02_contents");
  const chapters = await inFrame(() => [...document.querySelectorAll("li.chapter")].map((li) => {
    const a = li.querySelector("a.read");
    const cells = [...li.querySelectorAll(".cn")].map((c) => parseInt(c.textContent.replace(/,/g, ""), 10));
    return { id: li.id, file: a ? a.getAttribute("href") : null, cells };
  }));
  const summary0 = await inFrame(() => document.querySelector("main").innerText);
  const withLines = chapters.filter((c) => c.file && c.cells.length && c.cells[0] > 0)
    .sort((a, b) => b.cells[1] - a.cells[1]);
  check("the book has a chapter with lines", withLines.length > 0, chapters);

  // ---------------------------------------------------------------- a chapter
  const openFromContents = async (file) => {
    const t = now();
    await inFrame((f) => { const a = document.querySelector("li.chapter a.read[href='" + f + "']"); a.click(); }, file);
    await waitFrame((f) => window.READER && window.READER.chapter && window.READER.chapter.file === f &&
      window.readerState && window.readerState.page, file, 300000);
    return now() - t;
  };
  const toContents = async () => {
    const t = now();
    await inFrame(() => document.querySelector("a.nav[href='index.html']").click());
    await waitFrame(() => !window.READER && !!document.querySelector("li.chapter"), null, 300000);
    return now() - t;
  };
  const A = withLines[0];
  secs = await openFromContents(A.file);
  timing("first opening of a chapter (s)", secs);
  await shot("03_chapter");
  await inFrame(() => { window.__stay = 1; });
  const stayed = () => inFrame(() => window.__stay === 1);

  // the pencil
  await page.waitForTimeout(300);
  await inFrame((phone) => document.getElementById(phone ? "mpen" : "penbtn").click(), which === "phone");
  check("the pencil turns on", await inFrame(() => document.body.classList.contains("pencil")));

  // a move read without doubt, with three decoded moves after it in its main line,
  // the second of which moves the piece this move moved: another move that does
  // not reach the same square leaves that move illegal
  const target = await inFrame(() => {
    const D = window.READER;
    let fallback = null;
    for (const id of D.lineOrder) {
      const L = D.lines[id];
      const main = [];
      let cur = D.nodes[L.root];
      while (cur) {
        main.push(cur.id);
        const next = (cur.children || []).map((c) => D.nodes[c]).find((n) => n && n.main);
        cur = next || null;
      }
      for (let i = 3; i + 3 < main.length; i++) {
        const n = D.nodes[main[i]];
        const after = main.slice(i + 1, i + 4).map((x) => D.nodes[x]);
        if (!(n.status === "ok" && n.key && n.page && n.bbox && n.uci && after.every((x) => x.status === "ok" && x.page && x.key)))
          continue;
        const t = { id: n.id, san: n.san, key: n.key, page: n.page, to: n.uci.slice(2, 4), after: after.map((x) => x.key) };
        if (after[1].uci && after[1].uci.slice(0, 2) === n.uci.slice(2, 4)) return t;
        fallback = fallback || t;
      }
    }
    return fallback;
  });
  check("the chapter has a move read without doubt with decoded moves after it", !!target);
  await goPage(target.page);
  await tapMark(".mark[data-node='" + target.id + "']");
  await waitFrame(() => !document.getElementById("fix").hidden && document.getElementById("fixsan"));
  const dest = (san) => { const m = /([a-h][1-8])(=[QRBN])?[+#]?$/.exec(san); return m ? m[1] : null; };
  const alts = (await inFrame((san) => [...document.querySelectorAll("#fixlist button[data-san]")]
    .map((b) => b.dataset.san).filter((s) => s !== san), target.san))
    .sort((a, b) => (dest(a) === target.to) - (dest(b) === target.to));
  check("the corrector lists other legal moves", alts.length > 0, alts);
  await shot("04_move_corrector");
  // a move that leaves the next printed move illegal: try the alternatives in turn
  const following = (keys) => inFrame((keys) => keys.map((k) => {
    const n = Object.values(window.READER.nodes).find((x) => x.key === k);
    const el = n ? document.querySelector(".mark[data-node='" + n.id + "']") : null;
    return n ? { key: k, san: n.san, status: n.status, cls: el ? el.className : null } : { key: k, gone: true };
  }), keys);
  let flip = null, broken = null, patchSecs = null;
  const orig = await following(target.after);
  for (const alt of alts.slice(0, 6)) {
    const t = now();
    await inFrame((alt) => {
      const inp = document.getElementById("fixsan");
      inp.value = alt;
      inp.dispatchEvent(new Event("input"));
      inp.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    }, alt);
    await waitFrame((a) => {
      const c = window.READER.corrections.moves[a.key];
      return c && c.san === a.alt;
    }, { key: target.key, alt });
    patchSecs = now() - t;
    const st = await following(target.after);
    if (st.some((x) => x.gone || x.status !== "ok")) { flip = alt; broken = st; break; }
    note("correcting " + target.san + " to " + alt + " left the next moves decoded: " +
      st.map((x) => x.san + (orig.find((o) => o.key === x.key).san !== x.san ? " (printed " +
        orig.find((o) => o.key === x.key).san + ")" : "")).join(" ") + "; trying another move");
  }
  check("a different legal move breaks the moves after it", !!flip, { target, alts });
  timing("single correction, from the choice to the patch (s)", patchSecs);
  const afterFlip = await inFrame(() => ({ page: window.readerState.page, node: window.readerState.nodeId }));
  check("the patch keeps the page", afterFlip.page === target.page, afterFlip);
  check("the patch keeps the move", afterFlip.node === target.id || !!afterFlip.node, afterFlip);
  check("the page did not navigate", await stayed());
  const flipNode = await inFrame((id) => window.READER.nodes[id] || null, afterFlip.node);
  check("the move now holds the correction", flipNode && flipNode.san === flip && flipNode.corrected === "move", flipNode);
  await shot("05_move_corrected");
  // remove it: the moves after it decode again
  await waitFrame(() => !!document.getElementById("fixundo"));
  let t = now();
  await inFrame(() => document.getElementById("fixundo").click());
  await waitFrame((k) => !window.READER.corrections.moves[k], target.key);
  timing("removing a correction, to the patch (s)", now() - t);
  const back = await following(target.after);
  check("the following moves turn decoded again without navigation",
    back.every((x, i) => !x.gone && x.status === "ok" && x.san === orig[i].san) && await stayed(), { back, orig });
  check("their outlines on the page show decoded moves",
    back.filter((x) => x.cls).every((x) => /st-ok/.test(x.cls)), back);
  check("readerState keeps the move", await inFrame((id) => window.readerState.nodeId === id &&
    window.readerState.fen === window.READER.nodes[id].fen, afterFlip.node));
  // the correction again, kept for the rest of the test
  t = now();
  await inFrame((alt) => {
    const inp = document.getElementById("fixsan");
    inp.value = alt;
    inp.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  }, flip);
  await waitFrame((a) => { const c = window.READER.corrections.moves[a.key]; return c && c.san === a.alt; },
    { key: target.key, alt: flip });
  timing("single correction again (s)", now() - t);

  // ---------------------------------------------------------------- analysis with Stockfish
  // (the site built with --engine: the reader loads the engine from the site, in a worker)
  const engineOn = await inFrame(() => !!window.CHESSBOOK_ENGINE);
  if (engineOn) {
    // a move of the book, shown without a preview of a correction
    await inFrame((id) => { location.hash = "#node=" + id; }, afterFlip.node);
    await waitFrame((id) => window.readerState.nodeId === id && !!window.readerState.fen, afterFlip.node);
    t = now();
    await inFrame(() => document.getElementById("bcpu").click());
    await waitFrame(() => { const s = window.engineState(); return s.failed || (s.ready && s.done && !!s.fen); }, null, 120000);
    const ev = await inFrame(() => ({ s: window.engineState(), num: document.querySelector("#evalbar .enum").textContent,
      rows: document.querySelectorAll("#evlines .evline").length, loaded: window.engineLoaded,
      shown: !document.getElementById("evalbar").hidden && !document.getElementById("evalsec").hidden }));
    timing("engine loaded and the first position analysed (s)", now() - t);
    check("the app's reader shows an eval from the engine", ev.s.ready && !ev.s.failed && ev.shown && /^[+−]\d\.\d$|^−?M\d+$/.test(ev.num) &&
      ev.rows > 0 && ev.loaded && /Stockfish/.test(ev.loaded.name), ev);
    note("engine " + ev.loaded.name + " loaded from the " + ev.loaded.from + " in " + ev.loaded.ms + " ms, depth " + ev.s.depth);
    await shot("05b_analysis");
    await inFrame(() => document.getElementById("bcpu").click());
    check("turning analysis off in the app ends the worker", await inFrame(() => !window.engineState().worker));
  }

  // ---------------------------------------------------------------- a variation added on the board
  // (taps on the board's squares, as pointer events in the reader's frame)
  const boardTap = (sq) => inFrame((sq) => {
    const svg = document.querySelector("#board svg.board"), r = svg.getBoundingClientRect();
    const flip = svg.dataset.flip === "1", f = "abcdefgh".indexOf(sq[0]), row = 8 - parseInt(sq[1], 10);
    const k = r.width / 375, x = r.left + (14 + ((flip ? 7 - f : f) + 0.5) * 45) * k;
    const y = r.top + (1 + ((flip ? 7 - row : row) + 0.5) * 45) * k;
    for (const type of ["pointerdown", "pointerup"])
      svg.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y,
        pointerId: 7, isPrimary: true, button: 0, pointerType: "mouse" }));
  }, sq);
  const newMove = (id) => inFrame((id) => {
    // a legal move from a node's position that the line does not hold there
    const n = window.READER.nodes[id], held = n.children.map((c) => window.READER.nodes[c].uci);
    const m = CJ.legalMoves(n.fen).find((x) => held.indexOf(x[1]) < 0);
    return m ? { san: m[0], uci: m[1] } : null;
  }, id);
  const branch = await inFrame((avoid) => {
    const D = window.READER;
    for (const lid of D.lineOrder) {
      for (let cur = D.lines[lid].root; cur; ) {
        const n = D.nodes[cur];
        if (n.parent != null && n.key && n.fen && n.status === "ok" && n.key !== avoid) return { id: cur, key: n.key };
        cur = n.children.find((c) => D.nodes[c].main) || null;
      }
    }
    return null;
  }, target.key);
  check("the chapter has a move to branch from on the board", !!branch);
  await inFrame((id) => { location.hash = "#node=" + id; }, branch.id);
  await waitFrame((id) => window.readerState.nodeId === id, branch.id);
  let mv = await newMove(branch.id);
  await boardTap(mv.uci.slice(0, 2));
  await boardTap(mv.uci.slice(2, 4));
  await waitFrame(() => !!document.getElementById("bmadd"));
  check("a move on the board that the line does not hold opens the chooser",
    /Add a new variation/.test(await inFrame(() => document.getElementById("fix").innerText)));
  t = now();
  await inFrame(() => document.getElementById("bmadd").click());
  await waitFrame((a) => {
    const n = window.READER.nodes[window.readerState.nodeId];
    return window.READER.corrections.added[a.key] && n && n.corrected === "added" && n.san === a.san;
  }, { key: branch.key, san: mv.san });
  timing("a variation added on the board, to the patch (s)", now() - t);
  check("the app chooses the move added on the board", await stayed());
  await shot("08_board_variation");
  // a move from its end makes it longer, with no question
  const added0 = await inFrame(() => window.readerState.nodeId);
  mv = await newMove(added0);
  await boardTap(mv.uci.slice(0, 2));
  await boardTap(mv.uci.slice(2, 4));
  await waitFrame((a) => {
    const n = window.READER.nodes[window.readerState.nodeId], f = window.READER.corrections.added[a.key];
    return f && f[0].san.length === 2 && n && n.corrected === "added" && n.san === a.san;
  }, { key: branch.key, san: mv.san });
  check("a move from the end of the variation makes it longer without a question",
    await inFrame(() => document.getElementById("fix").hidden));
  // its corrector removes it
  await inFrame(() => document.getElementById("fixadded").click());
  await waitFrame(() => !!document.getElementById("addrm"));
  await inFrame(() => document.getElementById("addrm").click());
  await waitFrame((k) => !window.READER.corrections.added[k] &&
    !Object.values(window.READER.nodes).some((n) => n.corrected === "added"), branch.key);
  check("removing the variation brings back the move it branched from", await inFrame((k) =>
    window.READER.nodes[window.readerState.nodeId] && window.READER.nodes[window.readerState.nodeId].key === k, branch.key));

  // ---------------------------------------------------------------- a diagram
  const diag = await inFrame(() => {
    const D = window.READER;
    for (const p in D.pages) for (const d of D.pages[p].diagrams)
      if (d.selected && D.notPosition.indexOf(d.kind) < 0 && d.status !== "partial") return { id: d.id, page: +p, fen: d.fen || null };
    return null;
  });
  let diagDone = null;
  if (!diag) note("the chapter has no diagram to correct");
  else {
    await goPage(diag.page);
    await tapMark(".diag[data-diagram='" + diag.id + "']");
    await waitFrame(() => !!document.getElementById("fixboard") && !document.getElementById("fix").hidden);
    // the generated test book's ending, or kings on e1 and e8 on an empty board,
    // or the other side to move on a board that was read
    const place = async (sq, piece) => {
      const f = await frame();
      await f.click("#fixboard [data-sq='" + sq + "']");
      await f.click("#fixpieces button[data-put='" + piece + "']");
    };
    const hasKings = (fen) => fen && /K/.test(fen.split(" ")[0]) && /k/.test(fen.split(" ")[0]);
    if (hasKings(diag.fen)) {
      const turn = diag.fen.split(" ")[1] === "w" ? "b" : "w";
      await (await frame()).click("#fix [data-turn='" + turn + "']");
    } else {
      const ending = { g1: "K", d1: "R", f2: "P", g2: "P", h2: "P", g8: "k", f7: "p", g7: "p", h6: "p" };
      for (const [sq, pc] of Object.entries(ending)) await place(sq, pc);
    }
    const can = await inFrame(() => !document.getElementById("fixsave").disabled);
    check("the corrected position can be saved", can, await inFrame(() => document.getElementById("fixmsg").textContent));
    await shot("06_diagram_corrector");
    t = now();
    await (await frame()).click("#fixsave");
    await waitFrame((id) => {
      for (const p in window.READER.pages) for (const d of window.READER.pages[p].diagrams)
        if (d.id === id) return d.corrected && window.READER.corrections.diagrams[id];
      return false;
    }, diag.id);
    timing("diagram correction, to the patch (s)", now() - t);
    diagDone = diag.id;
    const lines = await inFrame((id) => Object.values(window.READER.lines).filter((L) => L.diagram === id)
      .map((L) => ({ id: L.id, status: L.status })), diag.id);
    note("lines from the corrected diagram " + diag.id + ": " + JSON.stringify(lines));
    check("the page did not navigate after the diagram correction", await stayed());
    await shot("07_diagram_corrected");
  }

  // ---------------------------------------------------------------- disconnect
  const split = await inFrame((avoid) => {
    const D = window.READER;
    for (const id of D.lineOrder) {
      const L = D.lines[id];
      let cur = D.nodes[L.root], k = 0;
      while (cur) {
        const next = (cur.children || []).map((c) => D.nodes[c]).find((n) => n && n.main);
        if (k >= 4 && cur.key && cur.page && cur.status === "ok" && avoid.indexOf(cur.key) < 0 && next) return { id: cur.id, key: cur.key, page: cur.page, line: L.id };
        cur = next || null; k++;
      }
    }
    return null;
  }, [target.key].concat(target.after));
  let splitDone = null;
  if (!split) note("no move to start a new line at");
  else {
    await goPage(split.page);
    const nLines = await inFrame(() => window.READER.lineOrder.length);
    await tapMark(".mark[data-node='" + split.id + "']");
    await waitFrame(() => !!document.getElementById("splithere"));
    t = now();
    await (await frame()).click("#splithere");
    await waitFrame((k) => window.READER.corrections.disconnect[k], split.key);
    timing("start a new line (disconnect), to the patch (s)", now() - t);
    const after = await inFrame(() => window.READER.lineOrder.length);
    check("starting a new line adds a line", after === nLines + 1, { nLines, after });
    splitDone = split.key;
    await shot("08_split");
  }

  // ---------------------------------------------------------------- connect
  const seq = await inFrame(() => {
    const D = window.READER;
    const u = D.unattached.find((u) => u.key && D.pages[u.page] && document && true);
    if (!u) return null;
    const num = /^(\d{1,3})\s*(\.\s*\.\s*\.|…|•••)?/.exec(u.text || "");
    const want = num ? parseInt(num[1], 10) : null, black = !!(num && num[2]);
    const mains = Object.values(D.nodes).filter((n) => n.main && n.parent != null && n.key && n.fen && n.page);
    // the move after which the sequence would follow
    const after = mains.filter((n) => want !== null && (black ? n.number === want && !n.black : n.number === want - 1 && n.black));
    const near = (n) => Math.abs(n.page - u.page);
    after.sort((a, b) => near(a) - near(b));
    const pick = after[0] || mains.sort((a, b) => near(a) - near(b))[0];
    return pick ? { key: u.key, page: u.page, text: u.text, to: pick.id, toPage: pick.page, toKey: pick.key } : null;
  });
  let connectDone = null;
  if (!seq) note("the chapter has no sequence placed in no line");
  else {
    await goPage(seq.page);
    await tapMark(".mark[data-seq='" + seq.key + "']");
    await waitFrame(() => !!document.getElementById("fixjoin"));
    await (await frame()).click("#fixjoin");
    check("joining asks for a move", await inFrame(() => document.body.classList.contains("joining")));
    await shot("09_connect");
    await goPage(seq.toPage);
    t = now();
    await tapMark(".mark[data-node='" + seq.to + "']");
    await waitFrame((k) => window.READER.corrections.connect[k], seq.key);
    timing("join a sequence to a line (connect), to the patch (s)", now() - t);
    const where = await inFrame((k) => {
      const D = window.READER;
      const u = D.unattached.find((x) => x.key === k);
      const placed = Object.values(D.nodes).some((n) => n.key && n.corrected === "connected");
      return { left: u ? u.reason : null, placed };
    }, seq.key);
    note("the joined sequence " + JSON.stringify(seq.text) + ": " + JSON.stringify(where));
    check("the joined sequence is placed, or stays in no line with the reason",
      where.placed || /join|tied|legal|unknown/.test(where.left || ""), where);
    connectDone = seq.key;
  }

  // ---------------------------------------------------------------- a piece symbol
  const sym = await inFrame(() => {
    const D = window.READER;
    for (const id in D.nodes) {
      const n = D.nodes[id];
      if (n.symbol && n.key && n.page && n.bbox && D.symbols[n.symbol]) return { id, sym: n.symbol, page: n.page, san: n.san || n.assumed || "" };
    }
    return null;
  });
  let symDone = null, pendingSeen = [], B = null;
  if (!sym) note("the chapter has no piece symbol the text recognition could not name");
  else {
    await goPage(sym.page);
    await tapMark(".mark[data-node='" + sym.id + "']");
    await waitFrame(() => !!document.getElementById("fixsymbol"));
    await (await frame()).click("#fixsymbol");
    await waitFrame(() => !!document.getElementById("fixsym"));
    const piece = /^[KQRBN]/.test(sym.san) ? sym.san[0] : "N";
    await page.evaluate(() => { window.__sent = []; });
    t = now();
    const tSym = t;
    await (await frame()).click("#fixsym button[data-piece='" + piece + "']");
    await waitFrame((s) => window.READER.corrections.glyphs[s.sym] === s.piece, { sym: sym.sym, piece });
    timing("piece symbol, to the open chapter's patch (s)", now() - t);
    await shot("10_symbol");
    symDone = sym.sym;
    // the other chapters, in the background
    const pend = await page.evaluate(() => more.slice());
    pendingSeen = pend;
    const prog = await note_();
    note("symbol " + JSON.stringify(sym.sym) + " named " + piece + "; after it: pending chapters " + JSON.stringify(pend) + "; top bar: " + prog);
    if (pend.length) {
      check("the top bar says the piece choice goes on", /Applying your piece choice to the other chapters: \d+ of \d+\./.test(prog), prog);
      check("the reader page says so as well", /Applying your piece choice/.test(await inFrame(() => document.getElementById("pagemsg").textContent)));
      // a chapter the batches have not reached: open it now
      const last = pend[pend.length - 1];
      B = withLines.find((c) => c.file === "ch" + String(last).padStart(2, "0") + ".html") ||
        { file: "ch" + String(last).padStart(2, "0") + ".html" };
      await toContents();
      const stillPending = await page.evaluate((k) => more.indexOf(k) >= 0, last);
      secs = await openFromContents(B.file);
      timing("opening a chapter while the symbol batches run (s)", secs);
      const there = await inFrame((s) => {
        const D = window.READER;
        const ns = Object.values(D.nodes).filter((n) => n.symbol === s);
        return { with: ns.length, corrected: ns.filter((n) => n.corrected === "symbol").length,
                 failed: ns.filter((n) => n.status === "failed").length,
                 glyph: D.corrections.glyphs[s] || null };
      }, sym.sym);
      note("chapter " + B.file + " opened while " + (stillPending ? "pending" : "already done") + ": " + JSON.stringify(there));
      check("a chapter opened while the batches run holds the piece choice", there.glyph === piece, there);
      // the moves printed with the symbol, as the chapter opened: the batches must not change them later
      const symNodes = () => inFrame((s) => {
        const D = window.READER, o = {};
        for (const n of Object.values(D.nodes)) if (n.symbol === s && n.key) o[n.key] = [n.san, n.status, n.corrected || null, n.line];
        return o;
      }, sym.sym);
      const atOpen = await symNodes();
      await shot("11_pending_chapter");
      // a correction there while the batches still run: a new line at its first suitable move
      await inFrame((phone) => document.getElementById(phone ? "mpen" : "penbtn").click(), which === "phone");
      const sB = await inFrame((s) => {
        const D = window.READER;
        // a line without the symbol, so that the moves printed with it stay comparable
        const withSym = new Set(Object.values(D.nodes).filter((n) => n.symbol === s).map((n) => n.line));
        for (const id of D.lineOrder) {
          if (withSym.has(id)) continue;
          let cur = D.nodes[D.lines[id].root], k = 0;
          while (cur) {
            const next = (cur.children || []).map((c) => D.nodes[c]).find((n) => n && n.main);
            if (k >= 3 && cur.key && cur.page && next) return { id: cur.id, key: cur.key, page: cur.page };
            cur = next || null; k++;
          }
        }
        return null;
      }, sym.sym);
      if (sB) {
        await goPage(sB.page);
        await tapMark(".mark[data-node='" + sB.id + "']");
        await waitFrame(() => !!document.getElementById("notpart"));
        t = now();
        await (await frame()).click("#notpart");
        await waitFrame((k) => window.READER.corrections.disconnect[k] && window.READER.corrections.disconnect[k].remove, sB.key);
        timing("a correction in that chapter during the batches, to the patch (s)", now() - t);
        B.split = sB.key;
      }
      // the batches finish
      await page.waitForFunction(() => /applied to the whole book/.test(document.getElementById("note").textContent), null, { timeout: 1800000 });
      timing("piece symbol, until the whole book holds it (s)", now() - tSym);
      const atEnd = await symNodes();
      const differ = Object.keys(atOpen).filter((k) => k in atEnd && JSON.stringify(atOpen[k]) !== JSON.stringify(atEnd[k]));
      note("moves printed with the symbol in " + B.file + ": " + Object.keys(atOpen).length + ", changed after the opening: " + differ.length);
      check("the chapter opened before the batches reached it needed no later change",
        differ.length === 0, differ.map((k) => [k, atOpen[k], atEnd[k]]));
      const sent = await page.evaluate(() => window.__sent.filter((m) => m.type === "correct-more").map((m) => m.chapters[0]));
      note("correct-more batches sent: " + JSON.stringify(sent));
      const most = await page.evaluate(() => window.__maxInflight);
      check("the batches run as one chain (one batch at a time)", most === 1, { most, sent });
      check("the reader page says the piece choice reached the whole book",
        /applied to the whole book/.test(await inFrame(() => document.getElementById("pagemsg").textContent)));
      await shot("12_symbol_done");
    } else {
      note("the piece symbol appears in this chapter only: no background batches");
    }
  }

  // ---------------------------------------------------------------- a correction stored for a chapter not built yet
  // a chapter not opened yet, or the first chapter again in a book with one chapter of lines
  const C = withLines.find((c) => c.file !== A.file && (!B || c.file !== B.file)) || A;
  let stored = null;
  if (C) {
    await toContents();
    // as if a correction had never reached the worker: stored in the browser only
    const key = await page.evaluate(() => { for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k.startsWith("chessbook-corrections:")) return k; } return null; });
    check("the browser stores the corrections", !!key);
    secs = await openFromContents(C.file);
    // a diagram the test has not corrected (a correction that touches no line the test changed)
    const cand = await inFrame(() => {
      const D = window.READER;
      for (const p in D.pages) for (const d of D.pages[p].diagrams)
        if (d.selected && D.notPosition.indexOf(d.kind) < 0 && d.status !== "partial" && !D.corrections.diagrams[d.id])
          return { id: d.id };
      return null;
    });
    if (cand) {
      await toContents();
      await page.evaluate((a) => {
        const v = JSON.parse(localStorage.getItem(a.key));
        v.corrections.diagrams[a.cand.id] = { fen: "6k1/5pp1/7p/8/8/8/5PPP/3R2K1 w - - 0 1" };
        localStorage.setItem(a.key, JSON.stringify(v));
      }, { key, cand });
      t = now();
      await openFromContents(C.file);
      await waitFrame((id) => window.READER.corrections.diagrams[id], cand.id, 120000);
      timing("a stored correction, applied when its chapter opens (s)", now() - t);
      check("a correction stored in the browser but not applied yet applies when its chapter opens, without Read again",
        await inFrame((id) => { for (const p in window.READER.pages) for (const d of window.READER.pages[p].diagrams)
          if (d.id === id) return !!d.corrected; return false; }, cand.id));
      stored = { file: C.file, diagram: cand.id };
      await shot("13_stored_applied");
    } else note("no move to store a correction for in " + C.file);
  } else note("the book has no third chapter for the stored correction");

  // ---------------------------------------------------------------- the contents page
  secs = await toContents();
  timing("opening the contents page after corrections (s)", secs);
  out.corrections = out.corrections || {};
  out.corrections[which] = await fixOf();
  const after = await inFrame(() => ({
    text: document.querySelector("main").innerText,
    cells: [...document.querySelectorAll("li.chapter")].map((li) => ({ id: li.id,
      cells: [...li.querySelectorAll(".cn")].map((c) => parseInt(c.textContent.replace(/,/g, ""), 10)) })),
  }));
  const m = /The run used your corrections of ([^.]*)\./.exec(after.text);
  check("the contents page counts the corrections", !!m, after.text.slice(0, 800));
  note("contents: " + (m ? m[0] : ""));
  check("the contents page counts the corrected move", /\bmoves?\b/.test(m[1]), m[1]);
  if (diagDone) check("the contents page counts the corrected diagram", /diagram/.test(m[1]), m[1]);
  if (splitDone) check("the contents page counts the new line", /line[s]? started anew/.test(m[1]), m[1]);
  if (symDone) check("the contents page counts the piece symbol", /piece symbol/.test(m[1]), m[1]);
  const a0 = chapters.find((c) => c.id === A.id), a1 = after.cells.find((c) => c.id === A.id);
  check("the chapter's counts changed", JSON.stringify(a0.cells) !== JSON.stringify(a1.cells), { before: a0.cells, after: a1.cells });
  await shot("14_contents_after");

  // ---------------------------------------------------------------- back to the first chapter
  secs = await openFromContents(A.file);
  timing("opening the corrected chapter again (s)", secs);
  const kept = await inFrame((a) => {
    const D = window.READER, nodes = Object.values(D.nodes);
    const byKey = (k) => nodes.find((n) => n.key === k);
    let diag = null;
    for (const p in D.pages) for (const d of D.pages[p].diagrams) if (d.id === a.diag) diag = d;
    return {
      move: byKey(a.move) ? { san: byKey(a.move).san, corrected: byKey(a.move).corrected } : null,
      split: a.split ? (byKey(a.split) || {}).corrected || null : null,
      diag: diag ? !!diag.corrected : null,
      symbol: a.sym ? nodes.filter((n) => n.symbol === a.sym).every((n) => n.corrected === "symbol" || n.status !== "failed") : null,
      connect: a.connect ? !!D.corrections.connect[a.connect] : null,
    };
  }, { move: target.key, split: splitDone, diag: diagDone, sym: symDone, connect: connectDone });
  check("the move correction persists across chapters", kept.move && kept.move.san === flip && kept.move.corrected === "move", kept);
  if (splitDone) check("the new line persists", kept.split === "split", kept);
  if (diagDone) check("the diagram correction persists", kept.diag === true, kept);
  if (connectDone) check("the join persists", kept.connect === true, kept);
  await shot("15_chapter_again");

  // ---------------------------------------------------------------- reload and read the book again
  const storedFix = await fixOf();
  // the library in this browser keeps the book and its reading, and would
  // open it without reading it (tests/device_library_e2e.js tests that): it
  // forgets them here, and keeps the corrections, so that the book is read again
  await page.evaluate(() => new Promise((resolve) => {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k && k.startsWith("chessbook-library:")) localStorage.removeItem(k);
    }
    localStorage.removeItem("chessbook-session");   // (the page would go back to the open book otherwise)
    const q = indexedDB.deleteDatabase("chessbook-library");
    q.onsuccess = q.onerror = () => resolve();
    setTimeout(resolve, 10000);
  }));
  await page.goto(siteUrl.split("?")[0]);
  await page.waitForFunction(() => /Ready/.test(document.getElementById("status").textContent), null, { timeout: 300000 });
  const tAgain = now();
  await upload();
  await waitFinal();
  timing("book processing with the stored corrections (s)", now() - tAgain);
  if (await page.evaluate(() => openChapter !== "index.html")) await toContents();
  const again = await inFrame(() => document.querySelector("main").innerText);
  const m2 = /The run used your corrections of ([^.]*)\./.exec(again);
  check("reading the book again applies the stored corrections", !!m2 && m2[0] === m[0], { before: m && m[0], after: m2 && m2[0] });
  await shot("16_contents_reloaded");
  await openFromContents(A.file);
  const re = await inFrame((a) => {
    const D = window.READER, n = Object.values(D.nodes).find((x) => x.key === a.move);
    return { san: n && n.san, corrected: n && n.corrected, fix: JSON.stringify(D.corrections) };
  }, { move: target.key });
  check("the reloaded chapter holds the move correction", re.san === flip && re.corrected === "move", re);
  const fix2 = await fixOf();
  check("the reloaded chapter's stored corrections equal those before", JSON.stringify(Object.assign({}, fix2, { note: "" })) === JSON.stringify(Object.assign({}, storedFix, { note: "" })));
  check("nothing waits to be applied after the reload", await inFrame(() => !/applies it at once/.test(document.getElementById("pagemsg").textContent)));
  await shot("17_chapter_reloaded");
  if (which === "phone") {
    const sw = await inFrame(() => ({ sw: document.documentElement.scrollWidth, w: window.innerWidth }));
    check("no sideways scroll in the reader at 390 px", sw.sw <= sw.w, sw);
    const shell = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, w: window.innerWidth }));
    check("no sideways scroll in the app at 390 px", shell.sw <= shell.w, shell);
  }
  await ctx.close();
}

(async () => {
  fs.mkdirSync(screens, { recursive: true });
  const exe = process.env.CHROMIUM || "/opt/pw-browsers/chromium";
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  try {
    for (const m of MODES) await run(browser, m);
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
