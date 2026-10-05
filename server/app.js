// The library's server: it stores the user's books and what the app made of
// them, and does no reading itself (the app reads every book in the browser).
// functions/api/[[path]].js hands every request under /api/ to handle().
//
// Bindings (wrangler.toml): BOOKS, an R2 bucket for the files, and DB, a D1
// database for the records (server/schema.sql). Every record carries the
// email of its owner, and every query asks for the owner's rows only.
//
//   GET    /api/books                    the library
//   PUT    /api/books/:id                the PDF (id: its SHA-256 in hex, checked by R2)
//   PATCH  /api/books/:id                {title, pages, opened}
//   DELETE /api/books/:id                the book and everything stored for it
//   GET    /api/books/:id/pdf            the PDF
//   PUT    /api/books/:id/reading        the finished reading (gzip; X-Reading-Version, X-Reading-Size)
//   GET    /api/books/:id/reading
//   PUT    /api/books/:id/corrections    {data, updated}: the later "updated" wins
//   GET    /api/books/:id/corrections
//   PUT    /api/books/:id/selection      the same, for the selection
//   GET    /api/books/:id/selection
//   PUT    /api/books/:id/position       {position: {chapter, page, node}, updated}
//   PUT    /api/books/:id/cover          a small JPEG of the first page
//   GET    /api/books/:id/cover
import { authenticate } from "./auth.js";

// A request to a Cloudflare site may carry at most 100 MB on the free plan.
// A PDF goes up in one request (so that R2 can check its SHA-256), with room
// to spare under that limit; a larger book is refused with a clear message.
export const MAX_PDF = 95 * 1024 * 1024;
export const MAX_READING = 95 * 1024 * 1024;
const MAX_JSON = 4 * 1024 * 1024;       // corrections, selection and position
const MAX_COVER = 1024 * 1024;
const ID = /^[0-9a-f]{64}$/;
const KINDS = ["corrections", "selection"];

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers },
  });
}

function fail(status, error) {
  return json({ error }, status);
}

// The owner's folder in R2: the email, made safe for a key.
function key(user, id, file) {
  return `${encodeURIComponent(user.email)}/${id}/${file}`;
}

async function bodyText(request, limit) {
  const size = Number(request.headers.get("content-length") || 0);
  if (size > limit) return null;
  const text = await request.text();
  return text.length > limit ? null : text;
}

async function bodyJson(request) {
  const text = await bodyText(request, MAX_JSON);
  if (text === null) throw new Error("too large");
  return JSON.parse(text);
}

async function record(env, user, id) {
  return env.DB.prepare("SELECT * FROM books WHERE owner = ? AND id = ?").bind(user.email, id).first();
}

function publicBook(row) {
  return {
    id: row.id,
    title: row.title,
    fileName: row.file_name,
    pages: row.pages,
    size: row.size,
    added: row.added,
    opened: row.opened,
    position: row.position ? { ...JSON.parse(row.position), updated: row.position_updated } : null,
    reading: row.reading_version ? {
      version: row.reading_version, size: row.reading_size, stored: row.reading_stored,
      updated: row.reading_updated,
    } : null,
    cover: row.cover_updated ? `api/books/${row.id}/cover?v=${row.cover_updated}` : null,
  };
}

// A stored file, answered with 304 when the browser holds the same copy.
async function serve(env, request, objectKey, type, cache) {
  const obj = await env.BOOKS.get(objectKey, { onlyIf: request.headers });
  if (!obj) return fail(404, "The library holds no such file.");
  const headers = { etag: obj.httpEtag, "cache-control": cache, "content-type": type };
  if (!obj.body) return new Response(null, { status: 304, headers });
  headers["content-length"] = String(obj.size);
  return new Response(obj.body, { headers });
}

async function list(env, user) {
  const { results } = await env.DB.prepare(
    "SELECT * FROM books WHERE owner = ? ORDER BY COALESCE(opened, added) DESC").bind(user.email).all();
  return json({ books: results.map(publicBook), maxPdf: MAX_PDF, user: user.email });
}

