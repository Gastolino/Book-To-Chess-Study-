"""Tests for chessbook.figurines: piece figurines given as private codes.

A generated book prints its pieces in a font whose text layer gives each
piece as a private-use code (as ChessBase's "CB...Link" fonts do), built by
hand with a ToUnicode map so that no figurine font is needed. The book must
teach the program which code is which piece, and the letters must then reach
the text, the words and the decoded moves. The Alekhine book in the corpus
(typeset with ChessBase figurine fonts) checks a real book when present.
"""
import sys
from collections import Counter
from pathlib import Path

import chess
import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook import figurines, pdftext  # noqa: E402
from chessbook.assemble import build_book  # noqa: E402

ALEKHINE = Path("/home/user/Book-To-Chess-Study-/corpus/alekhine.pdf")

# The codes the generated font gives each piece (not ChessBase's, so that
# only learning can find them).
CODES = {"K": 0xE101, "Q": 0xE102, "R": 0xE103, "B": 0xE104, "N": 0xE105}

GAME = ("e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Nb8 d4 Nbd7 "
        "Nbd2 Bb7 Bc2 Re8 Nf1 Bf8 Ng3 g6 a4 c5 d5 c4 Bg5 h6 Be3 Nc5 Qd2 h5 Bg5 Be7 "
        "Kh2 Kg7 Rf1 Qc7 Rae1 Rh8 Qc1 Qd8 Kg1 Kg8 Qd2 Qc7 Kh1 Kh7").split()


def _game_lines(per_line=4):
    """The game as lines of (text, is figurine) segments, checked for legality."""
    b = chess.Board()
    words = []
    for i, san in enumerate(GAME):
        b.push_san(san)                         # raises on an illegal move
        num = f"{i // 2 + 1}." if i % 2 == 0 else ""
        if san[0] in CODES:
            words.append([(num, False), (san[0], True), (san[1:], False)])
        else:
            words.append([(num + san, False)])
    lines = []
    for k in range(0, len(words), per_line * 2):
        segs = []
        for w in words[k:k + per_line * 2]:
            segs += w + [(" ", False)]
        lines.append([s for s in segs if s[0]])
    return lines


def make_figurine_pdf(path, body_lines, font_name="CBTestLink", codes=CODES):
    """A one-chapter book. body_lines holds lists of (text, figurine) segments
    or plain strings; figurine segments are printed in a font whose
    ToUnicode map gives each piece letter as its private code."""
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=600)
    page.insert_text((40, 80), "Chapter 1", fontname="helv", fontsize=24)
    page.insert_text((40, 112), "An Open Game", fontname="helv", fontsize=18)
    page = doc.new_page(width=420, height=600)
    page.insert_text((10, 10), " ", fontname="helv", fontsize=10)    # makes /helv
    page.clean_contents()
    cmap = ("/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            "/CMapName /FigTest def /CMapType 2 def\n"
            "1 begincodespacerange <00> <FF> endcodespacerange\n"
            f"{len(codes)} beginbfchar\n"
            + "".join(f"<{ord(k):02X}> <{v:04X}>\n" for k, v in codes.items())
            + "endbfchar\nendcmap CMapName currentdict /CMap defineresource pop end end")
    tu = doc.get_new_xref()
    doc.update_object(tu, "<<>>")
    doc.update_stream(tu, cmap.encode())
    fx = doc.get_new_xref()
    doc.update_object(fx, f"<< /Type /Font /Subtype /Type1 /BaseFont /ABCDEF+{font_name} "
                          f"/Encoding /WinAnsiEncoding /ToUnicode {tu} 0 R >>")
    t, v = doc.xref_get_key(page.xref, "Resources/Font")
    if t == "xref":
        doc.xref_set_key(int(v.split()[0]), "FFig", f"{fx} 0 R")
    else:
        doc.xref_set_key(page.xref, "Resources/Font/FFig", f"{fx} 0 R")
    ops, y = [], 60
    for segs in body_lines:
        if isinstance(segs, str):
            segs = [(segs, False)]
        ops.append(f"BT 1 0 0 1 40 {600 - y} Tm")
        for text, fig in segs:
            esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"{'/FFig' if fig else '/helv'} 10 Tf ({esc}) Tj")
        ops.append("ET")
        y += 14
    cx = page.get_contents()[0]
    doc.update_stream(cx, doc.xref_stream(cx) + ("\n" + "\n".join(ops)).encode("latin-1"))
    doc.save(path)
    return path


