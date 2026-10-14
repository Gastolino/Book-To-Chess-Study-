// Open one of the audit's books in the browser app, in Chromium, and drive it as a reader does.
//
//   const A = require("/home/user/Book-To-Chess-Study-/tools/audit/app_lib.js");
//   const app = await A.open({ book: "planning", device: "ipad" });   // or "phone", "desktop"
//   await app.gotoPage(12);                 // a PDF page, as tools/audit/page.py numbers it
//   await app.showReading(true);            // Show reading on (the app remembers it between opens)
//   await app.tapMark(key);                 // the box of a printed move (its token key)
//   await app.play("d1", "c1");             // a move on the board: piece, then square
//   console.log(await app.sheet());         // the sheet: {note, line, msg, buttons}
//   console.log(await app.lineFrom(key));   // the line's moves from that move on, with statuses
//   await app.shot("after_qc1");            // output/audit/app/<book>/<name>.png
//   console.log(app.errors);                // console errors and page errors so far
//   await app.close();
//
// Run scripts with NODE_PATH=/opt/node22/lib/node_modules. The app keeps its library in a browser
// profile (output/audit/profiles/<site>/<book>-<device>), so the first open of a book reads it in
// the app (minutes: Python runs in Pyodide) and later opens take it from the library in seconds.
// open({fresh: true}) starts from an empty profile. The reader's own objects are there to read:
// READER (the chapter's reading: pages, marks, nodes, lines), readerState (page, node),
// correctionsText() (the corrections stored). tests/readon_e2e.js and tests/thread_e2e.js show
// the sheet's buttons and what each step of the thread does.
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const BOOKS = JSON.parse(execFileSync("python3", ["-c",
  "import sys,json; sys.path.insert(0, sys.argv[1]); import books; " +
  "print(json.dumps({n: str(books.pdf_path(n)) for n in books.BOOKS}))", __dirname]).toString());
const DEVICES = {
  ipad: { viewport: { width: 1194, height: 834 }, hasTouch: true },
  phone: { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 },
  desktop: { viewport: { width: 1280, height: 800 } },
};
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm",
  ".json": "application/json", ".whl": "application/zip", ".svg": "image/svg+xml", ".png": "image/png",
  ".css": "text/css", ".webmanifest": "application/manifest+json", ".zip": "application/zip", ".data": "application/octet-stream" };

// The browser keeps a library for each origin, port included: each book and device has its own
// port, so that a book read once is in the library at the next open.
function portOf(name) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return 20000 + (h % 20000);
}

function serve(dir, port) {
  return new Promise((resolve, reject) => {
    const srv = http.createServer((req, res) => {
      let p = decodeURIComponent(req.url.split("?")[0]);
      if (p.endsWith("/")) p += "index.html";
      const f = path.join(dir, p);
      if (!f.startsWith(dir) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { "Content-Type": TYPES[path.extname(f)] || "application/octet-stream" });
      fs.createReadStream(f).pipe(res);
    });
    srv.once("error", reject);
    srv.listen(port, "127.0.0.1", () => resolve(srv));
  });
}

