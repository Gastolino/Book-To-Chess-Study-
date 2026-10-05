// The library: the user's own books, stored by the Cloudflare site (server/app.js).
//
// The app asks for /api/books when it starts. When the site answers, the
// start page becomes the library; when it does not (GitHub Pages, or the
// built site opened from a folder), LIB.on stays false and the app works as
// before, with nothing leaving the device.
//
// A book added to the library is read once in this browser, as before; the
// PDF, the finished reading (gzip), a cover picture and the book's title go
// to the server. Opening the book later, on any device, downloads the PDF and
// the reading and opens the book from them without reading it again, unless
// the reading was made by another version of the program or with another
// selection: then the book is read again and its reading replaced.
//
// Corrections, the selection and the place last read are written to the
// browser's storage as before and sent to the server as well, a moment after
// each change. A record "chessbook-library:<id>" in the browser's storage
// says when each was last changed here and when the server last took it, so
// that a change made offline, or one the server refused, is sent again later
// (when the page opens, when the browser comes online, and every half
// minute). On opening, the newer copy of the two wins.
//
// The page's own script (tools/build_web.py) calls LIB.message() with every
// message of the worker, LIB.fromReader() with every message of the reader,
// and LIB.add() for a book the user chooses.
const LIB = (() => {
  const api = { on: false, books: [], current: null, version: null, last: null };
  const PUSH_DELAY = 1500;        // milliseconds after a change before it is sent
  const POSITION_DELAY = 4000;
  const RETRY = 30000;
  const META = "chessbook-library:";
  let readyWaiters = [];
  let maxPdf = 95 * 1048576;

  const $ = (id) => document.getElementById(id);
  const say = (text, error) => status(text, error);

  // ---------------------------------------------------------------- the server
  async function call(method, path, body, headers) {
    const res = await fetch("api/" + path, {
      method, body, credentials: "same-origin", cache: "no-store",
      headers: Object.assign(body && typeof body === "string" ? { "content-type": "application/json" } : {},
                             headers || {}),
    });
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) throw new Error((data && data.error) || ("the server answered " + res.status));
    return data;
  }
  // An upload with its progress (fetch tells nothing of an upload's progress).
  function upload(method, path, body, headers, progress) {
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open(method, "api/" + path);
      for (const k in headers || {}) x.setRequestHeader(k, headers[k]);
      x.upload.onprogress = (e) => { if (e.lengthComputable && progress) progress(e.loaded / e.total); };
      x.onload = () => {
        let data = null;
        try { data = JSON.parse(x.responseText); } catch (e) { data = null; }
        if (x.status >= 200 && x.status < 300) resolve(data);
        else reject(new Error((data && data.error) || ("the server answered " + x.status)));
      };
      x.onerror = () => reject(new Error("the connection to the library failed"));
      x.send(body);
    });
  }
  // A download with its progress.
  async function download(path, progress) {
    const res = await fetch("api/" + path, { credentials: "same-origin" });
    if (!res.ok) throw new Error("the server answered " + res.status);
    const total = parseInt(res.headers.get("content-length") || "0", 10);
    if (!res.body || !total) return new Uint8Array(await res.arrayBuffer());
    const out = new Uint8Array(total);
    const reader = res.body.getReader();
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      out.set(value, got);
      got += value.length;
      if (progress) progress(got / total);
    }
    return got === total ? out : out.slice(0, got);
  }
  async function sha256(buffer) {
    const d = new Uint8Array(await crypto.subtle.digest("SHA-256", buffer));
    return Array.from(d, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  // ---------------------------------------------------------------- the library page
  function titleOf(b) {
    if (b.title) return b.title;
    // until the program has read the book: its file name, in words
    return b.fileName.replace(/\.pdf$/i, "").replace(/[_]+/g, " ").trim() || "A chess book";
  }
  function day(ms) {
    const d = new Date(ms), now = new Date();
    const start = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const days = Math.round((start(now) - start(d)) / 86400000);
    if (days === 0) return "today";
    if (days === 1) return "yesterday";
    const opts = { day: "numeric", month: "long" };
    if (d.getFullYear() !== now.getFullYear()) opts.year = "numeric";
    return d.toLocaleDateString("en-GB", opts);
  }
  function placeOf(b) {
    const local = meta(b.id).position;
    const server = b.position;
    const pos = local && (!server || local.updated > server.updated) ? local.data : server;
    return pos && pos.page ? pos : null;
  }
  function describe(b) {
    const parts = [];
    const pos = placeOf(b);
    if (b.pages) parts.push((pos ? "Page " + pos.page + " of " : "") + b.pages + (pos ? "" : " pages"));
    parts.push(b.opened ? "opened " + day(b.opened) : "added " + day(b.added));
    let text = parts.join(", ");
    text = text.charAt(0).toUpperCase() + text.slice(1);
    if (!b.reading) text += ". Not read yet";
    return text;
  }
  function render() {
    const list = $("books");
    list.innerHTML = "";
    $("libempty").hidden = api.books.length > 0;
    for (const b of api.books) {
      const li = document.createElement("li");
      li.className = "book";
      li.dataset.id = b.id;
      const open = document.createElement("button");
      open.type = "button";
      open.className = "open";
      const cover = document.createElement("span");
      cover.className = "cover";
      if (b.cover) {
        const img = document.createElement("img");
        img.className = "scan";
        img.alt = "";
        img.loading = "lazy";
        img.src = b.cover;
        cover.appendChild(img);
      }
      const words = document.createElement("span");
      words.className = "words";
      const t = document.createElement("span");
      t.className = "title";
      t.textContent = titleOf(b);
      const m = document.createElement("span");
      m.className = "meta";
      m.textContent = describe(b);
      words.append(t, m);
      open.append(cover, words);
      open.setAttribute("aria-label", "Open " + titleOf(b) + ". " + describe(b) + ".");
      open.addEventListener("click", () => api.open(b));
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "tb remove";
      rm.textContent = "Remove";
      rm.addEventListener("click", () => confirmRemove(li, b));
      li.append(open, rm);
      list.appendChild(li);
    }
  }
  function confirmRemove(li, b) {
    if (li.querySelector(".confirm")) return;
    const box = document.createElement("div");
    box.className = "confirm";
    box.setAttribute("role", "alertdialog");
    const q = document.createElement("span");
    q.textContent = "Remove this book, its stored reading and its corrections from the library?";
    const yes = document.createElement("button");
    yes.type = "button";
    yes.className = "tb yes";
    yes.textContent = "Remove the book";
    const no = document.createElement("button");
    no.type = "button";
    no.className = "tb";
    no.textContent = "Keep it";
    no.addEventListener("click", () => box.remove());
    yes.addEventListener("click", async () => {
      yes.disabled = no.disabled = true;
      try {
        await call("DELETE", "books/" + b.id);
        try { localStorage.removeItem(META + b.id); } catch (e) { /* no storage */ }
        api.books = api.books.filter((x) => x.id !== b.id);
        render();
        say("The book was removed from your library.");
      } catch (err) {
        yes.disabled = no.disabled = false;
        say("The book could not be removed: " + err.message, true);
      }
    });
    box.append(q, yes, no);
    li.appendChild(box);
    yes.focus();
  }
  function showLibrary() {
    document.body.classList.add("library");
    document.querySelector("#start h1").textContent = "Your library";
    $("intro").hidden = true;
    $("lib").hidden = false;
    $("drop").querySelector(".big").textContent = "Add a book";
    $("drop").querySelector(".small").textContent =
      "Choose a chess book PDF, or drop one here. The program reads it once and keeps it in your library.";
    $("drop").setAttribute("aria-label", "Add a chess book PDF to your library");
    $("another").textContent = "Library";
    render();
  }

  // ---------------------------------------------------------------- starting
  api.start = async function () {
    let data;
    try {
      const res = await fetch("api/books", { credentials: "same-origin", cache: "no-store" });
      if (!res.ok || !/json/.test(res.headers.get("content-type") || "")) return false;
      data = await res.json();
    } catch (e) {
      return false;
    }
    if (!data || !Array.isArray(data.books)) return false;
    api.on = true;
    api.books = data.books;
    if (data.maxPdf) maxPdf = data.maxPdf;
    showLibrary();
    flush();
    setInterval(flush, RETRY);
    window.addEventListener("online", flush);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") flush(true); });
    window.addEventListener("storage", (e) => { if (e.key) noticeKey(e.key); });
    return true;
  };
  function whenReady() {
    return ready ? Promise.resolve() : new Promise((resolve) => readyWaiters.push(resolve));
  }

  // ---------------------------------------------------------------- adding and opening
  api.add = async function (file) {
    if (busy) return;
    busy = true;
    $("bar").classList.add("on");
    try {
      say("Reading the file's fingerprint.");
      const buffer = await file.arrayBuffer();
      const id = await sha256(buffer);
      const known = api.books.find((b) => b.id === id);
      if (known) {
        busy = false;
        say("This book is already in your library.");
        return api.open(known);
      }
      if (buffer.byteLength > maxPdf) {
        busy = false;
        say("This book is larger than " + Math.round(maxPdf / 1048576) + " MB, the most the library can " +
            "store in one piece. The program reads it on this device, but it is not kept in your library.");
        api.current = null;
        return read(file, file.name);
      }
      let res;
      try {
        res = await upload("PUT", "books/" + id, buffer,
                           { "content-type": "application/pdf", "x-file-name": encodeURIComponent(file.name) },
                           (f) => say("Adding the book to your library: " + Math.round(100 * f) + "%."));
      } catch (err) {
        busy = false;
        say("The book could not be added to your library (" + err.message + "). The program reads it " +
            "on this device only.", true);
        api.current = null;
        return read(file, file.name);
      }
      api.books.unshift(res.book);
      api.current = { id, book: res.book, name: safeName(res.book.fileName), restored: false };
      busy = false;
      await whenReady();
      read(file, res.book.fileName);
    } catch (err) {
      busy = false;
      $("bar").classList.remove("on");
      say("The book could not be added: " + err.message, true);
    }
  };

  api.open = async function (b) {
    if (busy) return;
    busy = true;
    $("bar").classList.add("on");
    const name = safeName(b.fileName);
    api.current = { id: b.id, book: b, name, restored: false, position: null, t0: Date.now() };
    try {
      say("Downloading the book.");
      const pdf = await download("books/" + b.id + "/pdf",
                                 (f) => say("Downloading the book: " + Math.round(100 * f) + "%."));
      const file = new File([pdf], b.fileName, { type: "application/pdf" });
      await syncIn(b, name);
      const local = meta(b.id).position;
      api.current.position = local && (!b.position || local.updated > b.position.updated) ? local.data : b.position;
      call("PATCH", "books/" + b.id, JSON.stringify({ opened: Date.now() })).catch(() => {});
      if (!ready) say("The reader is still starting. The book opens in a moment.");
      await whenReady();
      if (b.reading && b.reading.version === api.version) {
        say("Downloading the program's reading of the book.");
        const reading = await download("books/" + b.id + "/reading",
          (f) => say("Downloading the program's reading of the book: " + Math.round(100 * f) + "%."));
        api.current.file = file;
        lastFile = file;
        lastName = b.fileName;
        say("Opening the book.");
        const bytes = pdf.buffer.slice(0);
        worker.postMessage({ type: "restore", name, bytes, reading: reading.buffer,
                             selection: storedSelection(name), corrections: storedCorrections(name) },
                           [bytes, reading.buffer]);
        return;
      }
      busy = false;
      if (b.reading) say("The program has changed since it read this book, so it reads the book again.");
      read(file, b.fileName, true);
    } catch (err) {
      busy = false;
      $("bar").classList.remove("on");
      say("The book could not be opened: " + err.message, true);
    }
  };

  // The top bar's words for a book opened from its stored reading.
  api.openedIn = function () {
    const t0 = api.current && api.current.t0;
    return t0 ? "opened from your library in " + Math.max(1, Math.round((Date.now() - t0) / 1000)) + " seconds"
              : "opened from your library";
  };

  function safeName(fileName) {
    return fileName.replace(/[^\w.\-]+/g, "_");
  }

  // ---------------------------------------------------------------- the worker
  // Returns true for the messages that only the library handles.
  api.message = function (m) {
    if (m.type === "ready") {
      api.version = m.version || null;
      const w = readyWaiters;
      readyWaiters = [];
      setTimeout(() => w.forEach((f) => f()), 0);
      return false;
    }
    if (!api.on) return false;
    const cur = api.current;
    if (m.type === "stale") {
      // the stored reading cannot be used: the book is read again, and its reading replaced
      busy = false;
      say(m.why + " The program reads the book again.");
      if (cur && cur.file) read(cur.file, cur.book.fileName, true);
      return true;
    }
    if (!cur) return false;
    if (m.type === "index") {
      cur.restored = !!m.restored;
      api.last = { restored: cur.restored, seconds: m.seconds || null };
      const b = cur.book;
      if (m.title && (m.title !== b.title || m.pages !== b.pages)) {
        b.title = m.title;
        b.pages = m.pages;
        call("PATCH", "books/" + cur.id, JSON.stringify({ title: m.title, pages: m.pages })).catch(() => {});
      }
      const mm = meta(cur.id);
      mm.name = cur.name;
      mm.pages = m.pages;
      saveMeta(cur.id, mm);
      seen(cur.id);
      if (!b.cover) worker.postMessage({ type: "cover", name: cur.name });
      const pos = cur.position;
      cur.position = null;
      if (pos && pos.chapter && pos.page) {
        // the place last read, on this device or another
        worker.postMessage({ type: "chapter", name: pos.chapter, hash: "#at=" + pos.page + ":" + (pos.node || ""),
                             small: window.matchMedia("(max-width: 700px)").matches });
      }
      return false;
    }
    if (m.type === "cover") {
      upload("PUT", "books/" + cur.id + "/cover", m.bytes, { "content-type": "image/jpeg" })
        .then((res) => { cur.book.cover = res.book.cover; }).catch(() => {});
      return true;
    }
    if (m.type === "done") {
      if (!m.restored) {
        $("note").textContent = "Saving the program's reading to your library.";
        worker.postMessage({ type: "save" });
      }
      return false;
    }
    if (m.type === "reading") {
      sendReading(cur, m, 0);
      return true;
    }
    return false;
  };
  function sendReading(cur, m, tries) {
    upload("PUT", "books/" + cur.id + "/reading", m.bytes,
           { "content-type": "application/octet-stream", "x-reading-version": m.version,
             "x-reading-size": String(m.size) })
      .then((res) => {
        cur.book.reading = res.book.reading;
        if (api.current === cur) status("The book is in your library: any device opens it without reading it again.");
      })
      .catch((err) => {
        if (tries < 4) setTimeout(() => sendReading(cur, m, tries + 1), 5000 * (tries + 1));
        else if (api.current === cur) {
          status("The program's reading could not be saved to your library (" + err.message + "). " +
                 "The book is read again the next time it opens.", true);
        }
      });
  }

  // ---------------------------------------------------------------- the reader
  api.fromReader = function (d) {
    if (!api.on || !api.current || !d) return;
    if (d.position) {
      const cur = api.current;
      if (!openChapter || !/^ch\d+\.html$/.test(openChapter)) return;
      const mm = meta(cur.id);
      mm.position = { data: { chapter: openChapter, page: d.position.page, node: d.position.node || null },
                      updated: Date.now(), sent: (mm.position && mm.position.sent) || 0 };
      saveMeta(cur.id, mm);
      schedule(POSITION_DELAY);
    }
    // a correction or a changed selection: the reader has written it to the storage already
    if (d.correct || d.selectionChanged) setTimeout(() => seen(api.current.id), 0);
  };

  // ---------------------------------------------------------------- sync
  function meta(id) {
    try {
      const v = JSON.parse(localStorage.getItem(META + id) || "null");
      if (v && typeof v === "object") return v;
    } catch (e) { /* no storage */ }
    return {};
  }
  function saveMeta(id, v) {
    try { localStorage.setItem(META + id, JSON.stringify(v)); } catch (e) { /* no storage */ }
  }
  function storageKey(mm, kind) {
    return mm.name && mm.pages ? "chessbook-" + kind + ":" + mm.name + ":" + mm.pages : null;
  }
  function localValue(key) {
    try { return key ? localStorage.getItem(key) : null; } catch (e) { return null; }
  }
  // Note what the browser holds now for the book: a value that differs from
  // the one seen last is a change made here, to be sent.
  function seen(id) {
    const mm = meta(id);
    let changed = false;
    for (const kind of ["corrections", "selection"]) {
      const key = storageKey(mm, kind);
      if (!key) continue;
      const v = localValue(key);
      const st = mm[kind] || { updated: 0, sent: 0, seen: null };
      if (v !== st.seen) {
        mm[kind] = { updated: Date.now(), sent: st.sent || 0, seen: v };
        changed = true;
      }
    }
    if (changed) {
      saveMeta(id, mm);
      schedule(PUSH_DELAY);
    }
  }
  function noticeKey(key) {
    const m = /^chessbook-(corrections|selection):/.exec(key);
    if (!m || !api.current) return;
    seen(api.current.id);
  }
  let timer = 0;
  function schedule(ms) {
    clearTimeout(timer);
    timer = setTimeout(() => flush(), ms);
  }
  // Send every change the server has not taken yet, for every book.
  let flushing = false;
  async function flush(leaving) {
    if (!api.on || flushing) return;
    flushing = true;
    try {
      const ids = [];
      try {
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i);
          if (k && k.startsWith(META)) ids.push(k.slice(META.length));
        }
      } catch (e) { /* no storage */ }
      for (const id of ids) {
        const mm = meta(id);
        for (const kind of ["corrections", "selection"]) {
          const st = mm[kind];
          if (!st || !(st.updated > (st.sent || 0))) continue;
          let data = null;
          try { data = st.seen ? JSON.parse(st.seen) : null; } catch (e) { data = null; }
          await send(id, kind, JSON.stringify({ data, updated: st.updated }), st.updated, leaving);
        }
        const p = mm.position;
        if (p && p.updated > (p.sent || 0)) {
          await send(id, "position", JSON.stringify({ position: p.data, updated: p.updated }), p.updated, leaving);
        }
      }
    } finally {
      flushing = false;
    }
  }
  async function send(id, kind, body, updated, leaving) {
    try {
      const res = await fetch("api/books/" + id + "/" + kind, {
        method: "PUT", body, keepalive: !!leaving && body.length < 60000, credentials: "same-origin",
        headers: { "content-type": "application/json" },
      });
      if (!res.ok && res.status !== 404) throw new Error(String(res.status));
      // taken (or the book is gone from the library): this change needs no more sending
      const mm = meta(id);
      if (mm[kind] && mm[kind].updated === updated) {
        mm[kind].sent = updated;
        saveMeta(id, mm);
      }
    } catch (e) {
      // offline or refused: the change stays marked, and goes with the next try
    }
  }
  // On opening: the newer of the browser's and the server's copy wins.
  async function syncIn(b, name) {
    const mm = meta(b.id);
    mm.name = name;
    if (b.pages) mm.pages = b.pages;
    saveMeta(b.id, mm);
    for (const kind of ["corrections", "selection"]) {
      let server;
      try { server = await call("GET", "books/" + b.id + "/" + kind); } catch (e) { continue; }
      const m2 = meta(b.id);
      const key = storageKey(m2, kind);
      if (!key) continue;
      const here = localValue(key);
      const st = m2[kind] || { updated: here === null ? 0 : 1, sent: 0, seen: here };
      if (st.seen !== here) {
        // changed here while no page watched it
        st.updated = Date.now();
        st.seen = here;
      }
      if (server.updated > st.updated) {
        const v = server.data === null ? null : JSON.stringify(server.data);
        try {
          if (v === null) localStorage.removeItem(key); else localStorage.setItem(key, v);
        } catch (e) { /* no storage */ }
        m2[kind] = { updated: server.updated, sent: server.updated, seen: v };
      } else {
        if (st.updated > server.updated && here !== null && st.updated === 1) st.updated = Date.now();
        m2[kind] = st;
      }
      saveMeta(b.id, m2);
    }
    flush();
  }

  return api;
})();
