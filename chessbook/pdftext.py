"""Text, layout and structure of a chess book PDF.

Three entry points serve the later stages and the book reader:

    book_fonts(doc)                    font roles and page layout learnt from the book
    page_lines(doc, page_index, fonts) the lines of one page in reading order, with roles
    book_structure(doc)                chapters, their page ranges and their sections

Each accepts an open pymupdf.Document or a path. Nothing in this module knows a
particular book: the body font, the font that main-line moves are set in,
heading fonts, the bands that hold running heads and page numbers, the gutter
between columns and the column edges are learnt from statistics over every
page. Results are cached on the document, so later calls are fast.

A line dict from page_lines has these fields:

    page    1-based PDF page number
    bbox    [x0, y0, x1, y1] in PDF points, origin top left, tight around the type
    text    the line's words joined by single spaces
    role    one of ROLES:
              head         running head or page number
              coord        board furniture: file letters and rank numbers beside a
                           board picture, or OCR junk read from the picture itself
              label        diagram number above or beside a board (Stage 1 logic),
                           including circled numbers
              caption      short centred line just under a board ("White to move")
              moves        line set in the move font: main-line moves
              text         body text and notes (notes may contain moves)
              heading      chapter or section title (large type or capitals)
              game_header  players and event, e.g. "Alekhine - N.N., New York 1924"
              blank        nothing but punctuation
    col     1 = left column, 2 = right column, 0 = a page set in one column, a
            block that spans both columns, or a running head
    spans   [{text, font, size, bbox, role}]: the PDF spans; text keeps its own
            spaces, and role is the font's role from book_fonts ("text" for the
            body font, "moves", "heading", "coord", "figurine" or "other")
    words   [{text, bbox, xs}]: one entry per word, so that a reader can lay a
            clickable box over a single move; xs holds the left edge of each
            character and, last, the right edge of the word
    diagram only on label, caption and coord lines: the id "p{page}-{k}" of the
            board picture the line belongs to (k counts pictures on the page in
            Stage 1 order)

Text in OCR'd books carries junk where figurines stood, and some of that junk
is made of control characters that Python treats as white space ("\x1d",
"\t"). page.get_text("words") and str.split() would break words there, so words
are built from character boxes and split on real spaces only. line["text"] is
the words joined by single spaces: use line["text"].split(" "), never
str.split().
"""
from __future__ import annotations

import copy
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pymupdf

try:
    import stage1_inspect as _s1
except ImportError:  # the package was imported from outside the project root
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import stage1_inspect as _s1

LABEL_RE, DIGIT_FIX, RESULTS, CIRCLE_RE = _s1.LABEL_RE, _s1.DIGIT_FIX, _s1.RESULTS, _s1.CIRCLE_RE
label_for, between_boards, FULL_PAGE = _s1.label_for, _s1.between_boards, _s1.FULL_PAGE
continues_as_move = _s1.continues_as_move

ROLES = ("head", "coord", "label", "caption", "moves", "text", "heading", "game_header", "blank")

# Piece letters in the order King, Queen, Rook, Bishop, Knight. Figurines are
# accepted in every notation. The move parser chooses one of these sets.
NOTATIONS = {
    "en": ("K", "Q", "R", "B", "N"),
    "de": ("K", "D", "T", "L", "S"),
    "fr": ("R", "D", "T", "F", "C"),
    "es": ("R", "D", "T", "A", "C"),
    "nl": ("K", "D", "T", "L", "P"),
    "ru": ("Кр", "Ф", "Л", "С", "К"),
}
FIGURINES = "♔♕♖♗♘♙♚♛♜♝♞♟"

_FLAGS = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
# Real spaces only: OCR junk for figurines includes \x1d and \t, which
# str.split() and page.get_text("words") would treat as word breaks.
SPACES = " \xa0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"
_SPACE_SET = frozenset(SPACES)
COORD_CHARS = frozenset("abcdefgh12345678")
SIZE_TOL = 0.04          # sizes of one font within 4 % are one size
HEAD_ZONE = 0.13         # running heads and page numbers lie in the top or bottom 13 %

# ---------------------------------------------------------------- tokens

_LEAD_STRIP = "([{\"'«“‘"
_TRAIL_PUNCT = "!?+#†‡±∓∞=)]},.;:»”’\"'"
_MOVE_NO_RE = re.compile(r"^(?:\d[0-9lIO]{0,2}|[lI][0-9lIO]?)\s*(?:\.{1,3}|…)")
_SQUARE_RE = re.compile(r"[a-h£][1-8](?:=[^\s=]{1,4}|[A-ZА-Я♔-♟]|\([A-ZА-Я♔-♟]\))?$")
# OCR reads the rank digit 1 as l or I and 8 as B; accepted only after junk.
_SQUARE_OCR_RE = re.compile(r"[a-h£][lIB]$")
_CASTLE_RE = re.compile(r"^[0O]-[0O](?:-[0O])?$")
_RESULT_RE = re.compile(r"^(?:[1l]-0|0-[1l]|1/2-1/2|½-½)$")


def _strip_trailing(t):
    while True:
        s = t.rstrip(_TRAIL_PUNCT)
        s = re.sub(r"(?<=[1-8lB])t{1,2}$", "", s)   # OCR prints the check sign + as t
        if s == t:
            return s
        t = s


def token_kind(tok):
    """Classify one word: "move" (move number, move, castling, result),
    "word" (anything with letters that is not a move) or "neutral"
    (numbers, punctuation, annotation signs, ellipses)."""
    t = tok.strip(SPACES).lstrip(_LEAD_STRIP)
    if not t:
        return "neutral"
    numbered = False
    m = _MOVE_NO_RE.match(t)
    if m:
        rest = t[m.end():].strip(SPACES)
        if not rest.strip(".…"):
            return "move"                      # "12." "16..." "lO."
        t, numbered = rest, True
    core = _strip_trailing(t)
    if not core or re.fullmatch(r"\.{2,}|…", core):
        return "move" if numbered else "neutral"
    if _RESULT_RE.match(core) or _CASTLE_RE.match(core):
        return "move"
    if 0 < len(core) <= 12:
        if _SQUARE_RE.search(core):
            return "move"
        # "fl" for f1, "fB" for f8: only after a move number or figurine junk.
        if _SQUARE_OCR_RE.search(core) and (numbered or not (core[0].isascii() and core[0].isalpha())):
            return "move"
    if any(ch.isalpha() for ch in core):
        return "word"
    return "neutral"


def is_move_token(tok):
    return token_kind(tok) == "move"


def _coord_token(tok):
    return len(tok) == 1 and tok in COORD_CHARS


def _page_number(text):
    """The page number a running head carries, or None."""
    t = text.strip(SPACES)
    whole = t.replace(" ", "").translate(DIGIT_FIX)
    if whole.isdigit() and len(whole) <= 4 and any(c.isdigit() for c in t):
        return int(whole)
    words = t.split(" ")
    for w in (words[0], words[-1]) if len(words) > 1 else ():
        f = w.translate(DIGIT_FIX)
        if f.isdigit() and len(f) <= 4 and any(c.isdigit() for c in w):
            return int(f)
    return None


def _norm(text):
    return "".join(ch for ch in text.lower() if ch.isalnum())


# ---------------------------------------------------------------- caches

_PATH_DOCS = {}
_CTX_CACHE = []


def _as_doc(doc):
    if isinstance(doc, (str, Path)):
        key = str(Path(doc).resolve())
        if key not in _PATH_DOCS:
            _PATH_DOCS[key] = pymupdf.open(key)
        return _PATH_DOCS[key]
    return doc


