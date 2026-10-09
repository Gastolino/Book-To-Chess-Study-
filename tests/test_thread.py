"""Tests for threading a line through the moves the program could not place
(assemble._Builder derive/join/do_graft and suggest, corrections.py
"connect" with "before", live.suggest, web/driver.py suggest).

A generated book reproduces the case of Wells - Shirov in The Art of
Planning: the game reads cleanly to 4...Qb6; a diagram and a heading follow;
White's fifth move is printed as OCR junk ("5.'it'et" for 5.Qc1) and stands
in no line; Black's fifth move (5...f5) is missing from the text (the page
prints "IS" in a note); then "6.c4 Bh6 7.e3 f4 8.exf4 Bxf4 9.Qxf4 Qxb2"
stands in no line too. The reader gives 5.Qc1 and joins it after 4...Qb6,
joins "6.c4 ..." after 5.Qc1, which the printed numbering refuses until the
reader gives 5...f5, and suggest() says at each step what comes next.
"""
import copy
import json
import sys
from pathlib import Path

import chess
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from chessbook import corrections as fixes  # noqa: E402
from chessbook import live  # noqa: E402
from chessbook.assemble import build_book  # noqa: E402
from test_assemble import H, _Writer, main_line  # noqa: E402

GAME = "d4 Nf6 Bg5 c5 Bxf6 gxf6 d5 Qb6 Qc1 f5 c4 Bh6 e3 f4 exf4 Bxf4 Qxf4 Qxb2".split()


def make_wells(path):
    """The game to 4...Qb6 on page 4, a diagram at the foot of the left
    column, a heading, "5.'it'et" at the foot of the right column; page 5
    goes on with "6.c4 ..." and lacks Black's fifth move."""
    w = _Writer()
    w.page(head=False)
    w.pg.insert_text((80, 120), "A Little Chess Book", fontname="tiro", fontsize=26)
    w.page(head=False)
    w.pg.insert_text((40, 60), "Contents", fontname="tiro", fontsize=20)
    w.pg.insert_text((40, 90), "Chapter 1 Open Files 3", fontname="tiro", fontsize=10)
    w.page(head=False)
    w.pg.insert_text((40, 80), "Chapter 1", fontname="tiro", fontsize=24)
    w.pg.insert_text((40, 112), "Open Files", fontname="tiro", fontsize=18)
    w.y = 150
    w.prose(until=H - 60)
    w.col(1)
    w.y = 150
    w.prose(until=H - 60)
    w.page()
    w.prose(n=4)
    w.line("GAME ONE", bold=True, size=11, x=80)
    w.mixed([("Wells - Shirov, ", True), ("Gibraltar 2006", False)])
    w.line("1.d4 Nf6 2.Bg5 c5 3.Bxf6 gxf6", bold=True)
    w.line("Shirov recaptures towards the centre.", indent=8)
    w.line("4.d5 Qb6", bold=True)
    w.line("Black aims at the weak b2 square.", indent=8)
    w.prose(n=1)
    w.picture("4", caption="White to move")
    w.col(1)
    w.line("Black's plan gains momentum.", indent=8)
    w.prose(n=2)
    w.line("DARK SQUARES", bold=True, size=11, x=265)
    w.line("No doubt he was encouraged by White.", indent=8)
    w.prose(n=3)
    w.line("5.'it'et", bold=True)
    w.prose(until=H - 60)
    w.page()
    w.line("An awkward looking response.", bold=True)
    w.line("IS Shirov calls on the help of the f-pawn.", indent=8)
    w.prose(n=3)
    w.line("6.c4 Bh6 7.e3 f4", bold=True)
    w.line("The intention is to leave White with", indent=8)
    w.line("a weak pawn on e3.")
    w.line("8.exf4 Bxf4 9.Qxf4 Qxb2", bold=True)
    w.line("Wells sacrifices the exchange.", indent=8)
    w.prose(until=H - 60)
    w.col(1)
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


def _diagram():
    """Diagram 4 as a board reading gives it: the position after 4...Qb6,
    with the pawn on f2 lost and its square doubtful."""
    b = chess.Board()
    for san in GAME[:8]:
        b.push_san(san)
    b.remove_piece_at(chess.F2)
    fen = b.fen()
    return {"p4-1": fen}, {"p4-1": {"fen": fen, "confidence": 0.3, "doubtful": ["f2"], "turn": "w",
                                    "turn_from": "caption", "flipped": False}}


