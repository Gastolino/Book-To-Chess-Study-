"""Tests for chessbook.textdiagram: diagrams printed as text in a chess font.

Generated pages print positions in each supported character convention and
check that the position, its place on the page and the side to move are
read, that Stage 1 lists the diagram, that its lines are board furniture and
that the moves after it decode from it. The ChessBase export of
Ivanchuk-Kasparov (corpus/ivanchuk.pdf) checks a real book when present.
"""
import sys
from pathlib import Path

import chess
import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook import pdftext, textdiagram as td  # noqa: E402
from chessbook.assemble import build_book  # noqa: E402

CORPUS = Path("/home/user/Book-To-Chess-Study-/corpus")
IVANCHUK = CORPUS / "ivanchuk.pdf"

# The position after 15.b4 in Ivanchuk-Kasparov, Linares 1991, as the
# ChessBase export prints it.
IVANCHUK_P2 = ["XIIIIIIIIY", "8-+rwqk+-tr0", "7+p+lvlp+-0", "6p+-zppzp-+0", "5+-+-+-+-0",
               "4PzPPwQP+-zp0", "3+-sN-+N+P0", "2-+-+-zPP+0", "1tR-+-+R+K0", "xabcdefghy"]
IVANCHUK_P2_FEN = "2rqk2r/1p1bbp2/p2ppp2/8/PPPQP2p/2N2N1P/5PP1/R4R1K"


# ------------------------------------------------------------------ encoders for the tests

def _squares(fen):
    b = chess.Board(fen)
    for rank in range(7, -1, -1):
        row = []
        for f in range(8):
            p = b.piece_at(chess.square(f, rank))
            row.append((p.symbol() if p else "", (f + rank) % 2 == 0))
        yield rank + 1, row


def chessbase_lines(fen):
    out = ["XIIIIIIIIY"]
    for n, row in _squares(fen):
        s = ""
        for p, dark in row:
            if not p:
                s += "+" if dark else "-"
            else:
                letter = "L" if p.upper() == "B" else p.upper()
                letter = letter if p.isupper() else letter.lower()
                s += ("zsvtwm"["PNBRQK".index(p.upper())] if dark else "") + letter
        out.append(f"{n}{s}0")
    return out + ["xabcdefghy"]


def marroquin_lines(fen):
    white_l, white_d, black_l, black_d = "pnbrqk", "PNBRQK", "omvtwl", "OMVTWL"
    out = ["1222222223"]
    for _, row in _squares(fen):
        s = ""
        for p, dark in row:
            if not p:
                s += "+" if dark else " "
            else:
                i = "PNBRQK".index(p.upper())
                s += ((white_d if dark else white_l) if p.isupper()
                      else (black_d if dark else black_l))[i]
        out.append(f"4{s}5")
    return out + ["7888888889"]


def unicode_lines(fen):
    sym = dict(zip("KQRBNPkqrbnp", "♔♕♖♗♘♙♚♛♜♝♞♟"))
    return [" ".join(sym.get(p, "·") for p, _ in row) for _, row in _squares(fen)]


def _lines(texts, x=100, y=100, step=12):
    return [(t, (x, y + k * step, x + 7 * len(t), y + k * step + 10)) for k, t in enumerate(texts)]


# ------------------------------------------------------------------ decoding

def test_chessbase_ranks_decode_to_the_ivanchuk_position():
    found = td.find_text_diagrams(_lines(IVANCHUK_P2))
    assert len(found) == 1
    d = found[0]
    assert d.placement == IVANCHUK_P2_FEN
    assert d.encoding == "chessbase"
    assert d.lines == list(range(10))           # ranks and both frame lines
    assert not d.flipped


@pytest.mark.parametrize("encoder,name", [(chessbase_lines, "chessbase"),
                                          (marroquin_lines, "marroquin"),
                                          (unicode_lines, "unicode")])
@pytest.mark.parametrize("fen", [chess.STARTING_FEN, "r5k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 30",
                                 "8/8/4k3/8/2B5/8/4K3/8 w - - 0 1"])
def test_every_convention_round_trips(encoder, name, fen):
    found = td.find_text_diagrams(_lines(encoder(fen)))
    assert [d.placement for d in found] == [fen.split()[0]]
    assert found[0].encoding == name


def test_board_printed_from_blacks_side():
    # Black at the bottom: ranks 1 to 8 downwards, files h to a
    rows = []
    for n, row in reversed(list(_squares("r5k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"))):
        s = ""
        for p, dark in reversed(row):
            if not p:
                s += "+" if dark else "-"
            else:
                letter = p.upper() if p.isupper() else p.lower()
                s += ("zsvtwm"["PNBRQK".index(p.upper())] if dark else "") + letter
        rows.append(f"{n}{s}0")
    flipped = ["XIIIIIIIIY"] + rows + ["xhgfedcbay"]
    found = td.find_text_diagrams(_lines(flipped))
    assert len(found) == 1 and found[0].flipped
    assert found[0].placement == "r5k1/5ppp/8/8/8/8/5PPP/3R2K1"


def test_invalid_positions_and_prose_are_not_diagrams():
    two_kings = chessbase_lines("r5k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1")
    two_kings[3] = "6-+-+-mk-+0"                       # a second black king
    assert td.find_text_diagrams(_lines(two_kings)) == []
    prose = ["This is a line of ordinary prose about chess."] * 10
    assert td.find_text_diagrams(_lines(prose)) == []
    # seven ranks only
    assert td.find_text_diagrams(_lines(chessbase_lines(chess.STARTING_FEN)[:8])) == []


