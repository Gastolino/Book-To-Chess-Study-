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


# ------------------------------------------------------------------ styles of the move font

def _mixed(b, parts, x=None):
    """One printed line made of (text, font) parts: "tiro" notes, "tibo" main
    moves, "tiit" moves in italic."""
    import pymupdf
    x = 50 if x is None else x
    for text, font in parts:
        b.pg.insert_text((x, b.y), text, fontname=font, fontsize=10)
        x += pymupdf.get_text_length(text + " ", font, 10)
    b.y += 14


def _italic_book():
    """A game in bold whose notes name lines in italic, as books do that set
    the main moves and the moves of the notes in two styles of one family.
    Each note names deeper moves than the game has reached."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(2)
    b.line("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4", bold=True)
    _mixed(b, [("A sharper try is", "tiro"), ("6.d4 exd4 7.e5 Ne4 8.Nxd4", "tiit"),
               ("with play.", "tiro")])
    _mixed(b, [("Also", "tiro"), ("6.Qe2 b5 7.Bb3 d6 8.c3 O-O", "tiit"), ("is known.", "tiro")])
    b.prose(1)
    b.line("4...Nf6 5.O-O Be7 6.Re1 b5 7.Bb3 d6 8.c3 O-O 9.h3 Bb7", bold=True)
    b.prose(2)
    return b


def test_italic_moves_are_notes_not_the_main_line(tmp_path):
    """The italic move font is told from the bold one: its moves are notes,
    so they neither break the game with a gap nor continue it."""
    from chessbook import pdftext as pt
    pdf = _italic_book().save(tmp_path / "italic.pdf")
    fonts = pt.book_fonts(pdf)
    assert [f["font"] for f in fonts["moves"]] == ["Times-Bold"]
    assert [f["font"] for f in fonts["note_moves"]] == ["Times-Italic"]
    book = build_book(pdf, output_dir=tmp_path / "out", books_dir=tmp_path / "books",
                      diagram_fens={})
    game = _line_with(book, "Ba4")
    assert _sans(book, game) == RUY + ["Nf6", "O-O", "Be7", "Re1", "b5", "Bb3", "d6", "c3",
                                       "O-O", "h3", "Bb7"]
    main = [book["nodes"][n] for n in _main_line(book, game)]
    assert all(n["status"] == "ok" for n in main)


# ------------------------------------------------------------------ list labels

def test_list_label_is_not_a_move():
    """"A)" or "b)" opening a list of lines is no move of the run before it."""
    (seq,) = find_sequences("7.Nxd7 A) ")
    assert [t.raw for t in seq.tokens if t.kind == "move"] == ["Nxd7"]
    seqs = find_sequences("8.O-O g6 b) 9.c4 Nb6")
    assert [[t.raw for t in s.tokens if t.kind == "move"] for s in seqs] == [["O-O", "g6"],
                                                                             ["c4", "Nb6"]]


# ------------------------------------------------------------------ long notation in sentences

QGD = ["d4", "d5", "c4", "e6", "Nc3", "Nf6", "cxd5", "exd5", "Bg5", "Be7", "e3", "O-O"]


def _long_book(notes):
    b = _Book()
    _front(b)
    b.page()
    b.prose(1)
    b.line("1.d4 d5 2.c4 e6 3.Nc3 Nf6 4.cxd5 exd5 5.Bg5 Be7 6.e3 O-O", bold=True)
    for n in notes:
        b.line(n)
    b.prose(1)
    b.line("7.Bd3 Nbd7 8.Qc2 Re8", bold=True)
    b.prose(2)
    return b


def _long_marks(book, raw):
    return [m for p in book["pages"] for m in p["marks"] if m["raw"].rstrip(".,") == raw]


def test_long_move_alone_in_prose_stays_text(tmp_path):
    """A move in long notation named in a sentence ("the potential to gain
    space with f2-f4") is no variation and stands in no line: it is text."""
    book = _build(tmp_path, _long_book([
        "White has the potential to gain space with f2-f4 later on.",
        "It is a deterrence against White advancing e3-e4 at once."]))
    game = _line_with(book, "Bg5")
    assert _sans(book, game) == QGD + ["Bd3", "Nbd7", "Qc2", "Re8"]
    assert not _long_marks(book, "f2-f4") and not _long_marks(book, "e3-e4")
    assert not [u for u in book["unattached"] if "-" in u["text"]]


def test_long_move_after_a_cue_is_a_variation(tmp_path):
    """"Instead e3-e4" gives another move: a variation where the line stands."""
    book = _build(tmp_path, _long_book(["Instead e3-e4 would lose a pawn here."]))
    (m,) = _long_marks(book, "e3-e4")
    n = book["nodes"][m["node"]]
    assert n["san"] == "e4" and not n["main"] and not m.get("ref")
    assert book["nodes"][n["parent"]]["san"] == "O-O"


def test_long_moves_forming_a_line_are_a_variation(tmp_path):
    """Moves of both sides next to each other ("...c7-c5 and d4xc5") form a
    line: the first is a variation where the line stands, the second its
    reply."""
    book = _build(tmp_path, _long_book(["The thrust ...c7-c5 and d4xc5 is not to be feared."]))
    (c5,) = _long_marks(book, "c7-c5")
    n = book["nodes"][c5["node"]]
    assert n["san"] == "c5" and not n["main"] and book["nodes"][n["parent"]]["san"] == "e3"
    (dxc5,) = _long_marks(book, "d4xc5")
    assert book["nodes"][dxc5["node"]]["san"] == "dxc5"
    assert book["nodes"][dxc5["node"]]["parent"] == c5["node"]
    game = _line_with(book, "Bg5")
    assert _sans(book, game) == QGD + ["Bd3", "Nbd7", "Qc2", "Re8"]


def test_long_move_refers_to_the_move_played(tmp_path):
    """"The early c2-c4" names the move 2.c4 of the line: a link to it."""
    book = _build(tmp_path, _long_book(["The early c2-c4 fights for the centre."]))
    (m,) = _long_marks(book, "c2-c4")
    assert m.get("ref") and book["nodes"][m["node"]]["san"] == "c4"
    assert book["nodes"][m["node"]]["number"] == 2


def test_long_move_from_another_square_is_no_reference(tmp_path):
    """The line played c3-c4, not c2-c4: "c2-c4" names a move it did not
    play, and stays text."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(1)
    b.line("1.d4 d5 2.Nf3 Nf6 3.c3 e6 4.Bf4 Bd6 5.c4 O-O", bold=True)
    b.line("The plan with c2-c4 at once was simpler.")
    b.line("The move c3-c4 costs a tempo.")
    b.prose(1)
    book = _build(tmp_path, b)
    assert not _long_marks(book, "c2-c4")
    (m,) = _long_marks(book, "c3-c4")
    assert m.get("ref") and book["nodes"][m["node"]]["number"] == 5


def test_long_move_after_and_then_goes_on_with_the_variation(tmp_path):
    """"7.Bh4 and then ...b7-b6" goes on with the variation of the note; a
    move of the same side ("8.Bd3 and then Ng1-e2") is a plan inside the
    variation, and never a move of the main line."""
    book = _build(tmp_path, _long_book([
        "If 6...h6 7.Bh4 and then ...b7-b6, Black is solid.",
        "If 6...c6 7.Bd3 and then Ng1-e2, White is fine."]))
    (b6,) = _long_marks(book, "b7-b6")
    n = book["nodes"][b6["node"]]
    assert n["san"] == "b6" and not n["main"]
    assert book["nodes"][n["parent"]]["san"] == "Bh4"
    assert not _long_marks(book, "Ng1-e2")
    game = _line_with(book, "Bg5")
    assert _sans(book, game) == QGD + ["Bd3", "Nbd7", "Qc2", "Re8"]


# ------------------------------------------------------------------ game boundaries

def _colour_headers(b, white, black, place):
    for text in (f"White: {white}", f"Black: {black}", place):
        b.line(text, x=120)


def test_headers_one_player_a_line_start_a_game(tmp_path):
    """"White: ..." over "Black: ..." over the place and year is a game
    header: the moves under it are a new game, and a run under it that
    continues the numbering of the game before does not resume that game."""
    b = _Book()
    _front(b)
    b.page()
    _colour_headers(b, "A. Smith", "B. Jones", "London 1990")
    b.prose(1)
    b.line("1.e4 e5 2.Nf3 Nc6 3.Bb5", bold=True)
    b.prose(2)
    _colour_headers(b, "C. Brown", "D. Green", "Paris 1 991")
    b.prose(1)
    b.line("3...a6 4.Ba4 Nf6", bold=True)
    b.prose(1)
    b.line("1.d4 d5 2.c4 e6 3.Nc3 Nf6", bold=True)
    b.prose(1)
    book = _build(tmp_path, b)
    first = _line_with(book, "Bb5")
    assert first["title"] == "A. Smith - B. Jones, London 1990"
    assert first["header"]["white"] == "A. Smith" and first["header"]["year"] == "1990"
    assert _sans(book, first) == ["e4", "e5", "Nf3", "Nc6", "Bb5"]
    second = _line_with(book, "c4")
    assert second["title"] == "C. Brown - D. Green, Paris 1991" and second["kind"] == "game"


def test_colour_header_lines():
    from chessbook import pdftext as pt
    from chessbook.assemble import colour_header_merge
    assert pt.colour_header("White: V. Kramnik") == ("white", "V. Kramnik")
    assert pt.colour_header("Black: D.Sadvakasov") == ("black", "D.Sadvakasov")
    assert pt.colour_header("White: to play and win the game") is None
    assert pt.colour_header("White to move") is None
    h = colour_header_merge(None, "White: P.Nikolic")
    h = colour_header_merge(h, "Black: Y.Seirawan")
    h = colour_header_merge(h, "Skelleftea 1 989")
    assert (h["white"], h["black"], h["site"], h["year"]) == ("P.Nikolic", "Y.Seirawan",
                                                               "Skelleftea", "1989")
    assert h["text"] == "P.Nikolic - Y.Seirawan, Skelleftea 1989"
    assert colour_header_merge(h, "Astana 200]")["year"] == "2001"


def test_a_first_move_read_on_another_square_is_misplaced():
    """A first move read only by moving it to another square ("Qf1" for a
    printed "Bb2" whose bishop already stands there) does not fit the
    diagram: the diagram may show the position after it (choose_start)."""
    from types import SimpleNamespace as NS
    from chessbook.assemble import _misplaced
    assert _misplaced([NS(status="guessed", san="Qf1", raw=".il.b2")])
    assert not _misplaced([NS(status="guessed", san="Bb2", raw=".il.b2")])
    assert not _misplaced([NS(status="ok", san="Qf1", raw=".il.b2")])
    assert not _misplaced([NS(status="guessed", san="e5", raw="eS")])


def test_lost_game_takes_up_again_from_a_diagram(tmp_path):
    """A game whose moves stopped reading (here the text lacks move 5, so the
    position after it is unknown) does not swallow the moves printed after a
    diagram as unread moves, even when the printed run of moves goes on past
    the diagram: the moves after it start from the position it shows."""
    import pymupdf
    b = _Book()
    _front(b)
    b.page()
    b.line("A. Smith - B. Jones, London 1990", x=120)
    b.prose(1)
    b.line("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 6.Re1 b5", bold=True)
    # a board beside the text, between two lines of the same run of moves
    b.pg.insert_image(pymupdf.Rect(300, b.y - 11, 400, b.y + 89), pixmap=b.board)
    b.line("7.Rd7 Kh7 8.Rxf7 Kg6 9.Rb7", bold=True)
    b.y += 90
    b.prose(2)
    ending = ENDING.replace(" 0 1", " 0 7")
    book = _build(tmp_path, b, {"p3-1": ending})
    game = _line_with(book, "Ba4")
    assert _sans(book, game)[:8] == RUY + ["Nf6"]
    rest = _line_with(book, "Rxf7")
    assert rest["id"] != game["id"] and rest["diagram"] == "p3-1"
    assert _sans(book, rest) == ["Rd7", "Kh7", "Rxf7", "Kg6", "Rb7"]


def test_a_note_does_not_take_the_game_header(tmp_path):
    """A line that the notes start before the game's own moves (from a
    diagram printed under the header) leaves the header to the game."""
    b = _Book()
    _front(b)
    b.page()
    _colour_headers(b, "A. Smith", "B. Jones", "London 1990")
    b.pictures("Diagram 1")
    b.line("Here 1.Rd8+ Kh7 2.Rd7 would win at once.")
    b.prose(1)
    b.pictures("Diagram 2")
    b.line("1.Rd7 Kh7 2.Rxf7 Kg6 3.Rb7", bold=True)
    b.prose(1)
    book = _build(tmp_path, b, {"p3-1": ENDING, "p3-2": ENDING})
    game = _line_with(book, "Rxf7")
    assert game["title"] == "A. Smith - B. Jones, London 1990" and game["kind"] == "game"
    note = _line_with(book, "Rd8+")
    assert note["id"] != game["id"] and note["title"] == "Diagram 1"


def test_a_reference_names_the_same_kind_of_piece():
    """"b3-b4" (a pawn) does not name the king's move Kb3-b4."""
    from chessbook.assemble import _Builder
    assert _Builder.same_kind({"san": "b4"}, "P")
    assert not _Builder.same_kind({"san": "Kb4"}, "P")
    assert _Builder.same_kind({"san": "Nc3"}, "N")
    assert _Builder.same_kind({"san": "Nc3"}, None)


