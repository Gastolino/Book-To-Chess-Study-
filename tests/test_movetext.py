"""Tests for chessbook.movetext: tokenizer, runs of moves, decoder, glyph model.

The OCR forms come from the Soviet Chess Primer (a ClearScan PDF), the first
book the project is tested on; the code itself knows no particular book.
"""
import sys
from pathlib import Path

import chess
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from chessbook.movetext import (  # noqa: E402
    LETTER_SETS, GlyphModel, clean_run, decode, decode_sequence, find_sequences,
    parse_move_text, tokenize,
)


def kinds(text):
    return [(t.kind, t.raw) for t in tokenize(text)]


def numbers(text):
    return [(t.raw, t.number, t.black) for t in tokenize(text) if t.kind == "number"]


def moves(text):
    return [t.raw for t in tokenize(text) if t.kind == "move"]


def sans(text, board=None, **kw):
    seqs = find_sequences(text)
    assert seqs, text
    return [d.san for d in decode(board or chess.Board(), seqs[0].tokens, **kw)]


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text, number", [
    ("lO.\x1bd3t", 10), ("IO.i.xflt!", 10), ("ll.g4t", 11), ("l.e4", 1), ("I.e4", 1),
    ("1o.\x1bh8#", 10), ("s.\x18xf7", 8), ("12.e4", 12),
])
def test_ocr_move_numbers(text, number):
    toks = tokenize(text)
    assert toks[0].kind == "number" and toks[0].number == number and not toks[0].black
    assert toks[1].kind == "move"


def test_split_digit_numbers():
    assert numbers("1 8.g6") == [("1 8.", 18, False)]
    assert numbers("1 1 .i.xf6t") == [("1 1 .", 11, False)]
    assert moves("1 1 .i.xf6t") == ["i.xf6t"]
    assert numbers("3 1 .Wfg6t") == [("3 1 .", 31, False)]


def test_split_digits_not_joined_against_the_numbering():
    # "5" is Black's move f5 with the file lost, not part of a number "52"
    toks = tokenize("I.d4 5 2 . .ig5 h6")
    assert [(t.kind, t.raw) for t in toks] == [
        ("number", "I."), ("move", "d4"), ("move", "5"), ("number", "2 ."),
        ("move", ".ig5"), ("move", "h6")]


@pytest.mark.parametrize("text", ["16...Wfxe5", "16 ... Wfxe5", "16 .. . Wfxe5", "16…Wfxe5"])
def test_black_continuations(text):
    toks = tokenize(text)
    assert toks[0].kind == "number" and toks[0].number == 16 and toks[0].black
    assert toks[1].kind == "move" and toks[1].raw == "Wfxe5" and toks[1].black


def test_black_continuation_with_space_before_move():
    toks = tokenize("8 ... axb5")
    assert (toks[0].number, toks[0].black) == (8, True)
    assert toks[1].raw == "axb5"


def test_bare_ellipsis_before_black_move():
    toks = tokenize("Black has ... d5 available")
    assert [(t.kind, t.raw) for t in toks] == [
        ("other", "Black"), ("other", "has"), ("number", "..."), ("move", "d5"),
        ("other", "available")]
    assert toks[2].number is None and toks[2].black and toks[3].black


def test_number_glued_to_previous_move():
    toks = tokenize("9.\x18xd4t10.®c3 \x1bxd4")
    assert [(t.kind, t.raw) for t in toks] == [
        ("number", "9."), ("move", "\x18xd4t"), ("number", "10."), ("move", "®c3"),
        ("move", "\x1bxd4")]


def test_glued_number_cut_leaves_a_whole_move():
    # "Ngt66." is "Ngt6" + "6.", not "Ngt" + "66."
    assert moves("5.Ng5 Ngt66.Bd3 e6") == ["Ng5", "Ngt6", "Bd3", "e6"]


def test_number_one_merged_with_rook_glyph():
    # "U:g6" is 1.Rg6: the "1." and the first stroke of the rook's "E:" became a "U"
    assert kinds("U:g6 i>hs 2.i>f6") == [("number", "U"), ("move", ":g6"), ("move", "i>hs"),
                                         ("number", "2."), ("move", "i>f6")]
    assert tokenize("U:a6t i>d7")[0].number == 1
    # an ordinary word, and a "U" in the middle of moves, are left alone
    assert kinds("Ulysses: the game")[0] == ("other", "Ulysses:")
    assert [k for k, _ in kinds("3.Kf2 U:g6")] == ["number", "move", "move"]


