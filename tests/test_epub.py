"""EPUB books (chessbook/epub.py): an EPUB is laid out into PDF pages, the
same bytes each time, beside the EPUB as <name>.epub.pdf; the book is then
read like a PDF book. The EPUB is built here (tests/epub_fixture.py)."""
import hashlib
import os
import sys
import zipfile
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from chessbook import epub  # noqa: E402
from epub_fixture import make_epub  # noqa: E402

LOCKED = "This EPUB is locked by its seller, so the program cannot read it."


def test_an_epub_is_known_by_its_first_bytes_or_its_name(tmp_path):
    head = make_epub(tmp_path / "x.epub").read_bytes()[:58]
    assert epub.is_epub(head)
    assert not epub.is_epub(b"%PDF-1.7\n" + bytes(49))
    # a book file saved from the library is a zip too, with no mimetype entry
    with zipfile.ZipFile(tmp_path / "x.chessbook", "w") as z:
        z.writestr("book.json", "{}")
    assert not epub.is_epub((tmp_path / "x.chessbook").read_bytes()[:58], "x.chessbook")
    assert epub.is_epub(b"PK\x03\x04", "Book.EPUB")


def test_convert_gives_the_same_pdf_each_time(tmp_path):
    data = make_epub(tmp_path / "x.epub").read_bytes()
    a, b = epub.convert(data), epub.convert(data)
    assert a[:5] == b"%PDF-"
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()
    doc = pymupdf.open("pdf", a)
    assert all((pg.rect.width, pg.rect.height) == epub.PAGE for pg in doc)
    assert doc.metadata["title"] == "Little Epub"
    assert [t[1] for t in doc.get_toc()] == ["Chapter 1", "Exercises"]
    # every picture lies on its page
    rects = [r for pg in doc for img in pg.get_images(full=True)
             for r in pg.get_image_rects(img[0]) if r in pg.rect]
    assert len(rects) == sum(len(pg.get_image_rects(img[0])) for pg in doc
                             for img in pg.get_images(full=True)) == 2


def test_as_pdf_writes_the_pdf_once_beside_the_epub(tmp_path):
    src = make_epub(tmp_path / "x.epub")
    own = tmp_path / "x.pdf"
    own.write_bytes(b"%PDF-1.7 the reader's own file")
    pdf = epub.as_pdf(src)
    assert pdf == tmp_path / "x.epub.pdf" and pdf.stem == "x.epub"
    assert pdf.read_bytes()[:5] == b"%PDF-"
    t = pdf.stat().st_mtime_ns
    assert epub.as_pdf(src) == pdf and pdf.stat().st_mtime_ns == t
    assert own.read_bytes() == b"%PDF-1.7 the reader's own file"
    # a PDF comes back as it is
    assert epub.as_pdf(own) == own
    # a newer EPUB is laid out again
    os.utime(src, ns=(t + 10**9, t + 10**9))
    epub.as_pdf(src)
    assert pdf.stat().st_mtime_ns != t


def test_a_zip_that_is_no_epub_or_a_locked_epub_is_refused(tmp_path):
    with zipfile.ZipFile(tmp_path / "plain.epub", "w") as z:
        z.writestr("a.txt", "no book")
    with pytest.raises(epub.EpubError, match="cannot open this EPUB"):
        epub.as_pdf(tmp_path / "plain.epub")
    locked = make_epub(tmp_path / "locked.epub", encrypted=True)
    with pytest.raises(epub.EpubError) as e:
        epub.convert(locked.read_bytes())
    assert str(e.value) == LOCKED
