"""Read the piece figurines printed in the moves of a book by their shape.

A scanned book prints its moves with piece figurines, and the text
recognition turns each figurine into junk ("i>", "tLl", "\\x14"). The move
decoder learns from the book which junk stands for which piece
(movetext.GlyphModel), but junk seen rarely, or junk that stands for two
pieces, leaves the piece to legal play alone. The picture of the figurine on
the page says which piece it is. This module reads those pictures, the way
boards.py reads the pieces of diagrams: nobody labels anything by hand for a
book.

How the figurines are read
--------------------------
1. Where. The assembler notes, for every move token whose piece symbol is
   junk (movetext.junk_prefix), where the symbol's characters stand on the
   page (a "spot": page, box, symbol). Tokens whose piece is a letter of the
   notation or a figurine character are left alone, and so is a book whose
   moves print junk symbols seldom (fewer than MIN_SPOTS, or fewer than
   MIN_SHARE of its move tokens): its text already names the pieces.
2. Cut out. The page is drawn as it is displayed (the redrawn type of a
   ClearScan page, the picture of a scanned page), one text line at a time,
   in grey at about 200 dpi, and only where spots stand. The ink of the
   line is separated from the paper (Otsu), and the spot's figurine is the
   ink whose parts have their centre inside the symbol's box. It is cut
   tightly, scaled to fit S x S pixels with its proportions kept, and
   blurred a little. A cut that is much smaller than the type (a dot, a
   comma) is no figurine and is dropped.
3. Group. A book prints each figurine the same way every time, so the cuts
   of the whole book fall into groups of nearly identical pictures
   (boards.group_drawings): about five per style of figurine (a book may
   have white and black figurines, or a bold style in its headings), and
   some small groups of bad cuts.
4. Name. The moves that the decoder reads with certainty name the groups:
   a move read as the only reading of its token, whose destination only one
   kind of piece can reach in that position, votes for its piece in its
   cut's group. Such a move can still be read wrongly (a line read from the
   wrong position), so each vote counts as odds of VOTE_ODDS for its piece:
   two votes of two name a group with confidence 0.8, eleven against three
   with nearly 1. The votes of groups that look alike count for each other,
   the more the more alike they are (the figurines of different pieces stand
   far apart, the cuts of one piece close together). The reference
   figurines (assets/figurines.npz, cut from other books by
   tools/make_figurine_refs.py) count as a few votes for the piece of the
   nearest of them, so that they name the groups of a book whose own moves
   name none; such a name never reaches CONFIDENT.
5. Use. Each move token whose cut is named with confidence USE_MIN or
   more carries the piece and confidence (Token.shape), and the decoder
   charges a reading of another piece about as much as a symbol it cannot
   read at all, so that legal play can still overrule a bad cut. A symbol
   named with confidence CONFIDENT or more gets no eye in the reader. The
   figurines are cut out after the first pass of the assembly and named
   again after each later pass but the last, whose certain moves are more
   (assemble.read_shapes_steps).

numpy and OpenCV are needed (as for boards.py); without them the assembler
reads the book as before.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import chess
import cv2
import numpy as np
import pymupdf

from .boards import group_drawings, _sqdist
from .movetext import SHAPE_KNOWN

ASSETS = Path(__file__).resolve().parent / "assets"
PIECES = "KQRBN"
ZOOM = 200 / 72         # pages are drawn at about 200 dpi
S = 24                  # pixels per side of a normalised cut
BLUR = 0.8              # sigma of the blur of a normalised cut
GROUP_DIST = 0.12       # RMS difference within one group of cuts
POOL = 0.1              # RMS difference at which the votes of another group count e^-1 times
REF_VOTES = 3.0         # votes that a reference figurine at no distance counts as
REF_DIST = 0.15         # RMS difference at which a reference counts e^-1 times as much
REF_MAX = 0.75          # most confidence of a name that the references alone give
MIN_SPOTS = 40          # junk symbols a book must print before its figurines are read
MIN_SHARE = 0.05        # ... and their least share of the book's move tokens
VOTE_ODDS = 4.0         # a vote names the right piece this many times as often as one wrong piece
CONFIDENT = SHAPE_KNOWN # named this surely, a symbol gets no eye
USE_MIN = 0.5           # less surely named cuts are not given to the decoder
SMALL = 0.3             # cuts lower than this share of the type's height are no figurines
BATCH_PAGES = 12        # pages cut per step of cut_steps


# ---------------------------------------------------------------- where

def worth_reading(spots, move_tokens):
    """True when a book prints junk symbols often enough for their shapes to
    be read (see MIN_SPOTS and MIN_SHARE)."""
    return len(spots) >= MIN_SPOTS and len(spots) >= MIN_SHARE * max(move_tokens, 1)


# ---------------------------------------------------------------- cut out

def _gray(pix):
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.stride)[:, :pix.w]
    return a.copy()


def _otsu(g):
    """Otsu's threshold of a grey array, or None when it holds no clear ink."""
    if int(g.max()) - int(g.min()) < 60:
        return None
    t, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return min(max(t, 60), 200)