def test_unreadable_moves_before_a_run_are_not_skipped(tmp_path):
    """"14 0 exO 15 gxO h5" printed (and misread) between a diagram and "16
    Rd7": the diagram shows the position before move 14, so the line does
    not start with 16.Rd7 as if the diagram stood at move 16."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(1)
    b.pictures("Diagram 1")
    b.line("The game was soon agreed drawn:")
    b.line("14 0 exO 15 gxO h5")
    b.line("16.Rd7 Kh7 17.Rxf7 Kg6", bold=True)
    b.prose(2)
    book = _build(tmp_path, b, {"p3-1": ENDING})
    line = next(L for L in book["lines"] if L["diagram"] == "p3-1")
    first = book["nodes"][_main_line(book, line)[0]]
    assert first["status"] == "failed" and "move 14" in first["reason"]
    assert line["start_fen"].endswith(" w - - 0 14")


def test_a_run_in_a_bracket_continues_the_variation_before_it(tmp_path):
    """"(1...Kh7 is met by the waiting move 2.Rb7, ...)": 2.Rb7 goes on from
    1...Kh7, the variation before it in the same bracket, not from the move
    the bracket follows, whose own continuation comes after the bracket."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(1)
    b.pictures("Diagram 1")
    b.line("1.Rd8+ Kh7 2.Rd7", bold=True)
    b.line("Also possible is 1.Rd7 Kh8 (1...Kh7 is met by the waiting")
    b.line("move 2.Rb7, while if 1...f5 then 2.Rd8+) 2.Rxf7 and wins.")
    b.prose(1)
    book = _build(tmp_path, b, {"p3-1": ENDING})
    nodes = book["nodes"]
    rd7 = next(n for n in nodes.values() if n["san"] == "Rd7" and n["number"] == 1)
    replies = {nodes[c]["san"]: c for c in rd7["children"]}
    assert set(replies) == {"Kh8", "Kh7", "f5"}
    assert [nodes[c]["san"] for c in nodes[replies["Kh8"]]["children"]] == ["Rxf7"]
    assert [nodes[c]["san"] for c in nodes[replies["Kh7"]]["children"]] == ["Rb7"]
    assert [nodes[c]["san"] for c in nodes[replies["f5"]]["children"]] == ["Rd8+"]