def test_side_to_move_from_the_text_around_the_diagram():
    pl = IVANCHUK_P2_FEN
    before = "While in this case the white king will be safer at h1. 12...h5 13.a4 h4 14.h3 Be7 15.b4"
    assert td.side_to_move(pl, before, "A committal decision. It was possible to continue 15.Nh2") \
        == (chess.BLACK, 15)
    assert td.side_to_move(pl, "", "15...a5 16.b5") == (chess.BLACK, 15)
    assert td.side_to_move(pl, "", "16.Nd2 Qc7") == (chess.WHITE, 16)
    assert td.side_to_move(pl, "15.b4 a5", "") == (chess.WHITE, 16)
    assert td.side_to_move(pl, "Black to move.", "") == (chess.BLACK, 1)
    # a king in check must move, whatever the text says
    check = "4k3/8/8/8/8/8/4R3/4K3"
    assert td.side_to_move(check, "White to play", "")[0] == chess.BLACK
    fen = td.full_fen(pl, before, "")
    assert fen == IVANCHUK_P2_FEN + " b k - 0 15"


# ------------------------------------------------------------------ a generated book

ENDING = "r5k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 30"


def make_book(path, encoder=chessbase_lines, flip_text=False):
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=600)
    page.insert_text((40, 80), "Chapter 1", fontname="tiro", fontsize=24)
    page.insert_text((40, 112), "Back Rank Mates", fontname="tiro", fontsize=18)
    page = doc.new_page(width=420, height=600)
    y = 60
    for t in ("A back rank weakness decides many games between beginners. The first",
              "example shows the idea in its simplest form, with White to move."):
        page.insert_text((40, y), t, fontname="tiro", fontsize=10)
        y += 13
    y += 8
    for t in encoder(ENDING):
        page.insert_text((140, y), t, fontname="cour", fontsize=13)
        y += 15
    y += 10
    page.insert_text((40, y), "30.Rd8+ Rxd8 31.Kf1 Rd2 32.Ke1 Rxf2", fontname="tibo", fontsize=10)
    y += 13
    for t in ("Black wins a second pawn and the ending is easy for him, because the",
              "black rook is far more active than the white king can ever hope to be."):
        page.insert_text((40, y), t, fontname="tiro", fontsize=10)
        y += 13
    doc.save(path)
    return path


@pytest.mark.parametrize("encoder", [chessbase_lines, marroquin_lines])
def test_generated_book_reads_its_text_diagram(tmp_path, encoder):
    pdf = make_book(tmp_path / "ending.pdf", encoder)
    book = build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books")
    diagrams = [d for p in book["pages"] for d in p["diagrams"]]
    assert len(diagrams) == 1
    d = diagrams[0]
    assert d["id"] == "p2-1" and d["kind"] == "board" and d["status"] == "read"
    assert d["fen"].split()[:2] == ENDING.split()[:2]
    lines = [L for L in book["lines"] if L["diagram"] == "p2-1"]
    assert len(lines) == 1 and lines[0]["status"] == "ok"
    assert lines[0]["start_fen"].split()[0] == ENDING.split()[0]
    assert book["stats"]["moves"]["ok"] == 6
    assert book["stats"]["waiting"] == 0
    # the ranks are board furniture, never moves or notes
    roles = {ln["text"]: ln["role"] for ln in pdftext.page_lines(pdf, 1)}
    for t in encoder(ENDING):
        if t.strip() in roles:
            assert roles[t.strip()] == "coord"


# ------------------------------------------------------------------ the corpus

@pytest.mark.skipif(not IVANCHUK.exists(), reason="corpus/ivanchuk.pdf is not available")
def test_ivanchuk_text_diagrams(tmp_path):
    book = build_book(IVANCHUK, output_dir=tmp_path / "output", books_dir=tmp_path / "books")
    diagrams = {d["id"]: d for p in book["pages"] for d in p["diagrams"]}
    assert sorted(diagrams) == ["p1-1", "p2-1", "p3-1", "p4-1", "p4-2", "p5-1"]
    # checked against the game's moves: after 8.Bg5, 15.b4 and 22...Qh6
    assert diagrams["p1-1"]["fen"] == "r2qkb1r/1p1bpppp/p2p1n2/6B1/3QP3/5N2/PPP2PPP/RN3RK1 b kq - 0 8"
    assert diagrams["p2-1"]["fen"] == IVANCHUK_P2_FEN + " b k - 0 15"
    assert diagrams["p3-1"]["fen"].startswith("2r1k1r1/3bbp2/1p1ppp1q/pP6/P1P1P2p/3Q3P/3NNPP1/5RRK w")
    st = book["stats"]
    assert st["moves"]["ok"] >= 130 and st["moves"]["failed"] == 0
    assert st["unattached"] <= 10
    lines = pdftext.page_lines(IVANCHUK, 1)
    ranks = [ln for ln in lines if ln["text"] in IVANCHUK_P2]
    assert len(ranks) == 10 and all(ln["role"] == "coord" and ln["diagram"] == "p2-1"
                                    for ln in ranks)
