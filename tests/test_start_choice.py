"""Tests for the choice of the position a line starts from (assemble.choose_start).

Small books generated here put a diagram after the moves it belongs to, a
reading with the wrong side to move, a diagram that only shows the position
a line reaches (a checkpoint), and a board reading with one doubtful square.
The corpus tests at the end run on the test books when they are present and
are skipped otherwise.
"""
import sys
from pathlib import Path

import chess
import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook.assemble import build_book  # noqa: E402
from chessbook.movetext import find_sequences  # noqa: E402

W, H = 420, 600
X0 = 50
PROSE = ("The position shows a typical idea that every player should know well. White has "
         "developed quickly and looks for a way to open lines against the black king, while "
         "Black hopes to finish his development in time.").split()
ENDING = "6k1/5pp1/7p/8/8/8/5PPP/3R2K1 w - - 0 1"


def _after(fen, *sans):
    b = chess.Board(fen)
    for s in sans:
        b.push_san(s)
    return b.fen()


class _Book:
    """A one-column book: Times-Roman notes, Times-Bold moves, board pictures."""

    def __init__(self):
        self.doc = pymupdf.open()
        self.board = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 64, 64), False)
        self.board.clear_with(255)
        for r in range(8):
            for c in range(8):
                if (r + c) % 2:
                    self.board.set_rect(pymupdf.IRect(c * 8, r * 8, c * 8 + 8, r * 8 + 8), (110,))
        self.word = 0
        self.pg = None

    def page(self, head=True):
        if self.pg is not None:
            self.pg.insert_text((W / 2 - 4, H - 22), str(self.doc.page_count), fontname="tiro",
                                fontsize=9)
        self.pg = self.doc.new_page(width=W, height=H)
        if head:
            self.pg.insert_text((X0, 30), "Chapter 1 - Endings", fontname="tiro", fontsize=9)
        self.y = 64

    def line(self, text, bold=False, size=10, x=None):
        self.pg.insert_text((x if x is not None else X0, self.y), text,
                            fontname="tibo" if bold else "tiro", fontsize=size)
        self.y += 14

    def prose(self, n):
        for _ in range(n):
            words = []
            while True:
                w = PROSE[self.word % len(PROSE)]
                if pymupdf.get_text_length(" ".join(words + [w]), "tiro", 10) > 300:
                    break
                words.append(w)
                self.word += 1
            self.line(" ".join(words))

    def pictures(self, *labels):
        """Boards side by side, each with its label and a caption under it."""
        y0 = self.y
        for k, label in enumerate(labels):
            x = X0 + 10 + 160 * k
            rect = pymupdf.Rect(x, y0, x + 120, y0 + 120)
            self.pg.insert_image(rect, pixmap=self.board)
            self.pg.insert_text((x + 30, y0 + 136), label, fontname="tiro", fontsize=10)
            self.pg.insert_text((x + 14, y0 + 150), "A quiet position", fontname="tiro",
                                fontsize=10)
        self.y = y0 + 172

    def save(self, path):
        self.page()
        self.doc.save(path)
        return path


def _front(b):
    b.page(head=False)
    b.pg.insert_text((80, 120), "A Book of Endings", fontname="tiro", fontsize=26)
    b.page(head=False)
    b.pg.insert_text((X0, 80), "Chapter 1", fontname="tiro", fontsize=24)
    b.y = 120
    b.prose(12)


def _main_line(book, line):
    out, nid = [], line["root"]
    while book["nodes"][nid]["children"]:
        nid = book["nodes"][nid]["children"][0]
        out.append(nid)
    return out


def _sans(book, line):
    return [book["nodes"][n]["san"] for n in _main_line(book, line)]


def _line_with(book, san):
    for line in book["lines"]:
        if san in _sans(book, line):
            return line
    raise AssertionError(f"no line plays {san}: {[x['title'] for x in book['lines']]}")


def _build(tmp_path, b, fens, readings=None):
    pdf = b.save(tmp_path / "endings.pdf")
    return build_book(pdf, output_dir=tmp_path / "out", books_dir=tmp_path / "books",
                      diagram_fens=fens, readings=readings)


# ------------------------------------------------------------------ synthetic books

