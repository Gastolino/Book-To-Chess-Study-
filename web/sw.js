// The app's service worker: it keeps the libraries the reader loads at every
// start (Pyodide and its packages, the PyMuPDF and python-chess wheels) in the
// browser's Cache Storage, so that they come from the device instead of the
// network. Safari drops large files from its ordinary cache within days; a
// service worker's cache stays with the site's other storage. Only files that
// never change under their name are kept (Pyodide's folder names its version,
// a wheel's name its version); everything else (the page, the app's scripts,
// app.zip) goes to the network as before. A new set of libraries comes with a
// new cache name, and the old cache is removed.
const CACHE = "__CACHE__";
// the URL prefixes of the files that never change
const KEEP = __KEEP__;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const name of await caches.keys())
      if (name.startsWith("chessbook-libs-") && name !== CACHE) await caches.delete(name);
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || !KEEP.some((p) => req.url.startsWith(p))) return;
  e.respondWith((async () => {
    let cache = null;
    try { cache = await caches.open(CACHE); } catch (err) { return fetch(req); }
    const hit = await cache.match(req.url);
    if (hit) return hit;
    const res = await fetch(req);
    // a whole answer only (not a range, not an error), kept by its URL
    if (res.ok && res.status === 200) cache.put(req.url, res.clone()).catch(() => {});
    return res;
  })());
});
