"""Move numbers printed without a dot, moves set as a narrow table, and notes
attached as variations.

Books such as the Starting Out and Move by Move series print "1 e4 c5 2 Nc3"
with no dot after the move numbers; some set the moves of a game as a narrow
table, the number on one line and the move on the next, repeating the number
before Black's reply. The synthetic tests hold the forms these books print;
the regression tests at the end read pages of the books themselves and are
skipped when the PDFs are absent.
"""
import os
import sys
from pathlib import Path

import chess
import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook import assemble, pdftext as pt, selection as sel  # noqa: E402
from chessbook.movetext import (  # noqa: E402
    GlyphModel, decode, find_sequences, numbering_counts, tokenize, uses_dotless_numbers,
)

# the test books live in corpus/ of the project, or of the checkout that
# holds this one as a work tree, or where BOOK_CORPUS points
CORPUS = next((p / "corpus" for p in [ROOT, *ROOT.parents] if (p / "corpus").is_dir()),
              ROOT / "corpus")
if os.environ.get("BOOK_CORPUS"):
    CORPUS = Path(os.environ["BOOK_CORPUS"])


def runs(text, dotless=True):
    """[(first number, black, [(raw, number, black) of the moves])] of each run."""
    out = []
    for s in find_sequences(text, dotless=dotless):
        out.append((s.first_number, s.black_first,
                    [(t.raw, t.number, t.black) for t in s.tokens if t.kind == "move"]))
    return out


def move_raws(text, dotless=True):
    return [[m[0] for m in r[2]] for r in runs(text, dotless)]


def sans(text, board=None, dotless=True):
    seqs = find_sequences(text, dotless=dotless)
    assert seqs, text
    return [d.san for d in decode(board or chess.Board(), seqs[0].tokens)]


# ---------------------------------------------------------------- learning the habit
def test_numbering_counts_tell_dotless_books_apart():
    dotless = ["1 e4 c5 2 Nc3 Nc6 3 f4 g6 4 Nf3 Bg7 5 Bc4 e6 6 f5 Nge7 7 fxe6"]
    dotted = ["1.e4 c5 2.Nc3 Nc6 3.f4 g6 4.Nf3 Bg7 5.Bc4 e6 6.f5 Nge7 7.fxe6"]
    assert numbering_counts(dotless)["dotless"] >= 3
    assert numbering_counts(dotless)["dotted"] == 0
    assert numbering_counts(dotted)["dotless"] == 0
    assert uses_dotless_numbers(dotless)
    assert not uses_dotless_numbers(dotted)
    # prose with numbers is no evidence either way
    assert not uses_dotless_numbers(["He won 2 games in 1997 and lost 3 on page 12."] * 50)
    # a book that mixes both ("1 e4 d5" in the prose, "8.f4" in the games)
    assert uses_dotless_numbers(dotted * 10 + dotless * 2)


def test_dotted_books_keep_dotless_numbers_out():
    assert runs("1 e4 c5 2 Nc3 Nc6", dotless=False) == []
    assert move_raws("1.e4 c5 2.Nc3 Nc6", dotless=False) == [["e4", "c5", "Nc3", "Nc6"]]


# ---------------------------------------------------------------- tokenizer
def test_dotless_game_from_move_one():
    assert sans("1 e4 c5 2 Nc3 Nc6 3 f4 g6 4 Nf3 Bg7 5 Bc4") == [
        "e4", "c5", "Nc3", "Nc6", "f4", "g6", "Nf3", "Bg7", "Bc4"]


def test_dotless_ocr_forms():
    # "cs" for c5, "s" for the move number 5, "Bbs" for Bb5
    assert sans("1 e4 cs 2 Nc3 Nc6 3 f4 g6 4 Nf3 Bg7 s Bbs") == [
        "e4", "c5", "Nc3", "Nc6", "f4", "g6", "Nf3", "Bg7", "Bb5"]
    # a number split by a space, "1 1" for 11
    assert runs("10 ... Nd4 1 1 Nb5!")[0][2] == [("Nd4", 10, True), ("Nb5!", 11, False)]
    # a number glued to a figurine's junk, and two moves glued together
    assert move_raws("25lt)c4 i..ds?") == [["lt)c4", "i..ds?"]]
    assert move_raws("14 lDc4lDg6 15 l:tds!") == [["lDc4", "lDg6", "l:tds!"]]
    # castling split by a space
    assert move_raws("6 o -o Nxb5 7 Nxbs ds") == [["o -o", "Nxb5", "Nxbs", "ds"]]
    # dots spread over several words, and an OCR result
    assert runs("26 .. .fS 27 Rd1 1-o")[0][2] == [(".fS", 26, True), ("Rd1", 27, False)]


