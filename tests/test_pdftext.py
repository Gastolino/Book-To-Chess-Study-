"""Tests for chessbook.pdftext on the first test book, The Soviet Chess Primer.

Primer-specific facts (page numbers, texts) belong here and nowhere in the
library code.
"""
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402

from chessbook import pdftext as pt  # noqa: E402

PDF = ROOT / "primer.pdf"
pytestmark = pytest.mark.skipif(not PDF.exists(), reason="primer.pdf is not in the project folder")


@pytest.fixture(scope="module")
def doc():
    return pymupdf.open(PDF)


@pytest.fixture(scope="module")
def fonts(doc):
    return pt.book_fonts(doc)


@pytest.fixture(scope="module")
def structure(doc):
    return pt.book_structure(doc)


@pytest.fixture(scope="module")
def p201(doc, fonts):
    return pt.page_lines(doc, 200, fonts)


@pytest.fixture(scope="module")
def p250(doc, fonts):
    return pt.page_lines(doc, 249, fonts)


def find(lines, start):
    hits = [ln for ln in lines if ln["text"].startswith(start)]
    assert hits, f"no line starts with {start!r}"
    return hits[0]


# ------------------------------------------------------------------ fonts

def test_book_fonts_is_json_and_learns_roles(fonts):
    json.loads(json.dumps(fonts))
    assert fonts["page_count"] == 402
    body = fonts["body"]
    assert abs(body["size"] - 10.1) < 0.3
    assert fonts["moves"], "no move font found"
    move = fonts["moves"][0]
    assert abs(move["size"] - 11.8) < 0.3
    assert (move["font"], move["size"]) != (body["font"], body["size"])
    assert any(abs(h["size"] - 42.2) < 0.5 for h in fonts["headings"])
    assert fonts["coords"]
    lay = fonts["layout"]
    assert lay["head_base_max"] is not None and lay["head_base_max"] < 60
    assert lay["foot_base_min"] is None          # the Primer has no running feet
    for g in lay["gutter"].values():
        assert 215 < g < 235                      # between the two text columns
    roles = {(e["font"], e["size"]): e["role"] for e in fonts["fonts"]}
    assert roles[(body["font"], body["size"])] == "text"
    assert roles[(move["font"], move["size"])] == "moves"


# ------------------------------------------------------------------ structure

def test_chapters_and_front_matter(structure):
    chapters = structure["chapters"]
    titles = [c["title"] for c in chapters]
    assert len(chapters) == 11, titles
    for n in range(1, 11):
        c = chapters[n - 1]
        assert c["kind"] == "chapter" and c["number"] == n, c
        assert c["title"].startswith(f"Chapter {n}"), c["title"]
    assert chapters[-1]["kind"] == "appendix"
    assert chapters[-1]["title"].startswith("Appendix")
    assert structure["front_matter_end"] == 13
    assert chapters[0]["start"] == 14
    assert chapters[-1]["end"] == 402
    for a, b in zip(chapters, chapters[1:]):
        assert a["end"] + 1 == b["start"] and a["start"] <= a["end"]
    starts = {c["number"]: c["start"] for c in chapters if c["kind"] == "chapter"}
    # "Chapter ?" on PDF page 242 is chapter 7 by its place in the sequence.
    assert starts[7] == 242 and starts[10] == 370
    assert chapters[0]["title"] == "Chapter 1: The Game Explained"
    assert chapters[9]["title"] == "Chapter 10: The Foundations of Opening Theory"
    assert all(c["confirmed"] for c in chapters)


def test_sections(structure):
    ch = {c["label"]: c for c in structure["chapters"]}
    s1 = [(s["page"], s["title"]) for s in ch["Chapter 1"]["sections"]]
    assert (32, "FUN EXERCISES") in s1
    assert (35, "SOLUTIONS TO FUN EXERCISES") in s1
    assert (15, "2. IDENTIFYING THE SQUARES - RECORDING A POSITION") in s1
    assert any(t == "ANSWERS AND SOLUTIONS" for _, t in
               ((s["page"], s["title"]) for s in ch["Chapter 3"]["sections"]))
    assert any(s["title"] == "GAMES" for s in ch["Chapter 5"]["sections"])
    assert any(s["title"] == "SOLUTIONS TO PROBLEMS" for s in ch["Appendix"]["sections"])
    for c in structure["chapters"]:
        for s in c["sections"]:
            assert c["start"] <= s["page"] <= c["end"]
    fm = [s["title"] for s in structure["front_matter"]]
    assert "Foreword by Mark Dvoretsky" in fm