async function open(opts) {
  const o = Object.assign({ book: "ivanchuk", device: "ipad", dark: true, fresh: false, timeout: 3600000 }, opts || {});
  const pdf = BOOKS[o.book] || o.book;
  const site = execFileSync("python3", [path.join(__dirname, "app_site.py")]).toString().trim();
  const srv = await serve(site, portOf(o.book + "-" + o.device));
  const url = "http://127.0.0.1:" + srv.address().port + "/";
  const profile = path.join(ROOT, "output", "audit", "profiles", path.basename(site), o.book + "-" + o.device);
  if (o.fresh) fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });
  const shots = path.join(ROOT, "output", "audit", "app", o.book);
  fs.mkdirSync(shots, { recursive: true });
  const ctx = await chromium.launchPersistentContext(profile, Object.assign({
    executablePath: "/opt/pw-browsers/chromium", colorScheme: o.dark ? "dark" : "light" }, DEVICES[o.device]));
  const page = ctx.pages()[0] || await ctx.newPage();
  const app = { page, ctx, url, errors: [], timings: {} };
  page.on("console", (m) => {
    if (m.type() === "error" && !/status of 404/.test(m.text())) app.errors.push(m.text());
  });
  page.on("pageerror", (e) => app.errors.push(String(e)));
  app.frame = async () => (await page.$("#view")).contentFrame();
  app.inFrame = async (fn, arg) => {
    for (let i = 0; ; i++) {
      try { return await (await app.frame()).evaluate(fn, arg); }
      catch (e) { if (i > 40) throw e; await page.waitForTimeout(250); }
    }
  };
  app.waitFrame = async (fn, arg, timeout) => {
    const t0 = Date.now();
    for (;;) {
      let v = null;
      try { v = await (await app.frame()).evaluate(fn, arg); } catch (e) { v = null; }
      if (v) return v;
      if (Date.now() - t0 > (timeout || 120000)) throw new Error("timed out in the reader: " + fn.toString().slice(0, 200));
      await page.waitForTimeout(100);
    }
  };
  app.tapIn = async (sel) => {
    const el = await (await app.frame()).$(sel);
    if (!el) throw new Error("nothing at " + sel);
    await el.scrollIntoViewIfNeeded();
    if (DEVICES[o.device].hasTouch) await el.tap(); else await el.click();
  };
  // Show reading on or off (the app remembers it between opens, so a bare tap may turn it off)
  app.showReading = async (on) => {
    const pressed = await app.inFrame(() => {
      const b = [document.getElementById("showread"), document.getElementById("mread")]
        .find((x) => x && x.getBoundingClientRect().width > 0);
      return b ? b.getAttribute("aria-pressed") === "true" : null; });
    if (pressed !== (on !== false)) {
      const vis = await app.inFrame(() => document.getElementById("showread").getBoundingClientRect().width > 0);
      await app.tapIn(vis ? "#showread" : "#mread");
      await page.waitForTimeout(300);
    }
  };
  app.shot = async (name) => { const p = path.join(shots, name + ".png"); await page.screenshot({ path: p }); return p; };
  app.gotoPage = async (p) => {
    await app.inFrame((p) => { location.hash = "#page=" + p; }, p);
    await app.waitFrame((p) => window.READER && window.readerState && window.readerState.page === p, p, 600000);
    await page.waitForTimeout(800);
  };
  app.markSel = (key) => app.inFrame((key) => {
    const i = READER.pages[readerState.page].marks.findIndex((m) => m.key === key);
    return i >= 0 ? "#ov .mark[data-mark='" + i + "']" : null; }, key);
  app.tapMark = async (key) => {
    const sel = await app.markSel(key);
    if (!sel) throw new Error("no box " + key + " on the page shown");
    await app.tapIn(sel);
  };
  app.marks = () => app.inFrame(() => READER.pages[readerState.page].marks.map((m, i) => ({
    i, key: m.key, raw: m.raw, status: m.status, move: m.node && READER.nodes[m.node] ? READER.nodes[m.node].san : null })));
  app.play = async (from, to) => {
    for (const sq of [from, to]) {
      const xy = await app.inFrame((sq) => {
        const svg = [document.querySelector("#minibox svg.board"), document.querySelector("#board svg.board")]
          .find((s) => s && s.getBoundingClientRect().width > 0);
        const r = svg.getBoundingClientRect(), flip = svg.dataset.flip === "1";
        const f = "abcdefgh".indexOf(sq[0]), row = 8 - parseInt(sq[1], 10);
        const c = flip ? 7 - f : f, rr = flip ? 7 - row : row, k = r.width / 375;
        return [r.left + (14 + (c + 0.5) * 45) * k, r.top + (1 + (rr + 0.5) * 45) * k];
      }, sq);
      const box = await (await page.$("#view")).boundingBox();
      if (DEVICES[o.device].hasTouch) await page.touchscreen.tap(box.x + xy[0], box.y + xy[1]);
      else await page.mouse.click(box.x + xy[0], box.y + xy[1]);
      await page.waitForTimeout(150);
    }
  };
  app.sheet = () => app.inFrame(() => { const f = document.getElementById("fix");
    return !f || f.hidden ? null : { note: (f.querySelector(".thr") || { innerText: "" }).innerText.trim(),
      line: (f.querySelector(".thl") || f).innerText.trim(),
      msg: (f.querySelector("#fixmsg") || { innerText: "" }).innerText.trim(),
      buttons: [...f.querySelectorAll("button")].map((b) => (b.id ? "#" + b.id + " " : "") + b.textContent.trim()) }; });
  app.fix = () => app.inFrame(() => JSON.parse(window.correctionsText()));
  app.lineFrom = (key) => app.inFrame((k) => {
    const D = READER, id = Object.keys(D.nodes).find((x) => D.nodes[x].key === k);
    if (!id) return null;
    const out = [];
    for (let cur = id; cur;) {
      const n = D.nodes[cur];
      out.push(n.number + (n.black ? "..." : ".") + (n.san || "?") + "[p" + n.page + " " + n.status +
               (n.corrected ? " " + n.corrected : "") + "]");
      cur = (n.children || []).find((x) => D.nodes[x] && D.nodes[x].main === n.main && D.nodes[x].line === n.line);
    }
    return out.join(" ");
  }, key);
  app.close = async () => { await ctx.close(); srv.close(); };

  const t0 = Date.now();
  await page.goto(url);
  // the app either shows the library (Ready) or reopens the book last read by itself
  await page.waitForFunction(() => /Ready/.test((document.getElementById("status") || {}).textContent || "") ||
    ["read", "opened"].includes(document.body.dataset.book), null, { timeout: 600000 });
  let how = "reopened by the app";
  if (!["read", "opened"].includes(await page.evaluate(() => document.body.dataset.book))) {
    const stored = await page.$("#books li.book button.open");
    if (stored && !o.fresh) { await stored.click(); how = "from the library"; }
    else { await page.setInputFiles("#file", pdf); how = "read in the app"; }
  }
  await page.waitForSelector("#view", { state: "visible", timeout: o.timeout });
  await page.waitForFunction(() => ["read", "opened"].includes(document.body.dataset.book), null, { timeout: o.timeout });
  await app.waitFrame(() => window.READER && window.readerState, null, 600000);
  app.timings.how = how;
  app.timings.open_seconds = (Date.now() - t0) / 1000;
  return app;
}

module.exports = { open, BOOKS, DEVICES };
