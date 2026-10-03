"""Tests for chessbook.assemble and chessbook.pgnout.

A small book generated here (two columns, Times-Roman notes, Times-Bold main
lines, English or German piece letters) checks the assembly rules exactly;
the Primer checks the same rules on a real OCR'd book. Primer-specific facts
belong here and nowhere in the library code.
"""
import io
import json
import sys
from pathlib import Path

import chess
import chess.pgn
import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook import pgnout  # noqa: E402
from chessbook.assemble import WAIT_REASON, build_book, display_title, parse_game_header  # noqa: E402

PDF = ROOT / "primer.pdf"

# ------------------------------------------------------------------ a generated book

PROSE = ("The position shows a typical idea that every player should know well. White has "
         "developed quickly and looks for a way to open lines against the black king, while "
         "Black hopes to finish his development in time. Such positions arise often in "
         "practice and deserve careful study by every beginner who wants to improve.").split()
W, H = 420, 600
COLS = (40, 225)
COL_W = 158
GAME_EN = ["1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6", "4.Ng5 d5 5.exd5 Nxd5", "6.Nxf7 Kxf7 7.Qf3+ Ke6",
           "8.Nc3"]
GAME_DE = ["1.e4 e5 2.Sf3 Sc6 3.Lc4 Sf6", "4.Sg5 d5 5.exd5 Sxd5", "6.Sxf7 Kxf7 7.Df3+ Ke6",
           "8.Sc3"]
MAIN_SAN = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6", "Ng5", "d5", "exd5", "Nxd5", "Nxf7", "Kxf7",
            "Qf3+", "Ke6", "Nc3"]
ENDING_FEN = "6k1/5pp1/7p/8/8/8/5PPP/3R2K1 w - - 0 1"


class _Writer:
    def __init__(self):
        self.doc = pymupdf.open()
        self.word = 0
        self.folio = 1
        self.board = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 64, 64), False)
        self.board.clear_with(255)
        for r in range(8):
            for c in range(8):
                if (r + c) % 2:
                    self.board.set_rect(pymupdf.IRect(c * 8, r * 8, c * 8 + 8, r * 8 + 8), (110,))

    def page(self, head=True):
        if self.doc.page_count:
            self.foot()
        self.pg = self.doc.new_page(width=W, height=H)
        if head:
            self.pg.insert_text((40, 30), "Chapter 1 - First Steps", fontname="tiro", fontsize=9)
        self.col(0)

    def foot(self):
        self.pg.insert_text((W / 2 - 4, H - 22), str(self.folio), fontname="tiro", fontsize=9)
        self.folio += 1

    def col(self, i):
        self.x0, self.y = COLS[i], 64

    def line(self, text, bold=False, size=10, indent=0, x=None):
        self.pg.insert_text((x if x is not None else self.x0 + indent, self.y), text,
                            fontname="tibo" if bold else "tiro", fontsize=size)
        self.y += 13

    def mixed(self, parts):
        x = self.x0
        for text, bold in parts:
            font = "tibo" if bold else "tiro"
            self.pg.insert_text((x, self.y), text, fontname=font, fontsize=10)
            x += pymupdf.get_text_length(text, font, 10)
        self.y += 13

    def prose(self, n=None, until=None):
        k = 0
        while (n is None or k < n) and (until is None or self.y < until):
            words = []
            while True:
                w = PROSE[self.word % len(PROSE)]
                if pymupdf.get_text_length(" ".join(words + [w]), "tiro", 10) > COL_W:
                    break
                words.append(w)
                self.word += 1
            self.line(" ".join(words))
            k += 1

    def picture(self, label, caption="White to move"):
        cx = self.x0 + COL_W / 2
        self.line(label, x=cx - 5)
        rect = pymupdf.Rect(cx - 60, self.y - 6, cx + 60, self.y + 114)
        self.pg.insert_image(rect, pixmap=self.board)
        for k, f in enumerate("abcdefgh"):
            self.pg.insert_text((rect.x0 + 6 + 15 * k, rect.y1 + 9), f, fontname="helv", fontsize=7)
        for k in range(8):
            self.pg.insert_text((rect.x0 - 7, rect.y0 + 10 + 15 * k), str(8 - k), fontname="helv",
                                fontsize=7)
        self.y = rect.y1 + 24
        self.line(caption, x=cx - pymupdf.get_text_length(caption, "tiro", 10) / 2)
        self.y += 6

    def save(self, path):
        self.foot()
        self.doc.save(path)


