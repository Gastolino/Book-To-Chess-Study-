"""The library of the Cloudflare site: a stored reading opens a book without
reading it again (web/driver.py save_reading and restore), the server's
functions refuse a request without Cloudflare Access (tests/server_test.mjs),
and the whole library runs end to end under `wrangler pages dev`
(tests/library_e2e.js)."""
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "tests"))

NODE = shutil.which("node") or "/opt/node22/bin/node"
NODE_PATH = "/opt/node22/lib/node_modules"


def _driver(tmp_path, monkeypatch):
    import driver
    monkeypatch.setattr(driver, "OUT", tmp_path / "out")
    monkeypatch.setattr(driver, "CFG", tmp_path / "cfg")
    return driver


def _same(a, b):
    """Two book dicts are the same book (the timings aside)."""
    a, b = dict(a), dict(b)
    a.pop("stats", None)
    b.pop("stats", None)
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@pytest.fixture
def garbled(tmp_path):
    from test_assemble import make_book
    from test_corrections import GARBLED, NOTE
    return make_book(tmp_path / "garbled.pdf", game=GARBLED, note7=NOTE, second=True)


def _drain(driver):
    events = []
    while True:
        out = json.loads(driver.step())
        events += out["events"]
        if out["done"]:
            return events


def test_a_stored_reading_opens_the_same_book(tmp_path, monkeypatch, garbled):
    driver = _driver(tmp_path, monkeypatch)
    driver.process(str(garbled), lambda *_: None)
    built = json.loads(json.dumps(driver.STATE["book"]))
    data = driver.save_reading()
    assert data.startswith(driver.READING_MAGIC)
    saved = tmp_path / "reading.bin"
    saved.write_bytes(data)
    assert driver.reading_header(saved)["version"] == driver.VERSION

    driver.STATE.clear()
    events = json.loads(driver.restore(str(garbled), str(saved)))
    assert [e["type"] for e in events] == ["index"]
    assert events[0]["pages"] == built["page_count"] and events[0]["title"] == built["title"]
    assert _same(driver.STATE["book"], built)
    rest = _drain(driver)
    assert rest[-1]["type"] == "done" and rest[-1]["restored"]
    assert any(e["type"] == "thumbs" for e in rest)
    # every chapter reader builds from the stored reading
    for ch in built["chapters"]:
        if ch["end"] >= ch["start"]:
            html = driver.chapter(ch["file"], lambda *_: None)
            assert "<html" in html
    assert "<html" in driver.index()


def test_corrections_apply_live_to_a_stored_reading(tmp_path, monkeypatch, garbled):
    """A correction made after the reading was stored (on another device, or
    live in the reader) gives the book a fresh reading with it gives."""
    driver = _driver(tmp_path, monkeypatch)
    fix = json.dumps({"version": 1, "glyphs": {"tLl": "N"}})
    driver.process(str(garbled), lambda *_: None, None, fix)
    fresh = json.loads(json.dumps(driver.STATE["book"]))
    assert fresh["corrections"]["glyphs"] == {"tLl": "N"}

    driver.process(str(garbled), lambda *_: None)
    plain = json.loads(json.dumps(driver.STATE["book"]))
    assert not _same(plain, fresh)
    saved = tmp_path / "reading.bin"
    saved.write_bytes(driver.save_reading())

    # the corrections arrive with the stored reading (made on another device)
    driver.STATE.clear()
    driver.restore(str(garbled), str(saved), None, fix)
    assert _same(driver.STATE["book"], fresh)

    # and live, in an open chapter
    driver.STATE.clear()
    driver.restore(str(garbled), str(saved))
    _drain(driver)
    assert _same(driver.STATE["book"], plain)
    name = next(c["file"] for c in plain["chapters"] if c["end"] >= c["start"] and c["index"] > 0)
    driver.chapter(name, lambda *_: None)
    out = json.loads(driver.correct(fix, name))
    assert out["patch"] is not None
    while out["pending"]:
        out = json.loads(driver.correct_more(json.dumps(out["pending"][:1]), name))
    assert _same(driver.STATE["book"], fresh)