def test_parse_chapter_heading():
    assert pt.parse_chapter_heading("Chapter ?") == ("chapter", "Chapter", None, "")
    assert pt.parse_chapter_heading("Chapter 1 0")[2] == 10
    assert pt.parse_chapter_heading("Chapter 7 - How to Begin a Game") == (
        "chapter", "Chapter", 7, "How to Begin a Game")
    assert pt.parse_chapter_heading("CHAPTER SIX: POSITIONAL PLAY")[2:] == (6, "POSITIONAL PLAY")
    assert pt.parse_chapter_heading("Appendix")[0] == "appendix"
    assert pt.parse_chapter_heading("Kapitel IV")[2] == 4
    assert pt.parse_chapter_heading("The chapter ends here") is None


# ------------------------------------------------------------------ page 201

def test_page_201_roles(p201):
    assert find(p201, "23J3e8t")["role"] == "moves"
    assert find(p201, "This was from a simultaneous blindfold")["role"] == "text"
    hdr = find(p201, "Alekhine - N.N.")
    assert hdr["text"] == "Alekhine - N.N., New York (simul) 1924"
    assert hdr["role"] == "game_header"
    files = [ln for ln in p201 if ln["text"] in list("abcdefgh")]
    assert len(files) == 24                      # three boards, eight files each
    assert all(ln["role"] == "coord" for ln in files)
    ranks = [ln for ln in p201 if ln["text"] in list("12345678") and ln["col"] == 2
             and ln["bbox"][2] < 254.4]          # beside the left edge of board 7
    assert len(ranks) == 8 and all(ln["role"] == "coord" for ln in ranks)
    label = find(p201, "5")
    assert label["role"] == "label" and label["diagram"] == "p201-1"
    captions = [ln for ln in p201 if ln["text"] == "White to move"]
    assert len(captions) == 3 and all(ln["role"] == "caption" for ln in captions)
    assert {ln["diagram"] for ln in captions} == {"p201-1", "p201-2", "p201-3"}
    assert [ln["text"] for ln in p201 if ln["role"] == "head"] == ["200", "The Soviet Chess Primer"]
    assert find(p201, "1-0")["role"] == "moves"


def test_page_201_reading_order(p201):
    texts = [ln["text"] for ln in p201]
    assert texts.index("This was from a simultaneous blindfold") < texts.index("There followed:")
    body = [ln for ln in p201 if ln["role"] != "head"]
    cols = [ln["col"] for ln in body]
    assert set(cols) == {1, 2}
    assert cols == sorted(cols), "left column must come before the right column"
    left = [ln for ln in body if ln["col"] == 1]
    assert all(ln["bbox"][2] < 228 for ln in left)
    # Within the left column, text runs top to bottom.
    seq = ["5", "Alekhine - N.N., New York (simul) 1924", "White to move",
           "White announced mate in four:", "This was from a simultaneous blindfold", "6"]
    idx = [texts.index(t) for t in seq]
    assert idx == sorted(idx)


def test_line_dict_fields_and_words(p201):
    for ln in p201:
        assert set(ln) >= {"page", "bbox", "text", "role", "col", "spans", "words"}
        assert ln["page"] == 201 and ln["role"] in pt.ROLES and ln["col"] in (0, 1, 2)
        assert [w["text"] for w in ln["words"]] == ln["text"].split(" ")
        x0, y0, x1, y1 = ln["bbox"]
        for w in ln["words"]:
            wx0, wy0, wx1, wy1 = w["bbox"]
            assert x0 - 0.5 <= wx0 <= wx1 <= x1 + 0.5 and y0 - 0.5 <= wy0 <= wy1 <= y1 + 0.5
        for s in ln["spans"]:
            assert set(s) >= {"text", "font", "size", "bbox", "role"}
    moves = find(p201, "23J3e8t")
    # Figurine junk made of control characters stays inside its word.
    assert "\x18fB" in [w["text"] for w in moves["words"]]
    assert "25J\x1d:xf8t" in [w["text"] for w in moves["words"]]
    assert all(s["role"] == "moves" for s in moves["spans"])
    # Boxes are tight: consecutive body lines do not overlap vertically.
    a = find(p201, "Black resigned, as 17")
    b = find(p201, "by 1 8.Wfc4t")
    assert a["bbox"][3] <= b["bbox"][1] + 0.5


# ------------------------------------------------------------------ page 250