_DOC_CACHES = {}


def _cache(doc):
    c = getattr(doc, "_chessbook_cache", None)
    if c is None:
        c = {"raw": {}}
        try:
            doc._chessbook_cache = c
        except AttributeError:
            c = _DOC_CACHES.setdefault(id(doc), (doc, c))[1]
    return c


# ---------------------------------------------------------------- raw pages

def _pictures(page):
    """Board-picture rectangles in Stage 1 order (same filter and sort as
    stage1_inspect.page_pictures, but without the slow image-rect lookup)."""
    area = abs(page.rect)
    out = []
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        if abs(r) / area >= FULL_PAGE:
            continue
        if r.width > 20 and r.height > 20:
            out.append(r)
    mid = page.rect.width / 2
    out.sort(key=lambda r: ((r.x0 + r.x1) / 2 > mid, r.y0))
    return out


def _raw_page(doc, i):
    cache = _cache(doc)["raw"]
    if i in cache:
        return cache[i]
    page = doc[i]
    d = page.get_text("rawdict", flags=_FLAGS)
    lines = []
    for b in d["blocks"]:
        if b.get("type", 0) != 0:
            continue
        for ln in b["lines"]:
            spans, chars = [], []
            for s in ln["spans"]:
                size, base = s["size"], s["origin"][1]
                # ClearScan fonts can claim absurd ascenders (3.3 em), which
                # makes boxes overlap; clamp to sensible proportions.
                asc = min(max(s.get("ascender", 0.8), 0.6), 0.95)
                desc = max(min(s.get("descender", -0.2), -0.1), -0.3)
                bx = s["bbox"]
                y0, y1 = max(bx[1], base - asc * size), min(bx[3], base - desc * size)
                if y1 <= y0:
                    y0, y1 = bx[1], bx[3]
                si = len(spans)
                spans.append({"font": s["font"], "size": size, "y0": y0, "y1": y1, "base": base})
                for c in s["chars"]:
                    chars.append((c["c"], c["bbox"][0], c["bbox"][2], si))
            for group in _split_gaps(chars, spans):
                rl = _make_line(group, spans, ln["bbox"])
                if rl:
                    lines.append(rl)
    raw = {"w": page.rect.width, "h": page.rect.height, "lines": lines, "pics": _pictures(page)}
    cache[i] = raw
    return raw


def _split_gaps(chars, spans):
    """Split a PDF line where a wide horizontal gap shows two columns merged."""
    groups, cur, last_x1 = [], [], None
    for ch in chars:
        c, x0, x1, si = ch
        if c not in _SPACE_SET:
            if last_x1 is not None and x0 - last_x1 > max(3.5 * spans[si]["size"], 25):
                groups.append(cur)
                cur = []
            last_x1 = x1
        cur.append(ch)
    if cur:
        groups.append(cur)
    return groups


def _make_line(chars, spans, line_bbox):
    vis = [c for c in chars if c[0] not in _SPACE_SET]
    if not vis:
        return None
    pieces = []
    for c, x0, x1, si in chars:
        if pieces and pieces[-1]["si"] == si:
            p = pieces[-1]
            p["text"] += c
        else:
            p = {"si": si, "text": c, "x0": None, "x1": None}
            pieces.append(p)
        if c not in _SPACE_SET:
            p["x0"] = x0 if p["x0"] is None else min(p["x0"], x0)
            p["x1"] = x1 if p["x1"] is None else max(p["x1"], x1)
    out_spans = []
    for p in pieces:
        s = spans[p["si"]]
        x0 = p["x0"] if p["x0"] is not None else chars[0][1]
        x1 = p["x1"] if p["x1"] is not None else x0
        out_spans.append({"text": p["text"], "font": s["font"], "size": s["size"],
                          "bbox": [x0, s["y0"], x1, s["y1"]], "base": s["base"],
                          "vis": sum(ch not in _SPACE_SET for ch in p["text"])})
    used = [s for s in out_spans if s["vis"]]
    x0 = min(c[1] for c in vis)
    x1 = max(c[2] for c in vis)
    y0 = min(s["bbox"][1] for s in used)
    y1 = max(s["bbox"][3] for s in used)
    dom = max(used, key=lambda s: s["vis"])
    # Words: split on real spaces only.
    words, cur = [], []
    for ch in chars:
        if ch[0] in _SPACE_SET:
            if cur:
                words.append(cur)
                cur = []
        else:
            cur.append(ch)
    if cur:
        words.append(cur)
    wout = []
    for w in words:
        sis = [c[3] for c in w]
        wy0 = min(spans[si]["y0"] for si in sis)
        wy1 = max(spans[si]["y1"] for si in sis)
        wout.append({"text": "".join(c[0] for c in w), "bbox": [w[0][1], wy0, w[-1][2], wy1],
                     "si": Counter(sis).most_common(1)[0][0],
                     "xs": [c[1] for c in w] + [w[-1][2]]})
    raw_text = "".join(c[0] for c in chars)
    return {"spans": out_spans, "words": wout, "span_src": spans,
            "bbox": [x0, y0, x1, y1], "base": dom["base"],
            "raw_bbox": pymupdf.Rect(min(c[1] for c in chars), line_bbox[1],
                                     max(c[2] for c in chars), line_bbox[3]),
            "raw_text": raw_text.strip(),
            "text": " ".join(w["text"] for w in wout)}


# ---------------------------------------------------------------- fonts

def _cluster_sizes(raw_counts):
    """Map (font, size rounded to 0.1) to (font, cluster size)."""
    by_font = defaultdict(list)
    for (name, size), n in raw_counts.items():
        by_font[name].append((n, size))
    mapping = {}
    for name, items in by_font.items():
        centres = []
        for n, size in sorted(items, reverse=True):
            for c in centres:
                if abs(size - c) <= SIZE_TOL * c:
                    mapping[(name, size)] = (name, c)
                    break
            else:
                centres.append(size)
                mapping[(name, size)] = (name, size)
    return mapping


def _real_word(tok, common):
    """True for a word of three or more letters drawn mostly from the letters
    common in this book's body text (case-insensitive). OCR junk such as
    "Ñåæçèé" fails; hyphenated words count by their parts."""
    for part in re.split(r"[-'’/]", tok.strip(SPACES)):
        core = part.strip("".join(ch for ch in set(part) if not ch.isalpha()))
        if len(core) >= 3 and core.isalpha() and \
                sum(ch.lower() in common for ch in core) * 3 >= 2 * len(core):
            return True
    return False


def _caps(text, least=4):
    """True for text set in capitals. OCR reads some capitals as small
    letters ("BRlliUGNG"), so a few lower-case l, i and ligatures count for
    little."""
    letters = [ch for ch in text if ch.isalpha() and (ch.isupper() or ch.islower())]
    if len(letters) < least:
        return False
    upper = sum(ch.isupper() for ch in letters)
    soft = sum(ch in "liﬁﬂﬀﬃﬄ" for ch in letters)
    return upper >= 0.85 * len(letters) or (upper >= 0.7 * len(letters)
                                            and upper + soft >= 0.9 * len(letters))


def _pic_zone_index(bbox, pics, margin):
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    best = None
    for j, r in enumerate(pics):
        if r.x0 - margin <= cx <= r.x1 + margin and r.y0 - margin <= cy <= r.y1 + margin:
            d = max(r.x0 - cx, 0, cx - r.x1) + max(r.y0 - cy, 0, cy - r.y1)
            if best is None or d < best[0]:
                best = (d, j)
    return None if best is None else best[1]