def test_dotless_black_moves():
    assert runs("3 ... e6 transposes to 2 ... e6 3 f4 Nc6") == [
        (3, True, [("e6", 3, True)]),
        (2, True, [("e6", 2, True), ("f4", 3, False), ("Nc6", 3, True)])]


def test_prose_numbers_stay_prose():
    for text in ("Black has 2 pawns and the 3 bishops on page 12 in 1997.",
                 "See Diagram 1 (B) and Game 3 in Chapter 5.",
                 "From 4312 games White scored 42%, with 1316 wins.",
                 "There are 3 ways to play it and 2 of them are bad."):
        assert runs(text) == [], text
    # the move after a diagram reference still counts
    assert move_raws("5 Bbs (Diagram 1) and now 5 ... Nd4") == [["Bbs"], ["Nd4"]]


def test_numbers_in_a_run_must_follow_on():
    # inside a run the expected number is read even when OCR spoils it
    assert runs("16 ... hs 11 tl)1h2 17 ... tl)fS")[0][2] == [
        ("hs", 16, True), ("tl)1h2", 17, False), ("tl)fS", 17, True)]
    assert runs("8 ... Nes g Nxes Bxes 10 Qhs!")[0][2] == [
        ("Nes", 8, True), ("Nxes", 9, False), ("Bxes", 9, True), ("Qhs!", 10, False)]
    # a digit that is the book's king glyph, glued to a capture, is no move
    # number the run does not expect ("6xg7" for Kxg7)
    assert runs("22 .*.xg7 6xg7 23 lld4")[0][2] == [
        (".*.xg7", 22, False), ("6xg7", 22, True), ("lld4", 23, False)]


def test_narrow_table_layout():
    # the number on its own line, the move on the next; the number repeated
    # before Black's reply; a glyph that starts with a dot (".t" for a bishop)
    text = "10\na3!\nGood.\n10\nh6?!\n11\nltJc3\n11\nl:.e8\n12\nltJd5\n12\nttJxd5\n13\n.txd5"
    text = text.replace("Good.", "     ")       # the main-font buffer blanks the notes
    r = runs(text)
    assert len(r) == 1
    assert [(m[1], m[2]) for m in r[0][2]] == [
        (10, False), (10, True), (11, False), (11, True), (12, False), (12, True), (13, False)]
    assert r[0][2][-1][0] == ".txd5"


def test_numbered_list_words_are_not_moves():
    assert runs("ANSWER: Black gains in two ways: 1. A pawn ... 4. White's knight",
                dotless=False) == []
    assert tokenize("Answer: 26 tbxb6+!", dotless=True)[0].kind == "other"


# ---------------------------------------------------------------- whole books
PAGES = [
    [("h", "Chapter 1"),
     ("n", "The Grand Prix Attack begins with simple moves."),
     ("m", "1 e4 c5 2 Nc3 Nc6 3 f4 g6 4 Nf3 Bg7 5 Bc4"),
     ("n", "In the next chapter we examine 5 Bb5, which is more popular."),
     ("m", "5 ... e6"),
     ("n", "5 ... d6 is dubious, as Black loses a tempo."),
     ("n", "3 ... e6 transposes to 2 ... e6 3 f4 Nc6 in Chapter Three."),
     ("m", "6 f5 Nge7 7 fxe6 fxe6"),
     ("n", "The alternative recapture, 7 ... dxe6, is examined in Game 2. White"),
     ("n", "has 2 pawns for the piece and 3 open files on page 12."),
     ("m", "8 d3 d5 9 Bb3"),
     ("n", "Unfavourable for White is 9 exd5 in view of 9 ... exd5 10 Bb3 c4"),
     ("n", "(10 ... Na5 11 Qe2 is unclear) and Black is fine."),
     ("n", "If 9 Bb5, then 9 ... d4 10 Ne2 Qb6 with an equal game."),
     ("m", "9 ... b5 10 0-0 c4 11 Ba4 0-0")],
]
STYLE = {"h": ("Times-Bold", 16), "m": ("Times-Bold", 10.5), "n": ("Times-Roman", 10)}


def make_dotless_book(path, pages=PAGES):
    doc = pymupdf.open()
    for lines in pages:
        p = doc.new_page(width=420, height=640)
        p.insert_text((200, 620), str(len(doc)), fontsize=8, fontname="Times-Roman")
        y = 70
        for kind, text in lines:
            font, size = STYLE[kind]
            p.insert_text((40, y), text, fontsize=size, fontname=font)
            y += size + 9
    doc.save(path)
    return path


def _main(book, line):
    out, nid = [], line["root"]
    while True:
        kids = [c for c in book["nodes"][nid]["children"] if book["nodes"][c]["main"]]
        if not kids:
            return out
        nid = kids[0]
        out.append(nid)


