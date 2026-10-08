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
     "connect":    {"203:52,120:e4": {"after": "202:310,96:Nf3"}},
     "disconnect": {"204:80,300:Qh5": {"start": "here"},
                    "204:90,410:Rd1": {"start": "p204-1"},
                    "205:60,90:Kf2":  {"remove": true}},
     "gaps":       {"7:28,664:e5": {"san": ["Bd7"]}},
     "added":      {"201:118,342:Nf3": [{"san": ["Nc6", "Bb5"]},
                                        {"san": ["d6"], "note": "Quieter."}],
                    "201:80,300:e4":   [{"san": ["d4", "d5"], "before": true}],
                    "202:40,610:Rd1":  [{"san": ["Qe4", "Kd7"], "page": 202,
                                         "rect": [310.2, 66.5, 352.8, 79.8],
                                         "text": "Qe4 Kd7", "main": true}]},
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
connect      the key of the first move of a run (or of any move of a line:
             the moves from it on) and the key of the move after which the
             run continues ("after"). The run continues the main line there
             when that move ends it, and forms a variation from it otherwise,
             provided its first move is legal there.
disconnect   the key of a move of a line. {"start": "here"} starts a new line
             with that move, from the position before it; {"start": <diagram
             id>} starts the new line from that diagram instead; {"remove":
             true} takes the moves from it to the end of the line out of the
             line, so that they stand in no line.
gaps         the key of the first printed move after a gap in the text (moves
             that the book's text lacks, assemble._Builder.gap) and the moves
             the reader gave for the gap, in SAN and in order ("san", a list:
             the reader may give them one at a time). The moves are played
             from the line's last position before the gap when they are
             legal there; when they fill the whole gap the line reads on from
             them, else a smaller gap follows them. The program never
             supplies such a move itself.
added        the key of a move of a line and the variations the reader added
             after it (by moving pieces on the board): a list, each entry a
             list of moves in SAN played from the position after that move
             ("san"), with an optional "note". {"before": true} plays them
             from the position before the move instead, as alternatives to
             it: the reader's variations at the start of a line (where no
             move stands before them) or after a move the reader gave for a
             gap are stored so. The key is that of a printed move, so the
             variations survive a rebuild like the other corrections.
             Variations that begin with the same moves share them in the
             move list, so a variation that branches inside another one is
             stored whole (the shared moves and its own). The moves are
             played while they are legal; the rest of a variation is left
             out, with the reason.
             An entry with "page" and "rect" holds moves that the book
             prints in a section of a page where the program found none
             (the reader's "Read a section"): "rect" is the section,
             [x0, y0, x1, y1] in PDF points on that page (the coordinates
             of the page's marks), "text" what the program read there (the
             browser app reads it; the reader may type the moves instead)
             and {"main": true} continues the main line when the move the
             key names ends it (the moves form a variation otherwise, and
             always with "before"). "first" counts the moves at the start
             of "san" that come before the section (moves the reader added
             earlier, which the section goes on from), when there are any.
             Each move read from the section has a box on the page: the
             box of its printed word when the section prints as many moves
             as it gives, else one box, the section's, for its first move.

The corrections are applied after the book is assembled, by replaying the
lines they touch (assemble._Builder.apply_fix), so that the browser app can
apply each one at once and a fresh build gives the same result.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import chess

from .selection import BOOKS_DIR, ID_RE, _FENCE_RE, _objects

VERSION = 1
PARTS = ("diagrams", "moves", "unattached", "glyphs", "connect", "disconnect", "gaps", "added")
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
    out = {"version": VERSION, "diagrams": {}, "moves": {}, "unattached": {}, "glyphs": {},
           "connect": {}, "disconnect": {}, "gaps": {}, "added": {}}
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
    for key, v in (data.get("connect") or {}).items():
        parse_key(key)
        after = (v or {}).get("after") if isinstance(v, dict) else v
        parse_key(after)
        if after == key:
            raise ValueError(f"The correction of {key!r} joins a move to itself.")
        out["connect"][key] = {"after": after}
    for key, v in (data.get("disconnect") or {}).items():
        parse_key(key)
        v = v if isinstance(v, dict) else {}
        if v.get("remove"):
            out["disconnect"][key] = {"remove": True}
        else:
            start = v.get("start") or "here"
            if start != "here" and not ID_RE.match(str(start)):
                raise ValueError(f"{start!r} is not a diagram id such as 'p201-1'.")
            out["disconnect"][key] = {"start": str(start)}
    for key, v in (data.get("gaps") or {}).items():
        parse_key(key)
        sans = (v or {}).get("san") if isinstance(v, dict) else v
        if isinstance(sans, str):
            sans = [sans]
        if not isinstance(sans, list) or not sans or \
                not all(isinstance(x, str) and x.strip() for x in sans):
            raise ValueError(f"The moves given for the gap at {key!r} are not a list of moves.")
        out["gaps"][key] = {"san": [x.strip() for x in sans]}
    for key, v in (data.get("added") or {}).items():
        parse_key(key)
        entries = v if isinstance(v, list) else [v]
        kept = []
        for e in entries:
            sans = e.get("san") if isinstance(e, dict) else e
            if isinstance(sans, str):
                sans = sans.split()
            if not isinstance(sans, list) or not sans or \
                    not all(isinstance(x, str) and x.strip() for x in sans):
                raise ValueError(f"A variation added at {key!r} is not a list of moves.")
            entry = {"san": [x.strip() for x in sans]}
            if isinstance(e, dict) and e.get("before"):
                entry["before"] = True
            if isinstance(e, dict) and e.get("note"):
                entry["note"] = str(e["note"])
            if isinstance(e, dict) and (e.get("page") is not None or e.get("rect") is not None):
                entry.update(_section(key, e, len(entry["san"]), entry.get("before")))
            if entry not in kept:
                kept.append(entry)
        if kept:
            out["added"][key] = kept
    if data.get("note"):
        out["note"] = str(data["note"])
    return out


def _section(key, e, moves, before):
    """The section of a page that an "added" entry was read from, in
    canonical form: {"page", "rect", "text"?, "first"?, "main"?}, its keys in
    the order in which the browser writes them. The rectangle keeps a tenth
    of a point, as the browser stores it."""
    try:
        page = int(e.get("page"))
        rect = [round(float(v), 1) for v in e.get("rect")]
    except (TypeError, ValueError):
        page, rect = 0, []
    if isinstance(e.get("page"), bool) or page < 1 or len(rect) != 4 or \
            rect[2] <= rect[0] or rect[3] <= rect[1]:
        raise ValueError(f"The section of a page given at {key!r} is not a page number and a "
                         "rectangle [x0, y0, x1, y1] with x1 > x0 and y1 > y0.")
    out = {"page": page, "rect": rect}
    if e.get("text"):
        out["text"] = str(e["text"])
    first = e.get("first") or 0
    if not isinstance(first, int) or isinstance(first, bool) or not 0 <= first < moves:
        raise ValueError(f"The section read at {key!r} gives no move of its own.")
    if first:
        out["first"] = first
    if e.get("main") and not before:
        out["main"] = True
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
                     "\"moves\", \"unattached\", \"glyphs\", \"connect\", \"disconnect\", "
                     "\"gaps\" or \"added\" was found.")


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