def _bands(raws, body_size):
    """Learn where running heads and page numbers sit: baseline limits for the
    top band and for the bottom band (None where the book has none).

    A candidate is a line in the top or bottom strip of a page, no larger than
    body text, that is a page number or a text recurring on many pages. A
    group of candidates counts only when it keeps one baseline and is the
    outermost line on its pages, which rules out captions such as "White to
    move" that recur near the foot of a page at varying heights."""
    n = len(raws)
    groups = defaultdict(list)
    for p, raw in enumerate(raws, 1):
        H, lines = raw["h"], raw["lines"]
        if not lines:
            continue
        lo = min(ln["base"] for ln in lines)
        hi = max(ln["base"] for ln in lines)
        for ln in lines:
            y0, y1 = ln["bbox"][1], ln["bbox"][3]
            zone = "top" if y1 < HEAD_ZONE * H else "bot" if y0 > (1 - HEAD_ZONE) * H else None
            if zone is None or _raw_dom_size(ln) > 1.15 * body_size:
                continue
            outer = (ln["base"] <= lo + 0.4 * body_size if zone == "top"
                     else ln["base"] >= hi - 0.4 * body_size)
            num = _page_number(ln["text"])
            if num is not None:
                groups[(zone, "num", p - num)].append((p, ln["base"], outer))
            nt = "".join(ch for ch in ln["text"].lower() if ch.isalpha())
            if len(nt) >= 4:
                groups[(zone, "txt", nt)].append((p, ln["base"], outer))
    bases = {"top": [], "bot": []}
    # The printed page number is the PDF page minus an offset that most
    # running heads agree on (front matter without folios aside).
    offsets = Counter()
    for (zone, kind, off), occ in groups.items():
        if kind == "num":
            offsets[off] += len({o[0] for o in occ})
    folio = None
    if offsets:
        off, cnt = offsets.most_common(1)[0]
        if cnt >= max(3, 0.25 * n):
            folio = off
    for (zone, kind, _), occ in groups.items():
        pages = {o[0] for o in occ}
        if len(pages) < (max(3, 0.1 * n) if kind == "num" else max(4, 0.04 * n)):
            continue
        med = statistics.median(o[1] for o in occ)
        close = [o[1] for o in occ if abs(o[1] - med) <= 1.5]
        if len(close) < 0.7 * len(occ) or sum(o[2] for o in occ) < 0.8 * len(occ):
            continue
        bases[zone] += close
    return {"folio_offset": folio,
            "head_base_max": round(max(bases["top"]) + 0.4 * body_size, 1) if bases["top"] else None,
            "foot_base_min": round(min(bases["bot"]) - 0.4 * body_size, 1) if bases["bot"] else None}


def _raw_dom_size(ln):
    w = Counter()
    for s in ln["spans"]:
        w[s["size"]] += s["vis"]
    return w.most_common(1)[0][0] if w else 0


def _gutter_for(lines_by_page, W):
    """The x of the gap between two columns, or None for one-column pages."""
    w = int(W) + 2
    cov = np.zeros(w + 1)
    for lines in lines_by_page:
        for x0, x1 in lines:
            a, b = max(int(x0), 0), min(int(x1) + 1, w)
            cov[a] += 1
            cov[b] -= 1
    cov = np.cumsum(cov)[:w]
    lo, hi = int(0.3 * W), int(0.7 * W)
    left = cov[int(0.08 * W):int(0.5 * W)].max(initial=0)
    right = cov[int(0.5 * W):int(0.92 * W)].max(initial=0)
    if min(left, right) < 10 or min(left, right) < 0.25 * max(left, right):
        return None
    seg = cov[lo:hi]
    m = seg.min()
    if m > 0.08 * min(left, right):
        return None
    ok = seg <= m + 0.02 * min(left, right)
    best, run_start = None, None
    for x in range(len(ok) + 1):
        if x < len(ok) and ok[x]:
            if run_start is None:
                run_start = x
        elif run_start is not None:
            length = x - run_start
            centre = lo + (run_start + x - 1) / 2
            score = (length, -abs(centre - W / 2))
            if best is None or score > best[0]:
                best = (score, centre)
            run_start = None
    return round(best[1], 1) if best else None


