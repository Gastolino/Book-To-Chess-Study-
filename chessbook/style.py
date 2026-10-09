"""The shared look of every HTML page the project writes (see DESIGN.md).

font_face_css()  the DM Sans and Geist Mono fonts as base64 @font-face rules, so
                 that pages work offline; built once per process and cached
tokens_css()     every colour of the design guide as a custom property, with
                 the dark values under prefers-color-scheme and data-theme
base_css()       body, type scale, hairlines, links, text buttons, check
                 boxes drawn in hairlines, focus, notation (.n), the stand-in
                 box for an unnamed sign (.ph) and tabular figures (.num)
page_css()       all three together, for a page's <style> element

Every page imports this module, so the reader, the contents page and the
stage reports share one set of fonts, colours and rules.
"""
from __future__ import annotations

import base64
import math
import re
from functools import lru_cache
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

SANS = '"DM Sans",system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif'
MONO = '"Geist Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace'

# token: (light, dark), in the order of the table in DESIGN.md
TOKENS = {
    "bg": ("#fbfbfa", "#141414"),
    "fg": ("#1b1b1b", "#e8e8e6"),
    "muted": ("#6f6f6c", "#9a9a96"),
    "line": ("#e3e3e0", "#2c2c2b"),
    "accent": ("#2f55c8", "#8aa6ff"),
    "ok": ("#3d8a5a", "#6fbf8c"),
    "doubt": ("#b8860b", "#d9ab3c"),
    "fail": ("#b4413a", "#e0756d"),
    "board-light": ("#ecebe6", "#b9b8b2"),
    "board-dark": ("#bdbab2", "#8f8d87"),
    # the bookmark icon when set, the ribbon on a bookmarked page and the line
    # under the current move outside reading mode, and nothing else: one sharp
    # warm yellow in both schemes, so that it stands out
    "bookmark": ("#f2b705", "#f2b705"),
}


def _font(name):
    return base64.b64encode((FONT_DIR / name).read_bytes()).decode("ascii")


@lru_cache(maxsize=None)
def font_face_css():
    """@font-face rules for DM Sans (variable in weight and optical size,
    upright and italic) and Geist Mono (400 and 500), each embedded as a base64
    woff2 file. The optical-size axis lets headings use the display cut and
    small text the 9pt cut (font-optical-sizing is auto)."""
    faces = [
        ("DM Sans", "dm-sans-latin-opsz-normal.woff2", "100 1000", "normal"),
        ("DM Sans", "dm-sans-latin-opsz-italic.woff2", "100 1000", "italic"),
        ("Geist Mono", "geist-mono-latin-400-normal.woff2", "400", "normal"),
        ("Geist Mono", "geist-mono-latin-500-normal.woff2", "500", "normal"),
    ]
    return "".join(
        f'@font-face{{font-family:"{fam}";src:url(data:font/woff2;base64,{_font(f)}) '
        f'format("woff2");font-weight:{w};font-style:{s};font-display:swap}}\n'
        for fam, f, w, s in faces)


def _vars(i):
    return ";".join(f"--{k}:{v[i]}" for k, v in TOKENS.items())


# In the dark scheme the pictures from the book (page images, thumbnails,
# diagram crops and samples, all marked class "scan") are dimmed, not
# inverted: inverting would swap the colours of the pieces.
DIM = "filter:brightness(.82) contrast(1.06)"


@lru_cache(maxsize=None)
def tokens_css():
    light, dark = _vars(0), _vars(1)
    return (f":root{{{light};color-scheme:light}}\n"
            f'@media (prefers-color-scheme:dark){{:root:not([data-theme="light"])'
            f'{{{dark};color-scheme:dark}}:root:not([data-theme="light"]) .scan{{{DIM}}}}}\n'
            f':root[data-theme="dark"]{{{dark};color-scheme:dark}}\n'
            f':root[data-theme="dark"] .scan{{{DIM}}}\n')


