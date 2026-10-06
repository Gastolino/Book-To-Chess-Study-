"""Assemble the games, fragments and variations of a chess book.

build_book(pdf_path) walks the selected pages of a book in reading order,
finds every run of numbered moves, decodes the runs into legal moves and
joins them into lines (games and fragments) with variations and comments.
It writes output/<stem>/book.json and returns the same dict:

    {"title", "pdf", "page_count", "folio_offset", "glyphs",
     "pages": [{"page", "folio", "width", "height", "chapter", "selected",
                "diagrams": [{"id", "rect", "label", "kind", "selected", "fen",
                              "status", "reading"?, "after_node", "checked", "lines"}],
                "marks": [{"bbox", "node", "status", "raw", "line", "reason"?, "key",
                           "seq"?, "symbol"?, "known"?, "corrected"?}]}],
     "chapters": [{..book_structure chapter.., "index", "file", "counts"}],
     "lines": [{"id", "title", "kind", "chapter", "page", "end_page", "start_fen",
                "root", "status", "diagram", "section", "header", "result",
                "moves", "variations", "start_note"}],
     "nodes": {id: {"san", "fen", "parent", "children", "number", "black",
                    "page", "bbox", "status", "raw", "comment", "main",
                    "assumed", "uci", "line", "alternatives"?, "reason"?, "key"?,
                    "corrected"?, "gap"?, "fill"?, "missing"?}},
     "unattached": [{"page", "chapter", "text", "reason", "key", "bbox"}],
     "dismissed", "attached": [the same, for sequences the reader dismissed or placed],
     "symbols": {piece symbol: times printed}, "letters", "corrections",
     "waiting": [{"page", "chapter", "text", "reason", "line", "diagram"}],
     "stats": {...}}

A diagram's "fen" is the position lines start from, read from its picture by
Stage 3 (boards.py) unless build_book was given FENs; "status" is "read",
"doubtful" (read, with squares the reader is unsure of), "corrected" (the
reader gave the position, see corrections.py), "partial" (the
picture shows part of a board only) or "unread"; "reading" holds Stage 3's
reading itself: its FEN, confidence, doubtful squares, side to move and
whether the book shows the board from Black's side.

"folio" is the page number printed in the book (PDF page minus the
"folio_offset" learnt from the running heads; None where the book prints
none); line titles and reasons name printed pages. Diagram ids are those of
selection.py: a picture that holds stacked boards gives one diagram per board
("p79-1a", "p79-1b"). A decoded node's number and side come from the
position it is played in, so the labels always match the board.

The reader's corrections
------------------------
corrections.py keeps the reader's corrections of a book. A token's "key"
("page:x,y:raw") names a move token on the page; a mark's "seq" is the key
of the sequence placed in no line that it belongs to, and its "symbol" the
piece symbol the text recognition could not name ("known" when the book
taught the program that symbol well, so that no eye marks it). A node's or mark's
"corrected" says what the reader corrected: "move" (the token reads as the
move given), "symbol" (its piece symbol), or "placed" (the first move of a
sequence the reader placed), "connected" (the first move of a run the reader
joined to a line) or "split" (the first move of a line the reader started
there). "symbols" counts every such piece symbol in the book, for the
reader's Review view.

The corrections are not used while the book is assembled. Each line keeps
the steps that built it (its ops); _Builder.finalize keeps the assembled
lines as the base and replays them with the corrections: corrected moves,
piece symbols and diagram positions are decoded again, sequences go where
the reader tied them, and lines are split or joined where the reader said
(_Builder.derive). _Builder.apply_fix replays only the lines that a changed
set of corrections touches, which lets the browser app apply a correction
at once (live.py) with the result of a fresh build.

How the text is read
--------------------
Main-line moves are set in a move font that pdftext.book_fonts learns from
the book; notes are set in the body font. A second style of the move font
(italic where the main line is upright, another weight or a smaller size:
pdftext "note_moves") sets moves named in the notes, and its words are
notes. Every word is classed by the font
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
A game starts at a game header (one line, "Alekhine - N.N., New York 1924",
or one line a player, "White: V. Kramnik" over "Black: D. Sadvakasov" and
the place and year), or at a main-font run that begins at move 1
with White and reads as play from the initial position: cleanly over two
moves each at least (a shorter run counts the runs that continue its
numbering after a diagram, "1 e4 e6 2 d3" / "2...d5 3 Nd2"), with no printed piece glyph or capture mark dropped to
make it fit, and with no diagram named ("Diagram 430") or position set up in
its sentence. Following main-font runs that continue its numbering continue
it, across columns, pages and diagrams, until a heading, the next game
header, a solution number, a result or the end of the chapter. A heading
only ends a decoded line when no main run continues it afterwards: one that
continues its numbering and reads as legal play from its last position
resumes it (a chess-font diagram set as text lines, a running title). Main-
font moves named inside the notes ("Perhaps 15 ... Bf8"), in a box of advice
that the book sets in the move font ("WARNING: ... for instance, 11 Qh4") or
in a caption are notes, not moves of the line. A misread move number of a
run that continues the line ("1 ... fxe4" for 7...fxe4, "s" for 5) is read
as the number the line expects. Where the
numbering skips moves that the text lacks, the program does not invent them:
the decoded part of the line ends with a "gap" node (status failed, no move,
with a reason) and the rest of the printed score follows unread. The gap
node's "gap" is the key of the first printed move after the gap, under which
the reader may give the moves the text lacks (corrections.py "gaps"; "fill"
holds those the line plays, "missing" the moves still lacking); the moves the
reader gave are nodes with "corrected" "filled" and the same "gap". A run that
starts later than move 1 without an earlier line to continue starts from the
diagram the sentence names, or else the diagram printed before it (but see
"How a line's starting position is chosen" below); the
diagram's position is read by Stage 3, so until then the line has status
"waiting" and keeps its raw move text. A numbered solution ("5. S. Loyd,
1878: 1.Qa1!!", "20. 2...Rh3+!") is matched to the diagram with the same
number among the exercises before it.

A line that stopped resumes where the text takes it up again: a main run
that continues the numbering of a line closed earlier in the chapter (after
a digression, a box or a sidebar: "4… e4" after White's fourth move) and
reads as legal play from its last position continues that line rather than
starting a new one (_Builder.resumable, and choose_start when a diagram
stands between), unless a word such as "Or", "Instead", "If" or "After", or
a bracket, makes it an alternative. The first main run of a chapter that
continues the last line of the chapter before, with no heading, game header
or diagram before it, continues that line too (chapter_join): the book's
structure then took a page inside the text for the start of a chapter.

A line whose main line stopped reading (a gap, or its last two moves
failed: _Builder.lost) does not take the moves printed after a diagram as
more unread moves: a run that continues its numbering after a diagram, or
the part after a diagram of a run that goes on past one (split_lost), starts
from the diagram instead (on_main, "resync").

Moves in long notation ("e2-e4", "Ng1-f3", "d2xd3") name the square the
piece leaves, and only a move from that square reads them. Such a move
without a move number inside a sentence (_LONG_TEXT_RE; ranges such as "the
a1-h8 diagonal" stay prose) is placed by do_long, by the structure of its
sentence (long_cue), not by its words: right after a numbered move of the
notes, joined by "and then", "followed by", "then", "with" or "and", it goes
on with that variation ("8.Rd1 and then Nb1-c3"), or stays text when it is
not legal there; introduced by "Or", "Instead", "If", "after", "then" or a
bracket that holds other moves, or next to a move of the other side ("...
d5xe4 and d3xe4"), it is a variation where the line stands; alone in the
prose ("the potential to gain space with f2-f4"), it is no variation. In
every case but the first, a move the line played refers to that move (a
mark linked to it): the most recent move of the main line, or of a
variation of the same note, from the same square to the same square, unless
a piece of that kind came to the square since (long_reference). Anything
else stays text, and only a variation that is not legal stands in no line.

A reply printed without its move number after a comment ("10.Nd3 Every swap
helps Black. b5 11.Bb3 a5") is no token of any run; it is the line's next
move when the text and the moves agree (bare_move_before, bare_lead,
place_bare, bare_cut, bare_tail): the last word before a numbered run that
continues the line's numbering one move on, alone in its sentence, with no
cue such as "Threat" or "idea" in its clause, legal at the line's end, and
the run reading cleanly after it. A bare move that passes the text's tests
and is legal, but whose run does not read on from it, is placed in no line
with the move it follows ("after"), for the reader to join.

Note runs become variations. A note run whose first move has the number of a
move in the line becomes an alternative to that move; a run that continues a
variation of the same note continues it ("..., followed by 15...Nxb4" can
only continue it; "5.e5 in view of 5...Qa5+" continues 5.e5; "9 0-0 (or 9
Bg5 ...) 9 ... d5 10 Bb3 and then: a) 10 ... b5" continues the variation
that the parenthesis interrupted); a run inside parentheses or brackets
branches off the variation that encloses it. Each placement is decoded from the position it implies and kept
only when the moves read cleanly from there, and no printed capture mark is
read as a quiet move. Runs the text gives as a threat or a plan
("threatening 13.Rh3"), runs whose sentence names another diagram (those
start a line of their own) and runs without a move number that no word such
as "instead" or "better" ties to a move are not placed. Runs that cannot be
placed go to "unattached" with the reason in plain words.

How a line's starting position is chosen
---------------------------------------
The diagram a run starts from is only the first candidate (choose_start).
Books often print a diagram after the moves it belongs to, or two boards
side by side of which only the first shows where the next moves begin. The
other candidates are the diagrams printed before the run since the last
heading and the last moves of another line, and the position the line
closed just before it reaches at the run's first move number. Each is tried
with the run and the runs that continue its numbering; the side to move
always comes from the move numbers. Another candidate replaces the first
only when the moves read further and with fewer failures from it, or when
they reach the position of a diagram printed around them and read no worse.
A doubtful square of the board reading (Stage 3) is changed, to empty or to
another piece, only when exactly one such change makes every move read
cleanly. When the first move is not legal from any candidate but the moves
after the run read cleanly from the diagram, the diagram shows the position
the run reaches: the run stays unread and the next run starts from it. A
diagram that a decoded line already reached with the other side to move
(or at another move of the game) is never a start, since the moves between
are missing. The line's "start_note" says in words when the start was not
the first candidate. A fragment does not end at a diagram printed after its
moves when the next main run continues its numbering and reads as legal
play from its last position (_Builder.hold); a line from the notes is held
only when the diagram shows the position it has reached.

A diagram's "after_node" names the move whose position the text ties to
the diagram: the last main-line move before a diagram printed inside or
right after a decoded line, or the last move of an opening sequence from the
initial position that the text gives just after the diagram ("This position
arises after the opening moves 1.e4 e5 ..."). It is a guess for Stage 3 to
check against its board reading. When a decoded main line reaches the very
position a diagram printed around it shows, after_node is that move and
"checked" is true: the diagram is a checkpoint inside the line.

Move numbers: the book's habit is learnt from its text (book_numbering).
In a book that prints numbers without a dot ("1 e4 c5 2 Nc3"), the
tokenizer reads such numbers too (see movetext.tokenize); a number without
dots names no side, so the narrow-table layout that repeats the number
before Black's reply ("12" / "ttJxd5") reads as Black's move.

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

from . import corrections as fixes
from . import figurines
from . import pdftext as pt
from . import selection as sel
from .movetext import GlyphModel, Token, clean_run, decode, find_sequences, numbering_counts
from .movetext import DOTLESS_MIN, DOTLESS_SHARE
from .movetext import LETTER_SETS, FIGURINES, _strip_suffix, _number_values, _relabel, _shape
from .movetext import CAPTURE_CHARS, _ocr_digit_slip, junk_prefix, letter_symbol, symbol_span
from .movetext import _resolve_letters, SHAPE_KNOWN, _RESULT_RE, _CASTLE_RE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"
VERSION = 1

STATUSES = ("ok", "guessed", "ambiguous", "failed", "inserted", "waiting")
_LINE_RANK = {"ok": 0, "inserted": 1, "guessed": 1, "ambiguous": 2, "failed": 3}
NOTE_BREAK = "¶"           # stands where main-font words were blanked from the notes
WAIT_REASON = "needs the diagram position (Stage 3)"
# what a node's "corrected" counts as in the counts of corrections
CORRECTED_COUNTS = {"move": "moves", "symbol": "symbol_moves", "connected": "connections",
                    "split": "splits", "filled": "gap_moves"}
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
# Words that make a move printed without a move number, after the prose that
# follows a line's last move, an idea rather than the line's next move
# ("Threat: Qxf7", "intending b5", "with Nd5 in mind"); see bare_move_before.
_BARE_CUE_RE = re.compile(
    r"\b(?:threat\w*|ideas?|plans?|planning|planned|intend\w*|intention\w*|in mind|"
    r"prepar(?:es|ing|ed) to|wants? to|wanting to|aim\w*|hop(?:es|ing) for)\b", re.I)
# Words that may stand between such a bare move and the numbered run that
# goes on after it ("b5, and then 11.Bb3", "b5 and if 11.Bb3").
_BARE_JOIN_WORDS = {"and", "then", "now", "if", "when", "after", "followed", "by", "with",
                    "next", "whereupon", "where", "e.g.", "eg", "say"}
# Words that tie a run without a move number to the move it replaces.
_ALT_CUE_RE = re.compile(r"\b(?:instead|better|stronger|weaker|preferable|worse|"
                         r"alternatively|or)\b", re.I)
# A move in long notation: the square the piece leaves, a separator, the square
# it goes to ("e7-e6", "Ng1-f3", "d2xd3", "Bf1–b5").
_LONG_RAW_RE = re.compile(r"[a-h][1-8]\s?[-–—x:×]\s?[a-h][1-8]")
_SQUARES_RE = re.compile(r"[a-h][1-8]")
# The same in running text, with the dots of a Black move and a piece letter or
# glyph before it, and the words after it that make it a range, not a move.
_LONG_TEXT_RE = re.compile(r"(?<![^\s(\[“\"‘'])((?:\.\.\.|…)\s?)?((?![(\[“\"‘'])\S{0,4}?)"
                           r"([a-h][1-8](?:\s?[-–—x:×]\s?[a-h][1-8])+(?:=?[QRBN])?[+#t]?[!?]{0,2})"
                           r"(?![\w\-–—])")
_RANGE_AFTER_RE = re.compile(r"^\W{0,2}(?:diagonals?|files?|ranks?|lines?|squares?|direction|sector|"
                             r"wing|side|axis|pawns?)\b", re.I)
# A square range named after a word such as "diagonal": "the short diagonal (a6-c8)".
_RANGE_BEFORE_RE = re.compile(r"\b(?:diagonals?|files?|ranks?|lines?)\W{0,3}"
                              r"(?:[a-h][1-8]\s?[-–—]\s?[a-h][1-8]\W{0,2}\s(?:and|or)\s)?$", re.I)
# Words before a run that make it an alternative or a supposition rather than
# the resumed line: "Or 4...d5", "Instead 4...d5", "If 4...d5", "After 4...d5".
_ALT_LEAD_RE = re.compile(r"\b(?:or|instead|if|after|alternatively|otherwise)\b[^.;:!?]*$", re.I)
_FOLLOW_RE = re.compile(r"\b(?:followed by|and then|then)\s*$", re.I)
# What joins a move in long notation to the numbered moves of the notes just
# before it, so that it goes on with their variation: "8.Rd1 and then Nb1-c3".
_LONG_FOLLOW_RE = re.compile(r"^[\s,]*(?:and\s+then|followed\s+by|then|with|and)[\s,:]*$", re.I)
# What may stand between two moves that form a line: "...d5xe4 and d3xe4".
_LONG_JOIN_RE = re.compile(r"^[\s,;]*(?:(?:and\s+then|followed\s+by|then|and)[\s,]*)?$", re.I)
# A word that introduces a move in long notation as a move of a line of
# analysis ("Instead d2-d4", "If Black ever plays ...g7-g5", "after b2-b4",
# and at the start of a clause "Or ...e7-e5", "and then f2-f4"), or a bracket
# ("(e2-e4 ..."). An "or" inside a list ("...Bd7-c6 or ...e7-e6") is none.
_LONG_ALT_RE = re.compile(
    r"(?:(?:^|(?<=[\s(\[]))(?:instead(?:\s+of)?|if|after)\b"
    r"|(?:^|[,;:(]\s*|\b(?:and|but)\s+)(?:or|then)\b|\()"
    r"(?:[\s,]*(?:white|black|he|she|we|one|you|now|first|ever|already|at\s+once|"
    r"immediately|plays?|played|playing|continues?|continued|tries|tried|answers?|"
    r"answered|repl(?:y|ies|ied)|the\s+move|\.\.\.|…))*[\s,]*$", re.I)
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
    return replace(run, tokens=toks, moves=moves, ply=_ply(moves[0]))


def _tokens_text(tokens):
    """The text of a run's tokens: "6.Nxf7 Kxf7 7.Qf3+"."""
    out = ""
    for t in tokens:
        glue = out.endswith((".", "…")) and t.kind == "move"
        out += ("" if glue or not out else " ") + t.raw.strip()
    return out


def _open_bracket(text, lo, off):
    """Offset of the innermost bracket left open between lo and off, or None."""
    level = 0
    for k in range(off - 1, lo - 1, -1):
        ch = text[k]
        if ch in ")]":
            level += 1
        elif ch in "([":
            if level == 0:
                return k
            level -= 1
    return None


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


def _misplaced(decs):
    """True when the first decoded move goes to another square than the one
    printed: it was read only by changing the square ("Qf1" for ".il.b2")."""
    if not decs or decs[0].status == "ok" or not decs[0].san:
        return False
    sq = _SQUARE_RE.search(_norm_raw(decs[0].raw) or "")
    dest = re.findall(r"[a-h][1-8]", decs[0].san)
    norm = str.maketrans({"£": "f", "l": "1", "I": "1", "B": "8", "S": "5"})
    return bool(sq and dest) and sq.group(0).translate(norm) != dest[-1]


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


def colour_header_merge(header, text):
    """A game header set one player a line ("White: V. Kramnik", "Black:
    D. Sadvakasov", then "Astana 2001"): header (None for the first line)
    with the line's player or place and year added, in the fields of
    parse_game_header."""
    h = dict(header or {"white": "", "black": "", "event": "", "site": "", "year": None,
                        "text": "", "by_colour": True})
    c = pt.colour_header(text)
    if c is not None:
        h[c[0]] = c[1]
    else:
        place = pt.join_year(text.strip())
        m = re.search(r"((?:1[5-9]|20)\d)([\dlI\]])\W{0,2}$", place)
        if m:
            h["year"] = m.group(1) + m.group(2).translate(str.maketrans("lI]", "111"))
            place = place[:m.start()].strip(" ,;.")
        h["site"] = place
        h["event"] = " ".join(x for x in (place, h["year"]) if x)
    h["text"] = " - ".join(x for x in (h["white"], h["black"]) if x) + (
        f", {h['event']}" if h["event"] else "")
    return h


