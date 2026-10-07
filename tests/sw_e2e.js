// End-to-end test of the service worker (web/sw.js) in Chromium: the
// libraries the app loads at every start come from the device after the
// first visit (tests/test_app_e2e.py serves the site and runs this).
//
// Usage: NODE_PATH=/opt/node22/lib/node_modules node tests/sw_e2e.js SITE_URL PROFILE_DIR
//
// The first visits load the libraries from the network and the service
// worker keeps them (on the very first, the worker waits up to two seconds
// for it, and a busy machine may start before); by the third visit (the
// browser started again on the same profile) Pyodide's files and the wheels
// come from the device, and the page, the app's scripts and app.zip from the
// network when it answers; and with the network cut off, the app opens all the
// same from the copies kept on the device. Prints one
// JSON object with the results; the exit code is 1 when a check fails.
const { chromium } = require("playwright");
const fs = require("fs");

const [siteUrl, profile] = process.argv.slice(2);
const out = { ok: false, checks: [], errors: [], timings: {} };
function check(name, cond, detail) {
  out.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) throw new Error("check failed: " + name + (detail !== undefined ? " (" + JSON.stringify(detail).slice(0, 800) + ")" : ""));
}
const EXE = process.env.CHROMIUM || "/opt/pw-browsers/chromium";
const LAUNCH = fs.existsSync(EXE) ? { executablePath: EXE } : {};

async function visit(offline) {
  const ctx = await chromium.launchPersistentContext(profile, LAUNCH);
  const page = ctx.pages()[0] || await ctx.newPage();
  if (offline) await ctx.setOffline(true);
  const seen = [];
  ctx.on("requestfinished", async (req) => {
    const res = await req.response().catch(() => null);
    if (res) seen.push({ url: req.url(), sw: res.fromServiceWorker() });
  });
  page.on("pageerror", (e) => out.errors.push(String(e)));
  const t = Date.now();
  await page.goto(siteUrl);
  await page.waitForFunction(() => typeof ready !== "undefined" && ready === true, null, { timeout: 300000 });
  const secs = (Date.now() - t) / 1000;
  if (offline) {
    // the library shows, offline
    await page.waitForFunction(() => document.body.classList.contains("library") &&
      !document.getElementById("lib").hidden, null, { timeout: 60000 });
  }
  // the board libraries load after the worker is ready
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(8000);
  const cached = await page.evaluate(async () => {
    const names = (await caches.keys()).filter((n) => n.startsWith("chessbook-libs-"));
    const urls = [];
    for (const n of names) for (const r of await (await caches.open(n)).keys()) urls.push(r.url);
    return { names, urls };
  });
  await ctx.close();
  return { secs, seen, cached };
}

(async () => {
  try {
    const one = await visit();
    out.timings["first visit, until ready (s)"] = one.secs;
    const two0 = await visit();
    out.timings["second visit, until ready (s)"] = two0.secs;
    check("one cache of libraries", two0.cached.names.length === 1, two0.cached.names);
    const kept = two0.cached.urls;
    check("the cache holds the wheels and Pyodide's files",
          kept.some((u) => /\/wheels\/pymupdf-.*\.whl$/.test(u)) && kept.some((u) => /\/wheels\/chess-.*\.whl$/.test(u)) &&
          kept.some((u) => /\/pyodide\/pyodide\.asm\.wasm$/.test(u)) && kept.some((u) => /\/pyodide\/opencv/.test(u)), kept);
    check("nothing else is kept", kept.every((u) => /\/(wheels|pyodide)\//.test(u)), kept);

    const two = await visit();
    out.timings["third visit, until ready (s)"] = two.secs;
    const libs = two.seen.filter((r) => /\/(wheels|pyodide)\//.test(r.url));
    check("the third visit takes the libraries from the device", libs.length > 4 && libs.every((r) => r.sw), libs);
    const rest = two.seen.filter((r) => /\/(index\.html|worker\.js|library\.js|app\.zip)$|\/$/.test(r.url));
    check("the page, the scripts and app.zip come from the network, through the service worker",
          rest.length >= 3 && rest.every((r) => r.sw), rest);
    const off = await visit(true);
    out.timings["offline visit, until ready (s)"] = off.secs;
    check("with the network cut off the app opens from the device", off.secs > 0, off.secs);
    check("no page errors", out.errors.length === 0, out.errors);
    out.ok = true;
  } catch (e) {
    out.failure = String(e && e.stack || e);
  }
  console.log(JSON.stringify(out));
  process.exit(out.ok ? 0 : 1);
})();
