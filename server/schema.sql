-- The library's records in D1 (binding DB). The book files live in R2
-- (binding BOOKS) under "<owner>/<book id>/": book.pdf, reading.gz (the
-- program's finished reading, gzip) and cover.jpg.
--
-- The deployment (.github/workflows/cloudflare.yml) runs this file on every
-- deploy, so each statement must leave existing tables and rows as they are.
-- Times are milliseconds since 1970 (JavaScript's Date.now()).

-- One row per book of each owner (the email Cloudflare Access gives).
CREATE TABLE IF NOT EXISTS books (
  owner TEXT NOT NULL,
  id TEXT NOT NULL,                 -- SHA-256 of the PDF, in hex
  file_name TEXT NOT NULL,          -- the PDF's file name when it was added
  title TEXT,                       -- the book's title in words, once the program has read it
  pages INTEGER,
  size INTEGER NOT NULL,            -- bytes of the PDF
  added INTEGER NOT NULL,
  opened INTEGER,
  position TEXT,                    -- JSON {chapter, page, node, key}: the place last read
  position_updated INTEGER,
  reading_version TEXT,             -- the program version that made the stored reading
  reading_size INTEGER,             -- bytes of the reading before gzip
  reading_stored INTEGER,           -- bytes stored (gzip)
  reading_updated INTEGER,
  cover_updated INTEGER,
  PRIMARY KEY (owner, id)
);

-- The corrections, the selection and the bookmarks of a book, as the browser
-- stores them (kind "corrections", "selection" or "bookmarks"); the copy with
-- the later "updated" wins.
CREATE TABLE IF NOT EXISTS book_data (
  owner TEXT NOT NULL,
  id TEXT NOT NULL,
  kind TEXT NOT NULL,
  data TEXT,                        -- JSON, or NULL when the browser removed it
  updated INTEGER NOT NULL,
  PRIMARY KEY (owner, id, kind)
);