def build(tmp, pdf, fix=None, state=None):
    fens, readings = _diagram()
    return build_book(pdf, output_dir=tmp / "out", books_dir=tmp / "books", corrections=fix,
                      state=state, diagram_fens=fens, readings=readings)


@pytest.fixture(scope="module")
def wells(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("wells")
    pdf = make_wells(tmp / "wells.pdf")
    state = {}
    book = build(tmp, pdf, state=state)
    return tmp, pdf, book, state


@pytest.fixture
def live_book(wells):
    """The assembled book and its state, given back without corrections
    after the test."""
    tmp, pdf, book, state = wells
    book = copy.deepcopy(book)
    yield book, state
    live.apply(state, book, {})


def key_of(book, raw):
    return next(m["key"] for p in book["pages"] for m in p["marks"] if m["raw"] == raw)


def game(book):
    line = next(L for L in book["lines"] if L["title"].startswith("Wells - Shirov"))
    return [book["nodes"][n] for n in main_line(book, line)]


def sans(book):
    return [n["san"] for n in game(book)]


def comparable(b):
    st = {k: v for k, v in b["stats"].items() if "seconds" not in k}
    return ({k: b[k] for k in ("lines", "nodes", "unattached", "dismissed", "attached", "waiting",
                               "symbols", "chapters")}, st,
            [p["marks"] for p in b["pages"]], [p["diagrams"] for p in b["pages"]])


def keys(book):
    return key_of(book, "Qb6"), key_of(book, "'it'et"), key_of(book, "c4")


QC1 = {"san": "Qc1"}


def test_the_book_reproduces_the_case(wells):
    _, _, book, _ = wells
    assert sans(book) == GAME[:8] and all(n["status"] == "ok" for n in game(book))
    qb6, itet, c4 = keys(book)
    u = {x["key"]: x for x in book["unattached"]}
    assert u[itet]["text"] == "5.'it'et" and "stand between it and the last diagram" in u[itet]["reason"]
    assert u[c4]["text"].startswith("6.c4 Bh6") and u[c4]["text"].endswith("Qxb2")
    # nothing on page 5 stands for Black's fifth move
    assert [m["raw"] for m in book["pages"][4]["marks"]][:2] == ["c4", "Bh6"]


def test_a_move_for_a_token_in_no_line_alone_changes_nothing(wells, live_book):
    tmp, pdf, _, _ = wells
    book, state = live_book
    before = comparable(book)
    _, itet, _ = keys(book)
    res = live.apply(state, book, {"moves": {itet: QC1}})
    assert res["lines"] == [] and sans(book) == GAME[:8]
    mark = next(m for m in book["pages"][3]["marks"] if m["key"] == itet)
    assert mark["status"] == "unattached" and "corrected" not in mark
    assert comparable(book)[0]["lines"] == before[0]["lines"]
    assert comparable(book) == comparable(build(tmp, pdf, {"moves": {itet: QC1}}))


def test_a_move_and_a_join_place_5_qc1(wells, live_book):
    tmp, pdf, _, _ = wells
    book, state = live_book
    qb6, itet, _ = keys(book)
    fix = {"moves": {itet: QC1}, "connect": {itet: {"after": qb6}}}
    live.apply(state, book, fix)
    assert sans(book) == GAME[:9]
    qc1 = game(book)[-1]
    assert qc1["key"] == itet and qc1["corrected"] == "connected" and qc1["status"] == "ok"
    assert not [u for u in book["unattached"] if u["key"] == itet]
    assert comparable(book) == comparable(build(tmp, pdf, fix))
    # without the move the join is refused, with the reason
    live.apply(state, book, {"connect": {itet: {"after": qb6}}})
    assert sans(book) == GAME[:8]
    u = next(u for u in book["unattached"] if u["key"] == itet)
    assert "not a legal move for White after 4...Qb6" in u["reason"]


def test_a_join_after_a_joined_move_and_the_numbering(wells, live_book):
    """A join may follow a move that another join placed; a run whose printed
    number skips a move is refused, with the move named."""
    tmp, pdf, _, _ = wells
    book, state = live_book
    qb6, itet, c4 = keys(book)
    fix = {"moves": {itet: QC1}, "connect": {itet: {"after": qb6}, c4: {"after": itet}}}
    res = live.apply(state, book, fix)
    assert res["lines"] and sans(book) == GAME[:9]
    u = next(u for u in book["unattached"] if u["key"] == c4)
    assert u["reason"] == "Black's 5th move is missing before 6.c4, so it does not join after 5.Qc1"
    assert u["missing"] == {"from_ply": 9, "count": 1}
    # no mark of the refused run says it is corrected
    assert not [m for m in book["pages"][4]["marks"] if m.get("corrected")]
    assert comparable(book) == comparable(build(tmp, pdf, fix))


def test_the_moves_given_before_a_run_make_the_rest_read(wells, live_book):
    tmp, pdf, _, _ = wells
    book, state = live_book
    qb6, itet, c4 = keys(book)
    fix = {"moves": {itet: QC1},
           "connect": {itet: {"after": qb6}, c4: {"after": itet, "before": ["f5"]}}}
    live.apply(state, book, fix)
    nodes = game(book)
    assert sans(book) == GAME and all(n["status"] == "ok" for n in nodes)
    f5, c4n = nodes[9], nodes[10]
    assert f5["corrected"] == "filled" and not f5.get("key") and f5["number"] == 5 and f5["black"]
    assert c4n["corrected"] == "connected" and c4n["key"] == c4 and c4n["number"] == 6
    assert next(L for L in book["lines"] if L["title"].startswith("Wells"))["status"] == "ok"
    assert not [u for u in book["unattached"] if u["key"] in (itet, c4)]
    assert book["stats"]["corrected"]["gap_moves"] == 1
    assert book["stats"]["corrected"]["connections"] == 2
    assert comparable(book) == comparable(build(tmp, pdf, fix))
    # the joins hold in either order of their keys
    fix2 = copy.deepcopy(fix)
    fix2["connect"] = dict(reversed(list(fix["connect"].items())))
    live.apply(state, book, fix2)
    assert sans(book) == GAME


def test_the_moves_given_before_a_run_are_checked(wells, live_book):
    book, state = live_book
    qb6, itet, c4 = keys(book)
    base = {"moves": {itet: QC1}, "connect": {itet: {"after": qb6}}}
    # f4 is not legal for Black there: the reason says so
    fix = copy.deepcopy(base)
    fix["connect"][c4] = {"after": itet, "before": ["f4"]}
    live.apply(state, book, fix)
    u = next(u for u in book["unattached"] if u["key"] == c4)
    assert u["reason"] == "the move you gave before it, f4, is not a legal move for Black after 5.Qc1"
    # one move too many: 6.c4 is printed as White's move, and Black's sixth comes next
    fix["connect"][c4] = {"after": itet, "before": ["f5", "a3"]}
    live.apply(state, book, fix)
    u = next(u for u in book["unattached"] if u["key"] == c4)
    assert "printed as White's move 6, but Black's move 6 comes next" in u["reason"]
    assert sans(book) == GAME[:9]


def test_suggest_threads_the_game(wells, live_book):
    book, state = live_book
    qb6, itet, c4 = keys(book)
    # 4...Qb6: next is the garbled move, which reads as nothing there
    s = live.suggest(state, qb6)
    assert (s["kind"], s["key"], s["page"], s["raw"], s["number"], s["black"]) == \
        ("run", itet, 4, "'it'et", 5, False)
    assert s["after"] == qb6 and s["number_gap"] == 0 and s["missing"] is None
    assert s["between"] == [] and s["decoded"] == []
    # the reader names the move: it reads as 5.Qc1
    live.apply(state, book, {"moves": {itet: QC1}})
    s = live.suggest(state, qb6)
    assert [(d["san"], d["unsure"], d["key"]) for d in s["decoded"]] == [("Qc1", False, itet)]
    # joined: next is "6.c4 ...", after Black's fifth move that the text lacks
    fix = {"moves": {itet: QC1}, "connect": {itet: {"after": qb6}}}
    live.apply(state, book, fix)
    s = live.suggest(state, itet)
    assert (s["kind"], s["key"], s["page"], s["after"]) == ("run", c4, 5, itet)
    assert s["number_gap"] == 1 and s["missing"] == {"from_ply": 9, "count": 1}
    assert s["between"][0] == ["f5"] and s["decoded"] == []
    assert s["seconds"] < 1.0
    # the same from 4...Qb6: the line is followed to its end first
    assert live.suggest(state, qb6)["key"] == c4
    # with 5...f5 given, the run reads through 9...Qxb2
    s = live.suggest(state, itet, ["f5"])
    assert s["number_gap"] == 0 and s["between"] == []
    assert [d["san"] for d in s["decoded"]] == GAME[10:]
    assert not any(d["unsure"] for d in s["decoded"]) and s["decoded"][0]["key"] == c4
    # joined: nothing more follows in the chapter
    fix["connect"][c4] = {"after": itet, "before": ["f5"]}
    live.apply(state, book, fix)
    assert live.suggest(state, c4) == {"done": True, "seconds": live.suggest(state, c4)["seconds"]}
    # a box the reader passes over is not offered again
    live.apply(state, book, {"moves": {itet: QC1}, "connect": {itet: {"after": qb6}}})
    assert live.suggest(state, itet, skip=[c4]).get("done")
    with pytest.raises(ValueError):
        live.suggest(state, "4:1,1:nothing")
    with pytest.raises(ValueError):
        live.suggest(state, itet, ["Kxe8"])


def test_suggest_offers_a_misread_move_of_the_line(wells, live_book):
    """A move of the line that does not read is what comes next, anchored
    after the move before it."""
    book, state = live_book
    qb6, itet, c4 = keys(book)
    d5 = key_of(book, "d5")
    # a move given for 4...Qb6 that is legal in no reading of the line: the move does not read
    live.apply(state, book, {"moves": {qb6: {"san": "O-O-O"}}})
    assert game(book)[-1]["san"] is None
    s = live.suggest(state, d5)
    assert (s["kind"], s["key"], s["after"], s["number_gap"]) == ("failed", qb6, d5, 0)
    assert s["decoded"] == []
    assert live.suggest(state, key_of(book, "Bg5"))["key"] == qb6


def test_connect_before_round_trip():
    a, b = "12:103,214:c4", "11:272,579:'it'et"
    data = fixes.normalise({"connect": {a: {"after": b, "before": [" f5 "]}}})
    assert data["connect"] == {a: {"after": b, "before": ["f5"]}}
    assert list(data["connect"][a]) == ["after", "before"]
    assert fixes.normalise({"connect": {a: {"after": b, "before": "Qc1 f5"}}})["connect"][a] == \
        {"after": b, "before": ["Qc1", "f5"]}
    # an empty list is left out, and the corrections of earlier versions stay valid
    assert fixes.normalise({"connect": {a: {"after": b, "before": []}}})["connect"][a] == {"after": b}
    assert fixes.normalise({"connect": {a: {"after": b}}})["connect"][a] == {"after": b}
    assert fixes.normalise({"connect": {a: b}})["connect"][a] == {"after": b}
    with pytest.raises(ValueError):
        fixes.normalise({"connect": {a: {"after": b, "before": ["f5", ""]}}})
    with pytest.raises(ValueError):
        fixes.normalise({"connect": {a: {"after": b, "before": [5]}}})


def test_the_driver_answers_suggest(tmp_path, monkeypatch):
    """web/driver.py suggest(): JSON for the worker's {suggest} message."""
    from test_web import _driver
    driver = _driver(tmp_path, monkeypatch)
    pdf = make_wells(tmp_path / "wells.pdf")
    driver.process(str(pdf), lambda *_: None)
    book = driver.STATE["book"]
    qb6, itet = key_of(book, "Qb6"), key_of(book, "'it'et")
    name = next(c["file"] for c in book["chapters"] if c["start"] <= 4 <= c["end"])
    out = json.loads(driver.suggest(qb6, name, "[]", "[]"))
    assert out["key"] == itet and out["after"] == qb6 and "seconds" in out
    out = json.loads(driver.suggest(qb6, name, json.dumps(["Qc1"]), json.dumps([itet])))
    assert out["key"] != itet