def test_number_glued_to_rook_glyph_starts_a_run():
    # "38J:k7!" is 38.Rc7!: the dot merged into the rook glyph, the c joined to
    # its stroke as a "k"
    assert kinds("38J:k7! gal")[:2] == [("number", "38"), ("move", "J:k7!")]
    assert sans("1.\x1dh7 Kd8 2.J:k7", chess.Board("4k3/8/8/8/8/8/8/4K2R w - - 0 1"),
                glyphs=GlyphModel(seed=True)) == ["Rh7", "Kd8", "Rc7"]
    # a "k" within a word is no file
    assert kinds("the bk7 and")[1] == ("other", "bk7")


def test_k_in_a_square_may_also_be_an_h():
    # OCR reads an h as a k as well as a c joined to the glyph before it: in
    # "1 ... .!k8" (Primer page 173) the king goes to h8, and "J:k7" may still be Rc7
    board = chess.Board("6k1/6pp/2r1q3/4B3/3pn3/1Q6/6PP/5RK1 b - - 0 1")
    assert sans("1...Kk8", board) == ["Kh8"]
    assert sans("1.Kk2", chess.Board("4k3/8/8/8/8/8/8/2K5 w - - 0 1")) == ["Kc2"]


def test_capital_c_before_a_rank_is_the_c_file():
    # OCR sets the c of a pawn move as a capital ("C4" for c4, "11 C3!"), and
    # a glyph before it keeps it a file ("èC7" for Qc7) ...
    assert sans("1.d4 d5 2.C4 e6 3.Nc3 C5") == ["d4", "d5", "c4", "e6", "Nc3", "c5"]
    b = chess.Board("k7/8/8/4Q3/8/8/8/4K3 w - - 0 1")
    assert sans("1.\x1bC7", b, glyphs=GlyphModel(seed=True)) == ["Qc7"]
    # ... but where C is the knight (French, Spanish), it stays a piece letter
    assert sans("1.e4 e5 2.C3", letters="French")[2].startswith("N")
    assert sans("1.e4 e5 2.Cc3", letters="Spanish")[2] == "Nc3"


def test_check_sign_printed_apart_from_its_move():
    # "'!Wfl t" is Qf1+ with the check sign set apart: the move is not lost
    assert moves("23. \x14d3 '!Wfl t 24. \x14c2 J.fl") == ["\x14d3", "'!Wfl t", "\x14c2", "J.fl"]
    # a word of prose before a "t" stays prose
    assert moves("2.Nf3 but t is") == ["Nf3"]


def test_two_moves_glued_after_a_one_character_glyph():
    assert moves("4.qa4ltlf6 5.0-0") == ["qa4", "ltlf6", "0-0"]
    assert moves("1.e4 e5 2.Nf3Nc6") == ["e4", "e5", "Nf3", "Nc6"]
    # in a text set in type, a square after a square is one move in long notation
    exact = [t.raw for t in tokenize("1.e2e4 e7e5 2.Ng1f3 Qd8h4+", exact=True) if t.kind == "move"]
    assert exact == ["e2e4", "e7e5", "Ng1f3", "Qd8h4+"]
    # in a text OCR read, it may be two moves whose space was lost: the
    # decoder reads it either way, as the board allows
    assert moves("1.e4e6 2.d4") == ["e4", "e6", "d4"]
    assert sans("1.e4e6 2.d4") == ["e4", "e6", "d4"]
    toks = tokenize("1.e2e4 e7e5 2.Ng1f3 Nb8c6")
    assert [d.san for d in decode(chess.Board(), toks)] == ["e4", None, "e5", None,
                                                            "Nf3", None, "Nc6", None]


def test_glyph_dot_after_number():
    # "3 . .ic4": the second dot belongs to the bishop glyph ".i"
    toks = tokenize("3 . .ic4 .ig4")
    assert (toks[0].raw, toks[0].black) == ("3 .", False)
    assert toks[1].raw == ".ic4"


def test_castling_promotion_annotations_checks():
    assert moves("5.0-0 O-O 6.0-0-0 o-o-o") == ["0-0", "O-O", "0-0-0", "o-o-o"]
    assert moves("1.e8=Q e1Q 2.a8\x1b") == ["e8=Q", "e1Q", "a8\x1b"]
    assert moves("1.e4!? e5?! 2.Qh5!! Nc6?? 3.Bc4 Nf6 4.Qxf7#") == [
        "e4!?", "e5?!", "Qh5!!", "Nc6??", "Bc4", "Nf6", "Qxf7#"]
    assert moves("12.Rxf7tt Kxf7 13.Qh5t") == ["Rxf7tt", "Kxf7", "Qh5t"]