def _variations(book, nid):
    """SAN sequences of the variations that branch off before node nid."""
    nodes = book["nodes"]
    parent = nodes[nid]["parent"]
    out = []
    for c in nodes[parent]["children"]:
        if nodes[c]["main"]:
            continue
        seq, k = [], c
        while True:
            seq.append(nodes[k]["san"])
            if not nodes[k]["children"]:
                break
            k = nodes[k]["children"][0]
        out.append(seq)
    return out


def test_dotless_book_end_to_end(tmp_path):
    pdf = make_dotless_book(tmp_path / "gpa_like.pdf")
    book = assemble.build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books")
    assert book["numbering"]["dotless"]
    games = [l for l in book["lines"] if l["start_fen"] == chess.STARTING_FEN]
    assert len(games) == 1 and games[0]["status"] == "ok"
    ids = _main(book, games[0])
    nodes = book["nodes"]
    assert [nodes[i]["san"] for i in ids] == [
        "e4", "c5", "Nc3", "Nc6", "f4", "g6", "Nf3", "Bg7", "Bc4", "e6", "f5", "Nge7", "fxe6",
        "fxe6", "d3", "d5", "Bb3", "b5", "O-O", "c4", "Ba4", "O-O"]
    by_ply = {k: i for k, i in enumerate(ids)}
    # 5 Bb5 instead of 5 Bc4; 5 ... d6 instead of 5 ... e6
    assert ["Bb5"] in _variations(book, by_ply[8])
    assert ["d6"] in _variations(book, by_ply[9])
    # "3 ... e6 transposes to 2 ... e6 3 f4 Nc6"
    assert ["e6"] in _variations(book, by_ply[5])
    assert ["e6", "f4", "Nc6"] in _variations(book, by_ply[3])
    assert ["dxe6"] in _variations(book, by_ply[13])
    # "Unfavourable for White is 9 exd5 in view of 9 ... exd5 10 Bb3 c4"; the
    # bracketed "10 ... Na5 11 Qe2" branches off inside it
    v = _variations(book, by_ply[16])
    assert ["exd5", "exd5", "Bb3", "c4"] in v
    assert ["Bb5", "d4", "Ne2", "Qb6"] in v          # "If 9 Bb5, then 9 ... d4 ..."
    exd5 = next(c for c in nodes[nodes[by_ply[16]]["parent"]]["children"]
                if nodes[c]["san"] == "exd5")
    bb3 = nodes[nodes[exd5]["children"][0]]["children"][0]
    assert [nodes[c]["san"] for c in nodes[bb3]["children"]] == ["c4", "Na5"]
    # prose numbers ("2 pawns", "3 open files", "page 12") made no runs
    assert not any("pawns" in u["text"] or "files" in u["text"] for u in book["unattached"])
    assert book["unattached"] == []


TABLE_PAGES = [
    [("h", "Chapter 1"),
     ("n", "A closed Ruy Lopez."),
     ("m", "1 e4 e5 2 Nf3 Nc6 3 Bb5 a6"),
     ("m", "4"), ("m", "Ba4"), ("n", "The usual retreat."),
     ("m", "4"), ("m", "Nf6"),
     ("m", "5"), ("m", "0-0"), ("n", "White castles."),
     ("m", "5"), ("m", "Be7"), ("n", "Also possible is 5 ... b5 6 Bb3 Bc5."),
     ("m", "6"), ("m", "Re1")],
]


