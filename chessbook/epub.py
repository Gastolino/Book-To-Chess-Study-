"""EPUB books, laid out into PDF pages that the rest of the program reads.

An EPUB has no pages of its own: MuPDF flows it into pages of PAGE points
at FONT points, about 60 characters wide, so that a line of moves stays on
one line. The PDF keeps the text layer, the pictures, the title and the
table of contents. Its file name is <name>.epub.pdf, so that it never
overwrites the reader's own <name>.pdf, and every store keyed by the stem
(books/<stem>/, output/<stem>/, the library) tells the two apart.
"""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pymupdf

PAGE = (432, 648)
FONT = 10


class EpubError(Exception):
    """An EPUB the program cannot read; its message is for the reader."""


def is_epub(head: bytes, name: str = "") -> bool:
    """Whether a file whose first bytes are head (58 are enough) is an EPUB:
    a zip whose first entry is the stored mimetype, or a file named .epub."""
    return ((head[:4] == b"PK\x03\x04" and head[30:58] == b"mimetypeapplication/epub+zip")
            or str(name).lower().endswith(".epub"))


def convert(data: bytes) -> bytes:
    """The PDF of the EPUB data. The same EPUB gives the same bytes (no new
    trailer /ID), so the library knows the book again by the PDF's hash."""
    try:
        locked = "META-INF/encryption.xml" in zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile:
        locked = False
    if locked:
        raise EpubError("This EPUB is locked by its seller, so the program cannot read it.")
    try:
        d = pymupdf.open(stream=data, filetype="epub")
        title = d.metadata.get("title") or ""
        toc = d.get_toc()
        d.layout(width=PAGE[0], height=PAGE[1], fontsize=FONT)
        pdf = d.convert_to_pdf()
    except Exception as e:
        raise EpubError("The program cannot open this EPUB file.") from e
    out = pymupdf.open("pdf", pdf)
    out.set_metadata({"title": title, "producer": "chessbook epub"})
    try:
        out.set_toc(toc)
    except Exception:
        pass  # a table of contents MuPDF cannot write is left out
    return out.tobytes(garbage=3, deflate=True, no_new_id=True)


def as_pdf(path) -> Path:
    """path itself for a PDF; for an EPUB, <dir>/<name>.epub.pdf (or
    output/epub/<name>.epub.pdf when its folder is read-only), written once
    and again only when the EPUB is newer."""
    path = Path(path)
    try:
        with open(path, "rb") as f:
            head = f.read(58)
    except OSError:
        return path
    if not is_epub(head, path.name):
        return path
    name = path.stem + ".epub.pdf"
    target = path.with_name(name)
    if not os.access(path.parent, os.W_OK):
        from .assemble import OUTPUT_DIR
        target = OUTPUT_DIR / "epub" / name
    if target.exists() and target.stat().st_mtime >= path.stat().st_mtime:
        return target
    pdf = convert(path.read_bytes())
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(pdf)
    tmp.replace(target)
    return target
