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


def make_long(path, diagram=True, variation=False, note=False, misread=False, other_game=False,
              far=False, slip=False, lacking=False, between=False):
    """test_thread.make_wells, with the rest of the game on page 6
    (a diagram after 12.d6 when diagram). For the rules of reading on:
    variation adds a variation in a note ("4...Qa5+ 5.c3 Qb6", after which
    "6.c4 Bh6 7.e3" would read); note prints "6.c4 Bh6 7.e3 f4" in the
    notes' font; misread prints 4...Qb6 as "Qb8" (the program reads it as
    Qb6); other_game prints another game's header before "6.c4 ..." and
    far a page of prose; slip prints 10...Qxa1 as "Qxa7"; lacking prints
    5.Qc1 as such, so that the game goes on with "6.c4 ..." in its own text,
    which lacks 5...f5 (a gap in the line); between prints other moves in
    the game's font ("17.Rb1 Qa5") between "5.'it'et" and "6.c4 ..."."""
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
    w.line("4.d5 Qb8" if misread else "4.d5 Qb6", bold=True)
    w.line("Black aims at the weak b2 square.", indent=8)
    if variation:
        w.line("Or 4...Qa5+ 5.c3 Qb6 with play.", indent=8)
    w.prose(n=1)
    w.picture("4", caption="White to move")
    w.col(1)
    w.line("Black's plan gains momentum.", indent=8)
    w.prose(n=2)
    w.line("DARK SQUARES", bold=True, size=11, x=265)
    w.line("No doubt he was encouraged by White.", indent=8)
    w.prose(n=3)
    w.line("5.Qc1" if lacking else "5.'it'et", bold=True)
    if between:
        w.line("Compare a later game.", indent=8)
        w.line("17.Rb1 Qa5", bold=True)
    w.prose(until=H - 60)
    if far:
        w.page()
        w.prose(until=H - 60)
        w.col(1)
        w.prose(until=H - 60)
    w.page()
    if other_game:
        w.line("GAME TWO", bold=True, size=11, x=80)
        w.mixed([("Kramnik - Leko, ", True), ("Brissago 2004", False)])
    w.line("An awkward looking response.", bold=True)
    w.line("IS Shirov calls on the help of the f-pawn.", indent=8)
    w.prose(n=3)
    w.line("6.c4 Bh6 7.e3 f4", bold=not note)
    w.line("The intention is to leave White with", indent=8)
    w.line("a weak pawn on e3.")
    w.line("8.exf4 Bxf4 9.Qxf4 Qxb2", bold=True)
    w.line("Wells sacrifices the exchange.", indent=8)
    w.prose(until=H - 60)
    w.col(1)
    w.prose(until=H - 60)
    w.page()
    w.prose(n=2)
    w.line("10.Ne2 Qxa7 11.Nc3 Qb2" if slip else "10.Ne2 Qxa1 11.Nc3 Qb2", bold=True)
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


def at(n):
    """The position after the game's first n moves, as the program's
    corrections hold it ("at")."""
    return " ".join(_fen(n).fen().split()[:2])


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


def the_reader(book, qb6="Qb6"):
    """The reader's own correction: 5.Qc1 for the junk, joined after 4...Qb6
    (printed as qb6)."""
    qb6, itet = key_of(book, qb6), key_of(book, "'it'et")
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
    assert res["auto"] == {"connect": {c4: {"after": itet, "before": ["f5"], "auto": True,
                                            "at": at(10)},
                                       qe3: {"after": d6, "before": ["Qc2"], "auto": True,
                                             "at": at(24)}}}
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
    # the position the program joined from ("at"), kept in its own entries only
    pos = at(10)
    data = fixes.normalise({"connect": {a: {"at": pos + " KQkq - 0 6", "auto": True, "after": b}},
                            "gaps": {a: {"san": ["Qc2"], "auto": True, "at": pos}}})
    assert list(data["connect"][a]) == ["after", "auto", "at"] and data["connect"][a]["at"] == pos
    assert data["gaps"][a] == {"san": ["Qc2"], "auto": True, "at": pos}
    assert "at" not in fixes.normalise({"connect": {a: {"after": b, "at": pos}}})["connect"][a]
    with pytest.raises(ValueError):
        fixes.normalise({"connect": {a: {"after": b, "auto": True, "at": "a board"}}})
    # the reader's removal of the program's join: stored, and the entry gone
    gone = fixes.decline(data, a, "connect")
    assert gone["declined"] == {a: {"part": "connect"}} and a not in gone["connect"]
    assert gone["gaps"][a] == data["gaps"][a]
    gone = fixes.decline(data, a)                        # (every entry of the program's there)
    assert gone["declined"] == {a: {"part": "connect"}} and not gone["connect"] and not gone["gaps"]
    assert fixes.normalise({"declined": {a: True}})["declined"] == {a: {"part": "connect"}}
    assert fixes.count(gone)["declined"] == 1
    with pytest.raises(ValueError):
        fixes.normalise({"declined": {a: {"part": "moves"}}})


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
    assert out["auto"]["connect"][c4] == {"after": itet, "before": ["f5"], "auto": True,
                                          "at": at(10)}
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
    assert final["corrections"]["connect"][c4] == {"after": itet, "before": ["f5"], "auto": True,
                                                   "at": at(10)}
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
    # the reader keeps the reader's removals of the program's joins (corrections.py "declined")
    from chessbook.review_js import CORRECTIONS_JS, REVIEW_JS
    assert '"added",\n    "declined"];' in CORRECTIONS_JS
    assert 'if (was && was.auto) FIX.set("declined", src.key, {part: "connect"});' in REVIEW_JS
    worker = (ROOT / "web" / "worker.js").read_text(encoding="utf-8")
    assert 'msg.type === "readOn"' in worker and "driver.read_on(" in worker
    run = worker[worker.index("async function run("):worker.index("onmessage =")]
    assert "await first();" in run
    more = worker[worker.index('msg.type === "correct-more"'):]
    assert more.index("await first();") < more.index("driver.correct_more(")