def test_moves_after_a_diagram_in_a_run_that_starts_nowhere(tmp_path):
    """A run from move 1 that does not read from the initial position, with
    no diagram before it, goes on across a diagram: the moves after the
    diagram start from the position it shows. The diagram, printed among the
    moves the line has read, does not end the line, and a later run of the
    main font that reads where its numbering puts it is a variation there,
    even when it would also read at the line's end."""
    import pymupdf
    b = _Book()
    _front(b)
    b.page()
    b.prose(1)
    b.line("1.Rd1 Kg8 2.Rd2 Kh7 3.Rd3 Kg8 4.Rd7", bold=True)
    b.pg.insert_image(pymupdf.Rect(300, b.y - 11, 400, b.y + 89), pixmap=b.board)
    b.line("4...Kh8 5.Rxf7 Kg8 6.Rf3", bold=True)
    b.y += 90
    b.prose(1)
    b.line("4...Kh7 5.h3", bold=True)
    b.prose(1)
    fen = "6k1/3R1pp1/7p/8/8/8/5PPP/6K1 b - - 0 4"
    book = _build(tmp_path, b, {"p3-1": fen})
    line = _line_with(book, "Rxf7")
    assert line["diagram"] == "p3-1"
    assert _sans(book, line) == ["Kh8", "Rxf7", "Kg8", "Rf3"]
    nodes = book["nodes"]
    root = nodes[line["root"]]
    assert [nodes[c]["san"] for c in root["children"]] == ["Kh8", "Kh7"]
    kh7 = nodes[root["children"][1]]
    assert [nodes[c]["san"] for c in kh7["children"]] == ["h3"]



