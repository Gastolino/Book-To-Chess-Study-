// End-to-end test of the book reader in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/reader_e2e.js READER_DIR PAGE SCREENS_DIR
//
// Opens READER_DIR/index.html, opens the preview of a diagram, follows the
// link of PDF page PAGE to its chapter reader, clicks a green move box and
// checks that window.readerState shows that move's position, steps with the
// arrow keys (also right after choosing a line in the dropdown, and with no
// move chosen), clicks a diagram and leaves it out of the selection, checks
// that the contents page shows that change, checks the phone layout at
// 390x844 (no sideways scroll, no jump of the window when a box is tapped,
// the small board), checks that no console errors occur, and saves
// screenshots into SCREENS_DIR. Prints one JSON object with the results; the
// exit code is 1 when a check fails.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const [dir, pageArg, screens] = process.argv.slice(2);
const PAGE = parseInt(pageArg || "250", 10);
const out = { ok: false, checks: [], errors: [], screenshots: [] };

function check(name, cond, detail) {
  out.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed: " + name + (detail ? " (" + JSON.stringify(detail) + ")" : ""));
}

// the move that continues the line from a node (main moves follow main moves)
const CONT = `(id) => {
  const N = window.READER.nodes, n = N[id];
  if (n.main) { for (const c of n.children) if (N[c].main) return c; return null; }
  return n.children.length ? n.children[0] : null;
}`;