def _compute_fonts(doc):
    n = doc.page_count
    raws = [_raw_page(doc, i) for i in range(n)]
    raw_counts = Counter()
    for raw in raws:
        for ln in raw["lines"]:
            for s in ln["spans"]:
                if s["vis"]:
                    raw_counts[(s["font"], round(s["size"], 1))] += s["vis"]
    if not raw_counts:
        return _empty_fonts(n)
    mapping = _cluster_sizes(raw_counts)
    merged = defaultdict(list)
    for k, v in mapping.items():
        merged[v].append(k[1])
    chars = Counter()
    for k, c in raw_counts.items():
        chars[mapping[k]] += c
    body = max(chars, key=lambda k: (chars[k], -k[1]))
    body_size = body[1]

    def key_of(s):
        return mapping.get((s["font"], round(s["size"], 1)), (s["font"], round(s["size"], 1)))

    letters = Counter()
    for raw in raws:
        for ln in raw["lines"]:
            for s in ln["spans"]:
                if key_of(s) == body:
                    letters.update(ch for ch in s["text"] if ch.isalpha())
    total, acc, common = sum(letters.values()), 0, []
    for ch, c in letters.most_common():
        if total and acc >= 0.999 * total:
            break
        common.append(ch)
        acc += c
    common = list(dict.fromkeys(ch.lower() for ch in common))
    common_set = set(common)

    bands = _bands(raws, body_size)
    stats = defaultdict(lambda: Counter())
    pages_of = defaultdict(set)
    narrow = {0: [], 1: []}
    body_extents = []
    for p, raw in enumerate(raws, 1):
        H, W, pics = raw["h"], raw["w"], raw["pics"]
        page_narrow = []
        for ln in raw["lines"]:
            keys = [key_of(s) for s in ln["spans"]]
            for k, s in zip(keys, ln["spans"]):
                if s["vis"]:
                    stats[k]["spans"] += 1
                    pages_of[k].add(p)
            src = ln["span_src"]
            for w in ln["words"]:
                sp = src[w["si"]]
                k = mapping.get((sp["font"], round(sp["size"], 1)))
                stats[k][token_kind(w["text"])] += 1
            weight = Counter()
            for k, s in zip(keys, ln["spans"]):
                weight[k] += s["vis"]
            dom = weight.most_common(1)[0][0]
            stats[dom]["lines"] += 1
            if dom == body and len(ln["words"]) >= 4:
                body_extents.append((p % 2, ln["bbox"][0], ln["bbox"][2]))
            if _caps(ln["text"]) and any(_real_word(w["text"], common_set) for w in ln["words"]):
                stats[dom]["caps_lines"] += 1
            near = _pic_zone_index(ln["bbox"], pics, 1.6 * body_size) if pics else None
            if near is not None and all(_coord_token(w["text"]) for w in ln["words"]):
                for k, s in zip(keys, ln["spans"]):
                    if s["vis"]:
                        stats[k]["coord_spans"] += 1
            x0, y0, x1, y1 = ln["bbox"]
            in_head = ((bands["head_base_max"] is not None and y1 < HEAD_ZONE * H
                        and ln["base"] <= bands["head_base_max"])
                       or (bands["foot_base_min"] is not None and y0 > (1 - HEAD_ZONE) * H
                           and ln["base"] >= bands["foot_base_min"]))
            vis_chars = sum(s["vis"] for s in ln["spans"])
            if not in_head and near is None and vis_chars >= 3 and x1 - x0 < 0.45 * W:
                page_narrow.append((x0, x1))
        narrow[p % 2].append(page_narrow)

    W0 = raws[0]["w"]
    gut_all = _gutter_for(narrow[0] + narrow[1], W0)
    gutters = {"odd": _gutter_for(narrow[1], W0) or gut_all,
               "even": _gutter_for(narrow[0], W0) or gut_all}

    # Typical width of a full line of body text, in one column and across
    # the page; captions are told from prose by being clearly narrower.
    col_w, page_w = [], []
    for parity, x0, x1 in body_extents:
        g = gutters["odd" if parity else "even"]
        (col_w if g is not None and (x1 <= g + 3 or x0 >= g - 3) else page_w).append(x1 - x0)

    def p90(v):
        v = sorted(v)
        return round(v[int(0.9 * (len(v) - 1))], 1) if len(v) >= 5 else None

    column_width, text_width = p90(col_w), p90(page_w)

    # Text edges of each column, per page parity: [[left, right], ...].
    columns = {}
    for name, parity in (("odd", 1), ("even", 0)):
        g = gutters[name]
        ext = [(x0, x1) for par, x0, x1 in body_extents if par == parity]
        sides = ([[e for e in ext if e[1] <= g + 3], [e for e in ext if e[0] >= g - 3]]
                 if g is not None else [ext])
        cols = []
        for side in sides:
            if len(side) >= 5:
                xs0 = sorted(e[0] for e in side)
                xs1 = sorted(e[1] for e in side)
                cols.append([round(xs0[int(0.05 * (len(xs0) - 1))], 1),
                             round(xs1[int(0.95 * (len(xs1) - 1))], 1)])
        columns[name] = cols

    body_ratio = _move_ratio(stats[body])
    all_moves = sum(st["move"] for st in stats.values())
    moves, headings, coords, figs = [], [], [], []
    for k, st in stats.items():
        if k == body:
            continue
        r = _move_ratio(st)
        if (st["move"] >= max(5, 0.03 * all_moves) and r >= 0.35 and r >= 2 * body_ratio
                and st["coord_spans"] < 0.5 * st["spans"]):
            moves.append(k)
    for k, st in stats.items():
        if k == body or k in moves:
            continue
        if st["spans"] and st["coord_spans"] >= max(5, 0.5 * st["spans"]):
            coords.append(k)
        elif k[1] >= 1.25 * body_size or (st["lines"] >= 2 and st["caps_lines"] >= 0.5 * st["lines"]):
            headings.append(k)
    figs = _figurine_fonts(raws, key_of, body, moves)

    def role(k):
        if k == body:
            return "text"
        for name, group in (("moves", moves), ("coord", coords), ("figurine", figs),
                            ("heading", headings)):
            if k in group:
                return name
        return "other"

    entries = []
    for k in sorted(chars, key=lambda k: -chars[k]):
        st = stats[k]
        entries.append({"font": k[0], "size": k[1], "sizes": sorted(merged[k]), "chars": chars[k],
                        "pages": len(pages_of[k]), "lines": st["lines"], "move_tokens": st["move"],
                        "word_tokens": st["word"], "move_ratio": round(_move_ratio(st), 3),
                        "coord_spans": st["coord_spans"], "caps_lines": st["caps_lines"],
                        "role": role(k)})

    def pack(group):
        return [{"font": k[0], "size": k[1]} for k in sorted(group, key=lambda k: -chars[k])]

    return {
        "version": 1,
        "page_count": n,
        "body": {"font": body[0], "size": body[1]},
        "moves": pack(moves),
        "headings": pack(headings),
        "coords": pack(coords),
        "figurines": pack(figs),
        "common_letters": "".join(common),
        "layout": {"page_width": round(W0, 1), "page_height": round(raws[0]["h"], 1),
                   "head_base_max": bands["head_base_max"],
                   "folio_offset": bands["folio_offset"],
                   "foot_base_min": bands["foot_base_min"],
                   "gutter": gutters,
                   "columns": columns,
                   "column_width": column_width,
                   "text_width": text_width or column_width},
        "fonts": entries,
    }


def _figurine_fonts(raws, key_of, body, moves):
    """Fonts used only for single figurine glyphs inside move text."""
    single, total = Counter(), Counter()
    for raw in raws:
        for ln in raw["lines"]:
            sp = ln["spans"]
            for j, s in enumerate(sp):
                if not s["vis"]:
                    continue
                k = key_of(s)
                if k == body or k in moves:
                    continue
                total[k] += 1
                t = s["text"].strip(SPACES)
                nxt = sp[j + 1]["text"] if j + 1 < len(sp) else ""
                if len(t) == 1 and (t in FIGURINES or re.match(r"[x:]?[a-h][1-8]", nxt)):
                    single[k] += 1
    return [k for k in total if total[k] >= 10 and single[k] >= 0.7 * total[k]]


def _move_ratio(st):
    m, w = st["move"], st["word"]
    return m / (m + w) if m + w else 0.0


def _empty_fonts(n):
    return {"version": 1, "page_count": n, "body": None, "moves": [], "headings": [],
            "coords": [], "figurines": [], "common_letters": "",
            "layout": {"page_width": None, "page_height": None, "head_base_max": None,
                       "folio_offset": None,
                       "foot_base_min": None, "gutter": {"odd": None, "even": None},
                       "columns": {"odd": [], "even": []},
                       "column_width": None, "text_width": None},
            "fonts": []}


def _fonts_internal(doc):
    c = _cache(doc)
    if "fonts" not in c:
        c["fonts"] = _compute_fonts(doc)
    return c["fonts"]


def book_fonts(doc):
    """Font roles and page layout of the whole book, as a JSON-serialisable dict.

    Keys: version, page_count, body {font, size}, moves [{font, size}],
    headings [...], coords [...], figurines [...], common_letters (the lower-case
    letters that make up 99.9 % of body text), layout {page_width, page_height,
    head_base_max, foot_base_min, folio_offset (PDF page minus printed page
    number, or None when the book prints none), gutter {odd, even}, columns {odd, even}
    (text edges [[left, right], ...] of each column), column_width, text_width}
    and fonts (one entry per font name and size cluster with its statistics
    and its role).
    """
    return copy.deepcopy(_fonts_internal(_as_doc(doc)))


class _Ctx:
    """Fast lookups built once from a fonts dict."""

    def __init__(self, fonts):
        self.size_map, self.centres, self.roles = {}, defaultdict(list), {}
        for e in fonts.get("fonts", []):
            k = (e["font"], e["size"])
            self.centres[e["font"]].append(e["size"])
            self.roles[k] = e.get("role", "other")
            for s in e.get("sizes", [e["size"]]):
                self.size_map[(e["font"], round(s, 1))] = k
        b = fonts.get("body")
        self.body = (b["font"], b["size"]) if b else None
        self.body_size = b["size"] if b else 10.0
        self.moves = {(f["font"], f["size"]) for f in fonts.get("moves", [])}
        self.figurines = {(f["font"], f["size"]) for f in fonts.get("figurines", [])}
        self.common = {ch.lower() for ch in fonts.get("common_letters", "")} or set(
            "abcdefghijklmnopqrstuvwxyz")
        lay = fonts.get("layout", {})
        self.head_max = lay.get("head_base_max")
        self.foot_min = lay.get("foot_base_min")
        self.gutter = lay.get("gutter") or {}
        self.column_width = lay.get("column_width")
        self.columns = lay.get("columns") or {}
        self.text_width = lay.get("text_width") or self.column_width

    def key(self, font, size):
        r = round(size, 1)
        k = self.size_map.get((font, r))
        if k:
            return k
        for c in self.centres.get(font, ()):
            if abs(c - size) <= SIZE_TOL * c:
                return (font, c)
        return (font, r)