def test_check_and_annotation_parsing():
    (p,) = [q for q in parse_move_text("Qa!+")]
    assert p["squares"] == ["a1"] and p["check"] == 1
    p = parse_move_text("\x18xd4t")[0]
    assert p["check"] == 1 and p["capture"] is True and "d4" in p["squares"]
    assert parse_move_text("Qxf7#")[0]["check"] == 3
    assert parse_move_text("e4!?")[0]["annotation"] == "!?"
    assert parse_move_text("0-0-0t") == [{"castle": "Q", "check": 1, "annotation": ""}]


def test_bang_read_as_1_after_a_square():
    # "c41?" is c4!? and "d3l" d3! with the "!" read as 1 or l, not a move to
    # the first rank ("Kh1", "Ne1") with "c4" read as junk
    b = chess.Board("r1bq1rk1/p2nbppp/4p3/1pppP3/8/3P1NP1/PPPN1PBP/R1BQR1K1 w - - 0 10")
    (d,) = decode(b, find_sequences("10.c41?")[0].tokens)
    assert (d.san, d.status, d.annotation) == ("c4", "ok", "!?")
    assert sans("1.e4 e5 2.Nf3 Nc6 3.d3l d6") == ["e4", "e5", "Nf3", "Nc6", "d3", "d6"]
    # ... also after a rank read as a letter ("hSI" for h5!)
    assert any("h5" in q["squares"] and q["annotation"] == "!" and q["prefix"] == ""
               for q in parse_move_text("hSI"))
    # a square followed by 1 is still the rank where nothing else reads
    assert "c1" in {s for q in parse_move_text("Rc1") for s in q["squares"]}


def test_check_sign_before_annotation_is_not_a_rank():
    # "t!" after a rank digit is a check and an annotation; "Nt!" is Nf1 ("t" = f, "!" = 1)
    p = parse_move_text("Vlxh5t!")
    assert all(q["check"] == 1 and q["annotation"] == "!" for q in p)
    assert "h5" in p[0]["squares"]
    assert parse_move_text("Nt!")[0]["squares"] == ["f1"]


def test_square_like_short_word_between_moves():
    (seq,) = find_sequences("14.d4 e5 15.Qf3 es 16.fxe5")
    assert [t.raw for t in seq.moves] == ["d4", "e5", "Qf3", "es", "fxe5"]
    seqs = find_sequences("A good answer to l .e4 is l ...e5. This")
    assert [(s.first_number, s.black_first, [t.raw for t in s.moves]) for s in seqs] == [
        (1, False, ["e4"]), (1, True, ["e5"])]


def test_english_words_are_not_moves():
    assert all(k == "other" for k, _ in kinds("a be Black and by a5 the pawn on e4"))
    # a lone "a5" is a move only within a numbered run
    assert kinds("3.e4 a5 4.d4")[2] == ("move", "a5")
    assert moves("17.g6! Black resigned, as 17 ... Wfxg6 would be met") == ["g6!", "Wfxg6"]
    assert moves("Vla5 \nmate. \n5.Vle2") == ["Vle2"]


def test_offsets_index_the_original_text():
    text = ("l.e4 e5 2.t!i)f3 \x1bf6? \nThe queen shouldn't be brought into play \n"
            "3.i.c4 \x1bg6 4.0-0 \x1bxe4? 5.i.xf7t '41e7 6.:Be1 \x1bf4 7.:Bxe5t! '4ixf7")
    for t in tokenize(text):
        assert text[t.start:t.end] == t.raw


def test_diagram_labels_do_not_break_a_run():
    text = "1.e4 e5 2.Nf3 \n5 \nNc6 3.Bb5"
    (seq,) = find_sequences(text)
    assert [t.raw for t in seq.moves] == ["e4", "e5", "Nf3", "Nc6", "Bb5"]


