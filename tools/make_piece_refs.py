"""Draw the reference pieces that board reading (chessbook/boards.py) compares
the pieces of a book with, and save them as chessbook/assets/pieces.npz.

Usage:
    python3 tools/make_piece_refs.py [--chromium PATH]

Three piece designs serve as references: the python-chess drawings
(chess.svg, rasterised with headless Chromium), and the chess symbols of the
DejaVu Sans and FreeSerif fonts (drawn with PyMuPDF). Each piece is drawn
black on white in a square of SIZE pixels, standing on the square's lower
part as a diagram font draws it. The browser app cannot run Chromium, so the
drawings ship as data.

The file also holds the square prior: how often each kind of piece stands
on each square in the positions of the games in tests/data/known_games.pgn
(see square_prior).
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import chess
import chess.svg
import cv2
import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "chessbook" / "assets" / "pieces.npz"
SIZE = 64
ORDER = "PNBRQKpnbrqk"
CHROMIUM = "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell"
FONTS = {"dejavu": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "freeserif": "/usr/share/fonts/truetype/freefont/FreeSerif.ttf"}
# The font symbols: U+2654..U+2659 white king..pawn, U+265A..U+265F black.
UNICODE = {"K": 0x2654, "Q": 0x2655, "R": 0x2656, "B": 0x2657, "N": 0x2658, "P": 0x2659,
           "k": 0x265A, "q": 0x265B, "r": 0x265C, "b": 0x265D, "n": 0x265E, "p": 0x265F}


def svg_pieces(chromium):
    cell = 200
    parts = []
    for k, sym in enumerate(ORDER):
        svg = chess.svg.piece(chess.Piece.from_symbol(sym), size=cell)
        parts.append(f"<div style='position:absolute;left:{k * cell}px;top:0;width:{cell}px;"
                     f"height:{cell}px'>{svg}</div>")
    page = ("<html><body style='margin:0;background:#fff'>" + "".join(parts) + "</body></html>")
    with tempfile.TemporaryDirectory() as tmp:
        src, png = Path(tmp) / "p.html", Path(tmp) / "p.png"
        src.write_text(page)
        subprocess.run([chromium, "--headless", "--no-sandbox", "--disable-gpu",
                        f"--window-size={cell * 12},{cell}", "--hide-scrollbars",
                        f"--screenshot={png}", src.as_uri()], check=True,
                       capture_output=True, timeout=120)
        img = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
    return [img[:, k * cell:(k + 1) * cell] for k in range(12)]


def font_pieces(path):
    out = []
    for sym in ORDER:
        doc = pymupdf.open()
        page = doc.new_page(width=200, height=200)
        page.insert_font(fontname="f", fontfile=path)
        page.insert_text((15, 170), chr(UNICODE[sym]), fontname="f", fontsize=170)
        pix = page.get_pixmap(dpi=72, colorspace=pymupdf.csGRAY)
        out.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.stride)[:, :pix.w].copy())
    return out


def ink_height(img):
    ys = np.nonzero((img < 160).any(1))[0]
    return float(ys.max() - ys.min() + 1)


def normalise(img):
    """The piece in a SIZE square: its ink box scaled to 80% of the square's
    height (or width), centred across and standing at 90% down."""
    ink = img < 160
    ys, xs = np.nonzero(ink)
    crop = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape
    k = 0.8 * SIZE / max(h, w)
    crop = cv2.resize(crop, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
    out = np.full((SIZE, SIZE), 255, np.uint8)
    h, w = crop.shape
    y = round(0.9 * SIZE) - h
    x = (SIZE - w) // 2
    out[y:y + h, x:x + w] = crop
    return out


def square_prior(pgn_path):
    """Where each kind of piece stands in the positions of real games:
    prior[k, sq] is the share of the time that a piece ORDER[k] spends on
    square sq (python-chess numbering, a1 = 0), counted over every position
    of the games in pgn_path. Black's table is White's seen from the other
    side, so both colours learn from both sides; a little of the mirror
    image across the board and a uniform share smooth the counts."""
    import chess.pgn
    counts = np.zeros((6, 64))
    with open(pgn_path, encoding="utf-8") as fh:
        while True:
            game = chess.pgn.read_game(fh)
            if game is None:
                break
            board = game.board()
            for move in [None] + list(game.mainline_moves()):
                if move is not None:
                    board.push(move)
                for sq, p in board.piece_map().items():
                    own = sq if p.color == chess.WHITE else chess.square_mirror(sq)
                    counts[p.piece_type - 1, own] += 1
    mirror = [chess.square(7 - chess.square_file(s), chess.square_rank(s)) for s in range(64)]
    counts = 0.8 * counts + 0.2 * counts[:, mirror]
    prior = counts / counts.sum(1, keepdims=True)
    prior = 0.85 * prior + 0.15 / 64
    prior[0, :8] = prior[0, 56:] = 1e-4          # no pawn stands on the first or last rank
    prior /= prior.sum(1, keepdims=True)
    order = {"P": 0, "N": 1, "B": 2, "R": 3, "Q": 4, "K": 5}
    out = np.zeros((12, 64))
    for k, sym in enumerate(ORDER):
        t = prior[order[sym.upper()]]
        out[k] = t if sym.isupper() else t[[chess.square_mirror(s) for s in range(64)]]
    return out.astype(np.float32)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chromium", default=CHROMIUM)
    ap.add_argument("--games", default=str(ROOT / "tests" / "data" / "known_games.pgn"))
    args = ap.parse_args(argv)
    sets = {"svg": svg_pieces(args.chromium)}
    for name, path in FONTS.items():
        sets[name] = font_pieces(path)
    names = sorted(sets)
    arr = np.stack([[normalise(im) for im in sets[n]] for n in names])
    # each piece's height as a share of its king's, which a design keeps
    # whatever the size it is drawn at
    heights = np.array([[ink_height(im) for im in sets[n]] for n in names], np.float32)
    heights[:, :6] /= heights[:, 5:6]
    heights[:, 6:] /= heights[:, 11:12]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, pieces=arr, designs=np.array(names), order=np.array(list(ORDER)),
                        heights=heights, prior=square_prior(args.games))
    print(f"Wrote {OUT}: {arr.shape}")


if __name__ == "__main__":
    sys.exit(main())
