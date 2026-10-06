// The library: the user's own books, kept either by the Cloudflare site
// (server/app.js) or in this browser, on this device.
//
// The app asks for /api/books when it starts. When the site answers, the
// library is the server's ("server"); when it does not (GitHub Pages, or the
// built site opened from a folder), the library lives in the browser's
// IndexedDB on this device ("device"). The library page, adding, opening
// and removing a book are the same code for both: only the store differs
// (serverStore and deviceStore below). When the browser keeps no IndexedDB
// either (some private windows), LIB.on stays false and the app reads books
// as before, keeping nothing.
//
// A book added to the library is read once in this browser, as before; the
// PDF, the finished reading (gzip), a cover picture and the book's title go
// to the store. Opening the book later downloads (or loads) the PDF and the
// reading and opens the book from them without reading it again, unless the
// reading was made by another version of the program or with another
// selection: then the book is read again and its reading replaced.
//
// Corrections, the selection, the bookmarks and the place last read are
// written to the browser's storage (localStorage) as before. With the server they are sent
// to it as well, a moment after each change. A record
// "chessbook-library:<id>" in the browser's storage says when each was last
// changed here and when the server last took it, so that a change made
// offline, or one the server refused, is sent again later (when the page
// opens, when the browser comes online, and every half minute). On opening,
// the newer copy of the two wins. On the device, the corrections and the
// selection stay in localStorage, and the place goes into the book's record.
//
// "Save to Files" writes one book as a single file (<title>.chessbook, a zip
// holding book.json, book.pdf, reading.gz and cover.jpg): the share sheet
// on an iPhone or iPad (Save to Files, AirDrop), a download elsewhere.
// "Add a book" takes such a file as well as a PDF, and restores the book
// with its reading, corrections, selection, bookmarks and place; a book the
// library holds already keeps the newer of the two sets of corrections (and
// of bookmarks).
//
// The page's own script (tools/build_web.py) calls LIB.message() with every
// message of the worker, LIB.fromReader() with every message of the reader,
// and LIB.add() for a file the user chooses.
const LIB = (() => {
  const api = { on: false, kind: null, books: [], current: null, version: null, last: null,
                persisted: null };
  const PUSH_DELAY = 1500;        // milliseconds after a change before it is sent
  const POSITION_DELAY = 4000;
  const RETRY = 30000;
  const META = "chessbook-library:";
  const HINT = "chessbook-homehint";
  // what the reader keeps in localStorage under "chessbook-<kind>:<file>:<pages>"
  const KINDS = ["corrections", "selection", "bookmarks"];
  let readyWaiters = [];
  let store = null;

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

  // The Cloudflare site's library. Every method returns a promise; a book is
  // the server's record of it (server/app.js, publicBook).
  const serverStore = {
    kind: "server",
    syncs: true,                  // corrections, the selection and the bookmarks go to the server too
    maxPdf: 95 * 1048576,
    async probe() {
      let data;
      try {
        const res = await fetch("api/books", { credentials: "same-origin", cache: "no-store" });
        if (!res.ok || !/json/.test(res.headers.get("content-type") || "")) return null;
        data = await res.json();
      } catch (e) {
        return null;
      }
      if (!data || !Array.isArray(data.books)) return null;
      if (data.maxPdf) serverStore.maxPdf = data.maxPdf;
      return data.books;
    },
    async add(id, buffer, fileName, progress) {
      const res = await upload("PUT", "books/" + id, buffer,
                               { "content-type": "application/pdf", "x-file-name": encodeURIComponent(fileName) },
                               (f) => progress("Adding the book to your library: " + Math.round(100 * f) + "%."));
      return res.book;
    },
    update: (id, fields) => call("PATCH", "books/" + id, JSON.stringify(fields)),
    remove: (id) => call("DELETE", "books/" + id),
    pdf: (id, progress) => download("books/" + id + "/pdf",
                                    (f) => progress("Downloading the book: " + Math.round(100 * f) + "%.")),
    reading: (id, progress) => download("books/" + id + "/reading",
      (f) => progress("Downloading the program's reading of the book: " + Math.round(100 * f) + "%.")),
    async putReading(id, bytes, version, size) {
      const res = await upload("PUT", "books/" + id + "/reading", bytes,
                               { "content-type": "application/octet-stream", "x-reading-version": version,
                                 "x-reading-size": String(size) });
      return res.book;
    },
    async putCover(id, bytes) {
      return (await upload("PUT", "books/" + id + "/cover", bytes, { "content-type": "image/jpeg" })).book;
    },
    getData: (id, kind) => call("GET", "books/" + id + "/" + kind),
    putData: (id, kind, data, updated, leaving) =>
      send(id, kind, JSON.stringify({ data, updated }), leaving),
    putPosition: (id, position, updated, leaving) =>
      send(id, "position", JSON.stringify({ position, updated }), leaving),
  };
  // Resolves when the server took the change, or when the book is gone from
  // the library (the change needs no more sending); rejects otherwise.
  async function send(id, kind, body, leaving) {
    const res = await fetch("api/books/" + id + "/" + kind, {
      method: "PUT", body, keepalive: !!leaving && body.length < 60000, credentials: "same-origin",
      headers: { "content-type": "application/json" },
    });
    if (!res.ok && res.status !== 404) throw new Error(String(res.status));
  }

  // ---------------------------------------------------------------- the device
  // The library in this browser's IndexedDB "chessbook-library": the store
  // "books" holds one record per book (keyed by the PDF's SHA-256, as on the
  // server: title, file name, page count, size, dates, the place last read,
  // the stored reading's version and sizes, and the cover picture as a
  // Blob); the store "files" holds the PDF ("<id>:pdf") and the gzipped
  // reading ("<id>:reading") as Blobs, apart from the records so that the
  // library page loads without them. IndexedDB keeps large Blobs in every
  // current browser, Safari on iPhone and iPad included, and one transaction
  // writes a book's file and its record together.
  function deviceStore() {
    const NAME = "chessbook-library";
    let dbp = null;
    const covers = {};            // object URLs of the cover pictures, by book id
    function open() {
      if (!dbp) {
        dbp = new Promise((resolve, reject) => {
          const req = indexedDB.open(NAME, 1);
          req.onupgradeneeded = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains("books")) db.createObjectStore("books", { keyPath: "id" });
            if (!db.objectStoreNames.contains("files")) db.createObjectStore("files");
          };
          req.onsuccess = () => {
            const db = req.result;
            // another page deletes or upgrades the database: let it
            db.onversionchange = () => { db.close(); dbp = null; };
            db.onclose = () => { dbp = null; };
            resolve(db);
          };
          req.onerror = () => { dbp = null; reject(req.error || new Error("the browser's storage cannot be opened")); };
        });
      }
      return dbp;
    }
    // One transaction over the stores names: fn(stores, keep) queues its
    // requests and keep(value) sets what the promise gives once the
    // transaction is complete. Safari closes the connection of a page left
    // in the background: the transaction is tried once more on a new one.
    async function tx(names, mode, fn, again) {
      const db = await open();
      try {
        return await new Promise((resolve, reject) => {
          const t = db.transaction(names, mode);
          let value;
          const stores = {};
          for (const n of names) stores[n] = t.objectStore(n);
          fn(stores, (v) => { value = v; });
          t.oncomplete = () => resolve(value);
          t.onabort = () => reject(t.error || new DOMException("The storage refused the change.", "AbortError"));
        });
      } catch (e) {
        if (!again && e && e.name === "InvalidStateError") {
          dbp = null;
          return tx(names, mode, fn, true);
        }
        throw e;
      }
    }
    function pub(rec) {
      if (!rec) return null;
      const b = Object.assign({}, rec);
      delete b.coverBlob;
      if (rec.coverBlob) {
        const c = covers[rec.id];
        if (!c || c.updated !== rec.coverUpdated) {
          if (c) URL.revokeObjectURL(c.url);
          covers[rec.id] = { url: URL.createObjectURL(rec.coverBlob), updated: rec.coverUpdated };
        }
        b.cover = covers[rec.id].url;
      } else b.cover = null;
      return b;
    }
    // change(rec) alters the record of book id in place; resolves with the book
    function change(id, fn, extra) {
      return tx(["books", "files"], "readwrite", (s, keep) => {
        const q = s.books.get(id);
        q.onsuccess = () => {
          const rec = q.result;
          if (!rec) return;
          fn(rec);
          s.books.put(rec);
          keep(rec);
        };
        if (extra) extra(s);
      }).then(pub);
    }
    async function file(id, kind) {
      const blob = await tx(["files"], "readonly", (s, keep) => {
        const q = s.files.get(id + ":" + kind);
        q.onsuccess = () => keep(q.result);
      });
      if (!blob) throw new Error(kind === "pdf" ? "the book's file is missing from this device"
                                                : "the stored reading is missing from this device");
      return new Uint8Array(await blob.arrayBuffer());
    }
    return {
      kind: "device",
      syncs: false,               // corrections, the selection and the bookmarks stay in localStorage
      maxPdf: Infinity,
      async list() {
        const recs = await tx(["books"], "readonly", (s, keep) => {
          const q = s.books.getAll();
          q.onsuccess = () => keep(q.result);
        });
        return (recs || []).sort((a, b) => (b.opened || b.added) - (a.opened || a.added)).map(pub);
      },
      add(id, buffer, fileName) {
        return tx(["books", "files"], "readwrite", (s, keep) => {
          const q = s.books.get(id);
          q.onsuccess = () => {
            if (q.result) { keep(q.result); return; }
            const rec = { id, fileName, title: null, pages: null, size: buffer.byteLength, added: Date.now(),
                          opened: null, position: null, reading: null, coverBlob: null, coverUpdated: null };
            s.files.put(new Blob([buffer], { type: "application/pdf" }), id + ":pdf");
            s.books.put(rec);
            keep(rec);
          };
        }).then(pub);
      },
      update(id, fields) {
        return change(id, (rec) => {
          if (typeof fields.title === "string") rec.title = fields.title.slice(0, 500);
          if (Number.isInteger(fields.pages)) rec.pages = fields.pages;
          if (Number.isFinite(fields.opened)) rec.opened = Math.max(rec.opened || 0, fields.opened);
        });
      },
      remove(id) {
        return tx(["books", "files"], "readwrite", (s) => {
          s.books.delete(id);
          s.files.delete(id + ":pdf");
          s.files.delete(id + ":reading");
        }).then(() => {
          if (covers[id]) { URL.revokeObjectURL(covers[id].url); delete covers[id]; }
        });
      },
      pdf: (id) => file(id, "pdf"),
      reading: (id) => file(id, "reading"),
      putReading(id, bytes, version, size) {
        return change(id, (rec) => {
          rec.reading = { version, size, stored: bytes.byteLength, updated: Date.now() };
        }, (s) => s.files.put(new Blob([bytes], { type: "application/gzip" }), id + ":reading"));
      },
      putCover(id, bytes) {
        return change(id, (rec) => {
          rec.coverBlob = new Blob([bytes], { type: "image/jpeg" });
          rec.coverUpdated = Date.now();
        });
      },
      putPosition(id, position, updated) {
        return change(id, (rec) => {
          if (rec.position && rec.position.updated > updated) return;
          rec.position = Object.assign({}, position, { updated });
          rec.opened = Math.max(rec.opened || 0, updated);
        });
      },
    };
  }

  async function sha256(buffer) {
    const d = new Uint8Array(await crypto.subtle.digest("SHA-256", buffer));
    return Array.from(d, (b) => b.toString(16).padStart(2, "0")).join("");
  }
  function tooFull(err) {
    return !!err && (err.name === "QuotaExceededError" || /quota|space|full/i.test(String(err.message || err)));
  }
  function mb(bytes) {
    const m = bytes / 1048576;
    return (m < 10 ? m.toFixed(1) : String(Math.round(m))) + " MB";
  }

  // ---------------------------------------------------------------- the book file (.chessbook)
  // A zip without compression (the PDF and the reading are compressed
  // already), which any unzip program opens as well.
  const CRC = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = CRC[(c ^ bytes[i]) & 255] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }
  function zip(entries) {
    const enc = new TextEncoder(), parts = [], central = [];
    const d = new Date();
    const time = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
    const date = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
    let offset = 0;
    for (const e of entries) {
      const name = enc.encode(e.name), crc = crc32(e.bytes), size = e.bytes.length;
      const h = new DataView(new ArrayBuffer(30));
      h.setUint32(0, 0x04034b50, true);
      h.setUint16(4, 20, true);
      h.setUint16(6, 0x0800, true);           // the name is UTF-8
      h.setUint16(10, time, true);
      h.setUint16(12, date, true);
      h.setUint32(14, crc, true);
      h.setUint32(18, size, true);
      h.setUint32(22, size, true);
      h.setUint16(26, name.length, true);
      parts.push(h.buffer, name, e.bytes);
      const c = new DataView(new ArrayBuffer(46));
      c.setUint32(0, 0x02014b50, true);
      c.setUint16(4, 20, true);
      c.setUint16(6, 20, true);
      c.setUint16(8, 0x0800, true);
      c.setUint16(12, time, true);
      c.setUint16(14, date, true);
      c.setUint32(16, crc, true);
      c.setUint32(20, size, true);
      c.setUint32(24, size, true);
      c.setUint16(28, name.length, true);
      c.setUint32(42, offset, true);
      central.push(c.buffer, name);
      offset += 30 + name.length + size;
    }
    const cd = central.reduce((s, p) => s + p.byteLength, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, entries.length, true);
    end.setUint16(10, entries.length, true);
    end.setUint32(12, cd, true);
    end.setUint32(16, offset, true);
    return new Blob(parts.concat(central, [end.buffer]), { type: "application/zip" });
  }
  // The files of a zip, by name (without folders); stored or deflated.
  async function unzip(buffer) {
    const v = new DataView(buffer), u8 = new Uint8Array(buffer), dec = new TextDecoder();
    let e = -1;
    for (let i = buffer.byteLength - 22; i >= Math.max(0, buffer.byteLength - 22 - 65535); i--) {
      if (v.getUint32(i, true) === 0x06054b50) { e = i; break; }
    }
    if (e < 0) throw new Error("it is not a book file saved from the library");
    const count = v.getUint16(e + 10, true), out = {};
    let p = v.getUint32(e + 16, true);
    for (let k = 0; k < count; k++) {
      if (v.getUint32(p, true) !== 0x02014b50) throw new Error("the file is damaged");
      const method = v.getUint16(p + 10, true), crc = v.getUint32(p + 16, true);
      const size = v.getUint32(p + 20, true), nlen = v.getUint16(p + 28, true);
      const elen = v.getUint16(p + 30, true), clen = v.getUint16(p + 32, true), off = v.getUint32(p + 42, true);
      const name = dec.decode(u8.subarray(p + 46, p + 46 + nlen)).split("/").pop();
      const start = off + 30 + v.getUint16(off + 26, true) + v.getUint16(off + 28, true);
      let data = u8.subarray(start, start + size);
      if (method === 8) {
        data = new Uint8Array(await new Response(new Blob([data]).stream()
          .pipeThrough(new DecompressionStream("deflate-raw"))).arrayBuffer());
      } else if (method !== 0) throw new Error("the file is packed in a way the program does not read");
      if (name && crc32(data) !== crc) throw new Error("the file is damaged");
      if (name) out[name] = data;
      p += 46 + nlen + elen + clen;
    }
    return out;
  }
  function fileTitle(b) {
    return titleOf(b).replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) ||
      "Chess book";
  }
  // What the browser holds for book b of the kind "corrections", "selection"
  // or "bookmarks": {data, updated} (updated is 0 when it holds nothing).
  function localData(b, kind) {
    const mm = meta(b.id);
    const key = storageKey({ name: mm.name || safeName(b.fileName), pages: b.pages || mm.pages }, kind);
    const v = localValue(key);
    let data = null;
    try { data = v ? JSON.parse(v) : null; } catch (e) { data = null; }
    const st = mm[kind];
    const updated = v === null ? (st && st.seen === null ? st.updated || 0 : 0)
                               : st && st.seen === v ? st.updated : Date.now();
    return { data, updated, text: v, key };
  }
  async function bookFile(b) {
    const pdf = await store.pdf(b.id, () => {});
    let reading = null;
    if (b.reading) {
      try { reading = await store.reading(b.id, () => {}); } catch (e) { reading = null; }
    }
    let cover = null;
    if (b.cover) {
      try { cover = new Uint8Array(await (await fetch(b.cover)).arrayBuffer()); } catch (e) { cover = null; }
    }
    const local = meta(b.id).position;
    const position = local && (!b.position || local.updated > b.position.updated)
      ? Object.assign({}, local.data, { updated: local.updated }) : b.position;
    const corr = localData(b, "corrections"), sel = localData(b, "selection");
    const marks = bookmarksOf(b);
    const info = {
      format: "chessbook", formatVersion: 1, saved: Date.now(), id: b.id, fileName: b.fileName,
      title: b.title || null, pages: b.pages || null, size: pdf.length, added: b.added, opened: b.opened,
      position: position || null,
      reading: reading ? { version: b.reading.version, size: b.reading.size } : null,
      corrections: { data: corr.data, updated: corr.updated },
      selection: { data: sel.data, updated: sel.updated },
      bookmarks: { data: marks.data, updated: marks.updated },
    };
    const entries = [{ name: "book.json", bytes: new TextEncoder().encode(JSON.stringify(info, null, 1)) },
                     { name: "book.pdf", bytes: pdf }];
    if (reading) entries.push({ name: "reading.gz", bytes: reading });
    if (cover) entries.push({ name: "cover.jpg", bytes: cover });
    return new File([zip(entries)], fileTitle(b) + ".chessbook", { type: "application/zip" });
  }
  // The share sheet on a phone or tablet (Save to Files, AirDrop), where the
  // browser shares files; a download elsewhere.
  function shares() {
    return !!(navigator.canShare && navigator.share) && window.matchMedia("(pointer: coarse)").matches;
  }
  function deliver(file) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(file);
    a.download = file.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  }
  async function saveBook(li, b, btn) {
    if (btn.disabled) return;
    btn.disabled = true;
    say("Preparing the book file.");
    let file;
    try {
      file = await bookFile(b);
    } catch (err) {
      btn.disabled = false;
      say("The book file could not be made: " + err.message, true);
      return;
    }
    btn.disabled = false;
    const done = () => say("The book file " + file.name + " (" + mb(file.size) + ") holds the book, the program's " +
                           "reading, your corrections, your bookmarks and your place. Add it to the library on " +
                           "another device.");
    if (shares() && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: file.name });
        done();
      } catch (err) {
        if (err && err.name === "AbortError") { say(""); return; }
        // the file took too long to make for the browser to count the tap: a second tap shares it
        offer(li, file, done);
      }
      return;
    }
    deliver(file);
    done();
  }
  function offer(li, file, done) {
    const old = li.querySelector(".confirm");
    if (old) old.remove();
    const box = document.createElement("div");
    box.className = "confirm";
    const q = document.createElement("span");
    q.textContent = "The book file " + file.name + " is ready.";
    const go = document.createElement("button");
    go.type = "button";
    go.className = "tb";
    go.textContent = "Save to Files";
    go.addEventListener("click", () => {
      navigator.share({ files: [file], title: file.name }).then(() => { box.remove(); done(); })
        .catch((err) => { if (!err || err.name !== "AbortError") { box.remove(); deliver(file); done(); } });
    });
    const no = document.createElement("button");
    no.type = "button";
    no.className = "tb";
    no.textContent = "Cancel";
    no.addEventListener("click", () => box.remove());
    box.append(q, go, no);
    li.appendChild(box);
    say("");
    go.focus();
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
    const kept = b.position;
    const pos = local && (!kept || local.updated > kept.updated) ? local.data : kept;
    return pos && pos.page ? pos : null;
  }
  // The bookmarks of book b: the newer of the browser's copy and the store's
  // (the server lists them with the book), as {data: {bookmarks: [...]}, updated}.
  function bookmarksOf(b) {
    const here = localData(b, "bookmarks");
    const there = b.bookmarks && b.bookmarks.updated ? b.bookmarks : null;
    if (there && there.updated > here.updated) return { data: there.data, updated: there.updated };
    return { data: here.data, updated: here.updated };
  }
  // "Bookmarks on pages 31 and 57", each page a button that opens the book there.
  function bookmarkLine(b) {
    const list = ((bookmarksOf(b).data || {}).bookmarks || []).filter((m) => m && m.page);
    if (!list.length) return null;
    const el = document.createElement("span");
    el.className = "bms";
    el.append(list.length === 1 ? "Bookmark on page " : "Bookmarks on pages ");
    list.forEach((m, i) => {
      const go = document.createElement("button");
      go.type = "button";
      go.className = "tb";
      go.textContent = String(m.page);
      go.setAttribute("aria-label", "Open " + titleOf(b) + " at the bookmark on page " + m.page);
      go.addEventListener("click", () => api.open(b, null, { chapter: m.chapter || null, page: m.page, node: m.node || null }));
      el.appendChild(go);
      if (i < list.length - 2) el.append(", ");
      else if (i === list.length - 2) el.append(" and ");
    });
    return el;
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
  function button(text, cls, fn) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "tb " + cls;
    el.textContent = text;
    el.addEventListener("click", fn);
    return el;
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
      const acts = document.createElement("span");
      acts.className = "acts";
      if (store.kind === "device") {
        const save = button(shares() ? "Save to Files" : "Save a copy", "save", () => saveBook(li, b, save));
        save.setAttribute("aria-label", "Save " + titleOf(b) + " as one file, to move it to another device");
        acts.appendChild(save);
      }
      acts.appendChild(button("Remove", "remove", () => confirmRemove(li, b)));
      li.append(open, acts);
      const bms = bookmarkLine(b);
      if (bms) li.appendChild(bms);
      list.appendChild(li);
    }
    space();
  }
  // One quiet line under the books: the room they take on this device.
  async function space() {
    const el = $("libspace");
    if (!el) return;
    if (store.kind !== "device" || !api.books.length) { el.hidden = true; return; }
    let used = null;
    try {
      const est = navigator.storage && navigator.storage.estimate ? await navigator.storage.estimate() : null;
      if (est && Number.isFinite(est.usage)) used = est.usage;
    } catch (e) { used = null; }
    if (used === null) {
      used = api.books.reduce((s, b) => s + (b.size || 0) + (b.reading ? b.reading.stored : 0), 0);
    }
    api.space = used;
    el.textContent = "The library takes " + mb(used) + " on this device.";
    el.hidden = false;
  }
  function confirmRemove(li, b) {
    const old = li.querySelector(".confirm");
    if (old) { if (old.classList.contains("removing")) return; old.remove(); }
    const box = document.createElement("div");
    box.className = "confirm removing";
    box.setAttribute("role", "alertdialog");
    const q = document.createElement("span");
    q.textContent = "Remove this book, its stored reading and its corrections from the library?";
    const no = button("Keep it", "", () => box.remove());
    const yes = button("Remove the book", "yes", async () => {
      yes.disabled = no.disabled = true;
      try {
        await store.remove(b.id);
        forget(b);
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
  // What the browser keeps for a removed book: its record, its corrections, its
  // selection and its bookmarks.
  function forget(b) {
    const name = meta(b.id).name || safeName(b.fileName);
    try {
      localStorage.removeItem(META + b.id);
      const keys = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && KINDS.some((kind) => k.startsWith("chessbook-" + kind + ":" + name + ":"))) keys.push(k);
      }
      keys.forEach((k) => localStorage.removeItem(k));
    } catch (e) { /* no storage */ }
  }
  // iPhone and iPad: Safari may clear the storage of a site not used for a
  // week; an app added to the Home Screen keeps its own storage, which it
  // does not clear.
  function homeHint() {
    const el = $("libhint");
    if (!el || store.kind !== "device") return;
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    const standalone = navigator.standalone === true || window.matchMedia("(display-mode: standalone)").matches;
    let off = false;
    try { off = localStorage.getItem(HINT) === "off"; } catch (e) { off = false; }
    if (!ios || standalone || off) { el.hidden = true; return; }
    el.querySelector("span").textContent = "Safari may clear these books after a week unused. An app on the " +
      "Home Screen keeps them: choose the share button, then Add to Home Screen, and add your books in that app.";
    el.querySelector("button").onclick = () => {
      try { localStorage.setItem(HINT, "off"); } catch (e) { /* no storage */ }
      el.hidden = true;
    };
    el.hidden = false;
  }
  function showLibrary() {
    document.body.classList.add("library");
    document.querySelector("#start h1").textContent = "Your library";
    $("intro").hidden = true;
    $("lib").hidden = false;
    $("drop").querySelector(".big").textContent = "Add a book";
    if (store.kind === "device") {
      $("drop").querySelector(".small").textContent =
        "Choose a chess book PDF, or a book file saved from a library, or drop one here. The program reads " +
        "a PDF once and keeps it on this device.";
      $("drop").setAttribute("aria-label", "Add a chess book PDF or a book file to your library");
      $("libempty").textContent = "Your library on this device holds no books yet. Add a chess book below: " +
        "the program reads it once and keeps it here, so that it opens at once the next time.";
    } else {
      $("drop").querySelector(".small").textContent =
        "Choose a chess book PDF, or drop one here. The program reads it once and keeps it in your library.";
      $("drop").setAttribute("aria-label", "Add a chess book PDF to your library");
    }
    $("another").textContent = "Library";
    homeHint();
    render();
  }

  // ---------------------------------------------------------------- starting
  api.start = async function () {
    let books = await serverStore.probe();
    if (books) store = serverStore;
    else {
      // no server: the library lives in this browser
      if (!window.indexedDB) return false;
      try {
        store = deviceStore();
        books = await store.list();
      } catch (e) {
        store = null;
        return false;
      }
    }
    api.on = true;
    api.kind = store.kind;
    api.books = books;
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
  // Ask the browser to keep the library's storage (it may grant it at once,
  // ask the user, or refuse); the answer shows in LIB.persisted.
  function persist() {
    if (store.kind !== "device" || !navigator.storage || !navigator.storage.persist) return;
    navigator.storage.persisted().then((p) => p || navigator.storage.persist())
      .then((p) => { api.persisted = !!p; }).catch(() => {});
  }

  // ---------------------------------------------------------------- adding and opening
  // A file the user chose: a PDF, or a book file saved from a library.
  api.add = async function (file) {
    if (busy) return;
    let head = "";
    try { head = String.fromCharCode(...new Uint8Array(await file.slice(0, 5).arrayBuffer())); }
    catch (e) { head = ""; }
    if (head.startsWith("PK\u0003\u0004")) return addBookFile(file);
    if (head !== "%PDF-" && !/\.pdf$/i.test(file.name)) {
      say("Please choose a chess book PDF, or a book file saved from a library.", true);
      return;
    }
    return addPdf(file);
  };
  async function addPdf(file) {
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
      if (buffer.byteLength > store.maxPdf) {
        busy = false;
        say("This book is larger than " + Math.round(store.maxPdf / 1048576) + " MB, the most the library can " +
            "store in one piece. The program reads it on this device, but it is not kept in your library.");
        api.current = null;
        return read(file, file.name);
      }
      let book;
      try {
        say(store.kind === "device" ? "Keeping the book on this device." : "Adding the book to your library.");
        book = await store.add(id, buffer, file.name, (text) => say(text));
      } catch (err) {
        busy = false;
        say(tooFull(err)
          ? "This device has no room left to keep the book (" + err.message + "). The program reads it for " +
            "now; removing a book from the library makes room."
          : "The book could not be added to your library (" + err.message + "). The program reads it " +
            "on this device only.", true);
        api.current = null;
        return read(file, file.name);
      }
      persist();
      api.books.unshift(book);
      api.current = { id, book, name: safeName(book.fileName), restored: false };
      busy = false;
      await whenReady();
      read(file, book.fileName);
    } catch (err) {
      busy = false;
      $("bar").classList.remove("on");
      say("The book could not be added: " + err.message, true);
    }
  }

  // A book file (.chessbook): the book with its reading, corrections,
  // selection and place, saved by "Save to Files" on this or another device.
  async function addBookFile(file) {
    busy = true;
    $("bar").classList.add("on");
    const stop = (text, error) => {
      busy = false;
      $("bar").classList.remove("on");
      say(text, error);
    };
    let parts, info;
    try {
      say("Opening the book file.");
      parts = await unzip(await file.arrayBuffer());
      info = JSON.parse(new TextDecoder().decode(parts["book.json"] || new Uint8Array()));
    } catch (err) {
      return stop("This file cannot be added: " + (err instanceof SyntaxError ? "it is damaged" : err.message) + ".", true);
    }
    const pdf = parts["book.pdf"];
    if (!info || info.format !== "chessbook" || !pdf || !info.fileName) {
      return stop("This file cannot be added: it is not a book file saved from a library.", true);
    }
    const id = await sha256(pdf);
    if (info.id && info.id !== id) return stop("This file cannot be added: its book is damaged.", true);
    const reading = parts["reading.gz"] && info.reading ? parts["reading.gz"] : null;
    const cover = parts["cover.jpg"] || null;
    const name = safeName(info.fileName);
    const known = api.books.find((b) => b.id === id);
    if (known) return mergeBookFile(known, info, reading, stop);

    // a new book: the store keeps it, then it opens from its reading
    let book = null, kept = true;
    try {
      say(store.kind === "device" ? "Keeping the book on this device." : "Adding the book to your library.");
      book = await store.add(id, pdf.slice().buffer, info.fileName, (text) => say(text));
      book = await store.update(id, Object.assign({ title: info.title || undefined },
                                                  Number.isInteger(info.pages) ? { pages: info.pages } : {}))
        .then((r) => (r && r.book) || r || book);
      if (reading) book = await store.putReading(id, reading.slice(), info.reading.version, info.reading.size || 0);
      if (cover) book = await store.putCover(id, cover.slice()).catch(() => book);
      if (info.position && info.position.page) {
        const { updated, ...pos } = info.position;
        await store.putPosition(id, pos, updated || Date.now()).catch(() => {});
      }
      persist();
    } catch (err) {
      kept = false;
      if (book) await store.remove(id).catch(() => {});
      say((tooFull(err) ? "This device has no room left to keep the book (" + err.message + "). "
                        : "The book could not be added to your library (" + err.message + "). ") +
          "It opens for now, and is not kept.", true);
    }
    // the corrections, the selection, the bookmarks and the place, as the reader keeps them
    const mm = meta(id);
    mm.name = name;
    if (info.pages) mm.pages = info.pages;
    for (const kind of KINDS) {
      const d = info[kind];
      if (!d || !d.data || !info.pages) continue;
      const v = JSON.stringify(d.data);
      try { localStorage.setItem(storageKey(mm, kind), v); } catch (e) { /* no storage */ }
      mm[kind] = { updated: d.updated || Date.now(), sent: 0, seen: v };
    }
    if (info.position && info.position.page) {
      const { updated, ...pos } = info.position;
      mm.position = { data: pos, updated: updated || Date.now(), sent: kept ? updated || Date.now() : 0 };
    }
    saveMeta(id, mm);
    busy = false;
    if (kept) {
      api.books.unshift(book);
      render();
      flush();
      return api.open(book);
    }
    // not kept: the book opens from the file, for this session
    const temp = { id, fileName: info.fileName, title: info.title, pages: info.pages, added: Date.now(),
                   reading: reading ? { version: info.reading.version } : null, position: null };
    return api.open(temp, { pdf, reading });
  }
  // The library holds the book already: the newer corrections, selection and
  // place win, and a stored reading of this program replaces a stale one.
  async function mergeBookFile(b, info, reading, stop) {
    const mm = meta(b.id);
    mm.name = mm.name || safeName(b.fileName);
    mm.pages = mm.pages || b.pages || info.pages;
    const pages = b.pages || info.pages;
    let verdict = "same";
    for (const kind of KINDS) {
      const here = localData(Object.assign({}, b, { pages }), kind);
      const there = info[kind] || { data: null, updated: 0 };
      const v = there.data ? JSON.stringify(there.data) : null;
      if (v === here.text || (v === null && here.text === null)) continue;
      if ((there.updated || 0) > here.updated) {
        try { if (v === null) localStorage.removeItem(here.key); else localStorage.setItem(here.key, v); }
        catch (e) { /* no storage */ }
        mm[kind] = { updated: there.updated, sent: 0, seen: v };
        if (kind === "corrections") verdict = "file";
      } else if (kind === "corrections") verdict = "device";
    }
    const pos = info.position;
    const local = mm.position;
    const keptAt = Math.max(local ? local.updated : 0, b.position ? b.position.updated : 0);
    if (pos && pos.page && (pos.updated || 0) > keptAt) {
      const { updated, ...data } = pos;
      mm.position = { data, updated, sent: 0 };
    }
    saveMeta(b.id, mm);
    try {
      if (reading && info.reading.version === api.version && (!b.reading || b.reading.version !== api.version)) {
        Object.assign(b, await store.putReading(b.id, reading.slice(), info.reading.version, info.reading.size || 0));
      }
    } catch (e) { /* the stored reading stays as it was */ }
    flush();
    render();
    stop("This book is already in your library. " + (
      verdict === "file" ? "The corrections in the file are newer than those on this device and replace them." :
      verdict === "device" ? "The corrections on this device are newer than those in the file and stay as they are." :
      "The file holds the same corrections."));
  }

  // Open book b: from the store, or from given = {pdf, reading} (a book file
  // the store could not keep); at = {chapter, page, node} opens it at a
  // bookmark instead of the place last read.
  api.open = async function (b, given, at) {
    if (busy) return;
    busy = true;
    $("bar").classList.add("on");
    const name = safeName(b.fileName);
    api.current = { id: b.id, book: b, name, restored: false, position: null, t0: Date.now(), ephemeral: !!given,
                    at: at || null };
    try {
      if (!given) say(store.kind === "device" ? "Opening the book." : "Downloading the book.");
      const pdf = given ? given.pdf : await store.pdf(b.id, (text) => say(text));
      const file = new File([pdf], b.fileName, { type: "application/pdf" });
      if (!given) await syncIn(b, name);
      const local = meta(b.id).position;
      api.current.position = local && (!b.position || local.updated > b.position.updated) ? local.data : b.position;
      if (at) {
        // a bookmark names its chapter; one whose chapter is unknown opens at the page last read
        const marks = ((bookmarksOf(b).data || {}).bookmarks || []).filter((m) => m && m.page);
        const same = marks.find((m) => m.page === at.page);
        api.current.position = { chapter: at.chapter || (same && same.chapter) || (api.current.position || {}).chapter,
                                 page: at.page, node: at.node || null };
      }
      if (!given) store.update(b.id, { opened: Date.now() }).catch(() => {});
      if (!ready) say("The reader is still starting. The book opens in a moment.");
      await whenReady();
      if (b.reading && b.reading.version === api.version) {
        if (!given && store.kind === "server") say("Downloading the program's reading of the book.");
        const reading = given ? given.reading.slice() : await store.reading(b.id, (text) => say(text));
        api.current.file = file;
        lastFile = file;
        lastName = b.fileName;
        say("Opening the book.");
        const bytes = pdf.slice().buffer;
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
        if (!cur.ephemeral) store.update(cur.id, { title: m.title, pages: m.pages }).catch(() => {});
      }
      const mm = meta(cur.id);
      mm.name = cur.name;
      mm.pages = m.pages;
      saveMeta(cur.id, mm);
      seen(cur.id);
      if (!b.cover && !cur.ephemeral) worker.postMessage({ type: "cover", name: cur.name });
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
      store.putCover(cur.id, m.bytes).then((book) => { cur.book.cover = book.cover; }).catch(() => {});
      return true;
    }
    if (m.type === "done") {
      if (!m.restored && !cur.ephemeral) {
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
    store.putReading(cur.id, m.bytes, m.version, m.size)
      .then((book) => {
        cur.book.reading = book.reading;
        if (api.current === cur) {
          status(store.kind === "device"
            ? "The book is in your library on this device: it opens next time without being read again."
            : "The book is in your library: any device opens it without reading it again.");
        }
      })
      .catch((err) => {
        if (store.kind === "server" && tries < 4) setTimeout(() => sendReading(cur, m, tries + 1), 5000 * (tries + 1));
        else if (api.current === cur) {
          status((tooFull(err)
            ? "This device has no room left to keep the program's reading (" + err.message + "). "
            : "The program's reading could not be saved to your library (" + err.message + "). ") +
            "The book is read again the next time it opens.", true);
        }
      });
  }

  // ---------------------------------------------------------------- the reader
  api.fromReader = function (d) {
    if (!api.on || !api.current || !d || api.current.ephemeral) return;
    if (d.position) {
      const cur = api.current;
      if (!openChapter || !/^ch\d+\.html$/.test(openChapter)) return;
      const mm = meta(cur.id);
      mm.position = { data: { chapter: openChapter, page: d.position.page, node: d.position.node || null },
                      updated: Date.now(), sent: (mm.position && mm.position.sent) || 0 };
      saveMeta(cur.id, mm);
      schedule(POSITION_DELAY);
    }
    // a correction, a changed selection or a bookmark: the reader has written it to the storage already
    if (d.correct || d.selectionChanged || d.bookmarksChanged) setTimeout(() => seen(api.current.id), 0);
    if (d.bookmarksChanged) {
      // the library page shows the bookmarks under the book
      const b = api.books.find((x) => x.id === api.current.id);
      if (b && b.bookmarks) b.bookmarks = null;
    }
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
  // the one seen last is a change made here (to be sent to the server, and
  // dated for a book file).
  function seen(id) {
    const mm = meta(id);
    let changed = false;
    for (const kind of KINDS) {
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
    const m = /^chessbook-(corrections|selection|bookmarks):/.exec(key);
    if (!m || !api.current) return;
    seen(api.current.id);
  }
  let timer = 0;
  function schedule(ms) {
    clearTimeout(timer);
    timer = setTimeout(() => flush(), ms);
  }
  // Send every change the store has not taken yet, for every book: to the
  // server the corrections, the selection, the bookmarks and the place; on
  // the device the place (the rest stays in localStorage).
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
        if (store.syncs) {
          for (const kind of KINDS) {
            const st = mm[kind];
            if (!st || !(st.updated > (st.sent || 0))) continue;
            let data = null;
            try { data = st.seen ? JSON.parse(st.seen) : null; } catch (e) { data = null; }
            await sent(id, kind, st.updated, store.putData(id, kind, data, st.updated, leaving));
          }
        }
        const p = mm.position;
        if (p && p.updated > (p.sent || 0) && api.books.some((b) => b.id === id)) {
          await sent(id, "position", p.updated, store.putPosition(id, p.data, p.updated, leaving));
        }
      }
    } finally {
      flushing = false;
    }
  }
  // the store took the change: it needs no more sending
  async function sent(id, kind, updated, promise) {
    try {
      const book = await promise;
      const mm = meta(id);
      if (mm[kind] && mm[kind].updated === updated) {
        mm[kind].sent = updated;
        saveMeta(id, mm);
      }
      if (kind === "bookmarks" && book && typeof book.updated === "number") {
        const b = api.books.find((x) => x.id === id);
        if (b) b.bookmarks = { data: book.data, updated: book.updated };
      }
      if (kind === "position" && book && book.id) {
        const b = api.books.find((x) => x.id === id);
        if (b) b.position = book.position;
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
    if (!store.syncs) return;
    for (const kind of KINDS) {
      let server;
      try { server = await store.getData(b.id, kind); } catch (e) { continue; }
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
