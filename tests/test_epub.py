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


def test_an_epub_book_is_read_like_a_pdf_book(tmp_path):
    from chessbook.assemble import build_book
    from test_assemble import MAIN_SAN, line_titled, main_line, sans
    book = build_book(make_epub(tmp_path / "x.epub"), output_dir=tmp_path / "output",
                      books_dir=tmp_path / "books")
    assert (tmp_path / "output" / "x.epub" / "book.json").exists()
    assert book["title"] == "Little Epub" and book["pdf"] == "x.epub.pdf"
    game = line_titled(book, "Smith - Jones")
    assert (game["kind"], game["status"]) == ("game", "ok")
    assert sans(book, main_line(book, game)) == MAIN_SAN
    # the first exercise's board picture is a diagram, and its solution waits for its position
    board = book["pages"][2]["diagrams"][0]
    assert (board["kind"], board["label"]) == ("board", "1")
    assert line_titled(book, "Solutions 1")["diagram"] == board["id"]


def test_make_reader_takes_an_epub(tmp_path, monkeypatch, capsys):
    import make_reader
    from chessbook import assemble, corrections, selection
    monkeypatch.setattr(assemble, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(selection, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(corrections, "BOOKS_DIR", tmp_path / "books")
    make_reader.main([str(make_epub(tmp_path / "x.epub")), "--passes", "1"])
    assert (tmp_path / "output" / "x.epub" / "reader" / "index.html").exists()
    assert (tmp_path / "x.epub.pdf").exists()
    locked = make_epub(tmp_path / "locked.epub", encrypted=True)
    with pytest.raises(SystemExit) as e:
        make_reader.main([str(locked)])
    assert e.value.code == 1 and LOCKED in capsys.readouterr().out


def test_svg_boards_come_through_as_pictures(tmp_path):
    """MuPDF draws an EPUB's SVG board as a picture, so it is a diagram too."""
    from chessbook.assemble import build_book
    book = build_book(make_epub(tmp_path / "s.epub", svg=True), output_dir=tmp_path / "output",
                      books_dir=tmp_path / "books")
    assert [d["kind"] for pg in book["pages"] for d in pg["diagrams"]] == ["board", "board"]