# ---------------------------------------------------------------------------
# Runs of moves
# ---------------------------------------------------------------------------
def test_note_run_starting_with_black():
    text = "Or 16 ... Wfxe5 17.Wfxe5 dxe5 1 8.g6 and mate is unstoppable."
    (seq,) = find_sequences(text)
    assert seq.first_number == 16 and seq.black_first and seq.depth == 0
    assert [(t.raw, t.number, t.black) for t in seq.moves] == [
        ("Wfxe5", 16, True), ("Wfxe5", 17, False), ("dxe5", 17, True), ("g6", 18, False)]


def test_parenthesised_sub_lines_have_depth():
    text = ("by 1 8.Wfc4t Wff7 (or 1 8 .. .1':!:£7; Black no longer has ... d5 available!) "
            "19.:B:h8#.")
    seqs = find_sequences(text)
    got = [(s.first_number, s.black_first, s.depth, [t.raw for t in s.moves]) for s in seqs]
    assert got == [
        (18, False, 0, ["Wfc4t", "Wff7"]),
        (18, True, 1, [".1':!:£7"]),
        (None, True, 1, ["d5"]),
        (19, False, 0, [":B:h8#"]),
    ]


def test_nested_parentheses():
    text = "12.Nf3 (12.Ne2 Nc6 (12...Nd7 13.f4) 13.d4) 12...Nc6 13.d4"
    got = [(s.first_number, s.black_first, s.depth) for s in find_sequences(text)]
    assert got == [(12, False, 0), (12, False, 1), (12, True, 2), (13, False, 1),
                   (12, True, 0)]


def test_run_side_settled_by_later_number():
    # "37.." could be either side; "3 8." two moves later shows it was White
    text = "37..1':!:d7 l:txd7 3 8.Axc4 bc4"
    (seq,) = find_sequences(text)
    assert (seq.first_number, seq.black_first, seq.side_known) == (37, False, True)
    assert [(t.number, t.black) for t in seq.moves] == [(37, False), (37, True), (38, False),
                                                       (38, True)]


def test_mate_ends_a_run():
    text = "6.i.xf7# \n5 \nI.e4 e5"
    seqs = find_sequences(text)
    assert [(s.first_number, [t.raw for t in s.moves]) for s in seqs] == [
        (6, ["i.xf7#"]), (1, ["e4", "e5"])]


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------
def test_decode_clean_english():
    text = "1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 5.O-O Be7 6.Re1 b5 7.Bb3 d6 8.c3 O-O"
    decs = decode(chess.Board(), find_sequences(text)[0].tokens)
    assert [d.san for d in decs] == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6",
                                     "O-O", "Be7", "Re1", "b5", "Bb3", "d6", "c3", "O-O"]
    assert all(d.status == "ok" for d in decs)
    assert decs[-1].fen == ("r1bq1rk1/2p1bppp/p1np1n2/1p2p3/4P3/1BP2N2/PP1P1PPP/RNBQR1K1 "
                            "w - - 1 9")


def test_decode_junk_glyphs():
    assert sans("1.e4 e5 2.ti)f3 ti)c6 3.i.b5 a6") == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]


PRIMER_LINE = "l.d4 g6 2.e4 Ag7 3.ti)f3 d6 4.ti)c3 \x18d7 5 . .ic4 ti)gf6?"
PRIMER_SANS = ["d4", "g6", "e4", "Bg7", "Nf3", "d6", "Nc3", "Nd7", "Bc4", "Ngf6"]


def test_decode_primer_line_with_seeded_glyphs():
    decs = decode(chess.Board(), find_sequences(PRIMER_LINE)[0].tokens,
                  glyphs=GlyphModel(seed=True))
    assert [d.san for d in decs] == PRIMER_SANS
    assert all(d.status == "ok" for d in decs)
    assert decs[-1].annotation == "?"


def test_decode_primer_line_without_any_glyph_knowledge():
    # The run itself settles the junk: "ti)gf6" needs two knights able to
    # reach f6, so "\x18d7" was a knight move, and "ti)" is a knight throughout.
    assert sans(PRIMER_LINE) == PRIMER_SANS


def test_decode_ocr_digits_and_squares():
    text = "1.e4 e5 2.ti)f3 ti)c6 3.i.c4 i.c5 4.0-0 ti)f6 5.J3el 0-0 6.c3 d6 7.h3 h6 8.d4 i.h6"
    assert sans(text, glyphs=GlyphModel(seed=True))[8] == "Re1"


