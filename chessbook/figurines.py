"""Piece figurines that a PDF's text layer gives as private codes.

Books typeset with ChessBase or similar figurine fonts (font names such as
"CBArialLink", "FigurineCB", "ChessBase", "DiagramTT", "Merida", "Alpha" or
"Zurich") print each piece as a glyph whose character code means nothing to
a reader of the text: usually a code from the Unicode private use area
(U+E000 to U+F8FF), sometimes a plain letter in a font of its own. The text
layer then reads "Nxe6" as "\\ue028xe6", and the move decoder has to guess
the piece.

The mapping from code to piece differs between fonts, so it is learnt per
book (learn_map): the assembler decodes the book once, code_counts()
records which piece each code stood for in the runs that read as real play,
and a code that stood for one piece nearly every time is mapped to
that piece's letter. pdftext then gives the letter in place of the code
(pdftext.set_figurine_map), so every later stage reads "Nxe6".

candidates() lists the codes worth learning: private-use characters printed
in front of a square, and any character of a font that the book uses only
for single figurines in front of squares (pdftext's "figurine" fonts).
Letters and symbols of ordinary text fonts are never touched, so OCR junk in
scanned books and the piece letters of other languages stay as printed.

KNOWN holds conventions of common figurine fonts. It serves only for codes
that the book gives too few decodable moves to learn.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

PIECE_LETTERS = "KQRBNP"
MIN_USES = 3                # decoded moves a code must stand in before it is mapped
MIN_SHARE = 0.85            # share of those moves that must agree on one piece

_MOVE_NO_RE = re.compile(r"^(?:\d{1,3}\s?(?:\.\.\.|…|\.)|\.\.\.|…)")
_TAIL_RE = re.compile(r"^[a-h]?[1-8]?[x:×]?[a-h][1-8]")

# Private-use codes that makers of figurine fonts gave the pieces, with the
# font names they apply to. ChessBase's figurine fonts (the "CB...Link"
# fonts that ChessBase and Fritz embed in exported PDFs) place King, Queen,
# Rook, Bishop and Knight at U+E024 to U+E028.
KNOWN = {
    "chessbase": {"": "K", "": "Q", "": "R", "": "B", "": "N"},
}
_KNOWN_FONT = {"chessbase": re.compile(r"(?i)chessbase|^cb.*link|figurinecb")}


def is_private(ch):
    return 0xE000 <= ord(ch) <= 0xF8FF or 0xF0000 <= ord(ch) <= 0x10FFFF


def font_base(name):
    """'AMAGAN+CBArialLink' -> 'CBArialLink' (subset prefixes dropped)."""
    return name.split("+", 1)[1] if "+" in name[:8] else name


def _word_chars(line):
    """[[(char, font)]] for each word of a pdftext raw line."""
    words, cur = [], []
    for s in line["spans"]:
        for ch in s["text"]:
            if ch.isspace() or ch == "\xa0":
                if cur:
                    words.append(cur)
                    cur = []
            else:
                cur.append((ch, s["font"]))
    if cur:
        words.append(cur)
    return words


def candidates(raw_pages, figurine_fonts=()):
    """{(font, char): uses in front of a square} for the codes worth learning.

    raw_pages: pdftext raw pages (dicts with "lines"). figurine_fonts: names
    of the fonts that book_fonts found used only for single figurines."""
    figurine_fonts = set(figurine_fonts)
    uses, total = Counter(), Counter()
    for raw in raw_pages:
        for ln in raw["lines"]:
            for w in _word_chars(ln):
                for ch, font in w:
                    total[(font, ch)] += 1
                text = "".join(c for c, _ in w)
                m = _MOVE_NO_RE.match(text)
                k = m.end() if m else 0
                if k >= len(w):
                    continue
                ch, font = w[k]
                if _TAIL_RE.match(text[k + 1:]):
                    uses[(font, ch)] += 1
    out = {}
    for (font, ch), n in uses.items():
        if ch in PIECE_LETTERS or ch in "abcdefgh":
            continue
        if not (is_private(ch) or font in figurine_fonts):
            continue
        if n >= MIN_USES and n >= 0.5 * total[(font, ch)]:
            out[(font, ch)] = n
    return out


def code_counts(runs):
    """{printed piece glyph: Counter(piece)} from decoded runs (lists of
    movetext.Decoded) that read as real play: few failed moves, and the
    first move read. Each move that the run's reading settled ("ok" or
    "guessed") counts for the piece that moved."""
    from .movetext import _san_piece, clean_run
    out = defaultdict(Counter)
    for decs in runs:
        if not clean_run(decs, max_failed=0.1, max_mean_cost=3.0):
            continue
        for d in decs:
            if d.san and d.glyph and d.status in ("ok", "guessed"):
                out[d.glyph.replace(" ", "")][_san_piece(d.san)] += 1
    return out


def learn_map(cands, glyph_counts):
    """{(font, char): piece letter} from a glyph model's counts.

    glyph_counts: {junk prefix: Counter(piece: weight)} (code_counts() or
    GlyphModel.counts).
    A prefix that is the code alone, or the code and a capture mark, counts
    for the code. Codes with too little or mixed evidence are left out."""
    by_char = defaultdict(Counter)
    for prefix, c in glyph_counts.items():
        p = prefix.replace(" ", "")
        if len(p) == 2 and p[1] in "x:×":
            p = p[0]
        if len(p) == 1:
            by_char[p].update(c)
    out = {}
    for font, ch in cands:
        c = by_char.get(ch)
        if not c:
            continue
        n = sum(c.values())
        piece, k = c.most_common(1)[0]
        if n >= MIN_USES and k >= MIN_SHARE * n and piece in PIECE_LETTERS:
            out[(font, ch)] = piece
    # One piece per code and one code per piece within a font.
    seen = defaultdict(set)
    for (font, ch), piece in sorted(out.items(), key=lambda t: -sum(by_char[t[0][1]].values())):
        if piece in seen[font]:
            del out[(font, ch)]
        else:
            seen[font].add(piece)
    return out


def known_map(cands):
    """{(font, char): piece letter} for candidates that a known font
    convention covers."""
    out = {}
    for font, ch in cands:
        for conv, pat in _KNOWN_FONT.items():
            if pat.search(font_base(font)) and ch in KNOWN[conv]:
                out[(font, ch)] = KNOWN[conv][ch]
    return out


def book_map(cands, glyph_counts):
    """The learnt mapping, completed by the known conventions for codes the
    book did not teach (a learnt piece always wins)."""
    learnt = learn_map(cands, glyph_counts)
    taken = {(font, piece) for (font, _), piece in learnt.items()}
    out = {k: v for k, v in known_map(cands).items() if (k[0], v) not in taken}
    out.update(learnt)
    return out, learnt
