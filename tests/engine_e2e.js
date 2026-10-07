// End-to-end test of the analysis with Stockfish, in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/engine_e2e.js READER_DIR CHAPTER_HTML SCREENS_DIR
//
// Serves READER_DIR (a chapter reader of the generated test book with the
// engine files in engine/ beside it; tests/test_reader.py builds it, with the
// diagram on page 5 read as a mate in one for White and the first exercise
// diagram on page 6 as a position where White is mated next move) over HTTP, since a page
// opened as a file cannot start a worker in Chromium. On a desktop: the
// processor icon loads the engine from the local files; the mate position
// shows M1 with the mating move as the top line; the eval bar is full for
// White's mate, empty for Black's and near the middle at the start; the
// settings persist across a reload; stepping through moves restarts the
// search on the shown position; a tap on a suggestion opens the board-move
// chooser; turning analysis off ends the worker; offline, and with the
// engine's files out of reach, the engine still loads from the browser's
// storage. On an iPhone 13 and on an iPad held sideways: the icon in the bar
// and in the panel, the eval in the bar, the eval bar beside the board at the
// foot of the phone's window, no sideways scroll. Screenshots of
// the board with the eval bar and the analysis, and of the settings, in the
// light and dark schemes. Prints one JSON object; the exit code is 1 when a
// check fails.
const { chromium, devices } = require("playwright");
const http = require("http");
const path = require("path");
const fs = require("fs");

const [readerDir, chapterFile, screens] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], screenshots: [], timings: {} };
function check(name, cond, detail) {
  out.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed: " + name + (detail !== undefined ? " (" + JSON.stringify(detail).slice(0, 500) + ")" : ""));
}
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".wasm": "application/wasm",
  ".txt": "text/plain; charset=utf-8" };
function serve(dir) {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const f = path.join(dir, decodeURIComponent(req.url.split("?")[0].split("#")[0]));
      if (!f.startsWith(dir) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.statusCode = 404; res.end(); return; }
      res.setHeader("content-type", TYPES[path.extname(f)] || "application/octet-stream");
      fs.createReadStream(f).pipe(res);
    });
    srv.listen(0, "127.0.0.1", () => resolve([srv, "http://127.0.0.1:" + srv.address().port + "/"]));
  });
}

