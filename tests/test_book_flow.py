"""The book flow of the browser app (tests/flow_e2e.js): the sign of work (the
open book with two chequered pages whose page turns) on the start page and in
the reader's top bar; a new book opens at its first page while it is read;
the pages run on from chapter to chapter, drawn ten at a time, with a
placeholder until a picture comes; a stored reading that other reading code
made opens all the same and offers Read again. On an iPhone 13 and an iPad
held sideways.

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


def test_the_book_icon_has_two_chequered_pages():
    """The sign of work and the app's icon: two pages of 3 by 4 squares in the
    board colours, and (moving) a third page that turns about the spine;
    web/icon.svg is the still book as tools/make_icons.py draws it."""
    import re
    from chessbook import style
    svg = style.book_svg()
    leaf = re.search(r'<g class="leaf">(.*?)</g>', svg).group(1)
    still = svg[:svg.index("<g class=\"leaf\">")]
    for part in (still, leaf):
        assert part.count('fill="var(--board-dark)"') == part.count('fill="var(--board-light)"')
    assert still.count('fill="var(--board-dark)"') == 12 and still.count('width="8" height="8"') == 24
    assert leaf.count('width="8" height="8"') == 12
    assert "@keyframes leaf" in style.BOOK_CSS and "prefers-reduced-motion:reduce" in style.BOOK_CSS
    # only a transform moves, so that the turn is cheap on a phone
    frames = re.search(r"@keyframes leaf\{(.*?)\}\n", style.BOOK_CSS).group(1)
    assert set(re.findall(r"\{(\w+):", frames)) == {"transform"}
    assert 'class="leaf"' not in style.book_svg(animated=False)
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
    if not book:
        from test_assemble import make_book
        from test_corrections import GARBLED, NOTE
        book = str(make_book(tmp_path / "garbled.pdf", game=GARBLED, note7=NOTE, second=True))
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    screens = Path(os.environ.get("CHESSBOOK_SCREENS", ROOT / "output" / "screens" / "flow"))
    try:
        env = dict(os.environ, NODE_PATH=NODE_PATH)
        proc = subprocess.run([NODE, str(ROOT / "tests" / "flow_e2e.js"),
                               f"http://127.0.0.1:{server.server_address[1]}/", book,
                               str(tmp_path / "work"), str(screens)],
                              capture_output=True, text=True, env=env, timeout=3600)
    finally:
        server.shutdown()
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, proc.stdout[-3000:] + proc.stderr[-3000:]
    res = json.loads(lines[-1])
    failed = [c for c in res["checks"] if not c["ok"]]
    assert res["ok"], (res.get("failure"), failed, res["errors"])
    assert res["errors"] == []
    names = {c["name"] for c in res["checks"]}
    assert {"while the app starts, the start page shows the book with two pages of 3 by 4 squares and a turning page",
            "with reduced motion the page does not turn",
            "a new book opens at its first page",
            "on a chapter's last page a swipe slides the page out and the place of the next page in",
            "the next chapter's reader shows the page enlarged where the turn left it, at its top left",
            "while the book is read, the small book shows at the top right of the top bar",
            "the small book appears and goes without moving the reader",
            "the small book is gone when the work is done",
            "the pictures come ten pages at a time",
            "the chapter files of the app hold no pictures",
            "a reading of other reading code opens without being read again, and offers Read again",
            "Read again reads the book and opens it where the reader was"} <= names
    assert {c["mode"] for c in res["checks"]} >= {"iphone13", "ipad"}
    print(json.dumps(res["timings"], indent=1))
    print("\n".join(res["notes"]))
