"""Tests for reading on by itself after a correction (assemble._Builder
read_on, live.read_on, corrections.py "auto", web/driver.py read_on,
progressive.Job.read_on).

The generated book is test_thread.py's Wells - Shirov case carried to the
end of the game: after "8.exf4 Bxf4 9.Qxf4 Qxb2" page 6
prints "10.Ne2 Qxa1 11.Nc3 Qb2", "12.d6", a diagram of the position after
12...Qc2 (a move the text lacks) and "13.Qe3 1-0". The reader gives only
5.Qc1 (the move printed as OCR junk) and joins it after 4...Qb6; one
read_on then supplies 5...f5 (the moves printed after it decide it), joins
"6.c4 ..." through 12.d6, supplies 12...Qc2 from the diagram and merges
13.Qe3: the whole game, with no move the book does not hold. Without the
diagram it stops before 13.Qe3 and says that Black's 12th move is missing.
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

GAME = ("d4 Nf6 Bg5 c5 Bxf6 gxf6 d5 Qb6 Qc1 f5 c4 Bh6 e3 f4 exf4 Bxf4 Qxf4 Qxb2 Ne2 Qxa1 "
        "Nc3 Qb2 d6 Qc2 Qe3").split()
QC1 = {"san": "Qc1"}


def make_long(path, diagram=True):
    """test_thread.make_wells, with the rest of the game on page 6
    (a diagram after 12.d6 when diagram)."""
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
    w.page()
    w.prose(n=2)
    w.line("10.Ne2 Qxa1 11.Nc3 Qb2", bold=True)
    w.line("The queen has to come back.", indent=8)
    w.line("12.d6", bold=True)
    w.line("A pawn on d6 cuts the board in two.", indent=8)
    w.prose(n=1)
    if diagram:
        w.picture("12", caption="White to move")
    else:
        w.prose(n=3)
    w.line("13.Qe3 1-0", bold=True)
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


def _fen(n):
    b = chess.Board()
    for san in GAME[:n]:
        b.push_san(san)
    return b


def _diagrams(diagram=True):
    """Diagram 4 lacks the pawn on f2 (a doubtful reading), diagram 12 shows
    the position after 12...Qc2."""
    b = _fen(8)
    b.remove_piece_at(chess.F2)
    fens = {"p4-1": b.fen()}
    readings = {"p4-1": {"fen": b.fen(), "confidence": 0.3, "doubtful": ["f2"], "turn": "w",
                         "turn_from": "caption", "flipped": False}}
    if diagram:
        fen = _fen(24).fen()
        fens["p6-1"] = fen
        readings["p6-1"] = {"fen": fen, "confidence": 0.95, "doubtful": [], "turn": "w",
                            "turn_from": "caption", "flipped": False}
    return fens, readings


def build(tmp, pdf, fix=None, state=None, diagram=True):
    fens, readings = _diagrams(diagram)
    return build_book(pdf, output_dir=tmp / "out", books_dir=tmp / "books", corrections=fix,
                      state=state, diagram_fens=fens, readings=readings)


def _book(tmp_path_factory, diagram):
    tmp = tmp_path_factory.mktemp("long" if diagram else "short")
    pdf = make_long(tmp / "wells.pdf", diagram)
    state = {}
    book = build(tmp, pdf, state=state, diagram=diagram)
    return tmp, pdf, book, state


@pytest.fixture(scope="module")
def long_book(tmp_path_factory):
    return _book(tmp_path_factory, True)


@pytest.fixture(scope="module")
def no_diagram(tmp_path_factory):
    return _book(tmp_path_factory, False)


@pytest.fixture
def fresh(request):
    """The module's book and state, given back without corrections after the
    test (request.param names the fixture)."""
    tmp, pdf, book, state = request.getfixturevalue(request.param)
    book = copy.deepcopy(book)
    yield tmp, pdf, book, state
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


def the_reader(book):
    """The reader's own correction: 5.Qc1 for the junk, joined after 4...Qb6."""
    qb6, itet = key_of(book, "Qb6"), key_of(book, "'it'et")
    return {"moves": {itet: QC1}, "connect": {itet: {"after": qb6}}}, itet