def _ctx(fonts):
    for f, c in _CTX_CACHE:
        if f is fonts:
            return c
    c = _Ctx(fonts)
    _CTX_CACHE.append((fonts, c))
    del _CTX_CACHE[:-8]
    return c


# ---------------------------------------------------------------- page lines

_NAME = r"[^\W\d_](?:[^\W\d_]|['’.])*"
_NAMES = rf"{_NAME}(?:\s+{_NAME}){{0,6}}"
GAME_HEADER_RE = re.compile(
    rf"^(?P<white>{_NAMES})\s*(?:[-–—]|\s(?:vs?\.?|versus)\s)\s*(?P<black>{_NAMES})"
    rf"\s*(?:[,;]\s*(?P<event>.*?))?\s*(?P<year>(?:1[5-9]|20)\d\d)?\s*[.)]?$")


_YEAR_SPLIT_RE = re.compile(r"(?<![\d\w])([1l])\s?([5-9])\s?(\d)\s?(\d)(?![\d\w])")


def join_year(text):
    """'London 1 921' -> 'London 1921': OCR splits the digits of a year."""
    return _YEAR_SPLIT_RE.sub(lambda m: "1" + m.group(2) + m.group(3) + m.group(4), text)


def _name_side(name):
    words = name.split()
    return name.replace(" ", "") in ("N.N.", "NN.", "N.N") or (
        len(words) >= 2 and all(w[0].isupper() for w in words if w[0].isalpha()))


def _game_header(text, name_font_is_body):
    text = join_year(text)
    m = GAME_HEADER_RE.match(text)
    if not m:
        return False
    white, black = m.group("white"), m.group("black")
    if not (white[0].isupper() and black[0].isupper()):
        return False
    if m.group("year"):
        return True
    if name_font_is_body:
        return False
    if m.group("event"):
        return True
    # "Mikhail Yudovich - N.N.": two names in the heading font, no place
    if _caps(text) or any(ch.isdigit() for ch in text) or len(text.split()) > 7:
        return False
    return _name_side(white.strip()) or _name_side(black.strip())


def _features(rl, ctx):
    keys = [ctx.key(s["font"], s["size"]) for s in rl["spans"]]
    weight, size_w = Counter(), Counter()
    for k, s in zip(keys, rl["spans"]):
        if s["vis"]:
            weight[k] += s["vis"]
            size_w[round(s["size"], 1)] += s["vis"]
    vis = sum(weight.values())
    dom = weight.most_common(1)[0][0]
    fig = sum(v for k, v in weight.items() if k in ctx.figurines)
    mv = sum(v for k, v in weight.items() if k in ctx.moves)
    kinds = Counter(token_kind(w["text"]) for w in rl["words"])
    real = any(_real_word(w["text"], ctx.common) for w in rl["words"])
    return {"keys": keys, "dom": dom, "dom_size": size_w.most_common(1)[0][0],
            "move_share": mv / max(vis - fig, 1), "kinds": kinds, "real": real,
            "caps": _caps(rl["text"]), "vis": vis}


_SECTION_NO_RE = re.compile(r"^(?:\d{1,2}|[IVX]{1,4})\.\s+(?=\S)")


def _is_heading(f, ctx, text):
    if not f["real"] or len(text) > 140:
        return False
    numbered = _SECTION_NO_RE.match(text)
    if numbered:                      # "1. CHECKMATE": the number is not a move
        text = text[numbered.end():]
    moves = f["kinds"]["move"] - (1 if numbered else 0)
    if moves * 2 > max(f["kinds"]["word"], 1):
        return False
    big = f["dom_size"] >= 1.25 * ctx.body_size and f["dom"] not in ctx.moves
    if numbered and not (_caps(text) or big):
        return False
    # a single word in capitals, in a font other than the body's ("PIN")
    short = (len(text.split()) == 1 and _caps(text, least=3) and f["dom"] != ctx.body)
    return f["caps"] or big or short


def _heading_like_big(f, ctx):
    return f["real"] and ((f["caps"] and f["dom_size"] >= 1.1 * ctx.body_size)
                          or f["dom_size"] >= 1.3 * ctx.body_size)


