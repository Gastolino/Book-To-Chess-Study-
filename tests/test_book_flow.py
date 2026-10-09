"""The book flow of the browser app (tests/flow_e2e.js): the sign of work (the
revolving book with six chequered pages, turning in space) on the start page
and in the reader's top bar; a new book opens at its first page while it is read;
the pages run on from chapter to chapter, drawn ten at a time, with a
placeholder until a picture comes; a stored reading that other reading code
made opens all the same and offers Read again. The top bar holds one line,
the book's name, the small book and Library, and on a phone or an upright
tablet goes away as the page scrolls down until the page is back at its top;
the reader's own bar leaves the book's name to it, while the reader written
to disk keeps it. On an iPhone 13 and an iPad held sideways (and upright for
the top bar).

The test needs a local Pyodide distribution and the PyMuPDF and python-chess
wheels for Pyodide (CHESSBOOK_PYODIDE, CHESSBOOK_WHEELS, as
tests/test_app_e2e.py), node and Playwright; it is skipped without them. The
book is the generated test book with a garbled game and a second chapter, or
the PDF that CHESSBOOK_FLOW_BOOK names."""
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

NODE = shutil.which("node") or "/opt/node22/bin/node"
NODE_PATH = "/opt/node22/lib/node_modules"
PYODIDE = Path(os.environ.get("CHESSBOOK_PYODIDE", ROOT / "local" / "pyodide"))
WHEELS = Path(os.environ.get("CHESSBOOK_WHEELS", ROOT / "local" / "wheels"))


def _wheel(pattern):
    found = sorted(WHEELS.glob(pattern)) if WHEELS.is_dir() else []
    return found[-1] if found else None


def _ready():
    return ((PYODIDE / "pyodide.js").exists() and _wheel("pymupdf-*.whl") and _wheel("chess-*.whl")
            and Path(NODE).exists() and Path(NODE_PATH, "playwright").exists())


class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map,
                          **{".wasm": "application/wasm", ".js": "text/javascript",
                             ".mjs": "text/javascript", ".whl": "application/zip",
                             ".webmanifest": "application/manifest+json"})

    def log_message(self, *args):
        pass