def test_a_run_that_replaces_only_the_last_move_is_no_variation_across_a_diagram():
    """After a diagram printed among the moves of the line, a run of the main
    font that reads where its numbering puts it is a variation there when it
    starts a full move or more before the line's next move ("25...fxe5" after
    move 34), but not when it only offers another move for the line's last
    one: that move is likely a stray of a note before the diagram ("22 Rf1
    Qb5." read as the game's 20...Qb5), and the run the game going on."""
    from types import SimpleNamespace
    from chessbook.assemble import _Builder
    b = _Builder.__new__(_Builder)
    b.reads_at = lambda L, run, P: True
    line = SimpleNamespace(hold_inside=True, next_ply=40)   # the line played 20...Qb5
    assert not b.variation_across_hold(line, SimpleNamespace(ply=39))   # "20...Kh8"
    assert b.variation_across_hold(line, SimpleNamespace(ply=38))       # "20.Nd5"
    assert b.variation_across_hold(line, SimpleNamespace(ply=29))       # "15...fxe5"
    # a diagram after the line's moves, and a run without a number, are no case
    assert not b.variation_across_hold(SimpleNamespace(hold_inside=False, next_ply=40),
                                       SimpleNamespace(ply=29))
    assert not b.variation_across_hold(line, SimpleNamespace(ply=None))
    b.reads_at = lambda L, run, P: False
    assert not b.variation_across_hold(line, SimpleNamespace(ply=29))


