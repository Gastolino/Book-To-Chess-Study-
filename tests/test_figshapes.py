"""Tests for chessbook.figshapes: piece figurines read by their shape.

The synthetic books print their figurines as pictures (drawn from the
DejaVu Sans chess symbols) under a text layer that gives every piece the
same junk character, as a scanned book's text recognition might: the text
alone cannot tell the pieces apart, the pictures can. The corpus tests use
tests/data/figurine_truth.json, checked by eye, and skip when a book is
missing.
"""
import io
import json
import os
import sys
from pathlib import Path

import chess
import chess.pgn
import numpy as np
import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "data"
sys.path.insert(0, str(ROOT))

from chessbook import figshapes  # noqa: E402
from chessbook.assemble import build_book  # noqa: E402
from chessbook.movetext import Token, decode, letter_symbol, symbol_span, tokenize  # noqa: E402

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SYMBOLS = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘"}
JUNK = "W"


def figurine_pixmaps(size=10):
    """{piece letter: grey pixmap of its DejaVu figurine}, about 300 dpi."""
    out = {}
    for p, ch in SYMBOLS.items():
        doc = pymupdf.open()
        page = doc.new_page(width=size * 1.2, height=size * 1.3)
        page.insert_font(fontname="dv", fontfile=FONT)
        page.insert_text((0.05 * size, 1.05 * size), ch, fontname="dv", fontsize=size)
        pix = page.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
        g = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.stride)[:, :pix.w]
        ys, xs = np.nonzero(g < 128)
        g = np.ascontiguousarray(g[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
        out[p] = pymupdf.Pixmap(pymupdf.csGRAY, g.shape[1], g.shape[0], g.tobytes(), 0)
    return out


def write_moves(page, x, y, line, pics, size=10):
    """Write a line of moves whose piece letters are pictures of figurines
    covering the junk character the text layer holds."""
    text = "".join(JUNK if ch in SYMBOLS else ch for ch in line)
    page.insert_text((x, y), text, fontname="helv", fontsize=size)
    for k, ch in enumerate(line):
        if ch in SYMBOLS:
            x0 = x + pymupdf.get_text_length(text[:k], fontname="helv", fontsize=size)
            w = pymupdf.get_text_length(JUNK, fontname="helv", fontsize=size)
            r = pymupdf.Rect(x0, y - 0.85 * size, x0 + w, y + 0.2 * size)
            page.draw_rect(r, color=None, fill=(1, 1, 1))
            page.insert_image(r, pixmap=pics[ch], keep_proportion=True)


def game_lines(n_games=6, per_line=6):
    games = []
    with open(DATA / "known_games.pgn", encoding="utf-8") as f:
        while len(games) < n_games:
            g = chess.pgn.read_game(f)
            if g is None:
                break
            games.append(g)
    out = []
    for g in games:
        b = g.board()
        parts = []
        for k, m in enumerate(g.mainline_moves()):
            san = b.san(m)
            parts.append((f"{b.fullmove_number}." if b.turn == chess.WHITE else "") + san)
            b.push(m)
        out.append([" ".join(parts[i:i + per_line]) for i in range(0, len(parts), per_line)])
    return out


def make_figurine_book(path):
    pics = figurine_pixmaps()
    doc = pymupdf.open()
    for k, lines in enumerate(game_lines()):
        page = doc.new_page(width=420, height=600)
        page.insert_text((40, 50), f"Game {k + 1}", fontname="helv", fontsize=14)
        page.insert_text((40, 75), "The moves of the game were these:", fontname="helv", fontsize=10)
        y = 100
        for line in lines:
            write_moves(page, 40, y, line, pics)
            y += 16
    doc.save(path)
    return path


# ------------------------------------------------------------------ helpers

def test_symbol_span_and_letters():
    assert symbol_span("\x14e4", "\x14") == (0, 1)
    assert symbol_span("'it> e4", "'it>") == (0, 4)
    assert symbol_span("i. xe4", "i.") == (0, 2)
    assert symbol_span("abc", "x") is None
    letters = {"K": 6, "Q": 5, "R": 4, "B": 3, "N": 2}
    assert letter_symbol("Ra", letters) and letter_symbol("N6", letters)
    assert not letter_symbol("tLl", letters) and not letter_symbol("Rx!", letters)


def test_certain_piece():
    # a king on e1 and a queen on d1 both reach d2; only the knight reaches h3
    fen = "4k3/8/8/8/8/8/8/3QK1N1 w - - 0 1"
    assert figshapes.certain_piece(fen, "e1d2") is None
    assert figshapes.certain_piece(fen, "g1h3") == "N"
    assert figshapes.certain_piece(fen, "d1a4") == "Q"


# ------------------------------------------------------------------ decoding

def _move(raw, shape=None):
    return Token("move", raw, 0, len(raw), number=1, black=False, shape=shape)


def test_shape_chooses_the_piece():
    board = chess.Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    plain = decode(board, [_move("Wd2")])[0]
    assert plain.status != "ok"
    king = decode(board, [_move("Wd2", ("K", 0.95))])[0]
    assert (king.san, king.status) == ("Kd2", "ok")
    queen = decode(board, [_move("Wd2", ("Q", 0.95))])[0]
    assert (queen.san, queen.status) == ("Qd2", "ok")


def test_legal_play_overrules_a_wrong_shape():
    # the shape says knight, but no knight can reach d2: the move still reads
    board = chess.Board("4k3/8/8/8/8/8/8/3Q1K2 w - - 0 1")
    d = decode(board, [_move("Wd2", ("N", 0.95))])[0]
    assert d.san == "Qd2"


# ------------------------------------------------------------------ cutting and naming

@pytest.fixture(scope="module")
def figurine_book(tmp_path_factory):
    return make_figurine_book(tmp_path_factory.mktemp("fig") / "figurines.pdf")


def _spots(pdf):
    """{key: (page, box, symbol)} of every junk character, with its piece."""
    doc = pymupdf.open(pdf)
    lines = game_lines()
    spots, truth = {}, {}
    for pno, page in enumerate(doc, 1):
        pieces = [ch for line in lines[pno - 1] for ch in line if ch in SYMBOLS]
        k = 0
        for b in page.get_text("rawdict")["blocks"]:
            for ln in b.get("lines", []):
                for s in ln["spans"]:
                    for c in s["chars"]:
                        if c["c"] == JUNK:
                            key = f"{pno}:{k}"
                            spots[key] = (pno, list(c["bbox"]), JUNK)
                            truth[key] = pieces[k]
                            k += 1
    return doc, spots, truth


def test_cut_group_and_name(figurine_book):
    doc, spots, truth = _spots(figurine_book)
    masks = figshapes.cut_steps(doc, spots)
    try:
        while True:
            next(masks)
    except StopIteration as stop:
        masks = stop.value
    assert len(masks) >= 0.95 * len(spots)
    # the moves of every fourth cut vote, one in ten of them wrongly
    votes = {}
    for k, key in enumerate(sorted(masks)):
        if k % 4 == 0:
            votes[key] = truth[key] if k % 40 else "KQRBN"["KQRBN".index(truth[key]) - 1]
    shapes = figshapes.Shapes(masks, refs=(np.zeros((0, figshapes.S ** 2), np.float32), [])).name(votes)
    got = shapes.reading()
    right = sum(1 for k, (p, c) in got.items() if p == truth[k])
    assert right >= 0.98 * len(masks), (right, len(masks), shapes.summary())
    # without votes, reference figurines (here the book's own) name the groups
    R = np.array([shapes.X[shapes.keys.index(k)] for k in votes])
    refs = figshapes.Shapes(masks, refs=(R, [truth[k] for k in votes])).name({})
    right = sum(1 for k, (p, c) in refs.reading().items() if p == truth[k])
    assert right >= 0.95 * len(masks)
    assert all(c < figshapes.CONFIDENT for _, c in refs.reading().values())


def test_normalise_keeps_proportions():
    tall = np.zeros((40, 10), bool)
    tall[:, 3:7] = True
    v = figshapes.normalise(tall).reshape(figshapes.S, figshapes.S)
    cols = np.nonzero(v.max(0) > 0.5)[0]
    rows = np.nonzero(v.max(1) > 0.5)[0]
    assert len(rows) > 3 * len(cols)


def test_build_reads_the_figurines(figurine_book, tmp_path):
    plain = build_book(figurine_book, output_dir=tmp_path / "a", books_dir=tmp_path / "b",
                       shapes=False)
    book = build_book(figurine_book, output_dir=tmp_path / "c", books_dir=tmp_path / "d")
    assert "shapes" not in plain
    sh = book["shapes"]
    assert sh["named"] >= 0.9 * sh["symbols"]
    a, b = plain["stats"]["moves"], book["stats"]["moves"]
    assert b["ok"] > a["ok"]
    assert b["failed"] + b["ambiguous"] + b["guessed"] < a["failed"] + a["ambiguous"] + a["guessed"]
    # a symbol whose figurine is named surely carries no eye
    marks = [m for pg in book["pages"] for m in pg["marks"] if m.get("symbol")]
    assert marks and sum(1 for m in marks if m.get("known")) >= 0.8 * len(marks)


# ------------------------------------------------------------------ the corpus

def _book(name):
    folders = [ROOT, ROOT / "corpus", ROOT / "corpus" / "archive3"]
    if os.environ.get("CHESSBOOK_BOOKS"):
        extra = Path(os.environ["CHESSBOOK_BOOKS"])
        folders = [extra, extra / "corpus", extra / "corpus" / "archive3"] + folders
    for f in folders:
        if (f / f"{name}.pdf").exists():
            return f / f"{name}.pdf"
    return None


TRUTH = json.loads((DATA / "figurine_truth.json").read_text(encoding="utf-8")) \
    if (DATA / "figurine_truth.json").exists() else {}


@pytest.mark.parametrize("name", sorted(TRUTH))
def test_corpus_figurine_truth(name, tmp_path):
    """The cuts of the truth set, named as the decoder gets them: a row's
    piece ("-" for a cut that shows no figurine, which must stay unnamed)."""
    pdf = _book(name)
    if pdf is None:
        pytest.skip(f"{name}.pdf is not available")
    book = build_book(pdf, output_dir=tmp_path / "out", books_dir=tmp_path / "books")
    shapes = book["shapes"]["tokens"]
    right = wrong = 0
    for r in TRUTH[name]:
        piece, conf = shapes.get(r["key"], (None, 0.0))
        named = piece if conf >= figshapes.USE_MIN else "-"
        right += named == r["piece"]
        wrong += named not in ("-", r["piece"])
    # measured when the truth was checked: 60 of 60 right in the Primer and
    # kia, 58 in planning and 54 in brunthaler (whose figurines only the
    # references name), and no cut named as the wrong piece
    assert right >= 0.88 * len(TRUTH[name]), (name, right)
    assert wrong == 0, (name, wrong)