def test_diagram_after_the_moves_is_a_checkpoint(tmp_path):
    """Two boards stand before the moves: the first shows where they start,
    the second (named after the moves) the position they reach. The line
    starts from the first, and the second becomes a checkpoint inside it."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(4)
    b.pictures("Diagram 1", "Diagram 2")
    b.line("1.Rd8+ Kh7 2.Rd7 (Diagram 2)", bold=True)
    b.prose(3)
    b.line("2...Kg8 3.Rd8+ Kh7", bold=True)
    b.prose(4)
    reached = _after(ENDING, "Rd8+", "Kh7", "Rd7")
    book = _build(tmp_path, b, {"p3-1": ENDING, "p3-2": reached})
    line = _line_with(book, "Rd8+")
    assert line["diagram"] == "p3-1" and line["status"] == "ok"
    assert _sans(book, line) == ["Rd8+", "Kh7", "Rd7", "Kg8", "Rd8+", "Kh7"]
    assert "not from" in line["start_note"]
    diag = {d["id"]: d for p in book["pages"] for d in p["diagrams"]}
    third = _main_line(book, line)[2]
    assert diag["p3-2"]["checked"] and diag["p3-2"]["after_node"] == third
    assert not diag["p3-1"]["checked"]


def test_wrong_side_to_move_in_the_reading(tmp_path):
    """The reading says White to move, but the text starts with Black's move:
    the numbering decides the side."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(4)
    b.pictures("Diagram 5")
    b.line("1...Kh7 2.Rd7 Kg8 3.Rd8+", bold=True)
    b.prose(4)
    start = _after(ENDING, "Rd8+")          # Black is to move here
    white = start.replace(" b ", " w ")
    book = _build(tmp_path, b, {"p3-1": white})
    line = _line_with(book, "Kh7")
    assert line["status"] == "ok" and line["start_fen"].split()[1] == "b"
    assert _sans(book, line) == ["Kh7", "Rd7", "Kg8", "Rd8+"]


def test_line_goes_on_past_a_checkpoint_diagram(tmp_path):
    """A fragment does not end at a diagram that shows the position it
    reaches when the next moves continue its numbering: the diagram becomes
    a checkpoint, even when its own picture could not be read."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(3)
    b.pictures("Diagram 7")
    b.line("1.Rd8+ Kh7", bold=True)
    b.prose(2)
    b.pictures("Diagram 8")
    b.prose(2)
    b.line("2.Rd7 Kg8 3.Rd8+ Kh7", bold=True)
    b.prose(3)
    book = _build(tmp_path, b, {"p3-1": ENDING})        # Diagram 8 unread
    line = _line_with(book, "Rd8+")
    assert line["status"] == "ok"
    assert _sans(book, line) == ["Rd8+", "Kh7", "Rd7", "Kg8", "Rd8+", "Kh7"]
    assert not book["waiting"]
    # with Diagram 8 read, it is confirmed as the position after 1...Kh7
    book = _build(tmp_path, b, {"p3-1": ENDING, "p3-2": _after(ENDING, "Rd8+", "Kh7")})
    line = _line_with(book, "Rd8+")
    diag = {d["id"]: d for p in book["pages"] for d in p["diagrams"]}
    assert diag["p3-2"]["checked"] and diag["p3-2"]["after_node"] == _main_line(book, line)[1]
    assert len([x for x in book["lines"] if "Rd7" in _sans(book, x)]) == 1


def test_diagram_decides_a_misread_square(tmp_path):
    """OCR reads b and h (and c and e) for each other. The text prints 1.h3,
    which is legal, but the board printed after the moves shows the pawn on
    b3, and so would every move after it: the move is 1.b3, a guess with the
    text's reading as its alternative, and the board is a checkpoint. A board
    that agrees with the text leaves the text's reading as it is."""
    start = "6k1/5pp1/7p/8/8/8/1P3PPP/3R2K1 w - - 0 1"

    def book_with(shown, where):
        b = _Book()
        _front(b)
        b.page()
        b.prose(3)
        b.pictures("Diagram 7")
        b.line("1.h3 Kh7 2.Rd7 Kg8", bold=True)
        b.prose(2)
        b.pictures("Diagram 8")
        b.prose(2)
        b.line("3.Rd8+ Kh7", bold=True)
        b.prose(3)
        where.mkdir()
        book = _build(where, b, {"p3-1": start, "p3-2": _after(start, *shown)})
        line = _line_with(book, "Rd7")
        diag = {d["id"]: d for p in book["pages"] for d in p["diagrams"]}
        return book, line, diag["p3-2"]

    book, line, board = book_with(["b3", "Kh7", "Rd7", "Kg8"], tmp_path / "b3")
    ids = _main_line(book, line)
    first = book["nodes"][ids[0]]
    assert _sans(book, line) == ["b3", "Kh7", "Rd7", "Kg8", "Rd8+", "Kh7"]
    assert first["status"] == "guessed" and first["alternatives"] == ["h3"]
    assert not first.get("corrected")
    assert board["checked"] and board["after_node"] == ids[3]

    book, line, board = book_with(["h3", "Kh7", "Rd7", "Kg8"], tmp_path / "h3")
    first = book["nodes"][_main_line(book, line)[0]]
    assert first["san"] == "h3" and first["status"] == "ok"
    assert board["checked"]


