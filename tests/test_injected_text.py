"""A converter's running header written into the middle of the text.

calibre printed the title of Tangborn's book (corpus/archive3/tangborn.pdf)
inside a line of moves on PDF page 7, glued to the move number before it and
followed by a scrap of its template ("10A Chess Opening for White: ... a
Fischer Favoriterend:>.Nf1 Bd7"). pdftext takes such a string out of the line
(pdftext.drop_injected), so that the line reads "10.Nf1 Bd7"; the same title
printed as a line of its own (a title page) or inside a sentence stays.
"""
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook import pdftext as pt  # noqa: E402

TITLE = "A Chess Opening for White: The King's Indian Attack, a Fischer Favorite"
TANGBORN = ROOT / "corpus" / "archive3" / "tangborn.pdf"


def test_drop_injected():
    line = "10" + TITLE + "rend:>.Nf1 Bd7"
    (a, e), = pt.drop_injected(line, [TITLE])
    assert line[:a] + line[e:] == "10.Nf1 Bd7"
    # a title page, and the title named in a sentence, stay
    assert pt.drop_injected(TITLE, [TITLE]) == []
    assert pt.drop_injected("as the book " + TITLE + " says.", [TITLE]) == []
    assert pt.drop_injected("10.Nf1 Bd7", []) == []


def test_injected_title_is_taken_out_of_the_line(tmp_path):
    doc = pymupdf.open()
    doc.set_metadata({"title": TITLE})
    page = doc.new_page(width=612, height=792)
    page.insert_text((40, 80), "A Chess Opening for White", fontsize=20)
    page.insert_text((5, 300), "9.Re1 Qc7", fontname="tibo", fontsize=12)
    page.insert_text((5, 330), "10" + TITLE + "rend:>.Nf1 Bd7", fontname="tibo", fontsize=8)
    page.insert_text((5, 360), "This square should be reserved for the Knight.", fontsize=12)
    page = doc.new_page(width=612, height=792)
    page.insert_text((40, 80), TITLE, fontsize=12)
    path = tmp_path / "book.pdf"
    doc.save(path)
    doc = pymupdf.open(path)
    texts = [ln["text"] for ln in pt.page_lines(doc, 0)]
    assert "10.Nf1 Bd7" in texts, texts
    line = next(ln for ln in pt.page_lines(doc, 0) if ln["text"] == "10.Nf1 Bd7")
    # one line, with the words where the page prints them
    assert [w["text"] for w in line["words"]] == ["10.Nf1", "Bd7"]
    assert line["words"][1]["bbox"][0] > 300
    assert [ln["text"] for ln in pt.page_lines(doc, 1)] == [TITLE]


@pytest.mark.skipif(not TANGBORN.exists(), reason="tangborn.pdf is not in the corpus")
def test_tangborn_page_7_reads_10_nf1_bd7():
    doc = pymupdf.open(TANGBORN)
    assert pt.injected_strings(doc) == [TITLE]
    texts = [ln["text"] for ln in pt.page_lines(doc, 6)]
    assert "10.Nf1 Bd7" in texts, texts
    assert not any("Favorite" in t for t in texts)
    # the title page keeps the title
    assert any(TITLE in ln["text"] for ln in pt.page_lines(doc, 1))
