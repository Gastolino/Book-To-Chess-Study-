"""Stage 3: read the board pictures of a chess book into positions (FENs).

read_book_boards(pdf, diagrams) reads every diagram of a book and returns
{diagram id: {"fen", "confidence", "doubtful", "status", ...}}. Nobody labels
anything by hand for a book: the program learns the book's piece drawings
from the book itself.

How a board is read
-------------------
1. The grid. Every board alternates light and dark squares. The program
   slides an 8 x 8 checker pattern over the picture, at every size from two
   thirds of the picture's shorter side up to the whole of it, and keeps the
   place where the corners of the squares (which pieces rarely cover)
   alternate most strongly between light and dark. The grid is then refined
   on a finer copy of the picture. A picture whose best grid does not
   separate light and dark corners cleanly holds part of a board only (or no
   board): it is reported as partial and skipped.
2. The pieces. The board is scaled to 64 pixels a square. Diagonal hatching
   of the dark squares is erased (long diagonal runs of thin ink; the solid
   black of a piece is protected). In each square, the background is the
   region that looks like an empty square of that colour and that can be
   reached from the square's edge; the rest is the piece. Thin strokes, such
   as arrows drawn on the board, do not count.
3. The piece drawings. A book draws each piece the same way every time, so
   the drawings of the whole book fall into groups of nearly identical
   pictures. The program groups them, splits the groups into white and black
   pieces (white pieces are mostly paper inside), and names each group:
     - where each group's pieces stand: kings stand on g1 and e1 far more
       often than pawns do, rooks on a1 and h1, and no pawn stands on the
       first or last rank (a table of squares learnt from real games);
     - how the group's outline compares with three reference piece designs
       (the python-chess drawings and two fonts, in assets/pieces.npz) and
       how tall it is beside the book's other pieces;
     - that every board has exactly one king of each colour, and seldom more
       than one queen or two rooks, bishops or knights of a colour;
     - positions the program already knows: a printed initial position, and
       the positions that decoded lines of the book reach at a diagram.
   The names that best satisfy all of these at once are kept.
4. Confidence. Each square gets a confidence from how clearly it is empty or
   occupied, how close its drawing is to its group, and how clearly its
   group's name won. Squares below DOUBT are listed as doubtful.
5. Orientation and side to move. Coordinates printed beside the picture tell
   when a board is shown from Black's side. The caption ("(B)", "Black to
   move", "White to play") gives the side to move; otherwise White is
   assumed, and the assembly takes the side from the move numbers that
   follow the diagram.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

import chess
import cv2
import numpy as np
import pymupdf

ASSETS = Path(__file__).resolve().parent / "assets"
MAX_SIDE = 720         # larger pictures are scaled down to this shorter side first
N = 64                 # pixels per square in the normalised board
G = 32                 # pixels per square side of a drawing's grouping feature
TYPES = "PNBRQK"
DOUBT = 0.6            # squares read with less confidence are doubtful
MIN_AREA = 0.08        # share of a square that a piece covers at least
SPECK = 0.55           # drawings below this share of the usual piece need dark ink to count
GROUP_DIST = 0.1       # RMS difference within one group of drawings
COLOUR_DOUBT = 0.08    # groups this close to the white/black divide may be either
PAR = (np.add.outer(np.arange(8), np.arange(8)) % 2).astype(bool)   # the dark squares of a normal board
RING = 6 * N // 64     # pixels at the edge of each square that count as background
SOLID_K = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5 * N // 64, 5 * N // 64))
CROSS = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
OPEN_K = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5 * N // 64, 5 * N // 64))
START = chess.STARTING_BOARD_FEN


# ---------------------------------------------------------------- pictures

def _gray_from_pixmap(pix):
    if pix.n == 1 and not pix.alpha:
        return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.stride)[:, :pix.w].copy()
    if pix.n - pix.alpha != 1 and pix.n - pix.alpha != 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.stride)[:, :pix.w * pix.n]
    a = a.reshape(pix.h, pix.w, pix.n).astype(np.float32)
    if pix.alpha:
        alpha = a[:, :, -1:] / 255.0
        a = a[:, :, :-1] * alpha + 255.0 * (1 - alpha)     # transparent parts are paper
    if a.shape[2] == 3:
        a = a @ np.float32([0.299, 0.587, 0.114])
    else:
        a = a[:, :, 0]
    return np.clip(a, 0, 255).astype(np.uint8)


def picture_gray(doc, xref):
    """An embedded picture as a grey array (paper light)."""
    g = _gray_from_pixmap(pymupdf.Pixmap(doc, xref))
    if np.median(g) < 100:      # a stencil or a negative: make the paper light
        g = 255 - g
    return g


class Pictures:
    """Finds the embedded picture behind each diagram record of Stage 1."""

    def __init__(self, doc):
        self.doc = doc
        self.pages = {}

    def images(self, pno):
        if pno not in self.pages:
            imgs = {i[0]: (i[0], i[2], i[3]) for i in self.doc[pno - 1].get_images(full=True)}
            self.pages[pno] = list(imgs.values())
        return self.pages[pno]

    def gray(self, rec):
        """The part of the page that rec["rect"] covers, as a grey array at
        about the resolution of the embedded picture (at most MAX_SIDE pixels
        on its shorter side)."""
        r = pymupdf.Rect(rec["rect"])
        px = list(rec.get("pixels") or [0, 0])
        page = self.doc[rec["page"] - 1]
        g = None
        if not rec.get("sub"):
            # the one picture of the page with the record's size: Stage 1's
            # rect is where it stands
            same = [x for x, w, h in self.images(rec["page"]) if [w, h] == px]
            if len(same) > 1:
                same = [x for x in same
                        if any(abs(q.x0 - r.x0) < 2 and abs(q.y0 - r.y0) < 2
                               for q in page.get_image_rects(x))][:1]
            if len(same) == 1:
                try:
                    g = picture_gray(self.doc, same[0])
                except (RuntimeError, ValueError):
                    g = None
        if g is None:
            # a board inside a picture of stacked boards: cut it out of the
            # picture that covers it
            for x, _, _ in self.images(rec["page"]):
                for q in page.get_image_rects(x, transform=True):
                    box, m = q
                    plain = abs(m.b) < 1e-6 and abs(m.c) < 1e-6 and m.a > 0 and m.d > 0
                    if g is None and plain and abs(box & r) > 0.9 * abs(r):
                        try:
                            full = picture_gray(self.doc, x)
                        except (RuntimeError, ValueError):
                            continue
                        H, W = full.shape
                        kx, ky = W / box.width, H / box.height
                        x0, y0 = int(max(0, round((r.x0 - box.x0) * kx))), int(max(0, round((r.y0 - box.y0) * ky)))
                        x1, y1 = int(min(W, round((r.x1 - box.x0) * kx))), int(min(H, round((r.y1 - box.y0) * ky)))
                        if x1 - x0 > 8 and y1 - y0 > 8:
                            g = full[y0:y1, x0:x1]
        if g is None:
            # a rotated or unusual picture: render that part of the page
            zoom = (px[0] / max(1.0, r.width)) if px[0] else 3.0
            zoom = max(1.0, min(zoom, MAX_SIDE / max(1.0, min(r.width, r.height))))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=r, colorspace=pymupdf.csGRAY)
            g = _gray_from_pixmap(pix)
        h, w = g.shape
        if min(h, w) > MAX_SIDE:
            k = MAX_SIDE / min(h, w)
            g = cv2.resize(g, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
        return g


# ---------------------------------------------------------------- the grid

def _box(ii, p):
    """Sum of every p x p window of the image whose integral is ii, indexed
    by the window's top-left corner."""
    return ii[p:, p:] - ii[:-p, p:] - ii[p:, :-p] + ii[:-p, :-p]