# ---------------------------------------------------------------- the rules
# read_on runs by itself after every correction the reader makes, so it never
# joins or fills a move it is not sure of: it stops and leaves it to the reader.

@pytest.fixture(scope="module")
def variant(tmp_path_factory):
    """Books made by make_long with options, built once each."""
    made = {}

    def get(**kw):
        name = "-".join(sorted(kw)) or "plain"
        if name not in made:
            tmp = tmp_path_factory.mktemp(name)
            pdf = make_long(tmp / "wells.pdf", **kw)
            state = {}
            fens, readings = _diagrams(kw.get("diagram", True))
            book = build_book(pdf, output_dir=tmp / "out", books_dir=tmp / "books", state=state,
                              diagram_fens=fens, readings=readings)
            made[name] = (tmp, pdf, book, state)
        tmp, pdf, book, state = made[name]
        live.apply(state, book, {})
        return tmp, pdf, book, state
    return get


def test_a_variation_does_not_read_on_by_itself(variant):
    """A note's variation ("4...Qa5+ 5.c3 Qb6") after which the game's next
    run ("6.c4 Bh6 7.e3") would read: the program reads on by itself only
    along a game's main line."""
    _, _, book, state = variant(variation=True)
    var = next(n for n in book["nodes"].values() if n.get("san") == "Qb6" and not n["main"])
    c4 = key_of(book, "c4")
    res = live.read_on(state, book, {}, var["key"])
    assert res["auto"] == {} and res["joined"] == [] and res["filled"] == []
    assert c4 in {u["key"] for u in book["unattached"]}
    assert not any(n.get("auto") for n in book["nodes"].values())


def test_a_note_in_the_next_column_is_not_the_game(variant):
    """The game's next moves printed in the notes' font: not joined, the
    reader is asked."""
    _, _, book, state = variant(note=True)
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    res = live.read_on(state, book, fix, itet)
    assert res["auto"] == {} and sans(book) == sans_of(GAME[:9])
    assert not res["stop"]["done"] and res["stop"]["key"] == c4
    assert "printed as a note" in res["stop"]["reason"]


def test_another_games_run_is_not_joined(variant):
    """Another game's header printed before "6.c4 ...": the program does not
    join it to the game it reads on (the reader may)."""
    _, _, book, state = variant(other_game=True)
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    res = live.read_on(state, book, fix, itet)
    assert res["auto"] == {} and sans(book) == sans_of(GAME[:9])
    assert res["stop"]["done"] and "another game" in res["stop"]["reason"] and "ask" not in res["stop"]
    assert res["stop"]["next"]["key"] == c4


def test_a_far_run_is_not_joined(variant):
    """"6.c4 ..." printed two pages after 5.Qc1, though only one move is
    missing before it and f5 would decide it: too far to join by itself or
    to ask about."""
    _, _, book, state = variant(far=True)
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    res = live.read_on(state, book, fix, itet)
    assert res["auto"] == {} and res["filled"] == [] and sans(book) == sans_of(GAME[:9])
    assert res["stop"]["done"] and res["stop"]["reason"] == "nothing more follows the line nearby"
    assert res["stop"]["next"]["key"] == c4 and res["stop"]["next"]["page"] == 6 and "ask" not in res["stop"]