def test_the_long_book_reproduces_the_case(long_book):
    _, _, book, _ = long_book
    assert sans(book) == GAME[:8]
    u = {x["key"]: x for x in book["unattached"]}
    c4 = key_of(book, "c4")
    assert c4 in u and key_of(book, "'it'et") in u
    # 13.Qe3 starts a line of its own from diagram 12
    qe3 = next(n for n in book["nodes"].values() if n.get("key") == key_of(book, "Qe3"))
    frag = next(L for L in book["lines"] if L["id"] == qe3["line"])
    assert frag["kind"] == "fragment" and frag["diagram"] == "p6-1"


@pytest.mark.parametrize("fresh", ["long_book"], indirect=True)
def test_one_read_on_threads_the_whole_game(fresh):
    tmp, pdf, book, state = fresh
    fix, itet = the_reader(book)
    c4, qe3 = key_of(book, "c4"), key_of(book, "Qe3")
    res = live.read_on(state, book, fix, itet)
    assert sans(book) == sans_of(GAME)
    nodes = game(book)
    # the moves the program supplied are its assumptions: doubtful until the reader checks them
    f5, qc2 = nodes[9], nodes[23]
    for n, san in ((f5, "f5"), (qc2, "Qc2")):
        assert n["san"] == san and n["corrected"] == "assumed" and n["status"] == "guessed"
        assert n["auto"] and not n.get("key")
    # its joins are marked as its own, and the reader's join as the reader's
    assert nodes[8]["corrected"] == "connected" and not nodes[8].get("auto")
    assert nodes[10]["key"] == c4 and nodes[10]["corrected"] == "connected" and nodes[10]["auto"]
    assert nodes[24]["key"] == qe3 and nodes[24]["auto"]
    mark = next(m for p in book["pages"] for m in p["marks"] if m["key"] == c4)
    assert mark["corrected"] == "connected" and mark["auto"]
    # the corrections it made, in the stored form
    d6 = nodes[22]["key"]
    assert res["auto"] == {"connect": {c4: {"after": itet, "before": ["f5"], "auto": True},
                                       qe3: {"after": d6, "before": ["Qc2"], "auto": True}}}
    assert res["corrections"]["connect"] == dict(fix["connect"], **res["auto"]["connect"])
    assert fixes.normalise(res["corrections"]) == res["corrections"]
    assert book["corrections"] == res["corrections"]
    assert [(f["key"], f["san"], f["how"], f["diagram"]) for f in res["filled"]] == \
        [(c4, ["f5"], "decisive", None), (qe3, ["Qc2"], "diagram", "p6-1")]
    assert [(j["key"], j["after"], j["moves"]) for j in res["joined"]] == [(c4, itet, 13), (qe3, d6, 1)]
    assert res["moves"] == 16 and res["end"] == qe3
    assert res["stop"]["done"] and "result" in res["stop"]["reason"]
    assert res["until"] == book["chapters"][1]["end"]
    # the counts of the reader's corrections leave the program's out
    assert book["stats"]["corrected"]["connections"] == 1
    assert book["stats"]["corrected"]["gap_moves"] == 0
    assert res["seconds"] < 10
    # a fresh build with the corrections gives the same book
    assert comparable(book) == comparable(build(tmp, pdf, res["corrections"]))


@pytest.mark.parametrize("fresh", ["no_diagram"], indirect=True)
def test_read_on_stops_where_the_text_lacks_a_move(fresh):
    _, _, book, state = fresh
    fix, itet = the_reader(book)
    qe3 = key_of(book, "Qe3")
    res = live.read_on(state, book, fix, itet)
    assert sans(book) == sans_of(GAME[:23])
    stop = res["stop"]
    assert not stop.get("done")
    assert (stop["kind"], stop["key"], stop["page"], stop["raw"]) == ("run", qe3, 6, "Qe3")
    assert stop["number_gap"] == 1 and stop["missing"] == {"from_ply": 23, "count": 1}
    assert stop["reason"] == "Black's 12th move is missing before 13.Qe3"
    assert stop["after"] == game(book)[-1]["key"] and stop["bbox"]
    # the moves offered for it: Black's moves, nothing in the text decides between them
    board = _fen(23)
    assert stop["between"] and all(len(x) == 1 and board.parse_san(x[0]) for x in stop["between"])
    # 13.Qe3 is not joined: every move of Black's would let it read
    assert qe3 not in res["auto"].get("connect", {})
    assert [f["san"] for f in res["filled"]] == [["f5"]]