def make_book(path, game=GAME_EN):
    w = _Writer()
    w.page(head=False)
    w.pg.insert_text((80, 120), "A Little Chess Book", fontname="tiro", fontsize=26)
    w.page(head=False)
    w.pg.insert_text((40, 60), "Contents", fontname="tiro", fontsize=20)
    w.pg.insert_text((40, 90), "Chapter 1 First Steps 3", fontname="tiro", fontsize=10)
    # page 3: chapter title
    w.page(head=False)
    w.pg.insert_text((40, 80), "Chapter 1", fontname="tiro", fontsize=24)
    w.pg.insert_text((40, 112), "First Steps", fontname="tiro", fontsize=18)
    w.y = 150
    w.prose(until=H - 60)
    w.col(1)
    w.y = 150
    w.prose(until=H - 60)
    # page 4: a game across both columns
    w.page()
    w.prose(until=H - 60 - 8 * 13)
    w.line("SHORT GAMES", bold=True, size=11, x=COLS[0] + 40)
    w.mixed([("Smith - Jones, ", True), ("London 1901", False)])
    w.line(game[0], bold=True)
    w.line("Better is 3...Bc5 4.c3 Nf6 with a", indent=8)
    w.line("quiet game.")
    w.line(game[1], bold=True)
    w.line("Safer is 5...Na5 6.Bb5+ c6", indent=8)
    w.line("7.dxc6 bxc6.")
    w.col(1)
    w.line(game[2], bold=True)
    w.line("The king has to walk into the open.", indent=8)
    w.line(game[3], bold=True)
    w.line("White has a strong attack.", indent=8)
    w.line("1-0", bold=True)
    w.prose(until=H - 60)
    # page 5: a position from a diagram
    w.page()
    w.picture("12")
    w.line("White wins a pawn by force.", indent=8)
    w.line("1.Rd8+ Kh7 2.Rd7 Kg8", bold=True)
    w.line("Or 2.Rd3 Kg6 3.h4 with a slow win.", indent=8)
    w.prose(until=H - 60)
    w.col(1)
    w.prose(until=H - 60)
    # page 6: exercises
    w.page()
    w.line("EXERCISES", bold=True, size=11, x=COLS[0] + 40)
    w.picture("1")
    w.prose(until=H - 60)
    w.col(1)
    w.picture("2")
    w.prose(until=H - 60)
    # page 7: solutions
    w.page()
    w.line("SOLUTIONS", bold=True, size=11, x=COLS[0] + 40)
    w.line("1. 1.Rd8+ Kh7 2.Rd7", bold=True)
    w.line("2. White wins with 1.Nf6+.")
    w.prose(until=H - 60)
    w.col(1)
    w.prose(until=H - 60)
    # pages 8-9: more text, so that the statistics have enough to learn from
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
def little(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("little")
    pdf = make_book(tmp / "little.pdf")
    book = build_book(pdf, output_dir=tmp / "output", books_dir=tmp / "books")
    return tmp, pdf, book


def main_line(book, line):
    out, nid = [], line["root"]
    while book["nodes"][nid]["children"]:
        nid = book["nodes"][nid]["children"][0]
        out.append(nid)
    return out


def sans(book, ids):
    return [book["nodes"][i]["san"] for i in ids]


def line_titled(book, start):
    hits = [x for x in book["lines"] if x["title"].startswith(start)]
    assert hits, f"no line titled {start!r}: {[x['title'] for x in book['lines']]}"
    return hits[0]


def test_book_json_written(little):
    tmp, pdf, book = little
    path = tmp / "output" / "little" / "book.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["page_count"] == book["page_count"] == 9
    for key in ("title", "pages", "chapters", "lines", "nodes", "unattached", "waiting", "stats"):
        assert key in book
    assert [c["label"] for c in book["chapters"]] == ["Front matter", "Chapter 1"]
    page = book["pages"][4]
    assert set(page) >= {"page", "width", "height", "chapter", "selected", "diagrams", "marks"}
    assert page["diagrams"][0] == {**page["diagrams"][0], "id": "p5-1", "label": "12",
                                   "fen": None, "status": "unread"}


def test_game_across_columns(little):
    _, _, book = little
    g = line_titled(book, "Smith - Jones")
    assert (g["kind"], g["status"], g["result"]) == ("game", "ok", "1-0")
    assert g["header"]["white"] == "Smith" and g["header"]["black"] == "Jones"
    assert g["header"]["site"] == "London" and g["header"]["year"] == "1901"
    ids = main_line(book, g)
    assert sans(book, ids) == MAIN_SAN
    nodes = book["nodes"]
    board = chess.Board()
    for i in ids:
        board.push_san(nodes[i]["san"])
        assert nodes[i]["fen"] == board.fen()
        assert nodes[i]["main"] and nodes[i]["status"] == "ok"
    # the main line continues from the left column into the right one
    nf6, nxf7 = nodes[ids[5]], nodes[ids[10]]
    assert nf6["page"] == nxf7["page"] == 4
    assert nf6["bbox"][2] < 210 < nxf7["bbox"][0]


def test_variations_and_comments(little):
    _, _, book = little
    g = line_titled(book, "Smith - Jones")
    nodes = book["nodes"]
    ids = main_line(book, g)
    # 3...Bc5 4.c3 Nf6 is an alternative to 3...Nf6
    parent = nodes[nodes[ids[5]]["parent"]]
    assert len(parent["children"]) == 2 and parent["children"][0] == ids[5]
    alt = parent["children"][1]
    var = [nodes[alt]["san"]]
    while nodes[alt]["children"]:
        alt = nodes[alt]["children"][0]
        var.append(nodes[alt]["san"])
    assert var == ["Bc5", "c3", "Nf6"]
    assert not nodes[parent["children"][1]]["main"]
    # 5...Na5 6.Bb5+ c6 7.dxc6 bxc6 is an alternative to 5...Nxd5
    parent = nodes[nodes[ids[9]]["parent"]]
    alt = parent["children"][1]
    assert nodes[alt]["san"] == "Na5"
    assert g["variations"] == 2
    # the book's notes are the comments of the moves they follow
    assert nodes[ids[5]]["comment"] == "Better is 3...Bc5 4.c3 Nf6 with a quiet game."
    assert nodes[ids[9]]["comment"] == "Safer is 5...Na5 6.Bb5+ c6 7.dxc6 bxc6."
    assert nodes[ids[13]]["comment"] == "The king has to walk into the open."
    assert nodes[ids[14]]["comment"] == "White has a strong attack."


def test_marks_cover_every_move_token(little):
    _, _, book = little
    page = book["pages"][3]
    marks = [m for m in page["marks"] if m["node"]]
    nodes = book["nodes"]
    g = line_titled(book, "Smith - Jones")
    assert {m["node"] for m in marks} >= set(main_line(book, g))
    for m in page["marks"]:
        x0, y0, x1, y1 = m["bbox"]
        assert 0 <= x0 < x1 <= page["width"] and 0 <= y0 < y1 <= page["height"]
        if m["node"]:
            n = nodes[m["node"]]
            assert m["status"] == n["status"] and n["page"] == 4
    # the mark of 3.Bc4 sits on the printed "3.Bc4" (after the number)
    bc4 = next(m for m in marks if nodes[m["node"]]["san"] == "Bc4" and nodes[m["node"]]["main"])
    assert bc4["raw"] == "Bc4"


def test_waiting_line_from_diagram(little):
    _, _, book = little
    w = line_titled(book, "Diagram 12")
    assert (w["kind"], w["status"], w["diagram"], w["start_fen"]) == ("fragment", "waiting", "p5-1",
                                                                     None)
    nodes = book["nodes"]
    ids = main_line(book, w)
    assert [nodes[i]["raw"] for i in ids] == ["Rd8+", "Kh7", "Rd7", "Kg8"]
    assert all(nodes[i]["status"] == "waiting" and nodes[i]["fen"] is None for i in ids)
    # the note's 2.Rd3 branches off 2.Rd7 by its number alone
    parent = nodes[nodes[ids[2]]["parent"]]
    assert [nodes[c]["raw"] for c in parent["children"]] == ["Rd7", "Rd3"]
    entry = next(x for x in book["waiting"] if x["line"] == w["id"])
    assert entry["reason"] == WAIT_REASON == "needs the diagram position (Stage 3)"
    assert entry["diagram"] == "p5-1" and entry["page"] == 5
    assert book["pages"][4]["diagrams"][0]["lines"] == [w["id"]]


def test_solutions_find_their_exercise_diagrams(little):
    _, _, book = little
    by_diagram = {x["diagram"]: x for x in book["lines"] if x["page"] == 7}
    assert set(by_diagram) == {"p6-1", "p6-2"}
    assert by_diagram["p6-1"]["title"] == "Solutions 1"
    assert by_diagram["p6-2"]["title"] == "Solutions 2"
    nodes = book["nodes"]
    assert nodes[nodes[by_diagram["p6-2"]["root"]]["children"][0]]["raw"] == "Nf6+"


def test_decoded_once_the_diagram_is_read(tmp_path):
    pdf = make_book(tmp_path / "little.pdf")
    book = build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books",
                      diagram_fens={"p5-1": ENDING_FEN})
    w = line_titled(book, "Diagram 12")
    assert w["status"] == "ok" and w["start_fen"] == ENDING_FEN
    ids = main_line(book, w)
    assert sans(book, ids) == ["Rd8+", "Kh7", "Rd7", "Kg8"]
    nodes = book["nodes"]
    parent = nodes[nodes[ids[2]]["parent"]]
    alt = parent["children"][1]
    assert nodes[alt]["san"] == "Rd3" and nodes[nodes[alt]["children"][0]]["san"] == "Kg6"
    assert book["pages"][4]["diagrams"][0]["status"] == "read"
    assert not any(x["line"] == w["id"] for x in book["waiting"])