(async () => {
  fs.mkdirSync(screens, { recursive: true });
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.on("console", (m) => { if (m.type() === "error") out.errors.push(m.text()); });
    page.on("pageerror", (e) => out.errors.push(String(e)));
    const index = "file://" + path.resolve(dir, "index.html");
    await page.goto(index);
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForSelector(".pg[data-page='" + PAGE + "']");
    await page.screenshot({ path: path.join(screens, "index_1280.png") });
    out.screenshots.push("index_1280.png");

    // the preview of a diagram on the contents page
    const frame = await page.$(".pg[data-page='" + PAGE + "'] .thumb .d");
    check("page " + PAGE + " shows a diagram frame on the contents page", frame);
    await frame.click();
    const box = await page.evaluate(() => {
      const lb = document.getElementById("lightbox");
      const img = lb.querySelector("img");
      return { hidden: lb.hidden, img: !!img, width: img ? img.getBoundingClientRect().width : 0,
               use: !!lb.querySelector("#lbuse") };
    });
    check("a click on a diagram frame opens a larger preview", !box.hidden && box.img && box.width >= 150, box);
    check("the preview offers to use or leave out the diagram", box.use);
    await page.screenshot({ path: path.join(screens, "index_preview_1280.png") });
    out.screenshots.push("index_preview_1280.png");
    await page.keyboard.press("Escape");
    const sel0 = await page.evaluate(() => window.selectionText());
    check("opening the preview changes nothing", JSON.parse(sel0).diagrams.exclude.length > 0);

    const link = await page.$(".pg[data-page='" + PAGE + "'] a");
    check("index links page " + PAGE + " to a chapter reader", link);
    const href = await link.getAttribute("href");
    out.chapter = href.split("#")[0];
    await Promise.all([page.waitForURL(/ch\d\d\.html/), link.click()]);
    await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
    let st = await page.evaluate(() => window.readerState);
    check("reader opens at page " + PAGE, st.page === PAGE, st);

    // with no move chosen, the right arrow starts a line on this page
    await page.keyboard.press("ArrowRight");
    st = await page.evaluate(() => window.readerState);
    check("ArrowRight with no move chosen stays on the page", st.page === PAGE && st.nodeId, st);

    // a green move box whose move has a following move with a position
    const target = await page.evaluate((contSrc) => {
      const cont = eval(contSrc);
      for (const el of document.querySelectorAll("#ov .mark.st-ok[data-node]")) {
        const n = window.READER.nodes[el.dataset.node];
        const c = n && n.fen ? cont(el.dataset.node) : null;
        if (c && window.READER.nodes[c].fen) return el.dataset.node;
      }
      return null;
    }, CONT);
    check("page " + PAGE + " has a green move box", target);
    const before = st.fen;
    await page.click("#ov .mark[data-node='" + target + "']");
    st = await page.evaluate(() => window.readerState);
    const nodeFen = await page.evaluate((id) => window.READER.nodes[id].fen, target);
    check("clicking the box selects its move", st.nodeId === target, st);
    check("readerState.fen changed", st.fen !== before, { before, after: st.fen });
    check("readerState.fen equals the move's FEN", st.fen === nodeFen, { fen: st.fen, nodeFen });
    const boardPieces = await page.$$eval("#board use", (els) => els.length);
    check("the board shows pieces", boardPieces > 0, boardPieces);
    const treeCur = await page.$eval("#tree .mv.cur", (el) => el.dataset.node).catch(() => null);
    check("the move list highlights the move", treeCur === target, treeCur);
    const markCur = await page.$$eval("#ov .mark.current", (els) => els.map((e) => e.dataset.node));
    check("the page highlights the move's box", markCur.includes(target), markCur);
    out.clicked = { node: target, fen: st.fen };

    await page.keyboard.press("ArrowRight");
    const st2 = await page.evaluate(() => window.readerState);
    const next = await page.evaluate(([id, contSrc]) => {
      const c = eval(contSrc)(id);
      return { id: c, fen: window.READER.nodes[c].fen };
    }, [target, CONT]);
    check("ArrowRight advances to the next move", st2.nodeId === next.id, { st2, next });
    check("ArrowRight updates the FEN", st2.fen === next.fen && st2.fen !== st.fen, st2);
    await page.keyboard.press("ArrowLeft");
    const st3 = await page.evaluate(() => window.readerState);
    check("ArrowLeft goes back", st3.nodeId === target, st3);
    out.advanced = { node: st2.nodeId, fen: st2.fen };

    // the dropdown gives the focus back, so the arrow keys step through moves
    const lineId = await page.evaluate(() => window.READER.nodes[window.readerState.nodeId].line);
    await page.selectOption("#linesel", lineId);
    const root = await page.evaluate(() => window.readerState.nodeId);
    await page.keyboard.press("ArrowRight");
    const st4 = await page.evaluate(() => ({ s: window.readerState,
      line: window.READER.nodes[window.readerState.nodeId].line }));
    check("ArrowRight after choosing a line steps through that line",
          st4.line === lineId && st4.s.nodeId !== root, st4);

    // a diagram frame, and leaving the diagram out
    const diag = await page.$("#ov .diag");
    check("page " + PAGE + " has a diagram frame", diag);
    const did = await diag.getAttribute("data-diagram");
    await diag.click();
    const panel = await page.evaluate(() => {
      const p = document.getElementById("dpanel");
      return { hidden: p.hidden, text: p.innerText, canvas: !!p.querySelector("canvas"),
               use: !!p.querySelector("#usediag") };
    });
    check("clicking a diagram opens the diagram panel", !panel.hidden && panel.canvas, panel.hidden);
    check("the panel names the diagram", /Diagram|Unnumbered diagram/.test(panel.text), panel.text.slice(0, 80));
    check("the panel says that board reading has not run", /Stage 3/.test(panel.text));
    check("the panel offers to use or leave out the diagram", panel.use);
    out.diagram = did;
    await page.screenshot({ path: path.join(screens, "reader_1280.png") });
    out.screenshots.push("reader_1280.png");
    await page.uncheck("#usediag");
    const framed = await page.$eval("#ov .diag[data-diagram='" + did + "']", (el) => el.classList.contains("excluded"));
    check("leaving the diagram out greys its frame", framed);

    // the phone layout
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(200);
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    check("no sideways scroll at 390 px", widths[0] <= widths[1], widths);
    const mark = await page.$("#ov .mark[data-node='" + target + "']");
    await mark.scrollIntoViewIfNeeded();
    const y0 = await page.evaluate(() => window.scrollY);
    await mark.click();
    const y1 = await page.evaluate(() => window.scrollY);
    check("tapping a box does not move the window", Math.abs(y1 - y0) < 2, { y0, y1 });
    const mini = await page.evaluate(() => {
      const m = document.getElementById("mini");
      const r = m.getBoundingClientRect();
      return { on: m.classList.contains("on"), pieces: m.querySelectorAll("use").length, w: r.width };
    });
    check("the small board shows the position at 390 px", mini.on && mini.pieces > 0, mini);
    await page.screenshot({ path: path.join(screens, "reader_390.png") });
    out.screenshots.push("reader_390.png");
    await page.click("#mfwd");
    await page.screenshot({ path: path.join(screens, "reader_390_board.png") });
    out.screenshots.push("reader_390_board.png");

    // back on the contents page, the diagram is left out there as well
    await page.goto(index);
    await page.waitForSelector(".pg");
    const iw = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    check("index has no sideways scroll at 390 px", iw[0] <= iw[1], iw);
    await page.screenshot({ path: path.join(screens, "index_390.png") });
    out.screenshots.push("index_390.png");
    const shared = await page.evaluate((id) => ({ box: document.querySelector(".dcb[data-id='" + id + "']").checked,
      sel: JSON.parse(window.selectionText()) }), did);
    check("the contents page shows the change made in the reader",
          !shared.box && shared.sel.diagrams.exclude.includes(did), shared.box);

    // unticking a page survives a visit to the reader and back
    await page.setViewportSize({ width: 1280, height: 900 });
    const cb = await page.$(".pcb[data-page='" + PAGE + "']");
    await cb.click();
    let selText = await page.evaluate(() => window.selectionText());
    let sel = JSON.parse(selText);
    check("unticking a page excludes it in the selection",
          sel.pages.exclude.some(([a, b]) => a <= PAGE && PAGE <= b), sel.pages);
    await page.goto("file://" + path.resolve(dir, out.chapter) + "#page=" + PAGE);
    await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
    const offShown = await page.evaluate(() => !document.getElementById("usepage").checked &&
      document.getElementById("offpage").classList.contains("on"));
    check("the reader marks the page as left out", offShown);
    await page.goBack();
    await page.waitForSelector(".pg");
    selText = await page.evaluate(() => window.selectionText());
    sel = JSON.parse(selText);
    check("the change survives a visit to the reader",
          sel.pages.exclude.some(([a, b]) => a <= PAGE && PAGE <= b), sel.pages);
    out.selection = selText;
    await page.click("#resetbtn");
    const reset = JSON.parse(await page.evaluate(() => window.selectionText()));
    check("Undo my changes restores the selection of the run",
          !reset.pages.exclude.some(([a, b]) => a <= PAGE && PAGE <= b) && !reset.diagrams.exclude.includes(did));

    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (e) {
    out.failure = String(e && e.message ? e.message : e);
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