def test_diagram_a_move_later_decides_no_square(tmp_path):
    """The board after 3.Rd7 shows the pawn on b5: 1...b5 for the printed
    1...b6 would reach it, but so does 3...b5, the move after the one it is
    tied to. The text's 1...b6 stands."""
    start = "6k1/1p3pp1/7p/8/8/8/5PPP/3R2K1 w - - 0 1"
    b = _Book()
    _front(b)
    b.page()
    b.prose(3)
    b.pictures("Diagram 7")
    b.line("1.Rd7 b6 2.Rd8+ Kh7 3.Rd7", bold=True)
    b.pictures("Diagram 8")
    b.prose(3)
    book = _build(tmp_path, b, {"p3-1": start,
                                "p3-2": _after(start, "Rd7", "b6", "Rd8+", "Kh7", "Rd7", "b5")})
    line = _line_with(book, "Rd8+")
    second = book["nodes"][_main_line(book, line)[1]]
    assert second["san"] == "b6" and second["status"] == "ok"


def test_reading_stored_before_misread_squares_takes_a_correction(tmp_path):
    """A reading stored by earlier code (the app's saved reading pickles the
    builder) holds no misread squares: a move corrected on the board is
    replayed as in a fresh reading."""
    import pickle
    from chessbook import live
    start = "6k1/5pp1/7p/8/8/8/1P3PPP/3R2K1 w - - 0 1"
    b = _Book()
    _front(b)
    b.page()
    b.prose(3)
    b.pictures("Diagram 7")
    b.line("1.h3 Kh7 2.Rd7 Kg8", bold=True)
    b.prose(3)
    pdf = b.save(tmp_path / "endings.pdf")
    state = {}
    book = build_book(pdf, output_dir=tmp_path / "out", books_dir=tmp_path / "books",
                      diagram_fens={"p3-1": start}, state=state)
    # (as web/driver.py save_reading stores it: without the PDF)
    doc, state["builder"].doc = state["builder"].doc, None
    old = pickle.loads(pickle.dumps(state["builder"]))
    old.__dict__.pop("misread")
    old.doc = doc
    state = {**state, "builder": old}
    line = _line_with(book, "Rd7")
    key = book["nodes"][_main_line(book, line)[3]]["key"]
    live.apply(state, book, {"moves": {key: {"san": "Kg6"}}})
    line = _line_with(book, "Rd7")
    assert _sans(book, line) == ["h3", "Kh7", "Rd7", "Kg6"]
    assert book["nodes"][_main_line(book, line)[3]]["corrected"] == "move"


def test_correction_before_a_misread_square_reads_the_text(tmp_path):
    """The board printed after the moves shows 2.b3 for the printed 2.h3. The
    reader then gives 1.b3 for 1.Rd7: 2.b3 is no longer legal, and 2.h3, the
    text's own reading, is read in its place, not a move the reader never gave."""
    from chessbook import live
    start = "6k1/5pp1/7p/8/8/8/1P3PPP/3R2K1 w - - 0 1"
    b = _Book()
    _front(b)
    b.page()
    b.prose(3)
    b.pictures("Diagram 7")
    b.line("1.Rd7 Kh7 2.h3 Kg8", bold=True)
    b.prose(2)
    b.pictures("Diagram 8")
    b.prose(2)
    b.line("3.Rd8+ Kh7", bold=True)
    b.prose(3)
    pdf = b.save(tmp_path / "endings.pdf")
    state = {}
    shown = _after(start, "Rd7", "Kh7", "b3", "Kg8")
    book = build_book(pdf, output_dir=tmp_path / "out", books_dir=tmp_path / "books",
                      diagram_fens={"p3-1": start, "p3-2": shown}, state=state)
    line = _line_with(book, "Rd8+")
    assert _sans(book, line) == ["Rd7", "Kh7", "b3", "Kg8", "Rd8+", "Kh7"]
    key = book["nodes"][_main_line(book, line)[0]]["key"]
    live.apply(state, book, {"moves": {key: {"san": "b3"}}})
    line = _line_with(book, "Rd8+")
    ids = _main_line(book, line)
    assert _sans(book, line) == ["b3", "Kh7", "h3", "Kg8", "Rd8+", "Kh7"]
    third = book["nodes"][ids[2]]
    assert third["status"] == "ok" and not third.get("reason")