def _stage1_current(folder, page_count):
    """Whether Stage 1's results in folder are for a book of page_count pages
    (any count when None) and as recent as this code (pages.json records how
    many text diagrams each page holds)."""
    try:
        pages = json.loads((Path(folder) / "pages.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return ((page_count is None or len(pages) == page_count)
            and all("text_diagrams" in p for p in pages))


def load_stage1(pdf_path, output_dir=None, page_count=None):
    """Stage 1's diagrams.json for the book. When output_dir lacks it, the
    project's own Stage 1 results for the same book are copied, or Stage 1 is
    run (it writes into ./output/<stem>/stage1 of its working directory)."""
    return _drain(load_stage1_steps(pdf_path, output_dir, page_count))


def _drain(steps):
    """Run a generator of steps to its end and return its value."""
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value


def load_stage1_steps(pdf_path, output_dir=None, page_count=None, first=None, found=None):
    """load_stage1 in steps of a few pages (yields (pages done, page count)).
    first and found go to stage1_inspect.analyse_steps when Stage 1 runs:
    first chooses the pages to inspect first, and found (a dict) receives
    the findings of every page inspected so far."""
    import shutil
    import tempfile
    pdf_path = Path(pdf_path).resolve()
    out = Path(output_dir or OUTPUT_DIR)
    dest = out / pdf_path.stem / "stage1"
    path = dest / "diagrams.json"
    if path.exists() and (dest / "pages.json").exists() and not _stage1_current(dest, None):
        path.unlink()                   # written before Stage 1 read text diagrams
    if not path.exists():
        shared = OUTPUT_DIR / pdf_path.stem / "stage1"
        same = False
        if shared.resolve() != dest.resolve() and (shared / "diagrams.json").exists():
            same = _stage1_current(shared, page_count)
        if same:
            src = shared
        else:
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))
            import stage1_inspect
            src = Path(tempfile.mkdtemp(prefix="stage1_"))
            steps = stage1_inspect.analyse_steps(pdf_path, src, first=first)
            while True:
                try:
                    done, n, pages = next(steps)
                except StopIteration:
                    break
                if found is not None:
                    found.update(pages)
                yield done, n
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
    ci: int = -1                # the chapter whose text holds the run
    text: str = ""              # the run's text, for messages
    bracket: Optional[int] = None   # offset of the bracket the run stands in (depth > 0)


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
    hold: Optional[int] = None  # a diagram that may end the line (see _Builder.hold)
    hold_inside: bool = False   # that diagram stands among the moves of the line's last run
    start_note: str = ""        # how the starting position was chosen, in plain words
    spec: dict = field(default_factory=dict)          # where the line starts (see _Builder.replay_line)
    ops: list = field(default_factory=list)           # how the line was built, for replaying it
    base_result: Optional[str] = None
    nseq: int = 0               # node ids handed out by replay_line


class _Decoder:
    """decode() with the book's glyph model, letter set and a memo. fixed maps
    piece symbols the reader identified (corrections.py "glyphs") to their
    piece: they read as certainly as the notation's own letters."""

    def __init__(self, glyphs, letters, fixed=None):
        self.glyphs = glyphs
        self.letters = letters
        self.fixed = dict(fixed or {})
        self.decode_letters = letters
        if self.fixed:
            self.decode_letters = {**LETTER_SETS.get(letters or "English", LETTER_SETS["English"]),
                                   **self.fixed}
        self.memo = {}
        self.accepted = []
        self.calls = 0
        self.seconds = 0.0

    def run(self, fen, tokens):
        if self.fixed:
            tokens = [self.named(t) for t in tokens]
        key = (fen, tuple((t.kind, t.raw, t.number, t.black, t.forced, t.shape) for t in tokens))
        hit = self.memo.get(key)
        if hit is None:
            t0 = time.perf_counter()
            # Never supply a move the text lacks: a gap in the numbering is
            # shown as a gap (see _Builder.gap), not filled with a guess.
            hit = decode(chess.Board(fen), tokens, glyphs=self.glyphs, letters=self.decode_letters,
                         insert=False)
            self.seconds += time.perf_counter() - t0
            self.calls += 1
            self.memo[key] = hit
        return hit


    def named(self, tok):
        """A move whose piece symbol the reader named carries that piece as a
        certain shape (Token.shape): the decoder reads it so even where the
        book's glyph model knows a longer junk ("1:'!:" for the "1:'!" that was
        named), and only illegal play overrules it."""
        if tok.kind != "move":
            return tok
        piece = self.fixed.get(junk_prefix(tok.raw, self.letters))
        if piece and piece in "KQRBN":
            return replace(tok, shape=(piece, 1.0))
        return tok