def test_the_book_icon_is_the_revolving_book_of_six_chequered_pages():
    """The sign of work and the app's icon, after the drawing the reader chose:
    six pages about the spine (a triangle and a quarter disc across the top, a
    band of two pages across the middle, a page on each side of the spine under
    it), each a face in the lighter tone with the chequer's dark squares cut to
    it and thin gaps in the background between the pages. Moving, the book turns
    in space: six leaves hinged on the spine, each holding its page's two faces,
    inside one element that tilts and turns the whole book, seen from a distance
    that follows --book-size; every page turns one way only and makes one whole
    turn a round, the pages lift off one at a time, and the round ends on the
    still drawing, which rests; with reduced motion nothing moves and the book
    stands flat and whole. web/icon.svg is the still book as tools/make_icons.py
    draws it."""
    import math
    import re
    from chessbook import style
    still, moving = style.book_svg(animated=False), style.book_svg(uid="t")
    # the view box is a square about the middle of the spine
    x, y, w, h = (float(v) for v in re.search(r'viewBox="([^"]+)"', still).group(1).split())
    assert w == h and x + w / 2 == 0 and y + h / 2 == 0
    page = re.compile(r'<path d="([^"]+)" fill="var\(--book-light\)"/>'
                      r'<path d="([^"]+)" fill="var\(--book-dark\)" fill-rule="evenodd"/>'
                      r'<path d="([^"]+)" fill="none" stroke="var\(--bg\)" stroke-width="[\d.]+"/>')
    pages = page.findall(still)
    assert len(pages) == 6 and 'class="leaf"' not in still
    assert all(face == edge and squares.count("M") >= 2 for face, squares, edge in pages)

    def box(d):
        # the corners and the ends of the arcs (an arc's last two numbers are its end point)
        points = []
        for cmd, args in re.findall(r"([MLA])([^MLAZ]*)", d):
            v = [float(t) for t in args.split()]
            points.append((v[-2], v[-1]))
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)
    boxes = [box(face) for face, _, _ in pages]
    # clockwise from the top left: the triangle and the quarter disc above the band, left and right of
    # the spine; the band's right page; the page under it, right of the spine; the page left of the
    # spine under the band; the band's left page
    tri, disc, right, low_right, low_left, left = boxes
    top_of_band = right[1]
    assert tri[2] <= 0 and disc[0] >= 0 and tri[3] <= top_of_band and disc[3] <= top_of_band
    assert right[0] >= 0 and left[2] <= 0 and right[2] > disc[2] and left[0] < tri[0]
    assert low_right[0] >= 0 and low_left[2] <= 0 and low_right[3] > right[3] and low_left[3] > left[3]
    # straight edges on the triangle and the right-hand pages, quarter circles on the others
    assert ["A" in face for face, _, _ in pages] == [False, True, False, False, True, True]

    # moving: a box, one element that turns the whole book, and in it six leaves, each the half of
    # the box on its page's side of the spine and hinged there, holding the page's front and back
    # faces (the same page as the still drawing, the back mirrored and darker) and a veil over each
    assert re.fullmatch(r'<span class="bookicon" aria-hidden="true"><span class="turn">(.*)</span></span>', moving)
    assert 'role="img" aria-label="At work"' in style.book_svg(label="At work")
    leaves = re.findall(r'<span class="leaf ([rl]) p(\d)">(.*?)</span>', moving)
    assert [(side, int(k)) for side, k, _ in leaves] == [("l", 0), ("r", 1), ("r", 2), ("r", 3), ("l", 4), ("l", 5)]
    half = w / 2
    for (side, k, body), (face, squares, _edge), (x0, _y0, x1, _y1) in zip(leaves, pages, boxes):
        svgs = re.findall(r'<svg class="(face|veil) (front|back)" viewBox="([^"]+)"[^>]*>(.*?)</svg>', body)
        assert [(a, b) for a, b, _, _ in svgs] == [("face", "front"), ("face", "back"), ("veil", "front"),
                                                   ("veil", "back")]
        # the faces lie over the half of the view box on the page's side
        assert {v for _, _, v, _ in svgs} == {f"{0 if side == 'r' else style._num(-half)} {style._num(-half)} "
                                              f"{style._num(half)} {style._num(w)}"}
        assert (x0 >= 0) == (side == "r") and (x1 <= 0) == (side == "l")
        drawn = f'<path d="{face}" fill="var(--book-light)"/><path d="{squares}" fill="var(--book-dark)" fill-rule="evenodd"/>'
        front, back = svgs[0][3], svgs[1][3]
        assert drawn in front and drawn in back
        assert f'<g transform="matrix(-1 0 0 1 {style._num(half if side == "r" else -half)} 0)">' in back
        assert f'<path class="bk" d="{face}"/>' in back
        # the gaps cut out of the page by its mask, the same mask on all four
        assert f'<mask id="t-{k}"' in front and body.count(f'mask="url(#t-{k})"') == 4
    # every id starts with the prefix given, so that two books on a page keep theirs apart
    ids = re.findall(r'id="([^"]+)"', moving)
    assert len(ids) == len(set(ids)) == 6 and all(i.startswith("t-") for i in ids)
    assert not set(ids) & set(re.findall(r'id="([^"]+)"', style.book_svg(uid="u")))

    css = style.BOOK_CSS

    def rule(selector):
        return re.search(re.escape(selector) + r"\{([^}]*)\}", css).group(1)
    # the box takes its size from --book-size, and the viewer's distance follows it
    assert re.search(r"width:var\(--book-size\);height:var\(--book-size\);"
                     r"perspective:calc\(var\(--book-size\) \* [\d.]+\)", rule(".bookicon"))
    for selector in (".bookicon .turn,.bookicon .leaf", ".bookicon .face,.bookicon .veil"):
        assert "position:absolute" in rule(selector)
    # three levels in space: the turn and the leaves keep their children in space, the faces hide
    # from behind (each with Safari's prefix too)
    assert "-webkit-transform-style:preserve-3d;transform-style:preserve-3d" in rule(".bookicon .turn,.bookicon .leaf")
    assert ("-webkit-backface-visibility:hidden;backface-visibility:hidden"
            in rule(".bookicon .face,.bookicon .veil"))
    assert "transform-origin:0 50%" in rule(".bookicon .r") and "transform-origin:100% 50%" in rule(".bookicon .l")
    # nothing that would flatten them: no filter, no clip, no overflow
    assert not re.search(r"filter|clip|overflow", css)

    def keyframes(name):
        body = re.search(r"@keyframes " + name + r"\{(.*?)\}\}", css).group(1) + "}"
        frames = []
        for stops, decl in re.findall(r"([\d.%,]+)\{([^}]*)\}", body):
            for stop in stops.split(","):
                frames.append((float(stop.rstrip("%")) / 100, decl))
        return frames
    round_s = float(re.search(r"animation:([\d.]+)s linear infinite both", rule(".bookicon .turn,.bookicon .leaf")).group(1))
    assert 2.6 <= round_s <= 3.0
    # the whole book: every keyframe the same list of functions, its tilt, its turn about the spine
    # and its size; it turns one way, half a turn a round
    turn = []
    for t, decl in keyframes("book-turn"):
        m = re.fullmatch(r"transform:rotateX\((-?[\d.]+)deg\) rotateY\((-?[\d.]+)deg\) "
                         r"scale3d\(([\d.]+),([\d.]+),([\d.]+)\)", decl)
        assert m and m.group(3) == m.group(4) == m.group(5), decl
        turn.append((t, float(m.group(1)), float(m.group(2)), float(m.group(3))))
    assert turn[0][1:] == (0, 0, 1) and turn[-1][1:] == (0, -180, 1)
    assert all(b[2] <= a[2] for a, b in zip(turn, turn[1:]))

    def at(frames, t):
        for a, b in zip(frames, frames[1:]):
            if a[0] <= t <= b[0]:
                return a[1] if b[0] == a[0] else a[1] + (b[1] - a[1]) * (t - a[0]) / (b[0] - a[0])
        return frames[-1][1]
    tilt = [(t, x) for t, x, _, _ in turn]
    spin = [(t, s) for t, _, s, _ in turn]
    # the book tips at once: past 8 degrees in the first 0.15 s
    assert at(tilt, 0.15 / round_s) <= -8
    # each page: its own turn about the spine, one way only, making up the whole turn with the book's
    starts, ends = [], []
    for k in range(6):
        frames = keyframes(f"book-leaf{k}")
        angles = [(t, float(re.match(r"transform:rotateY\((-?[\d.]+)deg\)", d).group(1))) for t, d in frames]
        assert angles[0] == (0, 0) and angles[-1][1] == -180 and angles[-1][0] == 1
        assert all(b[1] <= a[1] for a, b in zip(angles, angles[1:]))
        assert all(set(re.findall(r"([\w-]+):", d)) <= {"transform", "animation-timing-function"} for _, d in frames)
        starts.append(max(t for t, a in angles if a == 0))
        ends.append(min(t for t, a in angles if a == -180))
        # its angle in space (its own turn and the book's) only ever goes one way, by 360 degrees a round
        times = sorted({t for t, _ in angles} | {t for t, _ in spin})
        total = [at(angles, t) + at(spin, t) for t in times]
        assert all(b <= a + 1e-9 for a, b in zip(total, total[1:])) and total[0] == 0 and total[-1] == -360
    # the pages lift off one at a time, the first at once (and clearly: past 30 degrees by 0.15 s)
    assert sorted(starts)[0] == 0 and len(set(starts)) == 6
    assert min(b - a for a, b in zip(sorted(starts), sorted(starts)[1:])) * round_s >= 0.08
    first = keyframes(f"book-leaf{starts.index(0)}")
    first = [(t, float(re.match(r"transform:rotateY\((-?[\d.]+)deg\)", d).group(1))) for t, d in first]
    assert at(first, 0.15 / round_s) <= -30
    # then the still drawing rests, flat and whole, for 0.5 to 0.8 s of the round
    moving = max(t for t, x, s, c in turn if (x, s, c) != (0, -180, 1))
    rest = 1 - max(max(ends), min(t for t, *_ in turn if t > moving))
    assert 0.5 <= rest * round_s <= 0.8
    for k in range(6):
        for name, still_value in ((f"book-face{k}", 1), (f"book-veil{k}", 0), (f"book-back{k}", 0),
                                  (f"book-backveil{k}", 0)):
            frames = [(t, float(re.fullmatch(r"opacity:([\d.]+)", d).group(1))) for t, d in keyframes(name)]
            assert frames[0] == (0, still_value) and frames[-1] == (1, still_value)
            assert all(at(frames, t) == still_value for t in (1 - rest + 0.01, 1 - rest / 2))
    # and on the screen: a page turned edge on fades, so that the drawing that shows keeps within a
    # tenth of the box beyond it on every side, never thins below half the box's width but for a
    # moment, and two pages that overlap never come within 20 degrees of each other's plane
    _check_book_in_its_box(style)
    # without motion nothing moves, and the book stands flat and whole, its backs and veils gone
    reduced = re.search(r"@media \(prefers-reduced-motion:reduce\)\{(.*)\}", css).group(1)
    assert ".bookicon .turn,.bookicon .leaf,.bookicon .leaf>.face,.bookicon .leaf>.veil{animation:none}" in reduced
    # (as specific as the rules that name each page's animations, and after them)
    for k in range(6):
        assert re.search(r"\.bookicon \.p%d\{animation-name:book-leaf%d\}\.p%d>\.face\.front\{" % (k, k, k), css)
    assert css.index("@media (prefers-reduced-motion") > css.index(".p5>.veil.back")
    assert ".bookicon .turn,.bookicon .leaf{-webkit-transform-style:flat;transform-style:flat}" in reduced
    assert ".bookicon .back,.bookicon .veil{display:none}" in reduced
    # the chequer's tones: on the light page the darker board tone and the secondary text colour, in
    # the dark scheme the board's own tones; the backs and veils deeper there
    assert ":root{--book-light:var(--board-dark);--book-dark:var(--muted);" in css
    dark = "{--book-light:var(--board-light);--book-dark:var(--board-dark);"
    assert '@media (prefers-color-scheme:dark){:root:not([data-theme="light"])' + dark in css
    assert ':root[data-theme="dark"]' + dark in css
    sys.path.insert(0, str(ROOT / "tools"))
    import make_icons
    assert (ROOT / "web" / "icon.svg").read_text(encoding="utf-8").strip() == make_icons.source_svg()


