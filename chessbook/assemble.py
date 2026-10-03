"""Assemble the games, fragments and variations of a chess book.

build_book(pdf_path) walks the selected pages of a book in reading order,
finds every run of numbered moves, decodes the runs into legal moves and
joins them into lines (games and fragments) with variations and comments.
It writes output/<stem>/book.json and returns the same dict:

    {"title", "pdf", "page_count", "folio_offset", "glyphs",
     "pages": [{"page", "folio", "width", "height", "chapter", "selected",
                "diagrams": [{"id", "rect", "label", "kind", "selected", "fen",
                              "status", "after_node", "lines"}],
                "marks": [{"bbox", "node", "status", "raw", "line", "reason"?}]}],
     "chapters": [{..book_structure chapter.., "index", "file", "counts"}],
     "lines": [{"id", "title", "kind", "chapter", "page", "end_page", "start_fen",
                "root", "status", "diagram", "section", "header", "result",
                "moves", "variations"}],
     "nodes": {id: {"san", "fen", "parent", "children", "number", "black",
                    "page", "bbox", "status", "raw", "comment", "main",
                    "assumed", "uci", "line", "alternatives"?, "reason"?}},
     "unattached": [{"page", "chapter", "text", "reason"}],
     "waiting": [{"page", "chapter", "text", "reason", "line", "diagram"}],
     "stats": {...}}

"folio" is the page number printed in the book (PDF page minus the
"folio_offset" learnt from the running heads; None where the book prints
none); line titles and reasons name printed pages. Diagram ids are those of
selection.py: a picture that holds stacked boards gives one diagram per board
("p79-1a", "p79-1b"). A decoded node's number and side come from the
position it is played in, so the labels always match the board.

How the text is read
--------------------
Main-line moves are set in a move font that pdftext.book_fonts learns from
the book; notes are set in the body font. Every word is classed by the font
of its characters (a book without a distinct move font falls back to the
line roles). Each chapter becomes three aligned text buffers: the original
text, the main-font words only and the note words only, the other words
blanked out. find_sequences runs on the two filtered buffers, so a main line
continues across the notes between its moves, while a note never merges
with the main line. Token offsets are the same in all buffers and map back
to the word boxes on the page. Moves in the move font inside a sentence of
body text ("should White play 1.g6+, ...") count as notes.

How lines are formed
--------------------
A game starts at a game header, or at a main-font run that begins at move 1
with White and reads as play from the initial position: cleanly over two
moves each at least, with no printed piece glyph or capture mark dropped to
make it fit, and with no diagram named ("Diagram 430") or position set up in
its sentence. Following main-font runs that continue its numbering continue
it, across columns, pages and diagrams, until a heading, the next game
header, a solution number, a result or the end of the chapter. Where the
numbering skips moves that the text lacks, the program does not invent them:
the decoded part of the line ends with a "gap" node (status failed, no move,
with a reason) and the rest of the printed score follows unread. A run that
starts later than move 1 without an earlier line to continue starts from the
diagram the sentence names, or else the diagram printed before it; the
diagram's position is read by Stage 3, so until then the line has status
"waiting" and keeps its raw move text. A numbered solution ("5. S. Loyd,
1878: 1.Qa1!!", "20. 2...Rh3+!") is matched to the diagram with the same
number among the exercises before it.

Note runs become variations. A note run whose first move has the number of a
move in the line becomes an alternative to that move; a run that continues a
variation of the same note continues it ("..., followed by 15...Nxb4" can
only continue it); a run inside parentheses branches off the variation that
encloses it. Each placement is decoded from the position it implies and kept
only when the moves read cleanly from there, and no printed capture mark is
read as a quiet move. Runs the text gives as a threat or a plan
("threatening 13.Rh3"), runs whose sentence names another diagram (those
start a line of their own) and runs without a move number that no word such
as "instead" or "better" ties to a move are not placed. Runs that cannot be
placed go to "unattached" with the reason in plain words.

A diagram's "after_node" names the move whose position the text ties to
the diagram: the last main-line move before a diagram printed inside or
right after a decoded line, or the last move of an opening sequence from the
initial position that the text gives just after the diagram ("This position
arises after the opening moves 1.e4 e5 ..."). It is a guess for Stage 3 to
check against its board reading.

Decoding uses movetext's glyph learning over the whole book: the book is
assembled once with no glyph knowledge, a GlyphModel learns from the runs
that read cleanly, and the book is assembled again with that model; a third
pass learns the book's square habits (such as "6" printed for f3) from the
second pass, whose runs read cleanly enough to teach them.
"""
from __future__ import annotations

import bisect
import json
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

import chess
import pymupdf

from . import pdftext as pt
from . import selection as sel
from .movetext import GlyphModel, clean_run, decode, find_sequences, numbering_counts
from .movetext import DOTLESS_MIN, DOTLESS_SHARE
from .movetext import LETTER_SETS, FIGURINES, _strip_suffix, _number_values, _relabel, _shape
from .movetext import _ocr_digit_slip

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"
VERSION = 1

STATUSES = ("ok", "guessed", "ambiguous", "failed", "inserted", "waiting")
_LINE_RANK = {"ok": 0, "inserted": 1, "guessed": 1, "ambiguous": 2, "failed": 3}
NOTE_BREAK = "¶"           # stands where main-font words were blanked from the notes
WAIT_REASON = "needs the diagram position (Stage 3)"
COMMENT_MAX = 2000              # characters of note text kept as one comment
GAP_MAX = 8                     # plies a main run may skip and still continue its line

_EXERCISE_RE = re.compile(r"^(\d{1,3}[a-d]?)\.(?= )")
# What may follow a solution number: a move number ("1.Qa1", "2...Rh3+",
# OCR's "IJ" for "1." before a rook), so that "20. 2...Rh3+!" starts
# solution 20 instead of continuing solution 19.
_MOVE_ONE_RE = re.compile(r"^(?:[0-9lI]{1,3} ?[.…•·]|[0-9lI]{1,2}$|[1lI]J[^ ])")
# Words that make the moves after them a threat, a plan or an idea rather
# than moves played or recommended: such runs are not variations.
_THREAT_RE = re.compile(
    r"\b(?:threat\w*|prepar(?:es|ing|ed) to|wants? to|wanting to|plans?|planning|"
    r"intend\w*(?! to (?:play|continue|answer|meet))|resulting from|with the idea|aim\w* (?:at|to))\b", re.I)
# Words that may stand between such a cue and the moves it introduces.
_CONNECT_WORDS = {"and", "then", "followed", "by", "or", "with", "of", "the", "a", "an",
                  "to", "carry", "out", "play", "playing", "double", "move", "moves", "after",
                  "continue", "next", "is", "are", "was", "were", "now", "already",
                  "mate", "check", "mating"}
# Words that tie a run without a move number to the move it replaces.
_ALT_CUE_RE = re.compile(r"\b(?:instead|better|stronger|weaker|preferable|worse|"
                         r"alternatively|or)\b", re.I)
_FOLLOW_RE = re.compile(r"\b(?:followed by|and then|then)\s*$", re.I)
# "Diagram 430", "Position 262", "Diag. 12": the text names a diagram.
_DIAGRAM_REF_RE = re.compile(r"\b(?:[DO][il1]a?gr[ae](?:m|rn|in)s?|Diag\.|Position|Pos\.)\s*"
                             r"([0-9lIOSB]{1,3}[a-d]?)\b")
# Words that introduce a sequence from the initial position.
_OPENING_RE = re.compile(r"\b(?:opening|arises? after|begin\w*|after the moves|"
                         r"the game (?:began|went)|starts? with)\b", re.I)
_NUMBER_HINT_RE = re.compile(r"\d|[lIOoSsB|] ?[.…•·]")
_REF_TAIL_RE = re.compile(r"(?i)\b(?:positions?|diagrams?|diag\.|pos\.|pages?|p\.|no\.|nos\.|"
                          r"exercises?|problems?|games?|and|or|of|in|to|at)$")
_SETUP_RE = re.compile(r"\b(?:White|Black)\s*[:(]", re.I)
# The end of a sentence or clause: a word and a stop, a semicolon, or a stop
# before a capitalised word ("Threatening ...b5. If now 15.b4, then ...").
_SENTENCE_END_RE = re.compile(r"(?:[^\W\d_]{2}[.!?]|;)\s|[.!?]\s+(?=[A-Z][a-z]+ )")
_REAL_WORD_RE = re.compile(r"^[^\W\d_]{2,}")
_BARE_NUMBER_RE = re.compile(r"^[0-9lIO]{1,3}$")
_NUMBER_LINE_RE = re.compile(r"^[0-9lIOS]{1,3}(?: [0-9lIOS])?(?: ?[.…•·]+)*$")
_DOTS_RE = re.compile(r"^[.…•·]+$")
# A move number at the end of a stretch of the notes ("... Perhaps I S ... ").
_NOTE_NUMBER_END_RE = re.compile(r"(?:^|\s)[0-9lIOS]{1,3}(?: [0-9lIOS])?\s*(?:[.…•·]\s*){1,3}$")
_RESULT_NORM = {"1-0": "1-0", "l-0": "1-0", "1:0": "1-0", "1-o": "1-0", "l-o": "1-0",
                "0-1": "0-1", "0-l": "0-1", "0:1": "0-1", "o-1": "0-1", "o-l": "0-1"}


# ---------------------------------------------------------------- helpers

def _ply(tok):
    if tok.number is None:
        return None
    return (tok.number - 1) * 2 + int(bool(tok.black))


def _renumbered(run, ply):
    """The run read with the first move number and side that ply implies, when
    the number as printed can be read that way (OCR's "s" stands for 5 as well
    as 8; a number without dots names no side), else None."""
    first = run.tokens[0]
    if first.kind != "number" or first.number is None or ply is None:
        return None
    n, black = ply // 2 + 1, bool(ply % 2)
    if (n, black) == (first.number, bool(first.black)) or n not in _number_values(first):
        return None
    if first.side_known and bool(first.black) != black:
        return None
    toks = list(run.tokens)
    _relabel(toks, n, black)
    moves = [t for t in toks if t.kind == "move"]
    return _Run(run.kind, toks, moves, run.start, run.end, run.depth, _ply(moves[0]), run.result,
                run.home, run.context)


def _first_moves(tokens, n):
    """The tokens of a run up to its n-th move."""
    out, k = [], 0
    for t in tokens:
        if t.kind == "move":
            if k == n:
                break
            k += 1
        out.append(t)
    return out


def _ply_label(ply):
    if ply is None:
        return "?"
    n, black = ply // 2 + 1, ply % 2
    return f"{n}..." if black else f"{n}."


def _folio(page, offset):
    """The printed page number of a PDF page, or None where the book prints none."""
    if offset is None or page is None or page - offset < 1:
        return None
    return page - offset


def _ply_words(ply):
    """'White's move 17' or 'Black's move 16' for a ply index."""
    if ply is None:
        return "a move with no number"
    return f"{'Black' if ply % 2 else 'White'}'s move {ply // 2 + 1}"


def _board_ply(fen):
    """The ply index of the move about to be played in a position."""
    b = chess.Board(fen)
    return (b.fullmove_number - 1) * 2 + int(b.turn == chess.BLACK)


_DRAW_RE = re.compile(r"^(?:[1l]/2|½|Y2)-(?:[1l]/2|½|Y2)$")


def _norm_result(raw):
    r = raw.replace(" ", "")
    if r in _RESULT_NORM:
        return _RESULT_NORM[r]
    if _DRAW_RE.match(r):
        return "1/2-1/2"
    return None


def _norm_raw(raw):
    """Raw move text without annotation and check signs, for comparing waiting moves."""
    return re.sub(r"[!?+#t†‡.,;:)\s]+$", "", raw.replace(" ", ""))


_PLAIN_MOVE_RE = re.compile(r"^(?:[KQRBN]?[a-h]?[1-8]?[x:]?[a-h][1-8](?:=?[QRBN])?|O-O(?:-O)?|"
                            r"0-0(?:-0)?)[+#!?t]*$")


def _plain_move(raw):
    """True for a move printed in plain letters that any reader can parse."""
    return bool(_PLAIN_MOVE_RE.match(_norm_raw(raw) or ""))