def page_lines(doc, page_index, fonts=None):
    """The lines of one page in reading order: on a two-column page the left
    column top to bottom, then the right column, with blocks that span both
    columns (headings, full-width diagrams) cutting the order where they stand.

    page_index is 0-based; each returned dict has "page" 1-based. fonts is the
    dict from book_fonts (computed and cached when omitted). The module
    documentation lists the fields of a line dict.
    """
    doc = _as_doc(doc)
    if fonts is None:
        fonts = _fonts_internal(doc)
    ctx = _ctx(fonts)
    raw = _raw_page(doc, page_index)
    p = page_index + 1
    W, H, pics = raw["w"], raw["h"], raw["pics"]
    rls = raw["lines"]
    feats = [_features(rl, ctx) for rl in rls]
    role = [None] * len(rls)
    diag = [None] * len(rls)
    bs = ctx.body_size

    # Running heads and page numbers.
    for k, rl in enumerate(rls):
        x0, y0, x1, y1 = rl["bbox"]
        top = ctx.head_max is not None and y1 < HEAD_ZONE * H and rl["base"] <= ctx.head_max
        bot = ctx.foot_min is not None and y0 > (1 - HEAD_ZONE) * H and rl["base"] >= ctx.foot_min
        if (top or bot) and not _heading_like_big(feats[k], ctx):
            role[k] = "head"

    # Diagram labels, exactly as Stage 1 finds them.
    head_y = H * 0.06
    labels = []
    row_texts = [(x["raw_text"], x["raw_bbox"]) for x in rls]
    for k, rl in enumerate(rls):
        if role[k]:
            continue
        t, r = rl["raw_text"], rl["raw_bbox"]
        m = LABEL_RE.match(t.replace(" ", "") if len(t) <= 8 else t)
        if (m and m.group(1) not in RESULTS and (r.y0 + r.y1) / 2 > head_y
                and not any(r.intersects(pc + (-12, -4, 12, 4)) and not between_boards(r, pc)
                            for pc in pics)
                and not continues_as_move(r, row_texts)):
            labels.append((m.group(1), r, k))
    used, unlabelled = set(), []
    for j, pic in enumerate(pics):
        li = label_for(pic, [(a, b) for a, b, _ in labels], used)
        if li is not None:
            used.add(li)
            k = labels[li][2]
            role[k], diag[k] = "label", f"p{p}-{j + 1}"
        else:
            unlabelled.append(j)
    # A circled number beside the top corner of an unnumbered board (Stage 1
    # flags these boards as "circled"); each mark goes to its nearest board.
    for k, rl in enumerate(rls):
        if role[k] or not CIRCLE_RE.match(rl["raw_text"]):
            continue
        r, best = rl["raw_bbox"], None
        for j in unlabelled:
            pic = pics[j]
            if abs(r.y0 - pic.y0) >= 25:
                continue
            if r.x0 < pic.x0 - 5 and r.x1 < pic.x0 + 25:
                gap = pic.x0 - r.x1
            elif r.x1 > pic.x1 + 5 and r.x0 > pic.x1 - 25:
                gap = r.x0 - pic.x1
            else:
                continue
            if gap <= 4 * bs and (best is None or gap < best[0]):
                best = (gap, j)
        if best is not None:
            role[k], diag[k] = "label", f"p{p}-{best[1] + 1}"

    # Coordinates and other marks on or beside a board picture.
    if pics:
        for k, rl in enumerate(rls):
            if role[k]:
                continue
            f = feats[k]
            short = all(len(w["text"]) <= 2 for w in rl["words"]) and not f["kinds"]["move"]
            j = _pic_zone_index(rl["bbox"], pics, (2.5 if short else 1.6) * bs)
            if j is None:
                continue
            box = pymupdf.Rect(rl["bbox"])
            inside = abs(box & pics[j]) >= 0.6 * abs(box) if abs(box) else False
            # Text over a picture is OCR junk read from the board, unless it
            # reads as words (a chapter title printed over an ornament).
            vis = [ch for ch in rl["text"] if ch != " "]
            junky = sum(ch.isalnum() for ch in vis) < 0.6 * len(vis)
            if (inside and junky) or all(_coord_token(w["text"]) for w in rl["words"]) or (
                    not f["real"] and not f["kinds"]["move"]):
                role[k], diag[k] = "coord", f"p{p}-{j + 1}"

    # Captions: short centred lines just under a board. A caption is clearly
    # narrower than a full line of text, which keeps prose out of it.
    gut = ctx.gutter.get("odd" if p % 2 else "even") if ctx.gutter else None
    for j, pic in enumerate(pics):
        pcx = (pic.x0 + pic.x1) / 2
        in_col = gut is not None and (pic.x1 <= gut + 3 or pic.x0 >= gut - 3)
        full = ctx.column_width if in_col else ctx.text_width
        edges = ctx.columns.get("odd" if p % 2 else "even") or []
        if in_col and len(edges) == 2:
            edge = edges[0] if pcx < gut else edges[1]
        elif edges:
            edge = [min(e[0] for e in edges), max(e[1] for e in edges)]
        else:
            edge = None
        last = None
        for k in sorted(range(len(rls)), key=lambda k: rls[k]["bbox"][1]):
            if role[k] not in (None, "caption"):
                continue
            x0, y0, x1, y1 = rls[k]["bbox"]
            cx = (x0 + x1) / 2
            if y0 < pic.y1 - 2 or abs(cx - pcx) > 0.25 * pic.width or x1 - x0 > 1.1 * pic.width:
                continue
            ref = pic.y1 if last is None else last
            limit = 3.5 * bs if last is None else 0.8 * bs
            if y0 - ref > limit:
                break
            f = feats[k]
            if (role[k] is None and f["real"] and len(rls[k]["words"]) <= 8
                    and f["kinds"]["move"] == 0 and (full is None or x1 - x0 <= 0.9 * full)
                    and (edge is None or (x0 >= edge[0] + 0.4 * bs and x1 <= edge[1] - 0.4 * bs))):
                role[k], diag[k] = "caption", f"p{p}-{j + 1}"
                last = y1
            elif role[k] is None:
                break

    # Everything else, by content and font.
    for k, rl in enumerate(rls):
        if role[k]:
            continue
        f = feats[k]
        text = rl["text"]
        names_body = _names_font_is_body(rl, ctx)
        if _game_header(text, names_body):
            role[k] = "game_header"
        elif _is_heading(f, ctx, text):
            role[k] = "heading"
        elif ctx.moves and f["move_share"] > 0.5 and f["kinds"]["move"]:
            role[k] = "moves"
        elif not ctx.moves and _fallback_moves(rl, f):
            role[k] = "moves"
        elif any(ch.isalnum() or ch in FIGURINES for ch in text) or f["kinds"]["move"]:
            role[k] = "text"
        else:
            role[k] = "blank"

    # A short capital word printed on the row of a heading belongs to it
    # ("SOLUTIONS" "TO" "STUDIES" can come out as three PDF lines).
    for k, rl in enumerate(rls):
        t = rl["text"]
        if role[k] == "text" and len(t) <= 3 and t.isalpha() and t.isupper():
            for h, hl in enumerate(rls):
                if (role[h] == "heading" and abs(hl["base"] - rl["base"]) < 0.4 * bs
                        and min(abs(hl["bbox"][0] - rl["bbox"][2]),
                                abs(rl["bbox"][0] - hl["bbox"][2])) < 2 * bs):
                    role[k] = "heading"
                    break

    # The other line of a two-line heading in the same font, which OCR
    # errors kept from reading as capitals ("CONQUEIDNG THE SffiffiNTH"
    # above "(OR EIGHTH) RANK").
    for k, rl in enumerate(rls):
        if role[k] != "heading":
            continue
        for j, rj in enumerate(rls):
            if role[j] not in ("text", "moves") or len(rj["text"]) > 60:
                continue
            gap = min(abs(rl["bbox"][1] - rj["bbox"][3]), abs(rj["bbox"][1] - rl["bbox"][3]))
            cx, cxj = (rl["bbox"][0] + rl["bbox"][2]) / 2, (rj["bbox"][0] + rj["bbox"][2]) / 2
            if (gap <= 0.6 * bs and abs(cx - cxj) < 2 * bs and feats[j]["dom"] == feats[k]["dom"]
                    and feats[j]["dom"] != ctx.body and feats[j]["real"]
                    and not feats[j]["kinds"]["move"]
                    and sum(ch.isupper() for ch in rj["text"]) >= 0.6 * sum(
                        ch.isalpha() for ch in rj["text"])):
                role[j] = "heading"
    # A centred line in the body font right under a game header that has no
    # year carries the rest of the header ("Radio Match 1945").
    for k, rl in enumerate(rls):
        hm = GAME_HEADER_RE.match(join_year(rl["text"])) if role[k] == "game_header" else None
        if hm is None or hm.group("year"):
            continue
        for j, rj in enumerate(rls):
            gap = rj["bbox"][1] - rl["bbox"][3]
            cx, cxj = (rl["bbox"][0] + rl["bbox"][2]) / 2, (rj["bbox"][0] + rj["bbox"][2]) / 2
            if (role[j] == "text" and -1 <= gap <= 0.6 * bs and abs(cx - cxj) < 3 * bs
                    and len(rj["text"]) <= 40 and re.search(r"(?:1[5-9]|20)\d\d\s*\)?\s*$",
                                                           join_year(rj["text"]))):
                role[j] = "game_header"
                break

    # Reading order and columns.
    order, cols = _reading_order(rls, role, diag, pics, ctx, p, H)
    out = []
    for k in order:
        rl, f = rls[k], feats[k]
        spans = []
        for key, s in zip(f["keys"], rl["spans"]):
            spans.append({"text": s["text"], "font": s["font"], "size": round(s["size"], 1),
                          "bbox": [round(v, 1) for v in s["bbox"]],
                          "role": ctx.roles.get(key, "other")})
        d = {"page": p, "bbox": [round(v, 1) for v in rl["bbox"]], "text": rl["text"],
             "role": role[k], "col": cols[k], "spans": spans,
             "words": [{"text": w["text"], "bbox": [round(v, 1) for v in w["bbox"]],
                        "xs": [round(v, 1) for v in w["xs"]]}
                       for w in rl["words"]]}
        if diag[k]:
            d["diagram"] = diag[k]
        out.append(d)
    return out


def _names_font_is_body(rl, ctx):
    """True when the part of a line before its first comma is in the body font."""
    weight = Counter()
    for s in rl["spans"]:
        t = s["text"]
        weight[ctx.key(s["font"], s["size"]) == ctx.body] += s["vis"]
        if "," in t:
            break
    return weight[True] > weight[False]