def _vanished(d):
    """True when a piece move was read from a token that prints no piece glyph
    at all ("g4" read as Qg4): the reading of last resort."""
    return bool(d.san and d.san[0] in "KQRBN" and not d.glyph)


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
                 dotless=False, readings=None, fix=None, shapes=None):
        self.doc, self.fonts, self.chapters = doc, fonts, chapters
        # figurine shapes (figshapes.py): where each junk piece symbol stands,
        # and the piece read from its picture
        self.spots = {}                 # token key -> (page, box of the symbol, symbol)
        self.move_tokens = 0
        self.shapes = shapes or {}      # token key -> (piece letter, confidence)
        self.letter_table = None
        self.dotless = dotless          # the book prints move numbers without a dot
        self.diagrams = diagrams
        self.selection = selection
        self.dec = decoder
        self.diagram_fens = diagram_fens or {}
        self.readings = readings or {}      # Stage 3's readings (doubtful squares, captions)
        self.checked = {}                   # diagram id -> node whose position it shows
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
        # The reader's corrections (corrections.py) are not used while the
        # book is assembled: finalize() applies them afterwards by replaying
        # the lines they touch, so that one correction can be applied to the
        # assembled book alone (live, in the browser app) with the same result.
        self.fix = fixes.empty()
        self.fix_moves = fixes.TokenIndex({})
        self.fix_gaps = fixes.TokenIndex({})
        self.fix_glyphs = {}
        self.fix_diagrams = {}
        self.node_by_key = {}           # token key -> node id
        self.dismissed = []             # sequences the reader dismissed as no variation
        self.attached = []              # sequences placed where the reader said
        self.places = {}                # (chapter, start, end) -> (page, bbox) of a token
        self.replaying = False
        self.unplaced_runs = []         # (entry, run): sequences placed in no line
        self.by_line = defaultdict(list)        # line id -> its node ids
        self.line_pages = defaultdict(set)      # line id -> pages holding its marks
        self.base = None                # the lines as assembled, before corrections

    def page_label(self, page):
        """The page number printed in the book (the PDF page when unknown)."""
        if page is None:
            return None
        return _folio(page, self.folio_offset) or page

    # -------------------------------------------------------- nodes and marks
    def new_node(self, line, **kw):
        if self.replaying:
            line.nseq += 1
            nid = f"{line.id}.{line.nseq}"
        else:
            nid = f"n{len(self.nodes) + 1}"
        node = {"san": None, "fen": None, "parent": None, "children": [], "number": None,
                "black": None, "page": None, "bbox": None, "status": "ok", "raw": "",
                "comment": "", "main": False, "assumed": None, "uci": None, "line": line.id}
        node.update(kw)
        self.nodes[nid] = node
        self.by_line[line.id].append(nid)
        if node["parent"] is not None:
            self.nodes[node["parent"]]["children"].append(nid)
        return nid

    def place_of(self, tok, ci=None):
        """(page, bbox) of a token of chapter ci (the current one by default)."""
        k = (self.ci if ci is None else ci, tok.start, tok.end)
        hit = self.places.get(k)
        if hit is None:
            hit = self.places[k] = self.st.locate(tok.start, tok.end)
        return hit

    def key_of(self, tok, ci=None):
        page, box = self.place_of(tok, ci)
        return fixes.token_key(page, box, tok.raw) if box is not None else None

    def mark(self, stream, tok, node, status, line_id=None, reason=None):
        page, box = self.place_of(tok)
        if page is None:
            return None, None
        m = {"bbox": box, "node": node, "status": status, "raw": tok.raw, "line": line_id,
             "_o": tok.start, "key": fixes.token_key(page, box, tok.raw)}
        if tok.shape and tok.shape[1] >= SHAPE_KNOWN and node is not None and \
                (self.nodes[node].get("san") or "")[:1] == tok.shape[0]:
            # the picture of its figurine names the piece the move was read as
            m["known"] = True
        if reason:
            m["reason"] = reason
        if line_id:
            self.line_pages[line_id].add(page)
        if node is not None:
            self.node_by_key.setdefault(m["key"], node)
            n = self.nodes[node]
            if n.get("corrected"):
                m["corrected"] = n["corrected"]
        self.marks[page].append(m)
        return page, box

    def note_spot(self, tok):
        """Note where the junk piece symbol of a move token stands on its page
        (figshapes.py), and give the token the piece that the picture of its
        figurine was read as."""
        self.move_tokens += 1
        if self.letter_table is None:
            self.letter_table = _resolve_letters(self.dec.decode_letters)
        sym = junk_prefix(tok.raw, self.dec.decode_letters)
        if not sym or sym in FIGURINES or letter_symbol(sym, self.letter_table):
            return
        key = self.key_of(tok)
        if key is None:
            return
        span = symbol_span(tok.raw, sym)
        if span is not None:
            page, box = self.st.locate(tok.start + span[0], tok.start + span[1])
            # the square after the symbol must have room of its own: a text
            # layer that gives one character the whole word's box says
            # nothing of where the figurine stands
            _, rest = self.st.locate(tok.start + span[1], tok.end)
            if box is not None and rest is not None and box[2] > box[0] and \
                    rest[2] - rest[0] > 0.3 * (box[3] - box[1]):
                self.spots[key] = (page, box, sym)
        shape = self.shapes.get(key)
        if shape is not None:
            tok.shape = shape

    def forced(self, run):
        """The run with the moves the reader corrected carrying the move they
        gave (corrections.py "moves")."""
        if not self.fix_moves:
            return run
        pages = self.fix_moves.pages()
        toks, changed = [], False
        for t in run.tokens:
            if t.kind == "move":
                page, box = self.place_of(t, run.ci)
                if page in pages and box is not None:
                    _, v = self.fix_moves.find(page, box, t.raw)
                    if v and v["san"] != t.forced:
                        t, changed = replace(t, forced=v["san"]), True
            toks.append(t)
        if not changed:
            return run
        return replace(run, tokens=toks, moves=[t for t in toks if t.kind == "move"])

    # -------------------------------------------------------- stream building
    def word_classes(self, ln):
        words = ln["text"].split(" ")
        if not self.moves_font:
            c = "m" if ln["role"] == "moves" else "n"
            return [c] * len(words)
        roles = []
        for s in ln["spans"]:
            # moves set in a second style of the move font (italic where the
            # main line is upright) are named in the notes (pdftext "note_moves")
            r = "m" if s["role"] == "moves" else "n" if s["role"] in ("text", "note_moves") else None
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
                                        _ply(moves[0]), res,
                                        bracket=_open_bracket(text, a, part[0].start)
                                        if s.depth else None))
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
        _drain(self.chapter_steps(ci, ch))

    def chapter_steps(self, ci, ch, slice_seconds=None):
        """chapter() in slices of about slice_seconds each (none when None):
        a generator that yields between them, for a caller with other work
        to do (the browser app). The slices do not change the result."""
        mark = time.perf_counter()
        st = self.build_stream(ch)
        self.st, self.ci = st, ci
        runs = self.runs(st)
        runs = sorted(runs + self.long_runs(st, runs), key=lambda r: (r.start, r.kind))
        for r in runs:
            r.ci = ci
            r.text = re.sub(r"[ \n\r]+", " ", st.orig_text[r.start:r.end]).strip()
            for t in r.tokens:
                self.place_of(t)
                if t.kind == "move":
                    self.note_spot(t)
        self.all_runs = runs
        self.run_starts = [r.start for r in runs]
        self.token_spans = sorted((t.start, t.end) for r in runs for t in r.tokens)
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
        self.deferred = None            # (offset, run): the rest of a run cut at a diagram
        self.held_header = None         # the pending header, while a note starts a line
        # the last line of the chapter before, when it ends on its last pages
        prev = next((M for M in reversed(self.lines) if M.chapter < ci), None)
        last = self.nodes[prev.main_nodes[-1]] if prev is not None and prev.main_nodes else None
        self.prev_chapter_line = prev if (last and last.get("page")
                                          and last["page"] >= ch["start"] - 1) else None
        prev_kind = None
        self.now = 0
        for off, _, _, kind, x in items:
            if slice_seconds is not None and time.perf_counter() - mark > slice_seconds:
                yield
                mark = time.perf_counter()
            self.now = off
            a = self.active
            if a is not None and a.close_at is not None and off >= a.busy_until:
                self.close(max(a.close_at, a.busy_until))
            if kind in ("heading", "game_header", "break", "exercise") and a is not None \
                    and a.hold is not None:
                self.close(off)                 # the diagram did end the line
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
                    self.pending_header is not None and self.pending_header.get("by_colour") \
                    and not (pt.colour_header(x["text"]) and self.pending_header[
                        pt.colour_header(x["text"])[0]]):
                # "White: V. Kramnik" / "Black: D. Sadvakasov" / "Astana 2001"
                self.pending_header = colour_header_merge(self.pending_header, x["text"])
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
                self.pending_header = (
                    colour_header_merge(None, x["text"]) if pt.colour_header(x["text"]) else
                    parse_game_header(x["text"])) or {
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
                    self.hold(off, x)
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
            if kind == "diagram" and self.deferred is not None and self.deferred[0] <= off:
                # the moves after a diagram that a lost line's run held
                rest, self.deferred = self.deferred[1], None
                self.now = rest.start
                self.on_main(rest)
        self.close(st.pos)
        self.flush_pre_notes()

    def long_runs(self, st, runs):
        """Moves in long notation that stand in the text outside any run
        ("after Black has committed himself with ...e7-e6"): each becomes a
        run of kind "long" (see do_long). Ranges in prose ("the a1-h8
        diagonal") stay prose."""
        taken = sorted((t.start, t.end) for r in runs for t in r.tokens)
        starts = [a for a, _ in taken]
        out = []
        text = st.orig_text
        for m in _LONG_TEXT_RE.finditer(text):
            a, b = m.start(2), m.end(3)
            k = bisect.bisect_right(starts, b) - 1
            if k >= 0 and taken[k][1] > a:
                continue                        # part of a run already
            if _RANGE_AFTER_RE.match(text[b:b + 20]) or _RANGE_BEFORE_RE.search(text[max(0, a - 32):a]):
                continue
            sq = _SQUARES_RE.findall(m.group(3))
            if len(set(sq)) < len(sq) or not (m.group(2) or m.group(1) or self.square_move(sq[0], sq[1])):
                continue
            raw = text[a:b]
            if "\n" in raw:
                continue
            black = bool(m.group(1))
            toks = []
            if m.group(1):
                toks.append(Token("number", m.group(1).strip(), m.start(1), m.start(1) + len(m.group(1).strip()),
                                  None, True))
            mv = Token("move", raw, a, b, None, black, side_known=black)
            toks.append(mv)
            out.append(_Run("long", toks, [mv], toks[0].start, b, 0, None, None))
        return out

    @staticmethod
    def square_move(a, b):
        """True when a piece can go from square a to square b in one move on an
        empty board (a line, a diagonal or a knight's jump)."""
        fa, ra, fb, rb = ord(a[0]), int(a[1]), ord(b[0]), int(b[1])
        df, dr = abs(fa - fb), abs(ra - rb)
        return df == 0 or dr == 0 or df == dr or {df, dr} == {1, 2}

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
            if doff > off:
                continue
            if doff < max(self.cut, self.last_token_end):
                return None
            return did
        return None

    def last_diagram(self, off):
        """The last diagram before off in reading order in this chapter, if any."""
        for doff, did in reversed(self.diagram_events):
            if doff <= off:
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
        L.spec = {"fen": fen, "diagram": diagram, "ply": start_ply}
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
        the sentence names, or else the diagram before the run. A line from
        the notes does not take the game header that waits for the game's
        moves."""
        if born == "note" and self.pending_header is not None:
            held, self.pending_header = self.pending_header, None
            self.held_header = held
            try:
                return self.from_diagram(run, born, kind, title, did)
            finally:
                self.pending_header, self.held_header = held, None
        if did is None:
            ref = self.referenced_diagram(run)
            if ref and ref[1]:
                did = ref[1]
        did = did or self.usable_diagram(run.start)
        pick = self.choose_start(run, did)
        if pick is not None and pick.get("skip"):
            # the position before these moves is unknown; the moves after them
            # start from the diagram (on_main reaches it with the next run)
            self.unplaced(run, pick.get("reason") or (
                f"{self.diagram_name(did)} shows the position these moves reach, and the "
                "position they start from is unknown"))
            return None
        if pick is not None and pick.get("line") is not None:
            # the run goes on from a position of the line before it
            prev = pick["line"]
            if (born == "main" and prev.end_offset is not None and prev is not self.active
                    and prev.main_nodes
                    and self.nodes[prev.main_nodes[-1]]["fen"] == pick["fen"]
                    and self.pending_header is None and run.depth == 0
                    and not _ALT_LEAD_RE.search(self.lead_text(run.start, 60))):
                # it goes on from where that line stopped: the same line resumes
                # ("10...Qf6" after a digression, a diagram or a box between)
                return self.reopen(prev, run)
            header = self.pending_header
            title = title or (header["text"] if header else
                              f"{prev.title} (from move {_ply_label(run.ply)})")
            L = self.start_line(run, kind or ("game" if header else "fragment"), title, False,
                                None, born, header, pick["fen"])
            L.start_note = pick["note"]
            self.pending_header = None
            return L
        if pick is not None:
            did = pick["did"]
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
        fen = pick["fen"] if pick is not None else self.diagram_fen(did, run)
        unread = self.unread_numbers(run) if (fen is not None and born == "main"
                                              and (pick is None or pick.get("did") == did)) else None
        if unread is not None:
            # the moves printed between the diagram and the run cannot be read
            # ("14 0 exO 15 gxO h5 16 Bb2"): the diagram shows the position
            # before the first of them, not the position the run starts from
            b = chess.Board(fen)
            b.turn, b.ep_square, b.fullmove_number = chess.WHITE, None, unread
            fen = b.fen()
        L = self.start_line(run, kind, title, fen is None, did, born, header, fen)
        if pick is not None:
            L.start_note = pick["note"]
        if unread is not None:
            self.gap(L, run, run.ply, follow=False)
        self.pending_header = None
        if fen is None:
            self.waiting.append({"page": L.page, "chapter": self.ci, "text": self.run_text(run),
                                 "reason": WAIT_REASON, "line": L.id, "diagram": did})
        return L

    def unread_numbers(self, run):
        """The number of White's move that stands, with unreadable moves after
        it, right before a run in its sentence or at the start of its
        paragraph ("drawn: 14 0 exO 15 gxO h5" before "16 Bb2"), or None.
        Such moves are part of the line: the run does not start where its own
        number says."""
        if run.ply is None or run.ply < 2:
            return None
        want = run.ply // 2 + 1
        para = self.para_start_of(run.start)
        if not self.st.orig_text[para:run.start].strip() and para >= 2:
            para = self.para_start_of(para - 2)     # the run opens its paragraph
        lead = self.st.orig_text[max(para, run.start - 60):run.start]
        # the numbers stand after a word of the sentence, or open the paragraph
        lo = run.start - len(lead)
        words = lead.split()
        found, sentence = [], para >= run.start - 60

        def prose(w):
            return len(w) > 6 or bool(re.fullmatch(r"(?:[A-Z]?[a-z]{2,}|[a-z]{3,})[,.:;!?]?", w)
                                      and re.search(r"[aeiouy]", w.lower()))
        for i in range(len(words) - 1, -1, -1):
            w = words[i]
            if re.fullmatch(r"\d{1,3}\.?", w):
                # a move number with a move after it that cannot be read (a
                # move that reads would stand in a run)
                n = int(w.rstrip("."))
                rest = [x for x in words[i + 1:] if not _DOTS_RE.match(x)]
                nxt = rest[0] if rest else None
                # (not a year that OCR split, "1 957", nor the next number)
                if nxt is not None and not re.match(r"\d{2}", nxt) \
                        and not (nxt.rstrip(".").isdigit() and int(nxt.rstrip(".")) == n + 1) \
                        and _shape(nxt) != "strong":
                    found.append(n)
            elif prose(w):
                sentence = True             # a word of the sentence
                break
        found = [n for n in found if want - 3 <= n < want]
        if not found or not sentence:
            return None
        # moves that read stand in a run (the run itself may be the rest of
        # a longer one, split_lost): these did not
        if any(r is not run and r.start < run.start and r.end > lo for r in self.all_runs):
            return None
        return min(found)

    # -------------------------------------------------------- choosing the start
    def lookahead(self, run, limit=16):
        """The tokens of run and of the runs of its kind that follow it with
        the next move numbers (at most limit moves): the moves a starting
        position is tested against."""
        toks, n = list(run.tokens), len(run.moves)
        last = _ply(run.moves[-1])
        k = bisect.bisect_right(self.run_starts, run.start)
        taken = 0
        while last is not None and n < limit and k < len(self.all_runs) and taken < 4:
            r = self.all_runs[k]
            k += 1
            if r.kind != run.kind or r.start <= run.start:
                continue
            if r.ply is not None and r.ply <= last:
                continue                     # a variation in the same font
            if r.ply != last + 1:
                break
            toks.extend(r.tokens)
            n += len(r.moves)
            last = _ply(r.moves[-1])
            taken += 1
        return _first_moves(toks, limit)

    def start_score(self, fen, toks):
        """(clean moves before the first failure, failed moves, mean cost) of
        the tokens read from fen, and the decoding."""
        decs = self.dec.run(fen, toks)
        if not decs:
            return (0, 0, 9.0), decs
        prefix = next((i for i, d in enumerate(decs) if d.status == "failed"), len(decs))
        failed = sum(d.status == "failed" for d in decs)
        ok = [d.cost for d in decs if d.status != "failed"]
        return (prefix, failed, sum(ok) / len(ok) if ok else 9.0), decs

    def firm_header(self):
        """True when a game header is pending that surely starts another game:
        one line a player ("White: ..."), or a line that does not end like a
        sentence (a sentence of the notes that names a game ends with a stop)."""
        h = self.pending_header or getattr(self, "held_header", None)
        return h is not None and (bool(h.get("by_colour"))
                                  or not h.get("text", "").rstrip().endswith((".", ")")))

    def diagram_window(self, run, limit=4):
        """The diagrams printed before the run since the last heading and the
        last moves of another line, nearest first (at most limit): those the
        run may start from."""
        out = []
        head = (self.pending_header or self.held_header)["offset"] if self.firm_header() else 0
        for doff, did in reversed(self.diagram_events):
            if doff > run.start:
                continue
            if doff < max(self.cut, self.last_token_end, head) or len(out) >= limit:
                break
            out.append(did)
        return out

    def diagrams_near(self, run, toks):
        """{piece placement: diagram id} of the diagrams around the run: those
        printed before it since the last heading and those printed among or
        just after its moves. A position the moves reach that one of them
        shows confirms the starting position."""
        end = max(t.end for t in toks) if toks else run.end
        out = {}
        for doff, did in self.diagram_events:
            if (doff >= self.cut and doff <= end + 400) and self.diagram_fens.get(did):
                out.setdefault(self.diagram_fens[did].split(" ")[0], did)
        return out

    def checked_ply(self, did):
        """The ply about to be played in the position a decoded line reached
        at this diagram (a checkpoint), or None."""
        nid = self.checked.get(did)
        fen = self.nodes[nid]["fen"] if nid else None
        return _board_ply(fen) if fen else None

    def ply_conflict(self, did, ply):
        """True when a line already reached this diagram with the other side to
        move, or at another move of the game: a run at ply cannot start
        there. Analysis that the book numbers afresh from move 1 may start
        from it when the side to move agrees."""
        q = self.checked_ply(did)
        if q is None:
            return False
        return q % 2 != ply % 2 or (q != ply and ply > 1)

    def checkpoint_hits(self, decs, placements, own):
        return sum(1 for d in decs if d.fen and placements.get(d.fen.split(" ")[0]) not in
                   (None, own))

    def choose_start(self, run, default):
        """Choose the position a run that needs one starts from.

        The candidates are the diagram the text gives (default), the other
        diagrams printed before the run since the last heading, and the
        position the line closed before it reaches at the run's first move
        number. Each is tried with the run and the runs that continue its
        numbering. Another candidate replaces the default only when the moves
        read further and with fewer failures from it, or when they reach the
        position of a diagram printed around them (the book shows the
        position reached) and do not read worse. A doubtful square of the
        board reading that alone stops the moves from reading is corrected.
        Returns None to keep the default, else {"did" or "line", "fen", "note"}."""
        if run.ply is None or self.exercise is not None:
            return None
        toks = self.lookahead(run)
        n = sum(1 for t in toks if t.kind == "move")
        if not n:
            return None
        placements = self.diagrams_near(run, toks)
        cands = []                  # (order, did, line, fen)
        if default is not None and self.diagram_selected(default):
            fen = self.diagram_fen(default, run)
            if fen and self.ply_conflict(default, run.ply):
                # a line already reached this diagram at another move: the
                # moves between are missing from the text, and no move is
                # invented to bridge them
                n = self.nodes[self.checked[default]]
                return {"skip": True, "reason": (
                    f"{self.diagram_name(default)} shows the position after "
                    f"{n['number']}{'...' if n['black'] else '.'}{n['san']}, and the text lacks "
                    f"the moves between it and {_ply_words(run.ply)}")}
            if fen:
                cands.append((0, default, None, fen))
        for k, did in enumerate(self.diagram_window(run) if default is not None else []):
            if did == default or not self.diagram_selected(did) \
                    or self.ply_conflict(did, run.ply):
                continue
            fen = self.diagram_fen(did, run)
            if fen:
                cands.append((k + 1, did, None, fen))
        # a game header starts another game: no position of a line before it
        # is a start for its moves
        recent = [M for M in reversed(self.lines) if M.chapter == self.ci
                  and M.end_offset is not None and M is not self.active][:2] \
            if not self.firm_header() else []
        for k, prev in enumerate(recent):
            if prev.waiting or prev.broken or len(prev.main_nodes) <= 1:
                continue
            # the run goes on where a line before it stopped (a diagram, a
            # heading or a box of text between them closed that line), or
            # replaces one of the last two moves of the line just before it
            # (a move taken from the notes)
            for nid in reversed(prev.main_nodes[1:][-3:] if k == 0 else prev.main_nodes[-1:]):
                node = self.nodes[nid]
                if node["fen"] and node["status"] != "failed" \
                        and _board_ply(node["fen"]) == run.ply:
                    cands.append((9 + k, None, prev, node["fen"]))
                    break
        if not cands:
            return None
        scored = []
        for order, did, line, fen in cands:
            sc, decs = self.start_score(fen, toks)
            hits = self.checkpoint_hits(decs, placements, did)
            scored.append({"order": order, "did": did, "line": line, "fen": fen, "score": sc,
                           "hits": hits, "decs": decs})
        base = scored[0] if scored[0]["order"] == 0 else None
        if base is None and default is not None and self.diagram_fen(default, run) is not None:
            return None             # the default is left out by the selection
        best = base

        def better(c, b):
            (cp, cf, cc) = c["score"]
            clean = cf == 0 and cc <= 1.0 and all(d.cost <= 1.5 and not _vanished(d)
                                                  for d in c["decs"])
            if b is None:
                # no usable default: the line before goes on when its next
                # moves read cleanly (as after a heading, see resume), and a
                # diagram serves only when the moves read cleanly throughout
                if c["line"] is not None:
                    head = c["decs"][:4]
                    return len(head) >= 2 and (all(d.status != "failed" and d.cost <= 2.5 and not _vanished(d)
                                for d in head)
                            and sum(d.cost for d in head) <= 1.2 * len(head))
                return clean and n >= 2
            (bp, bf, bc) = b["score"]
            if c["hits"] and not b["hits"] and cp >= bp and cp >= 1 and cf <= bf:
                return True             # the moves reach a diagram printed around them
            if clean and bf > 0 and cp > bp:
                return True             # reads cleanly where the default does not
            return cp >= bp + 3 and cf < bf and cc <= bc + 0.5

        for c in scored:
            if c is base or not better(c, base):
                continue
            if best is base or (bool(c["hits"]), c["score"][0], -c["score"][1], -c["score"][2],
                                -c["order"]) > (bool(best["hits"]), best["score"][0],
                                                -best["score"][1], -best["score"][2],
                                                -best["order"]):
                best = c
        note = ""
        if best is not base and best is not None:
            if best["line"] is not None:
                note = (f"The moves go on from the position that the line \"{best['line'].title}\" "
                        f"reaches, so the line starts there.")
            elif base is not None:
                note = (f"The moves read as legal play from {self.diagram_name(best['did'])}, "
                        f"not from {self.diagram_name(default)}, so the line starts there.")
            else:
                note = (f"The moves read as legal play from {self.diagram_name(best['did'])}, "
                        "so the line starts there.")
        if best is not None and best["did"] is not None and best["score"][0] < min(n, 3):
            fixed = self.repair(best, toks, n, placements)
            if fixed is not None:
                best, extra = fixed
                note = (note + " " + extra).strip()
        if best is not None and base is not None and (
                best["score"][0] == 0 or (best is base and _misplaced(best["decs"][:1]))) \
                and self.shows_reached(run, toks, default):
            return {"skip": True}
        if best is None or (best is base and not note):
            return None
        return {"did": best["did"], "line": best["line"], "fen": best["fen"], "note": note}

    def shows_reached(self, run, toks, did):
        """True when the diagram shows the position the run reaches rather
        than the one it starts from: the run's first move is not legal there,
        but the moves after the run (three at least) read cleanly from it."""
        last = _ply(run.moves[-1])
        rest = [t for t in toks if t.start >= run.end]
        if last is None or sum(1 for t in rest if t.kind == "move") < 3:
            return False
        b = chess.Board(self.diagram_fens[did])
        b.turn = chess.BLACK if (last + 1) % 2 else chess.WHITE
        b.ep_square = None
        b.fullmove_number = (last + 1) // 2 + 1
        sc, _ = self.start_score(b.fen(), rest)
        return sc[1] == 0 and sc[2] <= 1.5

    def repair(self, cand, toks, n, placements):
        """The candidate with one doubtful square of its board reading changed,
        when that alone lets the moves read legally: (candidate, note) or
        None. Only the squares Stage 3 marked as doubtful are changed, each
        to empty or to another piece, and only a change that reads clearly
        better than every other is kept."""
        reading = self.readings.get(cand["did"]) or {}
        squares = [sq for sq in (reading.get("doubtful") or [])][:6]
        if not squares:
            return None
        base = chess.Board(cand["fen"])
        results = []
        for name in squares:
            sq = chess.parse_square(name)
            old = base.piece_at(sq)
            options = [None] if old is not None else []
            for color in (chess.WHITE, chess.BLACK):
                for pt in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
                    p = chess.Piece(pt, color)
                    if p != old:
                        options.append(p)
            for p in options:
                b = base.copy(stack=False)
                b.set_piece_at(sq, p) if p is not None else b.remove_piece_at(sq)
                if p is not None and p.piece_type == chess.PAWN and chess.square_rank(sq) in (0, 7):
                    continue
                if (len(b.pieces(chess.KING, chess.WHITE)) != 1
                        or len(b.pieces(chess.KING, chess.BLACK)) != 1):
                    continue
                b.castling_rights = b.clean_castling_rights()
                fen = b.fen()
                sc, decs = self.start_score(fen, toks)
                results.append((sc, name, old, p, fen, decs))
        if not results:
            return None
        # only a change under which every move reads cleanly and with one
        # reading, over four moves at least, and no other change does so
        good = [r for r in results if n >= 4 and r[0][1] == 0 and r[0][2] <= 1.0
                and all(d.cost <= 1.5 and d.status in ("ok", "guessed") for d in r[5])]
        if len(good) != 1:
            return None
        sc, name, old, p, fen, decs = good[0]
        def word(piece):
            if piece is None:
                return "empty"
            return f"a {'white' if piece.color else 'black'} {chess.piece_name(piece.piece_type)}"
        note = (f"The board reading of {self.diagram_name(cand['did'])} was unsure of {name}; "
                f"the program reads it as {word(p)} instead of {word(old)}, since only then "
                "are the moves legal.")
        new = dict(cand, fen=fen, score=sc, decs=decs,
                   hits=self.checkpoint_hits(decs, placements, cand["did"]))
        return new, note

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
        if run.text:
            return run.text
        return re.sub(r"[ \n\r]+", " ", self.st.orig_text[run.start:run.end]).strip()

    def unplaced(self, run, reason, src=None, dismiss=None, after=None):
        """A sequence placed in no line, with the reason in words. src is the
        line whose notes held it; dismiss holds the entry fields of a
        sequence the reader dismissed as no variation; after is the key of
        the move that the text prints it after (a bare move, see
        bare_move_before), which the reader offers as the move to join it
        to."""
        ci = run.ci if run.ci >= 0 else self.ci
        page, box = self.place_of(run.moves[0], ci) if run.moves else (None, None)
        key = fixes.token_key(page, box, run.moves[0].raw) if box is not None else None
        entry = {"page": page or self.place_of(run.tokens[0], ci)[0], "chapter": ci,
                 "text": self.run_text(run), "reason": reason, "key": key, "bbox": box,
                 "_src": src.id if src is not None else None}
        if after:
            entry["after"] = after
        if dismiss is not None:
            entry.update(dismiss)
            self.dismissed.append(entry)
            return
        self.unattached.append(entry)
        if src is None and not self.replaying:
            self.unplaced_runs.append((entry, run))
        saved, self.ci = self.ci, ci
        for t in run.moves:
            m_page, _ = self.mark(None, t, None, "unattached", reason=reason)
            if m_page is not None:
                m = self.marks[m_page][-1]
                m["_src"] = entry["_src"]
                if src is not None:
                    self.line_pages[src.id].add(m_page)
                if key:
                    m["seq"] = key
        self.ci = saved

    # -------------------------------------------------------- main runs
    def on_main(self, run):
        L = self.active
        if L is not None and L.hold is not None:
            cont = self.continues_held(L, run)
            if cont is not None:
                L.hold = None                   # the line goes on past the diagram
                run = cont
            elif self.variation_across_hold(L, run):
                # a diagram printed among the line's own moves did not end it:
                # here a variation in the main font follows, where its
                # numbering puts it
                L.hold = None
            else:
                self.close(run.start)
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
                first.kind == "number" and first.number is None and self.prose_line(run.start)) or (
                L is not None and P is not None and P < L.next_ply and not L.waiting
                and P - 1 in L.ply_node and self.prose_line(run.start)):
            # (the last: an earlier move of the line named in a sentence, as
            # in a box of advice set in the move font, is a variation)
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
            cut = (self.diagram_cut(run) if not (accept or self.replaying
                                                 or self.deferred is not None) else None)
            if cut is not None:
                # moves that do not read from the initial position: those after
                # a diagram printed among them are taken up at the diagram,
                # which shows their position if the moves before it do not
                # reach it (see the chapter loop)
                run, tail, off = cut
                self.deferred = (off, tail)
                accept, _, did = self.initial_accept(run)
            self.release_pre_notes(None if accept else did)
            self.adopt_pre_notes(self.start_from_initial(run, "main"))
            return
        # a line whose own moves stopped reading (the position after them is
        # a guess) takes up its numbering again after a diagram: the diagram
        # gives the position, and a new fragment starts from it
        resync = (L is not None and P is not None and P == L.next_ply and not L.waiting
                  and self.lost(L)
                  and any(L.last_token_end <= off <= run.start for off, _ in self.diagram_events))
        if L is not None and P == L.next_ply and not resync:
            if self.pending_header and L.header is None:
                L.header, L.kind, L.title = self.pending_header, "game", self.pending_header["text"]
                self.pending_header = None
            self.extend_or_defer(L, run)
            return
        if (L is not None and P is not None and P == L.next_ply + 1 and not L.waiting
                and not L.broken and L.last_fen and not self.lost(L)
                and not self.diagram_between(L, run)):
            # the reply printed without its number after a comment ("10.Nd3
            # Every swap helps Black. b5 11.Bb3"): the line goes on with it
            hit = self.bare_reply(run, L.last_fen, L.last_token_end, main=True)
            if hit is not None:
                ext, decs, clean = hit
                if clean:
                    self.extend(L, ext, decs)
                    return
                self.bare_unplaced(ext, L.main_nodes[-1])
        # (an earlier move of the open line that the run names makes it an
        # alternative within that line, not a resumption)
        R = (self.resumable(run, L) if P is not None and P > 0
             and (L is None or L.waiting or P > L.next_ply) else None)
        if R is not None:
            # the run resumes an earlier line of the chapter where it stopped,
            # after a digression ("4...Nf6" after other moves or a diagram)
            if L is not None:
                self.close(run.start)
            self.active = self.reopen(R, run)
            self.extend(R, run)
            self.adopt_pre_notes(R)
            return
        between = L is not None and (self.diagram_between(L, run) or resync)
        if L is not None and P is not None and not between:
            # The numbering does not continue the line, but nothing stands
            # between: moves missing from the text, moves the book leaves out
            # ("1.Kxc3+, 2.Qxf5+, ..."), a misprinted number, or a variation
            # in the main font.
            if L.waiting or L.broken:
                if P > L.next_ply:
                    self.extend_or_defer(L, run)
                    return
            elif P > L.next_ply:
                if P - L.next_ply <= GAP_MAX:
                    self.gap(L, run, P)
                    return
            elif not self.reads_at(L, run, P):
                # (a run that reads as legal play where its numbering puts it
                # is a variation there, however it may read at the line's end)
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
            L2 = self.chapter_join(run) or self.from_diagram(run, "main")
        if L2 is not None:
            self.active = L2
            self.extend(L2, run)
            self.adopt_pre_notes(L2)

    def variation_across_hold(self, L, run):
        """True when the run after a diagram printed among the moves of the
        held line L is a variation of L in the main font: it reads where its
        numbering puts it, a full move or more before the line's next move
        ("25...fxe5" after the game reached move 34). A run that only offers
        another move for the line's last one is not: that move is more likely
        a stray of the text before the diagram (a move named in a note), and
        the run the line itself, going on from the diagram."""
        return (L.hold_inside and run.ply is not None and run.ply < L.next_ply - 1
                and self.reads_at(L, run, run.ply))

    def reads_at(self, L, run, P):
        """True when the run reads cleanly from the position of L's main line
        before ply P."""
        nid = L.ply_node.get(P - 1)
        fen = self.nodes[nid]["fen"] if nid is not None else None
        return bool(fen) and _fit(self.dec.run(fen, run.tokens))[0] == 0

    def lost(self, L):
        """True when the line's main line no longer reads: a gap in the text,
        or its last two moves failed (the position after them is a guess)."""
        if L.broken:
            return True
        last = [self.nodes.get(n) for n in L.main_nodes[1:][-2:]]
        return len(last) == 2 and all(n is not None and n.get("status") == "failed" for n in last)

    def split_lost(self, L, run):
        """A run that a lost line would take in whole, cut at the first
        diagram printed among its moves: (head, tail) when the line is lost
        by the end of head (see lost), so that the moves after the diagram
        start from the position it shows (on_main, resync), else None."""
        if L.waiting or self.replaying:
            return None
        cut = self.diagram_cut(run)
        if cut is None:
            return None
        if not L.broken:
            decs = self.dec.run(L.last_fen, cut[0].tokens) if L.last_fen else []
            if len(decs) < 2 or not all(d.status == "failed" for d in decs[-2:]):
                return None
        return cut

    def diagram_cut(self, run):
        """(head, tail, offset): the run cut at the first diagram of the
        selection printed among its moves, when moves stand on both sides and
        the tail starts at a numbered move; else None."""
        cuts = [off for off, _, kind, did in self.st.events
                if kind == "diagram" and run.start < off < run.end and self.diagram_selected(did)]
        if not cuts:
            return None
        off = cuts[0]
        head = [t for t in run.tokens if t.end <= off]
        tail = [t for t in run.tokens if t.start >= off]
        hm = [t for t in head if t.kind == "move"]
        tm = [t for t in tail if t.kind == "move"]
        if not hm or not tm or _ply(tm[0]) is None:
            return None
        a = replace(run, tokens=head, moves=hm, end=head[-1].end, result=None, text="")
        b = replace(run, tokens=tail, moves=tm, start=tail[0].start, ply=_ply(tm[0]), text="")
        return a, b, off

    def extend_or_defer(self, L, run):
        """Extend L with the run, or with its moves up to a diagram printed
        among them when the line is lost there (split_lost): the rest of the
        run is taken up once the diagram is reached (chapter, "diagram")."""
        cut = self.split_lost(L, run)
        if cut is None:
            self.extend(L, run)
            return
        head, tail, off = cut
        self.extend(L, head)
        self.deferred = (off, tail)

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
        return replace(run, tokens=toks, moves=moves, ply=_ply(moves[0]))

    def gap(self, L, run, P, follow=True):
        """The numbering skips moves that the text does not show (P is the ply
        the run starts at). The program does not invent them: the decoded part
        of the line ends with a node that marks the gap, and with follow the
        run's moves come after it as unread text, since the position there is
        unknown."""
        if not self.replaying:
            L.ops.append(("gap", run, P, follow))
        page = self.place_of(run.tokens[0], run.ci)[0]
        key = self.key_of(run.moves[0], run.ci) if run.moves else None
        fill, stale = self.fill_gap(L, run, P, page, key) if self.replaying else ([], "")
        if L.next_ply >= P:
            return                  # the reader gave every move the text lacks
        missing = P - L.next_ply
        what = _ply_words(L.next_ply)
        if missing > 1:
            what += f" and the {missing - 1} move{'s' if missing > 2 else ''} after it"
        reason = (f"The book's text lacks {what}, so the program cannot follow the line "
                  "from here." if follow else
                  f"The book's text lacks {what}; the line goes on from the diagram after it.")
        nid = self.new_node(L, parent=L.main_nodes[-1], number=L.next_ply // 2 + 1,
                            black=bool(L.next_ply % 2), status="failed", raw="", main=True,
                            page=page, reason=(stale + " " + reason).strip())
        if key:
            # the reader can give the moves the text lacks (corrections.py "gaps")
            self.nodes[nid]["gap"] = key
            self.nodes[nid]["fill"] = fill
            self.nodes[nid]["missing"] = missing
        L.main_nodes.append(nid)
        L.broken = True
        L.last_fen = None
        L.ply_node[L.next_ply] = nid
        L.next_ply = P
        if follow and not self.replaying:
            self.extend_or_defer(L, run)

    def fill_gap(self, L, run, P, page, key):
        """Play the moves the reader gave for a gap in the text (corrections.py
        "gaps", stored under the key of the first printed move after the gap)
        as main-line moves of L, when they are legal from the line's last
        position. Returns (the moves played, the reason the stored moves were
        ignored, or "")."""
        if not key or not self.fix_gaps:
            return [], ""
        pg, x, y, raw = fixes.parse_key(key)
        _, v = self.fix_gaps.find(pg, (x, y), raw)
        if not v or not v.get("san"):
            return [], ""
        sans = list(v["san"])
        if L.waiting or L.broken or not L.last_fen:
            return [], ""
        missing = P - L.next_ply
        if len(sans) > missing:
            return [], (f"You gave {len(sans)} moves here, but the text lacks only "
                        f"{missing}, so the program ignores them.")
        board = chess.Board(L.last_fen)
        moves = []
        for san in sans:
            try:
                mv = board.parse_san(san)
            except ValueError:
                side = "Black" if board.turn == chess.BLACK else "White"
                return [], (f"The move you gave here, {san}, is not a legal move for {side} in "
                            "this position, so the program ignores the moves you gave.")
            moves.append((board.copy(), mv))
            board.push(mv)
        played = []
        for before, mv in moves:
            after = before.copy()
            after.push(mv)
            nid = self.new_node(L, parent=L.main_nodes[-1], san=before.san(mv), fen=after.fen(),
                                number=before.fullmove_number, black=before.turn == chess.BLACK,
                                status="ok", raw="", main=True, uci=mv.uci(), page=page,
                                corrected="filled", gap=key)
            L.main_nodes.append(nid)
            L.ply_node[L.next_ply] = nid
            L.next_ply += 1
            L.last_fen = after.fen()
            played.append(before.san(mv))
        return played, ""

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
            if not accept and n >= 2:
                # a short run that the next runs continue ("1 e4 e6 2 d3",
                # a diagram, "2...d5 3 Nd2"): read them together
                more = self.lookahead(run, 8)
                m = sum(1 for t in more if t.kind == "move")
                accept = m >= 5 and _fit(self.dec.run(chess.STARTING_FEN, more))[0] == 0
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
        cut = self.bare_cut(L, run)
        if cut is not None and cut[4]:
            # the reply printed without its number between the run's moves
            # ("7.Bd3 Every swap helps Black. Nbd7 8.Qc2"): the line goes on
            # with it, and the run is read in two parts
            head, ext, dh, de, _ = cut
            self.extend(L, head, dh)
            self.extend(L, ext, de)
            return
        if not self.replaying:
            L.ops.append(("main", run))
        else:
            run, decs = self.forced(run), None
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
            if not self.replaying:
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
        if self.replaying:
            if run.result:
                L.result = run.result
            return
        if cut is not None:
            # a bare move the moves after it do not confirm: an item to join
            head, ext = cut[0], cut[1]
            nid = next((n for s_, _, n in L.main_tok if s_ == head.moves[-1].start), None)
            if nid is not None:
                self.bare_unplaced(ext, nid)
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
        if box is not None:
            self.nodes[nid]["key"] = fixes.token_key(page, box, tok.raw)
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
            if tok.forced:
                self.nodes[nid]["corrected"] = "move"
            elif self.named_piece(tok, d):
                self.nodes[nid]["corrected"] = "symbol"
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
            if tok.forced:
                self.nodes[nid]["reason"] = (f"The move you gave here, {tok.forced}, is not legal "
                                             "in this position.")
        page, box = self.mark(self.st, tok, nid, self.nodes[nid]["status"], L.id)
        self.nodes[nid]["page"], self.nodes[nid]["bbox"] = page, box
        if box is not None:
            self.nodes[nid]["key"] = fixes.token_key(page, box, tok.raw)
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
        if self.is_long(run):
            # a move in long notation in the text after a line: it refers to
            # that line (see do_long)
            L = self.last_closed if (self.last_closed is not None
                                     and self.last_closed.chapter == self.ci) else None
            cue = self.long_cue(run)
            if L is None:
                if cue not in (None, "plan"):
                    self.unplaced(run, "no line stands where it is printed")
                return                  # a move named in the prose stays text
            op = ("long", run, cue)
            L.ops.append(op)
            self.do_long(L, op)
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
        """Place the line's note runs, recording each decision as an op of the
        line (see replay_line): the text decides what may be placed, the
        moves decide where."""
        blocks = [s for s, _, _ in L.main_tok]
        L.ops.append(("notes",))
        state = {"vars": defaultdict(list), "last": None}
        for run, as_main in L.notes:
            if self.is_long(run):
                op = ("long", run, self.long_cue(run))
                L.ops.append(op)
                self.do_long(L, op, state)
                continue
            if self.is_threat(run):
                op = ("unplaced", run, "the text gives these moves as a threat or a plan, not as "
                                       "moves played")
                self.tidy(L, run)
            elif (lambda ref: ref and ref[1] and ref[1] != L.diagram)(self.referenced_diagram(run)):
                ref = self.referenced_diagram(run)
                self.detached_line(run, ref[1], ref[0])
                continue
            elif run.ply is None and not _ALT_CUE_RE.search(self.lead_text(run.start, 60)):
                op = ("unplaced", run, "its first move carries no move number, and no word such as "
                                       "\"instead\" or \"better\" ties it to a move of the line")
                self.tidy(L, run)
            else:
                # the reply printed without its number after a comment
                # ("10.Nd3 Every swap helps Black. b5 11.Bb3") goes with the run
                ext = self.bare_lead(L, run, state, blocks)
                run = ext or run
                cue = bool(_FOLLOW_RE.search(self.lead_text(run.start, 40)))
                op = ["note", run, as_main, bisect.bisect_left(blocks, run.start), cue, False]
                if run.ply == 0 and not as_main and (L.waiting or 0 not in L.ply_node):
                    op[5] = None            # may be a sequence of its own (see note_op)
                if ext is not None:
                    op.append(True)         # begins with a bare move (see do_note)
                op = tuple(op)
            L.ops.append(op)
            placed = self.do_note(L, op, state, base=True)
            if placed and op[0] == "note":
                tail = self.bare_tail(L, run, state, op[3])
                if tail is not None:
                    # a move without its number that ends the variation
                    # ("... familiar with: Qxd4!"): it may only go on with it
                    op = ("note", tail, as_main, op[3], True, False)
                    L.ops.append(op)
                    self.do_note(L, op, state, base=True)

    @staticmethod
    def is_long(run):
        """A run found as long notation in the text ("...e7-e6", "Ng1-f3")
        without a move number to place it by."""
        return run.kind == "long" or (run.ply is None and len(run.moves) == 1
                                      and bool(_LONG_RAW_RE.search(run.moves[0].raw)))

    def long_cue(self, run):
        """How the text gives a move printed in long notation without a move
        number (see do_long), from the structure of its sentence alone:

        "plan"      a manoeuvre over several squares ("Nf3-d2-c4");
        ("follow", start)
                    it comes right after a numbered run of the notes (which
                    starts at start), joined by "and then", "followed by",
                    "then", "with" or "and": it goes on with that variation;
        "alt"       a word such as "Or", "Instead", "If", "after" or "then",
                    or a bracket that holds other moves, introduces it;
        "line"      a move of the other side stands right before or after it
                    ("... d5xe4 and d3xe4"): the moves form a line;
        None        a move named in the prose, alone: it refers to a move of
                    the line, or stays text.
        """
        mv = run.moves[0]
        if len(_SQUARES_RE.findall(mv.raw)) > 2:
            return "plan"               # a manoeuvre: "Nf3-d2-c4"
        text = self.st.orig_text
        k = bisect.bisect_left(self.run_starts, run.start)
        prev = next((r for r in reversed(self.all_runs[:k]) if r.end <= run.start), None)
        nxt = next((r for r in self.all_runs[k:] if r.start >= run.end and r is not run), None)
        before = text[prev.end:run.start] if prev is not None else None
        if (prev is not None and prev.kind == "note" and prev.ply is not None
                and len(before) <= 24 and _LONG_FOLLOW_RE.match(before)):
            return ("follow", prev.start)
        side = self.long_side(run)
        if (prev is not None and self.is_long(prev) and len(before) <= 16
                and _LONG_JOIN_RE.match(before)
                and self.move_side(prev, prev.moves[-1]) not in (None, side)):
            return ("follow", prev.start)   # "...d5xe4 and d3xe4": the reply
        lead = self.lead_text(run.start, 80)
        hit = _LONG_ALT_RE.search(lead)
        if hit:
            if not hit.group(0).strip().startswith("("):
                return "alt"
            # a bracket that holds other moves: "(b2-b4 and 12.Nd2)"
            inner = text[run.end:run.end + 80].split(")", 1)[0]
            if nxt is not None and nxt.start < run.end + len(inner):
                return "alt"
        if (prev is not None and before is not None and len(before) <= 16
                and _LONG_JOIN_RE.match(before)):
            other = self.move_side(prev, prev.moves[-1])
            if other is not None and other != side:
                return "line"
        if nxt is not None and nxt.start - run.end <= 16 \
                and _LONG_JOIN_RE.match(text[run.end:nxt.start]):
            other = self.move_side(nxt, nxt.moves[0])
            if other is not None and other != side:
                return "line"
        return None

    def long_side(self, run):
        """True for Black: the side that plays a move printed in long notation,
        from its dots ("...e7-e6"), the direction of a pawn's step, or else
        White, as books mark Black's moves in the prose with dots."""
        return self.move_side(run, run.moves[0])

    @staticmethod
    def move_side(run, tok):
        """True for Black, False for White, None when the text does not say:
        the move number or dots before the move, or the squares of a move in
        long notation."""
        if tok.number is not None or tok.side_known:
            return bool(tok.black)
        if tok is run.moves[0] and run.tokens and run.tokens[0].kind == "number":
            return bool(run.tokens[0].black) if run.tokens[0].side_known else None
        m = re.search(r"([a-h])([1-8])\s?[-–—x:×]\s?([a-h])([1-8])", tok.raw)
        if m is None:
            return None
        pawn = not re.search(r"[KQRBN]", tok.raw[:m.start()]) and not m.start()
        if pawn and m.group(2) != m.group(4):
            return m.group(4) < m.group(2)
        return False

    def long_reference(self, L, run, uci, kind=None):
        """The move of L that a move in long notation names: the most recent
        move printed before its sentence, in the line's main line or in a
        variation of the same note, that goes from the same square to
        the same square; or else the line's next move, when it is that move.
        None when there is no such move, or when after it a piece of the same
        kind and side went to that square from another square, or a piece
        came to the square it leaves (then the text names another move)."""
        # variations count from the note the sentence stands in: the text
        # after the last move of the main line before it
        para = max((s_ for s_, _, _ in L.main_tok if s_ < run.start), default=0)
        main = {nid for _, _, nid in L.main_tok}
        seen = []
        for page in self.line_pages.get(L.id, ()):
            for m in self.marks.get(page, ()):
                nid = m["node"]
                if (m["line"] == L.id and nid is not None and not m.get("ref")
                        and m["_o"] < run.start and nid in self.nodes
                        and (nid in main or m["_o"] >= para)):
                    seen.append((m["_o"], nid))
        seen.sort(key=lambda x: -x[0])
        for _, nid in seen:
            n = self.nodes[nid]
            u = n.get("uci")
            if not u:
                continue
            if u[:4] == uci and self.same_kind(n, kind):
                return nid
            if u[2:4] == uci[2:4] and n.get("san") and self.same_mover(n, uci, kind):
                break                   # the same piece came there from elsewhere since
            if u[2:4] == uci[:2]:
                break                   # a piece came to the square it leaves since
        nxt = next((nid for s_, _, nid in L.main_tok if s_ > run.start and nid in self.nodes), None)
        if nxt is not None and (self.nodes[nxt].get("uci") or "")[:4] == uci \
                and self.same_kind(self.nodes[nxt], kind):
            return nxt
        return None

    @staticmethod
    def same_kind(node, kind):
        """True when the move of node is made by the kind of piece that a move
        in long notation prints (kind: its letter, "P" for none, None when a
        glyph that cannot be read stands there)."""
        san = node.get("san") or ""
        if kind is None or not san or san.startswith("O-O"):
            return kind is None
        return (san[0] if san[0] in "KQRBN" else "P") == kind

    def same_mover(self, node, uci, kind=None):
        """True when the move of node was made by the side and kind of piece
        that would make the move uci (kind: the piece letter printed, "P"
        for none, None when unknown) in the position before node."""
        parent = self.nodes.get(node["parent"]) if node.get("parent") else None
        if not parent or not parent.get("fen"):
            return False
        b = chess.Board(parent["fen"])
        mover = b.piece_at(chess.parse_square(node["uci"][:2]))
        named = b.piece_at(chess.parse_square(uci[:2]))
        if mover is None:
            return False
        if named is not None:
            return named == mover
        return kind is not None and mover.color == b.turn and mover.symbol().upper() == kind

    def do_long(self, L, op, state=None):
        """Place a move printed in long notation that has no move number (cue
        from long_cue): (a) a move that goes on with the variation before it
        ("8.Rd1 and then Nb1-c3") continues it when it is legal there, and
        stays text otherwise; (b) a move the line played refers to that move
        (a mark linked to it, see long_reference); (c) a move that a word such
        as "Or" or "If" introduces, or that forms a line with the moves next
        to it, is a variation where the line stands when it is legal there,
        and stands in no line with the reason otherwise; (d) anything else
        (a move named in the prose, a plan) stays text."""
        _, run, cue = op
        tok = run.moves[0]
        sq = _SQUARES_RE.findall(tok.raw)
        if cue == "plan":
            return
        uci = sq[0] + sq[1]
        saved, self.ci = self.ci, run.ci
        try:
            if isinstance(cue, tuple):
                st_ = state or {}
                last = (st_.get("last") if st_.get("last_start") == cue[1] else
                        st_.get("long_last") if st_.get("long_start") == cue[1] else None)
                if last is not None and not L.waiting:
                    run = self.forced(run) if self.replaying else run
                    fen = self.nodes[last["last"]]["fen"]
                    decs = self.dec.run(fen, run.tokens) if fen else None
                    if decs and decs[0].status != "failed" and _fit(decs)[0] == 0:
                        nodes = self.insert_decoded(L, last["last"], run, decs)
                        last["last"] = nodes[-1]
                        if last["next"] is not None:
                            last["plies"][last["next"]] = nodes[-1]
                            last["next"] += 1
                        if state is not None:
                            state["long_last"], state["long_start"] = last, run.start
                return                      # a plan within the variation: text
            m = re.match(r"(?:\.\.\.|…)?\s?([KQRBN])?[a-h][1-8]", tok.raw)
            kind = (m.group(1) or "P") if m else None
            nid = self.long_reference(L, run, uci, kind)
            if nid is not None:
                page, box = self.mark(None, tok, nid, self.nodes[nid]["status"], L.id)
                if page is not None:
                    self.marks[page][-1]["ref"] = True
                return
            if cue is None:
                return                      # a move named in the prose
            before = [nid for s_, _, nid in L.main_tok if s_ < run.start and nid in self.nodes]
            at = before[-1] if before else (L.main_nodes[-1] if L.main_nodes else None)
            if at is not None and not L.waiting:
                run = self.forced(run) if self.replaying else run
                for parent in (at, self.nodes[at]["parent"]):
                    fen = self.nodes[parent]["fen"] if parent is not None else None
                    if not fen:
                        continue
                    decs = self.dec.run(fen, run.tokens)
                    if decs and decs[0].status != "failed" and _fit(decs)[0] == 0:
                        nodes = self.insert_decoded(L, parent, run, decs)
                        L.variations += 1
                        if state is not None:
                            # a reply in long notation may go on from it
                            state["long_last"] = {"depth": run.depth, "plies": {},
                                                  "last": nodes[-1], "next": None}
                            state["long_start"] = run.start
                        return
            self.unplaced(run, f"the move it names is not legal where the line \"{L.title}\" "
                               "stands, and the line did not play it", src=L)
        finally:
            self.ci = saved

    def do_note(self, L, op, state, base=False):
        """Carry out a recorded note op: place the run as a variation, or say
        why it has no place."""
        if op[0] == "unplaced":
            self.unplaced(op[1], op[2], src=L)
            return False
        if op[0] == "dismiss":
            self.unplaced(op[1], None, src=L, dismiss=op[2])
            return False
        if op[0] == "long":
            self.do_long(L, op, state)
            return False
        _, run, as_main, block, cue, side = op[:6]
        if self.replaying:
            run = self.forced(run)
        if len(op) > 6 and op[6]:
            # the run begins with a move printed without its number
            # (bare_lead): it goes on with the line when the moves confirm it,
            # else the numbered moves are placed on their own and the bare
            # move stands in no line, for the reader to join
            hit = self.place_bare(L, run, block, state["vars"][block])
            if hit is True:
                L.variations += 1
                state["last"] = state["vars"][block][-1]
                state["last_start"] = run.start
                return True
            head, run = self.cut_run(run, 1)
            if hit is not None:
                parent, decs = hit
                if decs and decs[0].status == "ok" and decs[0].san:
                    self.unplaced(head, f"it carries no move number, and the moves after it do not "
                                        f"read on from it after {self.move_words(parent)}", src=L,
                                  after=self.nodes[parent].get("key"))
            if base:
                self.tidy(L, head)
        follows = state["last"] is not None and cue
        placed = self.place(L, run, block, state["vars"][block],
                            only=state["last"] if follows else None)
        if placed is True:
            L.variations += 1
            state["last"] = state["vars"][block][-1]
            state["last_start"] = run.start
            return True
        if side is None and base:
            # an opening sequence inside a line that starts later: its own fragment
            decs = self.dec.run(chess.STARTING_FEN, run.tokens)
            if self.side_ok(run, decs):
                self.side_fragment(run, decs, L)
                L.ops[-1] = op[:5] + (True,)
                return False
        if side:
            return False                # the sequence is a line of its own
        self.unplaced(run, self.why_not(L, run, placed, follows), src=L)
        if base:
            self.tidy(L, run)
        return False

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
        # a run whose numbering goes on from the variation before it in the
        # same bracket continues that variation ("(1...Kh6 is met by the
        # waiting move 2.Rb7"), before it branches from the move the bracket
        # follows
        sibling = (cont[-1] if run.depth > 0 and cont and run.bracket is not None
                   and cont[-1].get("bracket") == run.bracket else None)
        for ply in plies:
            if sibling is not None and sibling["next"] == ply:
                add(sibling["last"], "continue")
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
            if not self.replaying:
                self.dec.accepted.append(decs)
            nodes = self.insert_decoded(L, parent, run, decs)
        plies = {}
        for nid in nodes:
            ply = self.node_ply(nid)
            if ply is not None:
                plies[ply] = nid
        last = nodes[-1] if nodes else parent
        vars_.append({"depth": run.depth, "plies": plies, "last": last,
                      "next": (max(plies) + 1) if plies else None, "bracket": run.bracket,
                      "end": run.end})
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
        if self.replaying:
            return
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
        if self.replaying:
            return
        for t in run.tokens:
            if t.kind == "number" and t.number is not None:
                L.replace.append((t.start, t.end, f"{t.number}{'...' if t.black else '.'}"))
            elif t.kind == "move":
                text = readable_move(t.raw, self.dec.glyphs, self.dec.letters)
                if text:
                    L.replace.append((t.start, t.end, text))

    # -------------------------------------------------------- bare moves
    #
    # Annotators often follow a move with a comment and print the reply
    # without its move number ("10.Nd3 Every swap helps Black. b5 11.Bb3
    # a5"). Such a word is no token of any run (tokenize reads a move only
    # inside a numbered run); the methods below find it in the text between
    # a line's last move and the numbered run that goes on after it, and the
    # moves decide: see bare_move_before for what the text must look like,
    # bare_lead and on_main for the numbered run that confirms it, and
    # bare_tail for a move that ends a variation in a bracket.

    def token_at(self, s, e):
        """True when a token of a run overlaps text[s:e]."""
        k = bisect.bisect_right(self.token_spans, (s, 10 ** 9))
        return (k > 0 and self.token_spans[k - 1][1] > s) or \
            (k < len(self.token_spans) and self.token_spans[k][0] < e)

    def bare_move_before(self, lo, hi, main=False):
        """A move printed without a move number as the last word before hi,
        after lo (the end of the line's last move), or None. The word must
        look like a move with its rank printed ("b5", "Qc7", "Bxf3!"), carry
        no stop or comma after it, and stand in no run; the words after it
        may only join it to the run ("b5, and then"). Its sentence (from the
        last stop, semicolon, colon or bracket before it) holds no other
        move, and its clause before a colon no cue that makes it a threat, a
        plan or an idea ("Threat: Qxf7 mate!"). With main, a word such as
        "Or", "Instead", "If" or "After" before it keeps it an alternative.
        Returns the move's token, with no number yet."""
        text = self.st.orig_text
        words = list(re.finditer(r"\S+", text[lo:hi]))
        k = len(words) - 1
        while k >= 0 and words[k].group().lower().strip(",;") in _BARE_JOIN_WORDS:
            k -= 1
        if k < 0:
            return None
        w = words[k].group()
        s, e = lo + words[k].start(), lo + words[k].end()
        if w[-1] in ".,;:" or w[0] in "([{\"'“‘" or _RESULT_RE.match(w) or self.token_at(s, e):
            return None
        core, _, _ = _strip_suffix(w)
        if not core or _shape(w) != "strong" or core.isdigit() or len(core) < 2:
            return None
        if not (re.search(r"[a-h][1-8]$", core) or _CASTLE_RE.match(core.replace(" ", ""))):
            return None                 # a rank read from a letter is no bare move
        head = text[lo:s]
        # the sentence and the clause the move stands in
        stops = [m.end() for m in re.finditer(r"[.!?;]\s|[(\[]", head)]
        clause = head[stops[-1]:] if stops else head
        cuts = [m.end() for m in re.finditer(r"[.!?;:]\s|[(\[]", head)]
        sentence = head[cuts[-1]:] if cuts else head
        if _BARE_CUE_RE.search(clause):
            return None
        if main and _ALT_LEAD_RE.search(re.sub(r"\s+", " ", sentence)):
            return None
        for m in re.finditer(r"\S+", sentence):
            ww = m.group()
            if _shape(ww) == "strong" and not ww.endswith((".", ",", ";")) \
                    and re.search(r"[a-h][1-8]", _strip_suffix(ww)[0]):
                return None             # another move in the sentence: prose about moves
        return Token("move", w, s, e, None, False)

    def bare_extended(self, run, tok, ply):
        """The run with the bare move tok before its first move, numbered
        from ply (the ply tok is played at)."""
        toks = [tok] + list(run.tokens)
        _relabel(toks, ply // 2 + 1, bool(ply % 2))
        moves = [t for t in toks if t.kind == "move"]
        saved, self.ci = self.ci, run.ci if run.ci >= 0 else self.ci
        try:
            self.place_of(moves[0])
            self.note_spot(moves[0])
        finally:
            self.ci = saved
        text = re.sub(r"[ \n\r]+", " ", self.st.orig_text[toks[0].start:toks[-1].end]).strip()
        return replace(run, tokens=toks, moves=moves, start=toks[0].start, ply=ply, text=text)

    def bare_reply(self, run, fen, lo, main=False):
        """(the run with the bare move before it, its decoding, clean) when a
        bare move stands last before the run (bare_move_before), the run's
        numbering is one move ahead of the position fen and the bare move is
        legal there; clean says whether the run reads cleanly after it. None
        otherwise."""
        if run.ply is None or not fen or _board_ply(fen) != run.ply - 1:
            return None
        tok = self.bare_move_before(lo, run.start, main=main)
        if tok is None:
            return None
        ext = self.bare_extended(run, tok, run.ply - 1)
        decs = self.dec.run(fen, ext.tokens)
        if not decs or decs[0].status != "ok" or not decs[0].san:
            return None
        clean = _fit(decs)[0] == 0 and not any(d.capture_mark and d.san and "x" not in d.san
                                               for d in decs)
        return ext, decs, clean

    def bare_unplaced(self, ext, nid):
        """The bare move before the run ext stands in no line, with the move
        nid (of the line in progress) the reader may join it to."""
        head, _ = self.cut_run(ext, 1)
        self.unplaced(head, "it carries no move number, and the moves after it do not read "
                            f"on from it after {self.move_words(nid)}",
                      after=self.nodes[nid].get("key"))

    def bare_cut(self, L, run):
        """A main run whose numbering skips one move inside it ("7.Bd3 8.Qc2
        Re8", the reply printed in the notes' font between them): (head, the
        rest with the bare move before it, the decodings of both) when the
        head reads cleanly from the line's last position, the bare move is
        legal after it and the rest reads cleanly after the bare move
        (bare_reply); else None."""
        if L.waiting or L.broken or not L.last_fen or run.ply is None or self.replaying:
            return None
        expect = run.ply
        j = None
        for i, t in enumerate(run.tokens):
            if t.kind != "move":
                continue
            p = _ply(t)
            if p == expect + 1 and i > 0 and run.tokens[i - 1].kind == "number":
                j = i
                break
            if p != expect:
                return None
            expect = p + 1
        if j is None:
            return None
        head, tail = self.cut_run(run, j)
        if head is None or tail is None or self.diagram_cut(run) is not None:
            return None
        dh = self.dec.run(L.last_fen, head.tokens)
        if _fit(dh)[0] != 0 or not dh[-1].fen:
            return None
        hit = self.bare_reply(tail, dh[-1].fen, head.end, main=True)
        if hit is None:
            return None
        ext, de, clean = hit
        return head, ext, dh, de, clean

    def bare_lead(self, L, run, state, blocks):
        """The note run with the bare move that the text prints before it
        (bare_move_before) as the next move of the variation it would go on
        with: the latest variation of the same note and bracket, or the main
        line's end, whose next move the run's numbering skips. The moves
        decide in place_bare whether it goes on so; else None."""
        if run.ply is None or L.waiting:
            return None
        block = bisect.bisect_left(blocks, run.start)
        vars_ = state["vars"][block]
        lo = None
        v = self.bare_parent(run, vars_, run.ply - 1)
        if v is not None and v.get("end", run.start) < run.start:
            lo = v["end"]
        elif (run.depth == 0 and block >= len(L.main_tok) and L.main_tok and not L.broken
                and L.next_ply == run.ply - 1):
            lo = L.main_tok[-1][1]
        if lo is None:
            return None
        tok = self.bare_move_before(lo, run.start)
        if tok is None:
            return None
        ext = self.bare_extended(run, tok, run.ply - 1)
        return None if self.is_threat(ext) else ext

    @staticmethod
    def bare_parent(run, vars_, ply):
        """The variation of the note that a bare move before run would go on
        with: the latest one of the run's depth and bracket whose next move
        is ply, or, for a run outside any bracket, the latest one of the note
        at all (the tokenizer's bracket depth ends inside a long bracket)."""
        cont = [v for v in vars_ if v["depth"] == run.depth
                and (run.depth == 0 or v.get("bracket") == run.bracket)]
        if cont and cont[-1]["next"] == ply:
            return cont[-1]
        if run.depth == 0 and vars_ and vars_[-1]["next"] == ply:
            return vars_[-1]
        return None

    def place_bare(self, L, run, block, vars_):
        """Place a note run that begins with a bare move (bare_lead) as the
        continuation of the variation, or of the main line, whose next move
        it is: only when the bare move is legal there and the whole reads
        cleanly. Returns True, or (the parent node tried, its decoding)."""
        cands = []
        v = self.bare_parent(run, vars_, run.ply)
        if v is not None:
            cands.append(v["last"])
        if (run.depth == 0 and not L.broken and L.main_tok and run.start > L.main_tok[-1][1]
                and run.ply == L.next_ply):
            cands.append(L.main_nodes[-1])
        tried = None
        for parent in cands:
            fen = self.nodes[parent]["fen"]
            if not fen:
                continue
            decs = self.dec.run(fen, run.tokens)
            if tried is None:
                tried = (parent, decs)
            if not decs or decs[0].status != "ok" or not decs[0].san or _fit(decs)[0] != 0:
                continue
            if any(d.capture_mark and d.san and "x" not in d.san for d in decs):
                continue
            if not self.replaying:
                self.dec.accepted.append(decs)
            nodes = self.insert_decoded(L, parent, run, decs)
            plies = {}
            for nid in nodes:
                ply = self.node_ply(nid)
                if ply is not None:
                    plies[ply] = nid
            vars_.append({"depth": run.depth, "plies": plies, "last": nodes[-1] if nodes else parent,
                          "next": (max(plies) + 1) if plies else None, "bracket": run.bracket,
                          "end": run.end})
            return True
        return tried

    def bare_tail(self, L, run, state, block):
        """A move printed without a move number that ends a variation inside
        a bracket: after the variation's last run, before the bracket closes
        and with no run between, a colon introduces it ("... should be
        familiar with: Qxd4!"), it is the only move of its sentence, no cue
        makes it a threat or an idea, and it is legal at the variation's
        end. Returns a note run of that move, or None."""
        if run.depth == 0 or run.ply is None or L.waiting:
            return None
        vars_ = state["vars"][block]
        v = vars_[-1] if vars_ else None
        if v is None or v.get("end") != run.end or v["next"] is None:
            return None
        text = self.st.orig_text
        k = bisect.bisect_right(self.run_starts, run.end)
        limit = self.all_runs[k].start if k < len(self.all_runs) else len(text)
        close = re.search(r"[)\]]", text[run.end:limit])
        if close is None:
            return None
        seg_end = run.end + close.start()
        open_ = re.search(r"[(\[]", text[run.end:seg_end])
        if open_ is not None:
            seg_end = run.end + open_.start()
        seg = text[run.end:seg_end]
        m = re.search(r"(?:^|\s)\S+:\s+(\S+)", seg)
        if m is None:
            return None
        s, e = run.end + m.start(1), run.end + m.end(1)
        w = m.group(1)
        if w[-1] in ".,;:" or self.token_at(s, e):
            return None
        core, _, _ = _strip_suffix(w)
        if not core or _shape(w) != "strong" or not re.search(r"[a-h][1-8]$", core):
            return None
        clause = seg[:m.start(1)]
        stops = [x.end() for x in re.finditer(r"[.!?;]\s", clause)]
        if _BARE_CUE_RE.search(clause[stops[-1]:] if stops else clause):
            return None
        rest = seg[m.end(1):]
        stop = re.search(r"[.!?;]\s", rest)
        for x in re.finditer(r"\S+", rest[:stop.start()] if stop else rest):
            if _shape(x.group()) == "strong" and re.search(r"[a-h][1-8]", _strip_suffix(x.group())[0]):
                return None
        fen = self.nodes[v["last"]]["fen"]
        if not fen:
            return None
        tok = Token("move", w, s, e, None, False)
        tail = self.bare_extended(_Run("note", [], [], s, e, run.depth, None, None, ci=run.ci,
                                       bracket=run.bracket), tok, v["next"])
        decs = self.dec.run(fen, tail.tokens)
        if not decs or decs[0].status != "ok" or not decs[0].san:
            return None
        return tail

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
        if L.waiting or L.broken or not L.main_tok or not L.last_fen or L.hold is not None:
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

    def hold(self, off, did=None):
        """A diagram after the moves of a fragment usually ends it, but the next
        main run may go on with its numbering and read as legal play from its
        last position (the diagram only showed the position reached). The line
        is held open at off: on_main continues it in that case, and anything
        else closes it at off (see close). A line that began in the notes is
        held only when the diagram shows the position it has reached."""
        a = self.active
        if a is None:
            return
        shown = (self.diagram_fens.get(did) or "").split(" ")[0]
        if a.waiting or a.broken or not a.last_fen or (
                a.born != "main" and shown != a.last_fen.split(" ")[0]):
            self.request_close(off)
        elif a.hold is None:
            a.hold = max(off, a.busy_until)     # a run may go on across the diagram
            a.hold_inside = off < a.busy_until

    def continues_held(self, L, run):
        """The run read as the continuation of the held line L, or None."""
        if L.waiting or L.broken or not L.last_fen or self.pending_header is not None:
            return None
        if run.ply != L.next_ply:
            run = _renumbered(run, L.next_ply) or self.misnumbered(L, run) or run
        if run.ply != L.next_ply:
            return None
        if _fit(self.dec.run(L.last_fen, _first_moves(run.tokens, 4)))[0] != 0:
            return None
        return run

    def close(self, off):
        self.close_suspended()
        L = self.active
        self.active = None
        if L is None:
            return
        late = []
        if L.hold is not None and off > L.hold:
            # the line ends at the diagram that held it: notes after the
            # diagram belong to what follows it
            late = [n for n in L.notes if n[0].start > L.hold]
            L.notes = [n for n in L.notes if n[0].start <= L.hold]
            off = L.hold
        L.hold = None
        L.end_offset = off
        self.finish_line(L)
        self.last_closed = L
        prev = None
        for run, _ in late:
            # as if no line had been open: a diagram between two notes ends
            # the line the first one starts (see flush_pre_notes)
            cut = [doff for doff, _ in self.diagram_events
                   if prev is not None and prev < doff < run.start]
            if cut and self.pre_notes:
                self.flush_pre_notes()
                if self.active is not None:
                    self.close(cut[0])
            self.on_note(run)
            prev = run.start

    def chapter_join(self, run):
        """A line of the chapter before that goes on at the top of this chapter
        (the text runs on across a page that the book's structure takes for
        the start of a chapter): the first main run of the chapter, before
        any heading, game header or diagram, continues its numbering and
        reads as legal play from its last position. The run starts a line
        that finalize() joins to that line (see derive)."""
        prev = self.prev_chapter_line
        if (prev is None or self.structural or self.diagram_events or self.pending_header
                or any(M.chapter == self.ci for M in self.lines) or run.depth > 0):
            return None
        if prev.waiting or prev.broken or not prev.last_fen or prev.next_ply != run.ply:
            return None
        if _fit(self.dec.run(prev.last_fen, _first_moves(run.tokens, 4)))[0] != 0:
            return None
        L = self.start_line(run, "fragment", prev.title, False, None, "main", None, prev.last_fen)
        L.joins = prev
        L.start_note = (f"The moves go on from the line \"{prev.title}\" of the chapter before, "
                        "so the line goes on there.")
        return L

    def resumable(self, run, active):
        """An earlier line of the chapter that the run continues: its main line
        ends just before the run's first move, the run reads cleanly from
        there, and no word ("Or", "Instead", "If", "After") or bracket makes
        it an alternative. When a diagram stands in between, the choice of
        the starting position (choose_start) decides instead.""" 
        if run.depth > 0 or self.pending_header is not None or run.ply is None:
            return None
        if _ALT_LEAD_RE.search(self.lead_text(run.start, 60)):
            return None
        # moves named inside a sentence ("... after 9 b3 d4! you have to ask") are no resumption
        i = self.line_index(self.st, run.start)
        if i >= 0:
            before = self.st.orig_text[self.st.lines[i].start:run.start]
            if any(len(w) >= 3 and w.isalpha() and not _shape(w) for w in before.split()):
                return None
        # the line the open one interrupted (the line just before it), or the
        # line closed last when none is open: a digression stands between
        # one line and its continuation, not between several
        if active is not None:
            k = self.lines.index(active)
            before = [M for M in self.lines[:k] if M.chapter == self.ci and M.end_offset is not None
                      and M.born != "note"]
            cands = before[-1:]
        else:
            cands = [self.last_closed] if self.last_closed is not None else []
        for M in cands:
            if M.chapter != self.ci or M is active or M.end_offset is None:
                continue
            if M.waiting or M.broken or not M.last_fen or M.next_ply != run.ply:
                continue
            toks = _first_moves(run.tokens, 4)
            if _fit(self.dec.run(M.last_fen, toks))[0] != 0:
                continue
            # a diagram printed in between governs the moves after it (see
            # choose_start, which weighs it against the line before)
            last = max(M.last_token_end, self.last_token_end)
            if any(last < doff < run.start and self.diagram_selected(did)
                   and not self.not_a_board(did) for doff, did in self.diagram_events):
                return None
            return M
        return None

    def reopen(self, L, run):
        """Open a closed line again for a run that continues its main line
        after other text (see from_diagram). The text between its last move
        and the run stays the comment of that move unless another line
        stands between them."""
        others = [M for M in self.lines if M is not L and M.chapter == L.chapter
                  and L.last_token_end < M.first_offset < run.start]
        if others:
            L.consumed.append((L.end_offset or L.last_token_end, self.para_start_of(run.start)))
        L.end_offset = None
        L.notes = []
        L.hold = L.close_at = None
        self.last_closed = None
        return L

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
            self.checkpoints(L)
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

    def checkpoints(self, L):
        """Diagrams printed around the line that show a position its main line
        reaches: the diagram is a checkpoint inside the line, and its
        after_node becomes that move, whatever the text position suggested."""
        reached = {}
        for nid in L.main_nodes[1:]:
            fen = self.nodes[nid]["fen"]
            if fen and self.nodes[nid]["status"] != "failed":
                reached.setdefault(fen.split(" ")[0], nid)
        if not reached:
            return
        lo = L.first_offset
        before = [doff for doff, _ in self.diagram_events if doff <= lo]
        if before:
            lo = before[-min(len(before), 3)]        # pictures set before the moves
        hi = (L.end_offset if L.end_offset is not None else L.last_token_end) + 1
        for doff, did in self.diagram_events:
            if not lo <= doff <= hi or did == L.diagram or did in self.checked:
                continue
            fen = self.diagram_fens.get(did)
            nid = reached.get(fen.split(" ")[0]) if fen else None
            if nid is not None:
                self.after_node[did] = nid
                self.checked[did] = nid

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
        for _, _, nid in main:
            self.nodes[nid]["comment"] = ""     # a reopened line gets its comments anew
        for (s, e, nid), nxt in zip(main, main[1:] + [None]):
            b = nxt[0] if nxt else (L.end_offset if L.end_offset is not None else e)
            c = extract(e, b, first_para=nxt is None)
            if c:
                node = self.nodes[nid]
                node["comment"] = (node["comment"] + " " + c).strip() if node["comment"] else c

    # -------------------------------------------------------- the reader's corrections
    #
    # A line keeps the steps that built it as ops: ("main", run) appended a
    # run to its main line, ("gap", run, P, follow) marked moves missing from
    # the text, ("notes",) began placing its notes, ("note", run, as_main,
    # block, cue, side) placed a note run as a variation, ("unplaced", run,
    # reason) left a run in no line. The text decided these steps; the moves
    # are decoded again whenever the line is replayed. finalize() keeps the
    # assembled lines as the base, derives from it the lines that the
    # reader's corrections ask for (a run placed elsewhere, a line split or
    # joined) and replays them with the corrected moves, piece symbols and
    # diagram positions. apply_fix() does the same for one changed set of
    # corrections and replays only the lines whose ops or moves it touches,
    # so that the result is always that of a fresh build.

    def snapshot(self):
        """Keep the assembled lines, before any correction, as the base."""
        comments, roots = {}, {}
        for n in self.nodes.values():
            if n.get("key") and n["comment"]:
                comments.setdefault(n["key"], n["comment"])
        for L in self.lines:
            roots[L.id] = self.nodes[L.root]["comment"]
            L.base_result = L.result

        def key(nid):
            n = self.nodes.get(nid)
            if n is None:
                return None
            return n.get("key") or ("root", n["line"]) if n["parent"] is None else n.get("key")
        self.base = {
            "lines": [(L, list(L.ops), dict(L.spec)) for L in self.lines],
            "unplaced": list(self.unplaced_runs),
            "comments": comments, "roots": roots,
            "after": {did: key(nid) for did, nid in self.after_node.items()},
            "checked": {did: key(nid) for did, nid in self.checked.items()},
            "last_key": {L.id: self.nodes[L.main_nodes[-1]].get("key")
                         for L in self.lines if len(L.main_nodes) > 1},
        }
        self.decoders = {(): self.dec}
        self.derived = {}
        self.split_lines = {}
        self.stale = set()

    def decoder_for(self, glyph_fix):
        k = tuple(sorted(glyph_fix.items()))
        dec = self.decoders.get(k)
        if dec is None:
            base = self.decoders[()]
            dec = self.decoders[k] = _Decoder(base.glyphs, base.letters, dict(glyph_fix))
        return dec

    @staticmethod
    def op_runs(op):
        """The runs an op holds."""
        if op[0] in ("main", "gap", "note", "unplaced", "dismiss", "attach", "long"):
            return [op[1]]
        if op[0] == "graft":
            return [r for sub in op[2] for r in _Builder.op_runs(sub)]
        return []

    @staticmethod
    def op_sig(op):
        """What an op depends on, for telling whether a line changed."""
        def rs(r):
            return (r.ci, r.start, r.end, len(r.tokens))
        if op[0] == "graft":
            return ("graft", op[1], tuple(_Builder.op_sig(o) for o in op[2]))
        return (op[0],) + tuple(rs(x) if isinstance(x, _Run) else
                                (tuple(sorted(x.items())) if isinstance(x, dict) else x)
                                for x in op[1:])

    def find_token(self, key, runs):
        """(index into runs, token index) of the move token that key names,
        among runs (a list of _Run), or None. Tokens may move by a fraction
        of a point between builds (corrections.TOLERANCE)."""
        try:
            page, x, y, raw = fixes.parse_key(key)
        except ValueError:
            return None
        best = None
        for i, r in enumerate(runs):
            for j, t in enumerate(r.tokens):
                if t.kind != "move":
                    continue
                pg, box = self.place_of(t, r.ci)
                if pg != page or box is None:
                    continue
                d = max(abs(box[0] - x), abs(box[1] - y))
                if d > fixes.TOLERANCE:
                    continue
                rank = (t.raw.replace(" ", "") != raw.replace(" ", ""), d)
                if best is None or rank < best[0]:
                    best = (rank, i, j)
        return best and best[1:]

    @staticmethod
    def cut_run(run, j):
        """(the part of run before token j, the part from token j on); either may be None."""
        toks = run.tokens
        # a move number printed before the move goes with it
        k = j
        while k > 0 and toks[k - 1].kind == "number":
            k -= 1

        def part(ts):
            ms = [t for t in ts if t.kind == "move"]
            if not ms:
                return None
            return replace(run, tokens=ts, moves=ms, start=ts[0].start, end=ts[-1].end,
                           ply=_ply(ms[0]), result=run.result if ts[-1] is toks[-1] else None,
                           text=_tokens_text(ts))
        return part(toks[:k]), part(toks[k:])

    def derive(self, fix):
        """The lines as the corrections ask for them: [(line, ops)], and the
        sequences placed in no line [(run, reason)] and dismissed
        [(run, fields)]. A line split from another carries spec
        {"after": line id} or the diagram it starts from."""
        recs = []
        for L, ops, spec in self.base["lines"]:
            if L.spec is not spec:
                L.spec = dict(spec)
            recs.append([L, list(ops)])
        glob = [[run, entry["reason"]] for entry, run in self.base["unplaced"]]
        dismissed = []
        moved = set()
        # lines that go on from a line of the chapter before (chapter_join)
        by_id = {rec[0].id: rec for rec in recs}
        for rec in list(recs):
            prev = getattr(rec[0], "joins", None)
            target = by_id.get(prev.id) if prev is not None else None
            if target is None or not target[0].main_nodes:
                continue
            key = self.base["last_key"].get(prev.id)
            if key:
                recs.remove(rec)
                target[1].append(("graft", key, rec[1], None))

        def where(key):
            """("line", rec, op index, token index) or ("glob", index, token index)."""
            cands = []
            for rec in recs:
                for oi, op in enumerate(rec[1]):
                    if op[0] in ("main", "note", "unplaced", "long"):
                        cands.append((("line", rec, oi), op[1]))
            for gi, g in enumerate(glob):
                if g is not None:
                    cands.append((("glob", gi), g[0]))
            hit = self.find_token(key, [r for _, r in cands])
            if hit is None:
                return None
            (loc, _), j = cands[hit[0]], hit[1]
            return loc + (j,)

        # sequences placed in no line: dismissed, or tied to a move of a line
        for key, v in sorted((fix.get("unattached") or {}).items()):
            loc = where(key)
            if loc is None:
                continue
            if loc[0] == "glob":
                run = glob[loc[1]][0]
                if run.moves[0] is not run.tokens[loc[2]]:
                    continue
                glob[loc[1]] = None
            else:
                rec, oi = loc[1], loc[2]
                op = rec[1][oi]
                if op[0] not in ("note", "unplaced") or op[1].moves[0] is not op[1].tokens[loc[3]]:
                    continue
                run = op[1]
                rec[1][oi] = ("skip",)
            if v["attach_to"] == "dismiss":
                dismissed.append((run, {"_fix": key}))
                continue
            tgt = where(v["attach_to"])
            if tgt is None or tgt[0] != "line":
                glob.append([run, "you tied it to a move that the program no longer finds"])
                continue
            tgt[1][1].append(("attach", run, v["attach_to"]))
        # lines split at a move, and runs taken out of a line
        n_split = defaultdict(int)
        for key, v in sorted((fix.get("disconnect") or {}).items()):
            loc = where(key)
            if loc is None or loc[0] != "line":
                continue
            rec, oi, j = loc[1], loc[2], loc[3]
            L, ops = rec
            op = ops[oi]
            if op[0] in ("note", "unplaced"):
                if v.get("remove"):
                    ops[oi] = ("unplaced", op[1], "you marked these moves as not part of the line")
                continue
            if op[0] != "main":
                continue
            head, tail = self.cut_run(op[1], j)
            rest_main = [o for o in ops[oi + 1:] if o[0] in ("main", "gap")]
            later = [o for o in ops[oi + 1:] if o[0] not in ("main", "gap")]
            keep = ops[:oi] + ([("main", head)] if head is not None else [])
            if v.get("remove"):
                toks = list(tail.tokens) + [t for o in rest_main if o[0] == "main"
                                            and o[1].ci == tail.ci for t in o[1].tokens]
                ms = [t for t in toks if t.kind == "move"]
                gone = replace(tail, tokens=toks, moves=ms, end=toks[-1].end,
                               text=_tokens_text(toks))
                rec[1] = keep + later
                glob.append([gone, "you marked these moves as not part of the line"])
                continue
            # a new line from this move on, with the notes printed after it
            n_split[L.id] += 1
            new_id = f"{L.id}-{n_split[L.id]}"
            def before(o):
                rs = self.op_runs(o)
                return bool(rs) and (rs[0].ci, rs[0].start) < (tail.ci, tail.start)
            mine = [o for o in later if o[0] == "notes" or before(o)]
            theirs = [o for o in later if o[0] == "notes" or not before(o)]
            rec[1] = keep + mine
            label = (f"{tail.moves[0].number}{'...' if tail.moves[0].black else '.'}"
                     if tail.moves[0].number is not None else "")
            spec = {"after": L.id}
            did = v.get("start")
            if did and did != "here":
                spec = {"diagram": did, "ply": tail.ply if tail.ply is not None else 0}
            L2 = self.split_lines.get(new_id)
            if L2 is None:
                L2 = self.split_lines[new_id] = _Line(
                    new_id, "fragment", "", L.chapter, 0, "", None, False, None, L.section,
                    None, tail.start, 0, None, L.born)
            L2.title = f"{L.title} (from move {label})"
            L2.page = self.place_of(tail.tokens[0], tail.ci)[0] or L.page
            L2.diagram = spec.get("diagram")
            L2.first_offset = tail.start
            L2.spec = spec
            L2.split_from = L.id
            recs.insert(recs.index(rec) + 1, [L2, [("main", tail)] + rest_main + theirs])
        # runs that continue a line after a move the reader chose
        for key, v in sorted((fix.get("connect") or {}).items()):
            loc = where(key)
            tgt = where(v["after"])
            if loc is None or tgt is None or tgt[0] != "line":
                continue
            if loc[0] == "glob":
                sub = [("main", glob[loc[1]][0])]
                head, tail = self.cut_run(sub[0][1], loc[2])
                if tail is None:
                    continue
                if head is not None:
                    glob[loc[1]][0] = head
                else:
                    glob[loc[1]] = None
                sub = [("main", tail)]
            else:
                rec, oi, j = loc[1], loc[2], loc[3]
                ops = rec[1]
                op = ops[oi]
                if rec is tgt[1] and op[0] == "main":
                    continue                # a line cannot continue itself
                if op[0] in ("note", "unplaced"):
                    ops[oi] = ("skip",)
                    sub = [("main", op[1])]
                elif op[0] == "main":
                    head, tail = self.cut_run(op[1], j)
                    first = all(o[0] not in ("main", "gap") for o in ops[:oi]) and head is None
                    rest = [o for o in ops[oi + 1:]]
                    sub = [("main", tail)] + [o for o in rest if o[0] in ("main", "gap")]
                    notes = [o for o in rest if o[0] not in ("main", "gap")]
                    if first:
                        sub += notes
                        recs.remove(rec)        # the whole line goes on from the move chosen
                        moved.add(rec[0].id)
                    else:
                        rec[1] = ops[:oi] + ([("main", head)] if head is not None else []) + notes
                else:
                    continue
            # the join goes right after the step that placed the move chosen,
            # so that the moves printed after it (a numbered run after a
            # bare move) find the line gone on when their turn comes
            tops = tgt[1][1]
            at = tgt[2] + 1 if tops[tgt[2]][0] in ("main", "note") else len(tops)
            tops.insert(at, ("graft", v["after"], sub, key))
        globs = [(g[0], g[1]) for g in glob if g is not None]
        return [(rec[0], rec[1]) for rec in recs], globs, dismissed

    # ---------------- replaying
    def drop_line(self, lid):
        """Remove a line's nodes, marks, waiting entry and the sequences its
        notes left in no line."""
        for nid in self.by_line.pop(lid, []):
            n = self.nodes.pop(nid, None)
            if n is not None and n.get("key") and self.node_by_key.get(n["key"]) == nid:
                del self.node_by_key[n["key"]]
        for page in self.line_pages.pop(lid, ()):
            self.marks[page] = [m for m in self.marks[page]
                                if m["line"] != lid and m.get("_src") != lid]
        self.unattached = [u for u in self.unattached if u.get("_src") != lid]
        self.dismissed = [u for u in self.dismissed if u.get("_src") != lid]
        self.attached = [u for u in self.attached if u.get("_src") != lid]
        self.waiting = [w for w in self.waiting if w.get("line") != lid]

    def root_fen(self, L):
        """The position a replayed line starts from, or None (unknown)."""
        spec = L.spec
        if "after" in spec:
            src = self.line_by_id.get(spec["after"])
            last = src.main_nodes[-1] if src is not None and src.main_nodes else None
            return self.nodes[last]["fen"] if last and last in self.nodes else None
        did = spec.get("diagram")
        if did and did in self.fix_diagrams:
            b = chess.Board(self.fix_diagrams[did])
            ply = spec.get("ply") or 0
            b.turn = chess.BLACK if ply % 2 else chess.WHITE
            b.ep_square = None
            b.fullmove_number = ply // 2 + 1
            return b.fen()
        if did and spec.get("fen") is None and "fen" not in spec:
            return self.diagram_fen(did, _Run("main", [], [], 0, 0, 0, spec.get("ply"), None))
        return spec.get("fen")

    def replay_line(self, L):
        """Build the nodes of a line again from its ops, with the corrections."""
        self.drop_line(L.id)
        self.replaying = True
        fen = self.root_fen(L)
        L.nseq = 0
        L.main_tok, L.main_nodes, L.ply_node, L.notes = [], [], {}, []
        L.variations, L.broken, L.result = 0, False, L.base_result
        L.waiting = fen is None
        L.start_fen = fen
        first = next((r for o in L.ops for r in self.op_runs(o)), None)
        start_ply = _board_ply(fen) if fen else L.spec.get("ply", 0) or 0
        L.next_ply, L.last_fen = start_ply, fen
        self.ci = first.ci if first is not None else L.chapter
        root = self.new_node(L, fen=fen, status="waiting" if L.waiting else "root", main=True,
                             page=L.page, comment=self.base["roots"].get(L.id, ""))
        L.root = root
        L.main_nodes.append(root)
        L.ply_node[start_ply - 1] = root
        if L.waiting and first is not None:
            self.waiting.append({"page": L.page, "chapter": L.chapter, "text": self.run_text(first),
                                 "reason": WAIT_REASON, "line": L.id,
                                 "diagram": L.spec.get("diagram")})
        if getattr(L, "split_from", None):
            L.first_split = True
        self.run_ops(L, L.ops)
        self.replaying = False
        self.finish_replayed(L)

    def run_ops(self, L, ops):
        state = {"vars": defaultdict(list), "last": None}
        for op in ops:
            kind = op[0]
            runs = self.op_runs(op)
            if runs:
                self.ci = runs[0].ci
            if kind == "main":
                n0 = len(L.main_nodes)
                self.extend(L, op[1])
                if getattr(L, "first_split", False) and len(L.main_nodes) > n0:
                    self.set_corrected(L.main_nodes[n0], "split")
                    L.first_split = False
            elif kind == "gap":
                self.gap(L, op[1], op[2], op[3])
            elif kind == "notes":
                state = {"vars": defaultdict(list), "last": None}
            elif kind in ("note", "unplaced", "dismiss", "long"):
                self.do_note(L, op, state)
            elif kind == "attach":
                self.do_attach(L, op[1], op[2])
            elif kind == "graft":
                self.do_graft(L, op, state)

    def target_node(self, L, key):
        """The node of line L whose move token key names, or None."""
        try:
            page, x, y, _ = fixes.parse_key(key)
        except ValueError:
            return None
        best = None
        for nid in self.by_line.get(L.id, []):
            n = self.nodes[nid]
            k = n.get("key")
            if not k:
                continue
            p2, x2, y2, _ = fixes.parse_key(k)
            d = max(abs(x2 - x), abs(y2 - y))
            if p2 == page and d <= fixes.TOLERANCE and (best is None or d < best[0]):
                best = (d, nid)
        return best and best[1]

    def set_corrected(self, nid, what):
        n = self.nodes[nid]
        n["corrected"] = what
        for m in self.marks.get(n["page"], []):
            if m["node"] == nid:
                m["corrected"] = what

    def do_attach(self, L, run, target):
        """A sequence the reader tied to a move of this line: an alternative
        to that move, or else the moves that follow it, whichever reads
        legally (and better)."""
        run = self.forced(run)
        nid = self.target_node(L, target)
        best = None
        if nid is not None and not L.waiting:
            node = self.nodes[nid]
            for parent in (node["parent"], nid):
                if parent is None or not self.nodes[parent]["fen"]:
                    continue
                decs = self.dec.run(self.nodes[parent]["fen"], run.tokens)
                f = _fit(decs)
                if f[0] <= 1 and (best is None or f < best[0]):
                    best = (f, parent, decs)
        if best is None:
            why = ("you tied it to a move that the program no longer finds" if nid is None else
                   "its moves are not legal at the move you tied it to")
            self.unplaced(run, why, src=L)
            return
        _, parent, decs = best
        nodes = self.insert_decoded(L, parent, run, decs)
        L.variations += 1
        if nodes:
            self.set_corrected(nodes[0], "placed")
        page, box = self.place_of(run.moves[0], run.ci)
        self.attached.append({"page": page, "chapter": run.ci, "text": self.run_text(run),
                              "reason": "", "key": fixes.token_key(page, box, run.moves[0].raw)
                              if box else None, "bbox": box, "_src": L.id,
                              "node": nodes[0] if nodes else None})

    def named_piece(self, tok, d):
        """True when the move reads with the piece the reader named for its
        symbol (the decoder's glyph, or the symbol the page shows for it)."""
        if d.glyph and d.glyph in self.fix_glyphs:
            return True
        piece = self.fix_glyphs.get(junk_prefix(tok.raw, self.dec.letters))
        if not piece or not d.san:
            return False
        return d.san[0] == piece if piece in "KQRBN" else d.san[0] not in "KQRBNO"

    def shown_move(self, raw):
        """A printed move as the reader would write it, where it can be read."""
        sym = junk_prefix(raw, self.dec.letters)
        if sym and sym in self.fix_glyphs:
            p = self.fix_glyphs[sym]
            raw = ("" if p == "P" else p) + raw[len(sym):]
        return readable_move(raw, self.dec.glyphs, self.dec.letters) or _shown(raw)

    def move_words(self, nid):
        n = self.nodes[nid]
        if n["parent"] is None:
            return "the start of the line"
        return f"{n['number']}{'...' if n['black'] else '.'}{n['san'] or _shown(n['raw'])}"

    def do_graft(self, L, op, state=None):
        """Runs that the reader said continue this line after one of its moves:
        the main line goes on with them when that move ends it, and they form
        a variation from that move otherwise (and a note run that continues
        their numbering goes on with them, state). Moves that are not legal
        there are placed in no line, with the reason."""
        _, target, sub, src_key = op
        nid = self.target_node(L, target)
        mains = [o[1] for o in sub if o[0] == "main"]
        if not mains:
            return
        run0 = self.forced(mains[0])

        def refuse(why):
            for o in sub:
                if o[0] in ("main", "note", "unplaced"):
                    self.unplaced(o[1], why, src=L)
        if nid is None:
            refuse("you joined it to a move that the program no longer finds")
            return
        fen = self.nodes[nid]["fen"]
        if not fen:
            refuse(f"the position after {self.move_words(nid)} is unknown, so its moves cannot "
                   "be checked there")
            return
        decs = self.dec.run(fen, run0.tokens)
        if not decs or decs[0].status == "failed" or _fit(decs)[0] == 2:
            shown = self.shown_move(run0.moves[0].raw)
            side = "Black" if chess.Board(fen).turn == chess.BLACK else "White"
            refuse(f"its first move, {shown}, is not a legal move for {side} after "
                   f"{self.move_words(nid)}")
            return
        if nid == L.main_nodes[-1] and not L.broken:
            n0 = len(L.main_nodes)
            self.run_ops(L, sub)
            if len(L.main_nodes) > n0 and src_key:
                self.set_corrected(L.main_nodes[n0], "connected")
            return
        # a variation from the move chosen: the runs read as one sequence
        toks = [t for r in mains for t in self.forced(r).tokens if r.ci == run0.ci]
        whole = replace(run0, tokens=toks, moves=[t for t in toks if t.kind == "move"],
                        end=toks[-1].end)
        decs = self.dec.run(fen, whole.tokens)
        nodes = self.insert_decoded(L, nid, whole, decs)
        L.variations += 1
        if nodes and src_key:
            self.set_corrected(nodes[0], "connected")
        if state is not None and nodes and not self.nodes[nid]["main"]:
            plies = {}
            for n in nodes:
                ply = self.node_ply(n)
                if ply is not None:
                    plies[ply] = n
            block = bisect.bisect_left([s_ for s_, _, _ in L.main_tok], whole.start)
            state["vars"][block].append({"depth": run0.depth, "plies": plies, "last": nodes[-1],
                                         "next": (max(plies) + 1) if plies else None,
                                         "bracket": run0.bracket, "end": whole.end})

    def finish_replayed(self, L):
        """Status and pages of a replayed line, and the comments of the
        assembled book on its moves."""
        comments = self.base["comments"]
        for nid in self.by_line.get(L.id, []):
            n = self.nodes[nid]
            if n.get("key") and n["parent"] is not None:
                n["comment"] = comments.get(n["key"], "")
        if L.waiting:
            L.status = "waiting"
        else:
            worst = max([_LINE_RANK.get(self.nodes[n]["status"], 0) for n in L.main_nodes[1:]],
                        default=0)
            L.status = {0: "ok", 1: "guessed", 2: "ambiguous", 3: "failed"}[worst]
            if len(L.main_nodes) <= 1:
                L.status = "failed"
        pages = [self.nodes[n]["page"] for n in L.main_nodes[1:]
                 if self.nodes[n]["page"] and self.nodes[n].get("key")]
        L.end_page = max(pages + [L.page])

    def apply_fix(self, fix, chapters=None, window=None):
        """Apply a set of corrections to the assembled book: derive the lines
        they ask for and replay those that changed. chapters limits the
        replay of lines whose moves change through a piece symbol to those
        chapters (the others wait for a later call); window limits it further
        to the lines that start within that many pages of the first such
        line (a small batch). Returns {"lines":
        replayed line ids, "removed": line ids, "pages": pages whose marks
        changed, "pending": chapters still to replay}."""
        fix = fixes.normalise(fix) if fix is not None else fixes.empty()
        old = self.fix
        self.fix = fix
        self.fix_moves = fixes.TokenIndex(fix["moves"])
        self.fix_gaps = fixes.TokenIndex(fix["gaps"])
        self.fix_glyphs = dict(fix["glyphs"])
        self.fix_diagrams = {did: v["fen"] for did, v in fix["diagrams"].items()}
        self.dec = self.decoder_for(self.fix_glyphs)
        derived, globs, dismissed = self.derive(fix)
        first = not self.derived
        prev = self.derived
        lines = [L for L, _ in derived]
        sigs = {}
        for L, ops in derived:
            sigs[L.id] = (tuple(self.op_sig(o) for o in ops),
                          tuple(sorted((k, v) for k, v in L.spec.items() if k != "fen")))
        removed = [lid for lid in prev if lid not in sigs]
        # which lines the changed moves, symbols and positions touch
        touched = set()
        changed_keys = {k for part in ("moves", "gaps") for k in set(old[part]) | set(fix[part])
                        if old[part].get(k) != fix[part].get(k)}
        changed_glyphs = {g for g in set(old["glyphs"]) | set(fix["glyphs"])
                          if old["glyphs"].get(g) != fix["glyphs"].get(g)}
        changed_diagrams = {d for d in set(old["diagrams"]) | set(fix["diagrams"])
                            if old["diagrams"].get(d) != fix["diagrams"].get(d)}
        pending = set()
        if not first:
            for L, ops in derived:
                runs = [r for o in ops for r in self.op_runs(o)]
                if changed_diagrams and L.spec.get("diagram") in changed_diagrams:
                    touched.add(L.id)
                if changed_keys:
                    for k in changed_keys:
                        if self.find_token(k, runs) is not None:
                            touched.add(L.id)
                if changed_glyphs and any(junk_prefix(t.raw, self.dec.letters) in changed_glyphs
                                          for r in runs for t in r.moves):
                    self.stale.add(L.id)
                if L.spec.get("after") in touched:
                    touched.add(L.id)
        due = sorted(L.page for L, ops in derived if L.id in self.stale
                     and (chapters is None or L.chapter in chapters))
        limit = due[0] + window if (due and window) else None
        for L, ops in derived:
            if L.id in self.stale:
                if (chapters is None or L.chapter in chapters) and (limit is None or L.page < limit):
                    touched.add(L.id)
                    self.stale.discard(L.id)
                else:
                    pending.add(L.chapter)
        self.line_by_id = {L.id: L for L in lines}
        todo = [L for L, ops in derived
                if first or prev.get(L.id) != sigs[L.id] or L.id in touched
                or (L.spec.get("after") and prev.get(L.spec["after"]) != sigs.get(L.spec["after"]))]
        for L, ops in derived:
            L.ops = ops
        for lid in removed:
            self.drop_line(lid)
        if first:
            self.nodes, self.by_line, self.line_pages = {}, defaultdict(list), defaultdict(set)
            self.node_by_key = {}
            self.waiting, self.attached = [], []
            self.marks = defaultdict(list)
            self.unattached = []
        # the sequences placed in no line, and those the reader dismissed
        pages = set()
        for page in list(self.marks):
            ms = self.marks[page]
            keep = [m for m in ms if not (m["node"] is None and m.get("_src") is None)]
            if len(keep) != len(ms):
                pages.add(page)
            self.marks[page] = keep
        self.unattached = [u for u in self.unattached if u.get("_src") is not None]
        self.dismissed = [u for u in self.dismissed if u.get("_src") is not None]
        self.replaying = True
        for run, reason in globs:
            self.unplaced(run, reason)
        for run, extra in dismissed:
            self.unplaced(run, None, dismiss=extra)
        self.replaying = False
        for u in self.unattached + self.dismissed:
            if u.get("_src") is None and u.get("page"):
                pages.add(u["page"])
        self.lines = lines
        for L in todo:
            before = set(self.line_pages.get(L.id, ()))
            self.replay_line(L)
            pages |= before | set(self.line_pages.get(L.id, ()))
        # diagrams that the text ties to a move, as the assembled book had them
        for name in ("after", "checked"):
            out = {}
            for did, key in self.base[name].items():
                if isinstance(key, tuple):
                    L = self.line_by_id.get(key[1])
                    nid = L.root if L is not None else None
                else:
                    nid = self.node_by_key.get(key)
                if nid is not None and nid in self.nodes:
                    out[did] = nid
            if name == "after":
                self.after_node = out
            else:
                self.checked = out
        self.derived = sigs
        return {"lines": [L.id for L in todo], "removed": removed, "pages": sorted(pages),
                "pending": sorted(pending)}

    def finalize(self, fix):
        """Keep the assembled lines as the base and apply the corrections."""
        self.snapshot()
        return self.apply_fix(fix)

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
                "start_note": L.start_note, "_offset": L.first_offset})
        return out