def _mixed(b, parts, size=10):
    """One line of moves set in Times-Bold, but for the parts given another
    font: [(text, font name)]."""
    x = X0
    for text, font in parts:
        b.pg.insert_text((x, b.y), text, fontname=font, fontsize=size)
        x += pymupdf.get_text_length(text, font, size)
    b.y += 14


def test_glyph_read_as_the_letter_it_draws(tmp_path):
    """A font that OCR traced from the scan (ClearScan) draws one letter with
    several glyphs, and names each by the letter OCR read: here the h's set
    in Courier stand where only a b makes the moves legal (3.Bb5, 4.Qb3,
    3.Bb5+). That glyph is a b, so the "h6" it draws in a game where both
    b6 and h6 are legal is 3...b6, read as certain. An h of the moves' own
    font stays an h (3.h3)."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(2)
    for parts in ([("1.e4 e5 2.Nf3 Nc6 3.B", "tibo"), ("h", "cour"), ("5 a6", "tibo")],
                  [("1.d4 d5 2.c4 c6 3.Nc3 Nf6 4.Q", "tibo"), ("h", "cour"), ("3 e6", "tibo")],
                  [("1.e4 c5 2.Nf3 d6 3.B", "tibo"), ("h", "cour"), ("5+ Bd7", "tibo")],
                  [("1.d4 Nf6 2.c4 e6 3.Nf3 ", "tibo"), ("h", "cour"), ("6 4.g3", "tibo")],
                  [("1.e4 e5 2.Nf3 Nc6 3.h3 Nf6", "tibo")]):
        _mixed(b, parts)
        b.prose(3)
    b.doc.set_metadata({"producer": "Adobe Acrobat 9.0 Paper Capture Plug-in with ClearScan"})
    book = _build(tmp_path, b, {})
    # (the games are read as one tree of lines from the initial position)
    read = [(m["raw"], book["nodes"][m["node"]]["san"], m["status"])
            for p in book["pages"] for m in p["marks"] if m.get("node")]
    assert ("Bb5", "Bb5", "ok") in read and ("Qb3", "Qb3", "ok") in read
    assert ("Bb5+", "Bb5+", "ok") in read
    assert ("b6", "b6", "ok") in read and not any(san == "h6" for _, san, _ in read)
    assert ("h3", "h3", "ok") in read


def test_doubtful_square_is_corrected(tmp_path):
    """The reading lost the rook on d1 and marked d1 as doubtful: only a white
    rook there makes the moves legal, so the line starts with it."""
    b = _Book()
    _front(b)
    b.page()
    b.prose(4)
    b.pictures("Diagram 9")
    b.line("1.Rd8+ Kh7 2.Rd7 Kg8 3.Rd8+ Kh7", bold=True)
    b.prose(4)
    lost = "6k1/5pp1/7p/8/8/8/5PPP/6K1 w - - 0 1"
    readings = {"p3-1": {"fen": lost, "confidence": 0.3, "doubtful": ["d1"], "turn": "w",
                         "turn_from": "default", "flipped": False}}
    book = _build(tmp_path, b, {"p3-1": lost}, readings)
    line = _line_with(book, "Rd7")
    assert line["status"] == "ok" and line["start_fen"].split()[0] == ENDING.split()[0]
    assert "d1" in line["start_note"] and "white rook" in line["start_note"]
    diag = {d["id"]: d for p in book["pages"] for d in p["diagrams"]}
    assert diag["p3-1"]["fen"] == lost           # the reading itself is kept


def test_answer_label_is_not_a_move():
    text = "14 ... Kh8 15 Ng5 Answer: 15 ... Qe8! 16 Rc1 Nb6 17 Ng4 Na4 18 Rb1 Answer: 20 Ne4"
    raws = [t.raw for s in find_sequences(text, lenient=True, dotless=True) for t in s.moves]
    assert "Answer:" not in raws and "Qe8!" in raws and "Ne4" in raws
    seq = find_sequences("10 ... b5 11 Answer: d4 12 Ne4", lenient=True, dotless=True)[0]
    assert [(t.raw, t.number, t.black) for t in seq.moves] == [
        ("b5", 10, True), ("d4", 11, False), ("Ne4", 12, False)]


# ------------------------------------------------------------------ the test books

CORPUS = ROOT / "corpus"


def _book_or_skip(name, tmp_path_factory):
    pdf = CORPUS / f"{name}.pdf"
    if not pdf.exists():
        pytest.skip(f"{pdf} is not present")
    return build_book(pdf, output_dir=tmp_path_factory.mktemp(name))


def _early_failures(book):
    """Lines from a diagram whose first or second move does not read."""
    out = []
    for line in book["lines"]:
        if not line["diagram"] or line["status"] == "waiting":
            continue
        ids = _main_line(book, line)
        first = next((k for k, n in enumerate(ids) if book["nodes"][n]["status"] == "failed"),
                     None)
        if first is not None and first <= 1:
            out.append(line["id"])
    return out


@pytest.fixture(scope="module")
def gpa(tmp_path_factory):
    return _book_or_skip("gpa", tmp_path_factory)


def test_gpa_lines_start_from_the_right_diagram(gpa):
    st = gpa["stats"]
    # (lines that the baseline split at diagrams are now whole, so there
    # are fewer lines; the moves tell the gain)
    assert st["line_status"]["ok"] >= 24
    # the front matter is read now: its introduction adds games (three of them with a move
    # that does not read); the chapters keep their count
    assert sum(1 for L in gpa["lines"] if L["status"] == "failed" and L["chapter"] > 0) <= 22
    assert st["moves"]["ok"] >= 7700 and st["moves"]["failed"] <= 320
    # the book prints two boards side by side: the line starts from the one
    # before its moves, not from the one its moves reach (baseline: 11 lines)
    assert len(_early_failures(gpa)) <= 2
    # "(Diagram N)" boards become checkpoints of the lines that reach them
    assert sum(d["checked"] for p in gpa["pages"] for d in p["diagrams"]) >= 100
    # Spassky - Kasparov: 7 d3 goes on from Diagram 21, not from Diagram 22
    line = next(x for x in gpa["lines"] if any(
        n["page"] == 160 and n["san"] == "d3" for n in (gpa["nodes"][i]
                                                         for i in _main_line(gpa, x))))
    assert [gpa["nodes"][i]["san"] for i in _main_line(gpa, line)][:8] == [
        "d3", "g6", "Nxd4", "cxd4", "Ne2", "Bg7", "Bd2", "O-O"]


def test_ivanchuk_stays_whole(tmp_path_factory):
    book = _book_or_skip("ivanchuk", tmp_path_factory)
    assert book["stats"]["line_status"] == {"ok": 1}
    # 75 moves of the game and 70 of its variations: "8.Rd1 and then
    # Nb1-c3" no longer adds Nc3 as a variation of the game at move 6
    assert book["stats"]["moves"]["ok"] == 145
    marks = {m["raw"].rstrip(".,)"): m for p in book["pages"] for m in p["marks"]}
    assert "Nb1–c3" not in marks
    # "playing ...a6-a5" names the game's next move, 15...a5
    a5 = marks["...a6–a5"] if "...a6–a5" in marks else marks["a6–a5"]
    node = book["nodes"][a5["node"]]
    assert a5.get("ref") and node["main"] and node["san"] == "a5" and node["number"] == 15


def test_kia_answer_labels_are_not_moves():
    pdf = CORPUS / "kia.pdf"
    if not pdf.exists():
        pytest.skip(f"{pdf} is not present")
    doc = pymupdf.open(pdf)
    raws = [t.raw for page in doc for s in find_sequences(page.get_text(), lenient=True,
                                                          dotless=True) for t in s.moves]
    assert len(raws) > 5000
    assert not [r for r in raws if r.rstrip(":").lower() in ("answer", "question", "exercise")]
