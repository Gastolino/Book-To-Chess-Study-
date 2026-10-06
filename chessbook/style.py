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
    # the bookmark icon when set and the ribbon on a bookmarked page, and
    # nothing else: one sharp warm yellow in both schemes, so that it stands out
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
    "end": "<path d='M14.5 5v10M5.5 5l5 5-5 5'/>",
    "flip": "<path d='M7 15.5v-11M4 7.5l3-3 3 3M13 4.5v11M10 12.5l3 3 3-3'/>",
    "chevron": "<path d='M7.5 5l5 5-5 5'/>",
    "pencil": "<path d='M4 16l.9-3.6L13.6 3.7a1.3 1.3 0 0 1 1.8 0l.9.9a1.3 1.3 0 0 1 0 1.8L7.6 15.1z"
              "M12.2 5.1l2.7 2.7'/>",
    "download": "<path d='M10 3.5v9M6.5 9l3.5 3.5L13.5 9M4.5 16h11'/>",
    # a processor: a square with pins on its sides, for the analysis switch
    "cpu": "<path d='M5.5 5.5h9v9h-9zM8 8h4v4H8zM8 2.5v3M12 2.5v3M8 14.5v3M12 14.5v3M2.5 8h3M2.5 12h3"
           "M14.5 8h3M14.5 12h3'/>",
    # a gear: a circle with six short teeth, for the analysis settings
    "gear": "<circle cx='10' cy='10' r='3'/><path d='M10 2.5v3M10 14.5v3M3.5 6.25l2.6 1.5M13.9 12.25l2.6 1.5"
            "M3.5 13.75l2.6-1.5M13.9 7.75l2.6-1.5'/>",
    "bookmark": "<path d='M5.5 3.5h9v13l-4.5-3.3-4.5 3.3z'/>",
}


def icon(name):
    return f"<svg viewBox='0 0 20 20' aria-hidden='true'>{ICONS[name]}</svg>"