def test_page_250_roles(p250):
    hdr = find(p250, "Fine -Yudovich")
    assert hdr["text"] == "Fine -Yudovich, Moscow 1937" and hdr["role"] == "game_header"
    assert find(p250, "8 ... axb5! 9.")["role"] == "moves"
    assert find(p250, "Lured by the prospect")["role"] == "text"
    assert find(p250, "Chapter 7 - How to Begin a Game")["role"] == "head"
    assert find(p250, "366")["role"] == "label"
    assert find(p250, "8.,hd5?")["role"] == "moves"
    texts = [ln["text"] for ln in p250]
    assert texts.index("... 0-1") < texts.index("In this well-known theoretical position (arising")


def test_other_pages(doc, fonts):
    p14 = pt.page_lines(doc, 13, fonts)
    assert find(p14, "Chapter 1")["role"] == "heading"
    assert find(p14, "1. THE CHESS BOARD AND PIECES")["role"] == "heading"
    p249 = pt.page_lines(doc, 248, fonts)
    # OCR junk over a board picture is board furniture, not a heading.
    assert not [ln for ln in p249 if ln["role"] == "heading"]
    p380 = pt.page_lines(doc, 379, fonts)
    circled = {ln["diagram"] for ln in p380 if ln["role"] == "label"}
    assert {"p380-4", "p380-5", "p380-6"} <= circled


def test_token_kind():
    moves = ["12.", "16...", "lO.", "24.\x18h6t!!", "8.,hd5?", "\x18fB", "0-0", "O-O-O",
             "1-0", "1/2-1/2", "e4", "Wfxe5", "\x14:x£8", "J\x1d:xf8t", "cx:d4", "b8=YlYt",
             "Nf3", "Sf3", "♘f3", "exd8=Q+"]
    for t in moves:
        assert pt.token_kind(t) == "move", t
    for t in ("that", "(or", "1st", "Queens"):
        assert pt.token_kind(t) == "word", t
    for t in ("...", "!!", "1924", "5"):
        assert pt.token_kind(t) == "neutral", t


def test_accepts_a_path():
    lines = pt.page_lines(str(PDF), 200)
    assert find(lines, "23J3e8t")["role"] == "moves"


# ------------------------------------------------------------------ another book

PROSE = ("The position in the diagram shows a typical idea that every player should know. "
         "White has developed his pieces quickly and now looks for a way to open lines "
         "against the black king, while Black hopes to complete his development in time. "
         "Such positions arise often in practice and deserve careful study by beginners.").split()