def test_moves_printed_between_are_left_to_the_reader(variant):
    """Other moves printed between 5.Qc1 and "6.c4 ...": the program does
    not join the run by itself, but the line may go on there, so its stop
    says so ("ask"), and the reader is asked about the run as before."""
    _, _, book, state = variant(between=True)
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    res = live.read_on(state, book, fix, itet)
    assert res["auto"] == {} and sans(book) == sans_of(GAME[:9])
    stop = res["stop"]
    assert stop["done"] and stop["ask"] and stop["next"]["key"] == c4
    assert stop["reason"] == "other moves are printed between the line's end and 6.c4"
    s = live.suggest(state, itet)
    assert s["key"] == c4 and s["number_gap"] == 1 and s["between"][0] == ["f5"]


def test_no_reading_on_after_a_misread_move(variant):
    """4...Qb6 printed as "Qb8" (the program reads Qb6, the only queen move
    that fits): the line holds a misread move, and the program does not
    build on it; once the reader names it, it reads on."""
    _, _, book, state = variant(misread=True)
    fix, itet = the_reader(book, "Qb8")
    qb8 = key_of(book, "Qb8")
    res = live.read_on(state, book, fix, itet)
    assert res["auto"] == {} and sans(book) == sans_of(GAME[:9])
    assert not res["stop"]["done"] and "where the book prints Qb8" in res["stop"]["reason"]
    fix["moves"][qb8] = {"san": "Qb6"}
    res = live.read_on(state, book, fix, itet)
    assert sans(book) == sans_of(GAME) and res["auto"]["connect"]


@pytest.mark.parametrize("how", [{"start": "here"}, {"remove": True}])
def test_read_on_respects_the_readers_split(variant, how):
    """The reader ended the line before 4.d5 (a new line from it, or its moves
    in no line): reading on from 3...gxf6 does not join them back."""
    _, _, book, state = variant()
    d5 = key_of(book, "d5")
    fix = {"disconnect": {d5: how}}
    live.apply(state, book, fix)
    assert sans(book) == GAME[:6]
    res = live.read_on(state, book, fix, key_of(book, "gxf6"))
    assert res["auto"] == {} and sans(book) == GAME[:6]
    if "start" in how:
        assert res["stop"]["done"] and res["stop"]["reason"] == "you ended the line here"
        assert res["stop"]["next"]["key"] == d5
    else:
        assert d5 in {u["key"] for u in book["unattached"]}


def test_a_removal_is_stored_and_kept(variant):
    """The reader removes the program's join of 6.c4 (corrections.decline,
    or skip): the corrections keep it ("declined"), and the program does not
    join it again, also in a book read again with them."""
    tmp, pdf, book, state = variant()
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    full = live.read_on(state, book, fix, itet)["corrections"]
    gone = fixes.decline(full, c4)
    assert c4 not in gone["connect"] and gone["declined"] == {c4: {"part": "connect"}}
    assert fixes.normalise(gone) == gone
    live.apply(state, book, gone)
    assert sans(book) == sans_of(GAME[:9])
    res = live.read_on(state, book, gone, itet)
    assert res["auto"] == {} and sans(book) == sans_of(GAME[:9])
    assert res["stop"]["key"] == c4 and "took back" in res["stop"]["reason"]
    assert res["corrections"]["declined"] == {c4: {"part": "connect"}}
    # skip stores it the same way
    live.apply(state, book, full)
    res = live.read_on(state, book, {k: v for k, v in full.items() if k != "connect"} |
                       {"connect": {k: v for k, v in full["connect"].items() if k != c4}},
                       itet, skip=[c4])
    assert res["corrections"]["declined"] == {c4: {"part": "connect"}} and res["auto"] == {}
    # a book read again with the corrections
    again = build(tmp, pdf, gone)
    assert again["corrections"]["declined"] == {c4: {"part": "connect"}}
    assert sans(again) == sans_of(GAME[:9])


def test_the_programs_entries_are_checked_again(variant):
    """A correction of a move before the program's joins: entries made from
    a position that changed are dropped and read again from the move
    corrected; when the reader takes back their own move, the program's
    entries after it go too."""
    _, _, book, state = variant()
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    full = live.read_on(state, book, fix, itet)["corrections"]
    assert set(full["connect"]) == {itet, c4, key_of(book, "Qe3")}
    # 5.Qd2 for 5.Qc1: every position after it changes
    other = copy.deepcopy(full)
    other["moves"][itet] = {"san": "Qd2"}
    live.apply(state, book, other)
    assert fixes.auto_part(book["corrections"]) == {}
    assert sans(book)[:9] == sans_of(GAME[:8] + ["Qd2"]) and len(sans(book)) == 9
    # (read on from it again, the program reads only what the new position decides)
    res = live.read_on(state, book, other, itet)
    for v in res["auto"].get("connect", {}).values():
        assert v["at"] != at(10)
    # an entry of an earlier version (no "at"): dropped, and read again
    old = copy.deepcopy(full)
    del old["connect"][c4]["at"]
    live.apply(state, book, old)
    assert fixes.auto_part(book["corrections"]) == {} and sans(book) == sans_of(GAME[:9])
    res = live.read_on(state, book, old, itet)
    assert res["corrections"]["connect"] == full["connect"] and sans(book) == sans_of(GAME)
    # the reader takes back their own 5.Qc1: the program's joins after it go
    mine = copy.deepcopy(full)
    del mine["moves"][itet], mine["connect"][itet]
    live.apply(state, book, mine)
    assert sans(book) == GAME[:8] and fixes.auto_part(book["corrections"]) == {}


