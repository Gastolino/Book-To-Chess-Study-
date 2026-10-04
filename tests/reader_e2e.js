// End-to-end test of the book reader in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/reader_e2e.js READER_DIR PAGE SCREENS_DIR
//
// Opens READER_DIR/index.html, opens the chapter holding PDF page PAGE,
// switches a diagram off and on again with a click on its outline, follows
// the link of page PAGE to its chapter reader and checks that the panel shows
// a board and a line, clicks a green move box and checks that
// window.readerState shows that move's position, steps with the arrow keys
// (also right after choosing a line under "On this page", with no move
// chosen, along a long line whose current move must stay in view, and from a
// main move whose game goes on only in variations), checks that move boxes
// stay hidden until hover, that "Show reading" outlines only the boxes that
// need attention without moving the page and keeps the focus outline, that
// hover and the current move look different in the move list, clicks a
// diagram and leaves it out of the selection (also on a page that is left
// out), checks that a box keeps its page, that the contents page shows the
// change and keeps its ticks after the Back button, checks the phone layout
// at 390x844 (no sideways scroll, a board as wide as the page, no jump of the
// window when a box is tapped, the small board, which steps aside when the
// panel is in view), checks the label of a page without a printed number,
// checks that no console errors occur, and saves screenshots into
// SCREENS_DIR. Prints one JSON object with the results; the exit code is 1
// when a check fails.
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

// the move the right arrow goes to: main moves follow main moves, and a main move whose game
// goes on only in variations leads into the first of them
const CONT = `(id) => {
  const N = window.READER.nodes, n = N[id];
  if (n.main) { for (const c of n.children) if (N[c].main) return c; }
  return n.children.length ? n.children[0] : null;
}`;
const ROW = 25.5;
const rgbOf = (page, prop) => page.evaluate((prop) => {
  const v = getComputedStyle(document.documentElement).getPropertyValue(prop).trim();
  const probe = document.createElement("i"); probe.style.color = v; document.body.appendChild(probe);
  const rgb = getComputedStyle(probe).color; probe.remove(); return rgb;
}, prop);