def test_fl_ligature_reads_as_f2_when_the_moves_need_it():
    # OCR reads "f2" as the "fl" ligature: "i>fl" is Kf1 or Kf2, and the
    # following moves decide (here 3.Kf3 needs the king on f2)
    b = chess.Board("8/8/8/4k3/8/8/3Q4/4K3 w - - 0 1")
    text = "1.\x1bd7 <it>e4 2.i>fl i>e5 3.i>f3 <it>f6 4.i>f4"
    assert sans(text, b, glyphs=GlyphModel(seed=True)) == [
        "Qd7", "Ke4", "Kf2", "Ke5", "Kf3", "Kf6", "Kf4"]
    # an "l" of any other file is no 2: "el" is e1 or nothing
    assert all("e2" not in p["squares"] for p in parse_move_text("Rel"))
    assert any("f2" in p["squares"] for p in parse_move_text("Rfl"))
    # when both readings are legal and nothing decides, "fl" is f1
    b = chess.Board("4k3/8/8/8/8/8/8/4K2R w - - 0 1")
    assert sans("1.\x1dfl Kd7", b, glyphs=GlyphModel(seed=True)) == ["Rf1", "Kd7"]


def test_clearscan_square_forms():
    # ClearScan prints f3 as "o", "O" or "fJ", f1 as "n" and the rank 1
    # after a file as "t" (The Art of Planning: "2 lbo d5", "2 ttJO e6",
    # "2 tbfJ d6", "7 tbn d5", "Rfe1" as ":tfet"). The number before such a
    # move and the reply after it are moves of the run, and the move is
    # read as the square, not as an a-file ("tLlo" is no Na3).
    toks = tokenize("1 e4 e5 2 ttJO e6 3 d4 exd4", dotless=True)
    assert [(t.kind, t.raw) for t in toks][3:7] == [
        ("number", "2"), ("move", "ttJO"), ("move", "e6"), ("number", "3")]
    toks = tokenize("1 e4 e6 2 lbo d5 3 exd5 exd5", dotless=True)
    assert [(t.kind, t.raw) for t in toks][3:6] == [("number", "2"), ("move", "lbo"),
                                                    ("move", "d5")]
    decs = decode(chess.Board(), toks)
    assert [d.san for d in decs] == ["e4", "e6", "Nf3", "d5", "exd5", "exd5"]
    assert sans("1.e4 c5 2.tLlo d6 3.d4 cxd4 4.tLlxd4 tLlf6 5.tLlc3")[2] == "Nf3"
    assert sans("1.e4 c5 2.tbfJ d6 3.d4 cxd4 4.tbxd4")[2] == "Nf3"
    assert sans("1.tbn Kd7", chess.Board("4k3/8/8/8/8/8/3N4/4K3 w - - 0 1"))[0] == "Nf1"
    assert sans("1.:tfet Kh7", chess.Board("7k/8/8/8/8/8/8/R4RK1 w - - 0 1"))[0] == "Rfe1"
    # a "t" set apart from the square is the check sign ("i.d t" for Bc1+)
    from chessbook.movetext import _parse_raw
    assert not any(q.whole for q in _parse_raw("i.d t").parses)
    assert any(q.whole == "et" for q in _parse_raw(":tfet").parses)
    # prose is no move ("two", "in", "at", "OPEN"), nor are the forms in a book set
    # in type
    assert moves("I have two and win in two at last") == []
    toks = tokenize("12 OPEN 13 tLlo", dotless=True)
    assert [t.raw for t in toks if t.kind == "move"] == ["tLlo"]
    toks = tokenize("1.e4 e6 2.lbo d5")
    assert decode(chess.Board(), toks, glyphs=GlyphModel(exact=True))[2].san != "Nf3"


def test_castling_and_promotion():
    b = chess.Board("4k3/1P6/8/8/8/8/8/R3K2R w KQ - 0 1")
    assert sans("1.0-0-0 Kf7 2.b8=Q", b) == ["O-O-O", "Kf7", "b8=Q"]
    assert sans("1.O-O Kd7 2.b8\x18t", b, glyphs=GlyphModel(seed=True)) == [
        "O-O", "Kd7", "b8=N+"]
    assert sans("1.b8Q", b) == ["b8=Q+"]


def test_decode_note_starting_with_black():
    board = chess.Board()
    for m in ["e4", "e5", "Nf3", "Nc6"]:
        board.push_san(m)
    (seq,) = find_sequences("Or 2 ... d6 3.d4 i.g4 4.dxe5")
    assert seq.black_first and seq.first_number == 2
    board.pop()                     # the note replaces Black's second move
    assert [d.san for d in decode_sequence(board, seq, glyphs=GlyphModel(seed=True))] == [
        "d6", "d4", "Bg4", "dxe5"]


