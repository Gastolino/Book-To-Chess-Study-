"""The thread in the browser app end to end (tests/thread_e2e.js): Pyodide in
the page's worker, in Chromium. The reader turns reading on from the row
under the board and makes the move of a box the program could not read on the
board; the program then reads on by itself ({readOn}): it supplies the move
the text lacks and joins the moves after it, until the line holds the whole
game with no further tap (chessbook/review_js.py, "the thread"). Undo takes it
all back, a reload keeps the program's corrections, and the reader's removal
of one is stored. The book is the generated Wells - Shirov book of
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


def _run(script, site, book, screens):
    """Serve site and run the e2e script on book: its JSON result."""
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = dict(os.environ, NODE_PATH=NODE_PATH)
        proc = subprocess.run([NODE, str(ROOT / "tests" / script),
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
    return res


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    site = tmp_path_factory.mktemp("app") / "site"
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(site),
                    "--local", str(PYODIDE), "--pymupdf", str(_wheel("pymupdf-*.whl")),
                    "--chess", str(_wheel("chess-*.whl"))], check=True)
    return site


@pytest.mark.skipif(not _ready(), reason="no local Pyodide folder, Pyodide wheels, node or Playwright")
def test_the_reader_threads_the_line_in_the_app(site, tmp_path):
    from test_thread import make_wells
    book = make_wells(tmp_path / "wells.pdf")
    res = _run("thread_e2e.js", site, book, ROOT / "output" / "screens" / "thread")
    names = {c["name"] for c in res["checks"]}
    assert {"turning reading on under the board turns the pencil on",
            "Cancel closes the sheet and leaves no joining",
            "Close ends the join",
            "the sheet said, line by line: reading on, then how far it read and that the line reads to its end",
            "the line holds the whole game, with no further tap",
            "Undo takes back the reader's move and the program's join after it, and asks for the move again",
            "while the program reads on, the board takes no move and a tap waits; then the tap is taken",
            "Cancel leaves no sheet, no thread and no joining",
            "after a reload the program's entries are kept, and the line holds the whole game",
            "removing it stores it as declined, and the line ends at 5.Qc1 again"} <= names
    assert sum(n.startswith("Show reading sits under the board") for n in names) == 4
    assert sum(n.startswith("a Show reading is on screen") for n in names) == 4
    print(json.dumps(res["timings"], indent=1))


@pytest.mark.skipif(not _ready(), reason="no local Pyodide folder, Pyodide wheels, node or Playwright")
def test_reading_on_stops_for_the_reader_in_the_app(site, tmp_path):
    """tests/readon_e2e.js: the program reads on to a move the text lacks and
    asks for it; the reader makes it and joins what follows, and the line
    holds the whole game (tests/test_read_on.py's book, whose diagram the app
    reads no position from)."""
    from test_read_on import make_long
    book = make_long(tmp_path / "wells.pdf")
    res = _run("readon_e2e.js", site, book, ROOT / "output" / "screens" / "thread")
    names = {c["name"] for c in res["checks"]}
    assert {"a reading on that fails says why in one line, keeps the correction as made, and goes on without reading on",
            "the program read on to Black's 12th move, which it leaves to the reader",
            "the page turned forward to 13.Qe3, which is outlined",
            "after 12...Qc2 the sheet offers 13.Qe3 to join",
            "the join is stored with Qc2 before it, as the reader's, and the line holds the whole game"} <= names
    print(json.dumps(res["timings"], indent=1))