def test_a_reading_of_another_version_or_selection_is_refused(tmp_path, monkeypatch, garbled):
    driver = _driver(tmp_path, monkeypatch)
    driver.process(str(garbled), lambda *_: None)
    saved = tmp_path / "reading.bin"
    saved.write_bytes(driver.save_reading())
    sel = json.dumps({"pages": {"exclude": [[5, 5]]}, "diagrams": {"exclude": [], "include": []}})
    out = json.loads(driver.restore(str(garbled), str(saved), sel))
    assert out[0]["type"] == "stale" and "selection" in out[0]["why"]
    monkeypatch.setattr(driver, "VERSION", "0" * 16)
    out = json.loads(driver.restore(str(garbled), str(saved)))
    assert out[0]["type"] == "stale" and "version" in out[0]["why"]
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"not a reading")
    assert json.loads(driver.restore(str(garbled), str(bad)))[0]["type"] == "stale"


def test_cover_is_a_small_jpeg(tmp_path, monkeypatch, garbled):
    driver = _driver(tmp_path, monkeypatch)
    data = driver.cover(str(garbled))
    assert data[:3] == b"\xff\xd8\xff" and len(data) < 60000


# ---------------------------------------------------------------- the server

def _node_ready():
    return Path(NODE).exists()


@pytest.mark.skipif(not _node_ready(), reason="node is missing")
def test_server_functions_refuse_requests_without_access():
    proc = subprocess.run([NODE, "--test", str(ROOT / "tests" / "server_test.mjs")],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-4000:]


# The site run locally: `wrangler pages dev` simulates R2 and D1 on disk.
# wrangler comes from CHESSBOOK_WRANGLER, the project's node_modules (npm
# install) or the PATH.
def _wrangler():
    for p in (os.environ.get("CHESSBOOK_WRANGLER"), ROOT / "node_modules" / ".bin" / "wrangler",
              shutil.which("wrangler")):
        if p and Path(p).exists():
            return str(p)
    return None


