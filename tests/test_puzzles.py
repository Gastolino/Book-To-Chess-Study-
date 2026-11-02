"""Tests for the puzzle books (assemble.puzzle_index, reader.chapter_data).

A generated puzzle book (ten numbered boards over three pages, their
solutions keyed by the same numbers in a chapter of their own) is found to
be a puzzle book and each puzzle is tied to its solution; the little game
book of test_assemble is not.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from chessbook import reader  # noqa: E402
from chessbook.assemble import build_book, puzzle_index  # noqa: E402
from test_assemble import COLS, ENDING_FEN, H, _Writer, make_book  # noqa: E402

# the positions of the puzzles: a rook ending (1.Rd8+ Kh7 2.Rd7) and a mate on the back rank (1.Ra8#)
ROOK_FEN = ENDING_FEN
MATE_FEN = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
KNIGHT_FEN = "6k1/5ppp/8/6N1/8/8/5PPP/6K1 w - - 0 1"
SOLUTIONS = {k: ("1.Rd8+ Kh7 2.Rd7" if k % 2 else "1.Ra8#") for k in range(1, 9)}


def puzzle_fens():
    """The diagram ids of the puzzles and their positions (diagram_fens)."""
    out = {}
    for k in range(1, 11):
        page, i = 3 + (k - 1) // 4, (k - 1) % 4 + 1
        out[f"p{page}-{i}"] = (ROOK_FEN if k % 2 else MATE_FEN) if k <= 8 else KNIGHT_FEN
    return out


def make_puzzle_book(path):
    """A puzzle book in the manner of make_day_book: a title page, the
    contents, ten boards labelled 1 to 10 on pages 3 to 5 (two to a column),
    then a chapter "Solutions" (page 6) that gives the solutions under a
    heading "SOLUTIONS", each after its number: puzzles 1 to 8 as numbered
    moves (the first with a side line, "Or 1.Rd7"), puzzle 9 in words
    ("9. Nf6+ wins the queen."), and none for puzzle 10. Two pages of text
    follow, so that the statistics have enough to learn from."""
    w = _Writer()
    w.page(head=False)
    w.pg.insert_text((80, 120), "Ten Puzzles", fontname="tiro", fontsize=26)
    w.page(head=False)
    w.pg.insert_text((40, 60), "Contents", fontname="tiro", fontsize=20)
    w.pg.insert_text((40, 90), "Chapter 1 First Steps 3", fontname="tiro", fontsize=10)
    w.pg.insert_text((40, 105), "Chapter 2 Solutions 6", fontname="tiro", fontsize=10)
    k = 1
    for j in range(3):
        w.page(head=j > 0)
        if j == 0:
            w.pg.insert_text((40, 50), "Chapter 1", fontname="tiro", fontsize=20)
            w.pg.insert_text((150, 50), "First Steps", fontname="tiro", fontsize=16)
        for c in (0, 1):
            w.col(c)
            for _ in range(2):
                if k <= 10:
                    w.picture(str(k))
                    k += 1
    w.page(head=False)
    w.pg.insert_text((40, 80), "Chapter 2", fontname="tiro", fontsize=24)
    w.pg.insert_text((40, 112), "Solutions", fontname="tiro", fontsize=18)
    w.y = 150
    w.line("SOLUTIONS", bold=True, size=11, x=COLS[0] + 40)
    for k in range(1, 9):
        w.line(f"{k}. {SOLUTIONS[k]}", bold=True)
        if k == 1:
            w.line("Or 1.Rd7 is slower.", indent=8)
    w.line("9. Nf6+ wins the queen.")
    w.prose(until=H - 60)
    w.col(1)
    w.y = 150
    w.prose(until=H - 60)
    for _ in range(2):
        w.page()
        w.prose(n=10)
        w.line("1.d4 d5 2.c4 e6 3.Nc3 Nf6", bold=True)
        w.prose(until=H - 60)
        w.col(1)
        w.prose(until=H - 60)
    w.save(path)
    return path


@pytest.fixture(scope="module")
def puzzles(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("puzzles")
    pdf = make_puzzle_book(tmp / "puzzles.pdf")
    book = build_book(pdf, output_dir=tmp / "output", books_dir=tmp / "books",
                      diagram_fens=puzzle_fens())
    return tmp, pdf, book


def test_a_puzzle_book_is_found(puzzles):
    """Ten numbered boards with their solutions in a chapter of solutions: the
    book is likely a puzzle book, and each puzzle has its solution, as a line
    (puzzles 1 to 8, with the side line of the first), as a sentence (9), or
    none (10)."""
    _, _, book = puzzles
    pz = book["puzzles"]
    assert pz["likely"] is True and 0.9 <= pz["score"] <= 1
    assert pz["reasons"] == {"boards": 10, "puzzles": 10, "tied": 9, "sections": 2}
    items = pz["items"]
    assert [it["label"] for it in items] == [str(k) for k in range(1, 11)]
    assert [it["diagram"] for it in items] == list(puzzle_fens())
    first = items[0]
    assert (first["page"], first["chapter"], first["start_fen"]) == (3, 1, ROOK_FEN)
    sol = first["solution"]
    assert (sol["line"], sol["page"], sol["chapter"], sol["status"]) == ("L1", 6, 2, "ok")
    assert sol["main"] == [["Rd8+", "d1d8"], ["Kh7", "g8h7"], ["Rd7", "d8d7"]]
    assert sol["main"][0][1] == "d1d8"
    assert sol["alts"] == [["Rd7", "d1d7"]]
    assert [it["solution"]["main"] for it in items[1:8:2]] == [[["Ra8#", "a1a8"]]] * 4
    assert items[8]["solution"] == {"note": "9. Nf6+", "page": 6, "san": ["Nf6+"]}
    assert items[9]["solution"] is None


def test_the_fields_puzzles_read(puzzles):
    """The diagrams carry the side printed with them and their series, and the
    lines the number of the exercise they solve."""
    _, _, book = puzzles
    d = book["pages"][2]["diagrams"][0]
    assert {"side", "series"} <= set(d) and d["side"] is None and d["series"] == "main"
    by_id = {L["id"]: L for L in book["lines"]}
    assert [by_id[f"L{k}"]["exercise"] for k in range(1, 9)] == [str(k) for k in range(1, 9)]
    assert [by_id[f"L{k}"]["diagram"] for k in range(1, 9)] == list(puzzle_fens())[:8]


def test_a_game_book_is_not_a_puzzle_book(tmp_path):
    """The little book of games: its two exercises are puzzles with their
    solutions (L3 and L4), the diagram whose line starts on its own page is
    not, and the book is no puzzle book; a second chapter of games adds no
    puzzle."""
    pdf = make_book(tmp_path / "little.pdf")
    book = build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books")
    pz = book["puzzles"]
    assert pz["likely"] is False
    assert [it["diagram"] for it in pz["items"]] == ["p6-1", "p6-2"]
    assert [it["solution"]["line"] for it in pz["items"]] == ["L3", "L4"]
    assert pz["reasons"]["boards"] == 3 and pz["reasons"]["puzzles"] == 2
    # the solutions wait for their positions: the printed moves, no uci
    assert pz["items"][0]["solution"]["main"][:2] == [["Rd8+", None], ["Kh7", None]]
    pdf2 = make_book(tmp_path / "second.pdf", second=True)
    book2 = build_book(pdf2, output_dir=tmp_path / "output2", books_dir=tmp_path / "books2")
    assert book2["puzzles"]["likely"] is False
    assert [it["diagram"] for it in book2["puzzles"]["items"]] == ["p6-1", "p6-2"]


def test_puzzle_index_again(puzzles):
    """puzzle_index gives the same from book.json alone (the browser app's
    corrections bring the book up to date without the builder's records)."""
    _, _, book = puzzles
    again = puzzle_index(dict(book))
    assert again == book["puzzles"]


def test_chapter_data_copies_the_solutions(puzzles):
    """The reader's data of the chapter of puzzles holds its ten puzzles with
    their solutions, though the solution lines are in the chapter of
    solutions; that chapter's data holds the puzzles its lines solve (not
    printed there) and the moves of those lines, each with its puzzle."""
    _, _, book = puzzles
    ch1, ch2 = book["chapters"][1], book["chapters"][2]
    d1 = reader.chapter_data(book, ch1, "")
    assert [it["label"] for it in d1["puzzles"]] == [str(k) for k in range(1, 11)]
    assert all(it["here"] for it in d1["puzzles"])
    first = d1["puzzles"][0]["solution"]
    assert first["chapter"] == 2 and first["line"] not in d1["lines"]
    assert first["main"][0] == ["Rd8+", "d1d8"]
    assert d1["puzzleBook"] == {"likely": True, "score": book["puzzles"]["score"],
                                "reasons": book["puzzles"]["reasons"], "count": 10}
    assert d1["solNodes"] == {}
    d2 = reader.chapter_data(book, ch2, "")
    assert [it["label"] for it in d2["puzzles"]] == [str(k) for k in range(1, 9)]
    assert not any(it["here"] for it in d2["puzzles"])
    l1 = d2["lines"]["L1"]
    sol = {nid for nid, did in d2["solNodes"].items() if did == "p3-1"}
    assert sol and all(d2["nodes"][nid]["line"] == "L1" for nid in sol)
    assert l1["root"] not in d2["solNodes"]