PROSE = ["The opening of this game shows a slow manoeuvre that strong players like",
         "to use against the Spanish, and the notes explain the ideas behind it."]


# ------------------------------------------------------------------ units

def test_learn_map_takes_codes_that_stood_for_one_piece():
    cands = {("Fig", ""): 10, ("Fig", ""): 8, ("Fig", ""): 5,
             ("Fig", ""): 4}
    counts = {"": Counter({"N": 12}), "x": Counter({"N": 3}),
              "": Counter({"B": 6, "N": 3}),          # mixed evidence
              "": Counter({"R": 2}),                  # too little evidence
              "": Counter({"K": 5}), "S": Counter({"N": 40})}
    assert figurines.learn_map(cands, counts) == {("Fig", ""): "N", ("Fig", ""): "K"}


def test_known_convention_fills_codes_the_book_did_not_teach():
    cands = {("CBArialLink", ""): 5, ("CBArialLink", ""): 5, ("Other", ""): 5}
    full, learnt = figurines.book_map(cands, {"": Counter({"Q": 9})})
    assert learnt == {("CBArialLink", ""): "Q"}
    assert full == {("CBArialLink", ""): "Q", ("CBArialLink", ""): "N"}


def test_candidates_are_private_codes_before_squares(tmp_path):
    lines = _game_lines() + ["In German books 1.e4 e5 2.Sf3 Sc6 3.Lb5 is the same opening."]
    pdf = make_figurine_pdf(tmp_path / "c.pdf", PROSE + lines)
    doc = pymupdf.open(pdf)
    cands = figurines.candidates([pdftext._raw_page(doc, i) for i in range(doc.page_count)])
    chars = {ch for _, ch in cands}
    assert chars == {chr(CODES[p]) for p in "KQRBN"}
    assert all(font == "CBTestLink" for font, _ in cands)


# ------------------------------------------------------------------ a generated book

def test_generated_book_learns_its_figurines(tmp_path):
    pdf = make_figurine_pdf(tmp_path / "fig.pdf", PROSE + _game_lines())
    book = build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books")
    learnt = {f["code"]: f["piece"] for f in book["figurines"] if f["learnt"]}
    assert learnt == {f"U+{v:04X}": k for k, v in CODES.items()}
    st = book["stats"]
    assert st["moves"]["ok"] == len(GAME) and st["moves"]["failed"] == 0
    raws = [n["raw"] for n in book["nodes"].values() if n["raw"]]
    assert "Nf3" in raws and "Bb5" in raws and "Qd2" in raws and "Kh2" in raws
    assert not any(figurines.is_private(ch) for r in raws for ch in r)
    # the letters reach the line text and the word boxes of pdftext
    doc = pymupdf.open(pdf)
    pdftext.set_figurine_map(doc, {("CBTestLink", chr(v)): k for k, v in CODES.items()})
    lines = pdftext.page_lines(doc, 1)
    text = " ".join(ln["text"] for ln in lines)
    assert "2.Nf3 Nc6 3.Bb5" in text
    words = [w["text"] for ln in lines for w in ln["words"]]
    assert "2.Nf3" in words
    pdftext.set_figurine_map(doc, {})
    assert "2.f3" in " ".join(ln["text"] for ln in pdftext.page_lines(doc, 1))


# ------------------------------------------------------------------ the corpus

@pytest.mark.skipif(not ALEKHINE.exists(), reason="corpus/alekhine.pdf is not available")
def test_alekhine_figurines():
    doc = pymupdf.open(ALEKHINE)
    fonts = pdftext.book_fonts(doc)
    cands = figurines.candidates([pdftext._raw_page(doc, i) for i in range(doc.page_count)],
                                 {f["font"] for f in fonts["figurines"]})
    assert {ch for _, ch in cands} == {"", "", "", "", ""}
    full = figurines.known_map(cands)
    pdftext.set_figurine_map(doc, full)
    # PDF page 21, as printed: "Be6 8.f4 Nf6 9.Nd3" and "14.fxg6 Bxh2+! 15.Kf2"
    text = " ".join(ln["text"] for ln in pdftext.page_lines(doc, 20))
    assert "Be6 8.f4 f6 9.Nd3" in text
    assert "14.fxg6 Bxh2+! 15.Kf2 hxg6 16.Bxg6+" in text
    assert "c8 10.Nd3" in text