# ------------------------------------------------------------------ bare moves after a comment

def _bare_book(notes, main=True):
    """A game with notes between its moves; the notes may print a reply
    without its move number after a comment."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(1)
    b.line("1.d4 d5 2.c4 e6 3.Nc3 Nf6 4.cxd5 exd5 5.Bg5 Be7 6.e3 O-O", bold=True)
    for n in notes:
        b.line(n)
    b.prose(1)
    if main:
        b.line("7.Bd3 Nbd7 8.Qc2 Re8", bold=True)
    b.prose(2)
    return b


def _var(book, *sans):
    """The node reached by the variation sans from the game's root."""
    nodes = book["nodes"]
    game = _line_with(book, "Bg5")
    nid = game["root"]
    for san in sans:
        kids = {nodes[c]["san"]: c for c in nodes[nid]["children"]}
        assert san in kids, f"{san} is not among {list(kids)} after {nodes[nid]['san']}"
        nid = kids[san]
    return nid


def test_bare_reply_after_a_comment_goes_on_with_the_variation(tmp_path):
    """"7.Nf3 Every swap helps Black. Nbd7 8.Qc2 Re8 9.h3": the reply
    printed without its number after the comment is the variation's next
    move, confirmed by the numbered run after it, which continues the
    numbering and reads from there. It goes with the variation even though
    "8.Qc2 Re8 9.h3" would also read as a variation of the game's move 8."""
    book = _build(tmp_path, _bare_book([
        "A good alternative is 7.Nf3 Every swap helps Black, so White",
        "retreats. Nbd7 8.Qc2 Re8 9.h3 and both sides are fine."]))
    nodes = book["nodes"]
    h3 = nodes[_var(book, *QGD, "Nf3", "Nbd7", "Qc2", "Re8", "h3")]
    assert h3["number"] == 9 and not h3["main"]
    nbd7 = _var(book, *QGD, "Nf3", "Nbd7")
    assert nodes[nbd7]["number"] == 7 and nodes[nbd7]["black"] and nodes[nbd7]["status"] == "ok"
    (m,) = [m for p in book["pages"] for m in p["marks"] if m["node"] == nbd7]
    assert m["raw"] == "Nbd7" and m["status"] == "ok"
    game = _line_with(book, "Bg5")
    assert _sans(book, game) == QGD + ["Bd3", "Nbd7", "Qc2", "Re8"]
    assert not book["unattached"]