def test_german_letters(tmp_path):
    pdf = make_book(tmp_path / "klein.pdf", game=GAME_DE)
    book = build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books",
                      letters="German")
    g = line_titled(book, "Smith - Jones")
    assert sans(book, main_line(book, g)) == MAIN_SAN and g["status"] == "ok"


def test_excluded_page_has_no_lines(tmp_path):
    pdf = make_book(tmp_path / "little.pdf")
    sel = tmp_path / "books" / "little" / "selection.json"
    sel.parent.mkdir(parents=True)
    sel.write_text(json.dumps({"pages": {"exclude": [[1, 2], [4, 4]]}}), encoding="utf-8")
    book = build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books")
    assert not any(x["page"] == 4 for x in book["lines"])
    assert book["pages"][3]["selected"] is False and book["pages"][3]["marks"] == []
    assert book["selection_from_file"] is True


def test_pgn_files(little):
    tmp, _, book = little
    rep = pgnout.write_pgn(book, tmp / "pgn")
    assert rep[1]["problems"] == [] and rep[1]["games"] >= 2
    text = (tmp / "pgn" / "ch01.pgn").read_text(encoding="utf-8")
    stream = io.StringIO(text)
    games = []
    while True:
        g = chess.pgn.read_game(stream)
        if g is None:
            break
        games.append(g)
    smith = next(g for g in games if g.headers["White"] == "Smith")
    assert smith.headers["Black"] == "Jones" and smith.headers["Site"] == "London"
    assert smith.headers["Date"] == "1901.??.??" and smith.headers["Result"] == "1-0"
    board = smith.board()
    got = []
    for mv in smith.mainline_moves():
        got.append(board.san(mv))
        board.push(mv)
    assert got == MAIN_SAN
    assert "SetUp" not in smith.headers
    nf6 = smith.next()
    for _ in range(5):
        nf6 = nf6.next()
    assert nf6.comment.startswith("Better is 3...Bc5")
    assert [v.san() for v in nf6.parent.variations] == ["Nf6", "Bc5"]
    # waiting lines are counted, not written
    assert rep[1]["waiting"] == sum(1 for x in book["lines"] if x["status"] == "waiting")


