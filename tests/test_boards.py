"""Board reading (Stage 3): synthetic boards drawn from known positions, and
regression tests on the corpus books when they are present.

The corpus tests look for the books in the project folder (primer.pdf and
corpus/*.pdf) or in the folder named by the CHESSBOOK_BOOKS environment
variable, and skip when a book is missing. Their expected positions are in
tests/data/board_truth.json, checked by eye against the pictures.
"""
import json
import os
import random
import sys
import time
from pathlib import Path

import chess
import chess.pgn
import cv2
import numpy as np
import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chessbook import boards  # noqa: E402
from chessbook.assemble import build_book  # noqa: E402

DATA = ROOT / "tests" / "data"
SQ = 40


# ------------------------------------------------------------------ drawing boards

def _pieces(design="svg"):
    z = np.load(boards.ASSETS / "pieces.npz")
    k = [str(x) for x in z["designs"]].index(design)
    return {str(sym): z["pieces"][k][i] for i, sym in enumerate(z["order"])}


def draw_board(fen, hatched=False, flip=False, design="svg", border=6):
    """A grey picture of the position: dark squares hatched or grey, white
    pieces filled with paper (as diagram fonts draw them), a frame round it."""
    pieces = _pieces(design)
    n = 8 * SQ + 2 * border
    img = np.full((n, n), 255, np.uint8)
    cv2.rectangle(img, (1, 1), (n - 2, n - 2), 0, 2)
    board = chess.Board(fen)
    for r in range(8):
        for c in range(8):
            y, x = border + r * SQ, border + c * SQ
            if (r + c) % 2:
                if hatched:
                    cell = np.full((SQ, SQ), 255, np.uint8)
                    for k in range(-SQ, 2 * SQ, 5):
                        cv2.line(cell, (k, SQ), (k + SQ, 0), 0, 1)
                    img[y:y + SQ, x:x + SQ] = cell
                else:
                    img[y:y + SQ, x:x + SQ] = 150
            sq = chess.square(7 - c, r) if flip else chess.square(c, 7 - r)
            p = board.piece_at(sq)
            if p is None:
                continue
            glyph = cv2.resize(pieces[p.symbol()], (SQ, SQ), interpolation=cv2.INTER_AREA)
            ink = glyph < 128
            filled = boards._fill(ink)
            halo = cv2.dilate(filled.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            cell = img[y:y + SQ, x:x + SQ]
            cell[halo] = 255
            cell[ink] = 0
    return img


def positions(n, seed=1):
    """n positions from the known games, at plies spread over each game."""
    rng = random.Random(seed)
    out = []
    with open(DATA / "known_games.pgn", encoding="utf-8") as fh:
        games = []
        while True:
            g = chess.pgn.read_game(fh)
            if g is None:
                break
            games.append(list(g.mainline_moves()))
    while len(out) < n:
        moves = rng.choice(games)
        b = chess.Board()
        for mv in moves[:rng.randrange(0, len(moves) + 1)]:
            b.push(mv)
        out.append(b.board_fen())
    return out


def make_pdf(path, fens, **kw):
    """A PDF with one board picture per position, four to a page, and the
    Stage 1 records of the pictures."""
    doc = pymupdf.open()
    recs = []
    for k, fen in enumerate(fens):
        if k % 4 == 0:
            page = doc.new_page(width=420, height=640)
        img = draw_board(fen, **kw)
        ok, png = cv2.imencode(".png", img)
        col, row = k % 2, (k % 4) // 2
        rect = pymupdf.Rect(30 + 190 * col, 40 + 290 * row, 30 + 190 * col + 170, 40 + 290 * row + 170)
        page.insert_image(rect, stream=png.tobytes())
        recs.append({"page": doc.page_count, "rect": [round(v, 1) for v in rect],
                     "pixels": [img.shape[1], img.shape[0]]})
    doc.save(path)
    return recs


def score(results, fens, flip=False):
    good = total = boards_ok = 0
    for k, fen in enumerate(fens):
        want = chess.Board(fen + " w - - 0 1")
        got_fen = results[f"p{k // 4 + 1}-{k % 4 + 1}"]["fen"]
        got = chess.Board(got_fen) if got_fen else chess.Board(None)
        bad = sum(want.piece_at(s) != got.piece_at(s) for s in chess.SQUARES)
        good += 64 - bad
        total += 64
        boards_ok += bad == 0
    return good / total, boards_ok / len(fens)


# ------------------------------------------------------------------ synthetic tests

@pytest.mark.parametrize("hatched", [False, True])
def test_synthetic_boards_read(tmp_path, hatched):
    fens = positions(40)
    pdf = tmp_path / "synthetic.pdf"
    recs = make_pdf(pdf, fens, hatched=hatched)
    res = boards.read_book_boards(pdf, recs)
    sq, whole = score(res, fens)
    assert sq >= 0.995 and whole >= 0.9, (sq, whole)
    first = res["p1-1"]
    assert set(first) >= {"fen", "confidence", "doubtful", "status"}
    assert first["status"] in ("read", "doubtful")


def test_board_seen_from_black_side(tmp_path):
    fens = positions(24, seed=3)
    pdf = tmp_path / "flipped.pdf"
    recs = make_pdf(pdf, fens, flip=True)
    res = boards.read_book_boards(pdf, recs)
    flipped = [res[f"p{k // 4 + 1}-{k % 4 + 1}"]["flipped"] for k in range(len(fens))]
    assert sum(flipped) >= 0.8 * len(fens)
    sq, _ = score(res, fens)
    assert sq >= 0.98


def test_initial_position_teaches_the_pieces(tmp_path):
    fens = [chess.STARTING_BOARD_FEN] + positions(11, seed=5)
    pdf = tmp_path / "start.pdf"
    recs = make_pdf(pdf, fens)
    res = boards.read_book_boards(pdf, recs)
    assert res["p1-1"]["fen"].split()[0] == chess.STARTING_BOARD_FEN
    assert res["p1-1"]["fen"].split()[2] == "KQkq"


def test_partial_picture_is_skipped(tmp_path):
    img = draw_board(chess.STARTING_BOARD_FEN)[:3 * SQ + 6]     # three ranks only
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=640)
    ok, png = cv2.imencode(".png", img)
    rect = pymupdf.Rect(40, 40, 240, 40 + 200 * img.shape[0] / img.shape[1])
    page.insert_image(rect, stream=png.tobytes())
    pdf = tmp_path / "part.pdf"
    doc.save(pdf)
    rec = {"page": 1, "rect": list(rect), "pixels": [img.shape[1], img.shape[0]]}
    res = boards.read_book_boards(pdf, [rec])
    assert res["p1-1"]["status"] == "partial" and res["p1-1"]["fen"] is None


