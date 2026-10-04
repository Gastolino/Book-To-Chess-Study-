"""Tests for lines that go on after a digression or across pages, for moves
printed in long notation, and for the reader's corrections that join and
split lines (connect, disconnect), applied live and by a fresh build.

Small books generated here (one column, Times-Roman notes, Times-Bold moves,
a running head and a page number on every page) check each rule exactly.
"""
import json
import sys
from pathlib import Path

import chess
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from chessbook import corrections as fixes  # noqa: E402
from chessbook import live, reader  # noqa: E402
from chessbook.assemble import _LONG_TEXT_RE, _RANGE_AFTER_RE, _RANGE_BEFORE_RE, build_book  # noqa: E402
from chessbook.movetext import Token, decode, find_sequences, tokenize  # noqa: E402
from test_corrections import GARBLED, NOTE, game_nodes, key_of  # noqa: E402
from test_assemble import make_book  # noqa: E402
from test_start_choice import ENDING, _Book, _front, _line_with, _main_line, _sans  # noqa: E402

RUY = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4"]


def _build(tmp_path, b, fens=None, corrections=None, state=None):
    pdf = b.save(tmp_path / "lines.pdf")
    return build_book(pdf, output_dir=tmp_path / "out", books_dir=tmp_path / "books",
                      diagram_fens=fens or {}, corrections=corrections, state=state)


# ------------------------------------------------------------------ the tokenizer

@pytest.mark.parametrize("text,dotless", [
    ("We return to the game: 4… e4 5.Nd4", False),
    ("We return to the game: 4…e4 5.Nd4", False),
    ("We return to the game: 4...e4 5.Nd4", False),
    ("We return to the game: 4. . . e4 5.Nd4", False),
    ("We return to the game: 4 ... e4 5 Nd4", True),
    ("We return to the game: 4 … e4 5 Nd4", True),
    ("We return to the game: 4 . . . e4 5 Nd4", True),
])
def test_black_move_numbers(text, dotless):
    """Black's numbered move reads with an ellipsis character, three dots,
    spaced dots, and in books that print numbers without a dot."""
    (seq,) = find_sequences(text, dotless=dotless)
    moves = [(t.raw, t.number, t.black) for t in seq.tokens if t.kind == "move"]
    assert moves == [("e4", 4, True), ("Nd4", 5, False)]


@pytest.mark.parametrize("text,move", [
    ("1 e2-e4", "e2-e4"), ("2.Ng1-f3", "Ng1-f3"), ("3.Bf1–b5", "Bf1–b5"), ("4.Nb1—c3", "Nb1—c3"),
    ("5.d2xd3", "d2xd3"), ("5.d2:d3", "d2:d3"), ("6.0-0", "0-0"),
])
def test_long_notation_tokens(text, move):
    toks = [t for t in tokenize(text, dotless=True) if t.kind == "move"]
    assert [t.raw for t in toks] == [move]