def test_pgn_setup_tags(tmp_path):
    pdf = make_book(tmp_path / "little.pdf")
    book = build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books",
                      diagram_fens={"p5-1": ENDING_FEN})
    line = line_titled(book, "Diagram 12")
    game = pgnout.line_game(book, line)
    assert game.headers["SetUp"] == "1" and game.headers["FEN"] == ENDING_FEN
    assert [game.board().san(m) for m in list(game.mainline_moves())[:1]] == ["Rd8+"]


def test_helpers():
    assert display_title("SOLUTIONS TO FUN EXERCISES") == "Solutions to Fun Exercises"
    assert display_title("1. THE OPENING AND ITS TASKS") == "1. The Opening and Its Tasks"
    h = parse_game_header("Alekhine - N.N., New York (simul) 1924")
    assert (h["white"], h["black"], h["site"], h["year"]) == ("Alekhine", "N.N.", "New York", "1924")


# ------------------------------------------------------------------ the Primer

primer = pytest.mark.skipif(not PDF.exists(), reason="primer.pdf is not in the project folder")


@pytest.fixture(scope="module")
def pbook(tmp_path_factory):
    out = tmp_path_factory.mktemp("primer_out")
    return build_book(PDF, output_dir=out)


@primer
def test_primer_counts(pbook):
    st = pbook["stats"]
    print(json.dumps({k: st[k] for k in ("lines", "games", "fragments", "line_status", "moves",
                                         "variations", "unattached", "waiting", "seconds")}))
    assert st["lines"] > 400 and st["waiting"] > 300
    decoded = st["lines"] - st["line_status"].get("waiting", 0)
    assert decoded >= 50
    m = st["moves"]
    read = m["ok"] + m["guessed"] + m["ambiguous"]
    assert read >= 1500 and m["failed"] <= 0.03 * read
    assert st["variations"] > 1000
    assert st["seconds"] < 150
    # the book's figurine junk was learnt: the knight's "\x18" among others
    learnt = {(g["junk"], g["piece"]) for g in pbook["glyphs"]}
    assert ("\x18", "N") in learnt and ("\x1b", "Q") in learnt


