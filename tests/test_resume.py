"""Coming back to the open book after the system closed the app: the page
keeps a small record of where the reader was (SESSION in
tools/build_web.py), and when it loads again within a day it opens the book
at that chapter, page, move and scroll from the stored reading, skipping
the library page (tests/resume_e2e.js, on the static site with the library
in the browser).

The test needs a local Pyodide distribution and the PyMuPDF and python-chess
wheels for Pyodide (CHESSBOOK_PYODIDE, CHESSBOOK_WHEELS, as
tests/test_app_e2e.py), node and Playwright; it is skipped without them.
The book is the generated test book with a garbled game and a second
chapter, or the PDF that CHESSBOOK_RESUME_BOOK names."""
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


def test_the_shell_keeps_a_session_record(tmp_path):
    """The shell writes the record on changes and when the page is hidden,
    reads the reader's view from its page, and resumes through the library;
    the manifest's start page is the page that resumes; nothing stops the
    browser from keeping the page alive in its back-forward cache (no
    unload handler)."""
    site = tmp_path / "site"
    wheel = tmp_path / "chess-1.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(site),
                    "--pymupdf-url", "https://example.invalid/pymupdf.whl", "--chess", str(wheel)],
                   check=True, capture_output=True)
    page = (site / "index.html").read_text(encoding="utf-8")
    assert '"chessbook-session"' in page and "LIMIT = 24 * 3600 * 1000" in page
    for ev in ('"visibilitychange"', '"pagehide"', '"freeze"'):
        assert ev in page
    assert '"unload"' not in page and "beforeunload" not in page
    assert "w.readerView()" in page and "LIB.start(SESSION.pending())" in page
    assert 'id="resume"' in page and "Back to " in page
    manifest = json.loads((site / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["start_url"] == "./" and manifest["scope"] == "./"
    lib = (site / "library.js").read_text(encoding="utf-8")
    assert "api.start = async function (resume)" in lib and "api.leaving = function (rec)" in lib
    assert 'window.addEventListener("pagehide", () => flush(true));' in lib
    reader = (ROOT / "chessbook" / "reader.py").read_text(encoding="utf-8")
    assert "window.readerView = readerView;" in reader and "&v=" in reader
    assert '"unload"' not in reader


@pytest.mark.skipif(not _ready(), reason="no local Pyodide folder, Pyodide wheels, node or Playwright")
def test_resume_end_to_end(tmp_path):
    site = tmp_path / "site"
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(site),
                    "--local", str(PYODIDE), "--pymupdf", str(_wheel("pymupdf-*.whl")),
                    "--chess", str(_wheel("chess-*.whl"))], check=True)
    book = os.environ.get("CHESSBOOK_RESUME_BOOK")
    if not book:
        from test_assemble import make_book
        from test_corrections import GARBLED, NOTE
        book = str(make_book(tmp_path / "garbled_games.pdf", game=GARBLED, note7=NOTE, second=True))
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    screens = Path(os.environ.get("CHESSBOOK_SCREENS", ROOT / "output" / "screens" / "resume"))
    try:
        env = dict(os.environ, NODE_PATH=NODE_PATH)
        proc = subprocess.run([NODE, str(ROOT / "tests" / "resume_e2e.js"),
                               f"http://127.0.0.1:{server.server_address[1]}/", book,
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
    assert {"the session record holds the book, chapter, page, move and view",
            "the start page says where the app goes back to, with a Library link",
            "the top bar says where the app came back to",
            "the book opened from the stored reading, not read again",
            "the reader is at the same scroll, in the page and in the move list",
            "a record older than a day shows the library",
            "closed while the book was read: the chapter opens at the page, and the app says the book is read again",
            "without a library the start page says the book has to be chosen again",
            "the book chosen again opens at the place"} <= names
    print(json.dumps(res["timings"], indent=1))
    print("\n".join(res["notes"]))
