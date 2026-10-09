"""The thread in the browser app end to end (tests/thread_e2e.js): Pyodide in
the page's worker, in Chromium. The reader turns reading on from the row
under the board, makes the move of a box the program could not read on the
board, gives the move the text lacks, and joins the moves the program then
reads on, until the line holds the whole game (chessbook/review_js.py, "the
thread"). The book is the generated Wells - Shirov book of
tests/test_thread.py.

The test needs a local Pyodide distribution and the PyMuPDF and python-chess
wheels for Pyodide, as tests/test_app_e2e.py does, and is skipped without
them.
"""
import functools
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_app_e2e import NODE, NODE_PATH, PYODIDE, _Handler, _ready, _wheel  # noqa: E402


@pytest.mark.skipif(not _ready(), reason="no local Pyodide folder, Pyodide wheels, node or Playwright")
def test_the_reader_threads_the_line_in_the_app(tmp_path):
    from test_thread import make_wells
    site = tmp_path / "site"
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(site),
                    "--local", str(PYODIDE), "--pymupdf", str(_wheel("pymupdf-*.whl")),
                    "--chess", str(_wheel("chess-*.whl"))], check=True)
    book = make_wells(tmp_path / "wells.pdf")
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    screens = ROOT / "output" / "screens" / "thread"
    try:
        env = dict(os.environ, NODE_PATH=NODE_PATH)
        proc = subprocess.run([NODE, str(ROOT / "tests" / "thread_e2e.js"),
                               f"http://127.0.0.1:{server.server_address[1]}/", str(book), str(screens)],
                              capture_output=True, text=True, env=env, timeout=1800)
    finally:
        server.shutdown()
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, proc.stdout[-3000:] + proc.stderr[-3000:]
    res = json.loads(lines[-1])
    failed = [c for c in res["checks"] if not c["ok"]]
    assert res["ok"], (res.get("failure"), failed, res["errors"])
    assert res["errors"] == []
    names = {c["name"] for c in res["checks"]}
    assert {"turning reading on under the board turns the pencil on",
            "Cancel closes the sheet and leaves no joining",
            "Close ends the join",
            "the line holds the whole game",
            "Close leaves no sheet, no thread and no joining"} <= names
    assert sum(n.startswith("Show reading sits under the board") for n in names) == 4
    assert sum(n.startswith("a Show reading is on screen") for n in names) == 4
    print(json.dumps(res["timings"], indent=1))