def make_book(path, chapters=3, pages_per_chapter=4, title_pages=True):
    """A small two-column book unlike the Primer: Times-Roman body, moves in
    Times-Bold at the same size, English piece letters, page numbers at the
    foot, chapter titles in 24 pt (or, without title_pages, chapters that
    only the running heads name) and one board picture per page."""
    doc = pymupdf.open()
    W, H = 420, 600
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 64, 64), False)
    pix.clear_with(255)
    for r in range(8):
        for c in range(8):
            if (r + c) % 2:
                pix.set_rect(pymupdf.IRect(c * 8, r * 8, c * 8 + 8, r * 8 + 8), (110,))
    state = {"word": 0, "move": 1, "pno": 1}

    def prose(page, x, y, chars=30):
        out = []
        while len(" ".join(out)) < chars:
            out.append(PROSE[state["word"] % len(PROSE)])
            state["word"] += 1
        page.insert_text((x, y), " ".join(out), fontname="tiro", fontsize=10)

    def folio(page):
        page.insert_text((W / 2 - 5, H - 25), str(state["pno"]), fontname="tiro", fontsize=9)
        state["pno"] += 1

    page = doc.new_page(width=W, height=H)
    page.insert_text((80, 120), "A Little Chess Book", fontname="tiro", fontsize=26)
    page = doc.new_page(width=W, height=H)
    page.insert_text((40, 60), "Contents", fontname="tiro", fontsize=20)
    for ch in range(1, chapters + 1):
        page = doc.new_page(width=W, height=H)
        if title_pages:
            page.insert_text((40, 80), f"Chapter {ch}", fontname="tiro", fontsize=24)
            page.insert_text((40, 115), ["Endings", "First Steps", "The Middlegame"][ch % 3],
                             fontname="tiro", fontsize=18)
        for k in range(20):
            prose(page, 40, 170 + 13 * k, 60)
        folio(page)
        for _ in range(pages_per_chapter):
            page = doc.new_page(width=W, height=H)
            page.insert_text((40, 30), f"Chapter {ch} - Lessons", fontname="tiro", fontsize=9)
            for ci, x0 in enumerate((40, 220)):
                y = 60
                if ci == 0:
                    page.insert_text((x0 + 60, y), "12", fontname="tibo", fontsize=10)
                    names = "Smith - Jones, "
                    page.insert_text((x0, y + 14), names, fontname="tibo", fontsize=10)
                    page.insert_text((x0 + pymupdf.get_text_length(names, "tibo", 10), y + 14),
                                     "London 1901", fontname="tiro", fontsize=10)
                    rect = pymupdf.Rect(x0 + 10, y + 22, x0 + 130, y + 142)
                    page.insert_image(rect, pixmap=pix)
                    for k, f in enumerate("abcdefgh"):
                        page.insert_text((rect.x0 + 6 + 15 * k, rect.y1 + 9), f,
                                         fontname="helv", fontsize=7)
                    for k in range(8):
                        page.insert_text((rect.x0 - 7, rect.y0 + 10 + 15 * k), str(8 - k),
                                         fontname="helv", fontsize=7)
                    page.insert_text((rect.x0 + 30, rect.y1 + 24), "White to move",
                                     fontname="tiro", fontsize=10)
                    y = rect.y1 + 44
                else:
                    page.insert_text((x0 + 20, y), "SECTION ONE", fontname="tibo", fontsize=11)
                    y += 18
                while y < H - 60:
                    m = state["move"]
                    kind = (y // 13) % 4
                    if kind == 0:
                        page.insert_text((x0, y), f"{m}.e4 e5 {m + 1}.Nf3 Nc6 {m + 2}.Bb5 a6",
                                         fontname="tibo", fontsize=10)
                        state["move"] += 3
                    elif kind == 1:
                        page.insert_text((x0, y), f"Or {m}...Nf6 {m + 1}.O-O Be7 with play.",
                                         fontname="tiro", fontsize=10)
                    else:
                        prose(page, x0, y)
                    y += 13
            folio(page)
    doc.save(path)


def test_another_book_layout(tmp_path):
    path = tmp_path / "little.pdf"
    make_book(path)
    doc = pymupdf.open(path)
    fonts = pt.book_fonts(doc)
    assert fonts["body"] == {"font": "Times-Roman", "size": 10.0}
    assert fonts["moves"] == [{"font": "Times-Bold", "size": 10.0}]
    lay = fonts["layout"]
    assert lay["foot_base_min"] is not None and lay["head_base_max"] is not None
    assert lay["gutter"]["odd"] is not None and 200 < lay["gutter"]["odd"] < 220
    s = pt.book_structure(doc)
    assert [c["label"] for c in s["chapters"]] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert s["chapters"][0]["title"] == "Chapter 1: First Steps"
    assert s["front_matter_end"] == 2 and s["chapters"][-1]["end"] == doc.page_count
    assert any(x["title"] == "SECTION ONE" for x in s["chapters"][0]["sections"])
    lines = pt.page_lines(doc, 3, fonts)
    roles = {ln["text"]: ln["role"] for ln in lines}
    assert roles["Chapter 1 - Lessons"] == "head" and roles["2"] == "head"
    assert roles["12"] == "label"
    assert roles["Smith - Jones, London 1901"] == "game_header"
    assert roles["White to move"] == "caption"
    assert roles["SECTION ONE"] == "heading"
    assert all(ln["role"] == "coord" for ln in lines if ln["text"] in list("abcdefgh"))
    assert {ln["role"] for ln in lines if ln["text"].startswith("Or ")} == {"text"}
    move_lines = [ln for ln in lines if ln["text"].endswith("Bb5 a6")]
    assert move_lines and all(ln["role"] == "moves" for ln in move_lines)
    caption = next(i for i, ln in enumerate(lines) if ln["text"] == "White to move")
    assert lines[caption + 1]["role"] == "text"          # prose below is not a caption
    cols = [ln["col"] for ln in lines if ln["role"] != "head"]
    assert cols == sorted(cols) and set(cols) == {1, 2}


def test_chapters_from_running_heads(tmp_path):
    path = tmp_path / "plain.pdf"
    make_book(path, title_pages=False)
    s = pt.book_structure(pymupdf.open(path))
    got = [(c["label"], c["start"], c["end"]) for c in s["chapters"]]
    assert got == [("Chapter 1", 3, 7), ("Chapter 2", 8, 12), ("Chapter 3", 13, 17)]
    assert s["front_matter_end"] == 2


def test_whole_book_under_a_minute():
    fresh = pymupdf.open(PDF)          # no cached extraction
    t0 = time.perf_counter()
    structure = pt.book_structure(fresh)
    fonts = pt.book_fonts(fresh)
    total = 0
    for i in range(fresh.page_count):
        total += len(pt.page_lines(fresh, i, fonts))
    elapsed = time.perf_counter() - t0
    print(f"book_structure + page_lines over {fresh.page_count} pages: {elapsed:.1f} s, "
          f"{total} lines")
    assert structure["chapters"] and total > 10000
    assert elapsed < 60
