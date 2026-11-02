"""EPUB books, laid out into PDF pages that the rest of the program reads.

An EPUB has no pages of its own: MuPDF flows it into pages of PAGE points
at FONT points, about 60 characters wide, so that a line of moves stays on
one line. The PDF keeps the text layer, the pictures, the title and the
table of contents. Its file name is <name>.epub.pdf, so that it never
overwrites the reader's own <name>.pdf, and every store keyed by the stem
(books/<stem>/, output/<stem>/, the library) tells the two apart.
"""
from __future__ import annotations

import hashlib
import io
import os
import posixpath
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pymupdf

PAGE = (432, 648)
FONT = 10
PRODUCER = "chessbook epub"
LOCKED = "This EPUB is locked by its seller, so the program cannot read it."
UNREADABLE = "The program cannot open this EPUB file."
# The two ways an EPUB hides the fonts it embeds so that they are not copied
# out of it. A book whose encryption.xml names only these, on font files, has
# no lock on its text: MuPDF sets it in its own fonts.
FONT_OBFUSCATION = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}
FONT_FILES = (".otf", ".ttf", ".woff", ".woff2", ".pfb", ".pfa", ".cff")


class EpubError(Exception):
    """An EPUB the program cannot read; its message is for the reader."""


def is_epub(head: bytes, name: str = "") -> bool:
    """Whether a file whose first bytes are head (58 are enough) is an EPUB:
    a zip whose first entry is the stored mimetype, or a file named .epub."""
    return ((head[:4] == b"PK\x03\x04" and head[30:58] == b"mimetypeapplication/epub+zip")
            or str(name).lower().endswith(".epub"))


def is_locked(z: zipfile.ZipFile) -> bool:
    """Whether the EPUB z is locked by a seller's DRM: Adobe ADEPT
    (META-INF/rights.xml), Apple FairPlay (META-INF/sinf.xml), or an
    encryption.xml that encrypts more than the book's fonts. Font obfuscation
    alone (the IDPF or the Adobe algorithm, on font files) is no lock."""
    names = set(z.namelist())
    if names & {"META-INF/rights.xml", "META-INF/sinf.xml"}:
        return True
    if "META-INF/encryption.xml" not in names:
        return False
    try:
        root = ElementTree.fromstring(z.read("META-INF/encryption.xml"))
    except (ElementTree.ParseError, KeyError, zipfile.BadZipFile):
        return True
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "EncryptedData":
            continue
        algorithm, uri = "", ""
        for sub in el.iter():
            tag = sub.tag.rsplit("}", 1)[-1]
            if tag == "EncryptionMethod":
                algorithm = sub.get("Algorithm") or ""
            elif tag == "CipherReference":
                uri = sub.get("URI") or ""
        name = posixpath.basename(uri.split("#")[0].split("?")[0]).lower()
        if algorithm not in FONT_OBFUSCATION or not name.endswith(FONT_FILES):
            return True
    return False


def fingerprint(data: bytes) -> str:
    """What the PDF of the EPUB data is laid out from: the EPUB's bytes, the
    page and font size and the MuPDF version. The PDF carries it as its
    keywords, so that as_pdf lays the EPUB out again when any of them changes
    and the command line reads the same pages as the app."""
    return (f"chessbook-epub {hashlib.sha256(data).hexdigest()} {PAGE[0]}x{PAGE[1]} {FONT} "
            f"{pymupdf.VersionBind}")


def convert(data: bytes) -> bytes:
    """The PDF of the EPUB data. The same EPUB gives the same bytes (no new
    trailer /ID), so the library knows the book again by the PDF's hash."""
    try:
        locked = is_locked(zipfile.ZipFile(io.BytesIO(data)))
    except zipfile.BadZipFile:
        locked = False
    if locked:
        raise EpubError(LOCKED)
    try:
        d = pymupdf.open(stream=data, filetype="epub")
        # laid out first: the table of contents' page numbers are this
        # layout's, not those of MuPDF's default one
        d.layout(width=PAGE[0], height=PAGE[1], fontsize=FONT)
        title = d.metadata.get("title") or ""
        toc = d.get_toc()
        pdf = d.convert_to_pdf()
    except Exception as e:
        raise EpubError(UNREADABLE) from e
    out = pymupdf.open("pdf", pdf)
    out.set_metadata({"title": title, "producer": PRODUCER, "keywords": fingerprint(data)})
    try:
        out.set_toc(toc)
    except Exception:
        pass  # a table of contents MuPDF cannot write is left out
    return out.tobytes(garbage=3, deflate=True, no_new_id=True)


def _laid_out_from(target: Path, data: bytes) -> bool:
    try:
        with pymupdf.open(target) as old:
            return (old.metadata or {}).get("keywords") == fingerprint(data)
    except Exception:
        return False


def as_pdf(path) -> Path:
    """path itself for a PDF; for an EPUB, <dir>/<name>.epub.pdf (or
    output/epub/<name>.epub.pdf when its folder is read-only), written once,
    and again only when it was laid out from other bytes, at another page or
    font size, or by another MuPDF (see fingerprint)."""
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
    data = path.read_bytes()
    if target.exists() and _laid_out_from(target, data):
        return target
    pdf = convert(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(pdf)
    tmp.replace(target)
    return target