def _scan(dark, sizes, inset, frac):
    """Best (score, x0, y0, s) of an 8x8 checker grid over a darkness image:
    the mean darkness of the four corner patches of every cell, with
    alternating signs, is largest where the grid fits the squares. The sign
    of cell (i, j) is the product of a row sign and a column sign, so the sum
    separates into eight column shifts and eight row shifts."""
    H, W = dark.shape
    ii = cv2.integral(dark).astype(np.float32)
    best = (-1.0, 0, 0, 0.0)
    for s in sizes:
        span = int(np.ceil(8 * s))
        nx, ny = W - span + 1, H - span + 1
        if nx < 1 or ny < 1:
            continue
        p = max(1, int(round(frac * s)))
        a = int(round(inset * s))
        B = _box(ii, p)
        b = int(round(s - 2 * a - p))
        hb, wb = B.shape
        if b < 0 or a + b >= min(hb, wb):
            continue
        C = B[a:hb - b, a:wb - b] + B[a:hb - b, a + b:] + B[a + b:, a:wb - b] + B[a + b:, a + b:]
        R = np.zeros((C.shape[0], nx), np.float32)
        for j in range(8):
            x = int(round(j * s))
            R += (1 if j % 2 else -1) * C[:, x:x + nx]
        acc = np.zeros((ny, nx), np.float32)
        for i in range(8):
            y = int(round(i * s))
            acc += (1 if i % 2 else -1) * R[y:y + ny]
        acc = np.abs(acc)
        k = np.unravel_index(np.argmax(acc), acc.shape)
        v = acc[k] / (256 * p * p)
        if v > best[0]:
            best = (float(v), int(k[1]), int(k[0]), float(s))
    return best


def _scaled(gray, f):
    H, W = gray.shape
    small = cv2.resize(gray, (max(1, round(W * f)), max(1, round(H * f))), interpolation=cv2.INTER_AREA)
    return (255.0 - small.astype(np.float32)) / 255.0


def locate_grid(gray):
    """(x0, y0, s, score): the board's top-left corner and square size in
    picture pixels, and the strength of the checker pattern there."""
    H, W = gray.shape
    f = 96.0 / min(H, W)
    dark = _scaled(gray, f)
    sm = min(dark.shape) / 8
    v, x0, y0, s = _scan(dark, np.arange(0.65 * sm, sm + 1e-6, 0.2), 0.06, 0.22)
    if s <= 0:
        return 0.0, 0.0, 1.0, 0.0
    # refine on a copy with about 32 pixels a square
    f2 = min(1.0, 32.0 / (s / f))
    darkf = _scaled(gray, f2)
    r = f2 / f
    X0, Y0, S = x0 * r, y0 * r, s * r
    span = int(np.ceil(8 * (S + 0.3 * r)))
    lx, ly = int(max(0, X0 - 1.5 * r)), int(max(0, Y0 - 1.5 * r))
    sub = darkf[ly:int(Y0 + 1.5 * r) + span + 1, lx:int(X0 + 1.5 * r) + span + 1]
    res = _scan(sub, np.arange(S - 0.3 * r, S + 0.3 * r + 1e-6, 0.125), 0.03, 0.15)
    if res[3]:
        X0, Y0, S = res[1] + lx, res[2] + ly, res[3]
    return X0 / f2, Y0 / f2, S / f2, v


def grid_check(gray, x0, y0, s):
    """(agreement, dark_top_left): the share of the squares' corner patches
    on the expected side of the light/dark divide (a whole board scores well
    above 0.8, a part of a board or a page of text near 0.5), and whether
    the top-left square is the dark one."""
    f = min(1.0, 40.0 / s)
    dark = _scaled(gray, f)
    ii = cv2.integral(dark)
    X0, Y0, S = x0 * f, y0 * f, s * f
    a, p = 0.08 * S, max(1, int(round(0.18 * S)))
    B = _box(ii, p)
    hb, wb = B.shape
    js = np.arange(8)
    xs = np.concatenate([X0 + js * S + a, X0 + js * S + S - a - p])
    ys = np.concatenate([Y0 + js * S + a, Y0 + js * S + S - a - p])
    xi = np.clip(np.round(xs).astype(int), 0, wb - 1)
    yi = np.clip(np.round(ys).astype(int), 0, hb - 1)
    V = B[yi][:, xi] / (p * p)                   # 16 x 16 corner patches
    cell = PAR[np.tile(js, 2)][:, np.tile(js, 2)]
    pos, neg = V[cell], V[~cell]
    flipped = pos.mean() < neg.mean()
    if flipped:
        pos, neg = neg, pos
    thr = (np.median(pos) + np.median(neg)) / 2
    agree = ((pos > thr).sum() + (neg <= thr).sum()) / V.size
    return float(agree), bool(flipped)


