"""Decode chess moves printed in a book into legal moves.

The text of a chess book reaches us through OCR or through a PDF text layer,
and the move text is the part that suffers most: figurines turn into junk
("ti)f3", "\\x18fB", "YlYxh6"), digits turn into letters ("lO.", "hdl"), move
numbers are split ("1 8.g6") or glued to the previous move ("xd4t10.Kc3"), and
a check sign comes out as "t". Nothing here knows a particular book; the junk
that stands for each piece is learnt from the book itself (GlyphModel).

Three steps, each usable on its own:

    tokenize(text)            -> [Token]     numbers, moves, results, other words
    find_sequences(text)      -> [Sequence]  runs of numbered moves, with depth
    decode(board, tokens)     -> [Decoded]   legal moves for one run of tokens

Some books print move numbers without a dot ("1 e4 c5 2 Nc3", "3 ... e6").
uses_dotless_numbers() tells from a book's text whether it does, and
tokenize(text, dotless=True) then reads a bare number as a move number when
the run expects it, or when the word after it clearly looks like a move;
numbers in prose ("2 pawns", "Diagram 1", years, page numbers) stay prose.
Whether the move after it is legal is for decode() to tell.

Decoding works against the legal moves of the position, never against a
grammar alone: every legal move is scored by how well it explains the raw
token (piece glyph, disambiguation, capture mark, destination square,
promotion, check sign), the OCR confusions that would be needed are charged,
and a beam search over the whole run prefers the readings under which the
following moves stay decodable. Within a run, junk already read as one piece
is more likely that piece again.

A token that no legal move explains is marked 'failed', and the search goes
on as if the token were not a move, or as if a move had been played there
(of the moves the following tokens allow, the one most like the text), so a
run picks up again at the next move number instead of stopping. The run's
numbering shows a move missing from the text (Decoded.missing_before). A run
with a failed token is searched a second time with a much wider beam, since
the reading that later moves required may have been pruned.

Decoding a whole book twice is the intended use: the first pass decodes with
no knowledge of the book's glyph junk, GlyphModel.learn_run() collects the
junk of every move that only one reading fitted (and how the book prints
squares: "l" for 1, a lost f-file letter), and the second pass decodes with
those priors.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Iterable, Optional

import chess

__all__ = [
    "Token", "Sequence", "Decoded", "GlyphModel", "LETTER_SETS", "FIGURINES",
    "COMMON_GLYPH_JUNK", "tokenize", "find_sequences", "decode", "decode_sequence",
    "clean_run", "parse_move_text", "numbering_counts", "uses_dotless_numbers",
]

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = (chess.PAWN, chess.KNIGHT, chess.BISHOP,
                                           chess.ROOK, chess.QUEEN, chess.KING)
PIECE_LETTER = {PAWN: "P", KNIGHT: "N", BISHOP: "B", ROOK: "R", QUEEN: "Q", KING: "K"}
LETTER_PIECE = {v: k for k, v in PIECE_LETTER.items()}

# ---------------------------------------------------------------------------
# Notation tables
# ---------------------------------------------------------------------------

#: Piece letters of the common national notations. Values are piece letters
#: in English (K Q R B N); pawns carry no letter in any of them.
LETTER_SETS: dict[str, dict[str, str]] = {
    "English": {"K": "K", "Q": "Q", "R": "R", "B": "B", "N": "N"},
    "German": {"K": "K", "D": "Q", "T": "R", "L": "B", "S": "N"},
    "French": {"R": "K", "D": "Q", "T": "R", "F": "B", "C": "N"},
    "Spanish": {"R": "K", "D": "Q", "T": "R", "A": "B", "C": "N"},
    "Dutch": {"K": "K", "D": "Q", "T": "R", "L": "B", "P": "N"},
    "Russian": {"Кр": "K", "Ф": "Q", "Л": "R", "С": "B", "К": "N",
                "Kr": "K", "F": "Q", "L": "R", "S": "B", "K": "N"},
}

#: Unicode chess figurines, recognised in every notation.
FIGURINES = {"♔": "K", "♕": "Q", "♖": "R", "♗": "B", "♘": "N", "♙": "P",
             "♚": "K", "♛": "Q", "♜": "R", "♝": "B", "♞": "N", "♟": "P"}

#: OCR junk that figurine fonts commonly turn into. It can seed a GlyphModel
#: (GlyphModel(seed=True)); decoding never needs it, because the junk of a
#: particular book is learnt from that book.
COMMON_GLYPH_JUNK: dict[str, list[str]] = {
    "N": ["\x18", "tLl", "ti)", "lt)", "tt:l", "ttl", "tLJ", "ttJ", "lLl", "lbl", "lb",
          "<:l", "tl)", "t!i)", "c!L!", "ltl", "tll", "lt:\\"],
    "Q": ["\x1b", "YlY", "'i!Y", "'ilY", "Wf", "1W", "V", "Y«", "Vl", "'!W", "VN", "'lW",
          "Wff", "YB", "1Mf", "'Wf"],
    "K": ["\x14", "®", "lt>", "<.!.>", "\\t>", "Wi>", "'it>", "<i!?", "<i!>", "ci>", "i>",
          "<Jl", "'4i", "@", "ctf?", "cj;l"],
    "R": ["J3", ":B:", "J\x1d:", "l:t", ".1':!:", "I:t", ":", "\x1d", "l:!", "l::1", "Ei:",
          "E\\", "J:", "È", "g"],
    "B": ["i.", ".i", "A", "J.", "h", ",h", ".t", "q", ".b", "Ö"],
}

# What an OCR'd character in the file slot of a square can stand for, with the
# cost of that reading. Exact readings cost nothing.
FILE_READ: dict[str, dict[int, float]] = {
    "a": {0: 0.0}, "b": {1: 0.0, 7: 0.6}, "c": {2: 0.0, 4: 0.5}, "d": {3: 0.0},
    "e": {4: 0.0, 2: 0.5}, "f": {5: 0.0}, "g": {6: 0.0}, "h": {7: 0.0, 1: 0.6},
    "o": {0: 0.6}, "t": {5: 0.5}, "£": {5: 0.15}, "q": {6: 0.5}, "r": {5: 0.9},
    "9": {6: 0.9}, "€": {4: 0.6}, "ƒ": {5: 0.3},
}
# The same for the rank slot. 'l', 'I', 'i' and '!' read as 1 (and as the
# 7 whose hook was lost), 'B', 'S' and 's' as 8 and 5, 'b' and 'G' as 6.
RANK_READ: dict[str, dict[int, float]] = {
    "1": {0: 0.0, 6: 0.8}, "2": {1: 0.0}, "3": {2: 0.0, 7: 0.8}, "4": {3: 0.0},
    "5": {4: 0.0, 5: 0.9}, "6": {5: 0.0, 7: 0.9, 4: 0.9}, "7": {6: 0.0, 0: 0.8},
    "8": {7: 0.0, 2: 0.8, 5: 0.9},
    "l": {0: 0.3, 6: 0.7}, "I": {0: 0.3, 6: 0.8}, "i": {0: 0.4, 6: 0.7},
    "!": {0: 0.6}, "|": {0: 0.4}, "]": {0: 0.7}, "j": {0: 0.9},
    "B": {7: 0.3, 2: 0.9}, "S": {7: 0.4, 4: 0.5}, "s": {7: 0.4, 4: 0.6},
    "b": {5: 0.5}, "G": {5: 0.5}, "Z": {1: 0.6}, "z": {1: 0.7}, "T": {6: 0.7},
    "A": {3: 0.9}, "?": {6: 1.0},
}
CAPTURE_CHARS = set("xX:×*")
LONG_SEP = set("-–—")
NOISE_CHARS = "'`’‘´\""      # stray marks OCR puts between the file and rank
DOT_CHARS = ".…•·"

# ---------------------------------------------------------------------------
# Costs (negative log-odds, roughly). Every reading of a token gets the sum.
# ---------------------------------------------------------------------------
C_VANISH = 2.0          # a piece move printed without any piece glyph
C_WRONG_LETTER = 3.5    # a recognised piece letter read as another piece
C_MISSING_FILE = 1.3    # destination file absent ("ex5")
C_MISSING_RANK = 2.5
C_ABSORB_X = 1.0        # a capture mark read as part of the piece glyph
C_FALSE_CAPTURE = 1.5   # capture mark on a non-capture
C_MISSING_X = 0.6       # capture without capture mark
C_DISAMB_WRONG = 2.0    # disambiguation that names another square
C_DISAMB_EXTRA = 0.3    # correct but unnecessary disambiguation
C_DISAMB_MISSING = 0.5  # needed disambiguation absent
C_CHECK_FALSE = 0.8     # check sign on a move that does not give check
C_CHECK_MISSING = 0.3   # check not marked
C_MATE_FALSE = 1.0
C_PROMO_EXTRA = 2.0
C_CASTLE_OTHER = 1.2
MAX_COST = 4.4          # readings dearer than this are not readings
FAIL_TRIGGER = 2.5      # above this, also consider that the token failed
C_FAIL = 4.5            # a token that no legal move explains (any move played)
C_SKIP = 4.5            # a token that is not a move at all
C_PARITY = 1.0          # the numbering disagrees with whose move it is
C_INSERT = 3.5          # a move missing from the text
MAX_FAILS = 2           # consecutive failed tokens the search can bridge
FIT_MARGIN = 0.45       # readings this close to the best one also "fit"
TIE = 0.2               # score differences below this are ties
BEAM = 16
MAX_WILD = 1500
C_UNREAD = 2.5          # a file or rank character read as a value no table allows
WILD_WEIGHT = 0.3       # how much a failed token's resemblance to a move counts
SQUARE_KAPPA = 4.0      # weight of the default square readings against the book's counts
SQUARE_MIN_N = 5        # observations of a character before its learnt readings count
GLYPH_STRONG_N = 2      # whole-junk observations before a learnt glyph is trusted ...
GLYPH_STRONG_SHARE = 0.75   # ... when this share of them name one piece
WEAK_SPREAD = 0.7       # most a weakly learnt glyph may favour one piece over another;
                        # below the cheapest misread of a printed square
C_IMPLIED_NONCAP = 1.0  # a junk glyph that includes the capture mark, on a non-capture
C_LONG_FROM = 9.0       # long notation whose from-square is not the square the piece leaves
C_PAWN_DISAMB = 1.5     # a file letter before a pawn move that captures nothing ("gg4")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Token:
    """One token of book text. raw == text[start:end] always.

    kind is 'number' (a move number, or a bare "..." continuation, whose
    number is None), 'move', 'result' or 'other'. For moves, number and black
    give the move's place in the numbering as far as the text shows it. For a
    number, black says whether it introduces a Black move ("16 ..."), and
    side_known is False when the dots could be read either way.
    layout marks 'other' tokens that stand alone on their line (diagram
    labels, board coordinates): they do not interrupt a run of moves.
    dotless marks a move number printed without a dot ("12 Nf3"), which
    tokenize() reads only when asked to (books that number moves that way).
    forced holds the SAN that a reader's correction gives a move token: the
    decoder then reads the token as that move, and as nothing else, where it
    is legal.
    """
    kind: str
    raw: str
    start: int
    end: int
    number: Optional[int] = None
    black: bool = False
    side_known: bool = True
    layout: bool = False
    dotless: bool = False
    forced: Optional[str] = None    # the SAN a reader's correction gives this move token


@dataclass
class Sequence:
    """A maximal run of numbered moves.

    first_number is None for a run that starts at a bare "..." continuation.
    depth counts the parentheses open around the run (0 = main text).
    tokens holds the run's number, move and result tokens; moves carry the
    number and side implied by the run's own numbering.
    """
    first_number: Optional[int]
    black_first: bool
    tokens: list
    start: int
    end: int
    depth: int = 0
    side_known: bool = True

    @property
    def moves(self) -> list:
        return [t for t in self.tokens if t.kind == "move"]


@dataclass
class Decoded:
    """The decoding of one move token.

    status: 'ok' (one reading fits the raw token), 'guessed' (several readings
    were legal and the moves that follow chose one), 'ambiguous' (several
    readings remain equally good; the best is still filled in) or 'failed'
    (no legal reading; san, uci and fen are None, and alternatives holds the
    move the search assumed in order to carry on, if any).
    fen is the position after the move. cost is the reading's cost (0 for a
    clean token). glyph is the text read as the piece glyph, annotation the
    "!", "?" etc. printed after the move, square_read the characters read as
    the destination file and rank (None where the text has none).
    missing_before holds the SAN of a move the numbering shows to be missing
    from the text just before this one; the search played it, and fen
    includes it (only when decode() is called with insert=True).
    capture_mark says whether the reading took a capture mark from the text
    (None for castling and failed tokens). glyph_lost is True when the move
    contradicts a piece glyph printed in the token: a pawn move read from a
    token with a piece glyph or with a file letter before a non-capture
    ("gg4" read as g4), or a piece letter of the notation read as another
    piece.
    """
    raw: str
    start: int
    end: int
    number: Optional[int]
    black: bool
    san: Optional[str]
    uci: Optional[str]
    fen: Optional[str]
    status: str
    alternatives: list = field(default_factory=list)
    cost: float = 0.0
    glyph: Optional[str] = None
    annotation: str = ""
    square_read: tuple = (None, None)
    missing_before: Optional[str] = None
    capture_mark: Optional[bool] = None
    glyph_lost: bool = False


# ---------------------------------------------------------------------------
# Glyph model
# ---------------------------------------------------------------------------
class GlyphModel:
    """What a book's glyph junk and square characters stand for, learnt from the book.

    learn() takes (prefix, piece) pairs, piece being one of K Q R B N P,
    usually from tokens that only one reading fitted. prior(prefix) returns
    a probability for each piece. A prefix never seen whole is judged by its
    characters (a character model over everything learnt), so "ti)" and "tLl"
    teach something about "t!i)" too. With nothing learnt, every piece is
    equally likely and a pawn is unlikely.

    The model also learns how the book prints squares: learn_squares() takes
    (file character, rank character, true square) triples, None standing for
    a character the text lacks. A book whose OCR loses the f-file letter
    ("Nf5" printed "N5") or prints "f3" as "6" then reads those cheaply.
    learn_run() feeds both from one decoded run.
    """
    PIECES = "KQRBNP"
    DEFAULT = {"K": 0.196, "Q": 0.196, "R": 0.196, "B": 0.196, "N": 0.196, "P": 0.02}

    def __init__(self, seed: bool = False, kappa: float = 2.0):
        self.kappa = kappa
        self.counts: dict[str, Counter] = defaultdict(Counter)
        self.char_counts: dict[str, Counter] = defaultdict(Counter)
        self.piece_totals: Counter = Counter()
        # (other character missing?, raw character or "") -> Counter(true file or rank)
        self.file_counts: dict[tuple, Counter] = defaultdict(Counter)
        self.rank_counts: dict[tuple, Counter] = defaultdict(Counter)
        # glyph -> Counter(True: capture, False: no capture), for moves printed
        # without a capture mark: some junk stands for the piece and the "x"
        self.capture_counts: dict[str, Counter] = defaultdict(Counter)
        self._cache: dict[str, dict[str, float]] = {}
        self._square_cache: dict = {}
        if seed:
            self.learn(((g, p) for p, gs in COMMON_GLYPH_JUNK.items() for g in gs), weight=2.0)

    def __len__(self):
        return int(sum(self.piece_totals.values()))

    # -- learning ---------------------------------------------------------
    def learn(self, pairs: Iterable[tuple[str, str]], weight: float = 1.0) -> int:
        n = 0
        for prefix, piece in pairs:
            prefix = _strip_spaces(prefix)
            piece = piece.upper()
            if not prefix or piece not in self.PIECES:
                continue
            self.counts[prefix][piece] += weight
            self.piece_totals[piece] += weight
            for ch in prefix:
                self.char_counts[piece][ch] += weight
            n += 1
        self._cache.clear()
        return n

    def learn_squares(self, triples: Iterable[tuple], weight: float = 1.0) -> int:
        """Learn (file char or None, rank char or None, true square index) triples."""
        n = 0
        for fch, rch, sq in triples:
            if sq is None or (fch is None and rch is None):
                continue
            self.file_counts[(rch is None, fch or "")][chess.square_file(sq)] += weight
            self.rank_counts[(fch is None, rch or "")][chess.square_rank(sq)] += weight
            n += 1
        self._square_cache.clear()
        return n

    def learn_decoded(self, decoded: Iterable["Decoded"], statuses=("ok",),
                      max_cost: float = 2.5, square_statuses=("ok", "guessed")) -> int:
        """Learn glyphs and square readings from decoded moves; returns the pairs learnt.

        Glyphs are learnt from moves with one fitting reading ('ok') whose
        reading cost little (cost <= max_cost); square readings also from
        moves that the following moves chose ('guessed'). Pass only runs that
        were decoded from their true starting position: a run read from the
        wrong position is forced through junk readings (see clean_run() and
        learn_run()).
        """
        pairs, squares = [], []
        for d in decoded:
            if not d.san or d.cost > max_cost:
                continue
            if d.status in statuses and d.glyph:
                pairs.append((d.glyph, _san_piece(d.san)))
            if d.status in square_statuses and d.glyph and d.capture_mark is False:
                self.capture_counts[_strip_spaces(d.glyph)]["x" in d.san] += 1
            if d.status in square_statuses:
                if d.uci and d.square_read != (None, None) and not d.san.startswith("O-O"):
                    squares.append((d.square_read[0], d.square_read[1],
                                    chess.Move.from_uci(d.uci).to_square))
        self.learn_squares(squares)
        return self.learn(pairs)

    def learn_run(self, decoded: list) -> int:
        """Learn from one decoded run, if it reads as a real line of play.

        A clean run (clean_run()) teaches glyphs and square readings from its
        'ok' moves. In a run that is clean but for a few failed moves, a failed
        move whose neighbours read well teaches how its square was printed:
        the move assumed in its place (alternatives[0]) was chosen by the
        moves that follow and by its resemblance to the text.
        """
        n = 0
        if clean_run(decoded):
            n += self.learn_decoded(decoded)
        elif clean_run(decoded, max_failed=0.2, max_mean_cost=1.5):
            squares = []
            for i, d in enumerate(decoded):
                if d.status != "failed" or not d.alternatives or d.square_read == (None, None):
                    continue
                nb = [decoded[j] for j in (i - 1, i + 1) if 0 <= j < len(decoded)]
                if any(x.status == "failed" for x in nb):
                    continue
                sq = _san_square(d.alternatives[0])
                if sq is not None:
                    squares.append((d.square_read[0], d.square_read[1], sq))
            n += self.learn_squares(squares)
        return n

    def support(self, prefix: str) -> tuple[float, float]:
        """(times the prefix was learnt whole, share of its likeliest piece)."""
        c = self.counts.get(_strip_spaces(prefix))
        if not c:
            return 0.0, 0.0
        n = sum(c.values())
        return n, max(c.values()) / n

    def strong(self, prefix: str) -> bool:
        """True when the book has shown this junk whole often enough, and
        nearly always as one piece, for its learnt reading to be trusted."""
        n, share = self.support(prefix)
        return n >= GLYPH_STRONG_N and share >= GLYPH_STRONG_SHARE

    def implies_capture(self, prefix: str) -> bool:
        """True when the book prints this junk for a piece and its capture
        mark together ("h" for "Bx"): moves read through it were captures
        nearly every time although no "x" was printed."""
        c = self.capture_counts.get(_strip_spaces(prefix))
        if not c:
            return False
        return c[True] >= 3 and c[True] >= 0.8 * (c[True] + c[False])

    # -- piece priors -----------------------------------------------------
    def _backoff(self, prefix: str) -> dict[str, float]:
        if not self.piece_totals:
            return dict(self.DEFAULT)
        total = sum(self.piece_totals.values())
        vocab = len({c for cc in self.char_counts.values() for c in cc}) + 20
        logs = {}
        for p in self.PIECES:
            pt = self.piece_totals[p]
            lp = math.log((pt + 1.0) / (total + 6.0))
            cc = self.char_counts[p]
            n = sum(cc.values())
            chars = prefix or " "
            ll = sum(math.log((cc[c] + 0.3) / (n + 0.3 * vocab)) for c in chars) / len(chars)
            logs[p] = lp + 2.0 * ll
        m = max(logs.values())
        z = sum(math.exp(v - m) for v in logs.values())
        out = {p: math.exp(v - m) / z for p, v in logs.items()}
        # Never let the character model rule a piece out completely.
        return {p: 0.9 * out[p] + 0.1 * self.DEFAULT[p] for p in self.PIECES}

    def prior(self, prefix: str) -> dict[str, float]:
        prefix = _strip_spaces(prefix)
        hit = self._cache.get(prefix)
        if hit is not None:
            return hit
        # A lone file letter is normally the file of a pawn capture ("cxd4"); it
        # stands for a piece only if the book has shown it whole ("h" for a
        # bishop), never because other junk contains the letter.
        base = dict(self.DEFAULT) if prefix in _FILE_LETTERS else self._backoff(prefix)
        c = self.counts.get(prefix)
        if c:
            n = sum(c.values())
            out = {p: (c[p] + self.kappa * base[p]) / (n + self.kappa) for p in self.PIECES}
        else:
            out = base
        self._cache[prefix] = out
        return out

    # -- square readings --------------------------------------------------
    def file_costs(self, fch: Optional[str], rank_missing: bool = False) -> dict[int, float]:
        """Cost of reading file character fch (None: no file printed) as each file."""
        key = ("f", fch, rank_missing)
        hit = self._square_cache.get(key)
        if hit is None:
            default = FILE_READ.get(fch, {}) if fch is not None else \
                {f: C_MISSING_FILE for f in range(8)}
            hit = _blend(default, self.file_counts.get((rank_missing, fch or "")), fch is None)
            self._square_cache[key] = hit
        return hit

    def rank_costs(self, rch: Optional[str], file_missing: bool = False) -> dict[int, float]:
        """Cost of reading rank character rch (None: no rank printed) as each rank."""
        key = ("r", rch, file_missing)
        hit = self._square_cache.get(key)
        if hit is None:
            default = RANK_READ.get(rch, {}) if rch is not None else \
                {r: C_MISSING_RANK for r in range(8)}
            hit = _blend(default, self.rank_counts.get((file_missing, rch or "")), rch is None)
            self._square_cache[key] = hit
        return hit

    def top(self, k: int = 30) -> list[tuple[str, str, float]]:
        """The k most frequent prefixes learnt, with their likeliest piece."""
        rows = []
        for prefix, c in self.counts.items():
            piece, n = c.most_common(1)[0]
            rows.append((prefix, piece, sum(c.values())))
        rows.sort(key=lambda r: -r[2])
        return rows[:k]

    def square_habits(self, k: int = 12) -> list[tuple[str, str, int, int]]:
        """Square readings the book uses that are not plain letters or digits.

        Rows of (slot, printed character, value, count); "-" stands for a
        character the text lacks.
        """
        rows = []
        for (miss, ch), cnt in self.file_counts.items():
            for f, n in cnt.items():
                if ch != "abcdefgh"[f]:
                    rows.append(("file", ch or "-", "abcdefgh"[f], int(n)))
        for (miss, ch), cnt in self.rank_counts.items():
            for r, n in cnt.items():
                if ch != str(r + 1):
                    rows.append(("rank", ch or "-", str(r + 1), int(n)))
        rows.sort(key=lambda r: -r[3])
        return rows[:k]


_FILE_LETTERS = set("abcdefgh")
_REAL_SPACES = " \n\r\u00a0"


def _strip_spaces(text: Optional[str]) -> str:
    """Strip real spaces only. str.strip() would also remove the control
    characters \\x1c-\\x1f and \\t, which OCR makes of figurines (the rook's
    "\\x1d"), and so turn a piece move into a pawn move."""
    return (text or "").strip(_REAL_SPACES)


def _blend(default: dict, counts: Optional[Counter], missing: bool) -> dict:
    """Default reading costs moved towards what the book has shown.

    A reading the book uses often gets cheaper and one it never uses a little
    dearer; a reading no default allows becomes possible once the book has
    shown it three times.
    """
    n = sum(counts.values()) if counts else 0
    if n < SQUARE_MIN_N:
        return dict(default)
    w = {k: math.exp(-v) for k, v in default.items()}
    z = sum(w.values()) or 1.0
    out = {}
    for k in range(8):
        c = counts.get(k, 0)
        if k in default:
            p0 = w[k] / z
            post = (c + SQUARE_KAPPA * p0) / (n + SQUARE_KAPPA)
            adj = max(-2.0, min(0.5, math.log(p0 / post)))
            floor = 0.5 if missing else (0.0 if default[k] == 0.0 else 0.1)
            out[k] = max(floor, default[k] + adj)
        elif c >= 3:
            out[k] = max(0.5, 1.0 - math.log((c + 0.5) / (n + 1.0)))
    return out


def clean_run(decoded: list, max_failed: float = 0.0, max_mean_cost: float = 1.5) -> bool:
    """True when a decoded run reads as a real line from its starting position.

    A run decoded from the wrong position (a solution that starts from a
    diagram, decoded from the initial position) shows failed moves and dear
    readings; such runs must not teach a GlyphModel.
    """
    if not decoded:
        return False
    failed = sum(d.status == "failed" for d in decoded)
    if failed > max_failed * len(decoded) or decoded[0].status == "failed":
        return False
    costs = [d.cost for d in decoded if d.status != "failed"]
    return sum(costs) / len(costs) <= max_mean_cost


def _san_square(san: str) -> Optional[int]:
    """Destination square of a SAN move (None for castling)."""
    if san.startswith("O-O"):
        return None
    m = re.findall(r"[a-h][1-8]", san)
    return chess.parse_square(m[-1]) if m else None


def _san_piece(san: str) -> str:
    if san.startswith("O-O"):
        return "K"
    return san[0] if san[0] in "KQRBN" else "P"


# ---------------------------------------------------------------------------
# Parsing one raw move token
# ---------------------------------------------------------------------------
@dataclass
class _Parse:
    prefix: str
    dfile: Optional[dict]      # disambiguation file readings, or None
    drank: Optional[dict]
    cap: object                # True, False or '-' (long notation)
    dest: dict                 # square -> cost under the default reading tables
    promo: Optional[str]       # None, '' (sign without piece) or the text
    fch: Optional[str] = None  # the character read as the destination file (None: absent)
    rch: Optional[str] = None  # the character read as the destination rank (None: absent)


@dataclass
class _Parsed:
    raw: str
    castle: Optional[str]      # 'K', 'Q' or None
    check: int                 # 0 none, 1 check, 2 double check, 3 mate
    annotation: str
    parses: list


_RESULT_RE = re.compile(r"^(?:1-0|0-1|l-0|0-l|1-o|o-1|l-o|o-l|1/2-1/2|½-½|Y2-Y2|1/2-l/2|1:0|0:1)$")
_CASTLE_RE = re.compile(r"^[0Oo°](?:[-–—_.]?[0Oo°]){1,2}$")
_PAREN_ANN = re.compile(r"\((?:[!?]{1,2})\)$")


def _strip_suffix(s: str):
    """Split annotation and check signs off the end of a token."""
    ann = ""
    check = 0
    s = _strip_spaces(s)
    while s:
        m = _PAREN_ANN.search(s)
        if m and m.start() > 0:
            ann = s[m.start() + 1:-1] + ann
            s = s[:m.start()]
            continue
        ch = s[-1]
        if (ch == "!" and len(s) >= 3 and s[-2] in "abcdefgh£tqo"
                and (len(s) == 3 or s[-3].isupper() or s[-3] == "x"
                     or not (s[-3].isalpha() or s[-3].isdigit()))):
            break               # "Qa!+", "Rxe!", "Nt!": the "!" is the rank 1 ("h5t!" is not)
        if ch in "!?":
            ann = ch + ann
            s = s[:-1]
        elif ch == "#":
            check = 3
            s = s[:-1]
        elif ch == "‡":
            check = max(check, 2)
            s = s[:-1]
        elif ch in "+†":
            check = max(check, 2 if check else 1) if check < 3 else check
            s = s[:-1]
        elif ch == "t" and len(s) >= 3:      # a final "t" is a check sign printed by OCR
            check = max(check, 2 if check else 1) if check < 3 else check
            s = s[:-1]
        elif ch in ",;)(." and len(s) > 2:
            s = s[:-1]
        elif ch == "=" and len(s) >= 3 and s[-2] in "+t#!?":
            s = s[:-1]          # "=" printed after the move as an evaluation
        elif s.endswith("e.p.") and len(s) > 4:
            s = s[:-4]
        else:
            break
    return s, check, ann


def _capture_opts(rest: str):
    run = 0
    while run < len(rest) and rest[len(rest) - 1 - run] in CAPTURE_CHARS:
        run += 1
    opts = [(True, rest[:len(rest) - k]) for k in range(1, run + 1)]
    opts.append((False, rest))
    if rest and rest[-1] in LONG_SEP:
        opts.append(("-", rest[:-1]))
    return opts


_DIS_RANK = {c: RANK_READ[c] for c in "12345678lI"}
_DIS_FILE = {c: v for c, v in FILE_READ.items() if c in "abcdefgh£"}


def _disamb_opts(rest: str):
    opts = [(None, None, rest)]
    if rest and rest[-1] in _DIS_RANK:
        dr = _DIS_RANK[rest[-1]]
        opts.append((None, dr, rest[:-1]))
        if len(rest) >= 2 and rest[-2] in _DIS_FILE:
            opts.append((_DIS_FILE[rest[-2]], dr, rest[:-2]))
    if rest and rest[-1] in _DIS_FILE:
        opts.append((_DIS_FILE[rest[-1]], None, rest[:-1]))
    return opts


def _dest_costs(fread: Optional[dict], rread: Optional[dict]) -> dict:
    files = fread if fread is not None else {f: C_MISSING_FILE for f in range(8)}
    ranks = rread if rread is not None else {r: C_MISSING_RANK for r in range(8)}
    return {chess.square(f, r): fc + rc for f, fc in files.items() for r, rc in ranks.items()}


def _enumerate_parses(core: str) -> list:
    out = []
    n = len(core)
    heads = []
    eq = core.rfind("=")
    if eq > 0:
        heads.append((core[:eq], core[eq + 1:]))
    else:
        heads.append((core, None))
        for t in (1, 2, 3, 4):
            if n - t >= 2 and core[n - t - 1] in RANK_READ:
                rr = RANK_READ[core[n - t - 1]]
                if 0 in rr or 7 in rr:
                    heads.append((core[:n - t], core[n - t:]))
    for head, promo in heads:
        if not head:
            continue
        rank_opts = []
        if head[-1] in RANK_READ:
            rank_opts.append((RANK_READ[head[-1]], head[-1], head[:-1]))
        elif head[-1] in FILE_READ:
            rank_opts.append((None, None, head))          # rank missing
        for rread, rch, before in rank_opts:
            b = before.rstrip(NOISE_CHARS) if rread is not None else before
            file_opts = []
            if b and b[-1] in FILE_READ:
                file_opts.append((FILE_READ[b[-1]], b[-1], b[:-1]))
            elif rread is not None:
                file_opts.append((None, None, b))         # file missing
            for fread, fch, rest in file_opts:
                if fread is None and rread is None:
                    continue
                dest = _dest_costs(fread, rread)
                for cap, rest2 in _capture_opts(rest):
                    for dfile, drank, prefix in _disamb_opts(rest2):
                        if cap == "-" and dfile is None:
                            continue
                        out.append(_Parse(_strip_spaces(prefix), dfile, drank, cap, dest, promo,
                                          fch, rch))
    if _LONG_CORE_RE.search(core):
        # long notation ("Ng1-f3", "e2-e4", "d2xd3"): the square the piece leaves is
        # printed, so only readings that take it as that square count
        out = [q for q in out if q.dfile is not None and q.drank is not None] or out
    return out


_LONG_CORE_RE = re.compile(r"[a-h£][1-8lI]\s?[-–—x:×]\s?[a-h£][1-8lIBS]")


@lru_cache(maxsize=200000)
def _parse_raw(raw: str) -> _Parsed:
    text = "".join(raw.split(" ")).replace("\n", "").replace("\r", "")
    core, check, ann = _strip_suffix(text)
    castle = None
    cc = core.replace(" ", "")
    if _CASTLE_RE.match(cc):
        zeros = sum(ch in "0Oo°" for ch in cc)
        castle = "Q" if zeros >= 3 else "K"
    parses = [] if castle else _enumerate_parses(core)
    if not parses and not castle and check and text.endswith("t"):
        # the final 't' was not a check sign after all
        parses = _enumerate_parses(core + "t")
        check = 0
    return _Parsed(raw, castle, check, ann, parses)


def parse_move_text(raw: str) -> list[dict]:
    """Every way of splitting a raw token into glyph, disambiguation, capture,
    square and promotion (for inspection and tests)."""
    p = _parse_raw(raw)
    if p.castle:
        return [{"castle": p.castle, "check": p.check, "annotation": p.annotation}]
    out = []
    for q in p.parses:
        out.append({"prefix": q.prefix, "capture": q.cap,
                    "squares": sorted(chess.square_name(s) for s in q.dest),
                    "promotion": q.promo, "check": p.check, "annotation": p.annotation})
    return out


# ---------------------------------------------------------------------------
# Scoring legal moves against a token
# ---------------------------------------------------------------------------
def _resolve_letters(letters) -> dict[str, int]:
    if letters is None:
        table = LETTER_SETS["English"]
    elif isinstance(letters, str):
        if letters not in LETTER_SETS:
            raise ValueError(f"unknown letter set {letters!r}; choose from {sorted(LETTER_SETS)}")
        table = LETTER_SETS[letters]
    else:
        table = dict(letters)
    out = {k: LETTER_PIECE[v.upper()] for k, v in table.items()}
    out.update({k: LETTER_PIECE[v] for k, v in FIGURINES.items()})
    return out


class _Scorer:
    def __init__(self, letters=None, glyphs: Optional[GlyphModel] = None):
        self.letters = _resolve_letters(letters)
        self._letters_arg = letters
        self.glyphs = glyphs if glyphs is not None else GlyphModel()
        self._plain = None
        self._capture_cache: dict[str, bool] = {}
        self._piece_cache: dict[str, dict[int, float]] = {}
        self._promo_cache: dict[str, dict[int, float]] = {}
        self._cand_cache: dict = {}
        self._index_cache: dict = {}

    def piece_costs(self, prefix: str) -> dict[int, float]:
        hit = self._piece_cache.get(prefix)
        if hit is not None:
            return hit
        if prefix == "":
            out = {pt: (0.0 if pt == PAWN else C_VANISH) for pt in PIECE_LETTER}
        elif prefix in self.letters:
            want = self.letters[prefix]
            out = {pt: (0.0 if pt == want else C_WRONG_LETTER) for pt in PIECE_LETTER}
        else:
            pri = self.glyphs.prior(prefix)
            out = {pt: min(-math.log(max(pri[PIECE_LETTER[pt]], 1e-6)), 6.0)
                   for pt in PIECE_LETTER}
            if len(self.glyphs) and not self.glyphs.strong(prefix):
                # Junk the book has shown whole only once or twice, or never
                # (read through its characters), may lean towards a piece but
                # never so far that it outweighs a misread of the printed
                # square ("l3h3": a rook to h3, not a king to h8).
                lo = min(out[pt] for pt in out if pt != PAWN)
                default = -math.log(GlyphModel.DEFAULT["P"])
                out = {pt: (max(c, default) if pt == PAWN else min(c, lo + WEAK_SPREAD))
                       for pt, c in out.items()}
        self._piece_cache[prefix] = out
        return out

    def plain(self) -> "_Scorer":
        """The same scorer with no glyph knowledge (the unlearnt prior)."""
        if self._plain is None:
            self._plain = _Scorer(self._letters_arg, None) if len(self.glyphs) else self
        return self._plain

    def weak_glyph(self, prefix: Optional[str]) -> bool:
        """True for junk whose reading rests on weak learnt evidence."""
        if not prefix or prefix in self.letters:
            return False
        return not (len(self.glyphs) and self.glyphs.strong(prefix))

    def implies_capture(self, prefix: str) -> bool:
        hit = self._capture_cache.get(prefix)
        if hit is None:
            hit = bool(prefix) and prefix not in self.letters and \
                self.glyphs.implies_capture(prefix)
            self._capture_cache[prefix] = hit
        return hit

    def promo_costs(self, text: Optional[str]) -> Optional[dict[int, float]]:
        if text is None:
            return None
        hit = self._promo_cache.get(text)
        if hit is not None:
            return hit
        t = text.strip("=()/")
        if t == "":
            out = {QUEEN: 0.2, ROOK: 0.9, BISHOP: 0.9, KNIGHT: 0.9}
        elif t in self.letters:
            want = self.letters[t]
            out = {pt: (0.0 if pt == want else 2.0) for pt in (QUEEN, ROOK, BISHOP, KNIGHT)}
        else:
            pri = self.glyphs.prior(t)       # most promotions are to a queen
            out = {pt: min(-math.log(max(pri[PIECE_LETTER[pt]], 1e-6)), 6.0)
                   + (0.2 if pt == QUEEN else 0.5) for pt in (QUEEN, ROOK, BISHOP, KNIGHT)}
        self._promo_cache[text] = out
        return out

    def _index(self, parsed: _Parsed):
        """(square -> [(parse, destination cost)], bitboard of those squares)."""
        hit = self._index_cache.get(parsed.raw)
        if hit is not None:
            return hit
        by_dest: dict = defaultdict(list)
        mask = 0
        g = self.glyphs
        for p in parsed.parses:
            fc = g.file_costs(p.fch, p.rch is None)
            rc = g.rank_costs(p.rch, p.fch is None)
            for f, a in fc.items():
                for r, b_ in rc.items():
                    sq = chess.square(f, r)
                    by_dest[sq].append((p, a + b_))
                    mask |= chess.BB_SQUARES[sq]
        hit = (dict(by_dest), mask)
        self._index_cache[parsed.raw] = hit
        return hit

    def _reading_cost(self, board, m, pt, p, dc, is_cap, need, same_file, best):
        """Cost of reading move m through parse p (dc: its destination cost)."""
        pc = self.piece_costs(p.prefix)[pt]
        c = dc + pc
        if c >= best:
            return c, pc
        if p.cap is True:
            c += 0.0 if is_cap else C_FALSE_CAPTURE
        elif p.cap == "-":
            c += 0.8 if is_cap else 0.0
        elif pt != PAWN and self.implies_capture(p.prefix):
            c += 0.0 if is_cap else C_IMPLIED_NONCAP     # "h" printed for "Bx"
        else:
            if is_cap:
                c += C_MISSING_X
            if p.prefix[-1:] in "xX×" and p.prefix:
                c += C_ABSORB_X
        long_form = p.cap == "-" or (p.dfile is not None and p.drank is not None)
        if pt == PAWN and not is_cap and not long_form and (p.dfile is not None
                                                            or p.drank is not None):
            c += C_PAWN_DISAMB          # a pawn move never names its file: "gg4" is Rg4
        ff, fr = chess.square_file(m.from_square), chess.square_rank(m.from_square)
        need_file = need or (pt == PAWN and is_cap)
        need_rank = same_file
        if p.dfile is not None:
            fc = p.dfile.get(ff)
            if fc is None:
                # long notation names the square the piece leaves: another square
                # is no reading of it ("Bf1-d4" is not d2-d4)
                c += C_LONG_FROM if long_form else C_DISAMB_WRONG
            else:
                c += fc + (0.0 if need_file or long_form else C_DISAMB_EXTRA)
        elif need_file and not (need_rank and p.drank is not None):
            c += C_DISAMB_MISSING
        if p.drank is not None:
            rc = p.drank.get(fr)
            if rc is None:
                c += C_LONG_FROM if long_form else C_DISAMB_WRONG
            else:
                c += rc + (0.0 if need_rank or long_form or (need and p.dfile is None)
                           else C_DISAMB_EXTRA)
        elif need_rank and p.dfile is None:
            c += C_DISAMB_MISSING
        if m.promotion:
            prc = self.promo_costs(p.promo)
            if prc is None:
                c += 0.4 if m.promotion == QUEEN else 1.2
            else:
                c += prc[m.promotion]
        elif p.promo is not None:
            c += C_PROMO_EXTRA
        return c, pc

    def candidates(self, board: chess.Board, parsed: _Parsed, limit: float = MAX_COST):
        """Every legal move that explains the token, cheapest first.

        Returns [(move, cost, glyph, glyph cost, board after the move, parse)].
        The boards are shared through a cache and must not be changed in place.
        """
        key = (board._transposition_key(), parsed.raw, limit)
        hit = self._cand_cache.get(key)
        if hit is not None:
            return hit
        out = []
        if parsed.castle:
            for m in board.generate_castling_moves():
                side = "K" if chess.square_file(m.to_square) > chess.square_file(m.from_square) else "Q"
                c = 0.0 if side == parsed.castle else C_CASTLE_OTHER
                b2 = board.copy(stack=False)
                b2.push(m)
                c += self._check_cost(b2, parsed.check)
                if c <= limit:
                    out.append((m, c, None, 0.0, b2, None))
        else:
            by_dest, mask = self._index(parsed)
            info = [(m, board.piece_type_at(m.from_square))
                    for m in board.generate_legal_moves(chess.BB_ALL, mask)
                    if not board.is_castling(m)] if mask else []
            groups = Counter((pt, m.to_square, m.promotion) for m, pt in info)
            for m, pt in info:
                is_cap = board.is_capture(m)
                need = groups[(pt, m.to_square, m.promotion)] > 1
                ff = chess.square_file(m.from_square)
                same_file = need and sum(
                    1 for o, opt in info
                    if opt == pt and o.to_square == m.to_square and o.promotion == m.promotion
                    and chess.square_file(o.from_square) == ff) > 1
                best, glyph, best_pc, best_p = math.inf, None, 0.0, None
                for p, dc in by_dest.get(m.to_square, ()):
                    c, pc = self._reading_cost(board, m, pt, p, dc, is_cap, need, same_file, best)
                    if c < best:
                        best, glyph, best_pc, best_p = c, p.prefix, pc, p
                if best <= limit:
                    b2 = board.copy(stack=False)
                    b2.push(m)
                    best += self._check_cost(b2, parsed.check)
                    if best <= limit:
                        out.append((m, best, glyph, best_pc, b2, best_p))
        out.sort(key=lambda t: t[1])
        if len(self._cand_cache) > 50000:
            self._cand_cache.clear()
        self._cand_cache[key] = out
        return out

    def relaxed(self, board: chess.Board, parsed: _Parsed):
        """[(move, resemblance cost, parse)] for every legal move, closest first.

        Used for a token that no reading explains: any character may then be
        misread (C_UNREAD), so that the move assumed in its place is one that
        looks like the text, among those the following moves allow.
        """
        g = self.glyphs
        out = []
        for m in board.legal_moves:
            pt = board.piece_type_at(m.from_square)
            f, r = chess.square_file(m.to_square), chess.square_rank(m.to_square)
            best, best_p = 3 * C_UNREAD, None
            if parsed.castle and board.is_castling(m):
                best = 0.5
            for p in parsed.parses:
                c = (g.file_costs(p.fch, p.rch is None).get(f, C_UNREAD)
                     + g.rank_costs(p.rch, p.fch is None).get(r, C_UNREAD)
                     + min(self.piece_costs(p.prefix)[pt], 4.0))
                if (p.cap is True) != board.is_capture(m):
                    c += 0.8
                if c < best:
                    best, best_p = c, p
            out.append((m, best, best_p))
        out.sort(key=lambda t: t[1])
        return out

    @staticmethod
    def _check_cost(after: chess.Board, check: int) -> float:
        gives = after.is_check()
        if check == 3:
            if not gives:
                return C_MATE_FALSE
            return 0.0 if after.is_checkmate() else 0.5
        if check:
            return 0.0 if gives else C_CHECK_FALSE
        return C_CHECK_MISSING if gives else 0.0


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------
# Words are split on real spaces and line breaks only: figurine junk contains
# control characters ("\x1d") that Python counts as white space.
_SPACE_RE = re.compile(r"[^ \n\r\f\u00a0\u2028\u2029\u3000]+")
_NUM_DOTS_RE = re.compile(r"^([0-9lIOoSsB|]{1,3})([.…•·]+)(.*)$", re.S)
_BARE_NUM_RE = re.compile(r"^[0-9lIOoSsB|]{1,3}$")
_DOTS_ONLY_RE = re.compile(r"^[.…•·]+$")
_LEAD_DOTS_RE = re.compile(r"^([.…•·]+)(.+)$", re.S)
_GLUE_AFTER = set("12345678t+#!?)")
_GLUED_NUM_RE = re.compile(r"([0-9][0-9lIOo]{0,2}|[lI][0-9lIOo]{0,2}|[sS])(?=[.…•·]+\S)")
_DOTLESS_RE = re.compile(r"^(\d{1,3})(?=[^\d.…•·])(.+)$", re.S)
_ONE_GLYPH_RE = re.compile(r"^[1Il](?=J[^ ])")
# Words after which a number names a diagram, a page or an exercise.
_REF_WORD_RE = re.compile(r"^(?:[DO][il1]a?gr[ae](?:m|rn|in)s?|Diag\.?|Positions?|Pos\.?|Nos?\.|"
                          r"[Pp]ages?|pp?\.|Fig(?:ure)?s?\.?|Exercises?|Problems?|Games?|"
                          r"Chapters?|Studies|Study)$")
_ANNOT_RE = re.compile(r"^(?:[!?]{1,2}|\([!?]{1,2}\)|[+#†‡]|tt?|=|±|∓|\+-|-\+|=\+|\+=)$")
_LAYOUT_RE = re.compile(r"^(?:\d{1,3}[a-d]?|[a-h]|[A-H])$")
_PIECE_WORD_RE = re.compile(r"^[A-Z][a-z]?[a-h1-8]?[x:]?[a-h£tqo][lIiSsBbGZz]$")
_STRONG_RE = re.compile(r"([a-h£tqo])['`’]?([1-8])(?:=\S{0,4}|[^\d\s]{1,3})?$")
_DIGIT_MAP = str.maketrans({"l": "1", "I": "1", "|": "1", "O": "0", "o": "0",
                            "S": "8", "s": "8", "B": "8"})
# Short English words that end like a square ("as" = a8, "del" = d1); in other
# languages such words rarely sit where a move is expected.
_STOP_WORDS = {
    "as", "has", "was", "is", "his", "this", "be", "he", "she", "all", "us", "yes", "its",
    "es", "das", "des", "les", "las", "los", "del", "el", "al", "il", "of", "if",
    "goes", "does", "lies", "uses", "tel", "feel", "deal", "real", "dual", "ideal",
    "eg", "cf", "ch", "ah", "oh", "aha", "ha", "ed", "led", "fed", "bed", "ted", "web",
    "rob", "bob", "job", "mob", "sob", "cob", "gob", "hob", "lob", "fob",
    "makes", "takes", "moves", "loses", "gives", "comes", "lines", "files", "games", "times",
    "cases", "bases", "rates", "dates", "notes", "goal", "coal", "foal", "heel", "peel",
}


def _read_number(digits: str) -> list[int]:
    """Possible values of a move number printed as digits (OCR letters allowed)."""
    d = digits.replace(" ", "").replace("\n", "")
    if not d or len(d) > 3:
        return []
    if not any(ch.isdigit() for ch in d) and (len(d) > 2 or "B" in d):
        return []
    base = d.translate(_DIGIT_MAP)
    if not base.isdigit() or base[0] == "0":
        return []
    vals = [int(base)]
    if any(ch in "Ss" for ch in d):
        alt = d.translate(str.maketrans({"S": "5", "s": "5"})).translate(_DIGIT_MAP)
        if alt.isdigit() and alt[0] != "0" and int(alt) not in vals:
            vals.append(int(alt))
    return vals


@lru_cache(maxsize=100000)
def _shape(w: str) -> Optional[str]:
    """'strong', 'weak' or None: how much a word looks like a move.

    Strong: a real digit for the rank with a file letter (or a usual OCR
    stand-in) before it, or castling. Weak: some reading as a move exists, but
    only through letters read as digits or a missing file or rank.
    """
    if not w or len(w) > 16 or _RESULT_RE.match(w):
        return None
    core, _, _ = _strip_suffix(w)
    if not core:
        return None
    cc = core.replace(" ", "")
    if _CASTLE_RE.match(cc) and any(ch in "-–—_" for ch in cc):
        return "strong"
    if (core.isdigit() and len(core) > 1) or core in "09":
        return None
    if core in _STOP_WORDS or core.lower() in _STOP_WORDS and core[1:].islower():
        return None
    parses = _parse_raw(w).parses
    if not parses or (core.isalpha() and all(p.rch is None for p in parses)):
        return None          # a word whose only reading lacks a rank ("Or", "and")
    m = _STRONG_RE.search(core)
    if m:
        pre = core[:m.start()]
        if not (pre.isalpha() and pre.islower() and len(pre) >= 4):
            return "strong"
    if core.isalpha() and core.islower() and (len(core) >= 6 or core[-1] in "acdefgh" or (
            len(core) >= 4 and not re.search(r"[a-h£tqo][lIiSsBbGZz]$", core))):
        return None          # a lowercase word ("and", "mate"), unless it ends like a square ("ttlel")
    if (core.isalpha() and len(core) >= 3 and core[0].isupper() and core[1:].islower()
            and not _PIECE_WORD_RE.match(core)):
        return None          # a capitalised word, unless it reads as "Rel" (Re1) or "Ncb" (Nc6)
    return "weak"


# Short English words that stand before a square in prose ("and d4").
_COMMON_WORDS = {"and", "or", "the", "in", "on", "at", "to", "by", "with", "then", "if", "of",
                 "but", "not", "so", "for", "from", "than", "when", "via", "onto", "into",
                 "a", "an", "is", "are", "was", "be", "its", "his", "her", "no", "nor", "yet",
                 "now", "both", "each", "all", "only", "while", "after", "also", "since"}

_LONG_TAIL_RE = re.compile(r"^[-–][a-h£][1-8lIBSs]")
_LONG_HEAD_RE = re.compile(r"[a-h£][1-8lIBSs]$")


def _plain_square_start(w: str) -> bool:
    return bool(re.match(r"^[a-h£]?[x:]?[a-h£]['`]?[1-8lIBSs]", w))


def _pieces(text: str) -> list[tuple[int, int]]:
    """Space-separated pieces, with brackets and stray punctuation split off."""
    out = []
    for m in _SPACE_RE.finditer(text):
        s, e = m.span()
        lead = []
        while s < e and text[s] in "([{" and not _PAREN_ANN.match(text[s:e]):
            lead.append((s, s + 1))
            s += 1
        trail = []
        while e > s:
            w = text[s:e]
            ch = w[-1]
            mm = _PAREN_ANN.search(w)
            if mm and mm.start() > 0:
                trail.append((s + mm.start(), e))
                e = s + mm.start()
            elif ch == ")" and "=" in w[:-1] and _open_parens(text, s) <= 0:
                break           # "d8=lt)": the bracket is part of a promotion glyph
            elif ch in ")]}" or (ch in ",;" and e - s >= 2):
                trail.append((e - 1, e))
                e -= 1
            elif (ch == "." and e - s >= 2 and w[-2] in "12345678#+!?t"
                  and not re.match(r"^[0-9lIOoSsB|]{1,3}[.…•·]+$", w)):
                trail.append((e - 1, e))
                e -= 1
            else:
                break
        out.extend(lead)
        if s < e:
            pos = s          # numbers glued to the end of the previous move: "xd4t10.Kc3"
            while True:
                cut = _glue_cut(text, pos, e)
                if cut is None:
                    break
                out.append((pos, cut))
                pos = cut
            out.append((pos, e))
        out.extend(reversed(trail))
    # castling split by a space: "o -o", "0- 0-0"
    k = 0
    while k + 1 < len(out):
        (a, b), (c, d) = out[k], out[k + 1]
        if c - b == 1 and text[b] == " " and _SPLIT_CASTLE_RE.match(text[a:b] + text[c:d]) \
                and _CASTLE_RE.match(_strip_suffix(text[a:b] + text[c:d])[0]):
            out[k:k + 2] = [(a, d)]
            continue
        k += 1
    return out


_SPLIT_CASTLE_RE = re.compile(r"^[0Oo][-–][0Oo](?:[-–][0Oo])?[+#!?t]*$")


def _open_parens(text: str, pos: int, window: int = 300) -> int:
    """Parentheses opened and not closed in the text just before pos."""
    a = max(0, pos - window)
    return text.count("(", a, pos) - text.count(")", a, pos)


def _glue_cut(text: str, s: int, e: int) -> Optional[int]:
    """Where a move number glued to the end of a move starts, if one does.

    Of the possible cuts, the first that leaves a complete move on the left
    wins ("Ngt66.Bd3" is "Ngt6" + "6.", not "Ngt" + "66.").
    """
    first = None
    for p in range(s + 2, e - 1):
        if text[p - 1] not in _GLUE_AFTER:
            continue
        g = _GLUED_NUM_RE.match(text, p, e)
        if not g or not _read_number(g.group(1)):
            continue
        if _STRONG_RE.search(text[s:p]) or _CASTLE_RE.match(text[s:p].rstrip("+t#!?")):
            return p
        # Otherwise the left part must at least hold a file letter: glyph junk
        # that ends in a digit and a dot ("'!1.c7" for Rc7) is not a move
        # followed by a glued move number.
        if first is None and re.search(r"[a-h£]", text[s:p]):
            first = p
    return first


_SQUARE_END_RE = re.compile(r"[a-h£][1-8][+#!?]*")
_BARE_SQUARE_RE = re.compile(r"^[a-h][1-8]$")


@lru_cache(maxsize=20000)
def _glued_moves(w: str) -> Optional[int]:
    """Where a second move starts in a word that holds two moves printed without
    a space ("lDc4lDg6", "Nf3Nc6"), if it does. Both parts must look clearly
    like moves; two bare squares ("e2e4") are one move in long notation."""
    if len(w) < 5:
        return None
    for m in _SQUARE_END_RE.finditer(w, 2):
        p = m.end()
        left, right = w[:p], w[p:]
        if len(right) < 3 or right[0] in "-–—x:×=+#!?.,;()" or right[0].isdigit():
            continue
        if _shape(left) != "strong" or _shape(right) != "strong":
            continue
        if _BARE_SQUARE_RE.match(left) and _BARE_SQUARE_RE.match(_strip_suffix(right)[0]):
            continue
        return p
    return None


# Letters that OCR prints for a one-digit move number ("g Nxes" for 9 Nxe5).
_OCR_NUMBER_WORDS = {"g": 9, "s": 5, "S": 5, "l": 1, "I": 1}


# Digits that OCR takes for one another.
_DIGIT_SLIPS = {("1", "7"), ("7", "1"), ("3", "8"), ("8", "3"), ("5", "6"), ("6", "5"),
                ("5", "8"), ("8", "5"), ("6", "8"), ("8", "6"), ("0", "8"), ("8", "0")}


def _ocr_digit_slip(printed: str, want: int) -> bool:
    """True when a printed number differs from want in one digit that OCR
    commonly misreads ("11" for 17)."""
    p = re.sub(r"\D", "", printed)
    w = str(want)
    if len(p) != len(w):
        return False
    diff = [(a, b) for a, b in zip(p, w) if a != b]
    return len(diff) == 1 and diff[0] in _DIGIT_SLIPS


def _prose_word(w: str) -> bool:
    """A word of prose ("Answer:", "Black,", "Both", "White's", "GM's"), which
    is never an unreadable move nor a glyph split from its square."""
    if re.fullmatch(r"[A-Za-z]{2,}['’]s[:.,;]*", w):
        return True
    if re.fullmatch(r"[A-Z]?(?=[a-z]*[aeiouy])[a-z]{4,}:", w):
        return True                  # "Answer:", "Question:": no move has four small letters

    return bool(re.fullmatch(r"[A-Z]?(?=[a-z]*[aeiouy])[a-z]{3,}[:.,;]*|[A-Z][A-Z]{3,}[:.,;]*", w)) \
        and not _shape(w) and not _PIECE_WORD_RE.match(w)


def _square_word(w: str) -> bool:
    """A short word that reads as a square ("es" for e5, "as" for a5)."""
    core = _strip_suffix(w)[0]
    return bool(re.fullmatch(r"[a-h][1-8lIiSsBbGZz]", core))


def _move_like(w: str) -> bool:
    """A weakly shaped word that still has a move's build: a piece letter before
    a file letter ("Bbs", "Raes") or a capture between two files ("gxfs")."""
    core = _strip_suffix(w)[0]
    return bool(re.match(r"^(?:[KQRBN][a-h1-8]?x?|[a-h]x)[a-h£][1-8lIiSsBbGZz]$", core))


def _alone_on_line(text: str, s: int, e: int) -> bool:
    a = text.rfind("\n", 0, s)
    b = text.find("\n", e)
    return (not text[a + 1:s].strip(" \u00a0")
            and not text[e:b if b >= 0 else len(text)].strip(" \u00a0"))


def _dot_count(text: str, spans) -> int:
    return sum(sum(3 if ch == "…" else 1 for ch in text[s:e] if ch in DOT_CHARS) for s, e in spans)


class _TokState:
    """Where the tokenizer stands in the numbering of the current run."""

    def __init__(self):
        self.in_seq = False
        self.last_num: Optional[int] = None
        self.last_black = False
        self.moves_since = 0
        self.prev = None            # kind of the previous significant token

    def expect(self):
        if self.last_num is None:
            return None, None
        ply = (self.last_num - 1) * 2 + int(self.last_black) + self.moves_since
        return ply // 2 + 1, bool(ply % 2)


def _collect_dots(text, pieces, j, groups):
    """Gather dot groups from piece j on. Returns (j, move_span or None)."""
    while j < len(pieces):
        a, b = pieces[j]
        w = text[a:b]
        if _DOTS_ONLY_RE.match(w):
            groups.append((a, b))
            j += 1
            continue
        ml = _LEAD_DOTS_RE.match(w)
        if ml:
            d = len(ml.group(1))
            if d == 1 and groups:
                return j + 1, (a, b)            # that dot belongs to the glyph (".ic4")
            groups.append((a, a + d))
            return j + 1, (a + d, b)
        break
    return j, None


def _side(text, groups, rest) -> tuple[bool, bool]:
    """(black, side_known) from the dots after a move number."""
    c = _dot_count(text, groups)
    glyph_dot = rest is not None and text[rest[0]] in DOT_CHARS
    attached = rest is not None and bool(groups) and groups[-1][1] == rest[0]
    if c == 1:
        return False, True
    if glyph_dot and c >= 2:
        return True, False                      # "5 ... .ixf3" or "3 … .ic4"
    if c == 2 and len(groups) == 1 and attached:
        return True, False                      # "6..id3" or "1..Ra6"
    return True, True


def _scan_number(text, pieces, i, st: Optional[_TokState], dotless: bool = False):
    """Read a move number starting at piece i: (token, next index, move span) or None.

    With dotless, a number printed without dots ("12 Nf3") also counts when
    the word after it looks like a move; the token then has dotless=True and
    the caller decides from the context whether it is a move number at all.
    """
    s, e = pieces[i]
    w = text[s:e]
    digit_spans, groups, rest = [], [], None
    m = _NUM_DOTS_RE.match(w)
    if m:
        de = s + len(m.group(1))
        digit_spans.append((s, de))
        groups.append((de, de + len(m.group(2))))
        if m.group(3):
            rest = (de + len(m.group(2)), e)
        j = i + 1
    elif _BARE_NUM_RE.match(w):
        digit_spans.append((s, e))
        j = i + 1
        # digits split by a space: "1 8.g6", "1 1 .Bxf6"
        while j < len(pieces) and len(digit_spans) < 3 and rest is None:
            a, b = pieces[j]
            if a - digit_spans[-1][1] != 1 or text[a - 1] != " ":
                break
            w2 = text[a:b]
            m2 = _NUM_DOTS_RE.match(w2)
            d2 = m2.group(1) if m2 else (w2 if _BARE_NUM_RE.match(w2) else None)
            if d2 is None or len(d2) != 1 or sum(b_ - a_ for a_, b_ in digit_spans) != 1:
                break
            if st is not None and st.in_seq and st.prev == "move":
                exp_n, _ = st.expect()
                joined = _read_number(text[digit_spans[0][0]:digit_spans[0][1]] + d2)
                alone = _read_number(d2)
                if exp_n is not None and not ({exp_n, exp_n + 1} & set(joined)) \
                        and ({exp_n, exp_n + 1} & set(alone)):
                    break
            digit_spans.append((a, a + len(d2)))
            j += 1
            if m2:
                ge = a + len(d2) + len(m2.group(2))
                groups.append((a + len(d2), ge))
                if m2.group(3):
                    rest = (ge, b)
                break
    else:
        return None
    if rest is None:
        j, rest = _collect_dots(text, pieces, j, groups)
        if (dotless and m is None and len(groups) == 1 and groups[0][1] - groups[0][0] == 1
                and rest is not None and rest[0] == groups[0][1]):
            # a book without dots: "13 .txd5" is 13 and a glyph (".t") that starts
            # with a dot
            rest, groups = (groups[0][0], rest[1]), []
    if not groups:
        return _dotless_number(text, pieces, digit_spans, j, st, rest) if dotless else None
    digits = " ".join(text[a:b] for a, b in digit_spans)
    vals = _read_number(digits)
    if not vals:
        return None
    num = vals[0]
    if st is not None and st.in_seq:
        exp_n, _ = st.expect()
        if exp_n in vals:
            num = exp_n
    black, known = _side(text, groups, rest)
    start, end = digit_spans[0][0], groups[-1][1]
    return Token("number", text[start:end], start, end, num, black, known), j, rest


MAX_DOTLESS = 200      # highest move number read without a dot


def _dotless_number(text, pieces, digit_spans, j, st, rest=None):
    """A move number printed without dots ("12 Nf3", the digits split "1 1 Nb5"):
    (token, next index, move span) when the word after it looks like a move.
    rest is the move's span when it is already known (else piece j); the
    move span returned is None when the move is piece j."""
    digits = " ".join(text[a:b] for a, b in digit_spans)
    vals = _read_number(digits)
    if not vals or vals[0] > MAX_DOTLESS or (rest is None and j >= len(pieces)):
        return None
    if not re.fullmatch(r"[0-9]+(?: [0-9]+)*", digits):
        # "I" and "s" are words in prose: an OCR letter read as a digit ("s Bbs"
        # for 5 Bb5) counts only where the run expects that very number, or for
        # an "S" or "s" alone before a clear move ("Answer: S lbd2!")
        exp = st.expect() if st is not None and st.in_seq and st.prev == "move" else (None, None)
        a, b = rest or pieces[j]
        alone = ((digits in ("S", "s") or (len(digits) >= 2 and digits[0].isdigit()))
                 and _shape(text[a:b]) == "strong")
        if not alone and (exp[0] is None or (exp[0] + 1 if exp[1] else exp[0]) not in vals):
            return None
    a, b = rest or pieces[j]
    w2 = text[a:b]
    if (_NUM_DOTS_RE.match(w2) or _BARE_NUM_RE.match(w2) or _RESULT_RE.match(w2)
            or w2 in "([{)]}" or not (_shape(w2) or _square_word(w2))):
        return None
    num = vals[0]
    if st is not None and st.in_seq:
        exp_n, _ = st.expect()
        if exp_n in vals:
            num = exp_n
    start, end = digit_spans[0][0], digit_spans[-1][1]
    return Token("number", text[start:end], start, end, num, False, True, dotless=True), j, rest


def _scan_continuation(text, pieces, i):
    """A bare "..." before a Black move: (token, next index, move span) or None."""
    groups = []
    j, rest = _collect_dots(text, pieces, i, groups)
    if not groups or _dot_count(text, groups) < 2:
        return None
    if rest is None:
        if j >= len(pieces):
            return None
        rest = pieces[j]
        j += 1
    if not _shape(text[rest[0]:rest[1]]):
        return None
    s, e = groups[0][0], groups[-1][1]
    return Token("number", text[s:e], s, e, None, True, True), j, rest


def tokenize(text: str, lenient: bool = False, dotless: bool = False) -> list[Token]:
    """Split book text into number, move, result and other tokens.

    Offsets index into text and raw == text[start:end]. A word becomes a move
    only inside a numbered run: right after a move number or a "..."
    continuation, or after another move of the run. Elsewhere chess-looking
    words ("a5", "be") come out as 'other'.

    lenient is for text that holds moves only (the main-line font of a book
    with a distinct move font): there a short word of junk that stands
    exactly where the numbering expects a move ("16.b3 gam 17.Bb2") or that
    ends in an annotation ("Nf5 ttlge???") is kept as a move, so that the run
    goes on and the unreadable move shows.

    dotless is for books that print move numbers without a dot ("1 e4 c5
    2 Nc3", see uses_dotless_numbers()). A number with no dot then counts as
    a move number when the word after it looks like a move and the number
    fits: inside a run it must be the number the run expects next; elsewhere
    the word after it must look clearly like a move ("13 Bh6", not "2 pawns"),
    and no word such as "Diagram" or "page" may stand before it. Whether the
    move is legal is for decode() to tell.
    """
    pieces = _pieces(text)
    toks: list[Token] = []
    st = _TokState()

    def other(s, e, layout=False):
        toks.append(Token("other", text[s:e], s, e, layout=layout))
        if not layout:
            st.in_seq = False
            st.prev = "other"

    def move(s, e):
        cut = _glued_moves(text[s:e])
        if cut:                                  # two moves printed without a space
            move(s, s + cut)
            move(s + cut, e)
            return
        n, b = st.expect()
        if n is None:                            # after a bare "...": sides alternate
            b = st.last_black == (st.moves_since % 2 == 0)
        toks.append(Token("move", text[s:e], s, e, n, bool(b)))
        st.moves_since += 1
        st.in_seq = True
        st.prev = "move"

    def number(tok):
        toks.append(tok)
        st.last_num, st.last_black, st.moves_since = tok.number, tok.black, 0
        st.in_seq = True
        st.prev = "number"

    def next_is_boundary(j):
        """True when piece j starts a number, a result, a bracket or the end."""
        if j >= len(pieces):
            return True
        a, b = pieces[j]
        w = text[a:b]
        if _RESULT_RE.match(w) or w in ")]};,([" or _DOTS_ONLY_RE.match(w):
            return True
        if dotless and w in _OCR_NUMBER_WORDS and j + 1 < len(pieces) \
                and _shape(text[pieces[j + 1][0]:pieces[j + 1][1]]) == "strong":
            return True                  # "cs s .i.g2": 5 printed as "s"
        return _scan_number(text, pieces, j, None, dotless) is not None

    def next_is_strong(j):
        return j < len(pieces) and _shape(text[pieces[j][0]:pieces[j][1]]) == "strong"

    def after_number(s, e, j):
        """Classify the word right after a move number; returns the next index."""
        w = text[s:e]
        if _RESULT_RE.match(w):
            toks.append(Token("result", w, s, e))
            st.in_seq, st.prev = False, "result"
            return j
        if (w.isdigit() and j > 0 and pieces[j - 1] == (s, e) and j < len(pieces)
                and _shape(text[pieces[j][0]:pieces[j][1]])):
            return j - 1                         # "6 ••• 7 g4": the move is missing, 7 is a number
        if w.endswith(":") and _prose_word(w) and j < len(pieces) \
                and _shape(text[pieces[j][0]:pieces[j][1]]):
            # "11 Answer: d4": a label of the book's question-and-answer
            # layout between a move number and its move
            other(s, e, layout=True)
            return after_number(pieces[j][0], pieces[j][1], j + 1)
        if (w in ("A", "I") and j < len(pieces) and _prose_word(text[pieces[j][0]:pieces[j][1]])) \
                or re.fullmatch(r"[A-Za-z]{2,}['’]s[:.,;]*", w) \
                or (w.endswith(":") and _prose_word(w)):
            other(s, e)                          # "1. A pawn ...", "4. White's": a numbered list
            return j
        if _shape(w) or (_parse_raw(w).parses and not w[:1].isupper()
                         and (next_is_boundary(j) or next_is_strong(j))):
            move(s, e)
            return j
        if j < len(pieces) and len(w) <= 5 and not any(ch.isdigit() for ch in w) \
                and pieces[j][0] - e == 1 and not _prose_word(w):
            a, b = pieces[j]                     # a glyph split from its square: "V d8#"
            w2 = text[a:b]
            if _plain_square_start(w2) and _shape(w2) == "strong":
                move(s, b)
                return j + 1
        if (not w.isalpha() and len(w) <= 10 and not _ANNOT_RE.match(w) and w not in "([{)]}"
                and any(ch.isalnum() or ord(ch) < 32 for ch in w) and not _prose_word(w)
                and not w.isdigit()):
            move(s, e)                           # unreadable, kept so that the run goes on
            return j
        other(s, e)
        return j

    def split_rank(i, w):
        """A rank digit split from a move that lacks one: "i.xd 1" for Bxd1."""
        if not re.fullmatch(r"[1-8]", w) or toks[-1].kind != "move":
            return False
        prev = toks[-1].raw
        core = _strip_suffix(prev)[0]
        if not re.search(r"[a-h£]$", core) or any(p.rch is not None
                                                  for p in _parse_raw(prev).parses):
            return False
        if i + 1 < len(pieces):
            nxt = text[pieces[i + 1][0]:pieces[i + 1][1]]
            m = _NUM_DOTS_RE.match(nxt)
            if _DOTS_ONLY_RE.match(nxt):
                return False
            if m:                        # "exd 1 8.Nf3": a split move number 18?
                exp_n, exp_b = st.expect()
                after = exp_n + 1 if (exp_n is not None and exp_b) else exp_n
                joined = _read_number(w + m.group(1))
                if after is not None and after in joined and after not in _read_number(m.group(1)):
                    return False
        return True

    def slot_before_number(j):
        """True when piece j is the move number that follows exactly one more move
        (also a number glued to its move without a dot: "14J\x1dhcl")."""
        if j >= len(pieces):
            return False
        exp_n, exp_b = st.expect()
        if exp_n is None:
            return False
        want = (exp_n + 1, False) if exp_b else (exp_n, True)
        r = _scan_number(text, pieces, j, None, dotless)
        if r is None:
            mg = _DOTLESS_RE.match(text[pieces[j][0]:pieces[j][1]])
            return bool(mg) and not want[1] and int(mg.group(1)) == want[0] \
                and bool(_shape(mg.group(2)))
        tok = r[0]
        return want[0] in _number_values(tok) and (not tok.side_known or tok.black == want[1])

    def dotless_ok(tok, j, rest):
        """Whether a number printed without a dot is a move number here (the
        move is the span rest, or else piece j)."""
        if rest is None:
            w2 = text[pieces[j][0]:pieces[j][1]]
            j += 1
        else:
            w2 = text[rest[0]:rest[1]]
        shp = _shape(w2)
        exp_n, exp_b = st.expect()
        vals = _number_values(tok)
        if st.in_seq and st.prev == "move" and exp_n is not None:
            want = exp_n + 1 if exp_b else exp_n
            if want in vals:
                tok.number = want
                return True
            if exp_b and exp_n in vals:
                # the number repeated before Black's reply, as in books that set
                # the moves as a table ("12 ltJd5" / "12 ttJxd5")
                tok.number, tok.black, tok.side_known = exp_n, True, False
                return True
            if _ocr_digit_slip(tok.raw, want) and shp:
                tok.number = want          # "16 ... hs 11 tl)1h2": 17 with its 7 read as 1
                return True
        # out of the run's numbering, a number without dots names no side: it
        # stands before Black's reply too in books that set moves as a table
        tok.side_known = False
        if shp == "strong":
            return True
        if shp != "weak":
            # a word that is also a square ("es" for e5) only with a move's
            # annotation or between moves
            return _square_word(w2) and (_strip_suffix(w2)[2] != "" or next_is_boundary(j)
                                         or next_is_strong(j))
        core = _strip_suffix(w2)[0]
        if not core.isalpha() or _move_like(w2):
            return True              # junk glyph, piece letter or capture: "dxeS", "Bbs"
        return (next_is_boundary(j) or next_is_strong(j) or text[pieces[j][0]] == "("
                or _move_like(text[pieces[j][0]:pieces[j][1]]))

    def lenient_move(i, w):
        if not lenient or len(w) > 10 or _ANNOT_RE.match(w) or _RESULT_RE.match(w) \
                or not any(ch.isalpha() for ch in w) \
                or (_prose_word(w) and (not w.isalpha() or len(w) >= 5 or w[0].isupper())):
            return False
        if re.fullmatch(r"[^ ]{2,8}[!?]{1,3}", w) and re.search(r"[a-h£]", w[:-1]):
            return True                  # "ttlge???": a move with its rank lost
        return slot_before_number(i + 1) and not (w.isalpha() and w.lower() in _STOP_WORDS)

    i = 0
    while i < len(pieces):
        s, e = pieces[i]
        w = text[s:e]
        if toks and toks[-1].kind == "move" and s - toks[-1].end <= 2 and (
                _ANNOT_RE.match(w)                                   # "e4 !"
                or (_LONG_TAIL_RE.match(w) and _LONG_HEAD_RE.search(toks[-1].raw))  # "e7 -e5"
                or (toks[-1].raw[-1:] in "-–" and _plain_square_start(w))          # "e7- e5"
                or split_rank(i, w)):
            t = toks[-1]                         # the rest of the same move
            toks[-1] = replace(t, raw=text[t.start:e], end=e)
            i += 1
            continue
        if _RESULT_RE.match(w):
            toks.append(Token("result", w, s, e))
            st.in_seq, st.prev = False, "result"
            i += 1
            continue
        if w in "([{)]}" or (len(w) == 1 and w.isalpha() and text[e:e + 1] == ")"
                             and (s == 0 or text[s - 1] in " \n(")):
            other(s, e)                          # a label of a list of lines: "A) 8.Be4"
            i += 1
            continue
        r = _scan_number(text, pieces, i, st, dotless)
        if r is not None and r[0].dotless and not dotless_ok(*r):
            r = None
        if r is not None and i > 0 and pieces[i - 1][1] < s \
                and _REF_WORD_RE.match(text[pieces[i - 1][0]:pieces[i - 1][1]]):
            r = None                     # "Position 68. The": a number in the text
            other(s, e)
            i += 1
            continue
        if r is not None:
            tok, j, rest = r
            number(tok)
            if rest is not None:
                i = after_number(rest[0], rest[1], j)
            elif j < len(pieces):
                i = after_number(pieces[j][0], pieces[j][1], j + 1)
            else:
                i = j
            continue
        r = _scan_continuation(text, pieces, i)
        if r is not None:
            tok, j, rest = r
            exp_n, exp_b = st.expect()
            if st.in_seq and st.prev == "move" and exp_b:
                tok.number = exp_n
            toks.append(tok)
            st.last_num, st.last_black, st.moves_since = tok.number, True, 0
            st.in_seq, st.prev = True, "number"
            i = after_number(rest[0], rest[1], j)
            continue
        mj = _ONE_GLYPH_RE.match(w)
        if mj and not (st.in_seq and st.prev == "move") and _shape(w[1:]) == "strong":
            # "1." printed with its dot lost before a glyph that starts with
            # "J" ("IJ\x1dd2!", "1J\x1dg4!" for 1.Rd2!, 1.Rg4!)
            number(Token("number", text[s:s + 1], s, s + 1, 1, False, True))
            move(s + 1, e)
            i += 1
            continue
        if (st.in_seq and st.prev == "move" and _BARE_NUM_RE.match(w) and i + 1 < len(pieces)
                and pieces[i + 1][0] - e == 1):
            exp_n, exp_b = st.expect()
            nxt = text[pieces[i + 1][0]:pieces[i + 1][1]]
            if exp_n is not None and not exp_b and exp_n in _read_number(w) \
                    and _shape(nxt) == "strong" and not _NUM_DOTS_RE.match(nxt):
                # a move number whose dot was lost: "4...Bg4 5 Qb3"
                number(Token("number", w, s, e, exp_n, False, True))
                i = after_number(pieces[i + 1][0], pieces[i + 1][1], i + 2)
                continue
        mg = _DOTLESS_RE.match(w)
        if mg:                                   # dotless number glued to a move: "4JWxd8t"
            val, rest_w = int(mg.group(1)), mg.group(2)
            exp_n, exp_b = st.expect()
            in_ctx = st.in_seq and st.prev == "move" and exp_n == val and _shape(rest_w)
            alone = (len(mg.group(1)) >= 2 and _shape(rest_w) == "strong"
                     and not rest_w[0].islower() and not rest_w[0].isdigit())
            if dotless and not alone and _shape(rest_w) == "strong" \
                    and not rest_w[0].isdigit() and val <= MAX_DOTLESS:
                # a dotless book glues numbers to junk glyphs too: "25lt)c4"
                alone = not re.match(r"[a-h]x?[a-h]?[1-8]", rest_w) or len(mg.group(1)) >= 2
            if in_ctx or alone:
                ds = s + len(mg.group(1))
                number(Token("number", text[s:ds], s, ds, val, bool(exp_b) if in_ctx else False,
                             False))
                move(ds, e)
                i += 1
                continue
        if _LAYOUT_RE.match(w) and _alone_on_line(text, s, e):
            other(s, e, layout=True)             # diagram label or board coordinate
            i += 1
            continue
        if (st.in_seq and st.prev == "move" and i + 1 < len(pieces) and len(w) <= 5
                and not any(ch.isdigit() for ch in w) and pieces[i + 1][0] - e == 1
                and w.lower() not in _COMMON_WORDS and w.lower() not in _STOP_WORDS
                and not (w.isalpha() and w[:1].isupper() and w[1:].islower())):
            a, b = pieces[i + 1]                 # a glyph split from its square: "ttl d4"
            w2 = text[a:b]
            if (_plain_square_start(w2) and _shape(w2) == "strong"
                    and re.fullmatch(r"[a-h£]['`]?[1-8][^ ]{0,3}", w2)):
                move(s, b)
                i += 2
                continue
        if dotless and st.in_seq and st.prev == "move" and w in _OCR_NUMBER_WORDS \
                and i + 1 < len(pieces) and _shape(text[pieces[i + 1][0]:pieces[i + 1][1]]):
            exp_n, exp_b = st.expect()
            if exp_n is not None and not exp_b and exp_n == _OCR_NUMBER_WORDS[w]:
                # a one-digit move number that OCR read as a letter: "g Nxes" for 9 Nxe5
                number(Token("number", w, s, e, exp_n, False, True, dotless=True))
                i = after_number(pieces[i + 1][0], pieces[i + 1][1], i + 2)
                continue
        if st.in_seq and st.prev == "move" and not (
                w.isdigit() and i + 1 < len(pieces)
                and text[pieces[i + 1][0]:pieces[i + 1][1]].isdigit()
                and not (i + 2 < len(pieces)
                         and _DOTS_ONLY_RE.match(text[pieces[i + 2][0]:pieces[i + 2][1]]))):
            # (digits spaced out like a folio, "1 6 5", are no move)
            shp = _shape(w)
            if w.endswith(":") and _prose_word(w):
                shp = None                       # "Answer:" after a move is no move
            if shp == "strong" or (shp == "weak" and (
                    next_is_boundary(i + 1) or next_is_strong(i + 1) or _move_like(w)
                    or (i + 1 < len(pieces) and text[pieces[i + 1][0]] == "("))):
                move(s, e)
                i += 1
                continue
            if (w.lower() in _STOP_WORDS and next_is_boundary(i + 1)
                    and any(p.fch is not None and p.rch is not None
                            for p in _parse_raw(w).parses)):
                move(s, e)                       # "es" (e8) between a move and a number
                i += 1
                continue
            if lenient_move(i, w):
                move(s, e)                       # junk where a move must stand
                i += 1
                continue
        other(s, e)
        i += 1
    return toks


# ---------------------------------------------------------------------------
# The book's way of numbering moves
# ---------------------------------------------------------------------------
_PLAIN_MOVE = r"(?:[KQRBN]?[a-h1-8]?x?[a-h][1-8](?:=[QRBN])?|O-O(?:-O)?|0-0(?:-0)?)[+#!?]*"
_PAIR_DOTLESS_RE = re.compile(
    rf"(?<![\w.,])(\d{{1,3}}) {_PLAIN_MOVE}(?: {_PLAIN_MOVE})? (\d{{1,3}}) {_PLAIN_MOVE}(?!\w)")
_PAIR_DOTTED_RE = re.compile(
    rf"(?<![\w.,])(\d{{1,3}})\. ?{_PLAIN_MOVE}(?: {_PLAIN_MOVE})? (\d{{1,3}})\. ?{_PLAIN_MOVE}(?!\w)")
DOTLESS_MIN = 3           # dotless pairs a book must show ...
DOTLESS_SHARE = 0.08      # ... and their least share of the dotted pairs


def numbering_counts(texts: Iterable[str]) -> dict:
    """How often the text numbers moves with and without a dot.

    Only clean evidence counts: two consecutive move numbers with one or two
    plainly printed moves after the first ("3 f4 g6 4 Nf3" or "3.f4 g6 4.Nf3"),
    which prose never produces by accident."""
    out = {"dotless": 0, "dotted": 0}
    for t in texts:
        t = re.sub(r"\s+", " ", t)
        for key, rx in (("dotless", _PAIR_DOTLESS_RE), ("dotted", _PAIR_DOTTED_RE)):
            out[key] += sum(1 for m in rx.finditer(t) if int(m.group(2)) == int(m.group(1)) + 1)
    return out


def uses_dotless_numbers(texts: Iterable[str]) -> bool:
    """True when a book prints move numbers without a dot ("1 e4 c5 2 Nf3"), in
    all its moves or beside dotted numbers; tokenize() then reads such numbers."""
    c = numbering_counts(texts)
    return c["dotless"] >= DOTLESS_MIN and c["dotless"] >= DOTLESS_SHARE * c["dotted"]


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------
_PAREN_LIFE = 600


def _number_values(tok: Token) -> list:
    if tok.number is None:
        return []
    digits = re.match(r"^[0-9lIOoSsB| \n]+", tok.raw)
    vals = _read_number(digits.group(0)) if digits else []
    if tok.number not in vals:
        vals = [tok.number] + vals
    return vals


def _relabel(tokens: list, number: Optional[int], black: bool) -> tuple:
    """Number the tokens of a run from its first number; returns the next slot."""
    n, b = number, black
    out = []
    for t in tokens:
        if t.kind == "number":
            out.append(replace(t, number=n if n is not None else t.number, black=b,
                               side_known=t.side_known if t is tokens[0] else True))
            continue
        if t.kind == "move":
            out.append(replace(t, number=n, black=b))
            n, b = ((n + 1 if n is not None else None), False) if b else (n, True)
            continue
        out.append(t)
    tokens[:] = out
    return n, b


def find_sequences(text: str, lenient: bool = False, dotless: bool = False) -> list[Sequence]:
    """Maximal runs of moves that begin at a move number or a "..." continuation.

    Parenthesised sub-lines come out as runs of their own with depth > 0.
    Within a run, the side of each move follows the run's numbering, which
    also settles numbers whose dots could be read either way. lenient and
    dotless are passed to tokenize().
    """
    toks = tokenize(text, lenient, dotless)
    seqs: list[Sequence] = []
    opens: list[int] = []        # offsets of open parentheses
    cur: Optional[dict] = None

    def depth_at(pos):
        while opens and pos - opens[-1] > _PAREN_LIFE:
            opens.pop()
        return len(opens)

    def close():
        nonlocal cur
        if cur and any(t.kind == "move" for t in cur["tokens"]):
            ts = cur["tokens"]
            first = ts[0]
            seqs.append(Sequence(first.number, first.black, ts, first.start, ts[-1].end,
                                 cur["depth"], first.side_known))
        cur = None

    def fits(t, n, b):
        if t.number is None:
            return b and cur["tokens"][-1].kind == "move"
        return n in _number_values(t) and (not t.side_known or t.black == b)

    def one_ahead(t, n, b):
        """A number one move later than expected: a move is missing from the text."""
        if t.number is None or not t.side_known or n is None:
            return False
        nn, nb = (n + 1, False) if b else (n, True)
        return t.number == nn and t.black == nb and cur["tokens"][-1].kind == "move"

    for t in toks:
        if t.kind == "other":
            if t.layout or _ANNOT_RE.match(t.raw):
                continue
            if t.raw in "([{":
                close()
                depth_at(t.start)
                opens.append(t.start)
                continue
            if t.raw in ")]}":
                close()
                if opens:
                    opens.pop()
                continue
            close()
            continue
        if t.kind == "result":
            if cur:
                cur["tokens"].append(t)
            close()
            continue
        if t.kind == "number":
            if cur is not None:
                n, b = cur["next"]
                if not fits(t, n, b) and cur["flexible"] and t.number is not None:
                    # the run's first number could be read as either side
                    first = cur["tokens"][0]
                    trial = list(cur["tokens"])
                    n2, b2 = _relabel(trial, first.number, not first.black)
                    if fits(t, n2, b2):
                        cur["tokens"], cur["next"] = trial, (n2, b2)
                        n, b = n2, b2
                if fits(t, n, b):
                    # (a number without dots keeps naming no side, so that a run
                    # split from this one later can still be read either way)
                    cur["tokens"].append(replace(t, number=n if t.number is not None else n,
                                                 black=b, side_known=t.side_known or not t.dotless))
                    if t.side_known and t.number is not None and cur["flexible"]:
                        cur["flexible"] = False         # a later number settles the side
                        cur["tokens"][0] = replace(cur["tokens"][0], side_known=True)
                    continue
                if one_ahead(t, n, b) and not cur["flexible"]:
                    cur["tokens"].append(t)             # decode() supplies the missing move
                    cur["next"] = (t.number, t.black)
                    continue
            close()
            cur = {"tokens": [t], "depth": depth_at(t.start), "next": (t.number, t.black),
                   "flexible": not t.side_known}
            continue
        if t.kind == "move":
            if cur is None:
                continue
            n, b = cur["next"]
            cur["tokens"].append(replace(t, number=n, black=b))
            cur["next"] = ((n + 1 if n is not None else None), False) if b else (n, True)
            core, check, _ = _strip_suffix(t.raw)
            if check == 3:
                close()
    close()
    return seqs


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------
KAPPA_RUN = 2.0       # weight of the book prior against the junk's earlier uses in the run


class _Hyp:
    __slots__ = ("cost", "board", "node", "offset", "fails", "gmap")

    def __init__(self, cost, board, node, offset, fails, gmap):
        self.cost = cost
        self.board = board
        self.node = node
        self.offset = offset        # 1 when the run's numbering is one ply out
        self.fails = fails          # consecutive failed tokens
        self.gmap = gmap            # glyph -> {piece type: uses so far in this run}


def _forced_candidates(board: chess.Board, san: str):
    """The one reading a corrected token allows: its SAN, where it is legal."""
    try:
        m = board.parse_san(san)
    except ValueError:
        return []
    b2 = board.copy(stack=False)
    b2.push(m)
    return [(m, 0.0, None, 0.0, b2, None)]


def _token_candidates(scorer, board, tok, parsed, gmap):
    if getattr(tok, "forced", None):
        return _forced_candidates(board, tok.forced)
    return _adjusted(scorer.candidates(board, parsed), board, gmap, scorer)


def junk_prefix(raw: str, letters=None) -> Optional[str]:
    """The piece symbol of a move token that is neither a piece letter of the
    notation nor a figurine: the junk OCR made of a figurine ("tLl" in
    "tLlxf6"), normalised as GlyphModel keys it. None for a pawn move, a
    castling, a clean letter or a token with no square."""
    parsed = _parse_raw(raw)
    if parsed.castle:
        return None
    known = _resolve_letters(letters)
    best = None
    for p in parsed.parses:
        if not p.prefix or p.fch is None or p.rch is None or p.dfile is not None \
                or p.drank is not None or p.promo is not None:
            continue
        key = (p.cap is not True, len(p.prefix))
        if best is None or key < best[0]:
            best = (key, p.prefix)
    if best is None:
        return None
    prefix = best[1]
    if prefix in known or prefix in _FILE_LETTERS:
        return None
    return prefix


def _board_key(b: chess.Board):
    return b._transposition_key()


def _adjusted(cands, board, gmap, scorer):
    """Candidate costs updated by the glyph's earlier uses in the same run.

    The same junk stands for the same piece throughout a book, so a glyph
    already read as a knight in this run is more likely a knight again (a
    Dirichlet update of the book prior with the run's own counts). Pawn
    readings are left alone: junk before a pawn move is an accident.
    """
    if not gmap:
        return cands
    out = []
    changed = False
    for m, c, glyph, pc, b2, prs in cands:
        pt = board.piece_type_at(m.from_square) if glyph and glyph in gmap else None
        if pt and pt != PAWN and glyph not in scorer.letters:
            cnt = gmap[glyph]
            n = sum(cnt.values())
            p1 = (cnt.get(pt, 0) + KAPPA_RUN * math.exp(-pc)) / (n + KAPPA_RUN)
            c = c - pc - math.log(p1)
            changed = True
        out.append((m, c, glyph, pc, b2, prs))
    if changed:
        out.sort(key=lambda t: t[1])
    return out


def _with_glyph(gmap, glyph, pt, scorer):
    if not glyph or pt == PAWN or glyph in scorer.letters:
        return gmap
    new = dict(gmap)
    cnt = dict(new.get(glyph, {}))
    cnt[pt] = cnt.get(pt, 0) + 1
    new[glyph] = cnt
    return new


OLD_AGE = 12          # tokens after which a parted hypothesis counts as old
OLD_KEEP = 4          # old hypotheses kept in the beam
RETRY_FACTOR = 4      # beam multiplier for the second search of a run with failures
WILD_MARGIN = 2.5     # a failed-token expansion must come this close to the best reading
WILD_HYPS = 3         # only the best few hypotheses expand a failed token

# A path entry: (token index, kind, move, inserted move, cost, glyph, parse);
# kind is "move", "wild" (a failed token, any move played) or "skip" (no ply).


def _search(board0: chess.Board, mtoks: list, labels: list, scorer: _Scorer,
            beam: int, allow_wild: bool, offset0: int, gmap0=None, old_keep: int = None,
            insert: bool = True, anchored: Optional[list] = None):
    """Beam search over move tokens. Returns (best hypothesis, index where all died).

    insert allows a move missing from the text to be supplied. anchored[k] is
    True when a printed move number stands right before token k: such a token
    is a move of the side its number names, so treating it as junk that takes
    no ply does not shift the numbering of the moves after it."""
    hyps = [_Hyp(0.0, board0.copy(stack=False), None, offset0, 0, gmap0 or {})]
    died_at = None
    for k, tok in enumerate(mtoks):
        parsed = _parse_raw(tok.raw)
        children: dict = {}
        failing = []
        best_total = math.inf

        def expand(h, b, off, extra, ins):
            nonlocal best_total
            best_local = math.inf
            for m, c, glyph, pc, b2, prs in _token_candidates(scorer, b, tok, parsed, h.gmap):
                total = h.cost + extra + c
                best_local = min(best_local, extra + c)
                best_total = min(best_total, total)
                key = (_board_key(b2), off)
                old = children.get(key)
                if old is None or total < old.cost:
                    gm = _with_glyph(h.gmap, glyph, b.piece_type_at(m.from_square), scorer)
                    children[key] = _Hyp(total, b2, (h.node, (k, "move", m, ins, c, glyph, prs)),
                                         off, 0, gm)
            return best_local

        for rank, h in enumerate(hyps):
            want = chess.BLACK if labels[k] ^ bool(h.offset) else chess.WHITE
            if h.board.turn == want:
                best_local = expand(h, h.board, h.offset, 0.0, None)
            else:
                best_local = expand(h, h.board, h.offset ^ 1, C_PARITY, None)
                if (insert and allow_wild and h.fails == 0 and rank < WILD_HYPS
                        and best_local > 1.0 + C_PARITY):
                    for w in h.board.legal_moves:        # a move missing from the text
                        b2 = h.board.copy(stack=False)
                        b2.push(w)
                        best_local = min(best_local, expand(h, b2, h.offset, C_INSERT, w))
            if best_local > FAIL_TRIGGER:
                failing.append(h)
        protected = []
        skip_flip = 0 if (anchored and anchored[k]) else 1
        for rank, h in enumerate(failing):
            if not allow_wild:
                protected.append(_Hyp(h.cost + C_FAIL, h.board,
                                      (h.node, (k, "skip", None, None, C_FAIL, None, None)),
                                      h.offset ^ skip_flip, h.fails + 1, h.gmap))
                continue
            if rank >= WILD_HYPS or h.fails >= MAX_FAILS or h.cost + C_FAIL > best_total + WILD_MARGIN:
                continue
            # the token is junk (no ply) or a move that no reading explains (any
            # move, the more alike the text the better)
            protected.append(_Hyp(h.cost + C_SKIP, h.board,
                                  (h.node, (k, "skip", None, None, C_SKIP, None, None)),
                                  h.offset ^ skip_flip, h.fails + 1, h.gmap))
            for w, rc, prs in scorer.relaxed(h.board, parsed):
                b2 = h.board.copy(stack=False)
                b2.push(w)
                c = C_FAIL + WILD_WEIGHT * rc
                protected.append(_Hyp(h.cost + c, b2, (h.node, (k, "wild", w, None, c, None, prs)),
                                      h.offset, h.fails + 1, h.gmap))
        kids = _prune(sorted(children.values(), key=lambda h: h.cost), beam,
                      OLD_KEEP if old_keep is None else old_keep)
        if protected:
            # Failed-token hypotheses are kept unpruned until the next token
            # tells them apart.
            protected.sort(key=lambda h: h.cost)
            seen = {(_board_key(h.board), h.offset) for h in kids}
            extra = []
            for h in protected:
                key = (_board_key(h.board), h.offset)
                if key not in seen:
                    seen.add(key)
                    extra.append(h)
                    if len(extra) >= MAX_WILD:
                        break
            kids = kids + extra
        if not kids:
            died_at = k
            break
        hyps = kids
    best = min(hyps, key=lambda h: h.cost)
    return best, died_at


def _prune(kids: list, beam: int, old_keep: int) -> list:
    """Keep the best `beam` hypotheses, but few that parted from the best one long ago.

    Two readings that never conflict (a pawn on h4 or on b4) would otherwise
    hold beam slots for the rest of the run, crowding out a recent and dearer
    alternative (a knight whose glyph was lost) before the moves that decide
    it are reached.
    """
    if len(kids) <= beam or old_keep >= beam:
        return kids[:beam]
    anc = set()
    node = kids[0].node
    for _ in range(OLD_AGE + 1):
        if node is None:
            break
        anc.add(id(node))
        node = node[0]
    out, old = [kids[0]], 0
    for h in kids[1:]:
        node, d = h.node, 0
        while node is not None and id(node) not in anc and d <= OLD_AGE:
            node = node[0]
            d += 1
        if d > OLD_AGE or (node is None and anc):
            if old >= old_keep:
                continue
            old += 1
        out.append(h)
        if len(out) >= beam:
            break
    return out


def _has_failure(node) -> bool:
    while node is not None:
        node, entry = node
        if entry[1] != "move":
            return True
    return False


def _better(a, a_died, b, b_died) -> bool:
    """True when search result a explains more tokens, or as many more cheaply."""
    na = _path_len(a.node) if a_died is not None else math.inf
    nb = _path_len(b.node) if b_died is not None else math.inf
    if na != nb:
        return na > nb
    return a.cost < b.cost - 1e-9


def _path_len(node) -> int:
    n = 0
    while node is not None:
        node = node[0]
        n += 1
    return n


def _path(node) -> list:
    out = []
    while node is not None:
        node, entry = node
        out.append(entry)
    out.reverse()
    return out


def _future_cost(board, mtoks, labels, scorer, offset, gmap, beam=4) -> float:
    if not mtoks:
        return 0.0
    best, died = _search(board, mtoks, labels, scorer, beam, False, offset, gmap)
    return best.cost + (C_FAIL * (len(mtoks) - died) if died is not None else 0.0)


def decode(board: chess.Board, tokens: list, lookahead: int = 3, letters=None,
           glyphs: Optional[GlyphModel] = None, beam: int = BEAM,
           insert: bool = True) -> list[Decoded]:
    """Decode the move tokens of one run, starting from a copy of board.

    tokens may hold number and result tokens too; only move tokens are decoded,
    and one Decoded comes back per move token, in order. The side to move is
    taken from board; the run's numbering then shows where a move is missing
    or extra. letters picks a LETTER_SETS entry (or a dict letter -> K Q R B N);
    glyphs is a GlyphModel holding the book's learnt glyph junk. lookahead is
    the number of following moves used to choose between readings that fit a
    token equally well. With insert=False the search never supplies a move
    that the numbering shows to be missing from the text; such a run then
    reads with the numbering one ply out, or fails.
    """
    return _decode(board, tokens, _Scorer(letters, glyphs), lookahead, beam, insert)


def decode_sequence(board: chess.Board, seq: Sequence, **kw) -> list[Decoded]:
    """decode() for the tokens of a Sequence."""
    return decode(board, seq.tokens, **kw)


def _anchors(tokens: list) -> list:
    """For each move token: True when a move number is printed right before it."""
    out, prev = [], None
    for t in tokens:
        if t.kind == "move":
            out.append(prev == "number")
        if t.kind in ("move", "number"):
            prev = t.kind
    return out


def _decode(board: chess.Board, tokens: list, scorer: _Scorer, lookahead: int, beam: int,
            insert: bool = True):
    mtoks = [t for t in tokens if t.kind == "move"]
    if not mtoks:
        return []
    labels = [bool(t.black) for t in mtoks]
    anchored = _anchors(tokens)
    offset0 = int((board.turn == chess.BLACK) != labels[0])
    best, died_at = _search(board, mtoks, labels, scorer, beam, True, offset0, insert=insert,
                            anchored=anchored)
    if died_at is not None or _has_failure(best.node):
        # A reading that only later moves confirm may have been pruned: try
        # again with a much wider beam that keeps every surviving alternative.
        wide, wide_died = _search(board, mtoks, labels, scorer, beam * RETRY_FACTOR, True, offset0,
                                  old_keep=beam * RETRY_FACTOR, insert=insert, anchored=anchored)
        if _better(wide, wide_died, best, died_at):
            best, died_at = wide, wide_died
    entries = _path(best.node)
    out: list[Decoded] = []
    b = board.copy(stack=False)
    offset, gmap = offset0, {}

    def failed(tok, parsed, alts=(), cost=C_FAIL, prs=None):
        sq = (prs.fch, prs.rch) if prs is not None else (None, None)
        return Decoded(tok.raw, tok.start, tok.end, tok.number, tok.black, None, None, None,
                       "failed", list(alts), round(cost, 3), None, parsed.annotation, sq)

    for idx, tok in enumerate(mtoks):
        parsed = _parse_raw(tok.raw)
        if idx >= len(entries):
            out.append(failed(tok, parsed))
            continue
        _, kind, m, ins, c, glyph, prs = entries[idx]
        missing = None
        if ins is not None:
            missing = b.san(ins)
            b.push(ins)
        elif kind == "move" and (labels[idx] ^ bool(offset)) != (b.turn == chess.BLACK):
            offset ^= 1
        if kind == "skip":
            if not anchored[idx]:
                offset ^= 1
            out.append(failed(tok, parsed, (), c))
            continue
        if kind == "wild":
            alt = b.san(m)
            b.push(m)
            out.append(failed(tok, parsed, [alt], c, prs))
            continue
        if getattr(tok, "forced", None):
            san = b.san(m)
            b.push(m)
            out.append(Decoded(tok.raw, tok.start, tok.end, tok.number, tok.black, san, m.uci(),
                               b.fen(), "ok", [], 0.0, None, parsed.annotation, (None, None),
                               missing, None, False))
            continue
        cands = _adjusted(scorer.candidates(b, parsed), b, gmap, scorer)
        mine_c = next((cc for mm, cc, *_ in cands if mm == m), c)
        lo = min([cc for _, cc, *_ in cands] + [mine_c])
        others = [(mm, cc, gg) for mm, cc, gg, *_ in cands
                  if mm != m and cc <= max(lo, mine_c) + FIT_MARGIN]
        score_c = mine_c
        if not others and mine_c <= lo + FIT_MARGIN and scorer.weak_glyph(glyph):
            # The learnt glyph alone set this reading apart. Unless the text
            # does so as well, the move is not read with certainty: compare
            # the readings that fit equally under no glyph knowledge.
            plain = scorer.plain().candidates(b, parsed)
            p_mine = next((cc for mm, cc, *_ in plain if mm == m), None)
            if p_mine is not None:
                p_lo = min(cc for _, cc, *_ in plain)
                others = [(mm, cc, gg) for mm, cc, gg, *_ in plain
                          if mm != m and cc <= max(p_lo, p_mine) + FIT_MARGIN]
                if others:
                    score_c = p_mine
        status, alts = "ok", []
        if others or mine_c > lo + FIT_MARGIN:
            def score(mv, cc, gg, n_ahead):
                toks_ = mtoks[idx + 1: idx + 1 + n_ahead]
                b2 = b.copy(stack=False)
                b2.push(mv)
                gm = _with_glyph(gmap, gg, b.piece_type_at(mv.from_square), scorer)
                return cc + _future_cost(b2, toks_, labels[idx + 1: idx + 1 + n_ahead],
                                         scorer, offset, gm)

            mine = score(m, score_c, glyph, lookahead)
            scored = sorted(((score(mm, cc, gg, lookahead), mm, cc, gg) for mm, cc, gg in others),
                            key=lambda t: t[0])
            status = "guessed"
            ties = [t for t in scored if t[0] <= mine + TIE]
            if ties:
                n_full = lookahead + 12
                if len(mtoks) - idx - 1 > lookahead:
                    mine_f = score(m, score_c, glyph, n_full)
                    ties = [t for t in ties if score(t[1], t[2], t[3], n_full) <= mine_f + TIE]
                if ties:
                    status = "ambiguous"
            alts = [b.san(t[1]) for t in scored]
        pt = b.piece_type_at(m.from_square)
        gmap = _with_glyph(gmap, glyph, pt, scorer)
        is_cap = b.is_capture(m)
        lost = False
        if prs is not None:
            if pt == PAWN:
                lost = bool(prs.prefix) or (not is_cap and prs.cap != "-" and (
                    prs.dfile is not None or prs.drank is not None)
                    and not (prs.dfile is not None and prs.drank is not None))
            elif prs.prefix in scorer.letters:
                lost = scorer.letters[prs.prefix] != pt
        san = b.san(m)
        b.push(m)
        sq = (prs.fch, prs.rch) if prs is not None else (None, None)
        cap_mark = (prs.cap is True) if prs is not None else None
        out.append(Decoded(tok.raw, tok.start, tok.end, tok.number, tok.black, san, m.uci(),
                           b.fen(), status, alts, round(mine_c, 3), glyph, parsed.annotation, sq,
                           missing, cap_mark, lost))
    return out