@primer
def test_primer_front_matter_is_left_out(pbook):
    assert not any(x["page"] <= 13 for x in pbook["lines"])
    assert all(not p["marks"] for p in pbook["pages"][:13])


@primer
def test_primer_short_game(pbook):
    g = next(x for x in pbook["lines"] if x["page"] == 30 and x["title"] == "Short Games 1")
    assert sans(pbook, main_line(pbook, g)) == ["f4", "e5", "g3", "exf4", "gxf4", "Qh4#"]
    assert g["status"] == "ok" and g["kind"] == "game"


@primer
def test_primer_page_250(pbook):
    lines = {x["title"]: x for x in pbook["lines"] if x["page"] == 250}
    fy = lines["Fine -Yudovich, Moscow 1937"]
    assert (fy["status"], fy["diagram"], fy["kind"]) == ("waiting", "p250-1", "game")
    assert any(w["line"] == fy["id"] and w["reason"] == WAIT_REASON for w in pbook["waiting"])
    frag = next(x for x in lines.values() if x["start_fen"] == chess.STARTING_FEN)
    ids = main_line(pbook, frag)
    assert sans(pbook, ids) == ["e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6", "d3", "Ne7", "Nxe5", "c6"]
    assert all(pbook["nodes"][i]["status"] == "ok" for i in ids)
    root = pbook["nodes"][frag["root"]]
    assert root["comment"] == "This position arises after the opening moves"
    page = pbook["pages"][249]
    assert {m["node"] for m in page["marks"]} >= set(ids)