def _shown(raw):
    """Raw OCR text with control characters made visible."""
    return "".join(ch if ch >= " " else "▫" for ch in (raw or "")).strip()


_SQUARE_RE = re.compile(r"[a-h£][1-8lIBS](?!.*[a-h£][1-8lIBS])")


def _same_printed_move(a, b):
    """Two printed forms of one move, OCR junk aside: the same destination
    square, and both pawn moves or both piece moves."""
    if _norm_raw(a) == _norm_raw(b):
        return True
    ca, cb = _norm_raw(a), _norm_raw(b)
    sa, sb = _SQUARE_RE.search(ca), _SQUARE_RE.search(cb)
    if not sa or not sb:
        return False
    norm = str.maketrans({"£": "f", "l": "1", "I": "1", "B": "8", "S": "5"})
    if sa.group(0).translate(norm) != sb.group(0).translate(norm):
        return False
    # a pawn move prints nothing before its square, or the file it captures from
    pa = re.fullmatch(r"(?:([a-h£])[x:×]?)?", ca[:sa.start()])
    pb = re.fullmatch(r"(?:([a-h£])[x:×]?)?", cb[:sb.start()])
    if (pa is None) != (pb is None):
        return False
    return pa is None or not (pa.group(1) and pb.group(1)) or pa.group(1) == pb.group(1)


_READ_SQUARE_RE = re.compile(r"([a-h£])['`]?([1-8lIBS])$")


def readable_move(raw, glyphs=None, letters=None):
    """A printed move with its OCR junk replaced where the reading is sure:
    the piece glyph when the book's glyph model knows it well (or it is a
    letter of the notation), the square, the capture mark, the check sign and
    the annotation. Returns None when the junk cannot be read with
    certainty; the raw text then stays as printed."""
    text = "".join((raw or "").split(" "))
    core, check, ann = _strip_suffix(text)
    if re.fullmatch(r"[0Oo](?:-[0Oo]){1,2}", core):
        san = "O-O-O" if core.count("-") == 2 else "O-O"
    else:
        m = _READ_SQUARE_RE.search(core)
        if not m:
            return None
        fix = str.maketrans({"£": "f", "l": "1", "I": "1", "B": "8", "S": "8"})
        square = (m.group(1) + m.group(2)).translate(fix)
        head = core[:m.start()]
        cap = ""
        if head[-1:] in ("x", ":", "×"):
            cap, head = "x", head[:-1].rstrip("x:×")
        table = dict(LETTER_SETS.get(letters or "English", LETTER_SETS["English"]))
        table.update(FIGURINES)
        if head == "":
            piece = ""
        elif re.fullmatch(r"[a-h]", head) and cap:
            piece = head                         # a pawn capture: "cxd4"
        elif head in table:
            piece = table[head] if table[head] != "P" else ""
        elif glyphs is not None and len(glyphs) and glyphs.strong(head):
            pri = glyphs.prior(head)
            piece = max(pri, key=pri.get)
            if piece == "P":
                return None
            if not cap and glyphs.implies_capture(head):
                cap = "x"
        else:
            return None
        san = piece + cap + square
    return san + {0: "", 1: "+", 2: "++", 3: "#"}[check] + ann


_SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the",
                "to", "with", "from", "into"}


def display_title(text):
    """'SOLUTIONS TO FUN EXERCISES' -> 'Solutions to Fun Exercises'. Text that is
    not all capitals is kept as printed."""
    t = re.sub(r"\s+", " ", text or "").strip()
    letters = [c for c in t if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) < 0.8 * len(letters):
        return t
    words = t.lower().split(" ")
    out = []
    for i, w in enumerate(words):
        if i and w in _SMALL_WORDS and not re.fullmatch(r"[\d.()]+|.*[:.]", words[i - 1]):
            out.append(w)
        else:
            out.append(re.sub(r"[^\W\d_]", lambda m: m.group(0).upper(), w, count=1))
    return " ".join(out)


def parse_game_header(text):
    """{"white", "black", "event", "site", "year", "text"} from a game header line,
    or None when the line does not read as one."""
    text = pt.join_year(text.strip())
    m = pt.GAME_HEADER_RE.match(text)
    if not m:
        return None
    white = re.sub(r"\s+", " ", m.group("white")).strip()
    black = re.sub(r"\s+", " ", m.group("black")).strip()
    event = (m.group("event") or "").strip(" ,;")
    if event.count("(") > event.count(")"):
        event += ")"                    # the pattern took the closing bracket as the end
    year = m.group("year")
    site = re.sub(r"\([^)]*\)", "", event)
    site = re.sub(r"\b(?:1[5-9]|20)\d\d\b", "", site).strip(" ,;.")
    ev = event + (" " + year if year and year not in event else "")
    return {"white": white, "black": black, "event": ev.strip(), "site": site,
            "year": year, "text": text.strip()}


def load_stage1(pdf_path, output_dir=None, page_count=None):
    """Stage 1's diagrams.json for the book. When output_dir lacks it, the
    project's own Stage 1 results for the same book are copied, or Stage 1 is
    run (it writes into ./output/<stem>/stage1 of its working directory)."""
    import shutil
    import tempfile
    pdf_path = Path(pdf_path).resolve()
    out = Path(output_dir or OUTPUT_DIR)
    dest = out / pdf_path.stem / "stage1"
    path = dest / "diagrams.json"
    if not path.exists():
        shared = OUTPUT_DIR / pdf_path.stem / "stage1"
        same = False
        if shared.resolve() != dest.resolve() and (shared / "diagrams.json").exists():
            try:
                pages = json.loads((shared / "pages.json").read_text(encoding="utf-8"))
                same = page_count is None or len(pages) == page_count
            except (OSError, ValueError):
                same = False
        if same:
            src = shared
        else:
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))
            import stage1_inspect
            src = Path(tempfile.mkdtemp(prefix="stage1_"))
            stage1_inspect.analyse(pdf_path, src)
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("diagrams.json", "numbers.json", "pages.json"):
            if (src / name).exists() and (src / name).resolve() != (dest / name).resolve():
                shutil.copyfile(src / name, dest / name)
    return json.loads(path.read_text(encoding="utf-8"))


def book_chapters(structure, page_count):
    """The chapters of book_structure with a front-matter entry first (index 0),
    so that chapter k of the book has index k and file chKK."""
    chapters = [dict(c) for c in structure.get("chapters") or []]
    if not chapters:
        chapters = [{"title": "Whole book", "label": "Whole book", "kind": "chapter",
                     "number": None, "subtitle": "", "start": 1, "end": page_count,
                     "confirmed": False, "sections": []}]
    first = chapters[0]["start"]
    front = {"title": "Front matter", "label": "Front matter", "kind": "front",
             "number": None, "subtitle": "", "start": 1, "end": first - 1,
             "confirmed": True, "sections": list(structure.get("front_matter") or [])}
    out = [front] + chapters
    for i, c in enumerate(out):
        c["index"] = i
        c["file"] = f"ch{i:02d}.html"
        c["pgn"] = f"ch{i:02d}.pgn"
    return out


def _split_at_diagrams(toks, diagrams):
    """Split a run of tokens where a diagram stands between two of its moves
    and the move number after the diagram does not continue the numbering
    ("1.Kf7 [Diagram 80] 2.Kg6!": Black's reply is printed in the picture).
    A run whose numbering goes on across the diagram stays whole, so that
    the moves after the diagram still help to read the moves before it."""
    out, cur, last = [], [], None
    for t in toks:
        if (cur and t.kind == "number" and t.number is not None and last is not None
                and any(cur[-1].end <= d <= t.start for d in diagrams[
                    bisect.bisect_left(diagrams, cur[-1].end):
                    bisect.bisect_right(diagrams, t.start)])):
            n, b = last
            want = (n + 1, False) if b else (n, True)
            if (t.number, bool(t.black)) != want:
                out.append(cur)
                cur = []
        cur.append(t)
        if t.kind == "move" and t.number is not None:
            last = (t.number, bool(t.black))
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- the text stream

@dataclass
class _TextLine:
    start: int                  # offset of the line's text in the buffers
    page: int
    line: dict
    word_starts: list
    para: bool                  # a paragraph starts with this line


@dataclass
class _Run:
    kind: str                   # "main" or "note"
    tokens: list                # number, move and result tokens (absolute offsets)
    moves: list
    start: int
    end: int
    depth: int
    ply: Optional[int]
    result: Optional[str]
    home: Optional[str] = None  # the diagram a held note would start from
    context: Optional[tuple] = None  # the solution context it was held in


class _Stream:
    """The text of one chapter in reading order, as three aligned buffers."""

    def __init__(self):
        self.orig, self.main, self.note = [], [], []
        self.pos = 0
        self.lines: list[_TextLine] = []
        self.starts: list[int] = []
        self.events = []        # (offset, order, kind, payload)

    def event(self, kind, payload=None, at=None):
        self.events.append((self.pos if at is None else at, len(self.events), kind, payload))

    def add(self, page, ln, classes, mask_upto, para):
        if para and self.pos:
            for b in (self.orig, self.main, self.note):
                b.append("\n")
            self.pos += 1
        text = ln["text"]
        words = text.split(" ")
        word_starts, o, k = [], [], 0
        main_parts, note_parts, orig_parts = [], [], []
        prev_main = None
        for w, c in zip(words, classes):
            word_starts.append(k)
            masked = k < mask_upto
            ow = " " * len(w) if masked else w
            orig_parts.append(ow)
            main_parts.append(ow if c == "m" else " " * len(w))
            if c == "m" or masked:
                # a main-font word breaks any note run that would span it
                note_parts.append((NOTE_BREAK + " " * (len(w) - 1)) if (c == "m" and prev_main is not True)
                                  else " " * len(w))
            else:
                note_parts.append(w)
            prev_main = c == "m"
            k += len(w) + 1
        tl = _TextLine(self.pos, page, ln, word_starts, para)
        self.lines.append(tl)
        self.starts.append(self.pos)
        self.orig.append(" ".join(orig_parts) + "\n")
        self.main.append(" ".join(main_parts) + "\n")
        self.note.append(" ".join(note_parts) + "\n")
        self.pos += len(text) + 1

    def finish(self):
        self.orig_text = "".join(self.orig)
        self.main_text = "".join(self.main)
        self.note_text = "".join(self.note)
        assert len(self.orig_text) == len(self.main_text) == len(self.note_text) == self.pos

    def locate(self, s, e):
        """(page, bbox) of the words holding characters s..e (union of word boxes,
        cut in proportion where a token covers only part of a word)."""
        i = bisect.bisect_right(self.starts, s) - 1
        page, box = None, None
        while 0 <= i < len(self.lines) and self.lines[i].start < e:
            tl = self.lines[i]
            words = tl.line["words"]
            for w, ws in zip(words, tl.word_starts):
                a, b = tl.start + ws, tl.start + ws + len(w["text"])
                lo, hi = max(a, s), min(b, e)
                if lo >= hi:
                    continue
                x0, y0, x1, y1 = w["bbox"]
                n = max(len(w["text"]), 1)
                xs = w.get("xs")
                if xs and len(xs) == n + 1:
                    # the edges of the characters themselves
                    bx = [xs[lo - a], y0, xs[hi - a] if hi - a < n else x1, y1]
                else:
                    bx = [x0 + (x1 - x0) * (lo - a) / n, y0, x0 + (x1 - x0) * (hi - a) / n, y1]
                if page is None:
                    page, box = tl.page, bx
                elif tl.page == page:
                    box = [min(box[0], bx[0]), min(box[1], bx[1]),
                           max(box[2], bx[2]), max(box[3], bx[3])]
            i += 1
        if box is not None:
            box = [round(v, 1) for v in box]
        return page, box

    def page_at(self, off):
        i = max(bisect.bisect_right(self.starts, off) - 1, 0)
        return self.lines[i].page if self.lines else None


# ---------------------------------------------------------------- the builder

