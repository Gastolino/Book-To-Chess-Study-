"""Chess diagrams printed as text in a chess diagram font.

Many PDFs exported from ChessBase, Fritz or a word processor draw each
diagram as eight lines of text in a chess font: every character (or pair of
characters) is one square. The text layer then holds the position itself,
for example (ChessBase "DiagramTT" fonts):

    XIIIIIIIIY
    8-+rwqk+-tr0
    7+p+lvlp+-0
    ...
    1tR-+-+R+K0
    xabcdefghy

find_text_diagrams(lines) finds such diagrams among the text lines of a page
and decodes each into a FEN. Nothing here depends on a font name: each known
character convention (ENCODINGS) is tried on every group of eight stacked
lines, and a reading is kept only when it gives eight ranks of eight squares,
one king of each colour, no pawn on the first or last rank and, where the
convention tells light from dark squares, the right square colours.

The conventions:

    chessbase   ChessBase / Fritz "DiagramTT" fonts. "-" empty light square,
                "+" empty dark square; a piece on a light square is one letter
                (upper case White, lower case Black: P N B/L R Q K), a piece
                on a dark square is a mark (z s v t w m) followed by the letter.
    marroquin   The Marroquin keyboard map used by Chess Merida, Chess Alpha,
                Chess Leipzig, Chess Cases, Chess Linares and most other
                diagram fonts: White p n b r q k on light squares and
                P N B R Q K on dark squares, Black o m v t w l on light squares
                and O M V T W L on dark squares, " " or "*" an empty light
                square and "+" an empty dark square.
    unicode     Unicode chess symbols, with ".", "·", "-", "_", "+", "□", "■"
                and the like for empty squares.
    letters     FEN letters (upper case White) with ".", "-" or "_" for empty
                squares, optionally separated by single spaces.

Side to move is not printed in the diagram; side_to_move() reads it from the
text around it (see there).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import chess

# ---------------------------------------------------------------- encodings

_PIECE = {"p": "p", "n": "n", "b": "b", "l": "b", "r": "r", "q": "q", "k": "k"}
_CB_DARK = set("zsvtwm")
_MAR_WHITE_LIGHT = dict(zip("pnbrqk", "PNBRQK"))
_MAR_WHITE_DARK = dict(zip("PNBRQK", "PNBRQK"))
_MAR_BLACK_LIGHT = dict(zip("omvtwl", "pnbrqk"))
_MAR_BLACK_DARK = dict(zip("OMVTWL", "pnbrqk"))
_UNI_PIECES = dict(zip("♔♕♖♗♘♙♚♛♜♝♞♟", "KQRBNPkqrbnp"))
_UNI_EMPTY = set(".·-_+□■▢▣⬜⬛◻◼ ")
_LETTER_EMPTY = set(".-_")


def _fen_letter(c):
    """FEN letter of a piece letter whose case gives the colour."""
    p = _PIECE.get(c.lower())
    if p is None:
        return None
    return p.upper() if c.isupper() else p


def _tok_chessbase(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "-":
            out.append(("", "l"))
        elif c == "+":
            out.append(("", "d"))
        elif c in _CB_DARK and i + 1 < len(s) and _fen_letter(s[i + 1]):
            out.append((_fen_letter(s[i + 1]), "d"))
            i += 1
        elif _fen_letter(c):
            out.append((_fen_letter(c), "l"))
        else:
            return None
        i += 1
    return out


def _tok_marroquin(s):
    out = []
    for c in s:
        if c in " *":
            out.append(("", "l"))
        elif c == "+":
            out.append(("", "d"))
        elif c in _MAR_WHITE_LIGHT:
            out.append((_MAR_WHITE_LIGHT[c], "l"))
        elif c in _MAR_WHITE_DARK:
            out.append((_MAR_WHITE_DARK[c], "d"))
        elif c in _MAR_BLACK_LIGHT:
            out.append((_MAR_BLACK_LIGHT[c], "l"))
        elif c in _MAR_BLACK_DARK:
            out.append((_MAR_BLACK_DARK[c], "d"))
        else:
            return None
    return out


def _spaced(s):
    """'r n b q' -> 'rnbq' when single spaces separate every character."""
    if len(s) >= 3 and all(s[i] == " " for i in range(1, len(s), 2)):
        return s[::2]
    return s


def _tok_unicode(s):
    s = _spaced(s)
    out = []
    for c in s:
        if c in _UNI_PIECES:
            out.append((_UNI_PIECES[c], None))
        elif c in _UNI_EMPTY:
            out.append(("", None))
        else:
            return None
    return out


def _tok_letters(s):
    s = _spaced(s)
    out = []
    for c in s:
        if c in _LETTER_EMPTY:
            out.append(("", None))
        elif c in "pnbrqkPNBRQK":
            out.append((c, None))
        else:
            return None
    return out


# Order matters only between readings that score the same.
ENCODINGS = (("chessbase", _tok_chessbase), ("marroquin", _tok_marroquin),
             ("unicode", _tok_unicode), ("letters", _tok_letters))
_COLOURED = {"chessbase", "marroquin"}
_RANK_DIGITS = "12345678"


@dataclass
class _Rank:
    squares: list
    number: int | None          # the rank number printed beside it, if any


def parse_rank(text, encoding):
    """Read one printed rank in an encoding: _Rank or None. Up to two frame
    characters (border, rank number) on each side are dropped."""
    tok = dict(ENCODINGS)[encoding]
    s = text.strip()
    if not s or len(s) > 40:
        return None
    best = None
    for a in range(0, 3):
        for b in range(0, 3):
            if a + b >= len(s):
                continue
            core = s[a:len(s) - b]
            sq = tok(core)
            if sq is None or len(sq) != 8:
                continue
            cost = a + b
            if best is None or cost < best[0]:
                num = next((int(c) for c in s[:a] if c in _RANK_DIGITS), None)
                best = (cost, _Rank(sq, num))
    return best[1] if best else None


# ---------------------------------------------------------------- diagrams

@dataclass
class TextDiagram:
    rect: tuple                 # (x0, y0, x1, y1) around the ranks and the frame
    placement: str              # FEN piece placement, White at the bottom
    encoding: str
    lines: list = field(default_factory=list)   # indices of the input lines it covers
    flipped: bool = False       # printed with Black at the bottom


def _rect(r):
    return tuple(float(v) for v in (r[0], r[1], r[2], r[3]))


def _x_overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    return w / max(1e-6, min(a[2] - a[0], b[2] - b[0]))


def _placement(ranks, flipped):
    rows = []
    for r in ranks:                 # top to bottom
        sq = r.squares[::-1] if flipped else r.squares
        rows.append(sq)
    if flipped:
        rows = rows[::-1]
    out = []
    for sq in rows:
        s, gap = "", 0
        for p, _ in sq:
            if p:
                if gap:
                    s += str(gap)
                    gap = 0
                s += p
            else:
                gap += 1
        out.append(s + (str(gap) if gap else ""))
    return "/".join(out)


def _colour_errors(ranks, flipped):
    """Squares printed in the wrong colour (a1 is dark)."""
    bad = 0
    for i, r in enumerate(ranks):
        rank = (i if flipped else 7 - i)
        for j, (_, c) in enumerate(r.squares):
            if c is None:
                continue
            f = 7 - j if flipped else j
            dark = (f + rank) % 2 == 0
            bad += (c == "d") != dark
    return bad


def valid_placement(placement):
    """One king of each colour and no pawn on the first or last rank."""
    try:
        b = chess.Board(placement + " w - - 0 1")
    except ValueError:
        return False
    if len(b.pieces(chess.KING, chess.WHITE)) != 1 or len(b.pieces(chess.KING, chess.BLACK)) != 1:
        return False
    if b.pieces(chess.PAWN, chess.WHITE) & (chess.BB_RANK_1 | chess.BB_RANK_8):
        return False
    if b.pieces(chess.PAWN, chess.BLACK) & (chess.BB_RANK_1 | chess.BB_RANK_8):
        return False
    return True


def _chains(lines, parsed):
    """Runs of parsed lines stacked one under the next, top to bottom."""
    idx = sorted((k for k in range(len(lines)) if parsed[k] is not None),
                 key=lambda k: lines[k][1][1])
    used, chains = set(), []
    for k in idx:
        if k in used:
            continue
        chain = [k]
        used.add(k)
        while True:
            a = lines[chain[-1]][1]
            h = a[3] - a[1]
            nxt = None
            for j in idx:
                if j in used:
                    continue
                b = lines[j][1]
                gap = b[1] - a[1]
                if 0.3 * h < gap < 1.6 * h and _x_overlap(a, b) > 0.6:
                    if nxt is None or b[1] < lines[nxt][1][1]:
                        nxt = j
            if nxt is None:
                break
            chain.append(nxt)
            used.add(nxt)
        chains.append(chain)
    return chains


def _frame_line(lines, k, ref, above):
    """A short border or file-letter line right above or below a rank."""
    t, r = lines[k]
    s = t.strip()
    if not s or len(s) > 14 or " " in s:
        return False
    h = ref[3] - ref[1]
    gap = (ref[1] - r[1]) if above else (r[1] - ref[1])
    return 0.3 * h < gap < 1.6 * h and _x_overlap(ref, r) > 0.6


def find_text_diagrams(lines):
    """Text diagrams among a page's lines.

    lines: [(text, rect)] with rect (x0, y0, x1, y1) in page coordinates, one
    entry per printed line. Returns [TextDiagram] in top-to-bottom order.
    """
    lines = [(t or "", _rect(r)) for t, r in lines]
    # A cheap test first: most pages hold no line that could be a rank.
    if sum(1 for t, _ in lines if 8 <= len(t.strip()) <= 40) < 8:
        return []
    found = []
    for name, _ in ENCODINGS:
        parsed = [parse_rank(t, name) for t, _ in lines]
        if sum(p is not None for p in parsed) < 8:
            continue
        for chain in _chains(lines, parsed):
            for s in range(0, len(chain) - 7):
                win = chain[s:s + 8]
                ranks = [parsed[k] for k in win]
                # digits beside the ranks are rank numbers only when they
                # count 8 to 1 or 1 to 8 (a frame may use a digit as border)
                nums = [r.number for r in ranks]
                files_line = None
                flipped = nums == [1, 2, 3, 4, 5, 6, 7, 8]
                # file letters under the board tell the orientation too
                below = [j for j in range(len(lines)) if j not in win
                         and _frame_line(lines, j, lines[win[-1]][1], False)]
                if below:
                    files_line = lines[below[0]][0]
                    if "hgfedcba" in files_line.replace(" ", ""):
                        flipped = True
                placement = _placement(ranks, flipped)
                if not valid_placement(placement):
                    continue
                errors = _colour_errors(ranks, flipped) if name in _COLOURED else 0
                if errors > 2:
                    continue
                above = [j for j in range(len(lines)) if j not in win
                         and _frame_line(lines, j, lines[win[0]][1], True)]
                members = sorted(set(win) | set(above[:1]) | set(below[:1]))
                x0 = min(lines[k][1][0] for k in members)
                y0 = min(lines[k][1][1] for k in members)
                x1 = max(lines[k][1][2] for k in members)
                y1 = max(lines[k][1][3] for k in members)
                score = (-errors, name in _COLOURED)
                found.append((score, TextDiagram((x0, y0, x1, y1), placement, name, members,
                                                 flipped)))
    # Keep the best reading of each block of lines.
    found.sort(key=lambda t: t[0], reverse=True)
    out, taken = [], set()
    for _, d in found:
        if taken & set(d.lines):
            continue
        taken |= set(d.lines)
        out.append(d)
    out.sort(key=lambda d: d.rect[1])
    return out


# ---------------------------------------------------------------- side to move

_TO_MOVE_RE = re.compile(r"\b(White|Black)\s+to\s+(?:move|play)\b")
_NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3})\s?(\.\.\.|…|\.)(?![\d.])")
_SAN_RE = re.compile(r"^(?:[KQRBN♔-♟]?[a-h]?[1-8]?[x:]?[a-h][1-8](?:=?[QRBN])?|[O0]-[O0](?:-[O0])?)"
                     r"[+#!?]*$")


def _numbered_moves(text):
    """[(number, black, [move tokens after the number])] in text order."""
    out = []
    ms = list(_NUMBER_RE.finditer(text))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        toks = []
        for t in text[m.end():end].split():
            t = t.strip(",;()[]")
            if _SAN_RE.match(t):
                toks.append(t)
            else:
                break
        if toks:
            out.append((int(m.group(1)), m.group(2) != ".", toks, m.start()))
    return out


def side_to_move(placement, before="", after=""):
    """(turn, fullmove number) of a diagram, read from the text around it.

    In order of trust: a king in check must move; "White to move" or
    "Black to play" just under or over the diagram; the move printed last
    before the diagram ("15.b4" leaves Black to move); the first numbered
    move after the diagram ("15...a5" is Black's move). Without any of these
    White is to move.
    """
    b = chess.Board(placement + " w - - 0 1")
    wk, bk = b.king(chess.WHITE), b.king(chess.BLACK)
    w_check = wk is not None and b.is_attacked_by(chess.BLACK, wk)
    b_check = bk is not None and b.is_attacked_by(chess.WHITE, bk)
    number = None
    tail = before[-400:]
    lead = after[:300]
    last = _numbered_moves(tail)
    nxt = _numbered_moves(lead)
    end_tok = re.sub(r"^\d{1,3}\s?(?:\.\.\.|…|\.)", "", (tail.split() or [""])[-1].strip(",;()[]"))
    if last and _SAN_RE.match(end_tok):
        n, black, toks, _ = last[-1]
        plies = len(toks[:1 if black else 2])
        ply = (n - 1) * 2 + int(black) + plies     # ply index of the next move
        number = ply // 2 + 1
        turn_from_text = chess.BLACK if ply % 2 else chess.WHITE
    elif nxt:
        n, black, _, _ = nxt[0]
        number = n
        turn_from_text = chess.BLACK if black else chess.WHITE
    else:
        turn_from_text = None
    m = _TO_MOVE_RE.search(lead[:120]) or _TO_MOVE_RE.search(before[-120:])
    if w_check != b_check:
        turn = chess.WHITE if w_check else chess.BLACK
    elif m:
        turn = chess.WHITE if m.group(1) == "White" else chess.BLACK
    elif turn_from_text is not None:
        turn = turn_from_text
    else:
        turn = chess.WHITE
    return turn, number or 1


def castling_rights(placement):
    """Castling rights where king and rook stand on their home squares."""
    b = chess.Board(placement + " w - - 0 1")
    out = ""
    for colour, rank, sym in ((chess.WHITE, 0, "KQ"), (chess.BLACK, 7, "kq")):
        if b.piece_at(chess.square(4, rank)) != chess.Piece(chess.KING, colour):
            continue
        if b.piece_at(chess.square(7, rank)) == chess.Piece(chess.ROOK, colour):
            out += sym[0]
        if b.piece_at(chess.square(0, rank)) == chess.Piece(chess.ROOK, colour):
            out += sym[1]
    return out or "-"


def full_fen(placement, before="", after=""):
    """A whole FEN for a diagram: side to move and move number from the text
    around it, castling rights from the kings and rooks on their home squares."""
    turn, number = side_to_move(placement, before, after)
    fen = f"{placement} {'w' if turn == chess.WHITE else 'b'} {castling_rights(placement)} - 0 {number}"
    try:
        chess.Board(fen)
    except ValueError:
        fen = f"{placement} {'w' if turn == chess.WHITE else 'b'} - - 0 {number}"
    return fen


def ink_rect(page, rect, margin=1.0):
    """The part of rect on a pymupdf page that holds ink: the printed board
    without the empty space that frame characters' advance widths add."""
    import pymupdf
    r = pymupdf.Rect(rect) & page.rect
    if r.is_empty:
        return tuple(rect)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=r, colorspace=pymupdf.csGRAY,
                          alpha=False)
    data = pix.samples
    w, h = pix.width, pix.height
    rows = [y for y in range(h) if min(data[y * w:(y + 1) * w]) < 160]
    if not rows:
        return tuple(rect)
    cols = [x for x in range(w) if min(data[x::w][:h]) < 160]
    x0, x1 = r.x0 + cols[0] / 2 - margin, r.x0 + (cols[-1] + 1) / 2 + margin
    y0, y1 = r.y0 + rows[0] / 2 - margin, r.y0 + (rows[-1] + 1) / 2 + margin
    return (max(x0, r.x0), max(y0, r.y0), min(x1, r.x1), min(y1, r.y1))


def page_text_diagrams(lines):
    """Text diagrams of a page with full FENs.

    lines: [(text, rect)] in reading order. Returns [(TextDiagram, fen)].
    """
    out = []
    for d in find_text_diagrams(lines):
        first, last = min(d.lines), max(d.lines)
        before = " ".join(t.strip() for t, _ in lines[max(0, first - 4):first])
        after = " ".join(t.strip() for t, _ in lines[last + 1:last + 8])
        out.append((d, full_fen(d.placement, before, after)))
    return out
