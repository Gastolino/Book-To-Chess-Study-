"""EPUB books (chessbook/epub.py): an EPUB is laid out into PDF pages, the
same bytes each time, beside the EPUB as <name>.epub.pdf; the book is then
read like a PDF book. The EPUB is built here (tests/epub_fixture.py)."""
import hashlib
import io
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
assert epub.LOCKED == LOCKED


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
    assert doc.metadata["keywords"] == epub.fingerprint(data)
    # every picture lies on its page
    rects = [r for pg in doc for img in pg.get_images(full=True)
             for r in pg.get_image_rects(img[0]) if r in pg.rect]
    assert len(rects) == sum(len(pg.get_image_rects(img[0])) for pg in doc
                             for img in pg.get_images(full=True)) == 2


def test_as_pdf_writes_the_pdf_once_beside_the_epub(tmp_path, monkeypatch):
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
    # a newer EPUB of the same bytes is the same book: its PDF is kept
    os.utime(src, ns=(t + 10**9, t + 10**9))
    assert epub.as_pdf(src) == pdf and pdf.stat().st_mtime_ns == t
    # another EPUB in its place is laid out again, even with an older date
    # (cp -p, unzip, rsync -t)
    make_epub(src, title="Another Epub")
    os.utime(src, ns=(t - 3600 * 10**9, t - 3600 * 10**9))
    epub.as_pdf(src)
    assert pymupdf.open(pdf).metadata["title"] == "Another Epub"
    # and so is a PDF laid out at another font size (or by another MuPDF)
    t = pdf.stat().st_mtime_ns
    monkeypatch.setattr(epub, "FONT", epub.FONT + 1)
    epub.as_pdf(src)
    assert pdf.stat().st_mtime_ns != t
    assert pymupdf.open(pdf).metadata["keywords"] == epub.fingerprint(src.read_bytes())


def test_a_zip_that_is_no_epub_or_a_locked_epub_is_refused(tmp_path):
    with zipfile.ZipFile(tmp_path / "plain.epub", "w") as z:
        z.writestr("a.txt", "no book")
    with pytest.raises(epub.EpubError, match="cannot open this EPUB"):
        epub.as_pdf(tmp_path / "plain.epub")
    locked = make_epub(tmp_path / "locked.epub", encrypted=True)
    with pytest.raises(epub.EpubError) as e:
        epub.convert(locked.read_bytes())
    assert str(e.value) == LOCKED
    # Adobe's lock (rights.xml) is a lock too
    with pytest.raises(epub.EpubError, match="locked by its seller"):
        epub.convert(make_epub(tmp_path / "adept.epub", rights=True).read_bytes())