def _fallback_moves(rl, f):
    m, w = f["kinds"]["move"], f["kinds"]["word"]
    if not m or m < 1.5 * w:
        return False
    first = next((x for x in rl["words"] if token_kind(x["text"]) != "neutral"), None)
    return first is not None and token_kind(first["text"]) == "move"


def _reading_order(rls, role, diag, pics, ctx, p, H):
    """Indices of rls in reading order and the column of each line:
    1 = left column, 2 = right column, 0 = one-column page or a block that
    spans both columns (running heads also get 0)."""
    n = len(rls)
    cols = [0] * n
    g = ctx.gutter.get("odd" if p % 2 else "even") if ctx.gutter else None
    tol = 0.3 * ctx.body_size

    def rows(idx):
        idx = sorted(idx, key=lambda k: (rls[k]["base"], rls[k]["bbox"][0]))
        out, row = [], []
        for k in idx:
            if row and rls[k]["base"] - rls[row[0]]["base"] > 0.4 * ctx.body_size:
                out += sorted(row, key=lambda k: rls[k]["bbox"][0])
                row = []
            row.append(k)
        return out + sorted(row, key=lambda k: rls[k]["bbox"][0])

    heads = [k for k in range(n) if role[k] == "head"]
    body = [k for k in range(n) if role[k] != "head"]
    top_heads = [k for k in heads if rls[k]["bbox"][1] < H / 2]
    bot_heads = [k for k in heads if rls[k]["bbox"][1] >= H / 2]

    side = {}
    if g is not None:
        for k in body:
            box = rls[k]["bbox"]
            if role[k] in ("coord", "label", "caption") and diag[k]:
                j = int(diag[k].split("-")[1]) - 1
                pr = pics[j]
                box = [min(box[0], pr.x0), box[1], max(box[2], pr.x1), box[3]]
            if box[2] <= g + tol:
                side[k] = 1
            elif box[0] >= g - tol:
                side[k] = 2
            else:
                side[k] = 0
        text_sides = {side[k] for k in body if role[k] not in ("coord", "blank")}
        if not (1 in text_sides and 2 in text_sides):
            g = None
    if g is None:
        return rows(top_heads) + rows(body) + rows(bot_heads), cols

    full = sorted((k for k in body if side[k] == 0),
                  key=lambda k: (rls[k]["bbox"][1] + rls[k]["bbox"][3]) / 2)
    full_y = [(rls[k]["bbox"][1] + rls[k]["bbox"][3]) / 2 for k in full]
    bands = defaultdict(lambda: {1: [], 2: []})
    for k in body:
        if side[k] == 0:
            continue
        cy = (rls[k]["bbox"][1] + rls[k]["bbox"][3]) / 2
        b = sum(1 for y in full_y if y < cy)
        bands[b][side[k]].append(k)
        cols[k] = side[k]
    order = rows(top_heads)
    for b in range(len(full) + 1):
        order += rows(bands[b][1]) + rows(bands[b][2])
        if b < len(full):
            order.append(full[b])
    return order + rows(bot_heads), cols


# ---------------------------------------------------------------- structure

CHAPTER_WORDS = {
    "chapter": "chapter", "chap": "chapter", "kapitel": "chapter", "chapitre": "chapter",
    "capítulo": "chapter", "capitulo": "chapter", "hoofdstuk": "chapter", "глава": "chapter",
    "lesson": "chapter", "lektion": "chapter", "leçon": "chapter", "lección": "chapter",
    "урок": "chapter",
    "part": "part", "teil": "part", "partie": "part", "parte": "part", "deel": "part",
    "часть": "part", "book": "part",
    "appendix": "appendix", "appendices": "appendix", "anhang": "appendix", "annexe": "appendix",
    "apéndice": "appendix", "apendice": "appendix", "bijlage": "appendix",
    "приложение": "appendix",
}
CHAPTER_RE = re.compile(
    r"^\s*(?P<word>" + "|".join(sorted(map(re.escape, CHAPTER_WORDS), key=len, reverse=True))
    + r")\b\.?\s*(?P<rest>.*)$", re.I)
NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUMBER_WORDS.update({w: i + 1 for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth".split())})
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _roman(s):
    if not s or any(c not in _ROMAN for c in s):
        return None
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = _ROMAN[a]
        total += -v if b in _ROMAN and _ROMAN[b] > v else v
    return total if total > 0 else None


def parse_chapter_heading(text):
    """Split "Chapter 7 - How to Begin a Game" into
    ("chapter", "Chapter", 7, "How to Begin a Game"). The number is None when
    it is missing or unreadable ("Chapter ?"); returns None for other text."""
    m = CHAPTER_RE.match(text.strip(SPACES))
    if not m:
        return None
    word = m.group("word")
    kind = CHAPTER_WORDS[word.lower()]
    rest = m.group("rest").strip(SPACES)
    num = None
    mm = re.match(r"^([0-9lI][0-9lIO]?(?: ?[0-9])*)(?=$|[\s:.\-–—])", rest)
    if mm and any(c.isdigit() for c in mm.group(1)) or (mm and len(mm.group(1)) == 1):
        num = int(mm.group(1).replace(" ", "").translate(DIGIT_FIX).replace("O", "0"))
        rest = rest[mm.end():]
    else:
        mm = re.match(r"^([IVXLC]+|[A-Za-z]+)(?=$|[\s:.\-–—])", rest)
        if mm and (_roman(mm.group(1)) or mm.group(1).lower() in NUMBER_WORDS):
            num = _roman(mm.group(1)) or NUMBER_WORDS[mm.group(1).lower()]
            rest = rest[mm.end():]
        elif re.match(r"^[^\w\s]{1,3}(?=$|\s)", rest):   # unreadable number such as "?"
            rest = re.sub(r"^[^\w\s]{1,3}", "", rest)
    rest = re.sub(r"^[\s:.\-–—]+", "", rest).strip(SPACES)
    if len(rest) > 90:
        return None
    return kind, word[:1].upper() + word[1:].lower(), num, rest


def _clean_title(t):
    t = t.replace("\xad", "-")
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*-\s*$", "", t)
    t = re.sub(r"(\S)- (\S)", r"\1 - \2", t)
    return t.strip(" -")


def book_structure(doc):
    """Chapters with page ranges and sections, and the end of the front matter.

    Returns {"chapters": [{"title", "start", "end", "sections": [{"title",
    "page"}], "kind", "number", "label", "subtitle", "confirmed"}],
    "front_matter_end": int, "front_matter": [{"title", "page"}]}.
    Pages are 1-based and ranges inclusive.
    """
    doc = _as_doc(doc)
    cache = _cache(doc)
    if "structure" in cache:
        return copy.deepcopy(cache["structure"])
    fonts = _fonts_internal(doc)
    ctx = _ctx(fonts)
    n = doc.page_count
    pages = [page_lines(doc, i, fonts) for i in range(n)]
    bs = ctx.body_size

    # Candidate chapter title lines near the top of a page.
    cands = []
    for p, lines in enumerate(pages, 1):
        H = doc[p - 1].rect.height
        content = [ln for ln in lines if ln["role"] not in ("head", "coord", "blank")]
        for k, ln in enumerate(content[:6]):
            parsed = parse_chapter_heading(ln["text"])
            if not parsed:
                continue
            size = _dom_size(ln)
            if ln["bbox"][1] > 0.45 * H and size < 1.5 * bs:
                continue
            if ln["role"] not in ("heading", "text", "moves", "label", "game_header"):
                continue
            cands.append({"page": p, "line": ln, "idx": lines.index(ln), "parsed": parsed,
                          "size": size, "key": _dom_key(ln, ctx)})

    chapters = []
    if cands:
        by_key = defaultdict(set)
        for c in cands:
            by_key[c["key"]].add(c["page"])
        style = max(by_key, key=lambda k: (len(by_key[k]), k[1]))
        style_size = style[1]
        if len(by_key[style]) >= 2 or style_size >= 1.5 * bs:
            chosen, seen_pages = [], set()
            for c in sorted(cands, key=lambda c: (c["page"], c["idx"])):
                if c["page"] in seen_pages:
                    continue
                if c["key"] == style or (c["size"] >= 0.8 * style_size and c["size"] >= 1.2 * bs):
                    chosen.append(c)
                    seen_pages.add(c["page"])
            chapters = _build_chapters(chosen, pages, ctx, n)
    if not chapters:
        chapters = _chapters_from_heads(pages, n)

    title_lines = {(c["start"], i) for c in chapters for i in c.pop("_lines", [])}
    keys = ("title", "label", "kind", "number", "subtitle", "start", "end", "confirmed")
    chapters = [{k: c[k] for k in keys} for c in chapters]
    for c in chapters:
        c["sections"] = _sections(pages, c["start"], c["end"], title_lines, bs)
    front_end = chapters[0]["start"] - 1 if chapters else 0
    front = []
    for p in range(1, front_end + 1):
        found = _sections(pages, p, p, set(), bs, min_size=1.25 * bs, caps_ok=True)
        # chapter titles before the first chapter are entries of a table of
        # contents, not sections of the front matter
        front.extend(s for s in found if not parse_chapter_heading(s["title"]))
    result = {"chapters": chapters, "front_matter_end": front_end, "front_matter": front}
    cache["structure"] = result
    return copy.deepcopy(result)


def _dom_size(ln):
    w = Counter()
    for s in ln["spans"]:
        w[s["size"]] += len(s["text"].strip(SPACES))
    return w.most_common(1)[0][0] if w else 0


def _dom_key(ln, ctx):
    w = Counter()
    for s in ln["spans"]:
        w[ctx.key(s["font"], s["size"])] += len(s["text"].strip(SPACES))
    return w.most_common(1)[0][0]


def _head_numbers(pages, start, end, kind):
    nums = Counter()
    texts = []
    for p in range(start, min(end, start + 40) + 1):
        for ln in pages[p - 1]:
            if ln["role"] != "head":
                continue
            texts.append(_norm(ln["text"]))
            parsed = parse_chapter_heading(ln["text"])
            if parsed and parsed[0] == kind and parsed[2] is not None:
                nums[parsed[2]] += 1
    return nums, texts


def _build_chapters(chosen, pages, ctx, n):
    bs = ctx.body_size
    out = []
    for i, c in enumerate(chosen):
        start = c["page"]
        end = chosen[i + 1]["page"] - 1 if i + 1 < len(chosen) else n
        kind, word, num, rest = c["parsed"]
        lines = pages[start - 1]
        used = [c["idx"]]
        # The subtitle: the following large lines on the title page.
        sub = [rest] if rest else []
        for k in range(c["idx"] + 1, len(lines)):
            ln = lines[k]
            if ln["role"] in ("coord", "blank"):
                continue
            if (ln["role"] == "heading" and _dom_size(ln) >= 1.3 * bs
                    and not parse_chapter_heading(ln["text"])):
                if num is None and not sub and re.fullmatch(r"[0-9lIO ]{1,4}", ln["text"]):
                    num = int(ln["text"].replace(" ", "").translate(DIGIT_FIX).replace("O", "0"))
                else:
                    sub.append(ln["text"])
                used.append(k)
                continue
            break
        out.append({"kind": kind, "word": word, "parsed_number": num, "start": start,
                    "end": end, "subtitle": _clean_title(" ".join(sub)), "_lines": used})

    # Numbers: printed, repaired by sequence and by the running heads.
    last = defaultdict(lambda: None)
    for c in out:
        kind = c["kind"]
        nums, texts = _head_numbers(pages, c["start"], c["end"], kind)
        head_num = nums.most_common(1)[0][0] if nums else None
        num, prev = c.pop("parsed_number"), last[kind]
        expected = None if prev is None else prev + 1
        if num is None:
            num = head_num if head_num is not None else expected
        elif expected is not None and num != expected:
            if head_num == num:
                pass
            elif head_num == expected or head_num is None:
                num = expected
        if num is not None:
            last[kind] = num
        c["number"] = num
        label = c.pop("word") + (f" {num}" if num is not None else "")
        c["label"] = label
        c["title"] = f"{label}: {c['subtitle']}" if c["subtitle"] else label
        sub_norm = _norm(c["subtitle"])
        c["confirmed"] = any((len(sub_norm) >= 4 and sub_norm in t) or
                             (_norm(label) and _norm(label) in t) for t in texts)
    return out


def _chapters_from_heads(pages, n):
    """Chapters read from running heads when the book has no title pages."""
    marks = []
    for p, lines in enumerate(pages, 1):
        for ln in lines:
            if ln["role"] == "head":
                parsed = parse_chapter_heading(ln["text"])
                if parsed and parsed[2] is not None:
                    marks.append((p, parsed))
                    break
    marked = {p for p, _ in marks}
    out = []
    for p, (kind, word, num, rest) in marks:
        if out and out[-1]["kind"] == kind and out[-1]["number"] == num:
            continue
        # A chapter's opening page usually has no running head of its own.
        start = p
        if start > 1 and start - 1 not in marked and (not out or start - 1 > out[-1]["start"]):
            start -= 1
        label = f"{word} {num}"
        out.append({"kind": kind, "number": num, "start": start, "label": label,
                    "subtitle": _clean_title(rest),
                    "title": f"{label}: {_clean_title(rest)}" if rest else label,
                    "confirmed": True, "_lines": []})
    for i, c in enumerate(out):
        c["end"] = out[i + 1]["start"] - 1 if i + 1 < len(out) else n
    return out


def _sections(pages, start, end, skip, bs, min_size=0, caps_ok=False):
    out = []
    for p in range(start, end + 1):
        lines = pages[p - 1]
        prev = None
        for k, ln in enumerate(lines):
            if ln["role"] != "heading" or (p, k) in skip or (
                    _dom_size(ln) < min_size and not (caps_ok and _caps(ln["text"]))):
                prev = None
                continue
            title = ln["text"]
            if not any(ch.isalpha() for ch in title):
                prev = None
                continue
            pb = prev[0]["bbox"] if prev is not None else None
            same_row = pb is not None and abs((pb[1] + pb[3]) - (ln["bbox"][1] + ln["bbox"][3])) < 0.8 * bs
            if (prev is not None and prev[0]["col"] == ln["col"]
                    and (same_row or 0 <= ln["bbox"][1] - pb[3] <= 0.9 * bs)):
                out[-1]["title"] = _clean_title(out[-1]["_raw"] + " " + title)
                out[-1]["_raw"] += " " + title
                prev = (ln,)
                continue
            out.append({"title": _clean_title(title), "page": p, "_raw": title})
            prev = (ln,)
    for s in out:
        s.pop("_raw")
    # a heading repeated as a running title on the following pages counts once
    dedup = []
    for s in out:
        if dedup and _norm(dedup[-1]["title"]) == _norm(s["title"]):
            continue
        dedup.append(s)
    return dedup