# ---------------------------------------------------------------- the squares

def board_image(gray, x0, y0, s):
    """The board cut out of the picture and scaled to 8N x 8N, float32 with
    the paper at 1 and the ink at 0."""
    H, W = gray.shape
    f = N / s
    xa, ya = int(np.floor(x0)), int(np.floor(y0))
    xb, yb = int(np.ceil(x0 + 8 * s)) + 1, int(np.ceil(y0 + 8 * s)) + 1
    crop = gray[max(0, ya):min(H, yb), max(0, xa):min(W, xb)]
    crop = cv2.copyMakeBorder(crop, max(0, -ya), max(0, yb - H), max(0, -xa), max(0, xb - W),
                              cv2.BORDER_REPLICATE)
    big = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
    ox, oy = int(round((x0 - xa) * f)), int(round((y0 - ya) * f))
    big = big[oy:oy + 8 * N, ox:ox + 8 * N]
    if big.shape != (8 * N, 8 * N):
        big = cv2.resize(big, (8 * N, 8 * N), interpolation=cv2.INTER_AREA)
    a = big.astype(np.float32)
    sample = a[::3, ::3]
    paper = np.percentile(sample, 97)
    ink = np.percentile(sample, 0.5)
    a -= ink
    a *= 1.0 / max(paper - ink, 1.0)
    return np.minimum(np.maximum(a, 0, out=a), 1, out=a)


def _diag_mean(img, L, dy):
    """Mean of img over a diagonal run of L pixels (a power of two) centred
    on each pixel: dy = -1 runs up to the right ("/"), dy = 1 down ("\\")."""
    P = np.pad(img, L)
    S = P.copy()
    step = 1
    while step < L:
        S += np.roll(S, (-dy * step, -step), axis=(0, 1))
        step *= 2
    h = L // 2
    S = np.roll(S, (dy * h, h), axis=(0, 1))
    return S[L:-L, L:-L] / L


def _run_mean(img, L, sy, sx, offset):
    """Mean of img over the L pixels (a power of two) at offset .. offset+L-1
    steps from each pixel in the direction (sy, sx), a diagonal step."""
    pad = L + offset
    S = np.pad(img, pad)
    step = 1
    while step < L:
        S = S + np.roll(S, (-sy * step, -sx * step), axis=(0, 1))
        step *= 2
    S = np.roll(S, (-sy * offset, -sx * offset), axis=(0, 1))
    return S[pad:-pad, pad:-pad] / L