def test_national_letters():
    assert sans("1.e4 e5 2.Sf3 Sc6 3.Lb5 a6 4.La4 Sf6 5.0-0 Le7 6.Te1 b5",
                letters="German")[-6:] == ["Ba4", "Nf6", "O-O", "Be7", "Re1", "b5"]
    assert sans("1.e4 e5 2.Cf3 Cc6 3.Fb5 a6 4.De2", letters="French")[:5] == [
        "e4", "e5", "Nf3", "Nc6", "Bb5"]
    assert set(LETTER_SETS) >= {"English", "German", "French", "Spanish", "Dutch", "Russian"}


def test_figurines():
    assert sans("1.e4 e5 2.♘f3 ♞c6 3.♗b5") == ["e4", "e5", "Nf3", "Nc6", "Bb5"]


def test_unreadable_token_fails_and_the_run_goes_on():
    decs = decode(chess.Board(), find_sequences("1.e4 e5 2.ttla \x18c6 3.d4 exd4 4.\x18xd4")[0].tokens,
                  glyphs=GlyphModel(seed=True))
    assert [d.status for d in decs][2] == "failed"
    assert decs[2].san is None and decs[2].alternatives == ["Nf3"]
    assert [d.san for d in decs[3:]] == ["Nc6", "d4", "exd4", "Nxd4"]


def test_move_missing_from_the_text_is_bridged():
    # Black's second move is missing; the numbering shows it.
    (seq,) = find_sequences("1.e4 e5 2.Nf3 3.Bb5 a6 4.Ba4 Nf6")
    decs = decode(chess.Board(), seq.tokens)
    assert [d.san for d in decs] == ["e4", "e5", "Nf3", "Bb5", "a6", "Ba4", "Nf6"]
    assert decs[3].missing_before is not None and decs[2].missing_before is None


def _out_of_step(decs, board=None):
    """The moves read at another ply than their printed number names."""
    start = (board or chess.Board()).ply()
    out, ply = [], start
    for d in decs:
        if d.san:
            ply = chess.Board(d.fen).ply() - 1
            if ply != (d.number - 1) * 2 + d.black:
                out.append((d.number, d.black, d.raw, d.san, d.status))
    return out


def test_printed_numbers_anchor_the_moves():
    # Move 2 is lost from the text: 3.d4 stands at its printed ply, so it is
    # not read, rather than read as 2.d4 with 4.Nxd4 bent to 3.Qxd4, all ok.
    board = chess.Board()
    for san in ("e4", "c5"):
        board.push_san(san)
    toks = find_sequences("3.d4 cxd4 4.Nxd4 a6 5.Nc3 e6")[0].tokens
    for insert in (False, True):
        decs = decode(board, toks, insert=insert)
        assert _out_of_step(decs) == [] and decs[0].san is None, insert
    # Black's sixth move is lost ("6.Nb3 7.Qe2"): the moves after it are
    # never read a ply early, nor is d6, printed without a number, read as
    # Black's sixth; with insert the missing move is supplied.
    toks = find_sequences("1.e4 c5 2.Nf3 e6 3.d4 cxd4 4.Nxd4 a6 5.Bd3 Bc5 6.Nb3 7.Qe2 d6 "
                          "8.Be3 Nf6 9.Bxa7 Rxa7")[0].tokens
    decs = decode(chess.Board(), toks, insert=False)
    assert _out_of_step(decs) == []
    assert [d.san for d in decs[:11]] == ["e4", "c5", "Nf3", "e6", "d4", "cxd4", "Nxd4", "a6",
                                          "Bd3", "Bc5", "Nb3"]
    decs = decode(chess.Board(), toks)
    assert _out_of_step(decs) == [] and decs[11].missing_before is not None
    # a White move printed as such is not played as Black's ("3.Bd6" for 2...Bd5)
    board = chess.Board("7k/1b6/5N1P/8/8/6p1/8/B5K1 w - - 0 1")
    decs = decode(board, find_sequences("1.Be5 Bh1 2.Bxg3 3.Bd6")[0].tokens, insert=False)
    assert [d.san for d in decs[:3]] == ["Be5", "Bh1", "Bxg3"] and _out_of_step(decs) == []
    # a number misread by OCR names its move with its other readings ("S" for 8)
    board = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "Re1", "b5",
                "Bb3", "d6"):
        board.push_san(san)
    decs = decode(board, find_sequences("S. c3 O-O 9. h3")[0].tokens, insert=False)
    assert [(d.san, d.status) for d in decs] == [("c3", "ok"), ("O-O", "ok"), ("h3", "ok")]
    # a position that repeats stands at its own move number, not at the first's
    decs = decode(chess.Board(), find_sequences(
        "1.Nf3 Nf6 2.Ng1 Ng8 3.Nf3 Nf6 4.Ng1 Ng8 5.e4 e5")[0].tokens, insert=False)
    assert [d.status for d in decs] == ["ok"] * 10 and _out_of_step(decs) == []


