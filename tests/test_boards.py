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


def draw_board(fen, hatched=False, flip=False, design="svg", border=6, halo=True):
    """A grey picture of the position: dark squares hatched or grey, white
    pieces filled with paper (as diagram fonts draw them), a frame round it.
    halo: a rim of paper round every piece; without it the square's colour
    shows wherever the drawing does not cover it (between a crown's points)."""
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
            if halo:
                filled = cv2.dilate(filled.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            cell = img[y:y + SQ, x:x + SQ]
            cell[filled] = 255
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


def test_white_queen_on_a_dark_square(tmp_path):
    """Tangborn and Brunthaler print pieces without a rim of paper: between
    the points of a white queen's crown on a dark square the square's grey
    shows, and the mask of the drawing encloses it. The grey is the square,
    not ink: the drawing is a white queen (it was read as a black knight,
    pawn or queen, without a doubt)."""
    fens, queens = [], []
    for k, fen in enumerate(positions(40, seed=7)):
        b = chess.Board(fen + " w - - 0 1")
        for s in list(b.pieces(chess.QUEEN, chess.WHITE)):
            b.remove_piece_at(s)
        dark = [s for s in chess.SQUARES if not b.piece_at(s) and 0 < chess.square_rank(s) < 7
                and (chess.square_file(s) + chess.square_rank(s)) % 2 == 0]
        queens.append(random.Random(k).choice(dark))
        b.set_piece_at(queens[-1], chess.Piece(chess.QUEEN, chess.WHITE))
        fens.append(b.board_fen())
    pdf = tmp_path / "queens.pdf"
    recs = make_pdf(pdf, fens, halo=False)
    res = boards.read_book_boards(pdf, recs)
    read = [chess.Board(res[f"p{k // 4 + 1}-{k % 4 + 1}"]["fen"]).piece_at(q) for k, q in enumerate(queens)]
    assert sum(p == chess.Piece(chess.QUEEN, chess.WHITE) for p in read) >= 38, read
    sq, whole = score(res, fens)
    assert sq >= 0.995 and whole >= 0.9, (sq, whole)


def test_one_drawing_is_one_group():
    """The first pass seeds a group with whichever drawing comes first: two
    drawings of one piece a little more than GROUP_DIST apart start two
    groups, and the drawings between them split between the two. Centres
    that end up closer than GROUP_DIST hold one drawing, and are one group
    (else the two halves are named apart, and one of them wrongly)."""
    rng = np.random.default_rng(1)
    base = rng.random(G2 := boards.G * boards.G).astype(np.float32)
    step = rng.standard_normal(G2).astype(np.float32)
    step /= np.sqrt((step ** 2).mean())             # RMS 1
    other = rng.random(G2).astype(np.float32)        # another piece, far away
    X = [base, base + 0.11 * step, other]
    X += [base + t * step for t in rng.uniform(0, 0.11, 40)]
    lab, C = boards.group_drawings(np.array(X, np.float32))
    assert len(set(lab[[0, 1]])) == 1 and lab[2] != lab[0] and len(C) == 2


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


def test_board_drawn_partly_as_glyphs_over_its_picture(tmp_path):
    """ClearScan (Brunthaler) keeps a scanned board as a picture and draws
    part of it, grey squares and pieces, as glyphs of a font over the
    picture, which then lacks them: p29's Day 91 picture holds neither its
    queens nor most grey squares, and 41 of the book's boards were skipped
    as partial. The board is what the page shows: the program reads the
    page there. Here the pictures lose their grey squares, which the page
    draws over them as grey glyphs of a font."""
    rng = random.Random(4)
    fens = []
    for fen in positions(12, seed=11):
        # the pieces stand on light squares only, so that the picture
        # without its grey squares still shows every piece
        b = chess.Board(fen + " w - - 0 1")
        light = lambda s: (chess.square_file(s) + chess.square_rank(s)) % 2 == 1
        others = [s for s in chess.SQUARES if b.piece_at(s) and b.piece_at(s).piece_type != chess.KING]
        for s in rng.sample(others, max(0, len(others) - 12)):
            b.remove_piece_at(s)            # a middlegame's pieces, not a full board
        for s in chess.SQUARES:
            if b.piece_at(s) and not light(s):
                p = b.remove_piece_at(s)
                free = [t for t in chess.SQUARES if light(t) and not b.piece_at(t)
                        and not (p.piece_type == chess.PAWN and chess.square_rank(t) in (0, 7))]
                b.set_piece_at(rng.choice(free), p)
        fens.append(b.board_fen())
    normal = positions(12, seed=12)
    doc = pymupdf.open()
    recs = []
    n = 8 * SQ + 12
    for k, fen in enumerate(normal + fens):
        if k % 4 == 0:
            page = doc.new_page(width=420, height=640)
        glyphs = k >= len(normal)
        img = draw_board(fen)
        if glyphs:
            img[img == 150] = 255           # the picture without its grey squares
        ok, png = cv2.imencode(".png", img)
        col, row = k % 2, (k % 4) // 2
        rect = pymupdf.Rect(30 + 190 * col, 40 + 290 * row, 30 + 190 * col + 170, 40 + 290 * row + 170)
        page.insert_image(rect, stream=png.tobytes())
        if glyphs:
            # ZapfDingbats "n" is a filled square 0.68 em wide
            s = SQ * rect.width / n
            fs = s / 0.66
            for r in range(8):
                for c in range(8):
                    if (r + c) % 2:
                        x = rect.x0 + (6 + c * SQ) * rect.width / n
                        y = rect.y0 + (6 + r * SQ) * rect.width / n
                        page.insert_text((x - 0.03 * fs - 0.2, y + s + 0.2), "n", fontname="zadb",
                                         fontsize=fs, color=(150 / 255,) * 3)
        recs.append({"page": doc.page_count, "rect": [round(v, 1) for v in rect],
                     "pixels": [img.shape[1], img.shape[0]]})
    pdf = tmp_path / "glyphs.pdf"
    doc.save(pdf)
    res = boards.read_book_boards(pdf, recs)
    ids = [f"p{k // 4 + 1}-{k % 4 + 1}" for k in range(len(recs))]
    over = {i: res[i] for i in ids[len(normal):]}
    assert all(r["status"] != "partial" for r in over.values()), [r["status"] for r in over.values()]
    sq, whole = score({f"p{k // 4 + 1}-{k % 4 + 1}": res[i] for k, i in enumerate(ids[len(normal):])}, fens)
    assert sq >= 0.99 and whole >= 0.8, (sq, whole)
    sq, whole = score(res, normal)
    assert sq >= 0.995 and whole >= 0.9, (sq, whole)


def test_wide_picture_of_a_whole_board_is_a_board(tmp_path):
    """ClearScan keeps a board with a white margin and its rank digits on the
    left as one picture wider than tall (The Art of Planning p32: 161.7 x
    119 pt). The 8 x 8 grid inside it is whole, so it is a board; a strip of
    three ranks and two boards side by side are not."""
    import stage1_inspect
    from chessbook import selection
    img = draw_board("r1qn1k2/2p2pp1/p2p3p/1p1P2b1/3P2N1/P6P/1P3PP1/R1B1Q1K1")
    wide = np.full((img.shape[0], img.shape[1] * 136 // 100), 255, np.uint8)
    wide[:, -img.shape[1]:] = img
    for k in range(8):
        cv2.putText(wide, str(8 - k), (wide.shape[1] - img.shape[1] - 30, 36 + SQ * k),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 2)
    pair = np.hstack([img, np.full((img.shape[0], 20), 255, np.uint8), img])
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=640)
    for k, (pic, w) in enumerate([(img, 120), (wide, 163), (img[:3 * SQ + 6], 120), (pair, 245)]):
        ok, png = cv2.imencode(".png", pic)
        page.insert_image(pymupdf.Rect(40, 20 + 150 * k, 40 + w, 20 + 150 * k + w * pic.shape[0]
                                       / pic.shape[1]), stream=png.tobytes())
    pdf = tmp_path / "wide.pdf"
    doc.save(pdf)
    _, diagrams, _, _ = stage1_inspect.inspect_page(pymupdf.open(pdf), 0)
    assert list(selection.picture_kinds(diagrams).values()) == [
        "board", "board_plus", "partial", "partial"]
    assert [d.get("whole") for d in diagrams] == [False, True, False, False]


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


def test_side_to_move_square_beside_the_board(tmp_path):
    """Brunthaler prints a small square above each board's right corner:
    filled for Black to move, empty for White, which OCR reads as "•" and
    "o". A letter there is no such square, and a board without one keeps
    the default."""
    fens = positions(4, seed=2)
    pdf = tmp_path / "markers.pdf"
    recs = make_pdf(pdf, fens)
    doc = pymupdf.open(pdf)
    page = doc[0]
    for rec, fill, text in ((recs[0], 0, "•"), (recs[1], None, "o"), (recs[2], None, "Do")):
        x1, y0 = rec["rect"][2], rec["rect"][1]
        if text == "Do":
            page.insert_text((x1 - 14, y0 - 6), text, fontsize=9)
        else:
            page.draw_rect(pymupdf.Rect(x1 - 10, y0 - 13, x1 - 2, y0 - 5), color=0, fill=fill, width=1)
            page.insert_text((x1 - 10, y0 - 5), text, fontsize=9, render_mode=3)
    pdf2 = tmp_path / "markers2.pdf"
    doc.save(pdf2)
    res = boards.read_book_boards(pdf2, recs)
    assert [res[f"p1-{k}"]["turn"] for k in (1, 2, 3, 4)] == ["b", "w", "w", "w"]
    assert [res[f"p1-{k}"]["turn_from"] for k in (1, 2, 3, 4)] == ["marker", "marker", "default", "default"]
    assert res["p1-1"]["fen"].split()[1] == "b"


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