BASE_CSS = r"""
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font-family:__SANS__;font-size:15px;
font-weight:400;line-height:1.5;font-optical-sizing:auto;-webkit-font-smoothing:antialiased;
-moz-osx-font-smoothing:grayscale;text-rendering:optimizeLegibility;overflow-x:hidden}
h1,h2,h3{font-weight:500;letter-spacing:-0.01em;margin:0}
h1{font-size:26px;line-height:1.25}
h2{font-size:20px;line-height:1.3}
h3{font-size:17px;line-height:1.35}
p{margin:0}
b,strong{font-weight:500}
.small{font-size:13px;line-height:1.5}
.muted{color:var(--muted)}
.n,code{font-family:__MONO__;font-size:1em;font-variant-ligatures:none}
.ph{display:inline-block;width:.55em;height:.7em;border:1px solid currentColor;margin:0 .05em;
vertical-align:-.05em}
.num{font-variant-numeric:tabular-nums}
.rule{border:0;border-top:1px solid var(--line);margin:0}
.hl-top{border-top:1px solid var(--line)}
.hl-bottom{border-bottom:1px solid var(--line)}
a{color:var(--accent);text-decoration:none;text-underline-offset:3px;text-decoration-thickness:1px}
a:hover{text-decoration:underline}
a.nav{color:var(--fg)}
a.nav:hover{color:var(--accent)}
button{font:inherit;color:inherit}
.tb{background:none;border:0;border-radius:0;padding:0;margin:0;font:inherit;color:var(--fg);
cursor:pointer;text-underline-offset:3px;text-decoration-thickness:1px}
.tb:hover{color:var(--accent);text-decoration:underline}
.tb:disabled,.tb[aria-disabled="true"]{color:var(--muted);cursor:default;text-decoration:none}
.ib{background:none;border:0;border-radius:0;padding:8px;margin:0;color:var(--fg);cursor:pointer;
line-height:0;display:inline-flex;align-items:center;justify-content:center}
.ib svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.25;
stroke-linecap:round;stroke-linejoin:round}
.ib:hover{color:var(--accent)}
.ib:disabled{color:var(--line);cursor:default}
input[type=checkbox]{-webkit-appearance:none;appearance:none;width:13px;height:13px;margin:0;flex:none;
border:1px solid var(--muted);border-radius:0;background:transparent;display:inline-grid;
place-content:center;vertical-align:-2px;cursor:pointer}
input[type=checkbox]:hover,input[type=checkbox]:checked{border-color:var(--fg)}
input[type=checkbox]:checked::after{content:"";width:7px;height:3.5px;border:solid var(--fg);
border-width:0 0 1.25px 1.25px;transform:translate(0,-1px) rotate(-45deg)}
input[type=checkbox]:indeterminate::after{content:"";width:7px;height:0;border:solid var(--fg);
border-width:1.25px 0 0 0;transform:none}
input[type=text],input[type=number]{font:inherit;color:var(--fg);background:transparent;
border:0;border-bottom:1px solid var(--line);border-radius:0;padding:1px 2px;
font-variant-numeric:tabular-nums;text-align:center}
:focus{outline:none}
:focus-visible{outline:1px solid var(--accent);outline-offset:2px}
::selection{background:color-mix(in srgb,var(--accent) 20%,transparent)}
"""


@lru_cache(maxsize=None)
def base_css():
    return BASE_CSS.replace("__SANS__", SANS).replace("__MONO__", MONO)


@lru_cache(maxsize=None)
def page_css():
    """Fonts, colour tokens and base rules, ready for a page's <style> element."""
    return font_face_css() + tokens_css() + base_css()


# Thin line icons, 20 by 20, drawn as strokes (the .ib rule sets the stroke).
ICONS = {
    "start": "<path d='M5.5 5v10M14.5 5l-5 5 5 5'/>",
    "back": "<path d='M12.5 5l-5 5 5 5'/>",
    "forward": "<path d='M7.5 5l5 5-5 5'/>",
    # a magnifying glass with a plus: the page enlarged
    "zoom": "<circle cx='8.5' cy='8.5' r='5.5'/><path d='M12.5 12.5l4.5 4.5M8.5 6v5M6 8.5h5'/>",
    "end": "<path d='M14.5 5v10M5.5 5l5 5-5 5'/>",
    "flip": "<path d='M7 15.5v-11M4 7.5l3-3 3 3M13 4.5v11M10 12.5l3 3 3-3'/>",
    "chevron": "<path d='M7.5 5l5 5-5 5'/>",
    "pencil": "<path d='M4 16l.9-3.6L13.6 3.7a1.3 1.3 0 0 1 1.8 0l.9.9a1.3 1.3 0 0 1 0 1.8L7.6 15.1z"
              "M12.2 5.1l2.7 2.7'/>",
    # a dashed rectangle: a section of the page for the program to read
    "section": "<path d='M3.5 6.5v-3h3M9 3.5h2M13.5 3.5h3v3M16.5 9v2M16.5 13.5v3h-3M11 16.5H9"
               "M6.5 16.5h-3v-3M3.5 11V9'/>",
    "download": "<path d='M10 3.5v9M6.5 9l3.5 3.5L13.5 9M4.5 16h11'/>",
    # a processor: a square with pins on its sides, for the analysis switch
    "cpu": "<path d='M5.5 5.5h9v9h-9zM8 8h4v4H8zM8 2.5v3M12 2.5v3M8 14.5v3M12 14.5v3M2.5 8h3M2.5 12h3"
           "M14.5 8h3M14.5 12h3'/>",
    # a gear: a circle with six short teeth, for the analysis settings
    "gear": "<circle cx='10' cy='10' r='3'/><path d='M10 2.5v3M10 14.5v3M3.5 6.25l2.6 1.5M13.9 12.25l2.6 1.5"
            "M3.5 13.75l2.6-1.5M13.9 7.75l2.6-1.5'/>",
    "bookmark": "<path d='M5.5 3.5h9v13l-4.5-3.3-4.5 3.3z'/>",
    # a circle, the left half filled: the page shown in reverse
    "invert": "<circle cx='10' cy='10' r='6.5'/><path d='M10 3.5a6.5 6.5 0 0 0 0 13z' fill='currentColor' stroke='none'/>",
    # two filled squares, the second up and to the right of the first, overlapping by a quarter:
    # one path filled even-odd, so that the square they share is cut out. It stands for the
    # program's reading laid over the page (Show reading). Squares of 8, offset by 4, fill the
    # middle 12 by 12 of the box (a filled shape weighs more than the others' strokes), and every
    # edge lies on a whole unit, so that it is sharp at one, two and three pixels to the unit
    "reading": "<path d='M4 8h8v8H4zM8 4h8v8H8z' fill='currentColor' fill-rule='evenodd' stroke='none'/>",
    # the contents: three rows, each a dot (the chapter's number) and a line (its title)
    "contents": "<circle cx='4.5' cy='5.5' r='1.25' fill='currentColor' stroke='none'/>"
                "<circle cx='4.5' cy='10' r='1.25' fill='currentColor' stroke='none'/>"
                "<circle cx='4.5' cy='14.5' r='1.25' fill='currentColor' stroke='none'/>"
                "<path d='M8.5 5.5h8M8.5 10h8M8.5 14.5h8'/>",
}


