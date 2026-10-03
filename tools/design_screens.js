// Screenshots of every kind of page for checking them against DESIGN.md.
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tools/design_screens.js BOOK_OUTPUT_DIR [--out NAME] [SCENE...]
//   e.g. node tools/design_screens.js output/primer --out final
//
// Writes BOOK_OUTPUT_DIR/reader/screens/<NAME>/<scene>_<width>_<light|dark>.png (NAME is
// "design" unless --out names another folder) at 1280x900 and 390x844, in the light and the
// dark colour scheme, and prints one line per picture with the page width it measured (a page
// wider than the window scrolls sideways) and any console error. A scene marked "phone" is
// taken at 390x844 only, with a touch screen.
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const args = process.argv.slice(2);
const bookDir = args.shift();
let outName = "design";
const only = [];
while (args.length) {
  const a = args.shift();
  if (a === "--out") outName = args.shift(); else only.push(a);
}
const R = path.resolve(bookDir, "reader");
const OUT = path.join(R, "screens", outName);
fs.mkdirSync(OUT, { recursive: true });

// a move on the given PDF page with a position, preferring one with a comment
async function pickMove(p, pdfPage) {
  return p.evaluate((pg) => {
    const D = window.READER;
    let best = null;
    for (const el of document.querySelectorAll("#ov .mark.st-ok[data-node]")) {
      const n = D.nodes[el.dataset.node];
      if (!n || !n.fen || n.page !== pg) continue;
      if (n.comment) return el.dataset.node;
      if (!best) best = el.dataset.node;
    }
    return best;
  }, pdfPage);
}
async function choose(p, id) {
  if (id) await p.evaluate((id) => { location.hash = "#node=" + id; }, id);
  await p.waitForTimeout(200);
  await p.evaluate(() => window.scrollTo(0, 0));
}
async function stepRight(p, k) {
  for (let i = 0; i < k; i++) { await p.keyboard.press("ArrowRight"); await p.waitForTimeout(20); }
  await p.evaluate(() => window.scrollTo(0, 0));
}

const scenes = {
  index: { file: "index.html", act: async () => {} },
  index_chapter: { file: "index.html", act: async (p) => {
    await p.evaluate(() => {
      const li = document.querySelector("#ch07");
      li.querySelector("details").open = true;
      li.scrollIntoView();
    });
    const b = await p.$(".pg[data-page='250'] .thumb .d");
    if (b) await b.click();
    await p.evaluate(() => document.querySelector("#ch07").scrollIntoView());
  }},
  // opened from a page number on the contents page: no move chosen yet
  ch07_link: { file: "ch07.html#page=250", act: async () => {} },
  ch07: { file: "ch07.html#page=250", act: async (p) => { await choose(p, await pickMove(p, 250)); } },
  // Show reading on a page with every kind of status, and a move chosen from several readings
  ch07_reading: { file: "ch07.html#page=255", act: async (p) => {
    await p.click("#showread");
    const id = await p.evaluate(() => {
      const el = document.querySelector("#ov .mark.st-guessed[data-node], #ov .mark.st-ambiguous[data-node]");
      return el ? el.dataset.node : null;
    });
    await choose(p, id);
  }},
  ch07_diagram: { file: "ch07.html#page=250", act: async (p) => {
    await p.click("#ov .diag");
    await p.evaluate(() => window.scrollTo(0, 0));
  }},
  // a move the program could not read, with a figurine it could not name
  ch07_failed: { file: "ch07.html#node=n5604", act: async (p) => { await p.evaluate(() => window.scrollTo(0, 0)); } },
  ch05: { file: "ch05.html", act: async (p) => {
    // a decoded line with variations and a comment on one of its moves
    const id = await p.evaluate(() => {
      const D = window.READER;
      for (const lid of D.lineOrder) {
        if (D.lines[lid].status === "waiting") continue;
        let vars = 0, com = null;
        for (const nid in D.nodes) {
          const n = D.nodes[nid];
          if (n.line !== lid) continue;
          if (n.children.length > 1) vars++;
          if (n.comment && n.fen && n.parent && !com) com = nid;
        }
        if (vars >= 2 && com) return com;
      }
      return null;
    });
    await choose(p, id);
  }},
  // a long game stepped through with the right arrow: the current move stays in view
  ch05_step: { file: "ch05.html#line=L322", act: async (p) => { await stepRight(p, 29); } },
  // a comment whose moves the text recognition garbled
  ch02_comment: { file: "ch02.html#node=n272", act: async (p) => { await p.evaluate(() => window.scrollTo(0, 0)); } },
  // phone: a tapped move shows on the small board in the bar
  ch07_tap: { phone: true, file: "ch07.html#page=250", act: async (p) => {
    const sel = "#ov .mark.st-ok[data-node]";
    await p.evaluate((s) => document.querySelector(s).scrollIntoView({ block: "center" }), sel);
    await p.tap(sel);
  }},
  // phone: the panel in view, where the small board steps aside
  ch05_panel: { phone: true, file: "ch05.html#line=L322", act: async (p) => {
    await stepRight(p, 9);
    await p.evaluate(() => document.getElementById("panel").scrollIntoView({ block: "start" }));
  }},
  stage1: { file: "../stage1/inspect.html", act: async () => {} },
  stage1_table: { file: "../stage1/inspect.html", act: async (p) => {
    await p.evaluate(() => {
      const h = Array.from(document.querySelectorAll("h2")).find((x) => /Every board picture/.test(x.textContent));
      if (h) h.scrollIntoView();
    });
  }},
  stage1_numbers: { file: "../stage1/inspect.html", act: async (p) => {
    await p.evaluate(() => {
      const h = Array.from(document.querySelectorAll("h2")).find((x) => /Every diagram number/.test(x.textContent));
      if (h) h.scrollIntoView();
    });
  }},
};

(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
  const names = only.length ? only : Object.keys(scenes);
  for (const name of names) {
    const sc = scenes[name];
    const sizes = sc.phone ? [[390, 844]] : [[1280, 900], [390, 844]];
    for (const [w, h] of sizes) {
      for (const scheme of ["light", "dark"]) {
        const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: scheme,
          hasTouch: !!sc.phone, isMobile: !!sc.phone });
        const p = await ctx.newPage();
        const errors = [];
        p.on("pageerror", (e) => errors.push(String(e)));
        p.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
        const url = "file://" + path.resolve(R, sc.file.split("#")[0]) + (sc.file.includes("#") ? "#" + sc.file.split("#")[1] : "");
        await p.goto(url);
        await p.evaluate(() => { try { localStorage.clear(); } catch (e) { /* no storage */ } });
        await p.reload();
        await p.waitForTimeout(300);
        await sc.act(p);
        await p.waitForTimeout(400);
        const sw = await p.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
        const f = path.join(OUT, `${name}_${w}_${scheme}.png`);
        await p.screenshot({ path: f });
        console.log(path.relative(process.cwd(), f), "width", sw.join("/"), errors.length ? "ERRORS " + errors.join(" | ") : "");
        await ctx.close();
      }
    }
  }
  await browser.close();
})();