# ---------------------------------------------------------------- top level

def _assemble(doc, fonts, chapters, diagrams, selection, glyphs, letters, diagram_fens, only=None,
              dotless=False, readings=None, fix=None):
    """One assembly pass. The corrections (fix) are not used here: the
    caller applies them with _Builder.finalize."""
    b, dec, _ = _drain(_assemble_steps(doc, fonts, chapters, diagrams, selection, glyphs, letters,
                                       diagram_fens, only, dotless, readings))
    return b, dec


CHAPTER_SLICE = 0.5     # seconds of a chapter's assembly per step of build_steps


def _assemble_steps(doc, fonts, chapters, diagrams, selection, glyphs, letters, diagram_fens,
                    only=None, dotless=False, readings=None, ctx=None, pass_no=None, shapes=None):
    """_assemble in steps: yields ("chapter", (pass_no, chapter index)) after
    each chapter, with ctx["builder"] the builder at work, and when ctx is
    given, ("part", (pass_no, chapter index)) inside a chapter about every
    CHAPTER_SLICE seconds. shapes gives the pieces read from the figurines'
    pictures (figshapes.py). Returns (builder, decoder, seconds spent in the
    pass)."""
    dec = _Decoder(glyphs, letters)
    b = _Builder(doc, fonts, chapters, diagrams, selection, dec, diagram_fens, dotless, readings,
                 shapes=shapes)
    if ctx is not None:
        ctx["builder"] = b
    seconds = 0.0
    for ci, ch in enumerate(chapters):
        if ch["end"] < ch["start"]:
            continue
        if only is not None and ci not in only:
            continue
        t = time.perf_counter()
        for _ in b.chapter_steps(ci, ch, CHAPTER_SLICE if ctx is not None else None):
            seconds += time.perf_counter() - t
            yield "part", (pass_no, ci)
            t = time.perf_counter()
        seconds += time.perf_counter() - t
        yield "chapter", (pass_no, ci)
    return b, dec, seconds