def sans_of(moves):
    b, out = chess.Board(), []
    for m in moves:
        out.append(b.san(b.parse_san(m)))
        b.push_san(m)
    return out


@pytest.mark.parametrize("fresh", ["long_book"], indirect=True)
def test_the_programs_corrections_stay_and_go(fresh):
    """The program's joins hold through the reader's next correction (which
    derives the lines from all corrections again), the reader may remove one,
    and a join the reader removed (skip) is not made again."""
    _, _, book, state = fresh
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    res = live.read_on(state, book, fix, itet)
    full = res["corrections"]
    # the reader's next correction, elsewhere: the whole game stays
    nxt = copy.deepcopy(full)
    nxt["moves"][key_of(book, "Bh6")] = {"san": "Bh6"}
    live.apply(state, book, nxt)
    assert len(sans(book)) == len(GAME)
    # the reader removes the program's join of 6.c4: the line ends at 5.Qc1 again
    gone = copy.deepcopy(full)
    del gone["connect"][c4]
    live.apply(state, book, gone)
    assert sans(book) == sans_of(GAME[:9])
    res = live.read_on(state, book, gone, itet, skip=[c4])
    assert res["auto"] == {} and sans(book) == sans_of(GAME[:9])
    assert res["stop"]["key"] == c4 and "took back" in res["stop"]["reason"]


@pytest.mark.parametrize("fresh", ["long_book"], indirect=True)
def test_read_on_after_a_move_that_needs_the_reader(fresh):
    """Before the reader names 5.Qc1, nothing reads after 4...Qb6: read_on
    joins nothing and stops at the junk, for the reader to make the move."""
    _, _, book, state = fresh
    qb6, itet = key_of(book, "Qb6"), key_of(book, "'it'et")
    res = live.read_on(state, book, {}, qb6)
    assert res["auto"] == {} and res["joined"] == [] and sans(book) == GAME[:8]
    assert (res["stop"]["key"], res["stop"]["kind"], res["stop"]["number_gap"]) == (itet, "run", 0)
    assert "cannot read 5.'it'et" in res["stop"]["reason"]


@pytest.mark.parametrize("fresh", ["long_book"], indirect=True)
def test_read_on_never_takes_a_note_for_the_game(fresh):
    """The book prints its games' moves in a font of their own: a run printed
    as a note is never joined to the game by the program, however well it
    reads (the reader may join it)."""
    _, _, book, state = fresh
    b = state["builder"]
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    run = next(r for _, r in b.base["unplaced"] if b.key_of(r.moves[0], r.ci) == c4)
    assert b.moves_font and run.kind == "main"
    run.kind = "note"
    try:
        res = live.read_on(state, book, fix, itet)
    finally:
        run.kind = "main"
    assert res["auto"] == {} and sans(book) == sans_of(GAME[:9])
    assert res["stop"]["key"] == c4 and "printed as a note" in res["stop"]["reason"]
    assert res["stop"]["number_gap"] == 1 and ["f5"] in res["stop"]["between"]


def test_auto_corrections_round_trip():
    a, b = "12:103,214:c4", "11:272,579:'it'et"
    data = fixes.normalise({"connect": {a: {"auto": 1, "before": "f5", "after": b}},
                            "gaps": {a: {"san": "Qc2", "auto": True}}})
    assert data["connect"][a] == {"after": b, "before": ["f5"], "auto": True}
    assert list(data["connect"][a]) == ["after", "before", "auto"]
    assert data["gaps"][a] == {"san": ["Qc2"], "auto": True}
    assert fixes.auto_part(data) == {"connect": data["connect"], "gaps": data["gaps"]}
    # the reader's own entries (and those of earlier versions) carry no flag
    plain = fixes.normalise({"connect": {a: {"after": b, "auto": False}}, "gaps": {a: ["Qc2"]}})
    assert plain["connect"][a] == {"after": b} and plain["gaps"][a] == {"san": ["Qc2"]}
    assert fixes.auto_part(plain) == {}


