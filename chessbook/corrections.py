"""The reader's own corrections of a book's readings.

A book's corrections live in books/<pdf stem>/corrections.json, beside its
selection (selection.py), and in the browser under
"chessbook-corrections:<file name>:<page count>":

    {"version": 1,
     "diagrams":   {"p201-1": {"fen": "6k1/5pp1/7p/8/8/8/5PPP/3R2K1 w - - 0 1"}},
     "moves":      {"201:118,342:tLlxf6t": {"san": "Nxf6+"}},
     "unattached": {"201:96,410:Qh5": {"attach_to": "201:118,342:tLlxf6t"},
                    "202:40,88:Rd1": {"attach_to": "dismiss"}},
     "glyphs":     {"tLl": "N"},
     "note": "Corrections made in the book reader."}

diagrams     a diagram id (selection.py) and the position it shows; it wins
             over Stage 3's reading of the picture.
moves        a move token and the move it stands for, in SAN. The token key
             is "page:x,y:raw": the PDF page, the left and top edge of the
             token on the page in points (rounded) and the text as the text
             layer reads it. The key does not depend on the program's
             numbering of nodes, so it survives a rebuild.
unattached   the key of the first move of a sequence that the program placed
             in no line, and the key of the main-line move it is a variation
             of ("attach_to"), or "dismiss" when it is no variation at all.
glyphs       a piece symbol that the text recognition garbled (the junk
             prefix of a move token, as movetext.junk_prefix gives it) and the
             piece it stands for, one of K Q R B N P. It applies to every move
             of the book printed with that symbol; a correction of a single
             move overrides it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import chess

from .selection import BOOKS_DIR, ID_RE, _FENCE_RE, _objects

VERSION = 1
PARTS = ("diagrams", "moves", "unattached", "glyphs")
PIECES = "KQRBNP"
KEY_RE = re.compile(r"^(\d+):(-?\d+),(-?\d+):(.*)$", re.S)
TOLERANCE = 2.5             # points a token may move between builds and keep its key


def corrections_path(pdf_path, books_dir=None):
    """books/<pdf stem>/corrections.json (books_dir defaults to <project>/books)."""
    return Path(books_dir or BOOKS_DIR) / Path(pdf_path).stem / "corrections.json"


def token_key(page, bbox, raw):
    """The stable key of a move token: "page:x,y:raw"."""
    return f"{int(page)}:{round(bbox[0])},{round(bbox[1])}:{raw}"


def parse_key(key):
    """(page, x, y, raw) of a token key; raises ValueError for another text."""
    m = KEY_RE.match(key or "")
    if not m:
        raise ValueError(f"{key!r} is not a move key such as '201:118,342:Nf3'.")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)


def legal_position(fen):
    """True when a FEN holds a position with one king of each colour and no pawn
    on the first or last rank."""
    try:
        b = chess.Board(fen)
    except ValueError:
        return False
    if len(b.pieces(chess.KING, chess.WHITE)) != 1 or len(b.pieces(chess.KING, chess.BLACK)) != 1:
        return False
    return not (b.pieces(chess.PAWN, chess.WHITE) | b.pieces(chess.PAWN, chess.BLACK)) & \
        (chess.BB_RANK_1 | chess.BB_RANK_8)


def normalise(data):
    """Check a corrections dict and return it in canonical form. Entries that
    cannot be right (a FEN without one king a side, a move key in another
    form, a piece other than K Q R B N P) raise ValueError."""
    if not isinstance(data, dict):
        raise ValueError("Corrections must be a JSON object.")
    out = {"version": VERSION, "diagrams": {}, "moves": {}, "unattached": {}, "glyphs": {}}
    for did, v in (data.get("diagrams") or {}).items():
        if not ID_RE.match(str(did)):
            raise ValueError(f"{did!r} is not a diagram id such as 'p201-1'.")
        fen = (v or {}).get("fen") if isinstance(v, dict) else v
        if not isinstance(fen, str) or not legal_position(fen):
            raise ValueError(f"The position given for {did} does not hold one king of each "
                             "side, or has a pawn on the first or last rank.")
        out["diagrams"][str(did)] = {"fen": chess.Board(fen).fen()}
    for key, v in (data.get("moves") or {}).items():
        parse_key(key)
        san = (v or {}).get("san") if isinstance(v, dict) else v
        if not isinstance(san, str) or not san.strip():
            raise ValueError(f"The correction of {key!r} gives no move.")
        out["moves"][key] = {"san": san.strip()}
    for key, v in (data.get("unattached") or {}).items():
        parse_key(key)
        to = (v or {}).get("attach_to") if isinstance(v, dict) else v
        if to != "dismiss":
            parse_key(to)
        out["unattached"][key] = {"attach_to": to}
    for prefix, piece in (data.get("glyphs") or {}).items():
        p = str(piece or "").strip().upper()[:1]
        if not prefix or p not in PIECES:
            raise ValueError(f"{piece!r} is not one of the pieces K, Q, R, B, N and P.")
        out["glyphs"][str(prefix)] = p
    if data.get("note"):
        out["note"] = str(data["note"])
    return out


def empty():
    return normalise({})


def count(data):
    """The number of corrections of each kind."""
    data = data or {}
    return {k: len(data.get(k) or {}) for k in PARTS}


def load(pdf_path, books_dir=None):
    """The book's saved corrections (empty when there is no file)."""
    path = corrections_path(pdf_path, books_dir)
    if not path.exists():
        return empty()
    return normalise(json.loads(path.read_text(encoding="utf-8")))


def save(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalise(data), indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def parse_corrections_text(text):
    """Read corrections pasted from the reader's "Copy corrections" button,
    even inside a chat message with prose or a ```json fence around them."""
    chunks = [m.group(1) for m in _FENCE_RE.finditer(text)] + [text]
    for chunk in chunks:
        for obj in _objects(chunk):
            if isinstance(obj, dict) and set(PARTS) & obj.keys():
                return normalise(obj)
    raise ValueError("The text holds no corrections: no JSON object with \"diagrams\", "
                     "\"moves\", \"unattached\" or \"glyphs\" was found.")


class TokenIndex:
    """Finds the entry of a token key for a token on the page, allowing the
    token to move by a fraction of a point between builds."""

    def __init__(self, entries):
        self.by_page = {}
        for key, value in (entries or {}).items():
            page, x, y, raw = parse_key(key)
            self.by_page.setdefault(page, []).append((x, y, raw, key, value))
        self.used = set()

    def __bool__(self):
        return bool(self.by_page)

    def pages(self):
        return set(self.by_page)

    def find(self, page, bbox, raw):
        """(key, value) of the entry for a token, or (None, None)."""
        best = None
        for x, y, r, key, value in self.by_page.get(page, ()):
            d = max(abs(x - bbox[0]), abs(y - bbox[1]))
            if d > TOLERANCE:
                continue
            rank = (r != raw, d)
            if r != raw and r.replace(" ", "") != raw.replace(" ", "") and d > 0.75:
                continue
            if best is None or rank < best[0]:
                best = (rank, key, value)
        if best is None:
            return None, None
        self.used.add(best[1])
        return best[1], best[2]