def read_boards(doc, diagrams, known=None, say=None):
    """Stage 3's readings of the book's boards ({id: reading}), or {} when
    the board reader cannot run (OpenCV missing)."""
    return _drain(read_boards_steps(doc, diagrams, known, say, batch=1 << 30))


BOARD_BATCH = 20        # board pictures per step of read_boards_steps


def read_boards_steps(doc, diagrams, known=None, say=None, batch=BOARD_BATCH):
    """read_boards in steps: yields ("boards", (pictures done, pictures))
    after each batch of pictures; the readings that need the whole book
    (the piece drawings grouped and named) come in the last step."""
    try:
        from . import boards
    except ImportError as exc:          # pragma: no cover - depends on the platform
        (say or (lambda *_: None))(f"board reading skipped: {exc}")
        return {}
    t = time.perf_counter()
    if any(d.get("boards") for d in diagrams):
        diagrams = sel.expand_boards(diagrams)
    ids = sel.diagram_ids(diagrams)
    pics = boards.Pictures(doc)
    cells = {}
    for j in range(0, len(ids), batch):
        for did, rec in zip(ids[j:j + batch], diagrams[j:j + batch]):
            cells[did] = boards.picture_cells(pics, rec)
        if len(ids) > batch:
            yield "boards", (min(j + batch, len(ids)), len(ids))
    out = boards.read_book_boards(doc, diagrams, known=known, progress=say, cells=cells)
    if say:
        n = sum(1 for r in out.values() if r.get("fen"))
        say(f"boards read in {time.perf_counter() - t:.1f} s: {n} positions")
    return out