def icon(name):
    return f"<svg viewBox='0 0 20 20' aria-hidden='true'>{ICONS[name]}</svg>"


# ---------------------------------------------------------------- the book icon
# A revolving book (after the drawing the reader chose): six pages fanned about
# the spine, each a flat shape with a chequer on its face in the board colours.
# Across the top, a page cut on the diagonal (a right triangle) on the left of
# the spine and a quarter disc on the right; across the middle, a wide band of
# two pages that the spine parts, the left one hollowed by a quarter circle and
# the right one cut on the diagonal; under them, a page on each side of the
# spine, the left one bounded by two quarter circles and the right one a
# parallelogram. Thin gaps in the page's background part the pages, as the
# gaps along the spine of a book do. The unit (U) is the quarter disc's radius;
# the top of the spine is at (0, -0.7 U) and the middle of the drawing, about
# which the pages turn, is the origin. The chequer's squares are a third of a
# unit, on one grid for the whole book, and each page's squares are cut to its
# shape as plain paths, since PyMuPDF (which draws the app's icons) ignores an
# SVG's clip paths and patterns. It is the app's icon (tools/make_icons.py
# renders web/icon.svg) and, turning, the sign that the app is at work.
BOOK_U = 16                 # the unit, in the view box's units
BOOK_SQ = 1 / 3             # a chequer square, in units
BOOK_GAP = 1.2              # the gap between two pages, in the view box's units
BOOK_HALF = 1.7 * BOOK_U    # half the drawing's height (it is 3.4 units tall and 2.8 wide)


def _cut_to_circle(poly, cx, cy, r):
    """The part of a convex polygon (its corners clockwise on the screen, and
    too small to hold the whole circle) that lies inside the circle about
    (cx, cy) of radius r, as SVG path data: the polygon's own edges where they
    stay inside, arcs of the circle where they leave it. The page's squares are
    drawn as plain shapes, not clipped, since PyMuPDF (which draws the app's
    icons) ignores an SVG's clip paths and patterns."""
    def inside(p):
        return (p[0] - cx) ** 2 + (p[1] - cy) ** 2 <= r * r + 1e-6

    # the polygon's corners with the points where its edges cross the circle
    points = []
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        points.append(p)
        dx, dy, fx, fy = q[0] - p[0], q[1] - p[1], p[0] - cx, p[1] - cy
        a, b, c = dx * dx + dy * dy, 2 * (fx * dx + fy * dy), fx * fx + fy * fy - r * r
        if b * b - 4 * a * c > 0:
            root = math.sqrt(b * b - 4 * a * c)
            for t in sorted(((-b - root) / (2 * a), (-b + root) / (2 * a))):
                if 1e-6 < t < 1 - 1e-6:
                    points.append((p[0] + t * dx, p[1] + t * dy))
    kept = [i for i, p in enumerate(points) if inside(p)]
    if len(kept) < 2:
        return ""

    def num(v):
        return f"{round(v, 2):g}"

    # two points next to each other on the polygon are joined by its edge (a chord of the
    # circle stays inside it); where points outside were left out between them, by the arc;
    # the closing edge back to the first point, when it is straight, is the Z
    path = ""
    for j, i in enumerate(kept + kept[:1]):
        x, y = points[i]
        if j == 0:
            path = f"M{num(x)} {num(y)}"
        elif i != (kept[j - 1] + 1) % len(points):
            path += f"A{r} {r} 0 0 1 {num(x)} {num(y)}"
        elif j < len(kept):
            path += f"L{num(x)} {num(y)}"
    return path + "Z"