def remove_hatching(a):
    """Erase the diagonal hatching of dark squares from a board image.

    A hatching pixel is ink that lies on a long diagonal run of ink in one
    direction while the other diagonal crosses about as much ink as an
    empty dark square holds; the solid black of a piece is ink both ways
    and is protected, and a piece outline is too short. How dense the
    hatching is (thin lines far apart, or thick lines close together) is
    measured on the dark squares first. Returns (cleaned image, share of the
    dark squares' area that was hatching)."""
    ink = (a < 0.55).astype(np.float32)
    q = N // 4
    dens = ink.reshape(8, N, 8, N)[:, q:-q, :, q:-q].mean(axis=(1, 3))
    density = max(float(np.median(dens[PAR])), float(np.median(dens[~PAR])))
    if density < 0.08:
        return a, 0.0
    cross = min(0.85, max(0.6, density + 0.25))
    L = 16 * N // 64
    r1 = _diag_mean(ink, L, -1)
    r2 = _diag_mean(ink, L, 1)
    cells = PAR.repeat(N, 0).repeat(N, 1)
    best = None
    for ra, rb, dy in ((r1, r2, 1), (r2, r1, -1)):
        h = (ink > 0) & (ra > 0.6) & (rb < cross) & (ra > rb + 0.2)
        share = max(h[cells].mean(), h[~cells].mean())
        if best is None or share > best[1]:
            best = (h, share, ra, rb, dy)
    h, share, ra, rb, dy = best
    if share < 0.05:
        return a, float(share)
    # stubs at the ends of the lines: ink close along a line to hatching
    k = (ra > 0.4) & (rb < cross - 0.15) & (ink > 0)
    sq = np.ones((3, 3), np.uint8)
    near = cv2.dilate(h.astype(np.uint8), sq, iterations=2) > 0
    h = h | (k & near)
    # hatching has more lines on both sides across it; the outline of a
    # white piece has the paper of the piece's inside on one side
    half = L // 2
    side_a = _run_mean(ink, half, dy, 1, 2)
    side_b = _run_mean(ink, half, -dy, -1, 2)
    # (near the edge of a square the other side may be a light square)
    band = np.ones(N, bool)
    band[N // 8:N - N // 8] = False
    edge = np.tile(band, 8)
    edge = edge[:, None] | edge[None, :]
    h &= (np.minimum(side_a, side_b) > 0.12) | edge
    # solid ink (the body of a black piece, a thick outline) is never
    # hatching; dense hatching has thick lines, so "solid" must be thicker
    ink8 = ink.astype(np.uint8)
    kk = SOLID_K if density > 0.4 else sq
    solid = cv2.dilate(cv2.erode(ink8, kk), kk) > 0
    solid = cv2.dilate(solid.astype(np.uint8), sq) > 0
    h &= ~solid
    out = a.copy()
    out[h] = 1.0
    fringe = cv2.dilate(h.astype(np.uint8), sq) > 0
    out[fringe & (a > 0.3)] = 1.0
    return out, float(share)


def _local_stats(a, sigma):
    """Local mean and standard deviation of a square, blurred within the
    square only (its edge reflected), so that neighbours do not bleed in."""
    m = cv2.GaussianBlur(a, (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    m2 = cv2.GaussianBlur(a * a, (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    return m, np.sqrt(np.maximum(m2 - m * m, 0))


def segment(a):
    """Piece masks (8, 8, N, N) of the squares of a cleaned board image, and
    each mask's area before thin strokes were removed.

    A pixel belongs to the background when its neighbourhood looks like the
    empty squares of its colour (mean grey and texture). The piece is what
    the background, spreading from the square's edge, does not reach: a
    white piece's inside is enclosed by its outline."""
    # the blur is narrow, so neighbours bleed only into the ring, which
    # counts as background anyway
    Mi, Si = _local_stats(a, N / 64)
    M = Mi.reshape(8, N, 8, N).transpose(0, 2, 1, 3)
    S = Si.reshape(8, N, 8, N).transpose(0, 2, 1, 3)
    ring = np.ones((N, N), bool)
    ring[RING:-RING, RING:-RING] = False
    q = N // 4
    cm_all = M[:, :, q:-q:2, q:-q:2].reshape(8, 8, -1)
    cs_all = S[:, :, q:-q:2, q:-q:2].reshape(8, 8, -1)
    info = {}
    for p in (False, True):
        cm = np.median(cm_all[PAR == p], axis=1)
        cs = np.median(cs_all[PAR == p], axis=1)
        # the empty squares are alike: the densest group of squares
        dist = np.maximum(np.abs(cm[:, None] - cm[None]), np.abs(cs[:, None] - cs[None]))
        k = int(np.argmax((dist < 0.05).sum(1)))
        calm = dist[k] < 0.05
        mb, sb = float(np.median(cm[calm])), float(np.median(cs[calm]))
        dm = np.abs(cm_all[PAR == p][calm] - mb)
        ds = np.abs(cs_all[PAR == p][calm] - sb)
        tm = min(0.25, max(0.08, 2 * float(np.percentile(dm, 98))))
        ts = min(0.25, max(0.06, 2 * float(np.percentile(ds, 98))))
        info[p] = (mb, sb, tm, ts)
    masks = np.zeros((8, 8, N, N), bool)
    raw = np.zeros((8, 8))
    P = np.array([[info[bool(PAR[i, j])] for j in range(8)] for i in range(8)], np.float32)
    BG = ((np.abs(M - P[:, :, 0, None, None]) < P[:, :, 2, None, None])
          & (np.abs(S - P[:, :, 1, None, None]) < P[:, :, 3, None, None]))
    BG |= ring
    busy = (~BG).sum(axis=(2, 3))
    for i in range(8):
        for j in range(8):
            if busy[i, j] < 0.3 * MIN_AREA * N * N:
                raw[i, j] = busy[i, j] / (N * N)
                continue                # nothing like a piece: empty
            bgl = BG[i, j]
            # the background may not seep through gaps in a thin outline:
            # spread it over the background narrowed by a pixel, then let
            # what it reached widen again
            narrow = cv2.erode(bgl.astype(np.uint8), CROSS) | ring
            _, lab = cv2.connectedComponents(narrow, connectivity=4)
            reached = (lab == lab[0, 0]).astype(np.uint8)
            reached = cv2.dilate(reached, CROSS) & bgl
            mk = 1 - reached
            raw[i, j] = mk.mean()
            mk = cv2.morphologyEx(mk, cv2.MORPH_OPEN, OPEN_K)
            if mk.any():
                # close small gaps in an outline and fill what it encloses;
                # specks apart from the drawing's main part do not count
                mk = _fill(cv2.morphologyEx(mk, cv2.MORPH_CLOSE, OPEN_K) > 0).astype(np.uint8)
                n, lab, stats, _ = cv2.connectedComponentsWithStats(mk, connectivity=8)
                if n > 2:
                    big = stats[1:, cv2.CC_STAT_AREA].max()
                    keep = [k for k in range(1, n) if stats[k, cv2.CC_STAT_AREA] >= 0.3 * big]
                    mk = np.isin(lab, keep).astype(np.uint8)
            masks[i, j] = mk > 0
    return masks, raw


ERODE = np.ones((3, 3), np.uint8)


def board_cells(gray):
    """Read the squares of one board picture. Returns a dict with "grid"
    None when the picture holds no whole board; else the grid (x0, y0, s) in
    picture pixels and, for each occupied square (row, column from the top
    left of the picture), its drawing: "glyph" (N x N, background white,
    centred across, foot at a fixed height), "mask", "area" (share of the
    square), "height" and "white" (share of the inside that is paper)."""
    out = {"grid": None, "agree": 0.0, "score": 0.0}
    if gray is None or min(gray.shape) < 48 or max(gray.shape) > 4 * min(gray.shape):
        return out
    x0, y0, s, score = locate_grid(gray)
    agree, dark_corner = grid_check(gray, x0, y0, s)
    out.update(agree=agree, score=score)
    if agree < 0.8 or score < 0.06:
        return out
    a = board_image(gray, x0, y0, s)
    c, hatch = remove_hatching(a)
    masks, raw = segment(c)
    C = c.reshape(8, N, 8, N).transpose(0, 2, 1, 3)
    occ = {}
    areas = masks.mean(axis=(2, 3))
    for i in range(8):
        for j in range(8):
            mk = masks[i, j]
            if areas[i, j] < MIN_AREA:
                continue
            ys, xs = np.nonzero(mk)
            g = np.where(mk, C[i, j], 1.0)
            dx = int(round(N / 2 - (xs.min() + xs.max() + 1) / 2))
            dy = int(round(0.9 * N - (ys.max() + 1)))
            T = np.float32([[1, 0, dx], [0, 1, dy]])
            g = cv2.warpAffine(g, T, (N, N), borderValue=1.0)
            m2 = cv2.warpAffine(mk.astype(np.uint8), T, (N, N), borderValue=0)
            # the colour: how much of the drawing's convex hull is paper (an
            # outline with gaps still has a hull that holds its inside)
            hull = np.zeros_like(m2)
            pts = cv2.findNonZero(m2)
            cv2.fillConvexPoly(hull, cv2.convexHull(pts), 1)
            inner = cv2.erode(hull, ERODE, iterations=2 * N // 64) > 0
            white = float((g[inner] > 0.6).mean()) if inner.any() else 0.0
            ink = float((g[m2 > 0] < 0.3).mean())
            occ[(i, j)] = {"glyph": (g * 255).astype(np.uint8), "mask": m2 > 0,
                           "area": float(areas[i, j]), "height": float(ys.max() - ys.min() + 1) / N,
                           "white": white, "ink": ink}
    out.update(grid=(float(x0), float(y0), float(s)), hatch=hatch, cells=occ,
               areas=areas, raw=raw, dark_corner=dark_corner)
    return out


# ---------------------------------------------------------------- references

_REFS = None


def _fill(mask):
    """The mask with its holes filled (everything the outside cannot reach)."""
    m = np.pad(mask.astype(np.uint8), 1)
    cv2.floodFill(m, None, (0, 0), 2)
    return m[1:-1, 1:-1] != 2


def _silhouette(mask, S=48):
    """A filled outline scaled to fit 80% of an S square, standing at 90%."""
    ys, xs = np.nonzero(mask)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
    h, w = crop.shape
    k = 0.8 * S / max(h, w)
    crop = cv2.resize(crop, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
    out = np.zeros((S, S), np.float32)
    h, w = crop.shape
    y, x = round(0.9 * S) - h, (S - w) // 2
    out[y:y + h, x:x + w] = crop
    return out


def references():
    """(silhouettes {type: [S x S, ...]}, heights {type: share of king's},
    prior (12, 64)) from assets/pieces.npz."""
    global _REFS
    if _REFS is None:
        z = np.load(ASSETS / "pieces.npz")
        order = [str(x) for x in z["order"]]
        sil = defaultdict(list)
        for design in z["pieces"]:
            for k, sym in enumerate(order):
                sil[sym.upper()].append(_silhouette(_fill(design[k] < 160)))
        designs = [str(x) for x in z["designs"]]
        hs = z["heights"][[k for k, d in enumerate(designs) if d != "dejavu"] or slice(None)]
        heights = {t: float(hs[:, order.index(t)].mean()) for t in TYPES}
        prior = {sym: z["prior"][k] for k, sym in enumerate(order)}
        _REFS = (dict(sil), heights, prior)
    return _REFS


def shape_scores(mask):
    """{type: best overlap (IoU) of the filled outline with a reference}."""
    sil, _, _ = references()
    s = _silhouette(_fill(mask))
    out = {}
    for t, refs in sil.items():
        out[t] = max(float(np.minimum(s, r).sum() / max(np.maximum(s, r).sum(), 1e-6)) for r in refs)
    return out


# ---------------------------------------------------------------- grouping

def _feature(glyph):
    g = cv2.resize(glyph, (G, G), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    return cv2.GaussianBlur(g, (0, 0), 1.0).ravel()


def _sqdist(X, C):
    """Squared distances between the rows of X and of C."""
    X = X.astype(np.float32)
    C = C.astype(np.float32)
    d = (X * X).sum(1)[:, None] - 2 * X @ C.T + (C * C).sum(1)[None]
    return np.maximum(d, 0)


def group_drawings(X, T=GROUP_DIST):
    """Group feature vectors whose RMS difference is below T: each vector
    joins the nearest group centre within T or starts a group; a second pass
    assigns every vector to its nearest centre. Returns (labels, centres)."""
    cap = 64
    cents = np.zeros((cap, X.shape[1]), np.float32)
    sums = np.zeros((cap, X.shape[1]), np.float64)
    counts = np.zeros(cap)
    n = 0
    lab = np.zeros(len(X), int)
    limit = T * T * X.shape[1]
    for k, x in enumerate(X):
        if n:
            d = ((cents[:n] - x) ** 2).sum(1)
            j = int(np.argmin(d))
            if d[j] < limit:
                sums[j] += x
                counts[j] += 1
                cents[j] = sums[j] / counts[j]
                lab[k] = j
                continue
        if n == cap:
            cap *= 2
            cents = np.resize(cents, (cap, X.shape[1]))
            sums = np.resize(sums, (cap, X.shape[1]))
            counts = np.resize(counts, cap)
        cents[n], sums[n], counts[n] = x, x, 1
        lab[k] = n
        n += 1
    C = cents[:n]
    if len(C) > 1:
        # reassign every vector to its nearest centre
        lab = np.argmin(_sqdist(X, C), 1)
        used = np.unique(lab)
        remap = {u: k for k, u in enumerate(used)}
        lab = np.array([remap[v] for v in lab])
        C = np.array([X[lab == k].mean(0) for k in range(len(used))])
    return lab, C


# ---------------------------------------------------------------- naming

def _otsu_split(values, weights):
    """The threshold that best splits weighted values in two."""
    order = np.argsort(values)
    v, w = np.asarray(values)[order], np.asarray(weights, float)[order]
    best = (None, -1.0)
    for k in range(1, len(v)):
        w0, w1 = w[:k].sum(), w[k:].sum()
        if w0 == 0 or w1 == 0:
            continue
        m0, m1 = (v[:k] * w[:k]).sum() / w0, (v[k:] * w[k:]).sum() / w1
        between = w0 * w1 * (m0 - m1) ** 2
        if between > best[1]:
            best = ((v[k - 1] + v[k]) / 2, between)
    return best[0] if best[0] is not None else 0.5


class Namer:
    """Names groups of drawings as pieces by maximising a score that adds,
    for every group, how well its squares, outline and height fit each
    piece, and for every board how well the counts of kings, queens and
    other pieces fit a position. A name is a piece symbol, upper case for
    White: a group whose colour is clear chooses among the six pieces of its
    colour, a group whose colour is unclear among all twelve."""

    W_SHAPE = 25.0      # per unit of outline overlap
    W_HEIGHT = 8.0
    W_KNOWN = 4.0       # per square of a known position
    KING = 6.0          # per board without exactly one king of a colour
    EXTRA = 2.0         # per queen beyond one, or rook, bishop or knight beyond two
    PAWNS = 6.0         # per pawn beyond eight

    def __init__(self, groups):
        # groups: dicts {"kind", "colours": "w", "b" or "wb", "members":
        # [(board, square)], "shape": {type: iou}, "height", "known": Counter(symbol)}
        self.groups = groups
        _, self.ref_heights, self.prior = references()

    def unary(self, g, flip):
        """Score of each allowed symbol for group g given the orientations."""
        out = {}
        H = self.tall
        best_shape = max(g["shape"].values()) if g["shape"] else 0.0
        for t in TYPES:
            base = self.W_SHAPE * (g["shape"].get(t, 0) - best_shape)
            if H:
                base -= self.W_HEIGHT * ((g["height"] / H - self.ref_heights[t]) / 0.08) ** 2 / 2
            for colour in g["colours"]:
                sym = t if colour == "w" else t.lower()
                pr = self.prior[sym]
                sq = [_square(r, c, flip.get(b, False)) for b, (r, c) in g["members"]]
                s = base + (float(np.log(pr[sq]).sum()) if sq else 0.0)
                s += self.W_KNOWN * g["known"].get(sym, 0)
                out[sym] = s
        return out

    def board_cost(self, cnt):
        c = 0.0
        for case in (str.upper, str.lower):
            c += self.KING * abs(cnt[case("K")] - 1)
            c += self.EXTRA * max(0, cnt[case("Q")] - 1)
            for t in "RBN":
                c += self.EXTRA * max(0, cnt[case(t)] - 2)
            c += self.PAWNS * max(0, cnt[case("P")] - 8)
        return c

    def solve(self, flip):
        """(names, margins): a symbol (or None for marks) for every group,
        and how far its name's score is ahead of the next best."""
        gs = self.groups
        hs = sorted((g["height"], len(g["members"])) for g in gs if g["kind"] == "piece")
        self.tall = None
        if hs:
            tot = sum(n for _, n in hs)
            acc = 0
            for h, n in hs:
                acc += n
                if acc >= 0.9 * tot:
                    self.tall = h
                    break
        U = [self.unary(g, flip) if g["kind"] == "piece" else None for g in gs]
        lab = [max(u, key=u.get) if u else None for u in U]
        per_board = [Counter(b for b, _ in g["members"]) for g in gs]
        counts = defaultdict(Counter)      # board -> symbol -> count

        def add(k, sym, sign):
            for b, c in per_board[k].items():
                counts[b][sym] += sign * c

        for k, sym in enumerate(lab):
            if sym:
                add(k, sym, 1)
        order = sorted(range(len(gs)), key=lambda k: -len(gs[k]["members"]))
        margins = [0.0] * len(gs)
        for _ in range(8):
            changed = False
            for k in order:
                if not U[k]:
                    continue
                bs = list(per_board[k])
                add(k, lab[k], -1)
                before = {b: self.board_cost(counts[b]) for b in bs}
                scores = {}
                for sym in U[k]:
                    cost = 0.0
                    for b in bs:
                        cnt = counts[b].copy()
                        cnt[sym] += per_board[k][b]
                        cost += self.board_cost(cnt) - before[b]
                    scores[sym] = U[k][sym] - cost
                best = max(scores, key=scores.get)
                vals = sorted(scores.values(), reverse=True)
                margins[k] = vals[0] - vals[1] if len(vals) > 1 else 99.0
                changed |= best != lab[k]
                lab[k] = best
                add(k, best, 1)
            if not changed:
                break
        return lab, margins


def _square(r, c, flip):
    """python-chess square of picture row r, column c (row 0 at the top)."""
    if flip:
        return chess.square(7 - c, r)
    return chess.square(c, 7 - r)


# ---------------------------------------------------------------- text near a diagram

TURN_RE = [
    # "(B)" and "(W)" in capitals only: a lower-case "(b)" names a part of a
    # question or a second diagram, and "(White)" after a name a player
    (re.compile(r"\((?:B|Bl\.?)\)|\b[Bb]lack\s+to\s+(?:move|play)|\b[Bb]lack\s+moves\b"
                r"|\bSchwarz\s+(?:am\s+Zug|zieht)|\bNoirs?\s+jouent|\bjuegan\s+(?:las\s+)?negras"), "b"),
    (re.compile(r"\((?:W|Wh\.?)\)|\b[Ww]hite\s+to\s+(?:move|play)|\b[Ww]hite\s+moves\b"
                r"|\bWei(?:ss|ß)\s+(?:am\s+Zug|zieht)|\bBlancs?\s+jouent|\bjuegan\s+(?:las\s+)?blancas"), "w"),
]


def page_words(page):
    """(words, lines) of a page: words as (Rect, text), lines as (Rect, text)."""
    words, lines = [], defaultdict(list)
    for x0, y0, x1, y1, t, blk, ln, _ in page.get_text("words"):
        r = pymupdf.Rect(x0, y0, x1, y1)
        words.append((r, t))
        lines[(blk, ln)].append((r, t))
    out = []
    for ws in lines.values():
        box = pymupdf.Rect(ws[0][0])
        for r, _ in ws[1:]:
            box |= r
        out.append((box, " ".join(t for _, t in ws)))
    return words, out


def caption_turn(lines, rect, gap=40):
    """'w' or 'b' when a caption printed just above or below the diagram
    names the side to move, else None. lines comes from page_words."""
    r = pymupdf.Rect(rect)
    near = []
    for box, text in lines:
        cx = (box.x0 + box.x1) / 2
        if not r.x0 - 20 <= cx <= r.x1 + 20:
            continue
        if r.y0 - gap <= box.y1 <= r.y0 + 2 or r.y1 - 2 <= box.y0 <= r.y1 + gap:
            near.append((min(abs(box.y1 - r.y0), abs(box.y0 - r.y1)), text))
    for _, text in sorted(near):
        for rx, side in TURN_RE:
            if rx.search(text):
                return side
    return None


def printed_orientation(words, rect):
    """True when the coordinates printed round the picture show the board
    from Black's side, False when from White's, None when none are printed.
    words comes from page_words."""
    r = pymupdf.Rect(rect)
    files, ranks = [], []
    for box, t in words:
        t = t.strip()
        if len(t) != 1:
            continue
        cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
        if t in "abcdefgh" and r.x0 - 4 <= cx <= r.x1 + 4 and r.y1 - 6 <= box.y0 <= r.y1 + 18:
            files.append((cx, t))
        elif t in "12345678" and r.y0 - 4 <= cy <= r.y1 + 4 and (
                r.x0 - 18 <= box.x1 <= r.x0 + 6 or r.x1 - 6 <= box.x0 <= r.x1 + 18):
            ranks.append((cy, t))
    votes = 0
    for seq, normal_up in ((files, True), (ranks, False)):
        if len(seq) >= 2:
            vals = [t for _, t in sorted(seq)]
            up = sum(1 for a, b in zip(vals, vals[1:]) if b > a)
            down = sum(1 for a, b in zip(vals, vals[1:]) if b < a)
            if up != down:
                # files read a..h left to right, ranks 8..1 top to bottom
                votes += 1 if (up > down) == normal_up else -1
    if votes > 0:
        return False
    if votes < 0:
        return True
    return None


# ---------------------------------------------------------------- the book

LAST = {}      # the groups and names of the last book read, for inspection

def read_book_boards(pdf, diagrams, known=None, ids=None, progress=None):
    """Read every board picture of a book.

    pdf is the book's path (or an open pymupdf Document); diagrams is Stage
    1's list of records (pictures of stacked boards may be expanded already,
    as selection.expand_boards does). known maps diagram ids to FENs that the
    program believes (for instance positions that decoded lines reach at a
    diagram); they help to name the book's piece drawings. Returns
    {id: {"fen", "confidence", "doubtful": [squares], "status", "turn",
    "turn_from", "flipped"}}; status is "read", "doubtful", "partial" (no
    whole board in the picture) or "unread" (no position could be made)."""
    from . import selection as sel
    say = progress or (lambda *_: None)
    doc = pdf if isinstance(pdf, pymupdf.Document) else pymupdf.open(pdf)
    if any(d.get("boards") for d in diagrams):
        diagrams = sel.expand_boards(diagrams)
    ids = ids or sel.diagram_ids(diagrams)
    pics = Pictures(doc)
    known = known or {}
    out, boards = {}, []
    for did, rec in zip(ids, diagrams):
        try:
            g = pics.gray(rec)
        except (RuntimeError, ValueError):
            g = None
        r = board_cells(g)
        if r["grid"] is None:
            out[did] = {"fen": None, "confidence": 0.0, "doubtful": [], "status": "partial"}
            continue
        r["id"] = did
        r["rec"] = rec
        boards.append(r)
    say(f"board reading: {len(boards)} whole boards in {len(ids)} pictures")
    if not boards:
        return out
    # every drawing of the book, grouped
    keys, feats = [], []
    for bi, r in enumerate(boards):
        for sq, c in r["cells"].items():
            keys.append((bi, sq))
            feats.append(_feature(c["glyph"]))
    X = np.asarray(feats, np.float32) if feats else np.zeros((0, G * G), np.float32)
    lab, C = group_drawings(X) if len(X) else (np.zeros(0, int), np.zeros((0, G * G)))
    ngroups = len(C)
    members = defaultdict(list)
    for k, gi in enumerate(lab):
        members[gi].append(keys[k])
    areas = np.array([boards[b]["cells"][sq]["area"] for b, sq in keys]) if keys else np.zeros(0)
    typical = float(np.median(areas)) if len(areas) else 0.0
    groups = []
    for gi in range(ngroups):
        mem = members[gi]
        cells = [boards[b]["cells"][sq] for b, sq in mem]
        mask = np.mean([c["mask"] for c in cells], 0) > 0.5
        area = float(np.median([c["area"] for c in cells]))
        kind = "piece"
        ink = float(np.median([c["ink"] for c in cells]))
        if mask.sum() < 20 or area < 0.35 * typical or (area < SPECK * typical and ink < 0.1):
            # drawings much smaller than the book's pieces (specks, dots or
            # crosses on the board), or rather small and without dark ink
            # (the grain of the paper or of a grey square)
            kind = "mark"
        groups.append({"members": mem, "kind": kind, "area": area, "mask": mask,
                       "white_share": float(np.mean([c["white"] for c in cells])),
                       "ink": ink,
                       "height": float(np.median([c["height"] for c in cells])),
                       "shape": shape_scores(mask) if kind == "piece" else {},
                       "known": Counter()})
    pieces = [g for g in groups if g["kind"] == "piece"]
    if pieces:
        thr = _otsu_split([g["white_share"] for g in pieces], [len(g["members"]) for g in pieces])
    else:
        thr = 0.5
    for g in groups:
        w = g["white_share"]
        g["colours"] = "w" if w > thr + COLOUR_DOUBT else "b" if w < thr - COLOUR_DOUBT else "wb"
    # orientation from printed coordinates
    flip = {}
    texts = {}
    for bi, r in enumerate(boards):
        rec = r["rec"]
        if rec["page"] not in texts:
            texts[rec["page"]] = page_words(doc[rec["page"] - 1])
        o = printed_orientation(texts[rec["page"]][0], rec["rect"])
        r["coords"] = o
        if o:
            flip[bi] = True
    # positions known beforehand: given FENs, and printed initial positions
    group_of = {key: lab[k] for k, key in enumerate(keys)}
    for bi, r in enumerate(boards):
        fen = known.get(r["id"])
        occ = set(r["cells"])
        if fen is None and len(occ) == 32 and occ == {(i, j) for i in (0, 1, 6, 7) for j in range(8)}:
            fen = START
        if not fen:
            continue
        try:
            bd = chess.Board(fen.split()[0] + " w - - 0 1")
        except ValueError:
            continue
        for fl in (flip.get(bi, False), not flip.get(bi, False)):
            want = {(i, j) for i in range(8) for j in range(8) if bd.piece_at(_square(i, j, fl))}
            if len(want ^ occ) <= max(1, len(want) // 10):
                for sq in occ & want:
                    p = bd.piece_at(_square(sq[0], sq[1], fl))
                    groups[group_of[(bi, sq)]]["known"][p.symbol()] += 1
                if fl != flip.get(bi, False):
                    flip[bi] = fl
                break
    # a drawing seen once or twice, or a rare one unlike any piece, is named
    # after a frequent drawing close to it; one like no frequent drawing (a
    # printed square name, a number, an arrow) is not a piece
    big = [k for k, g in enumerate(groups) if g["kind"] == "piece" and len(g["members"]) >= 8]
    for k, g in enumerate(groups):
        n = len(g["members"])
        if g["kind"] != "piece" or n >= 8 or (n >= 3 and max(g["shape"].values()) >= 0.55):
            continue
        if big:
            d = np.sqrt(((C[big] - C[k]) ** 2).mean(1))
            j = int(np.argmin(d))
            a, b = g["mask"], groups[big[j]]["mask"]
            iou = (a & b).sum() / max((a | b).sum(), 1)
            if d[j] < 2 * GROUP_DIST and iou > 0.7:
                g["kind"], g["follow"] = "follow", big[j]
                continue
        g["kind"], g["unlike"] = "mark", True
    namer = Namer(groups)
    names, margins = namer.solve(flip)
    for k, g in enumerate(groups):
        if g["kind"] == "follow":
            names[k], margins[k] = names[g["follow"]], margins[g["follow"]]
    # boards shown from Black's side without printed coordinates: the pieces
    # stand far more plausibly the other way round
    _, _, prior = references()
    changed = False
    for bi, r in enumerate(boards):
        if r["coords"] is not None:
            continue
        ll = [0.0, 0.0]
        for sq in r["cells"]:
            g = group_of[(bi, sq)]
            if not names[g]:
                continue
            sym = names[g]
            for k, fl in enumerate((False, True)):
                ll[k] += float(np.log(prior[sym][_square(sq[0], sq[1], fl)]))
        want = ll[1] > ll[0] + 12.0
        if want != flip.get(bi, False):
            flip[bi] = want
            changed = True
    if changed:
        names, margins = namer.solve(flip)
    # how close each drawing is to its group, against the nearest group
    # that carries another name
    tag = [(g["kind"] != "mark", names[k]) for k, g in enumerate(groups)]
    same = np.array([[a == b for b in tag] for a in tag]) if tag else np.zeros((0, 0), bool)
    closeness = {}
    if len(X):
        d = np.sqrt(_sqdist(X, C) / X.shape[1])
        own = d[np.arange(len(X)), lab]
        d[same[lab]] = np.inf
        near = np.minimum(d.min(1), 1.0)
        c = np.clip((near - own) / np.maximum(near, 1e-6) * 2.5, 0, 1)
        closeness = {key: float(v) for key, v in zip(keys, c)}
    LAST.update(groups=groups, names=names, margins=margins, thr=thr, boards=boards,
                group_of=group_of, flip=flip)
    # the positions
    for bi, r in enumerate(boards):
        turn = caption_turn(texts[r["rec"]["page"]][1], r["rec"]["rect"])
        out[r["id"]] = _position(r, bi, groups, names, margins, group_of, closeness,
                                 flip.get(bi, False), turn, typical)
    say(f"board reading: {ngroups} groups of piece drawings, "
        f"{sum(1 for v in out.values() if v['status'] == 'read')} boards read")
    return out


def _position(r, bi, groups, names, margins, group_of, closeness, flipped, turn, typical):
    board = chess.Board(None)
    conf = {}
    for i in range(8):
        for j in range(8):
            sq = _square(i, j, flipped)
            name = chess.square_name(sq)
            cell = r["cells"].get((i, j))
            if cell is None:
                # an empty square is doubtful when something nearly counted
                conf[name] = 1.0 - 0.4 * min(1.0, r["areas"][i, j] / MIN_AREA)
                continue
            g = group_of[(bi, (i, j))]
            grp = groups[g]
            if grp["kind"] == "mark" or not names[g]:
                # a mark the book repeats (a dot, a cross) or a speck much
                # smaller than a piece leaves the square empty; a drawing
                # of a piece's size seen once leaves it in doubt
                small = cell["area"] < 0.4 * typical
                conf[name] = 0.9 if (len(grp["members"]) >= 5 and not grp.get("unlike")) or small else 0.4
                continue
            sym = names[g]
            board.set_piece_at(sq, chess.Piece.from_symbol(sym))
            c_draw = closeness[(bi, (i, j))]
            c_name = float(1 - np.exp(-max(margins[g], 0) / 3.0))
            c_occ = min(1.0, max(0.0, (cell["area"] - MIN_AREA) / MIN_AREA))
            conf[name] = min(c_draw, c_name, c_occ)
    board.turn = chess.BLACK if turn == "b" else chess.WHITE
    # castling where king and rook stand at home
    rights = ""
    for sym, k_sq, r_sq in (("K", "e1", "h1"), ("Q", "e1", "a1"), ("k", "e8", "h8"), ("q", "e8", "a8")):
        white = sym.isupper()
        kp = board.piece_at(chess.parse_square(k_sq))
        rp = board.piece_at(chess.parse_square(r_sq))
        if kp and rp and kp.symbol() == ("K" if white else "k") and rp.symbol() == ("R" if white else "r"):
            rights += sym
    board.set_castling_fen(rights or "-")
    kings = (len(board.pieces(chess.KING, chess.WHITE)), len(board.pieces(chess.KING, chess.BLACK)))
    doubtful = sorted((s for s, v in conf.items() if v < DOUBT),
                      key=lambda s: (8 - int(s[1]), s[0]))
    confidence = float(min(conf.values())) if conf else 0.0
    if kings != (1, 1):
        for color in (chess.WHITE, chess.BLACK):
            for sq in board.pieces(chess.KING, color):
                n = chess.square_name(sq)
                if n not in doubtful:
                    doubtful.append(n)
    status = "read" if not doubtful and kings == (1, 1) else "doubtful"
    return {"fen": board.fen(), "confidence": round(confidence, 3), "doubtful": doubtful,
            "status": status, "turn": "b" if board.turn == chess.BLACK else "w",
            "turn_from": "caption" if turn else "default", "flipped": bool(flipped),
            "coordinates": r["coords"] is not None,
            "squares": {k: round(v, 3) for k, v in conf.items()}}
