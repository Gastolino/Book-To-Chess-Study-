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
# A revolving book seen along its spine: four pages fanned about the centre, a
# quarter turn apart, like the blades of a pinwheel. Each page is hinged on
# one half of the spine (the upper page on the upper half), runs along the
# icon's edge for its own length, and sweeps back to the centre in a quarter
# circle, so that it reads as a page that curls as it turns; its face is a
# chequer of three by three squares in the board colours, the far squares cut
# by the curve. It is the app's icon (tools/make_icons.py renders
# web/icon.svg) and, with four more pages that turn over a quarter turn each,
# one after the other and all clockwise, the sign that the app is at work.
# The turning pages copy the still ones, and the drawing is the same after a
# quarter turn, so that a page that lands on the next one and a page that
# starts again from its own place are invisible joins. The centre of the spine
# is the origin, so that a page turns about (0, 0) in any view box.
BOOK_R, SQ = 24, 8      # a page's length from the centre, and a chequer square


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


@lru_cache(maxsize=None)
def _dark_squares():
    """The dark squares of the upper page, as one path."""
    r, squares = BOOK_R, []
    for row in range(3):
        for col in range(3):
            if (row + col) % 2:
                x, y = col * SQ, -r + row * SQ
                squares.append(_cut_to_circle([(x, y), (x + SQ, y), (x + SQ, y + SQ), (x, y + SQ)], 0, -r, r))
    return "".join(squares)


def _book_page(light, dark, line):
    """The upper page: hinged on the spine's upper half, along the top edge to
    the right, and back to the centre in a quarter circle about the spine's top."""
    r = BOOK_R
    edge = f"M0 0V{-r}H{r}A{r} {r} 0 0 1 0 0Z"
    return (f'<path d="{edge}" fill="{light}"/><path d="{_dark_squares()}" fill="{dark}"/>'
            f'<path d="{edge}" fill="none" stroke="{line}" stroke-width="1" stroke-linejoin="round" '
            f'vector-effect="non-scaling-stroke"/>')


def book_svg(cls="bookicon", animated=True, light="var(--board-light)", dark="var(--board-dark)",
             line="var(--muted)", bg=None, label=None, pad=0):
    """The book icon as an SVG element. animated adds the four turning pages
    (class "leaf"); the colours default to the page's tokens; bg fills a square
    background (the app icon) and pad widens the view box around the book."""
    side = 2 * (BOOK_R + pad)
    corner = -BOOK_R - pad
    parts = []
    if bg:
        parts.append(f'<rect x="{corner}" y="{corner}" width="{side}" height="{side}" fill="{bg}"/>')
    page = _book_page(light, dark, line)

    def turned(k, body):
        return body if k == 0 else f'<g transform="rotate({90 * k})">{body}</g>'

    parts += [turned(k, page) for k in range(4)]
    if animated:
        # the upper page turns first, then the one on the right, and so on clockwise, each
        # 0.3 s after the one before. A page starts again from its own place while the page
        # before it still turns over that place, so the four are drawn last page first: the
        # page that starts again shows under the turning one, and the join stays invisible
        parts += [turned(k, f'<g class="leaf" style="animation-delay:{0.3 * k:g}s">{page}</g>')
                  for k in reversed(range(4))]
    aria = f'role="img" aria-label="{label}"' if label else 'aria-hidden="true"'
    return (f'<svg class="{cls}" viewBox="{corner} {corner} {side} {side}" '
            f'xmlns="http://www.w3.org/2000/svg" {aria}>' + "".join(parts) + "</svg>")


# The turning pages: each turns a quarter turn about the centre of the spine
# in 0.6 s, 0.3 s after the one before, so that the four swirl round the book
# in 1.5 s; then the book rests for 0.5 s. Only a transform moves, so that the
# turns cost little on a phone. Without motion (the reader's setting) the
# turning pages are hidden and the book stands still, whole.
BOOK_CSS = """
.bookicon{display:block;overflow:visible}
.bookicon .leaf{transform-box:view-box;transform-origin:0 0;animation:leaf 2s cubic-bezier(.45,0,.55,1) infinite}
@keyframes leaf{0%{transform:rotate(0deg)}30%{transform:rotate(90deg)}100%{transform:rotate(90deg)}}
@media (prefers-reduced-motion:reduce){.bookicon .leaf{animation:none;visibility:hidden}}
"""