@dataclass
class _Line:
    id: str
    kind: str
    title: str
    chapter: int
    page: int
    root: str
    start_fen: Optional[str]
    waiting: bool
    diagram: Optional[str]
    section: str
    header: Optional[dict]
    start_offset: int
    next_ply: int
    last_fen: Optional[str]
    born: str                   # "main", "note" or "header"
    main_tok: list = field(default_factory=list)       # [(start, end, node id)]
    main_nodes: list = field(default_factory=list)
    ply_node: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)          # deferred runs [(run, as_main)]
    replace: list = field(default_factory=list)        # (start, end, text) for comments
    consumed: list = field(default_factory=list)       # (start, end) of the line's own tokens
    end_offset: Optional[int] = None
    result: Optional[str] = None
    first_offset: int = 0
    variations: int = 0
    last_token_end: int = 0
    busy_until: int = 0         # end of the line's last main run
    close_at: Optional[int] = None
    broken: bool = False        # a gap in the text ended the decoded part of the line


class _Decoder:
    """decode() with the book's glyph model, letter set and a memo."""

    def __init__(self, glyphs, letters):
        self.glyphs = glyphs
        self.letters = letters
        self.memo = {}
        self.accepted = []
        self.calls = 0
        self.seconds = 0.0

    def run(self, fen, tokens):
        key = (fen, tuple((t.kind, t.raw, t.number, t.black) for t in tokens))
        hit = self.memo.get(key)
        if hit is None:
            t0 = time.perf_counter()
            # Never supply a move the text lacks: a gap in the numbering is
            # shown as a gap (see _Builder.gap), not filled with a guess.
            hit = decode(chess.Board(fen), tokens, glyphs=self.glyphs, letters=self.letters,
                         insert=False)
            self.seconds += time.perf_counter() - t0
            self.calls += 1
            self.memo[key] = hit
        return hit


def _fit(decs):
    """(rank, failed, mean cost): rank 0 = reads cleanly, 1 = reads with a few
    failures, 2 = does not read from this position."""
    if not decs:
        return (2, 0, 0.0)
    failed = sum(d.status == "failed" for d in decs)
    ok = [d.cost for d in decs if d.status != "failed"]
    mean = sum(ok) / len(ok) if ok else 9.0
    if failed == 0 and mean <= 1.5:
        return (0, failed, mean)
    if clean_run(decs, max_failed=0.25, max_mean_cost=2.0):
        return (1, failed, mean)
    return (2, failed, mean)


