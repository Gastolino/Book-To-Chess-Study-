"""Tests for the reader's corrections (chessbook/corrections.py) and how
build_book applies them: a diagram's position, a move token, a sequence that
found no place, and a piece symbol that the text recognition garbled.

A generated book with a garbled game checks each kind exactly; the Primer
checks that correcting one failed move lets the moves after it decode.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from chessbook import corrections as fixes  # noqa: E402
from chessbook import reader  # noqa: E402
from chessbook.assemble import build_book  # noqa: E402
from chessbook.movetext import junk_prefix  # noqa: E402
from test_assemble import ENDING_FEN, line_titled, main_line, make_book  # noqa: E402

PDF = ROOT / "primer.pdf"
# the game of the generated book, with the knight printed as OCR junk ("tLl") and
# 5...Nxd5 printed as nothing a reader can parse ("Zq9")
GARBLED = ["1.e4 e5 2.tLlf3 tLlc6 3.Bc4 tLlf6", "4.tLlg5 d5 5.exd5 Zq9",
           "6.tLlxf7 Kxf7 7.Qf3+ Ke6", "8.tLlc3"]
SANS = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6", "Ng5", "d5", "exd5", "Nxd5", "Nxf7", "Kxf7",
        "Qf3+", "Ke6", "Nc3"]
NOTE = "Or 12.Qh5+ g6 is also strong."


@pytest.fixture(scope="module")
def garbled(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("garbled")
    pdf = make_book(tmp / "garbled.pdf", game=GARBLED, note7=NOTE)
    book = build_book(pdf, output_dir=tmp / "output", books_dir=tmp / "books")
    return tmp, pdf, book


def rebuild(tmp, pdf, fix):
    return build_book(pdf, output_dir=tmp / "output", books_dir=tmp / "books", corrections=fix)


def game_nodes(book):
    g = line_titled(book, "Smith - Jones")
    return g, [book["nodes"][i] for i in main_line(book, g)]


def key_of(nodes, raw):
    return next(n["key"] for n in nodes if n["raw"] == raw)


def test_the_garbled_book_needs_corrections(garbled):
    _, _, book = garbled
    _, nodes = game_nodes(book)
    zq9 = next(n for n in nodes if n["raw"] == "Zq9")
    assert zq9["status"] == "failed" and zq9["san"] is None
    assert all(n.get("key") for n in nodes)
    assert book["symbols"] == {"tLl": 6}
    (u,) = book["unattached"]
    assert u["text"] == "12.Qh5+ g6" and u["key"].endswith(":Qh5+")
    assert book["stats"]["corrected"] == {"moves": 0, "symbol_moves": 0, "diagrams": 0,
                                          "sequences": 0, "symbols": 0, "connections": 0,
                                          "splits": 0, "gap_moves": 0}


def test_corrected_move_decodes_and_the_line_goes_on(garbled):
    tmp, pdf, book = garbled
    _, nodes = game_nodes(book)
    key = key_of(nodes, "Zq9")
    fixed = rebuild(tmp, pdf, {"moves": {key: {"san": "Nxd5"}}})
    g, nodes = game_nodes(fixed)
    assert [n["san"] for n in nodes] == SANS
    zq9 = next(n for n in nodes if n["raw"] == "Zq9")
    assert zq9["status"] == "ok" and zq9["corrected"] == "move"
    # the moves after it decode from the corrected position
    after = nodes[nodes.index(zq9) + 1:]
    assert all(n["status"] in ("ok", "guessed", "ambiguous") and n["san"] for n in after)
    mark = next(m for p in fixed["pages"] for m in p["marks"] if m.get("key") == key)
    assert mark["corrected"] == "move"
    assert fixed["stats"]["corrected"]["moves"] == 1


def test_a_corrected_move_that_is_not_legal_says_so(garbled):
    tmp, pdf, book = garbled
    _, nodes = game_nodes(book)
    fixed = rebuild(tmp, pdf, {"moves": {key_of(nodes, "Zq9"): {"san": "Qh5"}}})
    _, nodes = game_nodes(fixed)
    zq9 = next(n for n in nodes if n["raw"] == "Zq9")
    assert zq9["status"] == "failed" and "is not legal" in zq9["reason"]


def test_glyph_correction_applies_throughout_the_book(garbled):
    tmp, pdf, book = garbled
    _, before = game_nodes(book)
    assert any(n["status"] != "ok" for n in before if n["raw"].startswith("tLl"))
    fixed = rebuild(tmp, pdf, {"glyphs": {"tLl": "N"}})
    _, nodes = game_nodes(fixed)
    knights = [n for n in nodes if n["raw"].startswith("tLl")]
    assert len(knights) == 6
    assert all(n["status"] == "ok" and n["san"].startswith("N") and n["corrected"] == "symbol"
               for n in knights)
    assert fixed["stats"]["corrected"]["symbols"] == 1
    assert fixed["stats"]["corrected"]["symbol_moves"] == 6


def test_glyph_correction_still_needs_a_legal_move_and_a_move_correction_wins(garbled):
    tmp, pdf, book = garbled
    _, nodes = game_nodes(book)
    # a wrong piece for the symbol: no bishop reaches f3 after 1.e4 e5, so 2.tLlf3 fails
    wrong = rebuild(tmp, pdf, {"glyphs": {"tLl": "B"}})
    _, w = game_nodes(wrong)
    assert next(n for n in w if n["raw"] == "tLlf3")["san"] != "Bf3"
    # a correction of the one move overrides the symbol's piece
    both = rebuild(tmp, pdf, {"glyphs": {"tLl": "B"},
                              "moves": {key_of(nodes, "tLlf3"): {"san": "Nf3"}}})
    _, b = game_nodes(both)
    nf3 = next(n for n in b if n["raw"] == "tLlf3")
    assert nf3["san"] == "Nf3" and nf3["corrected"] == "move"


def test_diagram_correction_wins_over_the_reading(garbled):
    tmp, pdf, book = garbled
    assert line_titled(book, "Diagram 12")["status"] == "waiting"
    fixed = rebuild(tmp, pdf, {"diagrams": {"p5-1": {"fen": ENDING_FEN}}})
    w = line_titled(fixed, "Diagram 12")
    assert w["status"] == "ok" and w["start_fen"] == ENDING_FEN
    assert [fixed["nodes"][i]["san"] for i in main_line(fixed, w)] == ["Rd8+", "Kh7", "Rd7", "Kg8"]
    d = fixed["pages"][4]["diagrams"][0]
    assert d["status"] == "corrected" and d["corrected"] and d["fen"] == ENDING_FEN
    assert fixed["stats"]["corrected"]["diagrams"] == 1


def test_unattached_sequence_is_placed_or_dismissed(garbled):
    tmp, pdf, book = garbled
    _, nodes = game_nodes(book)
    seq = book["unattached"][0]["key"]
    target = key_of(nodes, "Qf3+")
    fixed = rebuild(tmp, pdf, {"unattached": {seq: {"attach_to": target}}})
    assert fixed["unattached"] == [] and len(fixed["attached"]) == 1
    g, nodes = game_nodes(fixed)
    qf3 = next(n for n in nodes if n["raw"] == "Qf3+")
    parent = fixed["nodes"][qf3["parent"]]
    alt = fixed["nodes"][parent["children"][1]]
    assert alt["san"] == "Qh5+" and alt["corrected"] == "placed" and not alt["main"]
    assert fixed["nodes"][alt["children"][0]]["san"] == "g6"
    assert fixed["stats"]["corrected"]["sequences"] == 1
    gone = rebuild(tmp, pdf, {"unattached": {seq: {"attach_to": "dismiss"}}})
    assert gone["unattached"] == [] and gone["dismissed"][0]["key"] == seq
    assert not any(m["status"] == "unattached" for p in gone["pages"] for m in p["marks"])


def test_corrections_file_is_read_by_default(garbled):
    tmp, pdf, book = garbled
    path = fixes.corrections_path(pdf, tmp / "books")
    fixes.save({"glyphs": {"tLl": "N"}}, path)
    try:
        fixed = build_book(pdf, output_dir=tmp / "output", books_dir=tmp / "books")
        assert fixed["corrections"]["glyphs"] == {"tLl": "N"}
        assert fixed["stats"]["corrected"]["symbol_moves"] == 6
    finally:
        path.unlink()


def test_schema_and_pasted_text():
    data = fixes.parse_corrections_text(
        "Here they are:\n```json\n{\"version\": 1, \"diagrams\": {\"p5-1\": {\"fen\": \"" + ENDING_FEN +
        "\"}}, \"moves\": {\"4:116,496:Zq9\": {\"san\": \"Nxd5\"}}, \"unattached\": "
        "{\"4:258,68:Qh5+\": {\"attach_to\": \"dismiss\"}}, \"glyphs\": {\"tLl\": \"n\"},}\n```")
    assert data["glyphs"] == {"tLl": "N"} and data["moves"]["4:116,496:Zq9"] == {"san": "Nxd5"}
    assert data["unattached"]["4:258,68:Qh5+"] == {"attach_to": "dismiss"}
    assert fixes.count(data) == {"diagrams": 1, "moves": 1, "unattached": 1, "glyphs": 1,
                                 "connect": 0, "disconnect": 0, "gaps": 0}
    for bad in ({"diagrams": {"p5-1": {"fen": "8/8/8/8/8/8/8/8 w - - 0 1"}}},
                {"diagrams": {"page five": {"fen": ENDING_FEN}}},
                {"moves": {"Zq9": {"san": "Nxd5"}}},
                {"glyphs": {"tLl": "X"}}):
        with pytest.raises(ValueError):
            fixes.normalise(bad)
    with pytest.raises(ValueError):
        fixes.parse_corrections_text("no corrections here")
    assert fixes.token_key(4, [115.6, 496.2, 130, 505], "Zq9") == "4:116,496:Zq9"
    idx = fixes.TokenIndex({"4:116,496:Zq9": {"san": "Nxd5"}})
    assert idx.find(4, [117.4, 495.1, 0, 0], "Zq9")[1] == {"san": "Nxd5"}
    assert idx.find(4, [125, 496, 0, 0], "Zq9") == (None, None)
    assert idx.find(5, [116, 496, 0, 0], "Zq9") == (None, None)


def test_junk_prefix():
    assert junk_prefix("tLlxf6t") == "tLl"
    assert junk_prefix("\x18f3") == "\x18"
    for clean in ("Nf3", "exd5", "e4", "O-O", "Rd8+", "♘f3"):
        assert junk_prefix(clean) is None, clean
    assert junk_prefix("Sf3", "German") is None and junk_prefix("Sf3") == "S"


def test_make_reader_corrections_option(tmp_path, monkeypatch):
    """make_reader --corrections saves pasted corrections as the book's corrections."""
    import make_reader
    from chessbook import selection as selmod
    pasted = tmp_path / "pasted.txt"
    pasted.write_text("```json\n{\"glyphs\": {\"tLl\": \"N\"}, \"moves\": {}}\n```\n", encoding="utf-8")

    def fake_build(*a, **k):
        raise SystemExit(0)

    monkeypatch.setattr(selmod, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(fixes, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(make_reader.assemble, "build_book", fake_build)
    pdf = make_book(tmp_path / "little.pdf")
    with pytest.raises(SystemExit):
        make_reader.main([str(pdf), "--corrections", str(pasted)])
    saved = json.loads((tmp_path / "books" / "little" / "corrections.json").read_text(encoding="utf-8"))
    assert saved["glyphs"] == {"tLl": "N"}


def test_reader_data_for_review(garbled, tmp_path):
    tmp, pdf, book = garbled
    rep = reader.build_reader(book, pdf, tmp_path / "reader")
    assert "ch01.html" in rep["files"]
    text = (tmp_path / "reader" / "ch01.html").read_text(encoding="utf-8")
    from test_reader import script_json
    data = script_json(text, "data")
    zq9 = next(n for n in data["nodes"].values() if n["raw"] == "Zq9")
    assert ["Nxd5", "f6d5"] in zq9["legal"] and zq9["before"]
    assert data["symbols"] == {"tLl": 6}
    assert data["unattached"][0]["key"].endswith(":Qh5+")
    assert any(m.get("symbol") == "tLl" for p in data["pages"].values() for m in p["marks"])
    for needle in ('id="reviewbtn"', 'id="revlist"', 'id="fix"', 'id="symmenu"',
                   "chessbook-corrections:", "Corrected by you", "Not a variation",
                   "Save the position", "Remove your correction"):
        assert needle in text, needle
    index = (tmp_path / "reader" / "index.html").read_text(encoding="utf-8")
    assert 'id="copyfix"' in index and "chessbook-corrections:" in index


def test_contents_page_counts_corrections(garbled, tmp_path):
    tmp, pdf, book = garbled
    _, nodes = game_nodes(book)
    fixed = rebuild(tmp, pdf, {"glyphs": {"tLl": "N"}, "moves": {key_of(nodes, "Zq9"): {"san": "Nxd5"}},
                               "diagrams": {"p5-1": {"fen": ENDING_FEN}}})
    reader.build_reader(fixed, pdf, tmp_path / "reader", chapters=set())
    index = (tmp_path / "reader" / "index.html").read_text(encoding="utf-8")
    assert ("The run used your corrections of <span class=\"num\">1</span> move, "
            "<span class=\"num\">1</span> diagram and <span class=\"num\">1</span> piece symbol.") in index


# ------------------------------------------------------------------ moves the text lacks

# the game with Black's fifth move and White's sixth missing from the text: after
# 5.exd5 the score goes on with 6...Kxf7, which no move of Black's reads there
GAPPED = ["1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6", "4.Ng5 d5 5.exd5", "6...Kxf7 7.Qf3+ Ke6", "8.Nc3"]


@pytest.fixture(scope="module")
def gapped(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gapped")
    pdf = make_book(tmp / "gapped.pdf", game=GAPPED)
    state = {}
    book = build_book(pdf, output_dir=tmp / "output", books_dir=tmp / "books", state=state)
    return tmp, pdf, book, state


def gap_of(book):
    _, nodes = game_nodes(book)
    return next(n for n in nodes if n.get("gap") and not n["san"])


def test_a_gap_in_the_text_is_a_gap_node(gapped):
    _, _, book, _ = gapped
    _, nodes = game_nodes(book)
    hole = gap_of(book)
    assert hole["status"] == "failed" and hole["missing"] == 2 and hole["fill"] == []
    assert "lacks Black's move 5 and the 1 move after it" in hole["reason"]
    # the key of the gap is the key of the first printed move after it
    after = nodes[nodes.index(hole) + 1]
    assert after["raw"] == "Kxf7" and after["key"] == hole["gap"] and after["status"] == "failed"


def test_filling_a_gap_reads_the_line_on(gapped):
    tmp, pdf, book, _ = gapped
    key = gap_of(book)["gap"]
    fixed = rebuild(tmp, pdf, {"gaps": {key: {"san": ["Nxd5", "Nxf7"]}}})
    _, nodes = game_nodes(fixed)
    assert [n["san"] for n in nodes] == SANS
    assert not any(n.get("gap") and not n["san"] for n in nodes)
    given = [n for n in nodes if n.get("corrected") == "filled"]
    assert [n["san"] for n in given] == ["Nxd5", "Nxf7"] and all(n["gap"] == key for n in given)
    assert all(n["status"] == "ok" for n in nodes)
    assert line_titled(fixed, "Smith - Jones")["status"] == "ok"
    assert fixed["stats"]["corrected"]["gap_moves"] == 2


def test_a_partial_fill_keeps_a_smaller_gap(gapped):
    tmp, pdf, book, _ = gapped
    key = gap_of(book)["gap"]
    fixed = rebuild(tmp, pdf, {"gaps": {key: {"san": ["Nxd5"]}}})
    _, nodes = game_nodes(fixed)
    hole = gap_of(fixed)
    assert hole["gap"] == key and hole["fill"] == ["Nxd5"] and hole["missing"] == 1
    assert "lacks White's move 6," in hole["reason"]
    before = fixed["nodes"][hole["parent"]]
    assert before["san"] == "Nxd5" and before["corrected"] == "filled"
    after = nodes[nodes.index(hole) + 1]
    assert after["raw"] == "Kxf7" and after["status"] == "failed"


def test_a_fill_that_is_not_legal_is_ignored_with_the_reason(gapped):
    tmp, pdf, book, _ = gapped
    key = gap_of(book)["gap"]
    for fill, words in ((["Qh5"], "Qh5, is not a legal move for Black"),
                        (["Nxd5", "Nxf7", "h3"], "You gave 3 moves here, but the text lacks only 2")):
        fixed = rebuild(tmp, pdf, {"gaps": {key: {"san": fill}}})
        hole = gap_of(fixed)
        assert hole["fill"] == [] and hole["missing"] == 2 and words in hole["reason"], hole["reason"]
        assert fixed["stats"]["corrected"]["gap_moves"] == 0


def test_gap_corrections_round_trip(tmp_path):
    data = fixes.parse_corrections_text('{"gaps": {"4:238,54:Kxf7": {"san": ["Nxd5", " Nxf7 "]}}}')
    assert data["gaps"] == {"4:238,54:Kxf7": {"san": ["Nxd5", "Nxf7"]}}
    assert fixes.normalise({"gaps": {"4:238,54:Kxf7": "Nxd5"}})["gaps"]["4:238,54:Kxf7"] == {"san": ["Nxd5"]}
    assert fixes.count(data)["gaps"] == 1
    path = fixes.save(data, tmp_path / "corrections.json")
    assert fixes.normalise(json.loads(path.read_text(encoding="utf-8"))) == data
    for bad in ({"gaps": {"Kxf7": {"san": ["Nxd5"]}}}, {"gaps": {"4:238,54:Kxf7": {"san": []}}},
                {"gaps": {"4:238,54:Kxf7": {"san": [""]}}}):
        with pytest.raises(ValueError):
            fixes.normalise(bad)


def test_a_gap_is_filled_live(gapped):
    """The browser app's worker: live.apply replays the line of the gap at once,
    with the result of a fresh build, and the chapter's patch carries it."""
    import copy
    from chessbook import live
    tmp, pdf, book, state = gapped
    book = copy.deepcopy(book)
    key = gap_of(book)["gap"]
    ch = book["chapters"][1]
    old = reader.chapter_data(book, ch, "")
    hole_id = next(k for k, n in old["nodes"].items() if n.get("gap") and not n["san"])
    assert old["nodes"][hole_id]["fill"] == [] and old["nodes"][hole_id]["missing"] == 2
    assert old["nodes"][hole_id]["legal"] and ["Nxd5", "f6d5"] in old["nodes"][hole_id]["legal"]
    fix = {"gaps": {key: {"san": ["Nxd5"]}}}
    res = live.apply(state, book, fix)
    assert res["lines"] and key in book["corrections"]["gaps"]
    patch, new = live.chapter_patch(book, ch, old)
    assert any(n.get("corrected") == "filled" and n["san"] == "Nxd5" for n in patch["nodes"].values())
    hole = next(n for n in new["nodes"].values() if n.get("gap") and not n["san"])
    assert hole["fill"] == ["Nxd5"] and hole["missing"] == 1
    fresh = rebuild(tmp, pdf, fix)
    _, a = game_nodes(book)
    _, b = game_nodes(fresh)
    assert [(n["san"], n["status"], n.get("corrected")) for n in a] == \
        [(n["san"], n["status"], n.get("corrected")) for n in b]
    # the whole gap: the line reads on
    live.apply(state, book, {"gaps": {key: {"san": ["Nxd5", "Nxf7"]}}})
    _, a = game_nodes(book)
    assert [n["san"] for n in a] == SANS
    assert book["stats"]["corrected"]["gap_moves"] == 2
    live.apply(state, book, {})
    assert gap_of(book)["fill"] == []


# ------------------------------------------------------------------ the Primer

@pytest.mark.skipif(not PDF.exists(), reason="primer.pdf is not in the project folder")
def test_primer_correcting_a_failed_move_decodes_the_moves_after_it(tmp_path):
    """On PDF page 66 the text recognition reads 2.Qa1+ as "'l!Y", which the
    program cannot read, and the note's moves after it stay unread. Once the
    reader gives 2.Qa1+, it reads as that move, and the moves after it
    (Rg1 and Qh8#) decode from there."""
    book = build_book(PDF, output_dir=tmp_path / "out", books_dir=tmp_path / "books")
    nid, node = next((k, n) for k, n in book["nodes"].items()
                     if n["page"] == 66 and n["raw"] == "'l!Y")
    assert node["status"] == "failed" and node["san"] is None
    before = {n.get("key"): n["san"] for n in book["nodes"].values() if n["page"] == 66}
    fixed = build_book(PDF, output_dir=tmp_path / "out", books_dir=tmp_path / "books",
                       corrections={"moves": {node["key"]: {"san": "Qa1+"}}})
    hit = next(n for n in fixed["nodes"].values() if n.get("key") == node["key"])
    assert hit["san"] == "Qa1+" and hit["status"] == "ok" and hit["corrected"] == "move"
    after = [n for n in fixed["nodes"].values() if n["page"] == 66 and n["san"]
             and not before.get(n.get("key"))]
    assert {n["san"] for n in after} >= {"Qa1+", "Rg1", "Qh8#"}, [n["san"] for n in after]
    assert fixed["stats"]["corrected"]["moves"] == 1
    m = fixed["stats"]["moves"]
    b = book["stats"]["moves"]
    decoded = lambda s: s["ok"] + s["guessed"] + s["ambiguous"]  # noqa: E731
    assert decoded(m) >= decoded(b) + 3 and m["failed"] < b["failed"]
