"""Reading a section of a page that the program missed.

The reader marks a section of a page (a rectangle in PDF points, as the
page's marks have them) where the book prints moves that the program found
in no line, and attaches the moves to a move of a line (corrections.py
"added", an entry with "page" and "rect"). The browser app's worker reads
the section for the reader first (web/driver.py words() and read_region());
the builder places a box on the page for each move it adds from a section
(assemble._Builder.add_variation).

words(doc, page, rect, near)  the words of the text layer in and near a
                              rectangle, with their boxes, in reading order
tokens(text, fen)             the text of a section as move tokens: a move
                              printed without its number takes the number
                              and side that follow from the moves before it,
                              or from the position for the first one
read(dec, fen, text)          the move sequences the text reads as, legal
                              from the position fen, best first
move_boxes(doc, page, rect, n)
                              the boxes of the n moves printed in the
                              section, or None when the section does not
                              hold n printed moves
"""
from __future__ import annotations

from dataclasses import replace

import chess

from .movetext import _move_like, _shape, tokenize

CANDIDATES = 5          # move sequences read() gives at most
ALTERNATIVES = 3        # other readings of one unsure move that read() tries
UNREAD_COST = 3.0       # the cost of a move of the text that a candidate leaves unread


def words(doc, page, rect, near=0.0):
    """The words of PDF page `page` (1-based) whose boxes meet the rectangle
    [x0, y0, x1, y1] grown by `near` points on every side: [{"text", "box",
    "inside"}], in the order of the text layer. "inside" says that the
    word's centre lies in the rectangle itself."""
    if not 1 <= page <= doc.page_count:
        return []
    x0, y0, x1, y1 = (float(v) for v in rect)
    gx0, gy0, gx1, gy1 = x0 - near, y0 - near, x1 + near, y1 + near
    out = []
    for w in doc[page - 1].get_text("words"):
        bx0, by0, bx1, by1, text = w[0], w[1], w[2], w[3], w[4]
        if bx1 < gx0 or bx0 > gx1 or by1 < gy0 or by0 > gy1 or not text.strip():
            continue
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        out.append(((w[5], w[6], w[7]), {
            "text": text, "box": [round(bx0, 1), round(by0, 1), round(bx1, 1), round(by1, 1)],
            "inside": x0 <= cx <= x1 and y0 <= cy <= y1}))
    out.sort(key=lambda x: x[0])
    return [w for _, w in out]


def section_text(doc, page, rect):
    """The text printed in the section: its words in reading order."""
    return " ".join(w["text"] for w in words(doc, page, rect) if w["inside"])


def tokens(text, fen=None):
    """The tokens of a section's text. A word that reads as a move but stands
    without a move number before it (the program finds runs of moves by
    their numbers, so a section it missed often has none) becomes a move,
    numbered after the move before it, or from the position fen when it is
    the first move of the section."""
    board = chess.Board(fen) if fen else None
    out, prev = [], None
    for t in tokenize(text):
        if t.kind == "other" and (_shape(t.raw) or _move_like(t.raw)):
            if prev is not None:
                number = prev.number + 1 if (prev.black and prev.number is not None) else prev.number
                t = replace(t, kind="move", number=number, black=not prev.black)
            elif board is not None:
                t = replace(t, kind="move", number=board.fullmove_number,
                            black=board.turn == chess.BLACK)
            else:
                t = replace(t, kind="move")
        if t.kind == "move":
            prev = t
        out.append(t)
    return out


def _cost(decs, total):
    """The cost of a candidate: the costs of its moves, and a share for every
    move of the text that it leaves unread."""
    return sum(d[2] for d in decs) + UNREAD_COST * (total - len(decs))


def _readable(decs):
    """The leading moves of a decoding that read as moves: [(SAN, UCI, cost,
    status)]. A move read against what the text prints (a piece glyph or a
    capture mark that the reading drops: "Qe4" read as the pawn move e4)
    counts as unsure ("lost"), whatever its cost: the printed move is most
    likely another one, of the other side or from another position."""
    out = []
    for d in decs:
        if not d.san:
            break
        lost = d.glyph_lost or (d.capture_mark and "x" not in d.san)
        out.append((d.san, d.uci, d.cost, "lost" if lost and d.status == "ok" else d.status))
    return out


def read(dec, fen, text):
    """The move sequences that the section's text reads as from the position
    fen, with the book's own decoder (assemble._Decoder: its glyph model and
    letters, and the piece symbols the reader named): [{"san": [...],
    "cost", "unsure"}], best first. "unsure" counts the moves read with
    doubt, among them a move that drops a piece glyph or a capture mark that
    the text prints. The best reading comes first; then, for each move that
    the decoder was unsure of, the reading with another of its candidates
    there and the moves after it read again. A sequence holds the moves
    while they are legal, so a later move that reads as nothing ends it."""
    toks = tokens(text, fen)
    at = [k for k, t in enumerate(toks) if t.kind == "move"]     # the token of each move
    if not at:
        return []
    total = len(at)
    decs = dec.run(fen, toks)
    best = _readable(decs)
    found = [best] if best else []
    # the other readings of the moves the decoder was unsure of (and of the
    # first move it could not read, the move it assumed there)
    board = chess.Board(fen)
    for i, d in enumerate(decs[:len(best) + 1]):
        for alt in [a for a in (d.alternatives or []) if a != d.san][:ALTERNATIVES]:
            b2 = board.copy(stack=False)
            try:
                m = b2.parse_san(alt)
            except ValueError:
                continue
            san = b2.san(m)
            b2.push(m)
            rest = toks[at[i] + 1:]
            found.append(best[:i] + [(san, m.uci(), 1.0, "guessed")] +
                         (_readable(dec.run(b2.fen(), rest)) if rest else []))
        if i >= len(best):
            break
        board.push_uci(best[i][1])
    out, keys = [], set()
    # (the readings with fewer unsure moves first, then the longer, then the cheaper)
    for c in sorted(found, key=lambda c: (sum(1 for x in c if x[3] == "lost"), -len(c), _cost(c, total))):
        key = tuple(x[0] for x in c)
        if key in keys:
            continue
        keys.add(key)
        out.append({"san": list(key), "cost": round(_cost(c, total), 2),
                    "unsure": sum(1 for x in c if x[3] != "ok")})
        if len(out) >= CANDIDATES:
            break
    return out


def move_words(doc, page, rect):
    """The words of the section that hold one printed move each, in reading
    order: [{"text", "box"}]. A move number printed on its own is no move."""
    out = []
    for w in words(doc, page, rect):
        if not w["inside"]:
            continue
        if sum(1 for t in tokens(w["text"]) if t.kind == "move") == 1:
            out.append(w)
    return out


def move_boxes(doc, page, rect, n):
    """The boxes of the n moves that the reader read in a section, one per
    printed move in reading order, when the section prints n moves; None
    otherwise (the section's own box then stands for its moves)."""
    if doc is None or n <= 0:
        return None
    try:
        found = move_words(doc, page, rect)
    except Exception:           # a page the document cannot give: the section's box serves
        return None
    if len(found) != n:
        return None
    return [w["box"] for w in found]