async function upload(env, request, user, id) {
  const size = Number(request.headers.get("content-length"));
  if (!size) return fail(411, "The upload must say its size.");
  if (size > MAX_PDF) {
    return fail(413, `This book is larger than ${MAX_PDF / 1048576} MB, the most the library ` +
                     "can store in one piece.");
  }
  const name = decodeURIComponent(request.headers.get("x-file-name") || "book.pdf").slice(0, 300);
  const old = await record(env, user, id);
  if (old) return json({ book: publicBook(old), stored: false });
  try {
    // R2 refuses the file when its SHA-256 is not the id the browser computed
    await env.BOOKS.put(key(user, id, "book.pdf"), request.body, {
      sha256: id,
      httpMetadata: { contentType: "application/pdf" },
    });
  } catch (e) {
    return fail(400, "The book arrived damaged (its contents do not match its fingerprint). " +
                     "Try adding it again.");
  }
  const now = Date.now();
  await env.DB.prepare(
    "INSERT OR IGNORE INTO books (owner, id, file_name, size, added) VALUES (?, ?, ?, ?, ?)")
    .bind(user.email, id, name, size, now).run();
  return json({ book: publicBook(await record(env, user, id)), stored: true }, 201);
}

async function update(env, request, user, id) {
  const body = await bodyJson(request);
  const sets = [], values = [];
  if (typeof body.title === "string") { sets.push("title = ?"); values.push(body.title.slice(0, 500)); }
  if (Number.isInteger(body.pages)) { sets.push("pages = ?"); values.push(body.pages); }
  if (Number.isFinite(body.opened)) { sets.push("opened = MAX(COALESCE(opened, 0), ?)"); values.push(body.opened); }
  if (sets.length) {
    await env.DB.prepare(`UPDATE books SET ${sets.join(", ")} WHERE owner = ? AND id = ?`)
      .bind(...values, user.email, id).run();
  }
  return json({ book: publicBook(await record(env, user, id)) });
}

async function remove(env, user, id) {
  await env.BOOKS.delete(["book.pdf", "reading.gz", "cover.jpg"].map((f) => key(user, id, f)));
  await env.DB.batch([
    env.DB.prepare("DELETE FROM book_data WHERE owner = ? AND id = ?").bind(user.email, id),
    env.DB.prepare("DELETE FROM books WHERE owner = ? AND id = ?").bind(user.email, id),
  ]);
  return json({ deleted: id });
}

async function putReading(env, request, user, id) {
  const stored = Number(request.headers.get("content-length"));
  const version = request.headers.get("x-reading-version") || "";
  const size = Number(request.headers.get("x-reading-size") || 0);
  if (!stored) return fail(411, "The upload must say its size.");
  if (stored > MAX_READING) return fail(413, "The reading is too large for the library.");
  if (!/^[0-9a-z]{1,64}$/.test(version)) return fail(400, "The reading names no program version.");
  await env.BOOKS.put(key(user, id, "reading.gz"), request.body, {
    httpMetadata: { contentType: "application/octet-stream" },
  });
  await env.DB.prepare(
    "UPDATE books SET reading_version = ?, reading_size = ?, reading_stored = ?, reading_updated = ? " +
    "WHERE owner = ? AND id = ?").bind(version, size, stored, Date.now(), user.email, id).run();
  return json({ book: publicBook(await record(env, user, id)) });
}

async function putCover(env, request, user, id) {
  const size = Number(request.headers.get("content-length"));
  if (!size || size > MAX_COVER) return fail(413, "The cover picture is too large.");
  await env.BOOKS.put(key(user, id, "cover.jpg"), request.body, {
    httpMetadata: { contentType: "image/jpeg" },
  });
  await env.DB.prepare("UPDATE books SET cover_updated = ? WHERE owner = ? AND id = ?")
    .bind(Date.now(), user.email, id).run();
  return json({ book: publicBook(await record(env, user, id)) });
}

async function getData(env, user, id, kind) {
  const row = await env.DB.prepare(
    "SELECT data, updated FROM book_data WHERE owner = ? AND id = ? AND kind = ?")
    .bind(user.email, id, kind).first();
  return { data: row && row.data ? JSON.parse(row.data) : null, updated: row ? row.updated : 0 };
}

