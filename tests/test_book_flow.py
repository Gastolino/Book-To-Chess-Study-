"""The book flow of the browser app (tests/flow_e2e.js): the sign of work (the
revolving book with six chequered pages that turn in) on the start page
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
    it and thin gaps in the background between the pages; moving, each page
    turns in by a quarter turn clockwise about the middle of the spine, fading
    in, one after the other 0.2 s apart, rests, and goes on clockwise, fading
    out; with reduced motion the book stands whole. web/icon.svg is the still
    book as tools/make_icons.py draws it."""
    import re
    from chessbook import style
    still, svg = style.book_svg(animated=False), style.book_svg()
    # the view box is a square about the middle of the spine, so that the pages turn about (0, 0)
    x, y, w, h = (float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split())
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
    # moving: the same six pages, each in its own group, starting 0.2 s apart in that order
    leaves = re.findall(r'<g class="leaf" style="animation-delay:([\d.]+)s">(.*?)</g>', svg)
    assert [float(d) for d, _ in leaves] == [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    assert [page.fullmatch(body).groups() for _, body in leaves] == pages
    # each turns about the middle of the spine (the origin), a quarter turn in and a quarter turn on,
    # clockwise, fading in and out; only a transform and the opacity move
    rule = re.search(r"\.bookicon \.leaf\{([^}]*)\}", style.BOOK_CSS).group(1)
    assert "transform-box:view-box" in rule and "transform-origin:0 0" in rule
    assert re.search(r"animation:leaf 2.4s \S+ infinite", rule)
    frames = re.search(r"@keyframes leaf\{(.*?)\}\n", style.BOOK_CSS).group(1)
    assert set(re.findall(r"[{;](\w+):", frames)) == {"transform", "opacity"}
    assert re.findall(r"([\d.]+)%\{transform:rotate\((-?\d+)deg\);opacity:([\d.]+)\}", frames) == [
        ("0", "-90", "0"), ("14", "0", "1"), ("72", "0", "1"), ("86", "90", "0"), ("100", "90", "0")]
    assert "@media (prefers-reduced-motion:reduce){.bookicon .leaf{animation:none}}" in style.BOOK_CSS
    # the chequer's tones: on the light page the darker board tone and the secondary text colour, in
    # the dark scheme the board's own tones
    assert ":root{--book-light:var(--board-dark);--book-dark:var(--muted)}" in style.BOOK_CSS
    dark = "{--book-light:var(--board-light);--book-dark:var(--board-dark)}"
    assert '@media (prefers-color-scheme:dark){:root:not([data-theme="light"])' + dark + "}" in style.BOOK_CSS
    assert ':root[data-theme="dark"]' + dark in style.BOOK_CSS
    sys.path.insert(0, str(ROOT / "tools"))
    import make_icons
    assert (ROOT / "web" / "icon.svg").read_text(encoding="utf-8").strip() == make_icons.source_svg()


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
    assert {"while the app starts, the start page shows the revolving book: six chequered pages, each turning in",
            "the pages turn in one after the other about the middle of the spine, all clockwise, and the book stands whole",
            "with reduced motion the pages do not turn and the book stands whole",
            "a new book opens at its first page",
            "on a chapter's last page a swipe slides the page out and the place of the next page in",
            "the next chapter's reader shows the page enlarged where the turn left it, at its top left",
            "while the book is read, the small book shows at the right of the top bar, just left of Library",
            "the small book appears and goes without moving the reader",
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