def _check_book_in_its_box(style, steps=1400):
    """The moving book as the viewer sees it, from style's own account of each
    page's pose: each page's outline (its corners and points along its arcs)
    turned about the spine, the book tipped and drawn smaller, then seen from the
    viewer's distance; a page counts while either face is more than a third
    opaque."""
    import math
    import re
    half = style.BOOK_HALF
    outlines = []
    for d, _parts in style._BOOK_PAGES:
        points, cur = [], None
        for cmd, args in re.findall(r"([MLA])([^MLAZ]*)", style._outline(d)):
            v = [float(a) for a in args.split()]
            if cmd == "A":
                # points along the quarter circle: its centre lies a radius from both ends
                (x1, y1), (x2, y2), r = cur, (v[-2], v[-1]), v[0]
                mx, my, dx, dy = (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1
                q = math.hypot(dx, dy)
                off = math.sqrt(max(r * r - q * q / 4, 0)) / q
                sweep = 1 if v[4] else -1
                cx, cy = mx - sweep * off * dy, my + sweep * off * dx
                a1, a2 = math.atan2(y1 - cy, x1 - cx), math.atan2(y2 - cy, x2 - cx)
                a2 += 2 * math.pi * ((sweep > 0 and a2 < a1) - (sweep < 0 and a2 > a1))
                points += [(cx + r * math.cos(a1 + (a2 - a1) * i / 8), cy + r * math.sin(a1 + (a2 - a1) * i / 8))
                           for i in range(1, 9)]
            cur = (v[-2], v[-1])
            points.append(cur)
        outlines.append(points)
    distance = style.BOOK_PERSPECTIVE * 2 * half
    narrow = longest = 0
    for i in range(steps):
        t = style.BOOK_ROUND * i / steps
        lo = hi = None
        for k, points in enumerate(outlines):
            if max(style._book_light(k, t, False)[0], style._book_light(k, t, True)[0]) <= 1 / 3:
                continue
            _angle, leaf, spin, tilt, scale = style._book_pose(k, t)
            a, b = math.radians(leaf + spin), math.radians(tilt)
            for x, y in points:
                x, z = x * math.cos(a) * scale, x * math.sin(a) * scale
                y, z = y * scale * math.cos(b) + z * math.sin(b), -y * scale * math.sin(b) + z * math.cos(b)
                sx, sy = x * distance / (distance - z), y * distance / (distance - z)
                assert max(abs(sx), abs(sy)) <= half * 1.2, (k, t)
                lo, hi = min(lo if lo is not None else sx, sx), max(hi if hi is not None else sx, sx)
        width = (hi - lo) / (2 * half) if lo is not None else 0
        narrow = narrow + 1 if width < 0.5 else 0
        longest = max(longest, narrow)
        if 0.01 < t < style.BOOK_ROUND - 0.01:
            for left, right in ((0, 1), (4, 2), (4, 3), (5, 2), (5, 3)):
                apart = (style._book_pose(left, t)[0] - style._book_pose(right, t)[0]) % 360
                assert min(apart, 360 - apart) >= 20, (left, right, t)
    assert longest * style.BOOK_ROUND / steps < 0.12


@pytest.mark.skipif(not _ready(), reason="no local Pyodide folder, Pyodide wheels, node or Playwright")
def test_book_flow_end_to_end(tmp_path):
    site = tmp_path / "site"
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(site),
                    "--local", str(PYODIDE), "--pymupdf", str(_wheel("pymupdf-*.whl")),
                    "--chess", str(_wheel("chess-*.whl"))], check=True)
    book = os.environ.get("CHESSBOOK_FLOW_BOOK")
    static = []
    if not book:
        from chessbook import reader
        from chessbook.assemble import build_book
        from test_assemble import make_book
        from test_corrections import GARBLED, NOTE
        book = str(make_book(tmp_path / "garbled.pdf", game=GARBLED, note7=NOTE, second=True))
        # the same book's reader written to disk, whose bar keeps the book's name
        out = tmp_path / "output" / "garbled" / "reader"
        reader.build_reader(build_book(Path(book), output_dir=tmp_path / "output", books_dir=tmp_path / "books"),
                            Path(book), out)
        static = [str(out)]
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    screens = Path(os.environ.get("CHESSBOOK_SCREENS", ROOT / "output" / "screens" / "flow"))
    try:
        env = dict(os.environ, NODE_PATH=NODE_PATH)
        proc = subprocess.run([NODE, str(ROOT / "tests" / "flow_e2e.js"),
                               f"http://127.0.0.1:{server.server_address[1]}/", book,
                               str(tmp_path / "work"), str(screens), *static],
                              capture_output=True, text=True, env=env, timeout=3600)
    finally:
        server.shutdown()
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if lines and not json.loads(lines[-1]).get("ok"):
        # the whole report, which an assertion's message would cut short
        (tmp_path / "flow.json").write_text(lines[-1], encoding="utf-8")
        print("flow report:", tmp_path / "flow.json")
    assert lines, proc.stdout[-3000:] + proc.stderr[-3000:]
    res = json.loads(lines[-1])
    failed = [c for c in res["checks"] if not c["ok"]]
    assert res["ok"], (res.get("failure"), failed, res["errors"])
    assert res["errors"] == []
    names = {c["name"] for c in res["checks"]}
    assert {"while the app starts, the start page shows the revolving book: six chequered pages turning in space",
            "the pages turn in space about the spine, one at a time and all one way, a whole turn a round, and the book rests whole",
            "the turning book keeps within a tenth of its box beyond it",
            "with reduced motion the pages do not turn and the book stands whole",
            "a new book opens at its first page",
            "on a chapter's last page a swipe slides the page out and the place of the next page in",
            "the next chapter's reader shows the page enlarged where the turn left it, at its top left",
            "while the book is read, the small book shows at the right of the top bar, just left of Library",
            "the small book appears and goes without moving the reader, and rests while it is hidden",
            "a tap on the small book says what the program does, under the bar, moving nothing",
            "the top bar is one line: the book's name, the small book, then Library in the right-hand corner",
            "the words of the work do not show in the top bar",
            "in the app the reader's bar shows the chapter without the book's name",
            "the top bar goes away as the page scrolls down, and the reader takes its room",
            "it stays away while the page scrolls up part of the way",
            "it comes back when the page is scrolled all the way to the top",
            "on a wider screen the top bar stays",
            "the small book is gone when the work is done",
            "the pictures come ten pages at a time",
            "the chapter files of the app hold no pictures",
            "a reading of other reading code opens without being read again, and offers Read again",
            "Read again reads the book and opens it where the reader was"} <= names
    assert {c["mode"] for c in res["checks"]} >= {"iphone13", "ipad"}
    # the top bar's line on the phone, and on the iPad held sideways and upright
    line = [c for c in res["checks"] if c["name"].startswith("the top bar is one line")]
    assert {(c["mode"], c["detail"]["tag"]) for c in line} == {("iphone13", "390x844"), ("ipad", "1180x820"),
                                                               ("ipad", "820x1180")}
    if static:
        assert "the reader opened from disk names the book in its bar" in names
    print(json.dumps(res["timings"], indent=1))
    print("\n".join(res["notes"]))