def normalise(mask):
    """A cut (True for ink) scaled to fit S x S with its proportions kept,
    centred and blurred, as a vector of S * S values in 0..1."""
    h, w = mask.shape
    k = (S - 2) / max(h, w)
    nh, nw = max(1, round(h * k)), max(1, round(w * k))
    small = cv2.resize(mask.astype(np.float32), (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((S, S), np.float32)
    y, x = (S - nh) // 2, (S - nw) // 2
    out[y:y + nh, x:x + nw] = small
    return cv2.GaussianBlur(out, (0, 0), BLUR).ravel()


def _lines(items):
    """The spots of one page in rows of print: [(spot box, key)] grouped by
    the height of their centres."""
    rows = []
    for key, box in sorted(items, key=lambda t: (t[1][1] + t[1][3]) / 2):
        yc, h = (box[1] + box[3]) / 2, box[3] - box[1]
        if rows and abs(yc - rows[-1]["yc"]) < 0.4 * max(h, rows[-1]["h"]):
            rows[-1]["items"].append((key, box))
        else:
            rows.append({"yc": yc, "h": h, "items": [(key, box)]})
    return [r["items"] for r in rows]


def cut_line(source, items, page_rect):
    """{key: ink mask} for the spots of one row of print. source draws the
    page (a pymupdf Page or DisplayList); items are [(key, box)]."""
    h = float(np.median([b[3] - b[1] for _, b in items]))
    if h <= 0:
        return {}
    clip = pymupdf.Rect(min(b[0] for _, b in items) - 0.4 * h, min(b[1] for _, b in items) - 0.35 * h,
                        max(b[2] for _, b in items) + 0.4 * h, max(b[3] for _, b in items) + 0.35 * h)
    clip &= page_rect
    if clip.is_empty or clip.width < 2 or clip.height < 2:
        return {}
    pix = source.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), colorspace=pymupdf.csGRAY,
                            alpha=False, clip=clip)
    g = _gray(pix)
    thr = _otsu(g)
    if thr is None:
        return {}
    ink = (g < thr).astype(np.uint8)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(ink, connectivity=8)
    hp = h * ZOOM
    out = {}
    for key, box in items:
        x0, x1 = (box[0] - clip.x0) * ZOOM, (box[2] - clip.x0) * ZOOM
        y0, y1 = (box[1] - clip.y0) * ZOOM, (box[3] - clip.y0) * ZOOM
        keep = [j for j in range(1, n)
                if x0 <= cent[j][0] <= x1 and y0 - 0.1 * hp <= cent[j][1] <= y1 + 0.1 * hp
                and stats[j][cv2.CC_STAT_HEIGHT] < 2 * hp and stats[j][cv2.CC_STAT_WIDTH] < 3 * hp]
        if not keep:
            continue
        # the figurine is the largest part and what stands over it: a dot,
        # a capture mark or a letter beside it that the symbol's box holds
        # too is left out
        big = max(keep, key=lambda j: stats[j][cv2.CC_STAT_WIDTH] * stats[j][cv2.CC_STAT_HEIGHT])
        lo, hi = stats[big][0], stats[big][0] + stats[big][2]
        slack = 0.1 * (hi - lo)
        keep = [j for j in keep if lo - slack <= cent[j][0] <= hi + slack]
        a = max(0, int(min(stats[j][0] for j in keep)), int(x0 - 0.15 * hp))
        b = min(ink.shape[1], int(max(stats[j][0] + stats[j][2] for j in keep)), int(x1 + 0.05 * hp) + 1)
        c = int(min(stats[j][1] for j in keep))
        d = int(max(stats[j][1] + stats[j][3] for j in keep))
        if b <= a or d <= c:
            continue
        mask = np.isin(lab[c:d, a:b], keep)
        ys, xs = np.nonzero(mask)
        if not len(ys):
            continue
        mask = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        if mask.shape[0] < SMALL * hp or max(mask.shape) < 0.35 * hp:
            continue
        out[key] = mask
    return out


def cut_steps(doc, spots, batch=BATCH_PAGES):
    """Cut out the figurines of spots ({key: (page, box, symbol)}): a
    generator that yields ("shapes", (pages done, pages)) after every batch
    of pages and returns {key: ink mask}."""
    by_page = defaultdict(list)
    for key, (page, box, _) in spots.items():
        if page is not None and box is not None:
            by_page[page].append((key, box))
    pages = sorted(by_page)
    out = {}
    for k, p in enumerate(pages):
        page = doc[p - 1]
        try:
            source = page.get_displaylist()
        except (RuntimeError, ValueError):
            source = page
        for items in _lines(by_page[p]):
            try:
                out.update(cut_line(source, items, page.rect))
            except (RuntimeError, ValueError):
                continue
        if (k + 1) % batch == 0 and k + 1 < len(pages):
            yield "shapes", (k + 1, len(pages))
    return out


# ---------------------------------------------------------------- votes

