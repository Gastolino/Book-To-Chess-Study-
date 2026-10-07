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
// window when a box is tapped, the board at the foot of the window above the
// bar, and "Moves"), and on an iPhone 13 (390x664 visible) the board that
// sticks to the foot of the window while the page scrolls by and lets go at
// the end of the page picture, "Board", the current move above the board, a
// correction, and the wide layouts with the board at the head of the panel;
// checks the label of a page without a printed number,
// opens the Review view and corrects one move, one diagram, one sequence
// placed in no line and one piece symbol (through the eye on the page), checks
// what the browser stores, takes screenshots of the editors at 1280 and 390 px
// in the light and dark schemes, and prints the corrections it made,
// checks that no console errors occur, and saves screenshots into
// SCREENS_DIR. Prints one JSON object with the results; the exit code is 1
// when a check fails.
const { chromium, devices } = require("playwright");
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
    // reading: a tap on the diagram sets up the position the book starts a line from, at the line's
    // start, so that the arrows step through the line; or the move after which the diagram stands
    const want = await page.evaluate((id) => {
      const d = Object.values(window.READER.pages).flatMap((pg) => pg.diagrams).find((x) => x.id === id);
      const lid = (d.lines || []).find((l) => window.READER.lines[l]);
      return lid ? window.READER.lines[lid].root : (d.after_node && window.READER.nodes[d.after_node] ? d.after_node : null);
    }, did);
    check("not in reading mode to begin with", !(await page.evaluate(() => document.body.classList.contains("reading"))));
    await diag.click();
    if (want) {
      const tapped = await page.evaluate(() => ({ node: window.readerState.nodeId,
        panel: !document.getElementById("dpanel").hidden, board: !!document.querySelector("#board svg"),
        start: !!document.querySelector("#tree .mv.start.cur") }));
      check("a tap on a diagram sets up the line it starts at its starting position, with no panel",
            tapped.node === want && !tapped.panel && tapped.board, { tapped, want });
      await page.click("#bfwd");
      const next = await page.evaluate(() => window.readerState.nodeId);
      check("the arrow then plays the line's first move", next && next !== want &&
            (await page.evaluate((w) => window.READER.nodes[w].children, want)).indexOf(next) >= 0, { next, want });
      // the line's description names the diagram, and opens its panel (in reading mode)
      await page.click("#showread");
      await page.click("#linemeta .dlink").catch(() => null);
      check("the diagram named under the line opens its panel",
            await page.evaluate(() => !document.getElementById("dpanel").hidden));
      await page.click("#dclose");
    } else await page.click("#showread");
    // reading mode: a tap on the diagram opens its panel
    await diag.click();
    const panel = await page.evaluate((id) => {
      const p = document.getElementById("dpanel");
      const d = Object.values(window.READER.pages).flatMap((pg) => pg.diagrams).find((x) => x.id === id);
      return { hidden: p.hidden, text: p.innerText, read: !!(d && d.fen),
               set: !!p.querySelector(".boardwrap svg, .boardwrap canvas"),
               use: !!p.querySelector("#usediag"), board: document.getElementById("board").offsetHeight,
               pictures: document.querySelectorAll("#panel canvas.pic").length,
               wide: p.querySelector(".boardwrap") ? p.querySelector(".boardwrap").getBoundingClientRect().width : 0,
               panelW: p.getBoundingClientRect().width };
    }, did);
    check("clicking a diagram opens the diagram panel", !panel.hidden, panel.hidden);
    check("the diagram panel takes the board's place: the position read from the picture, set up on a board, " +
          "and not the picture again (the page shows it)",
          panel.board === 0 && (panel.read ? panel.set && panel.pictures === 0 : panel.pictures === 1),
          { board: panel.board, pictures: panel.pictures, read: panel.read, set: panel.set });
    check("the panel names the diagram", /Diagram|Unnumbered diagram/.test(panel.text), panel.text.slice(0, 80));
    check("the panel says what board reading made of the diagram", /Stage 3/.test(panel.text));
    check("the panel offers to use or leave out the diagram", panel.use);
    out.diagram = did;
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(screens, "reader_1280.png") });
    out.screenshots.push("reader_1280.png");
    // on a page that is left out, ticking the diagram uses the page again ("Use this page"
    // belongs to reading mode, with the other controls of what the program reads)
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
    // from the top of the window
    await page.evaluate(() => window.scrollTo(0, 0));
    await mark.scrollIntoViewIfNeeded();
    const y0 = await page.evaluate(() => window.scrollY);
    await mark.click();
    await page.waitForTimeout(400);
    // the page stays in view: the window moves at most so far that the tapped box
    // stays above the board, which stays at the foot of the window above the bar
    const tapped = await page.evaluate((id) => {
      const r = document.querySelector("#ov .mark[data-node='" + id + "']").getBoundingClientRect();
      const b = document.getElementById("boardblock").getBoundingClientRect();
      return { y1: window.scrollY, top: r.top, bottom: r.bottom, free: b.top,
               panel: document.getElementById("lsec").getBoundingClientRect().top - window.innerHeight };
    }, target);
    check("tapping a box keeps it in view above the board, on the page",
          tapped.top >= 0 && tapped.bottom <= tapped.free && tapped.panel > 0, { y0, ...tapped });
    const boardW = await page.evaluate(() => [document.querySelector("#board svg").getBoundingClientRect().width,
      document.documentElement.clientWidth]);
    check("the board is as wide as the page at 390 px, within 16 px margins",
          Math.abs(boardW[0] - (boardW[1] - 32)) <= 1, boardW);
    // (the tapped box may lie at the end of the page, where the board has let go: from the top)
    const yTap = await page.evaluate(() => window.scrollY);
    await page.evaluate(() => window.scrollTo(0, 0));
    const foot = await page.evaluate(() => {
      const b = document.getElementById("boardblock").getBoundingClientRect();
      const bar = document.getElementById("mbar").getBoundingClientRect();
      return { bottom: b.bottom, barTop: bar.top, pieces: document.querySelectorAll("#board use").length,
               mini: document.getElementById("mini").classList.contains("on"),
               pressed: document.getElementById("mboard").getAttribute("aria-pressed") };
    });
    check("the board shows the position at the foot of the window, just above the bar, at 390 px",
          Math.abs(foot.bottom - foot.barTop) <= 1.5 && foot.pieces > 0 && !foot.mini && foot.pressed === "true", foot);
    await page.evaluate((y) => window.scrollTo(0, y), yTap);
    await page.screenshot({ path: path.join(screens, "reader_390.png") });
    out.screenshots.push("reader_390.png");
    await page.click("#bfwd");
    await page.screenshot({ path: path.join(screens, "reader_390_board.png") });
    out.screenshots.push("reader_390_board.png");
    await page.click("#mmoves");
    await page.waitForTimeout(300);
    const moves = await page.evaluate(() => {
      const b = document.getElementById("boardblock").getBoundingClientRect();
      return { top: b.top, bottom: b.bottom, line: document.getElementById("lsec").getBoundingClientRect().top,
               tree: document.getElementById("tree").getBoundingClientRect().top, h: window.innerHeight };
    });
    check("Moves shows the board in its place below the page, the line's moves under it",
          Math.abs(moves.top) <= 1 && moves.line >= moves.bottom - 1 && moves.tree < moves.h, moves);
    // the bar: no move arrows (the board has its own), and a magnifier that enlarges the page
    const bar = await page.evaluate(() => {
      const z = document.getElementById("mzoom").getBoundingClientRect();
      return { arrows: !!document.querySelector("#mbar #mback, #mbar #mfwd"), x: z.left, right: z.right, w: z.width,
               pressed: document.getElementById("mzoom").getAttribute("aria-pressed") };
    });
    check("on the phone, Enlarge page under the page gives way to the bar's magnifier",
          await page.evaluate(() => getComputedStyle(document.getElementById("zoom")).display === "none"));
    check("the phone bar holds a magnifier and no move arrows",
          !bar.arrows && bar.x >= 0 && bar.right <= 390 && bar.w >= 24 && bar.pressed === "false", bar);
    await page.click("#mzoom");
    const zoomed = await page.evaluate(() => ({
      zoom: document.getElementById("pagescroll").classList.contains("zoom"),
      pressed: document.getElementById("mzoom").getAttribute("aria-pressed"),
      label: document.getElementById("zoom").textContent,
      wide: document.getElementById("pagebox").getBoundingClientRect().width / document.getElementById("pagescroll").clientWidth }));
    check("the magnifier enlarges the page", zoomed.zoom && zoomed.pressed === "true" && zoomed.label === "Fit page" &&
          zoomed.wide > 1.9, zoomed);
    await page.screenshot({ path: path.join(screens, "reader_390_zoom.png") });
    out.screenshots.push("reader_390_zoom.png");
    // a diagram on the phone: the position read from it, set up on a board as wide as the panel
    await page.evaluate((p) => { location.hash = "#page=" + p; }, PAGE);
    await page.waitForFunction((p) => window.readerState.page === p, PAGE);
    await page.click("#mzoom");                     // the page fitted again, its diagram in reach
    // (in reading mode: when reading, the tap goes to the diagram's line; see above)
    await page.evaluate(() => { if (!document.body.classList.contains("reading")) document.getElementById("showread").click(); });
    await page.evaluate(() => document.querySelector("#ov .diag").click());
    await page.waitForTimeout(200);
    const dph = await page.evaluate(() => {
      const p = document.getElementById("dpanel"), w = p.querySelector(".boardwrap");
      return { hidden: p.hidden, pictures: p.querySelectorAll("canvas.pic").length,
               board: w ? w.getBoundingClientRect().width : 0, panel: p.getBoundingClientRect().width,
               h: window.innerHeight };
    });
    // (as wide as the move board: the panel's width, up to 55% of the window's height; it was half
    // the panel beside the picture)
    check("on the phone a diagram shows its position on a full-size board, without the picture",
          !dph.hidden && dph.pictures === 0 && dph.board >= 0.8 * dph.panel, dph);
    await page.screenshot({ path: path.join(screens, "reader_390_diagram.png") });
    out.screenshots.push("reader_390_diagram.png");
    await page.click("#dclose");
    check("a second tap fits the page again", await page.evaluate(() =>
      !document.getElementById("pagescroll").classList.contains("zoom") &&
      document.getElementById("mzoom").getAttribute("aria-pressed") === "false" &&
      document.getElementById("zoom").textContent === "Enlarge page"));

    // an iPhone 13 with its toolbars (390 x 664 visible): the board sticks to the foot of the
    // window while the page scrolls by, lets go at the end of the page picture and sticks again
    {
      const ctx13 = await browser.newContext({ ...devices["iPhone 13"], viewport: { width: 390, height: 664 } });
      const pp = await ctx13.newPage();
      pp.on("pageerror", (e) => out.errors.push(String(e)));
      pp.on("console", (m) => { if (m.type() === "error") out.errors.push(m.text()); });
      await pp.goto(page.url().split("#")[0] + "#node=" + target);
      await pp.waitForFunction((id) => window.readerState && window.readerState.nodeId === id, target);
      await pp.waitForTimeout(300);
      await pp.evaluate(() => window.scrollTo(0, 0));
      await pp.waitForTimeout(100);
      const g = () => pp.evaluate(() => {
        const r = (id) => { const x = document.getElementById(id).getBoundingClientRect(); return { top: x.top, bottom: x.bottom }; };
        return { y: window.scrollY, board: r("boardblock"), bar: r("mbar"), page: r("pagescroll"), line: r("lsec"),
                 sw: document.documentElement.scrollWidth, w: window.innerWidth,
                 stick: document.body.classList.contains("stickboard") };
      });
      const a = await g();
      check("iPhone 13: at the top of the page the board's foot sits on the bar's top edge",
            a.stick && Math.abs(a.board.bottom - a.bar.top) <= 1.5 && a.board.top > a.page.top, a);
      check("iPhone 13: the board takes at most about 55% of the window's height",
            (await pp.evaluate(() => document.querySelector("#board svg").getBoundingClientRect().height)) <= 0.56 * 664, a);
      check("iPhone 13: no sideways scroll", a.sw <= a.w, a);
      await pp.evaluate(() => window.scrollBy(0, 300));
      await pp.waitForTimeout(150);
      const b = await g();
      check("iPhone 13: scrolling the page by 300 px moves the page and leaves the board where it was",
            Math.abs(b.board.top - a.board.top) <= 1 && Math.abs((a.page.top - b.page.top) - 300) <= 1, { a, b });
      // to the end of the page picture and past it
      await pp.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      await pp.waitForTimeout(150);
      const c = await g();
      check("iPhone 13: past the end of the page picture the board scrolls up with it, the move list below it",
            c.board.bottom < c.bar.top - 50 && c.board.top >= c.page.bottom - 1 && c.line.top >= c.board.bottom - 1 &&
            c.line.top < c.bar.top, c);
      // the last line of the page can be brought just above the board before the board lets go
      const release = await pp.evaluate(() => {
        window.scrollTo(0, 0);
        const ps = document.getElementById("pagescroll").getBoundingClientRect();
        const top = document.getElementById("boardblock").getBoundingClientRect().top;
        window.scrollTo(0, ps.bottom - top + 1);
        const p2 = document.getElementById("pagescroll").getBoundingClientRect(), b2 = document.getElementById("boardblock").getBoundingClientRect();
        return { pageBottom: p2.bottom, boardTop: b2.top };
      });
      check("iPhone 13: the page's last line comes above the board's top edge", release.pageBottom <= release.boardTop, release);
      await pp.evaluate(() => window.scrollTo(0, 300));
      await pp.waitForTimeout(150);
      const d = await g();
      check("iPhone 13: scrolling back up the board sticks again", Math.abs(d.board.top - b.board.top) <= 1, { b, d });
      // a frame sequence while scrolling down the page and past it
      const H = await pp.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
      for (let i = 0; i < 8; i++) {
        await pp.evaluate((y) => window.scrollTo(0, y), Math.round(H * i / 7));
        await pp.waitForTimeout(80);
        const name = "sticky_390x664_" + i + ".png";
        await pp.screenshot({ path: path.join(screens, name) });
        out.screenshots.push(name);
      }
      // Board hides the board at the foot: the page has the whole height, the board stays in its place
      await pp.evaluate(() => window.scrollTo(0, 0));
      await pp.tap("#mboard");
      await pp.waitForTimeout(150);
      const off = await g();
      check("iPhone 13: Board hides the board at the foot of the window",
            !off.stick && off.board.top >= off.page.bottom - 1 && off.board.top > off.bar.top &&
            (await pp.$eval("#mboard", (e) => e.getAttribute("aria-pressed"))) === "false", off);
      await pp.tap("#mboard");
      await pp.waitForTimeout(150);
      const on = await g();
      check("iPhone 13: Board shows it again", on.stick && Math.abs(on.board.bottom - on.bar.top) <= 1.5, on);
      // stepping through the line keeps the current move on the page above the board
      await pp.evaluate(() => window.scrollTo(0, 0));
      for (let i = 0; i < 6; i++) {
        await pp.tap("#bfwd");
        await pp.waitForTimeout(450);
        const m = await pp.evaluate(() => {
          const el = document.querySelector("#ov .mark.current");
          if (!el) return null;
          const r = el.getBoundingClientRect(), b = document.getElementById("boardblock").getBoundingClientRect();
          return { top: r.top, bottom: r.bottom, boardTop: b.top, node: window.readerState.nodeId };
        });
        if (m) check("iPhone 13: the current move stays on the page above the board (" + i + ")",
                     m.top >= 0 && m.bottom <= m.boardTop + 1, m);
      }
      // a correction: the sheet above the bar, a smaller board in the bar, the page above them
      await pp.tap("#mpen");
      const vis = await pp.evaluate(() => {
        const b = document.getElementById("boardblock").getBoundingClientRect();
        const el = [...document.querySelectorAll("#ov .mark")].find((e) => {
          const r = e.getBoundingClientRect(); return r.top > 0 && r.bottom < b.top && r.width > 4; });
        return el ? el.dataset.node : null;
      });
      check("iPhone 13: a move shows above the board to correct", !!vis, vis);
      await pp.tap("#ov .mark[data-node='" + vis + "']");
      await pp.waitForSelector("#fix:not([hidden])");
      await pp.waitForTimeout(300);
      const fx = await pp.evaluate((id) => {
        const f = document.getElementById("fix").getBoundingClientRect(), bar = document.getElementById("mbar").getBoundingClientRect();
        const m = document.querySelector("#mini.on svg"), mr = m ? m.getBoundingClientRect() : null;
        const k = document.querySelector("#ov .mark[data-node='" + id + "']").getBoundingClientRect();
        return { fixTop: f.top, fixBottom: f.bottom, barTop: bar.top, mini: mr && { top: mr.top, bottom: mr.bottom, w: mr.width },
                 mark: { top: k.top, bottom: k.bottom }, sw: document.documentElement.scrollWidth, w: window.innerWidth,
                 stick: document.body.classList.contains("stickboard") };
      }, vis);
      check("iPhone 13: a correction shows its sheet above the bar, a board beside the bar's controls and the move above them",
            !fx.stick && Math.abs(fx.fixBottom - fx.barTop) <= 2 && fx.fixTop >= 100 && fx.mini && fx.mini.w >= 150 &&
            fx.mini.top >= fx.barTop - 1 && fx.mini.bottom <= 664 + 1 && fx.mark.top >= 0 && fx.mark.bottom <= fx.fixTop &&
            fx.sw <= fx.w, fx);
      await pp.screenshot({ path: path.join(screens, "sticky_390x664_correction.png") });
      out.screenshots.push("sticky_390x664_correction.png");
      await pp.tap("#fixclose");
      await pp.tap("#mpen");
      await pp.waitForTimeout(200);
      const back = await g();
      check("iPhone 13: closing the correction brings the board back to the foot",
            back.stick && Math.abs(back.board.bottom - back.bar.top) <= 1.5, back);
      // the wide layouts keep the board at the head of the panel
      for (const [w, h] of [[1280, 900], [1180, 820]]) {
        await pp.setViewportSize({ width: w, height: h });
        await pp.waitForTimeout(250);
        const wide = await pp.evaluate(() => {
          const panel = document.getElementById("panel"), r = panel.getBoundingClientRect();
          const b = document.querySelector("#board svg").getBoundingClientRect();
          return { first: panel.firstElementChild.id, foot: !!document.querySelector(".pagecol > .pagefoot"),
                   left: b.left - r.left, top: b.top - r.top, w: b.width, pw: r.width,
                   pos: getComputedStyle(document.getElementById("boardblock")).position };
        });
        check("at " + w + " px the board heads the panel on the right, as before",
              wide.first === "boardblock" && wide.foot && wide.pos === "static" && Math.abs(wide.left - 25) <= 1 &&
              Math.abs(wide.top - 16) <= 1 && Math.abs(wide.w - (wide.pw - 49)) <= 1, wide);
      }
      await ctx13.close();
    }

    // an iPad held upright (820 x 1180): the compact layout, with the line's title and moves beside
    // the board at the foot of the window, the board about a third of the height; held sideways,
    // the panel beside the page as before
    {
      const pad = await browser.newContext({ viewport: { width: 820, height: 1180 }, deviceScaleFactor: 2,
                                             isMobile: true, hasTouch: true });
      const tp = await pad.newPage();
      tp.on("pageerror", (e) => out.errors.push(String(e)));
      tp.on("console", (m) => { if (m.type() === "error") out.errors.push(m.text()); });
      await tp.goto(page.url().split("#")[0] + "#node=" + target);
      await tp.waitForFunction((id) => window.readerState && window.readerState.nodeId === id, target);
      await tp.waitForTimeout(300);
      const up = await tp.evaluate(() => {
        const r = (id) => document.getElementById(id).getBoundingClientRect();
        return { side: !!document.getElementById("side"), stick: document.body.classList.contains("stickboard"),
                 board: r("board"), tree: r("tree"), bar: r("mbar"), block: r("boardblock"), page: r("pagescroll"),
                 barShown: getComputedStyle(document.getElementById("mbar")).display !== "none",
                 treeIn: document.getElementById("side").contains(document.getElementById("tree")),
                 wide: document.documentElement.scrollWidth - window.innerWidth, h: window.innerHeight, w: window.innerWidth };
      });
      check("iPad upright: the board at the foot of the window, above the bar, with the moves beside it",
            up.side && up.treeIn && up.stick && up.barShown && Math.abs(up.block.bottom - up.bar.top) <= 1.5 &&
            up.tree.left >= up.board.right && up.tree.top < up.board.bottom && up.tree.width > 250, up);
      check("iPad upright: the board takes about a third of the height, the page the larger part",
            up.board.height <= 0.36 * up.h && up.board.height >= 0.3 * up.h && up.page.width >= up.w - 60, up);
      check("iPad upright: no sideways scroll", up.wide <= 0, up.wide);
      await tp.screenshot({ path: path.join(screens, "reader_ipad_upright.png") });
      out.screenshots.push("reader_ipad_upright.png");
      // stepping through the line keeps the current move in view in the move list beside the board
      for (let i = 0; i < 4; i++) await tp.click("#bfwd");
      const cur = await tp.evaluate(() => {
        const t = document.getElementById("tree").getBoundingClientRect(), c = document.querySelector("#tree .mv.cur");
        const r = c ? c.getBoundingClientRect() : null;
        return r && { inside: r.top >= t.top - 1 && r.bottom <= t.bottom + 1 };
      });
      check("iPad upright: the current move shows in the move list beside the board", cur && cur.inside, cur);
      // held sideways: the panel beside the page, the moves back in it
      await tp.setViewportSize({ width: 1180, height: 820 });
      await tp.waitForTimeout(400);
      const side = await tp.evaluate(() => ({ side: !!document.getElementById("side"),
        inPanel: document.getElementById("panel").contains(document.getElementById("tree")) &&
                 document.getElementById("panel").contains(document.getElementById("lsec")) &&
                 document.getElementById("panel").contains(document.getElementById("evalsec")),
        first: document.getElementById("panel").firstElementChild.id,
        bar: getComputedStyle(document.getElementById("mbar")).display }));
      check("iPad sideways: the panel beside the page holds the board and the moves again",
            !side.side && side.inPanel && side.first === "boardblock" && side.bar === "none", side);
      // and upright again
      await tp.setViewportSize({ width: 820, height: 1180 });
      await tp.waitForTimeout(400);
      check("iPad upright again: the moves beside the board", await tp.evaluate(() =>
        !!document.getElementById("side") && document.getElementById("side").contains(document.getElementById("tree"))));
      await pad.close();
    }

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
    if (!(await page.evaluate(() => document.body.classList.contains("reading")))) await page.click("#showread");
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

    // ---------------------------------------------------------------- the Review view and corrections
    await page.setViewportSize({ width: 1280, height: 900 });
    const chap = "file://" + path.resolve(dir, out.chapter);
    await page.goto(chap + "#page=" + PAGE);
    await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
    await page.evaluate(() => { for (const k of Object.keys(localStorage)) if (k.startsWith("chessbook-corrections:")) localStorage.removeItem(k); });
    await page.reload();
    await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
    const storeKey = await page.evaluate(() => "chessbook-corrections:" + window.READER.book.pdf + ":" + window.READER.pageCount);
    const stored = () => page.evaluate((k) => {
      const v = JSON.parse(localStorage.getItem(k) || "null"); return v ? v.corrections : null; }, storeKey);
    await page.click("#reviewbtn");
    const kinds = await page.$$eval("#revlist button[data-item]", (els) => els.map((e) => e.dataset.kind));
    check("Review lists piece symbols, moves, diagrams and sequences placed in no line",
          ["symbol", "move", "diagram", "seq"].every((k) => kinds.includes(k)), kinds.length);
    const firstKinds = kinds.slice(0, kinds.lastIndexOf("symbol") + 1);
    check("the piece symbols head the list, most frequent in the book first", firstKinds.every((k) => k === "symbol") &&
          await page.evaluate(() => { const D = window.READER; const b = Array.from(document.querySelectorAll(
            "#revlist button[data-kind='symbol']")).map((e) => D.symbols[e.dataset.sym] || 0);
            return b.every((x, i) => i === 0 || b[i - 1] >= x); }), firstKinds.length);

    // a move: one of the readings the program considered, or a typed move that must be legal
    const mv = await page.evaluate(() => {
      const D = window.READER;
      for (const b of document.querySelectorAll("#revlist button[data-kind='move']")) {
        b.click();
        const cur = window.readerState.nodeId, n = D.nodes[cur];
        if (n && n.legal && n.legal.length && n.key && document.querySelector("#fix button[data-san]"))
          return { item: b.dataset.item, node: cur, key: n.key, status: n.status };
      }
      return null;
    });
    check("a move of the Review view opens its editor on the board", mv && !(await page.$eval("#fix", (e) => e.hidden)), mv);
    const markShown = await page.$$eval("#ov .mark.current", (els) => els.length);
    check("selecting an item shows it on the page", markShown > 0, markShown);
    await page.fill("#fixsan", "Ka9");
    await page.press("#fixsan", "Enter");
    const refused = await page.$eval("#fixmsg", (e) => ({ text: e.textContent, bad: e.classList.contains("bad") }));
    check("a typed move that is not legal is refused in words", refused.bad && /not a legal move/.test(refused.text), refused);
    const boardBefore = await page.$eval("#board svg", (e) => e.getAttribute("aria-label"));
    const san = await page.$eval("#fix button[data-san]", (e) => e.dataset.san);
    await page.click("#fix button[data-san]");
    const afterMove = await page.evaluate(() => ({ label: document.querySelector("#board svg").getAttribute("aria-label"),
      msg: document.getElementById("fixmsg").textContent }));
    let st5 = await stored();
    check("a chosen move is stored in the browser under its token key",
          st5 && st5.moves[mv.key] && st5.moves[mv.key].san === san, st5 && st5.moves);
    check("the board shows the position after the chosen move at once",
          afterMove.label !== boardBefore && /You chose/.test(afterMove.msg), afterMove);
    // a failed move offers the legal moves of its position, filtered as the reader types
    const failed = await page.evaluate(() => {
      for (const b of document.querySelectorAll("#revlist button[data-kind='move']")) {
        const n = window.READER.nodes[(b.click(), window.readerState.nodeId)];
        if (n.status === "failed" && n.legal && n.legal.length > 3) return { node: n.id, n: n.legal.length };
      }
      return null;
    });
    if (failed) {
      const all = await page.$$eval("#fixlist button", (els) => els.length);
      const first = await page.$eval("#fixlist button", (e) => e.dataset.san);
      await page.fill("#fixsan", first.slice(0, 2));
      const some = await page.$$eval("#fixlist button", (els) => els.map((e) => e.dataset.san));
      check("a failed move lists the legal moves and filters them as the reader types",
            all >= Math.min(failed.n, 40) && some.length >= 1 && some.length <= all, { all, some: some.length });
    }

    // a diagram: a square, a piece from the row of thirteen, the side to move, and a check of the position
    await page.click("#revlist button[data-kind='diagram']");
    const dfix = await page.evaluate(() => {
      const ed = document.querySelector("#fixboard svg");
      return { board: !!ed, pieces: document.querySelectorAll("#fixpieces button").length,
               pieceDrawings: document.querySelectorAll("#fixpieces use").length,
               id: (document.querySelector(".diag.current") || {}).dataset ? document.querySelector(".diag.current").dataset.diagram : null };
    });
    check("a diagram opens an editable board with thirteen choices drawn with the board's pieces",
          dfix.board && dfix.pieces === 13 && dfix.pieceDrawings === 12 && dfix.id, dfix);
    const empty = await page.evaluate(() => {
      // an empty square for a test of the check: a second white king there is refused
      const rows = document.querySelectorAll("#fixboard [data-sq]");
      for (const r of rows) if (/empty$/.test(r.querySelector("title").textContent)) return r.dataset.sq;
      return null;
    });
    await page.click("#fixboard [data-sq='" + empty + "']");
    await page.click("#fixpieces button[data-put='K']");
    const twoKings = await page.evaluate(() => ({ dis: document.getElementById("fixsave").disabled,
      msg: document.getElementById("fixmsg").textContent }));
    check("a position without one king of each side cannot be saved", twoKings.dis && /one king of each colour/.test(twoKings.msg), twoKings);
    await page.click("#fixpieces button[data-put='']");
    const doubt = await page.evaluate((id) => {
      for (const p in window.READER.pages) for (const d of window.READER.pages[p].diagrams)
        if (d.id === id) return ((d.reading || {}).doubtful || [])[0] || null;
      return null;
    }, dfix.id);
    const kingAt = await page.evaluate((q) => q ? /king$/.test(document.querySelector("#fixboard [data-sq='" + q +
      "'] title").textContent) : true, doubt);
    const sq = !kingAt ? doubt : empty;
    await page.click("#fixboard [data-sq='" + sq + "']");
    await page.click("#fixpieces button[data-put='p']".replace("'p'", /[18]$/.test(sq) ? "'n'" : "'p'"));
    await page.click("#fix [data-turn='b']");
    const shownFen = await page.$eval("#fixboard svg", (e) => e.getAttribute("aria-label"));
    await page.click("#fixsave");
    st5 = await stored();
    const dsaved = st5 && st5.diagrams[dfix.id];
    check("a corrected diagram is stored with its position and side to move, and the board shows it",
          dsaved && / b /.test(dsaved.fen) && shownFen.indexOf(dsaved.fen.split(" ")[0]) >= 0, { dsaved, shownFen });
    out.diagramFixed = dfix.id;

    // a sequence placed in no line: tied to a move of the line, and another dismissed
    const seqs = await page.$$eval("#revlist button[data-kind='seq']", (els) => els.map((e) => e.dataset.item));
    await page.click("#revlist button[data-item='" + seqs[0] + "']");
    const seqKey = await page.evaluate(() => {
      const el = document.querySelector("#ov .mark.seqcur"); return el ? el.dataset.seq : null; });
    const to = await page.$eval("#fix button[data-to]", (e) => e.dataset.to).catch(() => null);
    check("a sequence placed in no line offers the moves of the line nearby", seqKey && to, { seqKey, to });
    await page.click("#fix button[data-to]");
    if (seqs.length > 1) {
      await page.click("#revlist button[data-item='" + seqs[1] + "']");
      await page.click("#fixdismiss");
    }
    st5 = await stored();
    check("the sequence's place is stored under its key",
          st5.unattached[seqKey] && st5.unattached[seqKey].attach_to === to &&
          (seqs.length < 2 || Object.values(st5.unattached).some((v) => v.attach_to === "dismiss")), st5.unattached);
    await page.click("#fixclose");

    // a piece symbol: the eye at the symbol on the page and its menu of six pieces
    const eyeAt = await page.evaluate(() => {
      const D = window.READER;
      for (const p in D.pages) D.pages[p].marks.forEach((m) => {});
      for (const p in D.pages) for (const m of D.pages[p].marks) {
        const n = m.node && D.nodes[m.node];
        if (m.symbol && !m.known && n && ["failed", "guessed", "ambiguous"].indexOf(n.status) >= 0 && n.san && /^[KQRBN]/.test(n.san))
          return { page: parseInt(p, 10), sym: m.symbol, piece: n.san[0], count: D.symbols[m.symbol] };
      }
      return null;
    });
    check("the chapter has an unreadable piece symbol on a move that needs a check", eyeAt, eyeAt);
    await page.evaluate((p) => { location.hash = "#page=" + p; }, eyeAt.page);
    await page.waitForFunction((p) => window.readerState.page === p, eyeAt.page);
    const eye = (await page.evaluateHandle((sym) => Array.from(document.querySelectorAll("#ov .eye"))
      .find((e) => e.dataset.sym === sym), eyeAt.sym)).asElement();
    const eyeLook = await eye.evaluate((e) => ({ shown: getComputedStyle(e).display !== "none",
      stroke: getComputedStyle(e.querySelector("svg")).strokeWidth, fill: getComputedStyle(e.querySelector("svg")).fill }));
    check("the eye is a thin line drawing at the symbol while Review is on", eyeLook.shown && eyeLook.stroke === "1.25px" &&
          eyeLook.fill === "none", eyeLook);
    await eye.scrollIntoViewIfNeeded();
    await eye.click();
    const menu = await page.evaluate(() => {
      const m = document.getElementById("symmenu"), cs = getComputedStyle(m);
      return { hidden: m.hidden, names: Array.from(m.querySelectorAll("button")).map((b) => b.textContent),
               pieces: m.querySelectorAll("use").length, shadow: cs.boxShadow, border: cs.borderTopStyle };
    });
    check("the eye opens a plain list of the six pieces with their names",
          !menu.hidden && menu.names.join(",") === "King,Queen,Rook,Bishop,Knight,Pawn" && menu.pieces === 6 &&
          menu.shadow === "none" && menu.border === "solid", menu);
    await page.click("#symmenu button[data-piece='" + eyeAt.piece + "']");
    st5 = await stored();
    const said = await page.$eval("#pagemsg", (e) => e.textContent);
    check("a piece chosen for a symbol is stored for the whole book and the count is said in words",
          st5.glyphs[eyeAt.sym] === eyeAt.piece && /This symbol appears .* times in the book/.test(said), { said, g: st5.glyphs });
    out.symbol = eyeAt;

    // the screenshots of the Review view, light and dark, wide and narrow
    const shots = async (w, h, scheme, name, open) => {
      await page.setViewportSize({ width: w, height: h });
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("about:blank");
      await page.goto(chap + "#page=" + PAGE);
      await page.waitForFunction(() => window.readerState && window.readerState.page !== null);
      await page.click("#reviewbtn");
      await page.click("#revlist button[data-kind='" + open + "']");
      await page.waitForTimeout(500);
      const geo = await page.evaluate(() => {
        const f = document.getElementById("fix").getBoundingClientRect(), bar = document.getElementById("mbar");
        const board = document.querySelector("#fixboard svg") || document.querySelector("#mini.on svg") ||
          document.querySelector("#board svg");
        const b = board ? board.getBoundingClientRect() : null;
        return { sw: document.documentElement.scrollWidth, iw: window.innerWidth, fixTop: f.top, fixBottom: f.bottom,
                 barTop: bar.offsetHeight ? bar.getBoundingClientRect().top : window.innerHeight,
                 board: b ? { top: b.top, bottom: b.bottom, w: b.width } : null };
      });
      await page.screenshot({ path: path.join(screens, name) });
      out.screenshots.push(name);
      return geo;
    };
    for (const scheme of ["light", "dark"]) {
      await shots(1280, 900, scheme, "review_move_1280_" + scheme + ".png", "move");
      const g = await shots(390, 844, scheme, "review_move_390_" + scheme + ".png", "move");
      check("at 390 px the move editor sits above the bar with the board in view (" + scheme + ")",
            g.sw <= g.iw && g.fixBottom <= g.barTop + 1 && g.board && g.board.top >= 0 && g.board.bottom <= 844 &&
            g.board.w > 100, g);
      const d = await shots(390, 844, scheme, "review_diagram_390_" + scheme + ".png", "diagram");
      check("at 390 px the diagram editor shows its board inside the window (" + scheme + ")",
            d.sw <= d.iw && d.board && d.board.top >= 0 && d.board.bottom <= d.barTop + 1 && d.board.w >= 200, d);
      await shots(1280, 900, scheme, "review_diagram_1280_" + scheme + ".png", "diagram");
      await shots(390, 844, scheme, "review_symbol_390_" + scheme + ".png", "symbol");
    }
    await page.emulateMedia({ colorScheme: "light" });
    await page.setViewportSize({ width: 1280, height: 900 });
    out.corrections = await page.evaluate(() => window.correctionsText());
    const idxFix = await (async () => { await page.goto(index); return page.evaluate(() => ({
      note: document.getElementById("fixnote").textContent, text: window.correctionsText() })); })();
    check("the contents page knows the stored corrections and copies them",
          /did not use yet/.test(idxFix.note) && JSON.parse(idxFix.text).glyphs[eyeAt.sym] === eyeAt.piece, idxFix.note);

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