def test_grid_located_inside_a_margin():
    img = draw_board("8/8/8/4k3/8/8/4K3/8")
    big = np.full((img.shape[0] + 90, img.shape[1] + 30), 255, np.uint8)
    big[60:60 + img.shape[0], 10:10 + img.shape[1]] = img
    cv2.putText(big, "Diagram 7", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    x0, y0, s, score_ = boards.locate_grid(big)
    assert abs(s - SQ) < 1.0 and abs(x0 - 16) < 2 and abs(y0 - 66) < 2


def test_caption_turn_and_printed_coordinates():
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=640)
    rect = pymupdf.Rect(100, 100, 260, 260)
    for k, f in enumerate("hgfedcba"):            # files printed h..a: Black's side
        page.insert_text((rect.x0 + 8 + 20 * k, rect.y1 + 10), f, fontsize=8)
    for k, r in enumerate("12345678"):
        page.insert_text((rect.x0 - 9, rect.y0 + 13 + 20 * k), r, fontsize=8)
    page.insert_text((150, 285), "Diagram 12 (B)", fontsize=9)
    words, lines = boards.page_words(page)
    assert boards.printed_orientation(words, rect) is True
    assert boards.caption_turn(lines, rect) == "b"
    page2 = doc.new_page(width=420, height=640)
    page2.insert_text((120, 90), "White to play and win", fontsize=9)
    words, lines = boards.page_words(page2)
    assert boards.caption_turn(lines, rect) == "w"
    assert boards.printed_orientation(words, rect) is None


def test_build_book_reads_the_boards(tmp_path):
    """The assembly reads the boards itself when no FENs are given, and a
    line that starts from a diagram is decoded instead of waiting."""
    from test_assemble import make_book, line_titled
    pdf = make_book(tmp_path / "little.pdf")
    book = build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books")
    d = book["pages"][4]["diagrams"][0]
    # the little book's board is a bare checkerboard: a position without
    # kings, which no line can start from
    assert d["fen"] is None and d["status"] == "unread"
    w = line_titled(book, "Diagram 12")
    assert w["status"] == "waiting"


# ------------------------------------------------------------------ the corpus

def _book(name):
    folders = [ROOT, ROOT / "corpus"]
    if os.environ.get("CHESSBOOK_BOOKS"):
        folders = [Path(os.environ["CHESSBOOK_BOOKS"]), Path(os.environ["CHESSBOOK_BOOKS"]) / "corpus"] + folders
    for f in folders:
        if (f / f"{name}.pdf").exists():
            return f / f"{name}.pdf"
    return None


TRUTH = json.loads((DATA / "board_truth.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus_reading(tmp_path_factory):
    import stage1_inspect
    cache = {}

    def read(name):
        if name not in cache:
            pdf = _book(name)
            if pdf is None:
                pytest.skip(f"{name}.pdf is not available")
            out = tmp_path_factory.mktemp(name)
            stage1_inspect.analyse(pdf, out)
            diagrams = json.loads((out / "diagrams.json").read_text(encoding="utf-8"))
            t = time.perf_counter()
            res = boards.read_book_boards(pdf, diagrams)
            cache[name] = (res, time.perf_counter() - t, diagrams)
        return cache[name]
    return read


@pytest.mark.parametrize("name", sorted(TRUTH))
def test_corpus_ground_truth(corpus_reading, name):
    res, seconds, _ = corpus_reading(name)
    good = total = whole = 0
    unflagged = []
    for did, fen in TRUTH[name].items():
        want = chess.Board(fen + " w - - 0 1")
        got = chess.Board(res[did]["fen"]) if res[did]["fen"] else chess.Board(None)
        bad = [chess.square_name(s) for s in chess.SQUARES if want.piece_at(s) != got.piece_at(s)]
        good += 64 - len(bad)
        total += 64
        whole += not bad
        unflagged += [(did, s) for s in bad if s not in res[did]["doubtful"]]
    # measured when the test was written: no error in the Primer, gpa and
    # alekhine samples, one square in kia's and seven in planning's (white
    # pieces on densely hatched squares of small pictures), all of them
    # among the squares reported as doubtful
    assert good / total >= 0.99, (name, good / total)
    assert whole >= 0.7 * len(TRUTH[name]), (name, whole)
    assert len(unflagged) <= 1, unflagged


def test_primer_speed_and_partial_boards(corpus_reading):
    res, seconds, diagrams = corpus_reading("primer")
    assert seconds < 120
    statuses = [r["status"] for r in res.values()]
    assert statuses.count("partial") >= 50
    assert statuses.count("read") >= 500