WRANGLER = _wrangler()
USER = "reader@example.com"
# the local site is asked directly, never through a proxy of the environment
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Site:
    """`wrangler pages dev` serving site_dir with the functions of this project."""

    def __init__(self, site_dir, state_dir):
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}/"
        env = dict(os.environ, WRANGLER_SEND_METRICS="false", CI="1")
        subprocess.run([WRANGLER, "d1", "execute", "DB", "--local", "--file",
                        str(ROOT / "server" / "schema.sql"), "--persist-to", str(state_dir)],
                       cwd=ROOT, check=True, capture_output=True, env=env, timeout=300)
        self.log = open(state_dir / "wrangler.log", "w")
        # a session of its own, so that the whole group (wrangler and workerd) stops together
        self.proc = subprocess.Popen(
            [WRANGLER, "pages", "dev", str(site_dir), "--ip", "127.0.0.1", "--port", str(self.port),
             "--binding", f"DEV_USER={USER}", "--persist-to", str(state_dir)],
            cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        t0 = time.time()
        while True:
            try:
                with _OPENER.open(self.url + "api/books", timeout=2) as r:
                    if r.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                pass
            if self.proc.poll() is not None or time.time() - t0 > 120:
                self.stop()
                raise RuntimeError("wrangler pages dev did not start: " +
                                   (state_dir / "wrangler.log").read_text()[-3000:])
            time.sleep(0.5)

    def stop(self):
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
        self.log.close()

    def call(self, method, path, body=None, headers=None):
        req = urllib.request.Request(self.url + "api/" + path, data=body, method=method,
                                     headers=headers or {})
        try:
            with _OPENER.open(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()


@pytest.mark.skipif(not WRANGLER, reason="wrangler is missing (npm install)")
def test_the_server_under_wrangler(tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    site = Site(site_dir, tmp_path / "state")
    try:
        assert json.loads(site.call("GET", "books")[1]) == {"books": [], "maxPdf": 95 * 1048576,
                                                           "user": USER}
        pdf = b"%PDF-1.4 a little book " * 1000
        bid = hashlib.sha256(pdf).hexdigest()
        wrong = hashlib.sha256(b"another").hexdigest()
        status, body = site.call("PUT", "books/" + wrong, pdf, {"x-file-name": "little%20book.pdf"})
        assert status == 400 and b"damaged" in body
        status, body = site.call("PUT", "books/" + bid, pdf, {"x-file-name": "little%20book.pdf"})
        assert status == 201, body
        assert site.call("PUT", "books/" + bid, pdf)[0] == 200          # already there
        assert site.call("GET", "books/" + bid + "/pdf") == (200, pdf)
        assert site.call("GET", "books/" + wrong + "/pdf")[0] == 404
        assert site.call("GET", "books/nothex/pdf")[0] == 404
        # the later copy of the corrections wins
        put = lambda data, t: json.loads(site.call(  # noqa: E731
            "PUT", f"books/{bid}/corrections", json.dumps({"data": data, "updated": t}).encode())[1])
        assert put({"corrections": {"glyphs": {"x": "N"}}}, 2000)["updated"] == 2000
        assert put({"corrections": {}}, 1000) == {"data": {"corrections": {"glyphs": {"x": "N"}}},
                                                  "updated": 2000}
        assert put(None, 3000) == {"data": None, "updated": 3000}
        status, body = site.call("PUT", f"books/{bid}/position", json.dumps(
            {"position": {"chapter": "ch02.html", "page": 9, "node": "n4"}, "updated": 5000}).encode())
        assert json.loads(body)["book"]["position"] == {"chapter": "ch02.html", "page": 9,
                                                        "node": "n4", "updated": 5000}
        site.call("PUT", f"books/{bid}/position", json.dumps(
            {"position": {"page": 1}, "updated": 4000}).encode())
        book = json.loads(site.call("GET", "books")[1])["books"][0]
        assert book["position"]["page"] == 9 and book["fileName"] == "little book.pdf"
        assert book["reading"] is None
        gz = b"\x1f\x8b reading"
        status, body = site.call("PUT", f"books/{bid}/reading", gz,
                                 {"x-reading-version": "abc123", "x-reading-size": "99"})
        assert json.loads(body)["book"]["reading"]["version"] == "abc123"
        assert site.call("GET", f"books/{bid}/reading") == (200, gz)
        assert site.call("DELETE", f"books/{bid}")[0] == 200
        assert json.loads(site.call("GET", "books")[1])["books"] == []
        assert site.call("GET", f"books/{bid}/reading")[0] == 404
    finally:
        site.stop()


# ---------------------------------------------------------------- end to end

PYODIDE = Path(os.environ.get("CHESSBOOK_PYODIDE", ROOT / "local" / "pyodide"))
WHEELS = Path(os.environ.get("CHESSBOOK_WHEELS", ROOT / "local" / "wheels"))


def _wheel(pattern):
    found = sorted(WHEELS.glob(pattern)) if WHEELS.is_dir() else []
    return found[-1] if found else None


def _e2e_ready():
    return (WRANGLER and (PYODIDE / "pyodide.js").exists() and _wheel("pymupdf-*.whl")
            and _wheel("chess-*.whl") and Path(NODE).exists() and Path(NODE_PATH, "playwright").exists())


@pytest.mark.skipif(not _e2e_ready(), reason="no wrangler, local Pyodide folder, Pyodide wheels, "
                                             "node or Playwright")
def test_library_end_to_end(tmp_path):
    """tests/library_e2e.js against the built site under wrangler. The books are
    the generated test book with a garbled game and a second book, or the two
    PDFs that CHESSBOOK_LIBRARY_BOOKS names (separated by a comma)."""
    site_dir = tmp_path / "site"
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(site_dir),
                    "--local", str(PYODIDE), "--pymupdf", str(_wheel("pymupdf-*.whl")),
                    "--chess", str(_wheel("chess-*.whl"))], check=True)
    books = [b for b in os.environ.get("CHESSBOOK_LIBRARY_BOOKS", "").split(",") if b]
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
    screens = Path(os.environ.get("CHESSBOOK_SCREENS", ROOT / "output" / "screens" / "library"))
    site = Site(site_dir, tmp_path / "state")
    try:
        env = dict(os.environ, NODE_PATH=NODE_PATH)
        proc = subprocess.run([NODE, str(ROOT / "tests" / "library_e2e.js"), site.url, *books[:2],
                               str(screens)], capture_output=True, text=True, env=env, timeout=7200)
    finally:
        site.stop()
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, proc.stdout[-3000:] + proc.stderr[-3000:]
    res = json.loads(lines[-1])
    failed = [c for c in res["checks"] if not c["ok"]]
    assert res["ok"], (res.get("failure"), failed, res["errors"])
    assert res["errors"] == []
    names = {c["name"] for c in res["checks"]}
    assert {"the correction reaches the server",
            "the page and the move last read reach the server",
            "the second device opens the book without reading it again",
            "the second device opens at the stored page and move",
            "the second device holds the correction",
            "removed books are gone from the library"} <= names
    print(json.dumps(res["timings"], indent=1))
    print("\n".join(res["notes"]))