def test_narrow_table_book(tmp_path):
    pdf = make_dotless_book(tmp_path / "table.pdf", TABLE_PAGES)
    book = assemble.build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books")
    line = next(l for l in book["lines"] if l["start_fen"] == chess.STARTING_FEN)
    ids = _main(book, line)
    assert [book["nodes"][i]["san"] for i in ids] == [
        "e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "Re1"]
    assert ["b5", "Bb3", "Bc5"] in _variations(book, ids[9])


HEADING_PAGES = [
    [("h", "Chapter 1"),
     ("n", "Ivanchuk - Kasparov, Linares 1991"),
     ("m", "1.e4 c5 2.Nf3 d6 3.Bb5+ Nd7 4.d4 Nf6"),
     ("h", "XIIIIIIIIY"),
     ("m", "5.O-O cxd4 6.Qxd4 a6"),
     ("n", "If 6...e5, then 7.Qd3 with a pleasant game."),
     ("m", "7.Bxd7+ Bxd7")],
]


def test_a_heading_inside_a_game_does_not_end_it(tmp_path):
    pdf = make_dotless_book(tmp_path / "heading.pdf", HEADING_PAGES)
    book = assemble.build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books")
    line = next(l for l in book["lines"] if l["start_fen"] == chess.STARTING_FEN)
    ids = _main(book, line)
    assert len(ids) == 14 and book["nodes"][ids[-1]]["san"] == "Bxd7"
    assert ["e5", "Qd3"] in _variations(book, ids[11])


# ---------------------------------------------------------------- the books themselves
def _book(name):
    path = CORPUS / f"{name}.pdf"
    if not path.exists():
        pytest.skip(f"{path} is not available")
    return path


def assemble_pages(pdf, first, last, passes=1):
    """Lines of pages first..last of a book, assembled as one chapter."""
    doc = pymupdf.open(pdf)
    fonts = pt.book_fonts(doc)
    stage1 = assemble.load_stage1(pdf, None, doc.page_count)
    diagrams = sel.expand_boards(stage1)
    structure = pt.book_structure(doc)
    chapters = assemble.book_chapters(structure, doc.page_count)
    selection = sel.Selection({}, None)
    numbering = assemble.book_numbering(doc)
    glyphs = GlyphModel()
    for _ in range(passes):
        dec = assemble._Decoder(glyphs, None)
        b = assemble._Builder(doc, fonts, chapters, diagrams, selection, dec, None,
                              numbering["dotless"])
        b.chapter(1, {"start": first, "end": last})
        glyphs = GlyphModel()
        for decs in dec.accepted:
            glyphs.learn_run(decs)
    return b, numbering


def _main_sans(b, L):
    return [b.nodes[n]["san"] for n in L.main_nodes[1:]]


def test_gpa_reads_its_first_game():
    b, numbering = assemble_pages(_book("gpa"), 15, 16)
    assert numbering["dotless"]
    L = b.lines[0]
    assert L.start_fen == chess.STARTING_FEN
    assert _main_sans(b, L)[:16] == [
        "e4", "c5", "Nc3", "Nc6", "f4", "g6", "Nf3", "Bg7", "Bc4", "e6", "f5", "Nge7",
        "fxe6", "fxe6", "d3", "d5"]


def test_planning_reads_its_narrow_table():
    b, numbering = assemble_pages(_book("planning"), 28, 33, passes=3)
    assert numbering["dotless"]
    L = next(L for L in b.lines if L.start_fen == chess.STARTING_FEN)
    got = _main_sans(b, L)
    # Grischuk - Kamsky: 10 a3! h6?! 11 Nc3 Re8 12 Nd5 Nxd5 13 Bxd5 Qc8 14 c3 Nd8 15 d4
    assert got[18:29] == ["a3", "h6", "Nc3", "Re8", "Nd5", "Nxd5", "Bxd5", "Qc8", "c3",
                          "Nd8", "d4"]


def test_kia_reads_dotless_numbers_glued_to_glyphs():
    b, numbering = assemble_pages(_book("kia"), 12, 41, passes=3)
    assert numbering["dotless"]
    # "1 e4 e6 2 d3 ds 3t'Dd2 tiJf6 4 g3 cs s .i.g2l'Dc6 6 tiJgf3" on page 20
    want = ["e4", "e6", "d3", "d5", "Nd2", "Nf6", "g3", "c5", "Bg2", "Nc6", "Ngf3"]
    got = [_main_sans(b, L)[:11] for L in b.lines if L.start_fen == chess.STARTING_FEN
           and b.nodes[L.main_nodes[1]]["page"] == 20]
    assert want in got


def test_ivanchuk_notes_become_variations():
    pdf = _book("ivanchuk")
    b, numbering = assemble_pages(pdf, 1, 4)
    assert not numbering["dotless"]
    L = b.lines[0]
    sans_ = _main_sans(b, L)
    assert sans_[:10] == ["e4", "c5", "Nf3", "d6", "Bb5+", "Nd7", "d4", "Nf6", "O-O", "cxd4"]
    assert len(sans_) == 75 and sans_[-1] == "Rxh4+"   # on past the diagrams to the end

    def var(ply):
        nid = L.main_nodes[ply + 1]
        out = []
        for c in b.nodes[b.nodes[nid]["parent"]]["children"]:
            if b.nodes[c]["main"]:
                continue
            seq, k = [], c
            while True:
                seq.append(b.nodes[k]["san"])
                if not b.nodes[k]["children"]:
                    break
                k = b.nodes[k]["children"][0]
            out.append(seq)
        return out

    # "Unfavourable for White is 5.e5 in view of 5...Qa5+ 6.Nc3 Ne4"
    assert ["e5", "Qa5+", "Nc3", "Ne4"] in var(8)
    # "If 5...Nxe4, then 6.Qe2 Nef6 7.dxc5 dxc5 8.Rd1"
    assert ["Nxe4", "Qe2", "Nf6", "dxc5", "dxc5", "Rd1"] in var(9)
    # "More often played are 3...Bd7 or 3...Nc6."
    assert ["Bd7"] in var(5) and ["Nc6"] in var(5)
    assert len(b.unattached) <= 6