@primer
def test_primer_annotated_game(pbook):
    g = next(x for x in pbook["lines"] if x["title"].startswith("Alekhine - Sanchez"))
    nodes = pbook["nodes"]
    ids = main_line(pbook, g)
    assert sans(pbook, ids)[:6] == ["e4", "e6", "d4", "d5", "Nd2", "c5"]
    assert g["variations"] >= 5
    # "Better was 6...exd5": an alternative to Black's sixth move
    six = next(i for i in ids if nodes[i]["number"] == 6 and nodes[i]["black"])
    alts = [nodes[c]["san"] for c in nodes[nodes[six]["parent"]]["children"][1:]]
    assert "exd5" in alts
    assert "Better was 6...exd5." in nodes[six]["comment"]
    assert g["result"] == "1-0"


@primer
def test_primer_solutions_follow_circled_diagrams(pbook):
    sol = [x for x in pbook["lines"] if x["page"] == 397 and x["diagram"]]
    by_title = {}
    for x in sol:
        by_title.setdefault(x["title"], x["diagram"])
    # the two-movers' solutions 1 and 4 point at the first and fourth two-mover
    assert by_title["Solutions to Problems 1"] == "p379-1"
    assert by_title["Solutions to Problems 4"] == "p379-4"


@primer
def test_primer_nodes_are_consistent(pbook):
    nodes = pbook["nodes"]
    for line in pbook["lines"]:
        root = nodes[line["root"]]
        assert root["parent"] is None and root["line"] == line["id"]
    for nid, n in nodes.items():
        assert len(set(n["children"])) == len(n["children"])
        for c in n["children"]:
            assert nodes[c]["parent"] == nid
        if n["parent"] is None or n["status"] == "waiting":
            continue
        parent_fen = nodes[n["parent"]]["fen"]
        if n["san"] and parent_fen:
            b = chess.Board(parent_fen)
            b.push_san(n["san"])
            assert b.fen() == n["fen"], nid
        if n["raw"]:
            assert n["page"] and n["bbox"], nid
        else:
            # a gap: the book's text lacks this move, so nothing is printed for it
            assert n["status"] == "failed" and n["san"] is None and n.get("reason"), nid


@primer
def test_primer_pgn(pbook, tmp_path):
    rep = pgnout.write_pgn(pbook, tmp_path)
    assert all(r["problems"] == [] for r in rep.values())
    assert rep[7]["games"] >= 8
    assert sum(r["games"] for r in rep.values()) >= 50


def test_glyph_ending_in_digit_and_dot_stays_whole():
    """movetext fix: rook junk such as "'!1." ("'!1.c7" for Rc7) is one move,
    not a move followed by a glued move number "1."."""
    from chessbook.movetext import tokenize
    toks = [(t.kind, t.raw) for t in tokenize("23.%Yg7 '!1.£8 24.'!1.c7! %Yxc7")]
    assert toks == [("number", "23."), ("move", "%Yg7"), ("move", "'!1.£8"), ("number", "24."),
                    ("move", "'!1.c7!"), ("move", "%Yxc7")]
    # a real glued number still splits
    assert [t.raw for t in tokenize("9.\x18xd4t10.®c3")] == ["9.", "\x18xd4t", "10.", "®c3"]