// open the chapter of the contents page that holds a PDF page
async function openChapterOf(page, p) {
  await page.evaluate((p) => {
    const d = document.querySelector(".pg[data-page='" + p + "']").closest("details");
    d.open = true;
  }, p);
}

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
    await page.waitForSelector(".pg[data-page='" + PAGE + "']", { state: "attached" });
    await page.screenshot({ path: path.join(screens, "index_1280.png") });
    out.screenshots.push("index_1280.png");

    // a diagram outline on the contents page switches the diagram off and on
    const sel0 = JSON.parse(await page.evaluate(() => window.selectionText()));
    await openChapterOf(page, PAGE);
    const frame = await page.$(".pg[data-page='" + PAGE + "'] .thumb .d");
    check("page " + PAGE + " shows a diagram outline on the contents page", frame);
    const fid = await frame.getAttribute("data-id");
    await frame.scrollIntoViewIfNeeded();
    await frame.click();
    const off = await page.evaluate((id) => {
      const b = document.querySelector(".thumb .d[data-id='" + id + "']");
      return { pressed: b.getAttribute("aria-pressed"), cls: b.classList.contains("off"),
               excluded: JSON.parse(window.selectionText()).diagrams.exclude.includes(id),
               note: b.closest(".pg").querySelector(".pgnote").textContent,
               msg: document.getElementById("msg").textContent };
    }, fid);
    check("a click on a diagram outline leaves the diagram out", off.pressed === "false" && off.cls && off.excluded, off);
    check("the page says in words that the diagram is left out",
          /is left out/.test(off.note) && /is now left out/.test(off.msg), off);
    await page.screenshot({ path: path.join(screens, "index_chapter_1280.png") });
    out.screenshots.push("index_chapter_1280.png");
    await frame.click();
    const sel1 = JSON.parse(await page.evaluate(() => window.selectionText()));
    check("a second click uses the diagram again and restores the selection",
          JSON.stringify(sel1.diagrams) === JSON.stringify(sel0.diagrams), { before: sel0.diagrams.exclude.length,
            after: sel1.diagrams.exclude.length });

    const link = await page.$(".pg[data-page='" + PAGE + "'] a");
    check("index links page " + PAGE + " to a chapter reader", link);
    const href = await link.getAttribute("href");
    out.chapter = href.split("#")[0];
    await Promise.all([page.waitForURL(/ch\d\d\.html/), link.click()]);
    await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
    let st = await page.evaluate(() => window.readerState);
    check("reader opens at page " + PAGE, st.page === PAGE, st);
    const opened = await page.evaluate(() => ({
      svg: !!document.querySelector("#board svg, #board canvas"),
      height: document.getElementById("board").offsetHeight,
      moves: document.querySelectorAll("#tree .mv").length,
      title: document.getElementById("linetitle").textContent }));
    check("a page link opens with a board and a line in the panel",
          opened.svg && opened.height > 100 && opened.moves > 0 && opened.title !== "No line chosen", opened);
    const box = await page.evaluate(() => getComputedStyle(document.getElementById("usepage")).appearance);
    check("check boxes are drawn in hairlines, not as the browser's control", box === "none", box);

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
    const sel = "#ov .mark[data-node='" + target + "']";
    const hidden = await page.$eval(sel, (el) => getComputedStyle(el).outlineWidth);
    await page.hover(sel);
    const hovered = await page.$eval(sel, (el) => [getComputedStyle(el).outlineWidth, getComputedStyle(el).outlineStyle]);
    check("a move box stays hidden until the pointer is over it",
          hidden === "0px" && hovered[0] !== "0px" && hovered[1] === "solid", { hidden, hovered });
    const before = st.fen;
    await page.click(sel);
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

    // the move list: the current move is the list's one Tab stop, and hover differs from it
    const accent = await rgbOf(page, "--accent");
    const treeLook = await page.evaluate(() => {
      const cur = document.querySelector("#tree .mv.cur");
      const other = Array.from(document.querySelectorAll("#tree .mv:not(.cur):not(.start)"))
        .find((e) => e.offsetParent && !e.closest(".var"));
      return { tag: cur.tagName, tab: cur.tabIndex, other: other ? other.dataset.node : null,
               stops: document.querySelectorAll("#tree .mv[tabindex='0']").length };
    });
    check("each move in the list is a button, and the list is one Tab stop",
          treeLook.tag === "BUTTON" && treeLook.tab === 0 && treeLook.stops === 1, treeLook);
    if (treeLook.other) {
      await page.hover("#tree .mv[data-node='" + treeLook.other + "']");
      const hov = await page.evaluate((id) => {
        const h = getComputedStyle(document.querySelector("#tree .mv[data-node='" + id + "'] .san"));
        const c = getComputedStyle(document.querySelector("#tree .mv.cur .san"));
        return { hover: h.color, line: h.textDecorationLine, cur: c.color };
      }, treeLook.other);
      check("hover underlines a move in its own colour, and only the current move is blue",
            hov.hover !== accent && hov.line === "underline" && hov.cur === accent, hov);
      await page.mouse.move(5, 5);
    }

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

    // "Show reading" outlines the boxes that need attention, leaves the moves read without doubt
    // unmarked, explains the outlines in words and moves nothing on the page
    const top0 = await page.evaluate(() => document.getElementById("pagebox").getBoundingClientRect().top + window.scrollY);
    await page.click("#showread");
    const shown = await page.evaluate(() => {
      const ok = document.querySelector("#ov .mark.st-ok:not(.current)");
      const other = document.querySelector("#ov .mark.st-waiting, #ov .mark.st-unattached, #ov .mark.st-guessed," +
        " #ov .mark.st-ambiguous, #ov .mark.st-failed");
      const legend = document.querySelector(".legend");
      return { on: document.body.classList.contains("reading"), okWidth: getComputedStyle(ok).outlineWidth,
               otherWidth: getComputedStyle(other).outlineWidth, otherStyle: getComputedStyle(other).outlineStyle,
               legend: getComputedStyle(legend).visibility === "visible" && legend.offsetHeight > 0,
               words: legend.textContent.indexOf("no outline is read without doubt") >= 0,
               top: document.getElementById("pagebox").getBoundingClientRect().top + window.scrollY,
               otherSel: other.dataset.mark };
    });
    check("Show reading outlines only the boxes that need attention and explains them in words",
          shown.on && shown.okWidth === "0px" && shown.otherWidth !== "0px" && shown.legend && shown.words, shown);
    check("Show reading moves nothing on the page", Math.abs(shown.top - top0) < 1, { top0, top: shown.top });
    await page.keyboard.press("Shift");
    await page.focus("#ov .mark[data-mark='" + shown.otherSel + "']");
    const focused = await page.evaluate((i) => {
      const el = document.querySelector("#ov .mark[data-mark='" + i + "']");
      return { visible: el.matches(":focus-visible"), color: getComputedStyle(el).outlineColor,
               width: getComputedStyle(el).outlineWidth, style: getComputedStyle(el).outlineStyle };
    }, shown.otherSel);
    check("with Show reading on, a focused box shows the blue focus outline",
          focused.visible && focused.color === accent && focused.style === "solid", focused);
    await page.evaluate(() => document.activeElement && document.activeElement.blur());
    await page.click("#showread");
    const hiddenAgain = await page.evaluate(() => ({ on: document.body.classList.contains("reading"),
      width: getComputedStyle(document.querySelector("#ov .mark.st-ok:not(.current)")).outlineWidth }));
    check("Hide reading hides the outlines again", !hiddenAgain.on && hiddenAgain.width === "0px", hiddenAgain);

    // a line under "On this page" gives the focus back, so the arrow keys step through moves
    const lineId = await page.evaluate(() => window.READER.nodes[window.readerState.nodeId].line);
    await page.click("#chips [data-line='" + lineId + "']");
    const root = await page.evaluate(() => window.readerState.nodeId);
    await page.keyboard.press("ArrowRight");
    const st4 = await page.evaluate(() => ({ s: window.readerState,
      line: window.READER.nodes[window.readerState.nodeId].line }));
    check("ArrowRight after choosing a line steps through that line",
          st4.line === lineId && st4.s.nodeId !== root, st4);

    // a diagram, its view in place of the board, and leaving the diagram out
    const diag = await page.$("#ov .diag");
    check("page " + PAGE + " has a diagram box", diag);
    const did = await diag.getAttribute("data-diagram");
    await diag.click();
    const panel = await page.evaluate(() => {
      const p = document.getElementById("dpanel");
      return { hidden: p.hidden, text: p.innerText, canvas: !!p.querySelector("canvas"),
               use: !!p.querySelector("#usediag"), board: document.getElementById("board").offsetHeight,
               pictures: document.querySelectorAll("#panel canvas").length };
    });
    check("clicking a diagram opens the diagram panel", !panel.hidden && panel.canvas, panel.hidden);
    check("the diagram picture replaces the board and appears once",
          panel.board === 0 && panel.pictures === 1, { board: panel.board, pictures: panel.pictures });
    check("the panel names the diagram", /Diagram|Unnumbered diagram/.test(panel.text), panel.text.slice(0, 80));
    check("the panel says what board reading made of the diagram", /Stage 3/.test(panel.text));
    check("the panel offers to use or leave out the diagram", panel.use);
    out.diagram = did;
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(screens, "reader_1280.png") });
    out.screenshots.push("reader_1280.png");
    // on a page that is left out, ticking the diagram uses the page again
    await page.uncheck("#usepage");
    const offState = await page.evaluate(() => ({ diag: document.getElementById("usediag").checked,
      note: document.getElementById("dpageoff").textContent }));
    check("the diagram panel says when the page is left out",
          !offState.diag && /left this page out/.test(offState.note), offState);
    await page.check("#usediag");
    const back = await page.evaluate(() => ({ page: document.getElementById("usepage").checked,
      sel: JSON.parse(window.selectionText ? window.selectionText() : "null") }));
    check("ticking a diagram on a page that is left out uses the page again", back.page, back);
    await page.uncheck("#usediag");
    await page.click("#dclose");
    const framed = await page.$eval("#ov .diag[data-diagram='" + did + "']", (el) => ({
      cls: el.classList.contains("excluded"), style: getComputedStyle(el).outlineStyle,
      note: document.getElementById("diagnote").textContent }));
    check("a diagram left out keeps a dashed outline and a note on the page",
          framed.cls && framed.style === "dashed" && /left out of the selection/.test(framed.note), framed);

    // a long line: the current move stays in view in the move list, and no row is cut
    const longLine = await page.evaluate(() => {
      const D = window.READER;
      let best = null, most = 0;
      for (const lid of D.lineOrder) {
        let k = 0;
        for (const id in D.nodes) if (D.nodes[id].line === lid && D.nodes[id].main) k++;
        if (k > most) { most = k; best = lid; }
      }
      return { id: best, moves: most };
    });
    await page.evaluate((id) => { location.hash = "#line=" + id; }, longLine.id);
    await page.waitForTimeout(100);
    const hiddenSteps = [], cutRows = [];
    for (let i = 0; i < Math.min(60, longLine.moves); i++) {
      await page.keyboard.press("ArrowRight");
      const v = await page.evaluate(() => {
        const t = document.getElementById("tree"), c = t.querySelector(".mv.cur");
        if (!c) return null;
        const a = t.getBoundingClientRect(), b = c.getBoundingClientRect();
        return { inside: b.top >= a.top - 1 && b.bottom <= a.bottom + 1, scroll: t.scrollHeight > t.clientHeight + 1,
                 h: t.clientHeight, node: c.dataset.node };
      });
      if (v && !v.inside) hiddenSteps.push(i + 1);
      if (v && v.scroll && Math.abs(v.h / ROW - Math.round(v.h / ROW)) > 0.05) cutRows.push(v.h);
    }
    check("the current move stays in view while stepping through a long line", hiddenSteps.length === 0,
          { line: longLine, hiddenSteps });
    check("the move list ends at a whole row", cutRows.length === 0, cutRows.slice(0, 5));

    // a main move whose game goes on only in variations: the right arrow enters the first one
    const fork = await page.evaluate(() => {
      const N = window.READER.nodes;
      for (const id in N) {
        const n = N[id];
        if (n.main && n.children.length && !n.children.some((c) => N[c].main)) return { id, first: n.children[0] };
      }
      return null;
    });
    if (fork) {
      await page.evaluate((id) => { location.hash = "#node=" + id; }, fork.id);
      await page.waitForTimeout(100);
      await page.keyboard.press("ArrowRight");
      const went = await page.evaluate(() => window.readerState.nodeId);
      check("the right arrow enters a variation where the main line stops", went === fork.first, { fork, went });
    }

    // a box on the page keeps the reader on that page, even when its move belongs to another page too
    const other = await page.evaluate(() => {
      const D = window.READER;
      for (const p in D.pages) for (const m of D.pages[p].marks) {
        const n = m.node && D.nodes[m.node];
        if (n && n.page && n.page !== parseInt(p, 10) && (n.page in D.pages)) return { page: parseInt(p, 10), node: m.node };
      }
      return null;
    });
    if (other) {
      await page.evaluate((p) => { location.hash = "#page=" + p; }, other.page);
      await page.waitForTimeout(100);
      await page.click("#ov .mark[data-node='" + other.node + "']");
      const kept = await page.evaluate(() => window.readerState);
      check("a click on a box keeps its page", kept.page === other.page && kept.nodeId === other.node,
            { other, kept });
    }
    await page.evaluate((p) => { location.hash = "#page=" + p; }, PAGE);
    await page.waitForTimeout(100);

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
    const boardW = await page.evaluate(() => [document.querySelector("#board svg").getBoundingClientRect().width,
      document.documentElement.clientWidth]);
    check("the board is as wide as the page at 390 px, within 16 px margins",
          Math.abs(boardW[0] - (boardW[1] - 32)) <= 1, boardW);
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
    await page.evaluate(() => document.getElementById("panel").scrollIntoView({ block: "start" }));
    await page.waitForTimeout(300);
    const aside = await page.evaluate(() => document.getElementById("mini").classList.contains("on"));
    check("the small board steps aside while the panel is in view", !aside, aside);

    // back on the contents page, the diagram is left out there as well
    await page.goto(index);
    await page.waitForSelector(".pg", { state: "attached" });
    const iw = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    check("index has no sideways scroll at 390 px", iw[0] <= iw[1], iw);
    await page.screenshot({ path: path.join(screens, "index_390.png") });
    out.screenshots.push("index_390.png");
    const shared = await page.evaluate((id) => ({
      pressed: document.querySelector(".thumb .d[data-id='" + id + "']").getAttribute("aria-pressed"),
      sel: JSON.parse(window.selectionText()) }), did);
    check("the contents page shows the change made in the reader",
          shared.pressed === "false" && shared.sel.diagrams.exclude.includes(did), shared.pressed);

    // unticking a page survives a visit to the reader and back
    await page.setViewportSize({ width: 1280, height: 900 });
    await openChapterOf(page, PAGE);
    const cb = await page.$(".pcb[data-page='" + PAGE + "']");
    await cb.scrollIntoViewIfNeeded();
    await cb.click();
    let selText = await page.evaluate(() => window.selectionText());
    let selObj = JSON.parse(selText);
    check("unticking a page excludes it in the selection",
          selObj.pages.exclude.some(([a, b]) => a <= PAGE && PAGE <= b), selObj.pages);
    await page.goto("file://" + path.resolve(dir, out.chapter) + "#page=" + PAGE);
    await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
    const offShown = await page.evaluate(() => !document.getElementById("usepage").checked &&
      document.getElementById("offpage").classList.contains("on") &&
      document.getElementById("offpage").offsetHeight > 0);
    check("the reader marks the page as left out", offShown);
    await page.goBack();
    await page.waitForSelector(".pg", { state: "attached" });
    selText = await page.evaluate(() => window.selectionText());
    selObj = JSON.parse(selText);
    check("the change survives a visit to the reader",
          selObj.pages.exclude.some(([a, b]) => a <= PAGE && PAGE <= b), selObj.pages);
    await page.waitForTimeout(200);
    const tick = await page.evaluate((p) => document.querySelector(".pcb[data-page='" + p + "']").checked, PAGE);
    check("after the Back button the page's box shows the stored selection", tick === false, tick);
    out.selection = selText;
    await page.click("#resetbtn");
    const reset = JSON.parse(await page.evaluate(() => window.selectionText()));
    check("Undo changes restores the selection of the run",
          !reset.pages.exclude.some(([a, b]) => a <= PAGE && PAGE <= b) && !reset.diagrams.exclude.includes(did));

    // a page without a printed number shows its PDF page in the page box, and Enter keeps it
    await page.goto("file://" + path.resolve(dir, "ch00.html") + "#page=1");
    await page.waitForFunction(() => window.readerState && window.readerState.page === 1);
    const lab = await page.evaluate(() => document.getElementById("pagenum").value);
    await page.focus("#pagenum");
    await page.keyboard.press("Enter");
    const still = await page.evaluate(() => [window.readerState.page, document.getElementById("pagenum").value]);
    check("a page without a printed number is labelled by its PDF page", lab === "PDF 1" && still[0] === 1 &&
          still[1] === "PDF 1", { lab, still });

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