def read_shapes_steps(doc, builder, say=None, old=None):
    """Read the figurines of the book's moves by their shape (figshapes.py):
    cut them out where builder found them (unless old, a figshapes.Shapes of
    the same book, holds the cuts already), group them and name the groups
    from the moves builder read with certainty. Yields ("shapes", (pages
    done, pages)) while cutting; returns the Shapes, or None when the book
    prints its pieces as letters or figurine characters, or when OpenCV is
    missing."""
    try:
        from . import figshapes
    except ImportError as exc:          # pragma: no cover - depends on the platform
        (say or (lambda *_: None))(f"figurine shapes skipped: {exc}")
        return None
    spots = builder.spots
    if not figshapes.worth_reading(spots, builder.move_tokens):
        return None
    t = time.perf_counter()
    if old is None:
        masks = yield from figshapes.cut_steps(doc, spots)
        shapes = figshapes.Shapes(masks)
    else:
        shapes = old
    shapes.name(figshapes.votes_from_nodes(shapes.keys, builder.nodes, builder.node_by_key))
    if say:
        named = shapes.reading()
        sure = sum(1 for v in named.values() if v[1] >= figshapes.CONFIDENT)
        say(f"figurines read in {time.perf_counter() - t:.1f} s: {len(spots)} symbols, "
            f"{len(shapes.keys)} cut out, {len(named)} named ({sure} surely), "
            f"{len(shapes.groups)} groups")
    return shapes