class _Builder:
    def __init__(self, doc, fonts, chapters, diagrams, selection, decoder, diagram_fens=None,
                 dotless=False):
        self.doc, self.fonts, self.chapters = doc, fonts, chapters
        self.dotless = dotless          # the book prints move numbers without a dot
        self.diagrams = diagrams
        self.selection = selection
        self.dec = decoder
        self.diagram_fens = diagram_fens or {}
        self.ids = sel.diagram_ids(diagrams)
        self.kinds = sel.picture_kinds(diagrams, chapters[1]["start"] if len(chapters) > 1 else 1)
        self.diag_info = {}
        self.page_ids = defaultdict(list)
        for did, d in zip(self.ids, diagrams):
            self.diag_info[did] = d
            self.page_ids[d["page"]].append(did)
        self.nodes = {}
        self.lines = []
        self.marks = defaultdict(list)
        self.unattached = []
        self.waiting = []
        self.after_node = {}
        self.moves_font = bool(fonts.get("moves"))
        self.bs = (fonts.get("body") or {}).get("size") or 10.0
        self.folio_offset = (fonts.get("layout") or {}).get("folio_offset")

    def page_label(self, page):
        """The page number printed in the book (the PDF page when unknown)."""
        if page is None:
            return None
        return _folio(page, self.folio_offset) or page

    # -------------------------------------------------------- nodes and marks
    def new_node(self, line, **kw):
        nid = f"n{len(self.nodes) + 1}"
        node = {"san": None, "fen": None, "parent": None, "children": [], "number": None,
                "black": None, "page": None, "bbox": None, "status": "ok", "raw": "",
                "comment": "", "main": False, "assumed": None, "uci": None, "line": line.id}
        node.update(kw)
        self.nodes[nid] = node
        if node["parent"] is not None:
            self.nodes[node["parent"]]["children"].append(nid)
        return nid

    def mark(self, stream, tok, node, status, line_id=None, reason=None):
        page, box = stream.locate(tok.start, tok.end)
        if page is None:
            return None, None
        m = {"bbox": box, "node": node, "status": status, "raw": tok.raw, "line": line_id,
             "_o": tok.start}
        if reason:
            m["reason"] = reason
        self.marks[page].append(m)
        return page, box

    # -------------------------------------------------------- stream building
    def word_classes(self, ln):
        words = ln["text"].split(" ")
        if not self.moves_font:
            c = "m" if ln["role"] == "moves" else "n"
            return [c] * len(words)
        roles = []
        for s in ln["spans"]:
            r = "m" if s["role"] == "moves" else "n" if s["role"] == "text" else None
            roles.extend(r for ch in s["text"] if ch not in pt._SPACE_SET)
        if len(roles) != sum(len(w) for w in words):
            c = "m" if ln["role"] == "moves" else "n"
            return [c] * len(words)
        total = Counter(r for r in roles if r)
        line_c = "m" if total["m"] > total["n"] else "n"
        out, k = [], 0
        for w in words:
            cnt = Counter(r for r in roles[k:k + len(w)] if r)
            k += len(w)
            if cnt["m"] > cnt["n"]:
                out.append("m")
            elif cnt["n"] > cnt["m"]:
                out.append("n")
            else:
                out.append(None)
        # A word in neither font (dots set in a symbol font: "1 • • • Re6+!")
        # goes with the word before it, or else the word after it; a plain word
        # of prose in a third font (OCR fonts set body text in many) is a note.
        for i, c in enumerate(out):
            if c is None and len(words[i]) >= 2 and words[i].isalpha() and not _shape(words[i]):
                out[i] = "n"
        for i, c in enumerate(out):
            if c is None:
                before = next((out[j] for j in range(i - 1, -1, -1) if out[j]), None)
                after = next((out[j] for j in range(i + 1, len(out)) if out[j]), None)
                out[i] = before or after or line_c
        # OCR sets a stretch of a line of moves in the body font now and then
        # ("6 tiJgf3 .i.e7 7 o-o o-o"): moves and numbers between main-font
        # words on both sides belong to the main line
        i = 0
        while i < len(out):
            if out[i] != "n" or i == 0 or out[i - 1] != "m":
                i += 1
                continue
            j = i
            while j < len(out) and out[j] == "n":
                j += 1
            if j < len(out) and all(_shape(w) or _BARE_NUMBER_RE.match(w) or _DOTS_RE.match(w)
                                    for w in words[i:j]) \
                    and all(any(ch.isalnum() for ch in w) for w in (words[i - 1], words[j])):
                out[i:j] = ["m"] * (j - i)
            i = j
        return out

    def column_edges(self, page, col):
        lay = self.fonts.get("layout") or {}
        cols = (lay.get("columns") or {}).get("odd" if page % 2 else "even") or []
        if col in (1, 2) and len(cols) == 2:
            return cols[col - 1]
        if cols:
            return [min(c[0] for c in cols), max(c[1] for c in cols)]
        return None

    def diagram_positions(self, page, lines):
        """Index of the line before which each diagram on the page stands."""
        pos = {}
        for k, ln in enumerate(lines):
            d = ln.get("diagram")
            if d and d not in pos and d in self.diag_info:
                pos[d] = k
        for did in self.page_ids.get(page, []):
            if did in pos:
                continue
            r = self.diag_info[did]["rect"]
            cx = (r[0] + r[2]) / 2
            gut = ((self.fonts.get("layout") or {}).get("gutter") or {}).get(
                "odd" if page % 2 else "even")
            best = len(lines)
            for k, ln in enumerate(lines):
                if ln["role"] == "head":
                    continue
                b = ln["bbox"]
                same = (gut is None or ln["col"] == 0
                        or (ln["col"] == 1) == (cx < gut))
                if same and b[1] >= r[1] - 2:
                    best = k
                    break
            pos[did] = best
        return pos

    def build_stream(self, ch):
        st = _Stream()
        excluded_run = False
        list_next = None        # the next item number of a numbered list in the prose
        for p in range(ch["start"], ch["end"] + 1):
            if not self.selection.page_selected(p):
                if not excluded_run:
                    st.event("break", {"page": p, "reason": "excluded page"})
                excluded_run = True
                continue
            excluded_run = False
            lines = pt.page_lines(self.doc, p - 1, self.fonts)
            dpos = self.diagram_positions(p, lines)
            by_line = defaultdict(list)
            for did, k in dpos.items():
                # a margin icon or a drawing that the selection leaves out is no
                # position for a line to start from
                if self.not_a_board(did):
                    continue
                by_line[k].append(did)
            st.event("page", p)
            prev = prev_classes = None
            for k, ln in enumerate(lines):
                for did in sorted(by_line.get(k, []), key=sel.id_key):
                    st.event("diagram", did)
                role = ln["role"]
                if role == "label" and self.move_number_label(lines, k):
                    role = "text"
                if (role == "game_header" and prev is not None and prev["role"] == "text"
                        and ln["text"].rstrip().endswith(".")
                        and not self.para_start(p, ln, prev)
                        and not re.search(r"[.!?:;)\]]\s*$", prev["text"])):
                    # a sentence that names a game runs on to this line ("... in
                    # L.Gomez" / "Cabrero-R.Sheldon, World Junior Championships, 1998.")
                    role = "text"
                if role in ("head", "coord", "blank", "label"):
                    continue
                if role in ("heading", "game_header", "caption"):
                    st.event(role, ln)
                    prev = None
                    if role != "caption":
                        list_next = None
                    continue
                classes = self.word_classes(ln)
                if prev is not None and prev_classes:
                    self.number_line_move(prev, prev_classes, ln, classes)
                para = self.para_start(p, ln, prev)
                if (not self.moves_font and not para and prev is not None
                        and prev["role"] == "text" and all(c == "m" for c in classes)
                        and not re.search(r"[.!?:;)\]]\s*$", prev["text"])
                        and any(w.isalpha() and w.islower() and not _shape(w)
                                for w in ln["text"].split(" "))):
                    # a sentence of the notes that runs on to a line of moves
                    # ("... Black's pieces are also well placed after 22.Ne2" /
                    # "Qe5 23.f4 Qf6 or 23...Qc5.")
                    classes = ["n"] * len(classes)
                prev_classes = classes
                text = ln["text"]
                mask = 0
                if para:
                    st.event("para")
                m = _EXERCISE_RE.match(text + (" " if re.fullmatch(r"\d{1,3}[a-d]?\.", text) else ""))
                # "... as in Position" / "73. Therefore ...": a number that a
                # sentence runs on to, not a solution number
                if m and prev is not None and _REF_TAIL_RE.search(prev["text"]):
                    m = None
                if m:
                    rest = text[m.end() + 1:]
                    nxt = rest.split(" ")[0]
                    worded = ((pt.token_kind(nxt) == "word" and _REAL_WORD_RE.match(nxt))
                              or re.match(r"^[A-Z\]\[|]\.$", nxt))
                    if worded and not para and prev is not None \
                            and not re.search(r"[.!?:;)]$", prev["text"]):
                        worded = False       # a sentence that runs on over a line break
                    if worded and (
                            (m.group(1) == "1" and prev is not None
                             and prev["text"].rstrip().endswith(":"))
                            or (list_next is not None and m.group(1) == str(list_next))):
                        # a numbered list in the prose ("Black gains in two ways:"
                        # / "1. Black may play ...g6" / "2. ..."), not solutions
                        list_next = int(m.group(1)) + 1
                        worded = False
                        m = None
                if m:
                    if not rest.strip() or _MOVE_ONE_RE.match(rest) or worded:
                        mask = m.end()
                        st.event("exercise", m.group(1))
                if _BARE_NUMBER_RE.match(text) and self.centred(p, ln):
                    st.event("number", int(text.translate(pt.DIGIT_FIX).replace("O", "0")))
                st.add(p, ln, classes, mask, para)
                base = st.starts[-1]
                k = 0
                for w, c in zip(text.split(" "), classes):
                    if c == "m" and _norm_result(w.strip(".,;")):
                        st.event("result", (_norm_result(w.strip(".,;")), len(w)), at=base + k)
                    k += len(w) + 1
                prev = ln
            for did in sorted(by_line.get(len(lines), []), key=sel.id_key):
                st.event("diagram", did)
        st.finish()
        return st

    def not_a_board(self, did):
        """True for a picture the selection leaves out that is no board at all:
        a margin icon, a drawing, or a strip far wider than high (a shaded box
        behind a question, a rule)."""
        if self.selection.diagram_selected(did):
            return False
        kind = self.kinds.get(did)
        if kind in ("icon", "illustration"):
            return True
        r = self.diag_info[did]["rect"]
        w, h = r[2] - r[0], r[3] - r[1]
        return kind == "partial" and (w > 2.5 * h or h > 2.5 * w)

    def move_number_label(self, lines, k):
        """True when a number taken for a diagram's label is a move number set
        in the move font on a line of its own, with the move on the next line
        ("16" / "tLlb2!!" beside a board)."""
        ln = lines[k]
        if not self.moves_font or not _BARE_NUMBER_RE.match(ln["text"]) or k + 1 >= len(lines):
            return False
        if not all(s["role"] == "moves" for s in ln["spans"] if s["text"].strip()):
            return False
        nxt = lines[k + 1]
        return (nxt["role"] in ("moves", "text") and nxt["col"] == ln["col"]
                and bool(_shape(nxt["text"].split(" ")[0])))

    @staticmethod
    def number_line_move(prev, prev_classes, ln, classes):
        """Moves set as a narrow table: a move number in the move font alone on
        its line, the move on the next line ("12" / "ttJxd5"). OCR fonts often
        set that move in another font; it belongs to the main line all the
        same, as do the moves that follow it on its line."""
        if (prev["col"] != ln["col"] or not all(c == "m" for c in prev_classes)
                or not _NUMBER_LINE_RE.match(prev["text"])):
            return
        for k, w in enumerate(ln["text"].split(" ")):
            if classes[k] == "m":
                continue
            if not (_shape(w) or _DOTS_RE.match(w)):
                break
            classes[k] = "m"

    def centred(self, page, ln):
        edges = self.column_edges(page, ln["col"])
        if not edges:
            return False
        cx = (ln["bbox"][0] + ln["bbox"][2]) / 2
        return abs(cx - (edges[0] + edges[1]) / 2) < 0.12 * (edges[1] - edges[0])

    def para_start(self, page, ln, prev):
        if prev is None or prev["col"] != ln["col"] or prev["page"] != ln["page"]:
            return True
        if abs(prev["bbox"][1] - ln["bbox"][1]) < 2 and ln["bbox"][0] > prev["bbox"][0]:
            return False            # one printed line that the PDF splits at a gap
        edges = self.column_edges(page, ln["col"])
        if edges is None:
            return False
        if ln["bbox"][0] > edges[0] + 0.45 * self.bs:
            return True
        return prev["bbox"][2] < edges[1] - 2.5 * self.bs

    # -------------------------------------------------------- runs
    def runs(self, st):
        """Main and note runs of the stream, block by block (headings, game
        headers, captions, solution numbers and excluded pages end a block;
        a diagram ends a run where the numbering does not go on across it)."""
        cuts = sorted({0, st.pos} | {off for off, _, kind, _ in st.events
                                      if kind in ("heading", "game_header", "caption", "break",
                                                  "exercise")})
        diagrams = sorted(off for off, _, kind, _ in st.events if kind == "diagram")
        out = []
        for a, b in zip(cuts, cuts[1:]):
            if b <= a:
                continue
            for kind, text in (("main", st.main_text), ("note", st.note_text)):
                chunk = text[a:b]
                # a run needs a move number, which OCR may print as "l."
                if not _NUMBER_HINT_RE.search(chunk):
                    continue
                # the main-font text holds moves only, so junk standing where
                # the numbering expects a move is kept as an unreadable move
                for s in find_sequences(chunk, lenient=kind == "main" and self.moves_font,
                                        dotless=self.dotless):
                    toks = [replace(t, start=t.start + a, end=t.end + a) for t in s.tokens]
                    parts = _split_at_diagrams(toks, diagrams)
                    if kind == "main" and self.moves_font:
                        parts = [q for part in parts for q in self.split_inline(st, part)]
                    for part in parts:
                        moves = [t for t in part if t.kind == "move"]
                        if not moves:
                            continue
                        res = next((_norm_result(t.raw) for t in part if t.kind == "result"),
                                   None)
                        out.append(_Run(kind, part, moves, part[0].start, part[-1].end, s.depth,
                                        _ply(moves[0]), res))
        out.sort(key=lambda r: (r.start, r.kind))
        return out

    def main_prose_before(self, off):
        """True when words of prose in the move font stand before off on its
        printed line ("pawn to take; for instance, 11 Qh4 ...")."""
        i = self.line_index(self.st, off)
        if i < 0:
            return False
        seg = self.st.main_text[self.st.lines[i].start:off]
        return any(re.fullmatch(r"(?=[a-z]*[aeiouy])[a-z]{3,}", w) and not _shape(w)
                   for w in re.split(r"[\s,;:.()]+", seg))

    def prose_line(self, off):
        """True when the printed line holding off has words of prose in it,
        whatever their font, or continues a sentence from the line before."""
        i = self.line_index(self.st, off)
        if i < 0:
            return False

        def prose(k):
            words = self.st.lines[k].line["text"].split(" ")
            return sum(1 for w in words if len(w) >= 3 and w.isalpha() and not _shape(w)) >= 2

        if prose(i):
            return True
        # or the sentence of the line before runs on to this line
        return (i > 0 and self.st.lines[i].start == off and prose(i - 1)
                and not re.search(r"[.!?:;]\s*$", self.st.lines[i - 1].line["text"]))

    @staticmethod
    def line_index(st, off):
        return bisect.bisect_right(st.starts, off) - 1

    def split_inline(self, st, toks):
        """Split off a move set in the move font inside a sentence of the notes
        whose move number stands in the notes' font ("Perhaps I S ... .tf8 was
        still the best"): in the main-font text it follows the main line's
        last move directly, and find_sequences would take it for the next
        move. It starts a run of its own (a note, see inline_run) that ends
        where a move number begins a new line."""
        out, cur, inline = [], [], False
        for t in toks:
            line = self.line_index(st, t.start)
            new_line = bool(cur) and self.line_index(st, cur[-1].start) != line
            if new_line and t.kind == "move" and self.inline_at(st, t.start) \
                    and _NOTE_NUMBER_END_RE.search(st.note_text[max(0, t.start - 40):t.start]):
                out.append(cur)
                cur, inline = [], True
            elif new_line and inline and t.kind == "number":
                out.append(cur)
                cur, inline = [], False
            cur.append(t)
        if cur:
            out.append(cur)
        return out

    # -------------------------------------------------------- chapter
    def chapter(self, ci, ch):
        st = self.build_stream(ch)
        runs = self.runs(st)
        items = [(off, 0, order, kind, payload) for off, order, kind, payload in st.events]
        items += [(r.start, 1, i, "run", r) for i, r in enumerate(runs)]
        items.sort(key=lambda t: (t[0], t[1], t[2]))
        self.st, self.ci = st, ci
        self.active = None
        self.pending_header = None
        self.pending_number = None
        self.section = ""
        self.section_page = ch["start"]
        self.cut = 0
        self.last_token_end = 0
        self.diagram_events = []        # (offset, id)
        self.exercise = None            # (number, diagram id or None, offset)
        self.ex_pointer = -1            # index of the last diagram matched to a solution
        self.pre_notes = []             # note runs between a game header and its first move
        self.diagram_section = []       # section index of each diagram event
        self.section_index = 0
        self.ex_group = -1              # unlabelled-diagram group used for solutions
        self.ex_last = None             # number of the previous solution
        self.structural = 0             # offset of the last structural event
        self.section_raw = ""
        self.prev_heading = None
        self.last_closed = None
        self.suspended = None           # (line, offset): a line a heading interrupted
        prev_kind = None
        self.now = 0
        for off, _, _, kind, x in items:
            self.now = off
            a = self.active
            if a is not None and a.close_at is not None and off >= a.busy_until:
                self.close(max(a.close_at, a.busy_until))
            if kind in ("game_header", "break", "diagram", "exercise"):
                self.close_suspended()          # the heading did end the line
            if kind in ("heading", "game_header", "break", "diagram", "exercise"):
                self.flush_pre_notes()
            a = self.active
            if kind == "heading":
                self.suspend(off)
                raw = x["text"]
                ph = self.prev_heading
                joined = (prev_kind == "heading" and ph is not None and ph["page"] == x["page"]
                          and ph["col"] == x["col"]
                          and -0.5 * self.bs <= x["bbox"][1] - ph["bbox"][3] <= 0.9 * self.bs)
                self.section_raw = (self.section_raw + " " + raw) if joined else raw
                self.section = pt._clean_title(self.section_raw)
                self.prev_heading = x
                if not joined:
                    self.section_index += 1
                self.section_page = x["page"]
                self.cut = self.structural = off
                self.pending_header = self.pending_number = self.exercise = None
            elif kind == "game_header" and prev_kind == "game_header" and \
                    self.pending_header is not None and not self.pending_header.get("year") \
                    and not pt.GAME_HEADER_RE.match(x["text"]):
                # the second line of a header ("Flohr - Horowitz, USSR - USA" /
                # "Radio Match 1945")
                ph = self.pending_header
                merged = parse_game_header(ph["text"] + ", " + x["text"])
                if merged:
                    merged["page"], merged["offset"] = ph["page"], ph["offset"]
                    self.pending_header = merged
            elif kind == "game_header":
                self.close(off)
                self.pending_header = parse_game_header(x["text"]) or {
                    "text": x["text"], "white": "", "black": "", "event": "", "site": "",
                    "year": None}
                self.pending_header["page"] = x["page"]
                self.pending_header["offset"] = off
                self.pending_number = self.exercise = None
                self.structural = off
            elif kind == "break":
                self.close(off)
                self.cut = self.structural = off
                self.pending_header = self.pending_number = self.exercise = None
            elif kind == "diagram":
                self.diagram_events.append((off, x))
                self.diagram_section.append(self.section_index)
                if a is not None and not a.waiting and a.main_tok:
                    # a diagram printed right after decoded moves shows the
                    # position they reach (a guess for Stage 3 to check); the
                    # run may already go on past the diagram
                    ends = [e for _, e, _ in a.main_tok]
                    k = bisect.bisect_right(ends, off) - 1
                    if k >= 0 and len(self.st.orig_text[ends[k]:off].strip()) < 120 and \
                            self.nodes[a.main_tok[k][2]]["fen"]:
                        self.after_node.setdefault(x, a.main_tok[k][2])
                if a is not None and a.kind == "fragment" and a.main_tok:
                    self.request_close(off)
                self.structural = max(self.structural, off)
            elif kind == "caption":
                self.structural = max(self.structural, off)
            elif kind == "exercise":
                self.request_close(off)
                if self.active is None:
                    self.exercise = (x, self.exercise_diagram(x, off), off)
                    self.structural = off
            elif kind == "para":
                # a new paragraph that does not open with a solution number ends
                # the solution's context (its line stays open for notes)
                if self.exercise is not None and off > self.exercise[2]:
                    self.exercise = None
            elif kind == "number":
                self.pending_number = (x, off)
            elif kind == "result":
                if a is not None and a.main_tok:
                    a.result = a.result or x[0]
                    self.request_close(off + x[1])
            elif kind == "run":
                if x.kind == "main":
                    self.on_main(x)
                else:
                    self.on_note(x)
            if kind != "page":
                prev_kind = kind
        self.close(st.pos)
        self.flush_pre_notes()

    def flush_pre_notes(self):
        """Note runs held back while no line was open: the context they belong
        to is ending, so they start their own line now (from the diagram before
        them), and the notes after the first become its variations."""
        notes, self.pre_notes = self.pre_notes, []
        for run in notes:
            L = self.active
            if L is not None:
                L.notes.append((run, False))
                continue
            if run.ply is None:
                self.unplaced(run, "its first move carries no move number")
                continue
            saved = self.exercise
            self.exercise = run.context
            try:
                L = self.from_diagram(run, "note", did=run.home)
            finally:
                self.exercise = saved
            if L is not None:
                self.active = L
                self.extend(L, run)

    def adopt_pre_notes(self, L):
        """Notes held back before a main line began belong to it."""
        if L is not None and self.pre_notes:
            L.notes.extend((r, False) for r in self.pre_notes)
            self.pre_notes = []

    def release_pre_notes(self, home):
        """Before a main line that starts from home (a diagram id, or None for
        the initial position) begins, held notes that would start from another
        diagram become lines of their own."""
        keep = [r for r in self.pre_notes if r.home is None or r.home == home]
        other = [r for r in self.pre_notes if not (r.home is None or r.home == home)]
        if other:
            self.pre_notes = other
            self.flush_pre_notes()
            self.close(self.now)
        self.pre_notes = keep

    def request_close(self, off):
        """Close the active line at off, or once the timeline has passed the end
        of its last main run when off falls inside that run."""
        a = self.active
        if a is None:
            return
        if self.now >= a.busy_until:
            self.close(off)
        else:
            a.close_at = max(off, a.close_at or 0)

    # -------------------------------------------------------- diagrams for lines
    def exercise_diagram(self, label, off):
        """The diagram a numbered solution refers to.

        First choice: the first diagram labelled with the same number after the
        diagram matched to the previous solution, preferring numbers outside
        the book's main numbered series. Books that print circled numbers often lose them to
        OCR; then solution N maps to the N-th unlabelled diagram of a section,
        taking the sections that hold unlabelled diagrams in order and moving
        to the next one each time the solution numbers start again. Pictures
        the selection leaves out do not count."""
        n = int(label) if label.isdigit() else None
        restart = n is not None and (self.ex_last is None or n <= self.ex_last)
        if n is not None:
            self.ex_last = n
        for main_ok in (False, True):
            for i, (doff, did) in enumerate(self.diagram_events):
                if i <= self.ex_pointer or doff > off:
                    continue
                d = self.diag_info[did]
                if d.get("label") == label and (main_ok or d.get("series") != "main"):
                    self.ex_pointer = i
                    return did
        if n is None:
            return None
        groups, cur = [], None
        for i, ((doff, did), sec) in enumerate(zip(self.diagram_events, self.diagram_section)):
            if doff > off:
                break
            if self.diag_info[did].get("label") or not self.diagram_selected(did):
                continue
            if cur is None or cur[0] != sec:
                cur = (sec, [])
                groups.append(cur)
            cur[1].append((i, did))
        if restart:
            self.ex_group += 1
        if 0 <= self.ex_group < len(groups) and n <= len(groups[self.ex_group][1]):
            i, did = groups[self.ex_group][1][n - 1]
            self.ex_pointer = max(self.ex_pointer, i)
            return did
        return None

    def usable_diagram(self, off):
        """The diagram a line starting at off begins from: the last diagram before
        it, provided no heading and no earlier line's moves stand between them."""
        if self.exercise is not None:
            return self.exercise[1]
        for doff, did in reversed(self.diagram_events):
            if doff >= off:
                continue
            if doff < max(self.cut, self.last_token_end):
                return None
            return did
        return None

    def last_diagram(self, off):
        """The last diagram before off in reading order in this chapter, if any."""
        for doff, did in reversed(self.diagram_events):
            if doff < off:
                return did
        return None

    def diagram_name(self, did):
        """'Diagram 12 on page 5', or 'the unnumbered diagram 2 on page 197'."""
        d = self.diag_info.get(did) or {}
        lab = d.get("label")
        page = self.page_label(d.get("page"))
        if lab:
            return f"Diagram {lab} on page {page}"
        k = did.split("-")[1] if did and "-" in did else "?"
        return f"the unnumbered diagram {k} on page {page}"

    # -------------------------------------------------------- the text around a run
    def para_start_of(self, off):
        k = self.st.orig_text.rfind("\n\n", 0, off)
        return k + 2 if k >= 0 else 0

    def lead_text(self, off, limit=160):
        """The words of the sentence before off, within its paragraph."""
        a = max(self.para_start_of(off), off - limit)
        seg = self.st.orig_text[a:off]
        ends = list(_SENTENCE_END_RE.finditer(seg))
        if ends:
            seg = seg[ends[-1].end():]
        return re.sub(r"[ \n\r]+", " ", seg)

    def referenced_diagram(self, run):
        """(label, diagram id or None) when the sentence before the run names a
        diagram ("To return to Diagram 430, ... 1.Rg4+"), else None."""
        hits = list(_DIAGRAM_REF_RE.finditer(self.lead_text(run.start, 300)))
        if not hits:
            return None
        lab = hits[-1].group(1).translate(pt.DIGIT_FIX).replace("O", "0")
        for _, did in reversed(self.diagram_events):
            if self.diag_info[did].get("label") == lab:
                return lab, did
        found = [did for did, d in self.diag_info.items() if d.get("label") == lab]
        main = [did for did in found if self.diag_info[did].get("series") == "main"]
        pick = main or found
        return lab, (pick[0] if len(pick) == 1 else None)

    def is_threat(self, run):
        """True when the text gives the run as a threat, a plan or an idea: a
        cue such as "threatening" stands before it in its sentence, with only
        moves and linking words between."""
        lead = self.lead_text(run.start)
        hits = list(_THREAT_RE.finditer(lead))
        if not hits:
            return False
        tail = lead[hits[-1].end():]
        if ")" in tail:
            return False                 # the threat was given in brackets before the run
        words = [w.strip("(),;:").lower() for w in tail.split(" ")]
        if "if" in words or "when" in words or "on" in words:
            return False                 # "..., and if 1...Re1 then 2.Rg7+": a variation
        return not [w for w in words if len(w) > 1 and w.isalpha() and w not in _CONNECT_WORDS]

    def inline_run(self, run):
        """True for main-font moves inside a sentence of body text ("should White
        play 1.g6+, the reply would be ..."): set in the move font, but
        mentioned in the notes rather than played."""
        return self.inline_at(self.st, run.start)

    @staticmethod
    def inline_at(st, off):
        """True when the main-font text at off stands inside a sentence of body
        text (see inline_run)."""
        i = bisect.bisect_right(st.starts, off) - 1
        if i < 0:
            return False
        tl = st.lines[i]
        if tl.line["role"] != "text":
            return False
        if any(ch.isalpha() for ch in st.note_text[tl.start:off].replace(NOTE_BREAK, " ")):
            return True
        # a printed line that the PDF splits at a wide gap: body words before
        # the run on the same row
        y, col = tl.line["bbox"][1], tl.line.get("col")
        for k in range(i - 1, max(i - 4, -1), -1):
            o = st.lines[k]
            if o.page != tl.page or abs(o.line["bbox"][1] - y) > 2 or o.line.get("col") != col:
                break
            seg = st.note_text[o.start:o.start + len(o.line["text"])].replace(NOTE_BREAK, " ")
            if o.line["role"] == "text" and any(ch.isalpha() for ch in seg):
                return True
        return False

    def no_start_reason(self, run, initial=False):
        """Why a run that needs a starting position found none, in plain words."""
        head = ("its moves do not read as play from the initial position"
                if initial else f"it starts at {_ply_words(run.ply)}")
        last = self.last_diagram(run.start)
        prev = self.last_closed
        if (not initial and prev is not None and prev.chapter == self.ci and not prev.waiting
                and run.ply is not None and prev.next_ply < run.ply
                and (last is None or self.diagram_offset(last) < prev.first_offset)):
            return (f"{head}, and the line \"{prev.title}\" before it stops at "
                    f"{_ply_words(prev.next_ply - 1)}, with the moves between missing from the text")
        if last is not None:
            return (f"{head}, and a heading or other moves stand between it and the last "
                    f"diagram before it, {self.diagram_name(last)}")
        return f"{head}, and no diagram comes before it in this chapter"

    def diagram_offset(self, did):
        for doff, d in self.diagram_events:
            if d == did:
                return doff
        return -1

    # -------------------------------------------------------- lines
    def start_line(self, run, kind, title, waiting, diagram, born, header=None, fen=None):
        line_id = f"L{len(self.lines) + 1}"
        page = self.st.page_at(run.start)
        start_ply = run.ply if run.ply is not None else 0
        if fen is not None:
            start_ply = _board_ply(fen)
        L = _Line(line_id, kind, title, self.ci, page, "", fen, waiting, diagram,
                  display_title(self.section), header, self.line_start_offset(run.start),
                  start_ply, fen, born)
        L.first_offset = run.start
        root = self.new_node(L, fen=fen, status="waiting" if waiting else "root", main=True,
                             page=page)
        L.root = root
        L.main_nodes.append(root)
        L.ply_node[start_ply - 1] = root
        self.lines.append(L)
        return L

    def line_start_offset(self, off):
        return max(self.structural, self.last_token_end, self.cut)

    def title_for(self, run, diagram):
        if self.pending_header:
            return self.pending_header["text"]
        sec = display_title(self.section)
        if self.exercise is not None and (diagram is None or diagram == self.exercise[1]):
            return f"{sec} {self.exercise[0]}".strip() if sec else f"Exercise {self.exercise[0]}"
        if self.pending_number is not None:
            n = self.pending_number[0]
            self.pending_number = None
            return f"{sec} {n}".strip() if sec else f"Game {n}"
        if diagram:
            lab = self.diag_info[diagram].get("label")
            return (f"Diagram {lab}" if lab else
                    f"Diagram on page {self.page_label(self.diag_info[diagram]['page'])}")
        page = self.page_label(self.st.page_at(run.start))
        return f"{sec}, page {page}" if sec else f"Page {page}"

    def diagram_selected(self, did):
        return did is not None and self.selection.diagram_selected(did)

    def from_diagram(self, run, born, kind=None, title=None, did=None):
        """Start a line at a run that needs a diagram's position: the diagram
        the sentence names, or else the diagram before the run."""
        if did is None:
            ref = self.referenced_diagram(run)
            if ref and ref[1]:
                did = ref[1]
        did = did or self.usable_diagram(run.start)
        if did is None:
            self.unplaced(run, self.no_start_reason(run))
            return None
        if not self.diagram_selected(did):
            self.unplaced(run, f"it starts from {self.diagram_name(did)}, which the selection "
                               "leaves out")
            return None
        header = self.pending_header
        kind = kind or ("game" if header else "fragment")
        title = title or self.title_for(run, did)
        fen = self.diagram_fen(did, run)
        L = self.start_line(run, kind, title, fen is None, did, born, header, fen)
        self.pending_header = None
        if fen is None:
            self.waiting.append({"page": L.page, "chapter": self.ci, "text": self.run_text(run),
                                 "reason": WAIT_REASON, "line": L.id, "diagram": did})
        return L

    def detached_line(self, run, did, lab):
        """A note run that the text ties to another diagram ("To return to
        Diagram 430, ...") starts its own line from that diagram."""
        if run.ply is None:
            self.unplaced(run, "its first move carries no move number")
            return
        if not self.diagram_selected(did):
            self.unplaced(run, f"the text refers it to {self.diagram_name(did)}, which the "
                               "selection leaves out")
            return
        fen = self.diagram_fen(did, run)
        L = self.start_line(run, "fragment", f"Diagram {lab}", fen is None, did, "note", None, fen)
        L.start_offset = run.start
        if fen is None:
            self.waiting.append({"page": L.page, "chapter": self.ci, "text": self.run_text(run),
                                 "reason": WAIT_REASON, "line": L.id, "diagram": did})
        self.extend(L, run)
        L.end_offset = run.end
        self.finish_line(L)

    def diagram_fen(self, did, run):
        fen = self.diagram_fens.get(did)
        if not fen:
            return None
        b = chess.Board(fen)
        want = chess.BLACK if (run.ply or 0) % 2 else chess.WHITE
        if b.turn != want:
            b.turn = want
            b.ep_square = None
        if run.ply is not None:
            b.fullmove_number = run.ply // 2 + 1      # the book's numbering
        return b.fen()

    def run_text(self, run):
        return re.sub(r"[ \n\r]+", " ", self.st.orig_text[run.start:run.end]).strip()

    def unplaced(self, run, reason):
        page = self.st.page_at(run.start)
        self.unattached.append({"page": page, "chapter": self.ci, "text": self.run_text(run),
                                "reason": reason})
        for t in run.moves:
            self.mark(self.st, t, None, "unattached", reason=reason)

    # -------------------------------------------------------- main runs
    def on_main(self, run):
        if self.suspended is not None:
            L = self.suspended[0]
            if run.ply != L.next_ply:
                run = _renumbered(run, L.next_ply) or self.misnumbered(L, run) or run
            if not self.resume(run):
                self.close_suspended()
        L = self.active
        if L is not None and run.ply != L.next_ply:
            run = _renumbered(run, L.next_ply) or self.misnumbered(L, run) or run
        P = run.ply
        first = run.tokens[0]
        if self.main_prose_before(run.start) or (
                first.kind == "number" and first.number is None and self.prose_line(run.start)):
            # "WARNING: ... 10 ... gxf5 is always very risky; for instance,
            # 11 Qh4", "playing ... d5 in one go": moves named in a box of
            # advice that the book sets in the move font, not moves of the game
            self.on_note(run)
            return
        if P is None and L is not None and run.moves[0].black:
            # "... Kd8": Black's move with no number. When the line expects
            # White's move, White's move is missing from the text.
            P = L.next_ply if L.next_ply % 2 == 1 else L.next_ply + 1
        solution = self.exercise is not None and L is None
        if (L is None or P != L.next_ply or run.tokens[0].kind != "number") and not solution \
                and self.inline_run(run):
            self.on_note(run)                   # moves mentioned in a sentence
            return
        if P == 0:
            if L is not None:
                self.close(run.start)
            accept, _, did = self.initial_accept(run)
            self.release_pre_notes(None if accept else did)
            self.adopt_pre_notes(self.start_from_initial(run, "main"))
            return
        if L is not None and P == L.next_ply:
            if self.pending_header and L.header is None:
                L.header, L.kind, L.title = self.pending_header, "game", self.pending_header["text"]
                self.pending_header = None
            self.extend(L, run)
            return
        between = L is not None and self.diagram_between(L, run)
        if L is not None and P is not None and not between:
            # The numbering does not continue the line, but nothing stands
            # between: moves missing from the text, moves the book leaves out
            # ("1.Kxc3+, 2.Qxf5+, ..."), a misprinted number, or a variation
            # in the main font.
            if L.waiting or L.broken:
                if P > L.next_ply:
                    self.extend(L, run)
                    return
            elif P > L.next_ply:
                if P - L.next_ply <= GAP_MAX:
                    self.gap(L, run, P)
                    return
            else:
                decs = self.dec.run(L.last_fen, run.tokens)
                if _fit(decs)[0] == 0:
                    self.extend(L, run, decs)
                    return
            if P < L.next_ply:
                L.notes.append((run, True))      # a main-font variation
                return
        if L is not None:
            title = f"{L.title} (from move {_ply_label(P)})" if L.header else None
            header = L.header
            if (between and P is not None and P > L.next_ply and not L.waiting
                    and not L.broken and L.kind == "game"):
                # the game goes on after a diagram, but moves before it are
                # missing from the text (printed inside the picture)
                self.gap(L, run, P, follow=False)
            self.close(run.start)
            if P is None:
                self.unplaced(run, "its first move carries no move number")
                return
            self.pending_header = self.pending_header or header
            self.release_pre_notes(self.usable_diagram(run.start))
            L2 = self.from_diagram(run, "main", kind="fragment" if header else None, title=title)
        else:
            if P is None:
                self.unplaced(run, "its first move carries no move number")
                return
            self.release_pre_notes(self.usable_diagram(run.start))
            L2 = self.from_diagram(run, "main")
        if L2 is not None:
            self.active = L2
            self.extend(L2, run)
            self.adopt_pre_notes(L2)

    def misnumbered(self, L, run):
        """The run renumbered to continue L when its printed number differs from
        the expected one in a digit that OCR misreads ("1 ... fxe4" for 7...fxe4)
        and its moves read cleanly as the continuation of L, else None."""
        first = run.tokens[0]
        if (L.waiting or L.broken or not L.last_fen or first.kind != "number"
                or first.number is None):
            return None
        n, black = L.next_ply // 2 + 1, bool(L.next_ply % 2)
        if first.side_known and bool(first.black) != black:
            return None
        if not _ocr_digit_slip(first.raw, n):
            return None
        toks = list(run.tokens)
        _relabel(toks, n, black)
        if _fit(self.dec.run(L.last_fen, toks))[0] != 0:
            return None
        moves = [t for t in toks if t.kind == "move"]
        return _Run(run.kind, toks, moves, run.start, run.end, run.depth, _ply(moves[0]),
                    run.result, run.home, run.context)

    def gap(self, L, run, P, follow=True):
        """The numbering skips moves that the text does not show (P is the ply
        the run starts at). The program does not invent them: the decoded part
        of the line ends with a node that marks the gap, and with follow the
        run's moves come after it as unread text, since the position there is
        unknown."""
        missing = P - L.next_ply
        what = _ply_words(L.next_ply)
        if missing > 1:
            what += f" and the {missing - 1} move{'s' if missing > 2 else ''} after it"
        reason = (f"The book's text lacks {what}, so the program cannot follow the line "
                  "from here." if follow else
                  f"The book's text lacks {what}; the line goes on from the diagram after it.")
        nid = self.new_node(L, parent=L.main_nodes[-1], number=L.next_ply // 2 + 1,
                            black=bool(L.next_ply % 2), status="failed", raw="", main=True,
                            page=self.st.page_at(run.start), reason=reason)
        L.main_nodes.append(nid)
        L.broken = True
        L.last_fen = None
        L.ply_node[L.next_ply] = nid
        L.next_ply = P
        if follow:
            self.extend(L, run)

    def diagram_between(self, L, run):
        return any(L.last_token_end < off < run.start for off, _ in self.diagram_events)

    def initial_accept(self, run):
        """(accept, decoded, diagram): whether a run from move 1 reads as play
        from the initial position.

        A run after a game header does, unless it reads very badly. Otherwise
        it must read cleanly over at least two moves each (or one, when the
        text introduces opening moves), and no move may contradict a piece
        glyph or a capture mark printed in the text ("1.Rg3" printed with a
        rook glyph is not 1.g3). A run whose sentence names a diagram or sets
        up a position ("White: ...") never does."""
        decs = self.dec.run(chess.STARTING_FEN, run.tokens)
        rank = _fit(decs)[0]
        n = len(run.moves)
        did = self.usable_diagram(run.start)
        failed = sum(d.status == "failed" for d in decs)
        lost = any(d.glyph_lost or (d.capture_mark and d.san and "x" not in d.san) for d in decs)
        lead = self.lead_text(run.start, 240)
        if self.pending_header is not None:
            # a game from its first move, unless a diagram printed under the
            # header shows the position the moves start from ("1.Rb3!")
            accept = (rank <= 1 or (n >= 6 and failed <= 0.2 * n and decs[0].status != "failed")) \
                and (did is None or (n >= 6 and not lost))
        elif lost or self.referenced_diagram(run) or _SETUP_RE.search(lead):
            accept = False
        elif rank == 0:
            accept = n >= 4 or (n >= 2 and bool(_OPENING_RE.search(lead)))
        elif rank == 1:
            accept = n >= 10 and failed <= 0.1 * n
        else:
            accept = False
        return accept, decs, did

    def start_from_initial(self, run, born):
        """Start a line at a run that begins at move 1 with White: from the initial
        position when it reads as play from there, otherwise from its diagram."""
        header = self.pending_header
        accept, decs, did = self.initial_accept(run)
        if not accept and (did is not None or self.referenced_diagram(run)):
            L = self.from_diagram(run, born)
            if L is not None:
                self.active = L
                self.extend(L, run)
            return L
        if accept:
            title = self.title_for(run, None)
            kind = "game" if (header or born == "main") else "fragment"
            L = self.start_line(run, kind, title, False, None, born, header, chess.STARTING_FEN)
            self.pending_header = None
            self.active = L
            self.extend(L, run, decs)
            if did is not None and (born == "note" or self.exercise is not None):
                # "This position arises after the opening moves 1.e4 e5 ...", or
                # the solution of "how did this position arise?": the diagram
                # shows the position these moves reach
                self.after_node.setdefault(did, L.main_nodes[-1])
            return L
        self.unplaced(run, self.no_start_reason(run, initial=True))
        return None

    def extend(self, L, run, decs=None):
        """Append a run to the main line of L."""
        if not (L.waiting or L.broken) and decs is None:
            decs = self.dec.run(L.last_fen, run.tokens)
        parent = L.main_nodes[-1]
        if L.waiting or L.broken:
            for t in run.moves:
                ply = _ply(t) if _ply(t) is not None else L.next_ply
                parent = self.add_waiting(L, parent, t, True, ply)
                L.main_nodes.append(parent)
                L.ply_node[ply] = parent
                L.next_ply = ply + 1
                L.main_tok.append((t.start, t.end, parent))
        else:
            self.dec.accepted.append(decs)
            for t, d in zip(run.moves, decs):
                new, _ = self.add_decoded(L, parent, t, d, True)
                for nid in new:
                    L.main_nodes.append(nid)
                parent = new[-1]
                # the board's own numbering: a failed token that took no ply
                # does not shift the moves after it
                ply = self.node_ply(parent)
                if ply is None:
                    ply = _ply(t) if _ply(t) is not None else L.next_ply
                L.ply_node[ply] = parent
                fen = self.nodes[parent]["fen"]
                L.next_ply = _board_ply(fen) if fen else ply + 1
                L.main_tok.append((t.start, t.end, parent))
            L.last_fen = self.nodes[parent]["fen"] or L.last_fen
        for t in run.tokens:
            L.consumed.append((t.start, t.end))
        L.last_token_end = max(L.last_token_end, run.end)
        L.busy_until = max(L.busy_until, run.end)
        self.last_token_end = max(self.last_token_end, run.end)
        if run.result:
            L.result = run.result
            if self.active is L:
                self.request_close(run.end)

    def add_waiting(self, L, parent, tok, main, ply=None):
        """A node for a move whose position is unknown: waiting for its diagram,
        or after a gap in the text of a decoded line (status failed)."""
        number, black = tok.number, bool(tok.black)
        if number is None and ply is not None:
            number, black = ply // 2 + 1, bool(ply % 2)
        if L.waiting:
            nid = self.new_node(L, parent=parent, number=number, black=black,
                                status="waiting", raw=tok.raw, main=main)
            status = "waiting"
        else:
            nid = self.new_node(L, parent=parent, number=number, black=black,
                                status="failed", raw=tok.raw, main=main,
                                reason="The position here is unknown, because the book's text "
                                       "lacks a move before it.")
            status = "failed"
        page, box = self.mark(self.st, tok, nid, status, L.id)
        self.nodes[nid]["page"], self.nodes[nid]["bbox"] = page, box
        return nid

    def add_decoded(self, L, parent, tok, d, main, merge=False):
        """Nodes for one decoded token under parent; returns (node ids, reused).
        With merge, a move that parent already has as a child reuses that child
        (reused is True). The move number and side come from the position the
        move is played in, so that the labels always match the board."""
        out = []
        board = chess.Board(self.nodes[parent]["fen"])
        number, black = board.fullmove_number, board.turn == chess.BLACK
        if d.san and d.fen:
            hit = self.child_with(parent, d.san) if merge else None
            if hit is not None:
                out.append(hit)
                self.mark(self.st, tok, hit, self.nodes[hit]["status"], L.id)
                return out, True
            nid = self.new_node(L, parent=parent, san=d.san, fen=d.fen, number=number,
                                black=black, status=d.status, raw=tok.raw, main=main,
                                uci=d.uci)
            if d.alternatives:
                self.nodes[nid]["alternatives"] = list(d.alternatives[:4])
        else:
            assumed = d.alternatives[0] if d.alternatives else None
            uci = None
            if assumed:
                try:
                    mv = board.parse_san(assumed)
                    uci = mv.uci()
                    board.push(mv)
                except ValueError:
                    assumed = None
            nid = self.new_node(L, parent=parent, san=None, fen=board.fen(), number=number,
                                black=black, status="failed", raw=tok.raw, main=main,
                                assumed=assumed, uci=uci)
        page, box = self.mark(self.st, tok, nid, self.nodes[nid]["status"], L.id)
        self.nodes[nid]["page"], self.nodes[nid]["bbox"] = page, box
        out.append(nid)
        return out, False

    def child_with(self, parent, san):
        for c in self.nodes[parent]["children"]:
            if self.nodes[c]["san"] == san:
                return c
        return None

    # -------------------------------------------------------- note runs
    def on_note(self, run):
        L = self.active
        if L is not None:
            L.notes.append((run, False))
            return
        # A note with no line open either tells how the position arose
        # ("after the opening moves 1.e4 e5 ...": a line from the initial
        # position) or discusses the position before its main line begins
        # ("A clear draw results from 1.a7?"): it waits for that main line.
        if run.ply == 0 and self.initial_accept(run)[0]:
            self.start_from_initial(run, "note")
            return
        run.home = self.usable_diagram(run.start)
        run.context = self.exercise
        self.pre_notes.append(run)

    def attach_notes(self, L):
        blocks = [s for s, _, _ in L.main_tok]
        variations = defaultdict(list)          # block -> [variation records]
        last_var = None
        for run, as_main in L.notes:
            if self.is_threat(run):
                self.unplaced(run, "the text gives these moves as a threat or a plan, not as "
                                   "moves played")
                self.tidy(L, run)
                continue
            ref = self.referenced_diagram(run)
            if ref and ref[1] and ref[1] != L.diagram:
                self.detached_line(run, ref[1], ref[0])
                continue
            if run.ply is None and not _ALT_CUE_RE.search(self.lead_text(run.start, 60)):
                self.unplaced(run, "its first move carries no move number, and no word such as "
                                   "\"instead\" or \"better\" ties it to a move of the line")
                self.tidy(L, run)
                continue
            block = bisect.bisect_left(blocks, run.start)
            follows = last_var is not None and bool(_FOLLOW_RE.search(
                self.lead_text(run.start, 40)))
            placed = self.place(L, run, block, variations[block],
                                only=last_var if follows else None)
            if placed is True:
                L.variations += 1
                last_var = variations[block][-1]
                continue
            if run.ply == 0 and not as_main and (L.waiting or 0 not in L.ply_node):
                # an opening sequence inside a line that starts later: its own fragment
                decs = self.dec.run(chess.STARTING_FEN, run.tokens)
                if self.side_ok(run, decs):
                    self.side_fragment(run, decs, L)
                    continue
            self.unplaced(run, self.why_not(L, run, placed, follows))
            self.tidy(L, run)

    def side_ok(self, run, decs):
        """Whether a note run from move 1 inside another line reads as its own
        sequence from the initial position: cleanly, over two moves each at
        least, with no piece glyph or capture mark dropped, and with no
        diagram named or position set up in its sentence."""
        if _fit(decs)[0] != 0 or len(run.moves) < 4:
            return False
        if any(d.glyph_lost or (d.capture_mark and d.san and "x" not in d.san) for d in decs):
            return False
        lead = self.lead_text(run.start, 240)
        return not (self.referenced_diagram(run) or _SETUP_RE.search(lead) or self.is_threat(run))

    def why_not(self, L, run, placed, follows=False):
        if follows:
            return ("the text gives it as the continuation of the variation before it, "
                    "and it does not read as legal play from there")
        if placed is None and run.ply is None:
            return (f"its first move carries no move number, and no move of the line "
                    f"\"{L.title}\" fits it")
        if placed is None:
            return (f"the line \"{L.title}\" does not reach {_ply_words(run.ply)}, where it "
                    "would branch off")
        if isinstance(placed, tuple) and placed[1]:
            return placed[1]
        if run.ply is None:
            return f"its moves are not legal at any place in the line \"{L.title}\""
        return (f"its moves are not legal where the numbering puts them in the line "
                f"\"{L.title}\", at {_ply_words(run.ply)}")

    def side_fragment(self, run, decs, owner):
        title = f"{owner.title}: moves from the initial position"
        L = self.start_line(run, "fragment", title, False, None, "note", None, chess.STARTING_FEN)
        L.start_offset = run.start
        self.extend(L, run, decs)
        L.end_offset = run.end
        self.finish_line(L)

    def candidates(self, L, run, block, vars_):
        """Places a note run can go, best first: (parent node, kind)."""
        P = run.ply
        plies = [P] if P is not None else []
        if P is None:
            for b in (block - 1, block):
                if 0 <= b < len(L.main_tok):
                    nid = L.main_tok[b][2]
                    ply = self.node_ply(nid)
                    if ply is not None and ply % 2 == 1:
                        plies.append(ply)
            if L.next_ply % 2 == 1 and block >= len(L.main_tok):
                plies.append(L.next_ply)
        out = []

        def add(parent, how):
            if parent is not None and (parent, how) not in out:
                out.append((parent, how))

        cont = [v for v in vars_ if v["depth"] == run.depth]
        inner = [v for v in vars_ if v["depth"] < run.depth]
        for ply in plies:
            if run.depth > 0 and inner:
                v = inner[-1]
                if ply in v["plies"]:
                    add(self.nodes[v["plies"][ply]]["parent"], "branch")
                elif v["next"] == ply:
                    add(v["last"], "branch-end")
            if cont and cont[-1]["next"] == ply:
                add(cont[-1]["last"], "continue")
            # an earlier variation of the note that ends where the run begins
            # ("9 0-0 (or 9 Bg5 ...) 9 ... d5 10 Bb3 and then: a) 10 ... b5")
            for v in reversed(vars_):
                if v["next"] == ply and v["depth"] <= run.depth:
                    add(v["last"], "resume")
            for v in reversed(vars_):
                if ply in v["plies"]:
                    add(self.nodes[v["plies"][ply]]["parent"], "branch")
            if ply in L.ply_node and ply - 1 in L.ply_node:
                add(L.ply_node[ply - 1], "main")
            if ply == L.next_ply and not L.broken:
                add(L.main_nodes[-1], "end")
        return out

    def node_ply(self, nid):
        n = self.nodes[nid]
        if n["number"] is None:
            return None
        return (n["number"] - 1) * 2 + int(bool(n["black"]))

    def place(self, L, run, block, vars_, only=None):
        """Place a note run in L: True when placed, (False, reason or None) when
        no candidate place reads cleanly, None when the line has no place for
        it at all. With only (a variation record), the run may only continue
        that variation ("..., followed by 15...Nxb4")."""
        if L.waiting and run.ply is None:
            return None             # nothing to check a number-less note against
        if only is not None:
            cands = [(only["last"], "continue")] if only["next"] == run.ply else []
            if not cands:
                return False, None
        else:
            cands = self.candidates(L, run, block, vars_)
        if not cands:
            return None
        if L.waiting:
            parent, how = cands[0]
            nodes = self.insert_waiting(L, parent, run)
        else:
            best, tried = None, None
            for parent, how in cands:
                fen = self.nodes[parent]["fen"]
                if fen is None or (how == "resume" and best is not None):
                    continue            # an older variation only when nothing nearer reads
                decs = self.dec.run(fen, run.tokens)
                f = _fit(decs)
                if any(d.capture_mark and d.san and "x" not in d.san for d in decs):
                    f = (2,) + f[1:]        # a printed capture read as a quiet move
                if tried is None:
                    tried = decs
                if f[0] == 0:
                    best = (f, parent, decs)
                    break
                if f[0] == 1 and (best is None or f < best[0]):
                    best = (f, parent, decs)
            if best is None:
                return False, self.unread_reason(L, run, tried)
            _, parent, decs = best
            self.dec.accepted.append(decs)
            nodes = self.insert_decoded(L, parent, run, decs)
        plies = {}
        for nid in nodes:
            ply = self.node_ply(nid)
            if ply is not None:
                plies[ply] = nid
        last = nodes[-1] if nodes else parent
        vars_.append({"depth": run.depth, "plies": plies, "last": last,
                      "next": (max(plies) + 1) if plies else None})
        return True

    def unread_reason(self, L, run, decs):
        """Tell an unreadable move apart from moves that are not legal there."""
        if not decs:
            return None
        bad = next((d for d in decs if d.status == "failed"), None)
        if bad is not None and not _plain_move(bad.raw):
            where = f" at {_ply_words(run.ply)}" if run.ply is not None else ""
            return (f"the program could not read its move \"{_shown(bad.raw)}\"{where} of the "
                    f"line \"{L.title}\"")
        return None

    def insert_waiting(self, L, parent, run):
        """Waiting moves under parent. Moves that repeat the line's moves (the
        same number, side and printed square) follow the existing nodes, so a
        note that repeats the main line before it branches off shares them."""
        out = []
        following = True
        for t in run.moves:
            hit = None
            if following:
                for c in self.nodes[parent]["children"]:
                    n = self.nodes[c]
                    if (n["number"], n["black"]) == (t.number, bool(t.black)) and \
                            _same_printed_move(n["raw"], t.raw):
                        hit = c
                        break
            if hit is not None:
                self.mark(self.st, t, hit, "waiting", L.id)
                parent = hit
            else:
                following = False
                parent = self.add_waiting(L, parent, t, False)
            out.append(parent)
        self.pretty(L, run, None)
        return out

    def insert_decoded(self, L, parent, run, decs):
        out = []
        merging = True
        for t, d in zip(run.moves, decs):
            new, reused = self.add_decoded(L, parent, t, d, False, merge=merging)
            merging = merging and reused
            parent = new[-1]
            out.extend(new)
        self.pretty(L, run, decs)
        return out

    def pretty(self, L, run, decs):
        """Write the decoded moves of a placed note run into the comment text:
        move numbers are rewritten, and a move reads as SAN with its number
        before it when it is White's or the first of the run."""
        if decs is None:
            self.tidy(L, run)
            return
        di, first = 0, True
        for t in run.tokens:
            if t.kind == "number":
                L.replace.append((t.start, t.end, ""))
                continue
            if t.kind != "move":
                continue
            d = decs[di]
            di += 1
            if d.san:
                lab = ""
                if t.number is not None and (first or not t.black):
                    lab = f"{t.number}..." if t.black else f"{t.number}."
                L.replace.append((t.start, t.end, lab + d.san + (d.annotation or "")))
            else:
                L.replace.append((t.start, t.end, t.raw))
            first = False

    def tidy(self, L, run):
        """Write a note run whose moves stay unread (unplaced, or waiting for a
        diagram) into the comment text in readable form where the junk can be
        read with certainty: "9.tLlxf6t" becomes "9.Nxf6+"."""
        for t in run.tokens:
            if t.kind == "number" and t.number is not None:
                L.replace.append((t.start, t.end, f"{t.number}{'...' if t.black else '.'}"))
            elif t.kind == "move":
                text = readable_move(t.raw, self.dec.glyphs, self.dec.letters)
                if text:
                    L.replace.append((t.start, t.end, text))

    # -------------------------------------------------------- closing
    def suspend(self, off):
        """A heading interrupts the active line. The line is held open instead
        of closed when its decoded moves could go on: when the next main run
        continues its numbering and reads as legal play from its last
        position, the heading was a line inside the game (a chess-font
        diagram, a running title) and the game goes on (see resume)."""
        L = self.active
        if L is None:
            return                  # a suspended line stays so over several headings
        if L.waiting or L.broken or not L.main_tok or not L.last_fen:
            self.close(off)
            return
        self.close_suspended()
        self.suspended = (L, off)
        self.active = None

    def resume(self, run):
        """Reopen the suspended line for a main run that continues it; True when
        it did."""
        L, off = self.suspended
        if run.ply != L.next_ply or self.pending_header is not None:
            return False
        if _fit(self.dec.run(L.last_fen, _first_moves(run.tokens, 4)))[0] != 0:
            return False
        self.suspended = None
        self.active = L
        self.adopt_pre_notes(L)
        return True

    def close_suspended(self):
        if self.suspended is None:
            return
        L, off = self.suspended
        self.suspended = None
        active, self.active = self.active, L
        self.close(off)
        self.active = active

    def close(self, off):
        self.close_suspended()
        L = self.active
        self.active = None
        if L is None:
            return
        L.end_offset = off
        self.finish_line(L)
        self.last_closed = L

    def finish_line(self, L):
        self.attach_notes(L)
        self.comments(L)
        if not L.waiting and L.main_tok:
            ends = [e for _, e, _ in L.main_tok]
            for doff, did in self.diagram_events:
                if L.first_offset < doff < L.last_token_end:
                    k = bisect.bisect_right(ends, doff) - 1
                    if k >= 0 and self.nodes[L.main_tok[k][2]]["fen"]:
                        self.after_node.setdefault(did, L.main_tok[k][2])
        if L.waiting:
            status = "waiting"
        else:
            worst = 0
            for nid in L.main_nodes[1:]:
                worst = max(worst, _LINE_RANK.get(self.nodes[nid]["status"], 0))
            status = {0: "ok", 1: "guessed", 2: "ambiguous", 3: "failed"}[worst]
            if len(L.main_nodes) <= 1:
                status = "failed"
        L.status = status
        if L.main_tok:
            pages = [self.nodes[n]["page"] for _, _, n in L.main_tok if self.nodes[n]["page"]]
            L.end_page = max(pages) if pages else L.page
        else:
            L.end_page = L.page

    def comments(self, L):
        text = self.st.note_text.replace(NOTE_BREAK, " ")
        main = L.main_tok
        if not main:
            return
        cuts = sorted([(a, b, "") for a, b in L.consumed] + list(L.replace))
        starts = [c[0] for c in cuts]

        def extract(a, b, first_para=False, last_para=False):
            if b <= a:
                return ""
            seg = text[a:b]
            if first_para:
                lead = len(seg) - len(seg.lstrip())
                cut = seg.find("\n\n", lead)
                if cut > 0:
                    b = a + cut
            if last_para:
                cut = seg.rfind("\n\n")
                if cut >= 0 and seg[cut:].strip():
                    a = a + cut
            out, i = [], a
            for s_, e_, rep in cuts[bisect.bisect_left(starts, a):]:
                if s_ >= b:
                    break
                if s_ < i or e_ > b:
                    continue
                out.append(text[i:s_])
                out.append(rep)
                i = e_
            out.append(text[i:b])
            s = "".join(out)
            s = re.sub(r"-\n(?=\w)", "-", s)
            s = re.sub(r"\s+", " ", s).strip()
            s = re.sub(r"\s+([.,;:!?)])", r"\1", s)
            s = re.sub(r"\(\s+", "(", s)
            s = re.sub(r"^[.,;:)\]]+\s*", "", s)
            if len(s) > COMMENT_MAX:
                s = s[:COMMENT_MAX].rsplit(" ", 1)[0] + " ..."
            return s if sum(ch.isalpha() for ch in s) >= 2 else ""

        root = self.nodes[L.root]
        root["comment"] = extract(L.start_offset, main[0][0], last_para=True)
        for (s, e, nid), nxt in zip(main, main[1:] + [None]):
            b = nxt[0] if nxt else (L.end_offset if L.end_offset is not None else e)
            c = extract(e, b, first_para=nxt is None)
            if c:
                node = self.nodes[nid]
                node["comment"] = (node["comment"] + " " + c).strip() if node["comment"] else c

    # -------------------------------------------------------- output
    def line_dicts(self):
        out = []
        for L in self.lines:
            moves = sum(1 for n in L.main_nodes[1:])
            h = L.header
            out.append({
                "id": L.id, "title": L.title, "kind": L.kind, "chapter": L.chapter,
                "page": L.page, "end_page": getattr(L, "end_page", L.page),
                "start_fen": L.start_fen, "root": L.root, "status": getattr(L, "status", "failed"),
                "diagram": L.diagram, "section": L.section,
                "header": ({k: h.get(k) for k in ("text", "white", "black", "event", "site", "year")}
                           if h else None),
                "result": L.result, "moves": moves, "variations": L.variations,
                "_offset": L.first_offset})
        return out