def test_a_move_read_for_the_other_side_is_guessed():
    # A number printed without dots names no side for sure ("12 Qc7" in a
    # book that prints none): read as Black's move of that number, Qc7 is
    # 'guessed', never 'ok'.
    board = chess.Board()
    for san in ("e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6", "Be2", "e5",
                "Nb3", "Be7", "O-O", "O-O", "Be3", "Be6", "Qd2", "Nbd7", "a4", "Rc8", "f3"):
        board.push_san(san)
    (num, qc7) = tokenize("12 Qc7", dotless=True)
    assert not num.side_known and not qc7.black
    (d,) = decode(board, [num, qc7], insert=False)
    assert d.san == "Qc7" and d.status == "guessed"


def test_prose_word_after_a_move_ends_the_run():
    seqs = find_sequences("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 and 4.Ba4 Nf6")
    assert [(s.first_number, len(s.moves)) for s in seqs] == [(1, 6), (4, 2)]


def test_ambiguous_and_guessed_statuses():
    # Two knights can reach d2 and the text does not say which.
    board = chess.Board("4k3/8/8/8/8/5N2/8/1N2K3 w - - 0 1")
    (d,) = decode(board, tokenize("1.Nd2"))
    assert d.status == "ambiguous" and d.san in ("Nbd2", "Nfd2")
    # "c3" with the knight glyph lost: the pawn reading fits, but the next
    # move needs a knight on c3.
    text = "1.e4 e5 2.c3 Nc6 3.Nd5"
    decs = decode(chess.Board(), find_sequences(text)[0].tokens)
    assert [d.san for d in decs] == ["e4", "e5", "Nc3", "Nc6", "Nd5"]
    assert decs[2].status == "guessed" and "c3" in decs[2].alternatives


def test_exact_text_reads_each_letter_as_printed():
    # OCR reads an e for a c, a 6 for a 5, a lost glyph for a pawn: in an
    # OCR'd book "3.Be4", where only a bishop to c4 can go, is Bc4. A book
    # whose text layer holds the letters it was set in (GlyphModel(exact=
    # True)) prints what it means: no legal move is "Be4" there.
    toks = find_sequences("1.e4 e5 2.Nf3 Nc6 3.Be4 Nf6")[0].tokens
    lenient = decode(chess.Board(), toks)
    assert (lenient[4].san, lenient[4].status) == ("Bc4", "ok")
    exact = decode(chess.Board(), toks, glyphs=GlyphModel(exact=True))
    assert exact[4].status == "failed" and exact[4].san is None
    assert [d.san for d in exact[:4]] == ["e4", "e5", "Nf3", "Nc6"] and exact[5].san == "Nf6"
    # a piece letter is that piece, and a move without one a pawn's
    assert decode(chess.Board(), tokenize("1.Bf3"))[0].san in ("Nf3", None)
    assert decode(chess.Board(), tokenize("1.Bf3"), glyphs=GlyphModel(exact=True))[0].status \
        == "failed"
    board = chess.Board("4k3/8/8/8/8/8/8/1N2K3 w - - 0 1")
    assert decode(board, tokenize("1.c3"))[0].san == "Nc3"
    assert decode(board, tokenize("1.c3"), glyphs=GlyphModel(exact=True))[0].status == "failed"
    # nor is "Nx" the junk of a figurine (no knight takes on e3 here)
    board = chess.Board("r2qr1k1/ppp2ppp/1nnp1b2/8/2PP2b1/PPNBB3/4NPPP/R2Q1RK1 b - - 0 12")
    assert decode(board, tokenize("12...Nxe3"))[0].san in ("Nc8", "Rxe3")
    assert decode(board, tokenize("12...Nxe3"), glyphs=GlyphModel(exact=True))[0].status \
        == "failed"
    board = chess.Board("5rn1/1p2qp1k/4pbpp/p2pP3/P1r2BNP/P5P1/3Q1PB1/1R2R1K1 w - - 0 28")
    learnt = GlyphModel(exact=True)
    learnt.learn([("bx", "Q")] * 3)          # (as junk read in a run would teach it)
    assert decode(board, tokenize("28.bxa5"), glyphs=learnt)[0].status == "failed"
    # the printed letters still read as they are
    text = "1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 5.O-O Be7 6.Re1 b5 7.Bb3 d6 8.c3 O-O 9.h3 Nb8"
    decs = decode(chess.Board(), find_sequences(text)[0].tokens, glyphs=GlyphModel(exact=True))
    assert all(d.status == "ok" for d in decs) and decs[-1].san == "Nb8"
    # a word that only OCR's misreadings make a move of ends the run
    text = "14.Qxc8+ Rxc8 15.b3 Rd8 White's d4 point is weak. 8.c3 Nd5 Hi, I'm back"
    assert [[m.raw for m in s.moves] for s in find_sequences(text, exact=True)] == [
        ["Qxc8+", "Rxc8", "b3", "Rd8"], ["c3", "Nd5"]]
    assert "White's" in [m.raw for m in find_sequences(text)[0].moves]