def shape_disagreements(shapes, spots, glyphs):
    """[(symbol, piece the glyph model reads, piece the shape shows, times)]
    for the symbols whose learnt reading the figurines' pictures contradict."""
    out = Counter()
    for key, (piece, conf) in shapes.reading().items():
        sym = spots.get(key, (None, None, None))[2]
        if not sym or not glyphs.strong(sym):
            continue
        pri = glyphs.prior(sym)
        learnt = max(pri, key=pri.get)
        if learnt != piece:
            out[(sym, learnt, piece)] += 1
    return [(a, b, c, n) for (a, b, c), n in out.most_common()]


def usable_fens(readings):
    """The FENs of readings that make a position with one king of each colour."""
    out = {}
    for did, r in readings.items():
        fen = r.get("fen")
        if not fen:
            continue
        b = chess.Board(fen)
        if len(b.pieces(chess.KING, chess.WHITE)) == 1 and len(b.pieces(chess.KING, chess.BLACK)) == 1:
            out[did] = fen
    return out


def build_book(pdf_path, output_dir=None, books_dir=None, letters=None, passes=3,
               diagram_fens=None, write=True, progress=None, boards=True, readings=None,
               corrections=None, state=None, shapes=True):
    """Assemble the whole book and write output/<stem>/book.json.

    letters names a movetext.LETTER_SETS entry (default English; figurines are
    always read). diagram_fens maps diagram ids to FENs read by Stage 3; lines
    that start from those diagrams are then decoded instead of waiting. When
    it is not given and boards is true, Stage 3 (boards.py) reads the board
    pictures after the first pass, using the positions that the first pass
    decoded at diagrams as known examples, and the later passes use its FENs.
    passes is the number of assembly passes (the glyph model of each pass is
    learnt from the runs the previous pass decoded cleanly). When shapes is
    true, the figurines printed as OCR junk in the moves are read by their
    pictures after each pass but the last (figshapes.py, read_shapes_steps),
    and the later passes use the pieces they show. readings may give
    Stage 3's readings (doubtful squares, sides to move) of the diagrams whose
    FENs diagram_fens supplies. corrections holds the reader's corrections
    (corrections.py); by default they are read from
    books/<stem>/corrections.json. A diagram's corrected position wins over
    every reading of it, a corrected move token reads as the move given, a
    corrected piece symbol reads as its piece throughout the book, and a
    sequence placed in no line goes where the reader tied it.

    build_steps does the same work in small steps (the browser app).
    """
    book = _drain(build_steps(pdf_path, output_dir, books_dir, letters, passes, diagram_fens,
                              progress, boards, readings, corrections, state, shapes=shapes))
    if write:
        out = Path(output_dir or OUTPUT_DIR) / Path(pdf_path).stem / "book.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(book, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    return book