def test_bare_reply_in_the_main_font_goes_on_with_the_game(tmp_path):
    """The same in the game itself: the reply in the notes' font after a
    comment, then the numbered moves in the move font."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(1)
    b.line("1.d4 d5 2.c4 e6 3.Nc3 Nf6 4.cxd5 exd5 5.Bg5 Be7 6.e3 O-O 7.Bd3", bold=True)
    b.line("Every swap helps Black, so White agrees to the loss of time and")
    b.line("retreats. Nbd7")
    b.line("8.Qc2 Re8 9.Nf3 Nf8", bold=True)
    b.prose(2)
    book = _build(tmp_path, b)
    game = _line_with(book, "Bg5")
    assert _sans(book, game) == QGD + ["Bd3", "Nbd7", "Qc2", "Re8", "Nf3", "Nf8"]
    assert game["status"] == "ok" and not book["unattached"]


def test_bare_move_after_a_threat_cue_stays_text(tmp_path):
    """"Idea: g5" gives a plan, not a move played, even when it is legal and
    the numbered run after it would read on from it."""
    book = _build(tmp_path, _bare_book([
        "A good alternative is 6...h6 7.Bh4 Idea: g5 trapping the bishop.",
        "8.Nf3 Nbd7 9.Bd3 and White is fine."]))
    nodes = book["nodes"]
    bh4 = nodes[_var(book, *QGD[:11], "h6", "Bh4")]
    assert not [c for c in bh4["children"] if nodes[c]["san"] == "g5"]
    assert not [m for p in book["pages"] for m in p["marks"] if m["raw"] == "g5"]
    assert not [n for n in nodes.values() if n["san"] == "g5"]


def test_bare_move_after_a_colon_ends_a_variation_in_a_bracket(tmp_path):
    """"(the careless 7.Bxf6? walks into a trick ...: Bxf6 picking off the
    bishop)": the move after the colon, alone in its sentence, ends the
    variation of the bracket; the moves after the bracket go on with the
    variation it interrupted."""
    book = _build(tmp_path, _bare_book([
        "Also possible is 7.Nf3 (the careless 7.Bxf6? walks into a trick",
        "every player should know: Bxf6 picking off the bishop) 7...Nbd7",
        "8.Bd3 Re8 and both sides are fine."]))
    nodes = book["nodes"]
    bxf6 = nodes[_var(book, *QGD, "Bxf6", "Bxf6")]
    assert bxf6["number"] == 7 and bxf6["black"] and not bxf6["children"]
    bd3 = nodes[_var(book, *QGD, "Nf3", "Nbd7", "Bd3")]
    assert bd3["number"] == 8


def test_bare_move_the_moves_do_not_confirm_is_an_item_to_join(tmp_path):
    """When the numbered run after the bare move does not read cleanly from
    it (here the text lacks Black's ninth move), the bare move stands in no
    line, with the move the text prints it after, and the reader can join it
    there: the moves after it then go on from it."""
    tmp = tmp_path
    b = _bare_book([
        "A good alternative is 7.Nf3 Every swap helps Black, so White",
        "retreats. Nbd7 8.Qc2 Re8 9.Bd3 10.O-O Nf8 and so on."])
    pdf = b.save(tmp / "bare.pdf")
    state = {}
    book = build_book(pdf, output_dir=tmp / "out", books_dir=tmp / "books", state=state)
    nodes = book["nodes"]
    nf3 = _var(book, *QGD, "Nf3")
    assert not nodes[nf3]["children"]
    (u,) = [u for u in book["unattached"] if u["text"] == "Nbd7"]
    assert u["after"] == nodes[nf3]["key"] and "no move number" in u["reason"]
    assert "7.Nf3" in u["reason"]
    (m,) = [m for p in book["pages"] for m in p["marks"] if m["raw"] == "Nbd7" and m.get("seq") == u["key"]]
    assert m["status"] == "unattached"
    # the pencil join: "Continue the line after 7.Nf3"
    fix = {"connect": {u["key"]: {"after": u["after"]}}}
    live.apply(state, book, fix)
    nodes = book["nodes"]
    nbd7 = nodes[_var(book, *QGD, "Nf3", "Nbd7")]
    assert nbd7["corrected"] == "connected" and nbd7["number"] == 7 and nbd7["black"]
    bd3 = nodes[_var(book, *QGD, "Nf3", "Nbd7", "Qc2", "Re8", "Bd3")]
    (gap,) = bd3["children"]
    assert nodes[gap]["status"] == "failed" and nodes[gap]["raw"] == "O-O"
    assert not [u for u in book["unattached"] if u["text"] == "Nbd7"]
    assert _comparable(book) == _comparable(_fresh(tmp, pdf, fix))