@pytest.mark.parametrize("raw,fen,san", [
    ("Ng1-f3", chess.STARTING_FEN, "Nf3"),
    ("e2-e4", chess.STARTING_FEN, "e4"),
    ("Bf1–b5", "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "Bb5"),
    ("e4xd5", "rnbqkbnr/ppp2ppp/8/3pp3/4P3/3P4/PPP2PPP/RNBQKBNR w KQkq - 0 3", "exd5"),
    ("e4:d5", "rnbqkbnr/ppp2ppp/8/3pp3/4P3/3P4/PPP2PPP/RNBQKBNR w KQkq - 0 3", "exd5"),
    ("tLlg1-f3", "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "Nf3"),
    # the square the piece leaves is printed: another square is no reading
    ("Nb1-f3", chess.STARTING_FEN, None),
    ("d2-e4", chess.STARTING_FEN, None),
    ("Bf1-d4", "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", None),
])
def test_long_notation_is_strict(raw, fen, san):
    (d,) = decode(chess.Board(fen), [Token("move", raw, 0, len(raw))], insert=False)
    assert d.san == san


@pytest.mark.parametrize("text,found", [
    ("after Black has committed himself with ...e7-e6.", ["e7-e6"]),
    ("the move e2-e4 is the most popular", ["e2-e4"]),
    ("White plays Bf1–b5 at once", ["f1–b5"]),
    ("with the idea Nf3-d2-c4", ["f3-d2-c4"]),
    ("the a1-h8 diagonal", []),
    ("along the c4-g8 diagonal", []),
    ("see pages 12-14", []),
    ("it takes 2-3 moves", []),
    ("and won, 1-0", []),
    ("only three squares on the short diagonal (a6-c8)", []),
    ("since the diagonals a2-g8 and e8-h5 are opened up", []),
])
def test_long_notation_in_prose(text, found):
    """Moves in long notation inside sentences are found; ranges are not."""
    got = [m.group(3) for m in _LONG_TEXT_RE.finditer(text)
           if not _RANGE_AFTER_RE.match(text[m.end(3):m.end(3) + 20])
           and not _RANGE_BEFORE_RE.search(text[max(0, m.start(2) - 32):m.start(2)])]
    assert got == found


# ------------------------------------------------------------------ resumed lines

def _ruy_book(resume, cue=""):
    """A game stops after White's fourth move; a diagram with a line of its
    own follows; then the text resumes with Black's fourth move."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(2)
    b.line("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4", bold=True)
    b.prose(3)
    b.pictures("Diagram 1")
    b.line("White wins in this ending.")
    b.line("1.Rd8+ Kh7 2.Rd7", bold=True)
    b.prose(3)
    b.line("We return to the game.")
    if "…" in resume:
        _with_ellipsis(b, cue + resume)
    else:
        b.line(cue + resume, bold=True)
    b.prose(3)
    return b


SERIF_BOLD = [Path(p) for p in ("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
                                "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf")]


def _with_ellipsis(b, text):
    """A line of moves in Times-Bold whose ellipsis (U+2026) is set in a
    TrueType font, since the base-14 fonts cannot encode it."""
    import pymupdf
    font = next((f for f in SERIF_BOLD if f.exists()), None)
    if font is None:
        pytest.skip("no TrueType serif font with an ellipsis")
    x = 50
    for part in text.replace("…", "\0…\0").split("\0"):
        if not part:
            continue
        if part == "…":
            b.pg.insert_text((x, b.y), part, fontname="ell", fontfile=str(font), fontsize=10)
            x += pymupdf.Font(fontfile=str(font)).text_length(part, 10)
        else:
            b.pg.insert_text((x, b.y), part, fontname="tibo", fontsize=10)
            x += pymupdf.get_text_length(part, "tibo", 10)
    b.y += 14


@pytest.mark.parametrize("resume", ["4...Nf6 5.O-O Be7", "4…Nf6 5.O-O Be7", "4. . . Nf6 5.O-O Be7"])
def test_resumed_line_continues_the_game(tmp_path, resume):
    book = _build(tmp_path, _ruy_book(resume), {"p3-1": ENDING})
    game = _line_with(book, "Ba4")
    assert _sans(book, game) == RUY + ["Nf6", "O-O", "Be7"]
    ending = _line_with(book, "Rd8+")
    assert ending["id"] != game["id"] and _sans(book, ending) == ["Rd8+", "Kh7", "Rd7"]
    assert len(book["lines"]) == 2


def test_resumed_line_in_a_dotless_book(tmp_path):
    b = _Book()
    _front(b)
    b.page()
    b.prose(2)
    for _ in range(3):              # enough dotless pairs for the book to read them so
        b.line("1 e4 e5 2 Nf3 Nc6 3 Bb5 a6 4 Ba4", bold=True)
        b.prose(2)
    b.pictures("Diagram 1")
    b.line("White wins in this ending.")
    b.line("1 Rd8+ Kh7 2 Rd7", bold=True)
    b.prose(3)
    b.line("We return to the game.")
    b.line("4 ... Nf6 5 O-O Be7", bold=True)
    b.prose(2)
    book = _build(tmp_path, b, {"p3-1": ENDING})
    assert book["numbering"]["dotless"]
    assert any(_sans(book, L) == RUY + ["Nf6", "O-O", "Be7"] for L in book["lines"])


def test_alternative_is_not_a_resumption(tmp_path):
    """"Or 4...d6" offers another move: it does not continue the game."""
    book = _build(tmp_path, _ruy_book("4...d6 5.c3 Bd7", cue="Or "), {"p3-1": ENDING})
    game = _line_with(book, "Ba4")
    assert _sans(book, game) == RUY


# ------------------------------------------------------------------ lines across pages

def _two_pages(between=None):
    """A game that starts at the foot of one page and goes on at the top of the
    next one, below the running head; the page number stands at the foot."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(30)
    b.line("1.e4 e5 2.Nf3 Nc6", bold=True)
    b.page()                         # running head "Chapter 1 - Endings", page number
    if between:
        between(b)
    b.line("3.Bb5 a6 4.Ba4 Nf6", bold=True)
    b.prose(3)
    return b


def test_line_goes_on_across_a_page_break(tmp_path):
    book = _build(tmp_path, _two_pages())
    (line,) = [L for L in book["lines"] if "Bb5" in _sans(book, L)]
    assert _sans(book, line) == RUY + ["Nf6"]
    assert line["end_page"] == line["page"] + 1


def test_line_goes_on_across_a_page_break_after_notes(tmp_path):
    """Notes at the top of the next page (with a move of their own) do not
    end the line."""
    def notes(b):
        b.prose(2)
        b.line("Here 2...d6 is a quieter choice for Black.")
        b.prose(1)
    book = _build(tmp_path, _two_pages(notes))
    (line,) = [L for L in book["lines"] if "Bb5" in _sans(book, L)]
    assert _sans(book, line) == RUY + ["Nf6"]


def test_reader_opens_a_page_at_the_governing_line(tmp_path):
    """The chapter reader of a page that opens mid-line lists that line and
    shows it (checked in Chromium by tests/pencil_e2e.js); here: the line's
    pages cover both pages, and its nodes are in the chapter's data."""
    pdf = _two_pages().save(tmp_path / "two.pdf")
    book = build_book(pdf, output_dir=tmp_path / "out", books_dir=tmp_path / "books")
    (line,) = [L for L in book["lines"] if "Bb5" in _sans(book, L)]
    assert line["page"] < line["end_page"]
    for ch in book["chapters"]:
        if ch["start"] <= line["end_page"] <= ch["end"]:
            data = reader.chapter_data(book, ch, "")
            assert line["id"] in data["lines"]
            nodes = [n for n in data["nodes"].values() if n["line"] == line["id"]]
            assert {n["page"] for n in nodes if n["page"]} == {line["page"], line["end_page"]}


# ------------------------------------------------------------------ connect and disconnect

@pytest.fixture()
def garbled(tmp_path):
    pdf = make_book(tmp_path / "garbled.pdf", game=GARBLED, note7=NOTE)
    state = {}
    book = build_book(pdf, output_dir=tmp_path / "out", books_dir=tmp_path / "books", state=state)
    return tmp_path, pdf, book, state


def _fresh(tmp, pdf, fix):
    return build_book(pdf, output_dir=tmp / "out", books_dir=tmp / "books", corrections=fix)


def _comparable(b):
    st = {k: v for k, v in b["stats"].items() if "seconds" not in k}
    return ({k: b[k] for k in ("lines", "nodes", "unattached", "dismissed", "attached", "waiting",
                               "symbols", "chapters")}, st,
            [p["marks"] for p in b["pages"]], [p["diagrams"] for p in b["pages"]])


def _game_sans(book, title="Smith - Jones"):
    line = next(L for L in book["lines"] if L["title"].startswith(title))
    return [book["nodes"][n]["san"] for n in _main_line(book, line)]


def test_disconnect_then_connect_back(garbled):
    tmp, pdf, book, state = garbled
    _, nodes = game_nodes(book)
    base = {"moves": {key_of(nodes, "Zq9"): {"san": "Nxd5"}}}
    nxf7 = key_of(nodes, "tLlxf7")
    nxd5 = key_of(nodes, "Zq9")
    # a new line from 6.Nxf7, from the position before it
    split = dict(base, disconnect={nxf7: {"start": "here"}})
    res = live.apply(state, book, split)
    assert set(res["lines"]) >= {"L1", "L1-1"}
    assert _game_sans(book)[-1] == "Nxd5"
    new = next(L for L in book["lines"] if L["id"] == "L1-1")
    first = book["nodes"][_main_line(book, new)[0]]
    assert first["san"] == "Nxf7" and first["corrected"] == "split"
    assert new["start_fen"] == book["nodes"][[n for n in _main_line(
        book, next(L for L in book["lines"] if L["id"] == "L1"))][-1]]["fen"]
    assert book["stats"]["corrected"]["splits"] == 1
    assert _comparable(book) == _comparable(_fresh(tmp, pdf, split))
    # joined again after 5...Nxd5: the game reads to its end once more
    joined = dict(split, connect={nxf7: {"after": nxd5}})
    live.apply(state, book, joined)
    assert _game_sans(book)[-5:] == ["Nxf7", "Kxf7", "Qf3+", "Ke6", "Nc3"]
    assert not any(L["id"] == "L1-1" for L in book["lines"])
    nx = next(n for n in book["nodes"].values() if n.get("key") == nxf7)
    assert nx["corrected"] == "connected"
    assert book["stats"]["corrected"]["connections"] == 1
    assert _comparable(book) == _comparable(_fresh(tmp, pdf, joined))


def test_not_part_of_the_line_and_an_illegal_connection(garbled):
    tmp, pdf, book, state = garbled
    _, nodes = game_nodes(book)
    nxf7 = key_of(nodes, "tLlxf7")
    e4 = next(n["key"] for n in nodes if n["san"] == "e4")
    gone = {"disconnect": {nxf7: {"remove": True}}}
    live.apply(state, book, gone)
    assert "Nxf7" not in _game_sans(book) and "Kxf7" not in _game_sans(book)
    u = next(u for u in book["unattached"] if u["key"] == nxf7)
    assert "not part of the line" in u["reason"]
    # joined after 1.e4 the moves are not legal: the reason says so in words
    bad = dict(gone, connect={nxf7: {"after": e4}})
    live.apply(state, book, bad)
    u = next(u for u in book["unattached"] if u["key"] == nxf7)
    assert "is not a legal move for Black after 1.e4" in u["reason"]
    assert _comparable(book) == _comparable(_fresh(tmp, pdf, bad))


def test_connection_from_a_move_inside_the_line_makes_a_variation(garbled):
    """Joined after a move that the main line goes on from, the moves form a
    variation there: 8.Nc3, taken out as a line of its own, joined after
    6...Kxf7 is the alternative 7.Nc3."""
    tmp, pdf, book, state = garbled
    _, nodes = game_nodes(book)
    nc3 = key_of(nodes, "tLlc3")
    kxf7 = next(n["key"] for n in nodes if n["san"] == "Kxf7")
    fix = {"glyphs": {"tLl": "N"}, "moves": {key_of(nodes, "Zq9"): {"san": "Nxd5"}},
           "disconnect": {nc3: {"start": "here"}}, "connect": {nc3: {"after": kxf7}}}
    live.apply(state, book, fix)
    assert _comparable(book) == _comparable(_fresh(tmp, pdf, fix))
    assert _game_sans(book)[-3:] == ["Kxf7", "Qf3+", "Ke6"]
    n = next(n for n in book["nodes"].values() if n.get("key") == nc3)
    assert n["corrected"] == "connected" and n["san"] == "Nc3" and not n["main"]
    assert book["nodes"][n["parent"]]["san"] == "Kxf7"


def test_corrections_schema_for_lines():
    data = fixes.normalise({"connect": {"3:10,20:e4": {"after": "2:30,40:Nf3"}},
                            "disconnect": {"3:50,60:Qh5": {"start": "p3-1"},
                                           "3:70,80:Rd1": {"remove": 1},
                                           "3:90,90:Kf2": {}}})
    assert data["connect"] == {"3:10,20:e4": {"after": "2:30,40:Nf3"}}
    assert data["disconnect"] == {"3:50,60:Qh5": {"start": "p3-1"}, "3:70,80:Rd1": {"remove": True},
                                  "3:90,90:Kf2": {"start": "here"}}
    with pytest.raises(ValueError):
        fixes.normalise({"connect": {"3:10,20:e4": {"after": "3:10,20:e4"}}})
    with pytest.raises(ValueError):
        fixes.normalise({"disconnect": {"3:10,20:e4": {"start": "the top"}}})


# ------------------------------------------------------------------ live corrections

def test_live_move_correction_equals_a_fresh_build(garbled):
    tmp, pdf, book, state = garbled
    ch = book["chapters"][1]
    before = reader.chapter_data(book, ch, "")
    _, nodes = game_nodes(book)
    fix = {"moves": {key_of(nodes, "Zq9"): {"san": "Nxd5"}}, "glyphs": {"tLl": "N"}}
    res = live.apply(state, book, fix, chapters={1})
    assert res["pending"] == [] and "L1" in res["lines"]
    patch, after = live.chapter_patch(book, ch, before)
    zq9 = next(n for n in after["nodes"].values() if n["raw"] == "Zq9")
    assert zq9["san"] == "Nxd5" and zq9["corrected"] == "move"
    assert zq9["id"] in patch["nodes"]
    # the moves after it are decoded in the patch
    nxt = after["nodes"][zq9["children"][0]]
    assert nxt["san"] == "Nxf7" and nxt["status"] == "ok"
    assert _comparable(book) == _comparable(_fresh(tmp, pdf, fix))


def test_live_glyph_correction_chapter_by_chapter(garbled):
    """A piece symbol reaches the open chapter first; the others are pending
    until a later call replays them."""
    tmp, pdf, book, state = garbled
    res = live.apply(state, book, {"glyphs": {"tLl": "N"}}, chapters={0})
    assert res["pending"] == [1]
    res = live.apply(state, book, {"glyphs": {"tLl": "N"}}, chapters={1})
    assert res["pending"] == []
    assert _comparable(book) == _comparable(_fresh(tmp, pdf, {"glyphs": {"tLl": "N"}}))


def test_driver_applies_a_correction(garbled, monkeypatch):
    """The browser app's worker functions (web/driver.py), run here in
    CPython: a correction comes back as a patch for the open chapter."""
    tmp, pdf, book, state = garbled
    sys.path.insert(0, str(ROOT / "web"))
    import driver
    monkeypatch.setattr(driver, "OUT", tmp / "app-out")
    monkeypatch.setattr(driver, "CFG", tmp / "app-cfg")
    driver.process(str(pdf), lambda *_: None)
    html = driver.chapter("ch01.html", lambda *_: None)
    assert "id=\"penbtn\"" in html
    _, nodes = game_nodes(driver.STATE["book"])
    fix = {"moves": {key_of(nodes, "Zq9"): {"san": "Nxd5"}}}
    out = json.loads(driver.correct(json.dumps(fix), "ch01.html"))
    zq9 = next(n for n in out["patch"]["nodes"].values() if n["raw"] == "Zq9")
    assert zq9["san"] == "Nxd5"
    assert out["pending"] == [] and out["seconds"] < 5
    saved = fixes.load(pdf, tmp / "app-cfg")
    assert saved["moves"] == fix["moves"]
    # reading the book again with the saved corrections gives the same book
    fresh = _fresh(tmp, pdf, saved)
    assert _comparable(driver.STATE["book"]) == _comparable(fresh)