def build_steps(pdf_path, output_dir=None, books_dir=None, letters=None, passes=3,
                diagram_fens=None, progress=None, boards=True, readings=None,
                corrections=None, state=None, ctx=None, shapes=True):
    """build_book in small steps, for a caller with other work to do between
    them (the browser app reads chapters while the book is assembled, see
    progressive.py). A generator: it yields (event, info) after each step
    and returns the book (as build_book does, without writing it). The
    events are "structure" (the layout and the chapters are known), "stage1"
    ((pages inspected, pages)), "diagrams" (Stage 1 is complete), "chapter"
    ((pass, chapter index), after each chapter of each assembly pass), "part"
    (the same, inside a chapter, about every CHAPTER_SLICE seconds),
    "boards" ((pictures read, pictures)), "shapes" ((pages of figurines
    cut out, pages), see read_shapes_steps), "pass" (pass number, after each
    pass) and "restructure" (the figurines were learnt and the book is read
    again from the start, its chapters perhaps changed).

    ctx, a dict, receives what the build knows at each step: doc, fonts,
    structure, chapters, numbering, the Stage 1 findings so far
    ("stage1_found", page index -> stage1_inspect.inspect_page) or the
    diagrams once complete, selection, text_fens, diagram_fens, readings,
    glyphs (the glyph model of the pass at work), shapes (the figurines read
    by their shape, a figshapes.Shapes, once read), builder and pass_no. The
    caller may set ctx["first_pages"] (a callable giving the page numbers
    Stage 1 is to inspect first) and ctx["fix"] (the corrections to apply at
    the end, in place of corrections); neither changes the result otherwise.
    """
    ctx = {} if ctx is None else ctx
    t0 = time.perf_counter()
    pdf_path = Path(pdf_path)
    out_root = Path(output_dir or OUTPUT_DIR)
    say = progress or (lambda *_: None)
    doc = pymupdf.open(pdf_path)
    fonts = pt.book_fonts(doc)
    structure = pt.book_structure(doc)
    chapters = book_chapters(structure, doc.page_count)
    numbering = book_numbering(doc)
    ctx.update(pdf=pdf_path, books_dir=books_dir, letters=letters, doc=doc, fonts=fonts,
               structure=structure, chapters=chapters, numbering=numbering,
               glyphs=GlyphModel(), readings=dict(readings or {}), pass_no=0, builder=None,
               stage1_found={}, diagrams=None)
    yield "structure", None
    # a picture of stacked boards counts as one diagram per board
    raw = yield from load_stage1_steps(
        pdf_path, out_root, doc.page_count,
        first=lambda: (ctx.get("first_pages") or (lambda: []))(), found=ctx["stage1_found"])
    diagrams = sel.expand_boards(raw)
    # Diagrams printed as text in a chess font carry their position already.
    text_fens = {did: d["fen"] for did, d in zip(sel.diagram_ids(diagrams), diagrams)
                 if d.get("fen")}
    # Stage 3 reads the pictures unless the caller supplied the positions;
    # positions printed as text always win, since they are exact.
    read_now = diagram_fens is None and boards
    fix = fixes.normalise(corrections) if corrections is not None else \
        fixes.load(pdf_path, books_dir)
    if text_fens or diagram_fens is not None:
        diagram_fens = {**(diagram_fens or {}), **text_fens}
    selection = sel.load_selection(pdf_path, structure, diagrams, books_dir)
    ctx.update(diagrams=diagrams, text_fens=text_fens, diagram_fens=diagram_fens,
               selection=selection)
    say(f"layout and structure read in {time.perf_counter() - t0:.1f} s; move numbers "
        f"{'without' if numbering['dotless'] else 'with'} dots")
    yield "diagrams", None
    glyphs = GlyphModel()
    timings = []
    readings = dict(readings or {})
    if read_now and passes <= 1:
        readings = yield from read_boards_steps(doc, diagrams, say=say)
        diagram_fens = {**usable_fens(readings), **text_fens}
        read_now = False
        ctx.update(readings=readings, diagram_fens=diagram_fens)
    figmap, learnt = {}, {}
    shapes_on = shapes
    shapes_read, shapes, use_shapes = None, {}, shapes_on
    fig_cands = figurines.candidates(
        (pt._raw_page(doc, i) for i in range(doc.page_count)),
        {f["font"] for f in fonts.get("figurines") or []})
    k = 0
    while k < max(1, passes):
        if read_now and k == 1:
            # positions the first pass reached at diagrams teach the reader
            known = {did: builder.nodes[nid]["fen"] for did, nid in builder.after_node.items()
                     if builder.nodes.get(nid, {}).get("fen")}
            readings = yield from read_boards_steps(doc, diagrams, known=known, say=say)
            diagram_fens = {**usable_fens(readings), **text_fens}
            read_now = False
            ctx.update(readings=readings, diagram_fens=diagram_fens)
        if k >= 1 and use_shapes:
            # the figurines' pictures, named from the moves the pass before
            # read with certainty (cut out once, named again after each pass)
            shapes_read = yield from read_shapes_steps(doc, builder, say, shapes_read)
            shapes = shapes_read.reading() if shapes_read is not None else {}
            use_shapes = shapes_read is not None
            ctx.update(shapes=shapes_read)
        ctx.update(glyphs=glyphs, pass_no=len(timings) + 1, first_pass=(k == 0))
        builder, dec, secs = yield from _assemble_steps(
            doc, fonts, chapters, diagrams, selection, glyphs, letters, diagram_fens,
            dotless=numbering["dotless"], readings=readings, ctx=ctx, pass_no=len(timings) + 1,
            shapes=shapes)
        timings.append(round(secs, 1))
        say(f"pass {len(timings)}: {len(builder.lines)} lines, {len(builder.nodes)} nodes, "
            f"{dec.calls} decodes in {timings[-1]} s")
        yield "pass", len(timings)
        if k + 1 < passes or fig_cands:
            learned = GlyphModel()
            for decs in dec.accepted:
                learned.learn_run(decs)
            if k + 1 < passes:
                glyphs = learned
        if fig_cands:
            # Piece figurines printed as private codes: learn which piece
            # each code stands for (over more passes while some code is
            # still unknown), give the letters in the text and read the
            # book again from the start.
            figmap, learnt = figurines.book_map(fig_cands, figurines.code_counts(dec.accepted))
            if len(learnt) < len(fig_cands) and k + 1 < passes:
                k += 1
                continue
            fig_cands = None
            if figmap:
                pt.set_figurine_map(doc, figmap)
                fonts = pt.book_fonts(doc)
                structure = pt.book_structure(doc)
                chapters = book_chapters(structure, doc.page_count)
                selection = sel.load_selection(pdf_path, structure, diagrams, books_dir)
                say(f"read {len(figmap)} figurine codes as piece letters; reading again")
                glyphs = GlyphModel()
                shapes_read, shapes, use_shapes = None, {}, shapes_on
                ctx.update(fonts=fonts, structure=structure, chapters=chapters,
                           selection=selection, figmap=figmap)
                yield "restructure", None
                k = 0
                continue
        k += 1
    if ctx.get("fix") is not None:
        fix = fixes.normalise(ctx["fix"])
    # the reader's corrections, applied by replaying the lines they touch
    builder.finalize(fix)
    book = _book_dict(pdf_path, doc, chapters, diagrams, selection, builder, glyphs, structure,
                      readings, fix, letters)
    book["numbering"] = numbering
    if shapes_read is not None:
        disagree = shape_disagreements(shapes_read, builder.spots, glyphs)
        if disagree:
            say("figurine shapes that contradict the learnt symbols: " + ", ".join(
                f"{a!r} {b}->{c} x{n}" for a, b, c, n in disagree[:8]))
        book["shapes"] = {
            "symbols": len(builder.spots), "cut": len(shapes_read.keys),
            "named": len(shapes), "sure": sum(1 for v in shapes.values()
                                              if v[1] >= SHAPE_KNOWN),
            "groups": [{"piece": p, "confidence": c, "how": h, "size": n, "votes": v}
                       for p, c, h, n, v in shapes_read.summary()],
            "disagree": [{"symbol": a, "learnt": b, "shape": c, "count": n}
                         for a, b, c, n in disagree],
            "tokens": {k: [p, c] for k, (p, c) in sorted(shapes_read.by_key.items())}}
    book["figurines"] = [{"font": f, "code": f"U+{ord(ch):04X}", "piece": p,
                          "learnt": (f, ch) in learnt}
                         for (f, ch), p in sorted(figmap.items())]
    if state is not None:
        # what the browser app keeps to apply later corrections live (live.py)
        state.update(builder=builder, doc=doc, chapters=chapters, diagrams=diagrams,
                     selection=selection, glyphs=glyphs, structure=structure, readings=readings,
                     letters=letters, pdf=pdf_path)
    book["stats"]["seconds"] = round(time.perf_counter() - t0, 1)
    book["stats"]["pass_seconds"] = timings
    return book


def book_numbering(doc):
    """How the book numbers its moves, learnt from its text: {"dotless": True when
    it prints numbers without a dot ("1 e4 c5 2 Nf3"), "counts": the clean
    dotless and dotted examples found (movetext.numbering_counts)}."""
    counts = numbering_counts(page.get_text() for page in doc)
    dotless = counts["dotless"] >= DOTLESS_MIN and counts["dotless"] >= DOTLESS_SHARE * counts["dotted"]
    return {"dotless": dotless, "counts": counts}


TITLE_PAGES = 5            # pages searched for the title page
TITLE_BODY_RATIO = 1.5     # a title is printed at least this much larger than the body text
_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "of",
                "on", "or", "the", "to", "vs", "with"}
_NOT_TITLES = re.compile(r"(?i)^(?:contents|table of contents|introduction|foreword|preface|"
                         r"bibliography|index|acknowledge?ments|symbols|by|about the authors?)\b|"
                         r"www\.|\.com\b|©|\bisbn\b")
_META_JUNK = re.compile(r"(?i)^(?:microsoft\s+word|word|untitled|document\d*)\s*-\s*|"
                        r"\.(?:docx?|pdf|rtf|odt|indd)$")


def _title_case(part):
    """A part of a title in the case of a title: every word but the short ones
    ("of", "by") starts with a capital, so that "THE ART OF" and "move by
    move" read "The Art of" and "Move by Move". Words with a capital or a
    digit inside ("McDonald", "e4") stay as printed."""
    if part.isupper():
        part = part.lower()
    out = []
    for i, w in enumerate(part.split()):
        if w == w.lower() and not any(c.isdigit() for c in w) and (not i or w not in _SMALL_WORDS):
            w = w[:1].upper() + w[1:]
        out.append(w)
    return " ".join(out)


def _join_title(title, subtitle=""):
    title, subtitle = _title_case(title.strip(" :")), _title_case(subtitle.strip())
    return f"{title}: {subtitle}" if subtitle else title


def _title_page(doc):
    """The title as the title page prints it: the largest line of type on the
    first pages (headings such as "Contents" and addresses aside), printed
    clearly larger than the body text, with the lines of the same size right
    below it ("THE ART OF" over "PLANNING IN CHESS") and a smaller line close
    under them as the subtitle ("move by move"). None when no page has one."""
    body = pt._ctx(pt._fonts_internal(doc)).body_size
    best = None
    for i in range(min(doc.page_count, TITLE_PAGES)):
        lines = []
        for b in doc[i].get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                text = " ".join("".join(sp["text"] for sp in l["spans"]).split())
                if sum(c.isalpha() for c in text) < 2:
                    continue
                size = max(sp["size"] for sp in l["spans"])
                lines.append((l["bbox"][1], l["bbox"][3], size, text))
        lines.sort()
        for k, (y0, y1, size, text) in enumerate(lines):
            if size < TITLE_BODY_RATIO * body or _NOT_TITLES.search(text):
                continue
            if best is None or size > best[0] + 0.5:
                best = (size, i, k, lines)
    if best is None:
        return None
    size, _, k, lines = best
    parts, bottom = [lines[k][3]], lines[k][1]
    sub = ""
    for y0, y1, sz, text in lines[k + 1:]:
        gap = y0 - bottom
        if abs(sz - size) <= 0.5 and gap <= 0.6 * size and not _NOT_TITLES.search(text):
            parts.append(text)
            bottom = y1
            continue
        if (sz < size and sz >= 0.5 * size and gap <= 0.6 * size
                and not _NOT_TITLES.search(text) and len(text) <= 60):
            sub = text
        break
    title = " ".join(parts)
    return _join_title(title, sub) if len(title) <= 120 else None


def _file_title(stem):
    """A title made from the file's name: "Brunthaler, Heinz - My daily
    exercise" gives "My Daily Exercise", and an author's names before an
    article ("lakdawala_cyrus_the_alekhine_defence") are left out."""
    name = stem.replace("_", " ").replace("+", " ")
    if " - " in name:
        name = name.split(" - ", 1)[1]
    words = name.split()
    for i in range(1, min(4, len(words))):
        if words[i].lower() in ("the", "a", "an"):
            words = words[i:]
            break
    return _title_case(" ".join(words).lower()) or stem


def _book_title(doc, structure, pdf_path):
    """The book's title in words: the title the PDF records (without the
    "Microsoft Word - " that some converters put before it), else the title
    page's (_title_page), else one made from the file's name."""
    t = (doc.metadata or {}).get("title") or ""
    t = _META_JUNK.sub("", _META_JUNK.sub("", t.strip())).strip()
    if t and "_" not in t and t.lower() != pdf_path.stem.lower():
        return t
    return _title_page(doc) or _file_title(pdf_path.stem)


def _diagram_reading(did, fen, reading, corrected=False):
    """The fields of a diagram in book.json that describe its position:
    status "read" (a position is in use), "doubtful" (in use, with doubtful
    squares), "corrected" (the reader gave the position), "partial" (the
    picture shows part of a board only) or "unread"."""
    reading = reading or {}
    out = {"fen": fen or None, "status": "unread"}
    if corrected:
        out["status"] = "corrected"
        out["corrected"] = True
    elif fen:
        out["status"] = "doubtful" if reading.get("doubtful") else "read"
    elif reading.get("status") == "partial":
        out["status"] = "partial"
    if reading.get("fen"):
        out["reading"] = {k: reading.get(k) for k in ("fen", "confidence", "doubtful", "turn",
                                                        "turn_from", "flipped")}
    return out


def _symbol_counts(book_marks, letters, fixed, glyphs=None):
    """{symbol: times printed} for every piece symbol of the book's move tokens
    that is neither a letter of the notation nor a figurine. With the book's
    glyph model, a mark whose symbol the book has taught well (the same junk
    read nearly always as one piece) is marked "known": the reader puts no
    eye on it, since a doubt about such a move is not about its piece."""
    out = Counter()
    for marks in book_marks.values():
        for m in marks:
            sym = junk_prefix(m["raw"], letters)
            if sym:
                out[sym] += 1
                m["symbol"] = sym
                if glyphs is not None and _symbol_known(glyphs, m["raw"], sym):
                    m["known"] = True
    return out


def _symbol_known(glyphs, raw, sym):
    """True when the glyph model trusts its reading of the symbol, or of the
    symbol with the capture sign after it that the book prints as part of
    the piece ("E:" for the rook in "E:h7#")."""
    if glyphs.strong(sym):
        return True
    k = raw.find(sym)
    nxt = raw[k + len(sym):k + len(sym) + 1] if k >= 0 else ""
    return bool(nxt) and nxt in CAPTURE_CHARS and glyphs.strong(sym + nxt)


def _book_dict(pdf_path, doc, chapters, diagrams, selection, b, glyphs, structure, readings=None,
               fix=None, letters=None):
    fix = fix or fixes.empty()
    symbols = _symbol_counts(b.marks, letters, fix["glyphs"], glyphs)
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
        marks = page_marks(b, p)
        pages.append({
            "page": p, "folio": _folio(p, b.folio_offset),
            "width": round(r.width, 1), "height": round(r.height, 1),
            "chapter": chapter_of.get(p), "selected": b.selection.page_selected(p),
            "diagrams": [{"id": did, "rect": d["rect"], "label": d.get("label"),
                          "kind": kinds.get(did), "selected": b.selection.diagram_selected(did),
                          **_diagram_reading(did, b.fix_diagrams.get(did) or b.diagram_fens.get(did),
                                             (readings or {}).get(did), did in fix["diagrams"]),
                          "after_node": b.after_node.get(did), "checked": did in b.checked,
                          "lines": diagram_lines.get(did, [])}
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
    for n in b.nodes.values():
        what = CORRECTED_COUNTS.get(n.get("corrected"))
        if what:
            counts[line_chapter[n["line"]]]["corrected"][what] += 1
    for u in b.dismissed + b.attached:
        counts[u["chapter"]]["corrected"]["sequences"] += 1
    for p in pages:
        if p["chapter"] in counts:
            for d in p["diagrams"]:
                if d.get("corrected"):
                    counts[p["chapter"]]["corrected"]["diagrams"] += 1
    for w in b.waiting:
        counts[w["chapter"]]["waiting"] += 1
    out_chapters = []
    for c in chapters:
        cc = dict(c)
        k = counts[c["index"]]
        k["line_status"] = dict(k["line_status"])
        k["moves"] = {s: k["moves"].get(s, 0) for s in STATUSES}
        k["corrected"] = dict(k["corrected"])
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
        for s, v in k["corrected"].items():
            total["corrected"][s] += v
    total["moves"] = dict(total["moves"])
    total["line_status"] = dict(total["line_status"])
    total["corrected"] = dict(total["corrected"])
    total["corrected"]["symbols"] = len(fix["glyphs"])
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
        "unattached": public_list(b.unattached),
        "dismissed": public_list(b.dismissed),
        "attached": public_list(b.attached),
        "waiting": public_list(b.waiting),
        "letters": letters or "English",
        "symbols": dict(symbols.most_common()),
        "corrections": fix,
        "stats": total,
    }


def _empty_counts():
    return {"lines": 0, "games": 0, "fragments": 0, "line_status": Counter(),
            "moves": Counter(), "variations": 0, "variation_moves": 0, "unattached": 0,
            "waiting": 0, "corrected": Counter({"moves": 0, "symbol_moves": 0, "diagrams": 0,
                                                "sequences": 0, "connections": 0, "splits": 0,
                                                "gap_moves": 0})}


def _public(entry):
    """A builder record without its private fields (those starting with _)."""
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def public_list(entries):
    """Records of sequences or waiting lines in reading order, without their
    private fields: the same order however the corrections were applied."""
    def key(u):
        box = u.get("bbox") or [0, 0]
        return (u.get("chapter") or 0, u.get("page") or 0, round(box[1]), round(box[0]),
                u.get("text") or "", u.get("line") or "")
    return [_public(u) for u in sorted(entries, key=key)]


def page_marks(b, page):
    """The marks of a page for book.json, in reading order."""
    return [_public(m) for m in sorted(b.marks.get(page, []), key=lambda m: m["_o"])]


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
