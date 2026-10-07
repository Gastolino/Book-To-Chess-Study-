"""The library in the browser (web/library.js with its IndexedDB store), on
the static site that GitHub Pages serves, with no server: a book added once
opens again without being read, with its corrections and at its place, after
the browser is started again; a book saved as a book file (.chessbook) opens
in another browser profile the same way; removing a book leaves nothing
behind (tests/device_library_e2e.js).

The test needs a local Pyodide distribution and the PyMuPDF and python-chess
wheels for Pyodide (CHESSBOOK_PYODIDE, CHESSBOOK_WHEELS, as
tests/test_app_e2e.py), node and Playwright; it is skipped without them.
The books are the generated test book with a garbled game and a second
book, or the two PDFs that CHESSBOOK_DEVICE_BOOKS names (separated by a
comma)."""
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


def test_the_shell_offers_the_library_everywhere(tmp_path):
    """The start page is the library wherever the app runs: the server's when
    /api/books answers, else the one in the browser; the app can be added to
    the Home Screen; the file chooser takes book files as well as PDFs."""
    site = tmp_path / "site"
    wheel = tmp_path / "chess-1.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(site),
                    "--pymupdf-url", "https://example.invalid/pymupdf.whl", "--chess", str(wheel)],
                   check=True, capture_output=True)
    page = (site / "index.html").read_text(encoding="utf-8")
    assert '<link rel="manifest" href="manifest.webmanifest">' in page
    assert 'accept="application/pdf,.pdf,.chessbook,application/zip,.zip"' in page
    assert 'id="libspace"' in page and 'id="libhint"' in page
    manifest = json.loads((site / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    # the icons: the revolving book with four chequered pages (tools/make_icons.py, web/icon.svg)
    for name in ("icon-32.png", "icon-180.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png"):
        assert (site / name).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", name
    assert {i["src"] for i in manifest["icons"]} >= {"icon-180.png", "icon-192.png", "icon-512.png",
                                                     "icon-maskable-512.png"}
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"])
    assert manifest["background_color"] == manifest["theme_color"] == "#fbfbfa"
    assert '<link rel="icon" href="favicon.svg" type="image/svg+xml">' in page
    # four pages, each with its dark squares as one shape
    assert (site / "favicon.svg").read_text(encoding="utf-8").count('fill="#bdbab2"') == 4
    lib = (site / "library.js").read_text(encoding="utf-8")
    assert 'indexedDB.open(NAME, 1)' in lib and "navigator.storage.persist()" in lib
    assert "navigator.storage.estimate()" in lib and "navigator.share(" in lib


@pytest.mark.skipif(not _ready(), reason="no local Pyodide folder, Pyodide wheels, node or Playwright")
def test_device_library_end_to_end(tmp_path):
    site = tmp_path / "site"
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(site),
                    "--local", str(PYODIDE), "--pymupdf", str(_wheel("pymupdf-*.whl")),
                    "--chess", str(_wheel("chess-*.whl"))], check=True)
    books = [b for b in os.environ.get("CHESSBOOK_DEVICE_BOOKS", "").split(",") if b]
    if len(books) < 2:
        import pymupdf
        from test_assemble import make_book
        from test_corrections import GARBLED, NOTE
        first = make_book(tmp_path / "garbled_games.pdf", game=GARBLED, note7=NOTE, second=True)
        plain = make_book(tmp_path / "plain.pdf", second=True)
        doc = pymupdf.open(plain)
        doc.set_metadata({"title": "Endgame Lessons for Club Players"})
        second = tmp_path / "endgame_lessons.pdf"
        doc.save(second)
        books = [str(first), str(second)]
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    screens = Path(os.environ.get("CHESSBOOK_SCREENS", ROOT / "output" / "screens" / "device_library"))
    try:
        env = dict(os.environ, NODE_PATH=NODE_PATH)
        proc = subprocess.run([NODE, str(ROOT / "tests" / "device_library_e2e.js"),
                               f"http://127.0.0.1:{server.server_address[1]}/", *books[:2],
                               str(tmp_path / "work"), str(screens)],
                              capture_output=True, text=True, env=env, timeout=7200)
    finally:
        server.shutdown()
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, proc.stdout[-3000:] + proc.stderr[-3000:]
    res = json.loads(lines[-1])
    failed = [c for c in res["checks"] if not c["ok"]]
    assert res["ok"], (res.get("failure"), failed, res["errors"])
    assert res["errors"] == []
    names = {c["name"] for c in res["checks"]}
    assert {"the PDF, the reading and the record are kept in IndexedDB",
            "the book opens without being read again",
            "the book opens at the stored page and move",
            "the book holds the correction",
            "the book file holds the book, its reading, its cover and its record",
            "the book from the file opens without being read",
            "the book from the file holds the correction",
            "the book file carries the bookmark",
            "the library on the other device lists the bookmark under the book",
            "the bookmark in the library opens the book at its page and move",
            "the newer corrections of a book file win, and the user is told",
            "a removed book leaves nothing behind",
            "a new book opens at its first page",
            "the pictures of the pages come from the device's store",
            "the pictures of the pages shown are kept on the device",
            "the parts of the reading are kept while it goes on",
            "the reading goes on from the parts kept", "the finished reading replaces the parts",
            "a stored book draws no thumbnails again",
            "offline, the app opens and the book shows its page"} <= names
    print(json.dumps(res["timings"], indent=1))
    print(json.dumps(res["storage"], indent=1))
    print("\n".join(res["notes"]))