# ---------------------------------------------------------------- top level

def _assemble(doc, fonts, chapters, diagrams, selection, glyphs, letters, diagram_fens, only=None,
              dotless=False):
    dec = _Decoder(glyphs, letters)
    b = _Builder(doc, fonts, chapters, diagrams, selection, dec, diagram_fens, dotless)
    for ci, ch in enumerate(chapters):
        if ch["end"] < ch["start"]:
            continue
        if only is not None and ci not in only:
            continue
        b.chapter(ci, ch)
    return b, dec


def build_book(pdf_path, output_dir=None, books_dir=None, letters=None, passes=3,
               diagram_fens=None, write=True, progress=None):
    """Assemble the whole book and write output/<stem>/book.json.

    letters names a movetext.LETTER_SETS entry (default English; figurines are
    always read). diagram_fens maps diagram ids to FENs read by Stage 3; lines
    that start from those diagrams are then decoded instead of waiting.
    passes is the number of assembly passes (the glyph model of each pass is
    learnt from the runs the previous pass decoded cleanly).
    """
    t0 = time.perf_counter()
    pdf_path = Path(pdf_path)
    out_root = Path(output_dir or OUTPUT_DIR)
    say = progress or (lambda *_: None)
    doc = pymupdf.open(pdf_path)
    fonts = pt.book_fonts(doc)
    structure = pt.book_structure(doc)
    # a picture of stacked boards counts as one diagram per board
    diagrams = sel.expand_boards(load_stage1(pdf_path, out_root, doc.page_count))
    chapters = book_chapters(structure, doc.page_count)
    selection = sel.load_selection(pdf_path, structure, diagrams, books_dir)
    numbering = book_numbering(doc)
    say(f"layout and structure read in {time.perf_counter() - t0:.1f} s; move numbers "
        f"{'without' if numbering['dotless'] else 'with'} dots")
    glyphs = GlyphModel()
    timings = []
    for k in range(max(1, passes)):
        t1 = time.perf_counter()
        builder, dec = _assemble(doc, fonts, chapters, diagrams, selection, glyphs, letters,
                                 diagram_fens, dotless=numbering["dotless"])
        timings.append(round(time.perf_counter() - t1, 1))
        say(f"pass {k + 1}: {len(builder.lines)} lines, {len(builder.nodes)} nodes, "
            f"{dec.calls} decodes in {timings[-1]} s")
        if k + 1 < passes:
            glyphs = GlyphModel()
            for decs in dec.accepted:
                glyphs.learn_run(decs)
    book = _book_dict(pdf_path, doc, chapters, diagrams, selection, builder, glyphs, structure)
    book["numbering"] = numbering
    book["stats"]["seconds"] = round(time.perf_counter() - t0, 1)
    book["stats"]["pass_seconds"] = timings
    if write:
        out = out_root / pdf_path.stem / "book.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(book, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    return book