def _signed_area(poly):
    return sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(poly, poly[1:] + poly[:1])) / 2


def _clockwise(poly):
    """The polygon with its corners clockwise on the screen (y pointing down)."""
    return poly if _signed_area(poly) > 0 else poly[::-1]


def _clip(poly, convex):
    """The part of a polygon inside a convex polygon (Sutherland and Hodgman),
    both with their corners clockwise on the screen."""
    out = list(poly)
    for a, b in zip(convex, convex[1:] + convex[:1]):
        def side(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        src, out = out, []
        for i, p in enumerate(src):
            q = src[(i + 1) % len(src)]
            sp, sq = side(p), side(q)
            if sp >= 0:
                out.append(p)
            if (sp >= 0) != (sq >= 0) and sp != sq:
                t = sp / (sp - sq)
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        if not out:
            return []
    return out if abs(_signed_area(out)) > 1e-9 else []


def _num(v):
    return f"{round(v, 2):g}"


def _poly_path(poly):
    return "M" + "L".join(f"{_num(x)} {_num(y)}" for x, y in poly) + "Z"


def _box(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# The pages, in units with the top of the spine at (0, 0): each as its outline (SVG path data
# with U-radius arcs) and the convex parts its face is made of, each part a polygon and, for a
# curved part, the circle (centre) it is cut to; "minus" parts are holes (the even-odd rule).
# Their order is the order in which they turn in, clockwise round the spine from the top left.
_BOOK_PAGES = (
    ("M-1 -1L-1 0L0 0Z", [(_box(-1, -1, 0, 0), None, False)]),       # the triangle (cut below)
    ("M0 0A1 1 0 0 1 1 -1L1 0Z", [(_box(0, -1, 1, 0), (1, 0), False)]),
    ("M0 0L1.4 0L1.4 1.4L1 1.4L1 1Z", [([(0, 0), (1.4, 0), (1.4, 1), (1, 1)], None, False),
                                       (_box(1, 1, 1.4, 1.4), None, False)]),
    ("M0 0L1 1L1 2.4L0 1.4Z", [([(0, 0), (1, 1), (1, 2.4), (0, 1.4)], None, False)]),
    ("M0 0A1 1 0 0 1 -1 1L-1 2.4A1 1 0 0 0 0 1.4Z", [(_box(-1, 0, 0, 1.4), None, False),
                                                    (_box(-1, 0, 0, 1.4), (-1, 0), True),
                                                    (_box(-1, 1.4, 0, 2.4), (-1, 1.4), False)]),
    ("M-1.4 0L0 0A1 1 0 0 1 -1 1L-1 1.4L-1.4 1.4Z", [(_box(-1.4, 0, -1, 1.4), None, False),
                                                    (_box(-1, 0, 0, 1.4), (-1, 0), False)]),
)
# the triangle's face is the box's half below its diagonal
_TRIANGLE = [(-1, -1), (0, 0), (-1, 0)]


def _scaled(x, y):
    return x * BOOK_U, (y - 0.7) * BOOK_U


def _outline(d):
    """A page's outline in the view box's units (the arcs' radius is U)."""
    out, nums = [], re.split(r"([MLAZ])", d)
    cmd = None
    for tok in nums:
        if tok in ("M", "L", "A", "Z"):
            cmd = tok
            out.append(tok)
            continue
        v = [float(t) for t in tok.split()] if tok.strip() else []
        if cmd in ("M", "L") and v:
            x, y = _scaled(v[0], v[1])
            out.append(f"{_num(x)} {_num(y)}")
        elif cmd == "A" and v:
            x, y = _scaled(v[5], v[6])
            out.append(f"{_num(v[0] * BOOK_U)} {_num(v[1] * BOOK_U)} {v[2]:g} {v[3]:g} {v[4]:g} {_num(x)} {_num(y)}")
    return "".join(out)


@lru_cache(maxsize=None)
def _page_squares(k):
    """Page k's dark squares, cut to its face, as one path (the even-odd rule)."""
    parts = _BOOK_PAGES[k][1]
    if k == 0:
        parts = [(_TRIANGLE, None, False)]
    sq, paths = BOOK_SQ, []
    for j in range(-3, 9):
        for i in range(-5, 5):
            if (i + j) % 2 == 0:
                continue
            square = [_scaled(x, y) for x, y in _box(i * sq, j * sq, (i + 1) * sq, (j + 1) * sq)]
            for poly, centre, _minus in parts:
                piece = _clip(square, _clockwise([_scaled(x, y) for x, y in poly]))
                if not piece:
                    continue
                if centre is None:
                    paths.append(_poly_path(piece))
                else:
                    cx, cy = _scaled(*centre)
                    paths.append(_cut_to_circle(_clockwise(piece), cx, cy, BOOK_U))
    return "".join(p for p in paths if p)


def book_svg(cls="bookicon", animated=True, light="var(--book-light)", dark="var(--book-dark)",
             line="var(--bg)", bg=None, label=None, pad=0, uid="book"):
    """The book icon. Still (animated False), an SVG element: the colours default
    to the page's tokens, line is the colour of the gaps between the pages (the
    page's background), bg fills a square background (the app icon) and pad widens
    the view box around the book. Moving, the book that turns in space while the
    app works (in the page's tokens, see BOOK_CSS); uid starts the ids of its
    masks, so that two moving books on one page keep theirs apart."""
    if animated:
        return _book_moving(cls, label, uid)
    half = BOOK_HALF + pad
    parts = []
    if bg:
        parts.append(f'<rect x="{_num(-half)}" y="{_num(-half)}" width="{_num(2 * half)}" '
                     f'height="{_num(2 * half)}" fill="{bg}"/>')
    gap = bg or line
    for k, (d, _parts) in enumerate(_BOOK_PAGES):
        edge = _outline(d)
        parts.append(f'<path d="{edge}" fill="{light}"/>'
                     f'<path d="{_page_squares(k)}" fill="{dark}" fill-rule="evenodd"/>'
                     f'<path d="{edge}" fill="none" stroke="{gap}" stroke-width="{BOOK_GAP:g}"/>')
    aria = f'role="img" aria-label="{label}"' if label else 'aria-hidden="true"'
    return (f'<svg class="{cls}" viewBox="{_num(-half)} {_num(-half)} {_num(2 * half)} {_num(2 * half)}" '
            f'xmlns="http://www.w3.org/2000/svg" {aria}>' + "".join(parts) + "</svg>")


# ---------------------------------------------------------------- the book at work
# Moving, the book turns in space. The round starts on the still drawing: one page
# at a time lifts off and swings about the spine, so that the six pages stand
# fanned round it like the leaves of a star book, each at its own angle; all the
# while the whole book tips its top towards the viewer (it is seen a little from
# above) and turns half a turn about its spine, so that the pages show their
# darker backs; then the pages fold on round the spine, one at a time, back into
# the still drawing, which rests until the next round. Every page turns one way
# only (a right-hand page comes towards the viewer, as a page turned forward does)
# and makes exactly one whole turn a round, half of it with the book and the rest
# on its own, so that each round ends on the drawing it started from.
#
# The markup is HTML, since browsers flatten 3D transforms inside an SVG:
#   span.bookicon        the box (--book-size) and the viewer's distance (perspective)
#     span.turn          the whole book: its tilt, its turn about the spine and its size
#       span.leaf x 6    a page's own turn about the spine: half the box, hinged on the spine
#         svg.face.front, svg.face.back    the page's two faces, each hidden from behind
#         svg.veil.front, svg.veil.back    a black veil over each face: the light on it
# Every leaf is the same half of the box, so that every layer's centre lies the
# same distance from the spine; Safari, which stacks whole layers by their depth,
# then stacks the pages as their angles say. Only transforms and opacities move.
# The gaps between the pages are cut out of each face by a mask, so that a page
# in front of another shows the page behind through its gaps.

BOOK_ROUND = 2.8            # seconds a round lasts
BOOK_PERSPECTIVE = 2.6      # the viewer's distance from the book, in book sizes
BOOK_FADE = 16              # degrees either side of edge on over which a face fades out and in
# The easings, as the points of a CSS cubic-bezier
_BOOK_EASE = {"out": (.2, .6, .35, 1), "inout": (.45, 0, .55, 1)}
# The whole book: (second, degrees, easing) points of its tilt (its top towards the
# viewer) and of its turn about the spine; the easing is the one that reaches the point
BOOK_TILT = ((0, 0), (0.45, 18, "out"), (1.65, 18), (2.2, 0, "inout"))
BOOK_SPIN = ((0, 0), (2.1, 180, "inout"))
BOOK_SHRINK = 0.9           # how much smaller the book is drawn at full tilt, so that it keeps to its box
# The pages: (page, second it lifts, its angle in the fan, second it folds on); a lift
# takes BOOK_LIFT seconds and a fold BOOK_FOLD. A right-hand page's fan angle is
# measured from where it lies, towards the viewer; a left-hand page's from where it
# lies, away from the viewer, so that the fan is the same turn for both. They lift
# from the top of the book down, a row's two pages one after the other, the first at
# once; in the fan the six leaves stand round the spine 45 or 90 degrees apart, so
# that the book is never seen edge on as a whole, and two pages whose shapes overlap
# never come within 60 degrees of each other. The pages fold on in the same order,
# and the drawing then rests for the last 0.6 s of the round.
BOOK_LIFT, BOOK_FOLD = 0.32, 0.34
BOOK_LEAVES = ((1, 0.00, 75, 1.22), (0, 0.13, 30, 1.35), (2, 0.26, 120, 1.48),
               (5, 0.39, 75, 1.61), (3, 0.52, 30, 1.74), (4, 0.65, 120, 1.86))
# The light comes from the left, in front; a face lit less than the book lying flat
# is veiled in black by as much (never lit more, so that the resting drawing is the
# still one). A face's veil also draws a thin dark edge just inside the page's gap,
# and shows at least BOOK_EDGE while the page is off its place, so that two pages
# that overlap stay apart; the veil's inside is var(--book-veil) of its black.
BOOK_LIGHT = (-0.6, -0.1, 0.8)
BOOK_AMBIENT = 0.72
BOOK_EDGE = 0.25
BOOK_EDGE_WIDTH = 0.45      # in the view box's units
_BOOK_VEIL = 0.3            # var(--book-veil) on the light page, which the veils' opacities are worked out for

_BOOK_SIDE = {0: "l", 1: "r", 2: "r", 3: "r", 4: "l", 5: "l"}


def _bezier(points, x):
    """A CSS cubic-bezier easing at x (0 to 1)."""
    p1x, p1y, p2x, p2y = points

    def at(t, a, b):
        return 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if at(mid, p1x, p2x) < x else (lo, mid)
    return at((lo + hi) / 2, p1y, p2y)


def _book_curve(points, t):
    """The value at second t of a curve given by (second, value[, easing]) points."""
    if t <= points[0][0]:
        return points[0][1]
    for a, b in zip(points, points[1:]):
        if t <= b[0]:
            if b[0] == a[0]:
                return b[1]
            ease = _BOOK_EASE[b[2] if len(b) > 2 else "inout"]
            return a[1] + (b[1] - a[1]) * _bezier(ease, (t - a[0]) / (b[0] - a[0]))
    return points[-1][1]


def _book_leaf_points(k):
    """Page k's own turn about the spine, as (second, degrees, easing) points: it
    lifts to its fan angle, waits, and folds on to make up the whole turn with the
    book's own half turn."""
    _, lift, fan, fold = next(row for row in BOOK_LEAVES if row[0] == k)
    rest = 360 - BOOK_SPIN[-1][1]
    points = [(0, 0), (lift, 0), (lift + BOOK_LIFT, fan, "out"), (fold, fan),
              (fold + BOOK_FOLD, rest, "inout"), (BOOK_ROUND, rest)]
    return [p for i, p in enumerate(points) if i == 0 or p[0] > points[i - 1][0]]


def _book_pose(k, t):
    """Page k at second t: its angle about the spine (0 where a right-hand page
    lies, growing as such a page comes towards the viewer), its own turn, the
    book's turn, tilt and size."""
    leaf, spin = _book_curve(_book_leaf_points(k), t), _book_curve(BOOK_SPIN, t)
    tilt = _book_curve(BOOK_TILT, t)
    scale = 1 - (1 - BOOK_SHRINK) * tilt / max(p[1] for p in BOOK_TILT)
    home = 0 if _BOOK_SIDE[k] == "r" else 180
    return home + leaf + spin, leaf, spin, tilt, scale


def _book_light(k, t, back):
    """Page k's face at second t: how opaque it is (faded near edge on, none from
    behind) and how much of its veil shows (the light it lacks and its edge)."""
    angle, leaf, spin, tilt, _ = _book_pose(k, t)
    side = 1 if _BOOK_SIDE[k] == "r" else -1
    facing = side * math.cos(math.radians(angle)) * (-1 if back else 1)
    opacity = min(max(facing / math.sin(math.radians(BOOK_FADE)), 0), 1) ** 2
    # the face's normal: turned with the page about the spine, then tipped with the book
    a, b = math.radians(leaf + spin), math.radians(tilt)
    n = (-math.sin(a), math.cos(a) * math.sin(b), math.cos(a) * math.cos(b))
    if back:
        n = tuple(-c for c in n)
    norm = math.sqrt(sum(c * c for c in BOOK_LIGHT))

    def lit(v):
        return BOOK_AMBIENT + (1 - BOOK_AMBIENT) * max(sum(p * q / norm for p, q in zip(v, BOOK_LIGHT)), 0)
    dark = max(1 - lit(n) / lit((0, 0, 1)), 0)
    off = abs((leaf + spin + 180) % 360 - 180)
    edge = BOOK_EDGE * min(off / 15, 1)
    return opacity, min(max(dark / _BOOK_VEIL, edge), 1) * opacity


def _pct(t):
    return f"{round(100 * t / BOOK_ROUND, 2):g}%"


def _simplified(points, tols):
    """The fewest of the (second, values...) points that keep every value within its
    tolerance of the straight line between the points kept (Douglas and Peucker)."""
    if len(points) < 3:
        return points
    (t0, *v0), (t1, *v1) = points[0], points[-1]
    worst, at = 0, 0
    for i in range(1, len(points) - 1):
        t, *v = points[i]
        u = (t - t0) / (t1 - t0)
        miss = max(abs(c - (a + (b - a) * u)) / tol for c, a, b, tol in zip(v, v0, v1, tols))
        if miss > worst:
            worst, at = miss, i
    if worst <= 1:
        return [points[0], points[-1]]
    return _simplified(points[:at + 1], tols)[:-1] + _simplified(points[at:], tols)


def _keyframes(name, points, fmt, tols):
    """Keyframes from (second, values...) points sampled over a round, kept where the
    straight lines between them stray; a value that holds is written once."""
    # a value that holds stays exact: the samples are cut where one starts or ends to hold
    cuts = [0] + [i for i in range(1, len(points) - 1)
                  if (points[i][1:] == points[i - 1][1:]) != (points[i][1:] == points[i + 1][1:])] + [len(points) - 1]
    kept = [points[0]]
    for a, b in zip(cuts, cuts[1:]):
        kept += _simplified(points[a:b + 1], tols)[1:]
    rules = []
    for i, (t, *v) in enumerate(kept):
        if 0 < i < len(kept) - 1 and kept[i - 1][1:] == v == kept[i + 1][1:]:
            continue
        rules.append(f"{_pct(t)}{{{fmt(*v)}}}")
    return f"@keyframes {name}{{{''.join(rules)}}}"


def _book_samples(fn, step=0.01):
    n = round(BOOK_ROUND / step)
    return [(BOOK_ROUND * i / n, *fn(BOOK_ROUND * i / n)) for i in range(n + 1)]


def _num3(v):
    return f"{round(v, 3):g}"


def _book_css():
    """The moving book's rules and keyframes, worked out from the tables above."""
    size = "var(--book-size)"
    css = [f".bookicon{{--book-size:80px;display:block;position:relative;width:{size};height:{size};"
           f"perspective:calc({size} * {BOOK_PERSPECTIVE:g})}}",
           ".bookicon .turn,.bookicon .leaf{position:absolute;top:0;height:100%;"
           "-webkit-transform-style:preserve-3d;transform-style:preserve-3d;"
           f"animation:{BOOK_ROUND:g}s linear infinite both}}",
           ".bookicon .turn{left:0;width:100%;animation-name:book-turn}",
           ".bookicon .leaf{width:50%}",
           ".bookicon .r{left:50%;transform-origin:0 50%}",
           ".bookicon .l{left:0;transform-origin:100% 50%}",
           ".bookicon .face,.bookicon .veil{position:absolute;left:0;top:0;width:100%;height:100%;display:block;"
           "-webkit-backface-visibility:hidden;backface-visibility:hidden;"
           f"animation:{BOOK_ROUND:g}s linear infinite both}}",
           ".bookicon .back{transform:rotateY(180deg)}",
           ".bookicon .veil{opacity:0;transform:translateZ(.2px)}",
           ".bookicon .veil.back{transform:rotateY(180deg) translateZ(.2px)}",
           ".bookicon .bk{fill:#000;fill-opacity:var(--book-back)}",
           ".bookicon .vi{fill:#000;fill-opacity:var(--book-veil)}",
           ".bookicon .ve{fill:none;stroke:#000;stroke-opacity:.6}"]
    # the whole book: its tilt, its turn and its size, in one list of the same functions (the
    # book's are the same for every page; page 0's pose gives them)
    css.append(_keyframes("book-turn", _book_samples(lambda t: _book_pose(0, t)[2:]),
                          lambda spin, tilt, scale: f"transform:rotateX({0 - tilt:.4g}deg) rotateY({0 - spin:.4g}deg) "
                                                    f"scale3d({_num3(scale)},{_num3(scale)},{_num3(scale)})",
                          (0.4, 0.25, 0.002)))
    for k in range(6):
        p = f".bookicon .p{k}"
        # (the faces' rules as specific as the reduced-motion rule below, which comes after them)
        css.append(f"{p}{{animation-name:book-leaf{k}}}"
                   f".p{k}>.face.front{{animation-name:book-face{k}}}.p{k}>.face.back{{animation-name:book-back{k}}}"
                   f".p{k}>.veil.front{{animation-name:book-veil{k}}}.p{k}>.veil.back{{animation-name:book-backveil{k}}}")
        # the page's own turn: its points, each segment eased as the table says
        rules = []
        points = _book_leaf_points(k)
        for i, (t, angle, *_e) in enumerate(points):
            ease = points[i + 1][2] if i + 1 < len(points) and len(points[i + 1]) > 2 else None
            rule = f"transform:rotateY({-angle:g}deg)"
            if ease:
                rule += f";animation-timing-function:cubic-bezier({','.join(f'{c:g}' for c in _BOOK_EASE[ease])})"
            rules.append(f"{_pct(t)}{{{rule}}}")
        css.append(f"@keyframes book-leaf{k}{{{''.join(rules)}}}")
        for back, face, veil in ((False, "book-face", "book-veil"), (True, "book-back", "book-backveil")):
            samples = _book_samples(lambda t: _book_light(k, t, back))
            css.append(_keyframes(f"{face}{k}", [(t, o) for t, o, _ in samples],
                                  lambda o: f"opacity:{_num3(o)}", (0.01,)))
            css.append(_keyframes(f"{veil}{k}", [(t, v) for t, _, v in samples],
                                  lambda v: f"opacity:{_num3(v)}", (0.01,)))
    # without motion (the reader's setting) the drawing stands still and flat, its
    # backs and veils gone, so that no browser can show a page from the wrong side
    css.append("@media (prefers-reduced-motion:reduce){"
               ".bookicon .turn,.bookicon .leaf,.bookicon .leaf>.face,.bookicon .leaf>.veil{animation:none}"
               ".bookicon .turn,.bookicon .leaf{-webkit-transform-style:flat;transform-style:flat}"
               ".bookicon .back,.bookicon .veil{display:none}}")
    return "\n".join(css) + "\n"


def _book_moving(cls, label, uid):
    """The moving book's markup: the box, the turning book, and six leaves each
    holding its page's faces and veils (the page drawn as the still drawing draws
    it, over the half of the view box on its side of the spine)."""
    h = BOOK_HALF
    leaves = []
    for k, (d, _parts) in enumerate(_BOOK_PAGES):
        edge, side = _outline(d), _BOOK_SIDE[k]
        x0 = 0 if side == "r" else -h
        box = f'viewBox="{_num(x0)} {_num(-h)} {_num(h)} {_num(2 * h)}"'
        mask = f"{uid}-{k}"
        # the back is drawn mirrored about the middle of its half (its rotateY(180deg) turns it back)
        mirror = f'<g transform="matrix(-1 0 0 1 {_num(2 * x0 + h)} 0)">'
        page = (f'<path d="{edge}" fill="var(--book-light)"/>'
                f'<path d="{_page_squares(k)}" fill="var(--book-dark)" fill-rule="evenodd"/>')
        veil = (f'<path class="vi" d="{edge}"/>'
                f'<path class="ve" d="{edge}" stroke-width="{BOOK_GAP + 2 * BOOK_EDGE_WIDTH:g}"/>')
        svg = f'<svg class="{{}}" {box} xmlns="http://www.w3.org/2000/svg">{{}}</svg>'
        leaves.append(
            f'<span class="leaf {side} p{k}">'
            + svg.format("face front",
                         f'<mask id="{mask}" maskUnits="userSpaceOnUse" x="{_num(x0)}" y="{_num(-h)}" '
                         f'width="{_num(h)}" height="{_num(2 * h)}"><path d="{edge}" fill="#fff" stroke="#000" '
                         f'stroke-width="{BOOK_GAP:g}"/></mask><g mask="url(#{mask})">{page}</g>')
            + svg.format("face back", f'{mirror}<g mask="url(#{mask})">{page}<path class="bk" d="{edge}"/></g></g>')
            + svg.format("veil front", f'<g mask="url(#{mask})">{veil}</g>')
            + svg.format("veil back", f'{mirror}<g mask="url(#{mask})">{veil}</g></g>')
            + "</span>")
    aria = f'role="img" aria-label="{label}"' if label else 'aria-hidden="true"'
    return f'<span class="{cls}" {aria}><span class="turn">{"".join(leaves)}</span></span>'


# The chequer's two tones: on the light page the darker board tone and the
# secondary text colour, so that the pages stand out from the white as the
# drawing's white pages stand out from black; in the dark scheme the board's own
# tones. A page's back is its face under --book-back of black, and a veil's inside
# is --book-veil of black: both deeper in the dark scheme, where the board's tones
# sit on near-black and a light veil would hardly show.
BOOK_CSS = """
:root{--book-light:var(--board-dark);--book-dark:var(--muted);--book-back:.16;--book-veil:.3}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--book-light:var(--board-light);--book-dark:var(--board-dark);--book-back:.3;--book-veil:.3}}
:root[data-theme="dark"]{--book-light:var(--board-light);--book-dark:var(--board-dark);--book-back:.3;--book-veil:.3}
""" + _book_css()