def test_decoded_offsets_and_numbers():
    text = "Or 16 ... Wfxe5 17.Wfxe5 dxe5"
    seq = find_sequences(text)[0]
    board = chess.Board("r4rk1/ppp2ppp/3p4/4q3/8/8/PPP1QPPP/R4RK1 b - - 0 16")
    for d in decode(board, seq.tokens, glyphs=GlyphModel(seed=True)):
        assert text[d.start:d.end] == d.raw
    assert [(d.number, d.black) for d in decode(board, seq.tokens)] == [
        (16, True), (17, False), (17, True)]


# ---------------------------------------------------------------------------
# Glyph model
# ---------------------------------------------------------------------------
def test_glyph_model_learns_and_backs_off():
    g = GlyphModel()
    assert abs(g.prior("ti)")["N"] - g.prior("ti)")["Q"]) < 1e-9
    g.learn([("ti)", "N")] * 8 + [("tLl", "N")] * 5 + [("YlY", "Q")] * 6 + [(".i", "B")] * 7)
    assert max(g.prior("ti)").items(), key=lambda kv: kv[1])[0] == "N"
    # an unseen variant made of the same characters leans the same way
    assert max(g.prior("t!i)").items(), key=lambda kv: kv[1])[0] == "N"
    assert max(g.prior("YY").items(), key=lambda kv: kv[1])[0] == "Q"


def test_two_pass_learning_from_decoded_runs():
    text = ("1.e4 e5 2.ti)f3 ti)c6 3.i.b5 a6 4.i.a4 ti)f6 5.0-0 i.e7 6.J3e1 b5 7.i.b3 d6 "
            "8.c3 0-0 9.h3 ti)b8 10.d4 ti)bd7")
    g = GlyphModel()
    decs = decode(chess.Board(), find_sequences(text)[0].tokens, glyphs=g)
    assert clean_run(decs)
    assert g.learn_run(decs) > 0
    assert max(g.prior("ti)").items(), key=lambda kv: kv[1])[0] == "N"
    assert max(g.prior("i.").items(), key=lambda kv: kv[1])[0] == "B"


def test_square_habits_are_learnt():
    g = GlyphModel()
    g.learn_squares([(None, "5", chess.F5)] * 8 + [(None, "5", chess.D5)])
    assert g.file_costs(None)[5] < g.file_costs(None)[3]


# ---------------------------------------------------------------------------
# Bench smoke test
# ---------------------------------------------------------------------------
def test_bench_smoke(tmp_path):
    import corrupt_bench
    known, dropped = corrupt_bench.load_known()
    assert len(known) >= 25 and not dropped
    out = tmp_path / "bench.txt"
    results = corrupt_bench.bench(20, out, quiet=True, notations=("english", "junk"),
                                  levels=("medium",))
    assert out.exists() and "per-move" in out.read_text()
    for notation in ("english", "junk"):
        st2 = results[(notation, "medium")][2]
        assert st2["games"] == 20
        assert st2["correct"] / st2["moves"] >= 0.97