def book_numbering(doc):
    """How the book numbers its moves, learnt from its text: {"dotless": True when
    it prints numbers without a dot ("1 e4 c5 2 Nf3"), "counts": the clean
    dotless and dotted examples found (movetext.numbering_counts)}."""
    counts = numbering_counts(page.get_text() for page in doc)
    dotless = counts["dotless"] >= DOTLESS_MIN and counts["dotless"] >= DOTLESS_SHARE * counts["dotted"]
    return {"dotless": dotless, "counts": counts}


def _book_title(doc, structure, pdf_path):
    t = (doc.metadata or {}).get("title") or ""
    if t.strip():
        return t.strip()
    for s in structure.get("front_matter") or []:
        if len(s["title"]) >= 6:
            return s["title"]
    return pdf_path.stem


def _book_dict(pdf_path, doc, chapters, diagrams, selection, b, glyphs, structure):
    ids = sel.diagram_ids(diagrams)
    kinds = b.kinds
    chapter_of = {}
    for c in chapters:
        for p in range(c["start"], c["end"] + 1):
            chapter_of[p] = c["index"]
    lines = b.line_dicts()
    lines.sort(key=lambda d: (d["chapter"], d["_offset"]))
    for d in lines:
        d.pop("_offset")
    diagram_lines = defaultdict(list)
    for d in lines:
        if d["diagram"]:
            diagram_lines[d["diagram"]].append(d["id"])
    pages = []
    by_page = defaultdict(list)
    for did, d in zip(ids, diagrams):
        by_page[d["page"]].append((did, d))
    for p in range(1, doc.page_count + 1):
        r = doc[p - 1].rect
        marks = sorted(b.marks.get(p, []), key=lambda m: m.pop("_o"))
        pages.append({
            "page": p, "folio": _folio(p, b.folio_offset),
            "width": round(r.width, 1), "height": round(r.height, 1),
            "chapter": chapter_of.get(p), "selected": b.selection.page_selected(p),
            "diagrams": [{"id": did, "rect": d["rect"], "label": d.get("label"),
                          "kind": kinds.get(did), "selected": b.selection.diagram_selected(did),
                          "fen": (b.diagram_fens.get(did) or None),
                          "status": "read" if b.diagram_fens.get(did) else "unread",
                          "after_node": b.after_node.get(did), "lines": diagram_lines.get(did, [])}
                         for did, d in by_page.get(p, [])],
            "marks": marks})
    # per-chapter counts
    counts = {c["index"]: _empty_counts() for c in chapters}
    for d in lines:
        c = counts[d["chapter"]]
        c["lines"] += 1
        c[d["kind"] + "s"] += 1
        c["line_status"][d["status"]] += 1
        c["variations"] += d["variations"]
    line_chapter = {d["id"]: d["chapter"] for d in lines}
    for n in b.nodes.values():
        if n["status"] == "root" or n["parent"] is None:
            continue
        c = counts[line_chapter[n["line"]]]
        c["moves"][n["status"]] += 1
        if not n["main"]:
            c["variation_moves"] += 1
    for u in b.unattached:
        counts[u["chapter"]]["unattached"] += 1
    for w in b.waiting:
        counts[w["chapter"]]["waiting"] += 1
    out_chapters = []
    for c in chapters:
        cc = dict(c)
        k = counts[c["index"]]
        k["line_status"] = dict(k["line_status"])
        k["moves"] = {s: k["moves"].get(s, 0) for s in STATUSES}
        cc["counts"] = k
        out_chapters.append(cc)
    nodes = {}
    for nid, n in b.nodes.items():
        nn = dict(n)
        if nn["status"] == "root":
            nn["status"] = "ok"
        nodes[nid] = nn
    total = _empty_counts()
    for c in out_chapters:
        k = c["counts"]
        for key in ("lines", "games", "fragments", "variations", "variation_moves",
                    "unattached", "waiting"):
            total[key] += k[key]
        for s, v in k["moves"].items():
            total["moves"][s] += v
        for s, v in k["line_status"].items():
            total["line_status"][s] += v
    total["moves"] = dict(total["moves"])
    total["line_status"] = dict(total["line_status"])
    return {
        "version": VERSION,
        "title": _book_title(doc, structure, pdf_path),
        "pdf": pdf_path.name,
        "page_count": doc.page_count,
        "folio_offset": b.folio_offset,
        "selection": b.selection.to_dict(),
        "selection_file": str(b.selection.path) if b.selection.path else None,
        "selection_from_file": b.selection.from_file,
        "glyphs": [{"junk": g, "piece": p, "count": round(n, 1)} for g, p, n in glyphs.top(30)],
        "pages": pages,
        "chapters": out_chapters,
        "lines": lines,
        "nodes": nodes,
        "unattached": b.unattached,
        "waiting": b.waiting,
        "stats": total,
    }


def _empty_counts():
    return {"lines": 0, "games": 0, "fragments": 0, "line_status": Counter(),
            "moves": Counter(), "variations": 0, "variation_moves": 0, "unattached": 0,
            "waiting": 0}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Assemble the games of a chess book PDF.")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--letters", default=None)
    ap.add_argument("--passes", type=int, default=3)
    args = ap.parse_args(argv)
    book = build_book(args.pdf, letters=args.letters, passes=args.passes, progress=print)
    print(json.dumps(book["stats"], indent=1))


if __name__ == "__main__":
    main()