def _zip(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, text in entries.items():
            z.writestr(name, text)
    return zipfile.ZipFile(io.BytesIO(out.getvalue()))


def test_an_epub_that_only_hides_its_fonts_is_not_locked(tmp_path):
    """Publishers obfuscate the fonts of books with no DRM (encryption.xml with
    the IDPF or the Adobe font algorithm): MuPDF reads their text."""
    from epub_fixture import AES, IDPF_FONTS, encryption_xml
    data = make_epub(tmp_path / "fonts.epub", obfuscated_fonts=True).read_bytes()
    assert zipfile.ZipFile(tmp_path / "fonts.epub").read("META-INF/encryption.xml")
    doc = pymupdf.open("pdf", epub.convert(data))
    assert "Smith - Jones" in "".join(pg.get_text() for pg in doc)
    # the same encryption.xml that also encrypts a chapter is a lock
    z = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as w:
        for info in z.infolist():
            body = z.read(info)
            if info.filename == "META-INF/encryption.xml":
                body = encryption_xml([(IDPF_FONTS, "OEBPS/fonts/a.otf"), (AES, "OEBPS/ch1.xhtml")])
            w.writestr(info, body)
    with pytest.raises(epub.EpubError, match="locked by its seller"):
        epub.convert(out.getvalue())
    enc = "META-INF/encryption.xml"
    # a font encrypted with another algorithm is no font obfuscation
    assert epub.is_locked(_zip({enc: encryption_xml([(AES, "OEBPS/f.otf")])}))
    # and the font algorithm on a picture hides more than a font
    assert epub.is_locked(_zip({enc: encryption_xml([(IDPF_FONTS, "OEBPS/board1.png")])}))
    assert not epub.is_locked(_zip({enc: encryption_xml([(IDPF_FONTS, "OEBPS/Fonts/Charis.TTF")])}))
    assert epub.is_locked(_zip({enc: "<not xml"}))
    assert epub.is_locked(_zip({"META-INF/sinf.xml": "<sinf/>"}))


def test_the_contents_point_at_the_laid_out_pages(tmp_path):
    """The table of contents' page numbers are those of the 432x648 layout,
    not of MuPDF's default one, which a long book shows."""
    doc = pymupdf.open("pdf", epub.convert(make_epub(tmp_path / "x.epub", prose=20).read_bytes()))
    toc = {t[1]: t[2] for t in doc.get_toc()}
    held = [i + 1 for i, pg in enumerate(doc) if "EXERCISES" in pg.get_text()]
    assert held and toc["Exercises"] == held[0]
    assert "Chapter 1" in doc[toc["Chapter 1"] - 1].get_text()


def test_ligatures_of_the_layout_read_as_their_letters(tmp_path):
    """MuPDF sets ff, fi and fl as ligatures: 8.Rff1 reads as the move of the
    rook on the f-file to f1, not as a move with no file."""
    from chessbook import pdftext
    from chessbook.assemble import build_book
    from test_assemble import line_titled, main_line, sans
    game = ["1.f4 a5 2.a4 b6 3.Ra3 c6", "4.Rf3 d6 5.Nh3 g6", "6.e3 Nd7 7.Be2 Bb7", "8.Rff1"]
    src = make_epub(tmp_path / "x.epub", game=game)
    doc = pymupdf.open(epub.as_pdf(src))
    raw = "".join(c["c"] for pg in doc for b in pg.get_text("rawdict", flags=pdftext._FLAGS)["blocks"]
                  for ln in b.get("lines", ()) for sp in ln["spans"] for c in sp["chars"])
    assert "\ufb00" in raw and "\ufb01" in raw  # the layout does make ligatures
    text = " ".join(ln["text"] for i in range(doc.page_count) for ln in pdftext.page_lines(doc, i))
    assert "Rff1" in text and not set(text) & set(pdftext.LIGATURES)
    book = build_book(src, output_dir=tmp_path / "output", books_dir=tmp_path / "books")
    line = line_titled(book, "Smith - Jones")
    assert line["status"] == "ok"
    assert sans(book, main_line(book, line))[-1] == "Rff1"


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
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        make_reader.main([str(locked)])
    # the reason goes to stderr (SystemExit with a message exits with 1), as
    # "Cannot find" does, so that it shows when stdout is redirected
    assert e.value.code == LOCKED
    assert LOCKED not in capsys.readouterr().out


def test_the_command_lines_say_why_an_epub_is_refused(tmp_path, monkeypatch):
    import stage1_inspect
    from chessbook import assemble
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"not a zip")
    monkeypatch.setattr(assemble, "OUTPUT_DIR", tmp_path / "output")
    with pytest.raises(SystemExit) as e:
        assemble.main([str(bad)])
    assert e.value.code == epub.UNREADABLE
    locked = make_epub(tmp_path / "locked.epub", encrypted=True)
    monkeypatch.setattr(sys, "argv", ["stage1_inspect.py", str(locked)])
    with pytest.raises(SystemExit) as e:
        stage1_inspect.main()
    assert e.value.code == LOCKED


def test_stage1_inspect_reads_the_laid_out_pages(tmp_path, monkeypatch):
    """stage1_inspect x.epub reads x.epub.pdf, the pages the reader shows, and
    writes to output/x.epub/stage1, where the reader looks for them."""
    import json

    import stage1_inspect
    src = make_epub(tmp_path / "x.epub")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["stage1_inspect.py", str(src)])
    stage1_inspect.main()
    assert (tmp_path / "x.epub.pdf").exists()
    out = tmp_path / "output" / "x.epub" / "stage1"
    assert (out / "diagrams.json").exists() and not (tmp_path / "output" / "x").exists()
    assert len(json.loads((out / "diagrams.json").read_text())) == 2


def test_svg_boards_come_through_as_pictures(tmp_path):
    """MuPDF draws an EPUB's SVG board as a picture, so it is a diagram too."""
    from chessbook.assemble import build_book
    book = build_book(make_epub(tmp_path / "s.epub", svg=True), output_dir=tmp_path / "output",
                      books_dir=tmp_path / "books")
    assert [d["kind"] for pg in book["pages"] for d in pg["diagrams"]] == ["board", "board"]