def test_a_join_stops_before_a_misread_move(variant):
    """10...Qxa1 printed as "Qxa7" in the run the program joins (the only
    reading that fits is Qxa1, at a cost): it joins the run up to 10.Ne2
    and leaves the rest to the reader; once the reader names the move and
    joins it, the program reads on to the end of the game."""
    tmp, pdf, book, state = variant(slip=True)
    fix, itet = the_reader(book)
    c4, qxa7 = key_of(book, "c4"), key_of(book, "Qxa7")
    res = live.read_on(state, book, fix, itet)
    assert sans(book) == sans_of(GAME[:19])
    assert list(res["auto"]["connect"]) == [c4] and res["filled"][0]["san"] == ["f5"]
    assert not res["stop"]["done"] and res["stop"]["key"] == qxa7
    assert "Qxa7" in res["stop"]["reason"]
    assert qxa7 in {u["key"] for u in book["unattached"]}
    # the same in a book read again with the corrections
    assert sans(build(tmp, pdf, res["corrections"])) == sans_of(GAME[:19])
    fix = copy.deepcopy(res["corrections"])
    ne2 = game(book)[-1]["key"]
    fix["moves"][qxa7] = {"san": "Qxa1"}
    fix["connect"][qxa7] = {"after": ne2}
    res = live.read_on(state, book, fix, qxa7)
    assert sans(book) == sans_of(GAME)


def test_a_gap_fill_stops_before_a_misread_move(variant):
    """The game's own text lacks 5...f5 (a gap in the line) and prints
    10...Qxa1 as "Qxa7" further on, past the moves read_on reads to decide
    the fill: the program supplies f5, but the line's moves after it read
    on only up to 10.Ne2; the rest is left to the reader, as after a join."""
    tmp, pdf, book, state = variant(lacking=True, slip=True)
    qc1, c4, qxa7 = key_of(book, "Qc1"), key_of(book, "c4"), key_of(book, "Qxa7")
    assert sans(book)[:9] == sans_of(GAME[:9])
    gap = game(book)[9]
    assert gap["status"] == "failed" and gap.get("gap") == c4
    res = live.read_on(state, book, {}, qc1)
    assert res["auto"] == {"gaps": {c4: {"san": ["f5"], "auto": True, "at": at(9)}}}
    assert [f["how"] for f in res["filled"]] == ["decisive"] and res["joined"] == []
    assert sans(book) == sans_of(GAME[:19])
    assert not any(n["status"] in ("failed", "guessed") and n.get("key") for n in game(book))
    assert qxa7 in {u["key"] for u in book["unattached"]}
    assert not res["stop"]["done"] and res["stop"]["key"] == qxa7
    # the same in a book read again with the corrections
    assert sans(build(tmp, pdf, res["corrections"])) == sans_of(GAME[:19])
    # once the reader names the move, the program reads on through 12.d6 (13.Qe3, which
    # the text printed after the line broke, starts a line of its own: the reader joins it)
    fix = copy.deepcopy(res["corrections"])
    fix["moves"][qxa7] = {"san": "Qxa1"}
    fix["connect"][qxa7] = {"after": game(book)[-1]["key"]}
    res = live.read_on(state, book, fix, qxa7)
    assert sans(book) == sans_of(GAME[:23])
    assert res["stop"]["key"] == key_of(book, "Qe3")


def test_read_on_from_a_move_in_no_line_stops(variant):
    """The reader's join is refused (its first move is not legal after the
    move the reader gave before it): read_on, run from it, reads nothing and
    says why, rather than fail; the correction itself is applied."""
    _, _, book, state = variant()
    fix, itet = the_reader(book)
    c4 = key_of(book, "c4")
    fix["connect"][c4] = {"after": itet, "before": ["Qa5+"]}
    res = live.read_on(state, book, fix, c4)
    assert res["auto"] == {} and res["joined"] == [] and res["filled"] == []
    assert res["stop"]["done"] and "stands in no line" in res["stop"]["reason"]
    assert res["moves"] == 0 and res["end"] is None
    assert sans(book) == sans_of(GAME[:9])
    assert any(u["key"] == c4 and "not a legal move" in u["reason"] for u in book["unattached"])
