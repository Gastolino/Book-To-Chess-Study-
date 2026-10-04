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
    assert st["line_status"]["ok"] >= 27 and st["line_status"]["failed"] <= 22
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
    assert book["stats"]["moves"]["ok"] == 146


def test_kia_answer_labels_are_not_moves():
    pdf = CORPUS / "kia.pdf"
    if not pdf.exists():
        pytest.skip(f"{pdf} is not present")
    doc = pymupdf.open(pdf)
    raws = [t.raw for page in doc for s in find_sequences(page.get_text(), lenient=True,
                                                          dotless=True) for t in s.moves]
    assert len(raws) > 5000
    assert not [r for r in raws if r.rstrip(":").lower() in ("answer", "question", "exercise")]