(async () => {
  const [srv, base] = await serve(path.resolve(readerDir));
  const url = base + path.basename(chapterFile);
  const browser = await chromium.launch();
  fs.mkdirSync(screens, { recursive: true });
  const watch = (page) => {
    // the engine's files are blocked on purpose in two steps below
    page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource: net::ERR_FAILED/.test(m.text())) out.errors.push(m.text()); });
    page.on("pageerror", (e) => out.errors.push(String(e)));
  };
  const shot = async (page, name) => {
    const p = path.join(screens, name);
    await page.screenshot({ path: p });
    out.screenshots.push(p);
  };
  const both = async (page, name) => {
    await shot(page, name + "_light.png");
    await page.emulateMedia({ colorScheme: "dark" });
    await page.waitForTimeout(150);
    await shot(page, name + "_dark.png");
    await page.emulateMedia({ colorScheme: "light" });
  };
  const state = (page) => page.evaluate(() => window.engineState());
  const view = (page) => page.evaluate(() => ({
    status: document.getElementById("evstatus").textContent,
    rows: [...document.querySelectorAll("#evlines .evline")].map((b) => ({ score: b.querySelector(".esc").textContent,
      first: b.querySelector(".efirst").textContent, uci: b.dataset.uci, pv: b.querySelector(".epv").textContent })),
    num: document.querySelector("#evalbar .enum").textContent,
    share: parseFloat(document.querySelector("#evalbar .ebar i").style.height),
    barShown: !document.getElementById("evalbar").hidden && getComputedStyle(document.getElementById("evalbar")).display !== "none",
    secShown: !document.getElementById("evalsec").hidden,
    pressed: document.getElementById("bcpu").getAttribute("aria-pressed"),
    mnum: document.getElementById("mevalnum").textContent,
    fen: window.readerState.fen, sw: document.documentElement.scrollWidth, w: window.innerWidth,
  }));
  const settled = (page, timeout) => page.waitForFunction(() => { const s = window.engineState();
    return s.failed || (s.ready && s.done && s.fen && s.fen === window.readerState.fen); }, null, { timeout: timeout || 60000 });
  const lines = (page) => page.evaluate(() => {
    const L = window.READER.lines;
    const by = (f) => Object.keys(L).find((k) => f(L[k]));
    return { mateW: by((l) => l.diagram === "p5-1"), mateB: by((l) => l.diagram === "p6-1"),
      game: by((l) => /Smith/.test(l.title)) };
  });
  const goLine = async (page, id) => {
    await page.evaluate((id) => { location.hash = "#line=" + id; }, id);
    await page.waitForFunction((id) => window.readerState.nodeId === window.READER.lines[id].root, id);
  };
  try {
    // ---------------------------------------------------------------- desktop
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    watch(page);
    await page.goto(url);
    await page.waitForFunction(() => window.READER && window.readerState && window.engineState);
    await page.evaluate(() => { localStorage.clear(); indexedDB.deleteDatabase("chessbook-engine"); });
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState && window.engineState);
    const I = await lines(page);
    await goLine(page, I.mateW);
    let v = await view(page);
    check("analysis is off until the icon is pressed", !v.barShown && !v.secShown && v.pressed === "false", v);
    let t0 = Date.now();
    await page.click("#bcpu");
    await page.waitForFunction(() => window.engineState().ready || window.engineState().failed, null, { timeout: 60000 });
    let s = await state(page);
    check("the engine loads from the local files", s.ready && !s.failed && s.from === "network" && /Stockfish/.test(s.name), s);
    out.timings["engine load, first time (ms)"] = s.loadMs;
    await settled(page);
    s = await state(page); v = await view(page);
    out.timings["mate in one, to depth " + s.depth + " (ms)"] = Date.now() - t0;
    check("the mate in one shows M1 as the top line", v.rows.length >= 1 && v.rows[0].score === "M1" && v.rows[0].first === "1.Ra8#" &&
      v.rows[0].uci === "a1a8", v.rows);
    check("the bar is full for White's mate", v.barShown && v.share === 100 && v.num === "M1", v);
    check("the status says the depth reached", /^Depth \d+ reached\.$/.test(v.status), v.status);
    check("the number of lines follows the settings", v.rows.length === s.settings.lines, { rows: v.rows.length, lines: s.settings.lines });
    check("the icon is pressed and the section shows", v.pressed === "true" && v.secShown, v);
    await both(page, "engine_board_1280");

    // Black's mate: the sign turns and the bar empties
    await goLine(page, I.mateB);
    await settled(page);
    v = await view(page);
    check("Black's mate shows −M1 and an empty bar", v.rows[0].score === "−M1" && v.share === 0 && v.num === "−M1" &&
      v.rows[0].first === "1.Rb1", v);
    await goLine(page, I.game);
    await settled(page);
    v = await view(page);
    check("the start of a game sits near the middle of the bar", v.share > 30 && v.share < 70 && /^[+−]\d\.\d$/.test(v.num), v);
    check("the lines carry move numbers from the shown position", v.rows.every((r) => /^1\.[a-hNBRQKO]/.test(r.first)), v.rows);

    // stepping through moves restarts the search on the shown position
    const fen0 = v.fen;
    await page.keyboard.press("ArrowRight");
    await page.waitForFunction(() => window.engineState().fen === window.readerState.fen && window.readerState.fen, null, { timeout: 20000 });
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await settled(page);
    s = await state(page); v = await view(page);
    check("stepping moves restarts the search on the shown position", s.fen === v.fen && v.fen !== fen0 && s.done, { fen: s.fen, shown: v.fen });
    check("after Black's move the lines start with a black move", v.rows.every((r) => /^\d+…/.test(r.first)), v.rows);
    check("the eval is from White's view after a black move", /^[+−]/.test(v.num), v.num);

    // Deeper lifts the limit for this position
    const depth0 = s.depth;
    await page.click("#evdeeper");
    await page.waitForFunction((d) => { const s = window.engineState(); return s.done && s.depth > d; }, depth0, { timeout: 90000 });
    s = await state(page);
    check("Deeper searches further", s.depth > depth0 && s.deeper === 1, { before: depth0, after: s.depth });

    // a suggestion that is not the book's move opens the board-move chooser
    await goLine(page, I.game);
    await settled(page);
    v = await view(page);
    const bookNext = await page.evaluate(() => { const r = window.READER.lines[window.readerState.nodeId ? window.READER.nodes[window.readerState.nodeId].line : null];
      const root = window.READER.nodes[r.root]; return root.children.map((c) => window.READER.nodes[c].uci); });
    const other = v.rows.find((r) => bookNext.indexOf(r.uci) < 0);
    check("a suggested move other than the book's is listed", !!other, { rows: v.rows, bookNext });
    await page.click("#evlines .evline[data-uci='" + other.uci + "']");
    await page.waitForSelector("#fix:not([hidden])");
    let fix = await page.evaluate(() => document.getElementById("fix").innerText);
    check("a tap on a suggestion opens the board-move chooser", /Your move 1\./.test(fix) && /Add a new variation/.test(fix) && /Cancel/.test(fix), fix);
    check("the chooser's move is the suggestion", fix.indexOf(other.first.replace(/^1\./, "")) > 0, { fix, other });
    await page.click("#bmcancel");
    const book = v.rows.find((r) => bookNext.indexOf(r.uci) >= 0);
    if (book) {
      await page.click("#evlines .evline[data-uci='" + book.uci + "']");
      await page.waitForFunction((u) => { const n = window.READER.nodes[window.readerState.nodeId]; return n && n.uci === u; }, book.uci);
      check("a tap on the book's move steps to it", await page.evaluate(() => document.getElementById("fix").hidden));
      await goLine(page, I.game);
    }

    // the settings: the gear, a change, and a reload
    await page.click("#bgear");
    await page.waitForSelector("#evset:not([hidden])");
    const foot = await page.evaluate(() => document.querySelector("#evset .evfoot").innerText);
    check("the settings name the engine and the licence", /Stockfish 19/.test(foot) && /GNU General Public License, version 3/.test(foot) &&
      /sends nothing anywhere/.test(foot), foot);
    const style = await page.evaluate(() => { const b = document.querySelector("#evset button[data-set]"), cs = getComputedStyle(b);
      const r = document.querySelector("#evlines .evline"), rs = getComputedStyle(r), bar = getComputedStyle(document.querySelector("#evalbar .ebar"));
      return { bg: cs.backgroundColor, border: cs.borderTopWidth, radius: cs.borderTopLeftRadius, shadow: cs.boxShadow, mono: rs.fontFamily,
        barBorder: bar.borderTopWidth, barShadow: bar.boxShadow, barRadius: bar.borderTopLeftRadius }; });
    check("the choices are plain text buttons and the rows notation type", /^(rgba\(0, 0, 0, 0\)|transparent)$/.test(style.bg) &&
      style.border === "0px" && style.shadow === "none" && style.radius === "0px" && /Geist Mono/.test(style.mono), style);
    check("the eval bar is a hairline with no shadow or rounding", style.barBorder === "1px" && style.barShadow === "none" && style.barRadius === "0px", style);
    await both(page, "engine_settings_1280");
    await page.click("#evset button[data-set='lines'][data-value='2']");
    await page.click("#evset button[data-set='limit'][data-value='t1']");
    await page.click("#evset button[data-set='arrow'][data-value='true']");
    await settled(page);
    v = await view(page); s = await state(page);
    check("a change of the lines applies at once", v.rows.length === 2 && s.settings.lines === 2 && s.settings.limit === "t1", { rows: v.rows.length, s: s.settings });
    check("the arrow for the top suggestion is drawn on the board", await page.evaluate(() => !!document.querySelector("#board svg.board .eva") &&
      !!document.querySelector("#board svg.board .evh")));
    await shot(page, "engine_arrow_1280_light.png");
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState && window.engineState);
    s = await state(page);
    check("the settings persist across a reload", s.settings.lines === 2 && s.settings.limit === "t1" && s.settings.arrow === true && !s.on, s.settings);
    check("the engine is not loaded until analysis is turned on", !s.worker && !s.loading, s);

    // from the browser's storage, the second time, and the time it takes
    t0 = Date.now();
    await page.click("#bcpu");
    await page.waitForFunction(() => window.engineState().ready || window.engineState().failed, null, { timeout: 60000 });
    s = await state(page);
    check("the second load comes from the browser's storage", s.ready && s.from === "storage", s);
    out.timings["engine load, from storage (ms)"] = s.loadMs;
    await settled(page);
    s = await state(page);
    check("a time limit stops the search", s.done && s.settings.limit === "t1", s);

    // what the engine found is kept: a position shown again shows it at once, without a search,
    // and so it does after the page loads again (the browser's IndexedDB)
    await goLine(page, I.game);
    await settled(page);
    await goLine(page, I.mateB);
    await settled(page);
    t0 = Date.now();
    await goLine(page, I.game);
    await page.waitForFunction(() => { const s = window.engineState(); return s.cached && s.done && s.fen === window.readerState.fen; },
      null, { timeout: 5000 });
    out.timings["a kept analysis shows after (ms)"] = Date.now() - t0;
    s = await state(page); v = await view(page);
    check("a position analysed before shows its kept result at once, without searching",
      s.cached && !s.searching && v.rows.length === 2 && /kept from an earlier analysis/.test(v.status), { s, v });
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState && window.engineState);
    await page.click("#bcpu");
    await goLine(page, I.game);
    await page.waitForFunction(() => { const s = window.engineState(); return s.cached && s.lines.length === 2; }, null, { timeout: 20000 });
    check("the kept analysis survives a reload of the page", true);
    const kept = await page.evaluate(() => new Promise((res) => {
      const q = indexedDB.open("chessbook-analysis");
      q.onsuccess = () => { const c = q.result.transaction("positions").objectStore("positions").count(); c.onsuccess = () => res(c.result); };
      q.onerror = () => res(-1);
    }));
    check("the analysis cache is kept in the browser's IndexedDB", kept >= 2, kept);
    // Deeper always searches
    const d0 = (await state(page)).depth;
    await settled(page, 90000);
    await page.click("#evdeeper");
    await page.waitForFunction((d) => { const s = window.engineState(); return s.done && !s.cached && s.depth > d; }, d0, { timeout: 90000 });
    check("Deeper searches beyond the kept result", true);

    // turning analysis off stops it and ends the worker
    await page.click("#bcpu");
    s = await state(page); v = await view(page);
    check("turning analysis off ends the worker and hides the bar", !s.on && !s.worker && !s.searching && !v.barShown && !v.secShown &&
      v.pressed === "false" && v.num === "", { s, v });
    check("no arrow stays on the board", await page.evaluate(() => !document.querySelector("#board svg.board .eva")));

    // offline: the engine still loads, from the browser's storage
    await ctx.setOffline(true);
    await page.click("#bcpu");
    await page.waitForFunction(() => window.engineState().ready || window.engineState().failed, null, { timeout: 60000 });
    await settled(page);
    s = await state(page); v = await view(page);
    check("offline, the engine loads from the browser's storage and runs", s.ready && s.from === "storage" && s.done && v.num !== "", { s, v });
    await page.click("#bcpu");
    await ctx.setOffline(false);
    // the engine's files out of reach (a server that no longer serves them): the stored copy serves
    await page.route("**/engine/**", (route) => route.abort());
    await page.reload();
    await page.waitForFunction(() => window.READER && window.readerState && window.engineState);
    await page.click("#bcpu");
    await page.waitForFunction(() => window.engineState().ready || window.engineState().failed, null, { timeout: 60000 });
    s = await state(page);
    check("with the files out of reach the stored copy serves after a reload", s.ready && s.from === "storage", s);
    await page.unroute("**/engine/**");

    // a fresh profile with the files out of reach: the status says so in one line
    const ctx2 = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const p2 = await ctx2.newPage();
    watch(p2);
    await p2.route("**/engine/**", (route) => route.abort());
    await p2.goto(url);
    await p2.waitForFunction(() => window.READER && window.readerState && window.engineState);
    await p2.click("#bcpu");
    await p2.waitForFunction(() => window.engineState().failed, null, { timeout: 60000 });
    const said = await p2.evaluate(() => document.getElementById("evstatus").textContent);
    check("when the engine cannot be loaded the status says so in one line", /^The engine could not be loaded: .+\.$/.test(said) && said.split("\n").length === 1, said);
    await ctx2.close();

    // the tab hidden: the search pauses
    await page.evaluate(() => { location.hash = "#line=" + Object.keys(window.READER.lines)[0]; });
    await page.waitForTimeout(100);
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.waitForFunction(() => !window.engineState().searching, null, { timeout: 20000 });
    const paused = await page.evaluate(() => document.getElementById("evstatus").textContent);
    check("nothing runs while the page is hidden", /Paused while the page is hidden/.test(paused), paused);
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await settled(page);
    check("the search starts again when the page shows", (await state(page)).done);
    await ctx.close();

    // ---------------------------------------------------------------- iPhone 13
    const phone = await browser.newContext({ ...devices["iPhone 13"] });
    const pp = await phone.newPage();
    watch(pp);
    await pp.goto(url + "#line=" + I.mateW);
    await pp.waitForFunction(() => window.READER && window.readerState && window.engineState);
    await pp.evaluate(() => localStorage.clear());
    await pp.tap("#mcpu");
    await settled(pp);
    v = await view(pp);
    check("on a phone the icon in the bar turns analysis on", v.pressed === "true" && v.rows[0].score === "M1" && v.mnum === "M1", v);
    check("no sideways scroll at 390 px", v.sw <= v.w, v);
    const eb = await pp.evaluate(() => {
      const e = document.getElementById("evalbar").getBoundingClientRect(), b = document.getElementById("boardblock").getBoundingClientRect();
      const bar = document.getElementById("mbar").getBoundingClientRect(), w = document.querySelector("#board svg").getBoundingClientRect();
      return { e: [e.left, e.top, e.width, e.height], b: [b.left, b.top, b.right, b.bottom], barTop: bar.top, board: [w.left, w.right],
               stick: document.body.classList.contains("stickboard"), hidden: document.getElementById("evalbar").hidden };
    });
    check("on a phone the eval bar stands beside the board at the foot of the window",
          eb.stick && !eb.hidden && eb.e[2] > 0 && eb.e[1] >= eb.b[1] && eb.e[1] + eb.e[3] <= eb.b[3] + 1 &&
          eb.e[0] + eb.e[2] <= eb.board[0] + 1 && Math.abs(eb.b[3] - eb.barTop) <= 1.5, eb);
    await pp.tap("#mmoves");
    await pp.waitForTimeout(300);
    await both(pp, "engine_board_390");
    await pp.tap("#bgear");
    await pp.waitForSelector("#evset:not([hidden])");
    await pp.evaluate(() => document.getElementById("evset").scrollIntoView({ block: "center" }));
    await pp.waitForTimeout(200);
    v = await view(pp);
    check("no sideways scroll with the settings open", v.sw <= v.w, v);
    await both(pp, "engine_settings_390");
    await pp.tap("#bgear");
    // a tap on a suggestion opens the chooser as the sheet above the bar
    await pp.evaluate((id) => { location.hash = "#line=" + id; }, I.game);
    await settled(pp);
    v = await view(pp);
    const bookNextP = await pp.evaluate((id) => { const root = window.READER.nodes[window.READER.lines[id].root];
      return root.children.map((c) => window.READER.nodes[c].uci); }, I.game);
    const otherP = v.rows.find((r) => bookNextP.indexOf(r.uci) < 0);
    check("on a phone a suggestion other than the book's is listed", !!otherP, { rows: v.rows, bookNextP });
    await pp.tap("#evlines .evline[data-uci='" + otherP.uci + "']");
    await pp.waitForSelector("#fix:not([hidden])");
    fix = await pp.evaluate(() => document.getElementById("fix").innerText);
    check("on a phone a tap on a suggestion opens the chooser", /Your move/.test(fix) && /Add a new variation/.test(fix), fix);
    await pp.tap("#bmcancel");
    await phone.close();

    // ---------------------------------------------------------------- iPad held sideways
    const pad = await browser.newContext({ viewport: { width: 1180, height: 820 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    const tp = await pad.newPage();
    watch(tp);
    await tp.goto(url + "#line=" + I.mateW);
    await tp.waitForFunction(() => window.READER && window.readerState && window.engineState);
    await tp.evaluate(() => localStorage.clear());
    await tp.tap("#bcpu");
    await settled(tp);
    v = await view(tp);
    check("on a tablet the icon in the panel turns analysis on", v.pressed === "true" && v.rows[0].score === "M1" && v.barShown, v);
    check("no sideways scroll on the tablet", v.sw <= v.w, v);
    await both(tp, "engine_board_1180");
    await tp.tap("#bgear");
    await tp.waitForSelector("#evset:not([hidden])");
    await both(tp, "engine_settings_1180");
    await pad.close();

    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (err) {
    out.failure = String(err && err.stack ? err.stack : err);
  }
  await browser.close();
  srv.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
