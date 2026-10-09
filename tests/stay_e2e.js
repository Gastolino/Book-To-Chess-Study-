// End-to-end test of the reader staying on the line being read, in Chromium (Playwright).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/stay_e2e.js CHAPTER_HTML
//
// Opens a chapter reader of a generated book (tests/test_reader.py builds it) whose game
// "1.e4 c5 2.Nf3 d6 3.Bb5+" is followed by a note that repeats "1.e4 c5 2.Nf3" before it
// branches off with "Nc6 3.Bb5 d6", and whose game goes on over the next two pages. Checks:
// a tap on the repeated c5 lights that box alone; from the note's Nc6, back, back, forward and
// forward come back to Nc6, one box lit at each step, in the note; forward from the game's Nf3
// goes to its d6; after turning to a later page the arrows do not go back to the page before;
// the move list and Home keep the page; the address names the box and gives it back; and every
// box, tapped and then stepped from with each arrow, lights one box at most and never turns the
// page against the arrow. No console errors. Prints one JSON object; the exit code is 1 when a
// check fails.
const { chromium } = require("playwright");
const path = require("path");

const [file] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], walk: null };
function check(name, cond, detail) {
  out.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed: " + name + (detail ? " (" + JSON.stringify(detail) + ")" : ""));
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") out.errors.push(m.text()); });
  page.on("pageerror", (e) => out.errors.push(String(e)));
  const url = "file://" + path.resolve(file);
  // the reader's place: its page, move and the boxes lit
  const st = () => page.evaluate(() => ({ page: window.readerState.page, node: window.readerState.nodeId,
    lit: [...document.querySelectorAll("#ov .mark.current")].map((e) => +e.dataset.mark), hash: location.hash }));
  const goPage = async (p) => {
    await page.evaluate((p) => { location.hash = "#page=" + p; }, p);
    await page.waitForFunction((p) => window.readerState.page === p, p);
  };
  const tap = async (i) => { await page.click("#ov .mark[data-mark='" + i + "']"); return st(); };
  const press = async (id) => { await page.click("#" + id); return st(); };
  try {
    await page.goto(url);
    await page.waitForFunction(() => window.READER && window.readerState && window.readerState.page);
    // the boxes of the page with the game and the note, in reading order
    const P = await page.evaluate(() => {
      const D = window.READER;
      for (const p of Object.keys(D.pages).map(Number).sort((a, b) => a - b)) {
        const ms = D.pages[p].marks;
        const raws = ms.map((m) => m.raw);
        if (raws.filter((r) => r === "c5").length === 2) {
          const at = (raw, k) => raws.reduce((acc, r, i) => (r === raw ? acc.concat([i]) : acc), [])[k];
          return { page: p, n: ms.length, marks: ms.map((m) => ({ raw: m.raw, node: m.node, key: m.key })),
                   c5: at("c5", 0), c5b: at("c5", 1), nf3: at("Nf3", 0), nf3b: at("Nf3", 1), d6: at("d6", 0),
                   nc6: at("Nc6", 0), e4b: at("e4", 1) };
        }
      }
      return null;
    });
    check("the page prints the game and the note that repeats its first moves", P && P.nc6 !== undefined &&
          P.marks[P.c5].node === P.marks[P.c5b].node && P.marks[P.nf3].node === P.marks[P.nf3b].node &&
          P.c5b > P.d6 && P.nc6 === P.nf3b + 1, P);
    await goPage(P.page);

    // a tap on the note's c5 lights that box only, and the page stays
    let s = await tap(P.c5b);
    check("a tap on the repeated c5 lights that box alone", s.page === P.page && s.lit.join() === String(P.c5b) &&
          s.node === P.marks[P.c5b].node, s);
    s = await tap(P.c5);
    check("a tap on the game's c5 lights that box alone", s.lit.join() === String(P.c5), s);

    // from the note's Nc6: back, back, forward, forward stay in the note's sentence
    s = await tap(P.nc6);
    const seen = [];
    for (const id of ["bback", "bback", "bfwd", "bfwd"]) seen.push(await press(id));
    check("from the note's Nc6, back and back light the note's Nf3 and c5",
          seen[0].lit.join() === String(P.nf3b) && seen[1].lit.join() === String(P.c5b), seen);
    check("forward and forward come back to the note's Nf3 and its Nc6",
          seen[2].lit.join() === String(P.nf3b) && seen[3].lit.join() === String(P.nc6) &&
          seen[3].node === P.marks[P.nc6].node && seen.every((x) => x.page === P.page), seen);
    // the arrow keys do the same
    await page.keyboard.press("ArrowLeft");
    s = await st();
    check("the left arrow key steps back to the note's Nf3", s.lit.join() === String(P.nf3b), s);
    await page.keyboard.press("ArrowRight");
    s = await st();
    check("the right arrow key steps to the note's Nc6", s.lit.join() === String(P.nc6), s);

    // forward from the game's Nf3 goes on in the game: d6
    await tap(P.nf3);
    s = await press("bfwd");
    check("forward from the game's Nf3 goes to the game's d6", s.lit.join() === String(P.d6) &&
          s.node === P.marks[P.d6].node, s);

    // the address names the box: the note's c5 again, from the address alone
    await tap(P.c5b);
    s = await st();
    const key = P.marks[P.c5b].key;
    check("the address names the page, the move and the box", s.hash === "#at=" + P.page + ":" + s.node + ":" +
          encodeURIComponent(key), { s, key });
    await page.goto("about:blank");
    await page.goto(url + s.hash);
    await page.waitForFunction(() => window.readerState && window.readerState.page);
    s = await st();
    check("the address gives back the box: the note's c5, lit alone", s.page === P.page && s.lit.join() === String(P.c5b), s);
    // the address of before ("#at=PAGE:NODE") lights one box of the move on that page
    await page.goto("about:blank");
    await page.goto(url + "#at=" + P.page + ":" + P.marks[P.c5b].node);
    await page.waitForFunction(() => window.readerState && window.readerState.page);
    s = await st();
    check("an address without a box lights one box of its move on its page", s.page === P.page && s.lit.length === 1 &&
          P.marks[s.lit[0]].node === P.marks[P.c5b].node, s);
    // a move id that is not printed on the page asked for: the page wins
    const far = P.marks[P.c5].node;
    await page.goto("about:blank");
    await page.goto(url + "#at=" + (P.page + 2) + ":" + far + ":" + encodeURIComponent(key));
    await page.waitForFunction(() => window.readerState && window.readerState.page);
    s = await st();
    check("an address whose box and move are printed on another page shows its own page", s.page === P.page + 2 &&
          s.node !== far, s);

    // after turning to later pages, the arrows do not go back to the page left
    await goPage(P.page);
    await tap(P.nc6);
    await page.click("#nextpage");
    await page.waitForFunction((p) => window.readerState.page === p + 1, P.page);
    await page.click("#nextpage");
    await page.waitForFunction((p) => window.readerState.page === p + 2, P.page);
    s = await press("bfwd");
    check("after turning two pages, forward stays on the page shown", s.page === P.page + 2 && s.lit.length === 1, s);
    await goPage(P.page);
    await tap(P.nc6);
    await page.click("#nextpage");
    await page.waitForFunction((p) => window.readerState.page === p + 1, P.page);
    await page.keyboard.press("ArrowLeft");
    s = await st();
    check("after turning a page, back does not go to the page left", s.page === P.page + 1, s);

    // the move list keeps the page when the move is printed on it, and lights one box
    await goPage(P.page);
    await tap(P.nc6);
    await page.click("#tree .mv[data-node='" + P.marks[P.c5].node + "']");
    s = await st();
    check("a move chosen in the move list lights one of its boxes on this page", s.page === P.page && s.lit.length === 1 &&
          P.marks[s.lit[0]].node === P.marks[P.c5].node, s);
    // Home keeps the page; End goes forward only
    await goPage(P.page + 1);
    await tap(0);
    s = await press("bstart");
    check("Home goes to the start position and keeps the page", s.page === P.page + 1 && s.lit.length === 0 &&
          (await page.evaluate(() => window.READER.nodes[window.readerState.nodeId].parent === null)), s);
    s = await press("bend");
    check("End goes to the end of the line, forward", s.page >= P.page + 1 && s.lit.length === 1 &&
          (await page.evaluate(() => window.READER.nodes[window.readerState.nodeId].children.length === 0)), s);

    // the walk: every box tapped, then each arrow from it
    const walk = await page.evaluate(async () => {
      const D = window.READER;
      const goto = (p) => new Promise((r) => {
        if (window.readerState.page === p) { r(); return; }
        window.addEventListener("hashchange", () => r(), { once: true });
        location.hash = "#page=" + p;
      });
      const cur = () => [...document.querySelectorAll("#ov .mark.current")].map((e) => +e.dataset.mark);
      const bad = [];
      let boxes = 0;
      for (const p of Object.keys(D.pages).map(Number).sort((a, b) => a - b)) {
        for (let i = 0; i < D.pages[p].marks.length; i++) {
          if (!D.pages[p].marks[i].node) continue;
          boxes++;
          for (const dir of ["tap", "bfwd", "bback"]) {
            await goto(p);
            document.querySelector("#ov .mark[data-mark='" + i + "']").click();
            if (dir !== "tap") document.getElementById(dir).click();
            const s = { page: window.readerState.page, lit: cur() };
            if (dir === "tap" && (s.page !== p || s.lit.join() !== String(i))) bad.push([p, i, dir, s]);
            if (s.lit.length > 1) bad.push([p, i, dir, s]);
            if (dir === "bfwd" && s.page < p) bad.push([p, i, dir, s]);
            if (dir === "bback" && s.page > p) bad.push([p, i, dir, s]);
          }
        }
      }
      return { boxes, bad };
    });
    out.walk = walk;
    check("every box: a tap lights it alone, and the arrows light one box at most and turn the page only their way",
          walk.boxes > 20 && walk.bad.length === 0, walk);
    check("no console errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (err) {
    out.failure = String(err && err.message ? err.message : err);
  }
  await browser.close();
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