// Last write wins: a copy older than the stored one is not taken, and the
// answer gives the copy the server holds afterwards.
async function putData(env, request, user, id, kind) {
  const body = await bodyJson(request);
  if (!Number.isFinite(body.updated)) return fail(400, "The copy says not when it was made.");
  const data = body.data === null || body.data === undefined ? null : JSON.stringify(body.data);
  await env.DB.prepare(
    "INSERT INTO book_data (owner, id, kind, data, updated) VALUES (?, ?, ?, ?, ?) " +
    "ON CONFLICT (owner, id, kind) DO UPDATE SET data = excluded.data, updated = excluded.updated " +
    "WHERE excluded.updated >= book_data.updated").bind(user.email, id, kind, data, body.updated).run();
  return json(await getData(env, user, id, kind));
}

async function putPosition(env, request, user, id) {
  const body = await bodyJson(request);
  const p = body.position || {};
  if (!Number.isFinite(body.updated) || !Number.isInteger(p.page)) {
    return fail(400, "The position needs a page and the time it was read.");
  }
  const position = JSON.stringify({
    chapter: typeof p.chapter === "string" ? p.chapter.slice(0, 40) : null,
    page: p.page,
    node: typeof p.node === "string" ? p.node.slice(0, 40) : null,
  });
  await env.DB.prepare(
    "UPDATE books SET position = ?, position_updated = ?, opened = MAX(COALESCE(opened, 0), ?) " +
    "WHERE owner = ? AND id = ? AND COALESCE(position_updated, 0) <= ?")
    .bind(position, body.updated, body.updated, user.email, id, body.updated).run();
  return json({ book: publicBook(await record(env, user, id)) });
}

async function route(request, env, user, parts) {
  const method = request.method;
  if (parts.length === 1 && method === "GET") return list(env, user);
  const id = parts[1];
  if (!ID.test(id || "")) return fail(404, "There is no such address in the library.");
  const what = parts[2] || "";
  if (parts.length > 3) return fail(404, "There is no such address in the library.");
  if (!what && method === "PUT") return upload(env, request, user, id);
  // every other address needs the book in the library
  const row = await record(env, user, id);
  if (!row) return fail(404, "The library holds no such book.");
  if (!what) {
    if (method === "PATCH") return update(env, request, user, id);
    if (method === "DELETE") return remove(env, user, id);
    if (method === "GET") return json({ book: publicBook(row) });
  } else if (what === "pdf" && method === "GET") {
    return serve(env, request, key(user, id, "book.pdf"), "application/pdf",
                 "private, max-age=31536000, immutable");
  } else if (what === "reading") {
    if (method === "PUT") return putReading(env, request, user, id);
    if (method === "GET") return serve(env, request, key(user, id, "reading.gz"), "application/octet-stream",
                                       "private, no-cache");
  } else if (what === "cover") {
    if (method === "PUT") return putCover(env, request, user, id);
    if (method === "GET") return serve(env, request, key(user, id, "cover.jpg"), "image/jpeg",
                                       "private, max-age=31536000, immutable");
  } else if (KINDS.includes(what)) {
    if (method === "PUT") return putData(env, request, user, id, what);
    if (method === "GET") return json(await getData(env, user, id, what));
  } else if (what === "position" && method === "PUT") {
    return putPosition(env, request, user, id);
  }
  return fail(405, "The library does not take this request at this address.");
}

export async function handle(request, env) {
  const user = await authenticate(request, env);
  if (!user) {
    return fail(403, "The library needs you to sign in through Cloudflare Access.");
  }
  const path = new URL(request.url).pathname.replace(/^\/api\/?/, "").replace(/\/+$/, "");
  const parts = path.split("/");
  if (parts[0] !== "books") return fail(404, "There is no such address in the library.");
  try {
    return await route(request, env, user, parts);
  } catch (e) {
    if (e instanceof SyntaxError || (e && e.message === "too large")) {
      return fail(400, "The request held no readable JSON of a reasonable size.");
    }
    return fail(500, "The library could not do this: " + (e && e.message ? e.message : e));
  }
}
