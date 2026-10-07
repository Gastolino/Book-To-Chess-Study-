// The app's service worker: it keeps the libraries the reader loads at every
// start (Pyodide and its packages, the PyMuPDF and python-chess wheels) in the
// browser's Cache Storage, so that they come from the device instead of the
// network. Safari drops large files from its ordinary cache within days; a
// service worker's cache stays with the site's other storage. Only files that
// never change under their name are kept this way (Pyodide's folder names its
// version, a wheel's name its version); a new set of libraries comes with a new
// cache name, and the old cache is removed.
//
// The app's own files (the page, its scripts, app.zip, the icons) change with
// each version of the app: they come from the network when it answers, and a
// copy is kept (APP), which answers when the network does not, or not within
// three seconds. The app then opens offline, with the books of the library on
// the device (the engine keeps itself in IndexedDB).
const CACHE = "__CACHE__";
const APP = "chessbook-app";
const SLOW = 3000;
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
// the app's own files: the network first, the copy kept when it fails or is slow
async function appFile(req) {
  let cache = null;
  try { cache = await caches.open(APP); } catch (err) { return fetch(req); }
  const key = req.mode === "navigate" ? new URL("./", self.registration.scope).href : req.url.split("#")[0];
  const net = fetch(req).then((res) => {
    if (res.ok && res.status === 200 && res.type === "basic") cache.put(key, res.clone()).catch(() => {});
    return res;
  });
  const kept = await cache.match(key);
  if (!kept) return net;
  const late = new Promise((resolve) => setTimeout(() => resolve(kept), SLOW));
  return Promise.race([net.catch(() => kept), late]);
}
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  if (!KEEP.some((p) => req.url.startsWith(p))) {
    // (the service worker's own file and other sites go to the network as they are)
    if (req.url.startsWith(self.registration.scope) && !/\/sw\.js$/.test(new URL(req.url).pathname))
      e.respondWith(appFile(req));
    return;
  }
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