def certain_piece(fen, uci):
    """The piece letter of a move when no other kind of piece can reach its
    destination in the position (fen, before the move); None otherwise."""
    try:
        b = chess.Board(fen)
        m = chess.Move.from_uci(uci)
    except ValueError:
        return None
    pt = b.piece_type_at(m.from_square)
    if pt is None or pt == chess.PAWN:
        return None
    kinds = {b.piece_type_at(x.from_square) for x in b.legal_moves
             if x.to_square == m.to_square} - {chess.PAWN}
    if kinds != {pt}:
        return None
    return chess.piece_symbol(pt).upper()


def votes_from_nodes(keys, nodes, node_by_key):
    """{key: piece} for the spots whose move the assembly read with
    certainty: status "ok" and a destination that only one kind of piece
    can reach."""
    out = {}
    for key in keys:
        nid = node_by_key.get(key)
        n = nodes.get(nid) if nid is not None else None
        if not n or n.get("status") != "ok" or not n.get("uci") or n.get("parent") is None:
            continue
        parent = nodes.get(n["parent"])
        if not parent or not parent.get("fen"):
            continue
        piece = certain_piece(parent["fen"], n["uci"])
        if piece:
            out[key] = piece
    return out


# ---------------------------------------------------------------- references

_REFS = None


def references():
    """(vectors (n, S * S), piece letters [n]) of the reference figurines
    in assets/figurines.npz; empty when the file is missing."""
    global _REFS
    if _REFS is None:
        path = ASSETS / "figurines.npz"
        if path.exists():
            z = np.load(path)
            X = z["shapes"].astype(np.float32).reshape(len(z["shapes"]), -1) / 255.0
            _REFS = (X, [str(p) for p in z["pieces"]])
        else:
            _REFS = (np.zeros((0, S * S), np.float32), [])
    return _REFS


def _rms(X, C):
    return np.sqrt(_sqdist(X, C) / X.shape[1])


# ---------------------------------------------------------------- the reading

class Shapes:
    """The figurines of one book: cuts, groups and names.

    masks maps a spot key to its ink mask. name(votes) names the groups;
    then reading() gives {key: (piece, confidence)} for every named cut,
    and groups lists the groups (for inspection and the reference tool)."""

    def __init__(self, masks, refs=None):
        self.keys = sorted(masks)
        self.masks = masks
        self.X = np.array([normalise(masks[k]) for k in self.keys], np.float32).reshape(-1, S * S)
        self.refs = references() if refs is None else refs
        if len(self.keys):
            self.labels, self.centres = group_drawings(self.X, GROUP_DIST)
        else:
            self.labels, self.centres = np.zeros(0, int), np.zeros((0, S * S), np.float32)
        self.groups = []
        self.by_key = {}

    def name(self, votes):
        """Name the groups from votes ({key: piece letter})."""
        groups, V = [], np.zeros((len(self.centres), len(PIECES)))
        for g in range(len(self.centres)):
            members = [self.keys[i] for i in np.nonzero(self.labels == g)[0]]
            v = Counter(votes[k] for k in members if k in votes)
            for p, n in v.items():
                V[g, PIECES.index(p)] = n
            groups.append({"index": g, "members": members, "votes": dict(v), "piece": None,
                           "confidence": 0.0, "how": None})
        if len(groups):
            # the votes of groups that look alike (one figurine cut a little
            # differently, or printed by another scan) count for each other
            W = np.exp(-(_rms(self.centres, self.centres) / POOL) ** 2)
            P = W @ V
            # the reference figurines count as a few votes for the piece of
            # the nearest of them, the fewer the farther it is
            R, rp = self.refs
            Q = np.zeros_like(P)
            if len(rp):
                D = _rms(self.centres, R)
                for j, p in enumerate(PIECES):
                    cols = [i for i, q in enumerate(rp) if q == p]
                    if cols:
                        Q[:, j] = REF_VOTES * np.exp(-(D[:, cols].min(1) / REF_DIST) ** 2)
            for x, pv, qv in zip(groups, P, Q):
                tv = pv + qv
                if tv.max() < 0.5:
                    continue
                # a certain move can still be read wrongly (a line read from
                # the wrong position), so each vote counts as odds of
                # VOTE_ODDS for its piece: two votes of two give 0.8, one
                # 0.5, eleven against three nearly 1
                w = VOTE_ODDS ** (tv - tv.max())
                j = int(np.argmax(w))
                conf = min(float(w[j] / w.sum()), 0.99)
                if pv.sum() < 0.5:
                    conf = min(conf, REF_MAX)       # the book's own moves never named it
                how = "votes" if x["votes"] else "near" if pv.sum() >= qv.sum() else "reference"
                x.update(piece=PIECES[j], confidence=conf, how=how)
        self.groups = groups
        self.by_key = {}
        for x in groups:
            if x["piece"]:
                for k in x["members"]:
                    self.by_key[k] = (x["piece"], round(float(x["confidence"]), 3))
        return self

    def reading(self, least=USE_MIN):
        """{key: (piece, confidence)} of the cuts named at least this surely."""
        return {k: v for k, v in self.by_key.items() if v[1] >= least}

    def summary(self):
        """[(piece, confidence, how, members, votes)] of the groups, largest first."""
        rows = [(x["piece"], round(float(x["confidence"]), 2), x["how"], len(x["members"]), x["votes"])
                for x in self.groups]
        return sorted(rows, key=lambda r: -r[3])
