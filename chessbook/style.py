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
             line="var(--bg)", bg=None, label=None, pad=0):
    """The book icon as an SVG element. animated makes the pages turn in one after
    the other (class "leaf"); the colours default to the page's tokens, and line
    is the colour of the gaps between the pages (the page's background); bg fills
    a square background (the app icon) and pad widens the view box around the book."""
    half = BOOK_HALF + pad
    parts = []
    if bg:
        parts.append(f'<rect x="{_num(-half)}" y="{_num(-half)}" width="{_num(2 * half)}" '
                     f'height="{_num(2 * half)}" fill="{bg}"/>')
    gap = bg or line
    for k, (d, _parts) in enumerate(_BOOK_PAGES):
        edge = _outline(d)
        body = (f'<path d="{edge}" fill="{light}"/>'
                f'<path d="{_page_squares(k)}" fill="{dark}" fill-rule="evenodd"/>'
                f'<path d="{edge}" fill="none" stroke="{gap}" stroke-width="{BOOK_GAP:g}"/>')
        if animated:
            body = f'<g class="leaf" style="animation-delay:{0.2 * k:g}s">{body}</g>'
        parts.append(body)
    aria = f'role="img" aria-label="{label}"' if label else 'aria-hidden="true"'
    return (f'<svg class="{cls}" viewBox="{_num(-half)} {_num(-half)} {_num(2 * half)} {_num(2 * half)}" '
            f'xmlns="http://www.w3.org/2000/svg" {aria}>' + "".join(parts) + "</svg>")


# The pages turn in: each swings in by a quarter turn about the middle of the
# spine, clockwise, and fades in as it comes; it rests in its place, then swings
# on by another quarter turn, still clockwise, and fades out. The six start
# 0.2 s apart, so that they come in one after the other round the spine and the
# book swirls; the round lasts 2.4 s. Only a transform and the opacity move, so
# that the turns cost little on a phone. Without motion (the reader's setting)
# the book stands still, whole. The chequer's two tones: on the light page the
# darker board tone and the secondary text colour, so that the pages stand out
# from the white as the drawing's white pages stand out from black; in the dark
# scheme the board's own tones.
BOOK_CSS = """
:root{--book-light:var(--board-dark);--book-dark:var(--muted)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--book-light:var(--board-light);--book-dark:var(--board-dark)}}
:root[data-theme="dark"]{--book-light:var(--board-light);--book-dark:var(--board-dark)}
.bookicon{display:block;overflow:visible}
.bookicon .leaf{transform-box:view-box;transform-origin:0 0;animation:leaf 2.4s cubic-bezier(.45,0,.55,1) infinite both}
@keyframes leaf{0%{transform:rotate(-90deg);opacity:0}14%{transform:rotate(0deg);opacity:1}72%{transform:rotate(0deg);opacity:1}86%{transform:rotate(90deg);opacity:0}100%{transform:rotate(90deg);opacity:0}}
@media (prefers-reduced-motion:reduce){.bookicon .leaf{animation:none}}
"""
