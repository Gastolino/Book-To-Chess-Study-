"""The browser app end to end: Pyodide in the page's worker, in Chromium
(tests/app_e2e.js drives it).

The test needs a local Pyodide distribution and the PyMuPDF and python-chess
wheels for Pyodide, since the CDN may be out of reach:

    CHESSBOOK_PYODIDE   a Pyodide 0.29 folder (with pyodide.js and pyodide-lock.json)
    CHESSBOOK_WHEELS    a folder holding pymupdf-*.whl and chess-*.whl

It is skipped when they are missing. The book is the generated test book with
a garbled game (fast, and with every kind of correction), or the PDF that
CHESSBOOK_APP_BOOK names (corpus/gpa.pdf exercises the piece-symbol batches
across chapters). numpy and OpenCV need not be there: the app then reads the
book without board reading.
"""
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
                             ".mjs": "text/javascript", ".whl": "application/zip"})

    def log_message(self, *args):
        pass


@pytest.mark.skipif(not _ready(), reason="no local Pyodide folder, Pyodide wheels, node or Playwright")
def test_app_in_chromium(tmp_path):
    site = tmp_path / "site"
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(site),
                    "--local", str(PYODIDE), "--pymupdf", str(_wheel("pymupdf-*.whl")),
                    "--chess", str(_wheel("chess-*.whl"))], check=True)
    book = os.environ.get("CHESSBOOK_APP_BOOK")
    if not book:
        from test_assemble import make_book
        from test_corrections import GARBLED, NOTE
        book = str(make_book(tmp_path / "garbled.pdf", game=GARBLED, note7=NOTE))
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    screens = ROOT / "output" / "screens" / "app"
    try:
        env = dict(os.environ, NODE_PATH=NODE_PATH)
        proc = subprocess.run([NODE, str(ROOT / "tests" / "app_e2e.js"),
                               f"http://127.0.0.1:{server.server_address[1]}/", book, str(screens)],
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
    assert {"the following moves turn decoded again without navigation",
            "the contents page counts the corrections",
            "the move correction persists across chapters",
            "reading the book again applies the stored corrections"} <= names
    assert {c["mode"] for c in res["checks"]} >= {"desktop", "phone"}
    print(json.dumps(res["timings"], indent=1))
    print("\n".join(res["notes"]))