def test_the_driver_answers_read_on(tmp_path, monkeypatch):
    """web/driver.py read_on(): the worker's {readOn} message, answered with
    the patch, the corrections with the program's, and where it stopped."""
    from test_web import _driver
    driver = _driver(tmp_path, monkeypatch)
    pdf = make_long(tmp_path / "wells.pdf")
    driver.process(str(pdf), lambda *_: None)
    book = driver.STATE["book"]
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    name = next(c["file"] for c in book["chapters"] if c["start"] <= 4 <= c["end"])
    driver.chapter(name, lambda *_: None)
    out = json.loads(driver.read_on(itet, name, json.dumps(fix), json.dumps({"pages": 5})))
    assert out["chapter"] == name and not out["queued"] and out["patch"]["nodes"]
    assert out["auto"]["connect"][c4] == {"after": itet, "before": ["f5"], "auto": True}
    assert out["corrections"]["connect"][c4]["auto"] and out["patch"]["corrections"] == out["corrections"]
    assert out["filled"][0]["san"] == ["f5"] and out["moves"] >= 14 and "seconds" in out
    assert {"stop", "joined", "until", "end", "pending"} <= set(out)
    # the corrections are saved with the program's, for a book read again
    saved = json.loads(Path(driver.STATE["fix_path"]).read_text())
    assert saved["connect"][c4]["auto"]
    # without corrections given, the set the book holds is used
    out2 = json.loads(driver.read_on(itet, name))
    assert out2["auto"] == {} and out2["corrections"] == out["corrections"]


def test_a_book_still_read_reads_on_in_its_chapter(tmp_path, monkeypatch):
    """While the book is read (progressive.Job), read_on applies to the
    chapter's own reading, made at once, and the final book keeps the
    program's corrections."""
    from chessbook import assemble, progressive, reader
    monkeypatch.setattr(assemble, "OUTPUT_DIR", tmp_path / "shared")
    pdf = make_long(tmp_path / "wells.pdf", diagram=False)
    job = progressive.Job(pdf, tmp_path / "out", tmp_path / "books")
    while job.plain is None:
        job.step()
    k = next(c["index"] for c in job.chapters() if c["start"] <= 4 <= c["end"])
    while not job._can_solo(k):
        job.step()
    book = job.source(k)
    ch = book["chapters"][k]
    job.opened(ch["file"], live.snapshot(reader.chapter_data(book, ch, "")))
    # the keys of the printed moves are those of every reading: the chapter's own one gives them
    if k not in job.solo:
        job._solo(k)
    book = job.source(k)
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    res = job.read_on(fix, ch["file"], itet)
    assert not res["queued"] and res["patch"]
    assert res["auto"]["connect"][c4]["before"] == ["f5"]
    assert job.fix["connect"][c4]["auto"]
    while not job.done:
        job.step()
    final = job.final
    assert final["corrections"]["connect"][c4] == {"after": itet, "before": ["f5"], "auto": True}
    assert sans(final)[:11] == sans_of(GAME[:11])


def test_the_app_plumbs_read_on_first(tmp_path):
    """The page passes {readOn} from the reader to the worker and its answer
    back ({readOnDone}, {readOnFailed}, the patch as a correction's); the
    worker runs it before the book's reading steps and the piece-symbol
    replays (web/worker.js "urgent")."""
    from test_web import build
    page = build(tmp_path)
    assert 'Object.assign({ type: "readOn", chapter: openChapter }, e.data.readOn)' in page
    assert "toView({ readOnDone: done })" in page and "toView({ readOnFailed: m.text, id: m.id })" in page
    assert 'patched({ chapter: m.chapter, result: r })' in page
    worker = (ROOT / "web" / "worker.js").read_text(encoding="utf-8")
    assert 'msg.type === "readOn"' in worker and "driver.read_on(" in worker
    run = worker[worker.index("async function run("):worker.index("onmessage =")]
    assert "await first();" in run
    more = worker[worker.index('msg.type === "correct-more"'):]
    assert more.index("await first();") < more.index("driver.correct_more(")
