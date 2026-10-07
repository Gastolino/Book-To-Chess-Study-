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
    assert data.startswith(driver.READING_MAGIC2)
    saved = tmp_path / "reading.bin"
    saved.write_bytes(data)
    assert driver.reading_header(saved)["version"] == driver.VERSION

    driver.STATE.clear()
    events = json.loads(driver.restore(str(garbled), str(saved)))
    assert [e["type"] for e in events] == ["index"]
    assert events[0]["pages"] == built["page_count"] and events[0]["title"] == built["title"]
    assert _same(driver.STATE["book"], built)
    # the thumbnails come with the reading: none is drawn again, and nothing is saved again
    assert len(driver.STATE["thumbs"]) == built["page_count"]
    rest = _drain(driver)
    assert rest[-1]["type"] == "done" and rest[-1]["restored"] and not rest[-1]["resave"]
    assert not any(e["type"] == "thumbs" for e in rest)
    # every chapter reader builds from the stored reading
    for ch in built["chapters"]:
        if ch["end"] >= ch["start"]:
            html = driver.chapter(ch["file"], lambda *_: None)
            assert "<html" in html
    assert "<html" in driver.index()


def test_a_reading_without_thumbnails_is_saved_again_with_them(tmp_path, monkeypatch, garbled):
    """A reading stored before the thumbnails went into it draws them once,
    asks to be saved again, and keeps the version of the code that made it
    (so that the app still offers to read it with today's code)."""
    driver = _driver(tmp_path, monkeypatch)
    driver.process(str(garbled), lambda *_: None)
    pages = driver.STATE["book"]["page_count"]
    driver.STATE["thumbs"] = {}
    driver.STATE["reading_version"] = "older-code"
    old = tmp_path / "old.bin"
    old.write_bytes(driver.save_reading())

    driver.STATE.clear()
    events = json.loads(driver.restore(str(garbled), str(old)))
    assert events[0]["outdated"] == "code"
    rest = _drain(driver)
    assert sum(len(e["thumbs"]) for e in rest if e["type"] == "thumbs") == pages
    assert rest[-1]["resave"]
    again = tmp_path / "again.bin"
    again.write_bytes(driver.save_reading())
    assert driver.reading_version() == "older-code"
    assert driver.reading_header(again)["version"] == "older-code"

    driver.STATE.clear()
    driver.restore(str(garbled), str(again))
    assert len(driver.STATE["thumbs"]) == pages
    assert not any(e["type"] == "thumbs" for e in _drain(driver))


def _read_until(driver, path, stop=None, partial=None, selection=None):
    """Read the book at path; at each checkpoint keep checkpoint()'s bytes.
    With stop (a part name) the reading ends there, as a reading the app
    lost would. Returns (the checkpoints, the events)."""
    notes = json.loads(driver.start(path, selection, None, partial))
    kept, events = {}, list(notes)
    while True:
        out = json.loads(driver.step())
        events += out["events"]
        for ev in out["events"]:
            if ev["type"] == "checkpoint":
                part = "boards" if "boards" in ev["parts"] else "stage1"
                kept[part] = driver.checkpoint()
                if stop == part:
                    return kept, events
        if out["done"]:
            return kept, events


def test_a_reading_cut_short_goes_on_from_its_parts(tmp_path, monkeypatch, garbled):
    """The parts of a reading under way (Stage 1, then the board readings)
    come out as checkpoints; a reading that starts from them reads neither
    again and makes the same book as a reading from the start."""
    driver = _driver(tmp_path, monkeypatch)
    kept, events = _read_until(driver, str(garbled))
    assert [e["parts"] for e in events if e["type"] == "checkpoint"] == [["stage1"], ["boards", "stage1"]]
    full = json.loads(json.dumps(driver.STATE["book"]))
    assert all(v.startswith(driver.PARTIAL_MAGIC) for v in kept.values())

    for part in ("stage1", "boards"):
        # a fresh worker: nothing of the first reading is left in its files
        shutil.rmtree(tmp_path / "out")
        driver.STATE.clear()
        saved = tmp_path / (part + ".bin")
        saved.write_bytes(kept[part])
        said = []
        import stage1_inspect
        from chessbook import assemble
        ran = {"stage1": 0, "boards": 0}
        real_s1, real_b = stage1_inspect.analyse_steps, assemble.read_boards_steps

        def s1(*a, **k):
            ran["stage1"] += 1
            return real_s1(*a, **k)

        def rb(*a, **k):
            ran["boards"] += 1
            return (yield from real_b(*a, **k))
        monkeypatch.setattr(stage1_inspect, "analyse_steps", s1)
        monkeypatch.setattr(assemble, "read_boards_steps", rb)
        kept2, events = _read_until(driver, str(garbled), partial=str(saved))
        said = [e["text"] for e in events if e["type"] == "progress"]
        assert any("taken up where it stopped" in t for t in said), said
        assert ran["stage1"] == 0
        assert ran["boards"] == (0 if part == "boards" else 1)
        # the parts it had are not sent again; the ones it made are
        sent = [e["parts"] for e in events if e["type"] == "checkpoint"]
        assert sent == ([] if part == "boards" else [["boards", "stage1"]])
        assert _same(driver.STATE["book"], full)
        monkeypatch.setattr(stage1_inspect, "analyse_steps", real_s1)
        monkeypatch.setattr(assemble, "read_boards_steps", real_b)


def test_parts_of_other_code_or_another_selection_are_not_used(tmp_path, monkeypatch, garbled):
    driver = _driver(tmp_path, monkeypatch)
    kept, _ = _read_until(driver, str(garbled), stop="boards")
    saved = tmp_path / "boards.bin"
    saved.write_bytes(kept["boards"])
    job = type("J", (), {"ctx": {}})()
    pdf = Path(str(garbled))
    # another selection: Stage 1 is taken, the board readings are not
    assert driver._resume_parts(pdf, saved, '{"pages": [1]}', job) == {"stage1"}
    assert "stored_readings" not in job.ctx
    assert driver._resume_parts(pdf, saved, None, job) == {"stage1", "boards"}
    # other reading code, another book, or a damaged file: nothing is taken
    monkeypatch.setattr(driver, "VERSION", "other-code")
    assert driver._resume_parts(pdf, saved, None, type("J", (), {"ctx": {}})()) == set()
    monkeypatch.undo()
    driver = _driver(tmp_path, monkeypatch)
    assert driver._resume_parts(pdf.with_name("other.pdf"), saved, None, job) == set()
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"junk")
    assert driver._resume_parts(pdf, bad, None, job) == set()


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


def test_a_reading_of_another_selection_is_refused(tmp_path, monkeypatch, garbled):
    driver = _driver(tmp_path, monkeypatch)
    driver.process(str(garbled), lambda *_: None)
    saved = tmp_path / "reading.bin"
    saved.write_bytes(driver.save_reading())
    sel = json.dumps({"pages": {"exclude": [[5, 5]]}, "diagrams": {"exclude": [], "include": []}})
    out = json.loads(driver.restore(str(garbled), str(saved), sel))
    assert out[0]["type"] == "stale" and "selection" in out[0]["why"]
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"not a reading")
    assert json.loads(driver.restore(str(garbled), str(bad)))[0]["type"] == "stale"


def test_a_change_of_the_reader_keeps_the_stored_reading(tmp_path):
    """The version a stored reading names is a digest of the reading code
    alone: a change of the reader, its scripts or its look leaves it, and a
    change of the code that reads the book changes it."""
    import driver
    root = tmp_path / "copy"
    shutil.copytree(ROOT / "chessbook", root / "chessbook",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT / "stage1_inspect.py", root / "stage1_inspect.py")
    v0 = driver._version(root=root)
    assert v0 == driver.VERSION
    for name in ("reader.py", "review_js.py", "engine_js.py", "style.py", "progressive.py"):
        f = root / "chessbook" / name
        f.write_text(f.read_text(encoding="utf-8") + "\n# a change of the reader\n", encoding="utf-8")
    assert driver._version(root=root) == v0
    for name in ("chessbook/reader.py", "chessbook/style.py", "web/library.js", "tools/build_web.py"):
        assert name not in driver.READING_FILES
    f = root / "chessbook" / "movetext.py"
    f.write_text(f.read_text(encoding="utf-8") + "\n# a change of the reading\n", encoding="utf-8")
    assert driver._version(root=root) != v0


def test_a_reading_of_other_reading_code_opens_and_offers_a_new_reading(tmp_path, monkeypatch, garbled):
    """A stored reading that other reading code made opens all the same,
    marked outdated: the app offers Read again, and forces nothing."""
    driver = _driver(tmp_path, monkeypatch)
    driver.process(str(garbled), lambda *_: None)
    built = json.loads(json.dumps(driver.STATE["book"]))
    saved = tmp_path / "reading.bin"
    saved.write_bytes(driver.save_reading())
    monkeypatch.setattr(driver, "VERSION", "0" * 16)
    out = json.loads(driver.restore(str(garbled), str(saved)))
    assert out[0]["type"] == "index" and out[0]["outdated"] == "code"
    assert _same(driver.STATE["book"], built)
    name = next(c["file"] for c in built["chapters"] if c["end"] >= c["start"] and c["index"] > 0)
    assert "<html" in driver.chapter(name, lambda *_: None)
    # corrections still apply: the builder's state loaded
    res = json.loads(driver.correct(json.dumps({"version": 1, "glyphs": {"tLl": "N"}}), name))
    assert res["patch"] is not None
    # the reading of today opens without a note
    monkeypatch.undo()
    driver = _driver(tmp_path, monkeypatch)
    out = json.loads(driver.restore(str(garbled), str(saved)))
    assert out[0]["type"] == "index" and out[0]["outdated"] is None


def test_a_reading_whose_builder_cannot_load_opens_for_reading(tmp_path, monkeypatch, garbled):
    """The builder's state of a stored reading is pickled apart from the
    book: when this program cannot load it, the book opens from the book
    alone, and a correction says that the book needs reading again."""
    import pickle
    driver = _driver(tmp_path, monkeypatch)
    driver.process(str(garbled), lambda *_: None)
    built = json.loads(json.dumps(driver.STATE["book"]))
    data = driver.save_reading()
    head, _ = data[len(driver.READING_MAGIC2):].split(b"\n", 1)
    broken = (driver.READING_MAGIC2 + head + b"\n" + pickle.dumps(driver.STATE["book"])
              + b"\x80\x05c" + b"chessbook.nothing\nBuilder\n.")
    saved = tmp_path / "reading.bin"
    saved.write_bytes(broken)
    out = json.loads(driver.restore(str(garbled), str(saved)))
    assert out[0]["type"] == "index" and out[0]["outdated"] == "state"
    assert _same(driver.STATE["book"], built)
    _drain(driver)
    name = next(c["file"] for c in built["chapters"] if c["end"] >= c["start"] and c["index"] > 0)
    assert "<html" in driver.chapter(name, lambda *_: None)
    with pytest.raises(ValueError, match="Read again"):
        driver.correct(json.dumps({"version": 1, "glyphs": {"tLl": "N"}}), name)
    # a reading of the first format, which held one pickle, still opens
    old = driver.READING_MAGIC + head + b"\n" + pickle.dumps({"book": built, "keep": None})
    saved.write_bytes(old)
    out = json.loads(driver.restore(str(garbled), str(saved)))
    assert out[0]["type"] == "index" and out[0]["outdated"] == "state"


def test_pages_are_drawn_ten_at_a_time(tmp_path, monkeypatch, garbled):
    """The chapter readers of the app hold no page pictures; draw() gives the
    pictures of the pages asked for, at the resolution of the screen."""
    driver = _driver(tmp_path, monkeypatch)
    driver.process(str(garbled), lambda *_: None)
    name = next(c["file"] for c in driver.STATE["book"]["chapters"] if c["end"] >= c["start"] and c["index"] > 0)
    html = driver.chapter(name, lambda *_: None)
    assert '<script type="application/json" id="images">{}</script>' in html
    data = driver.draw(json.dumps([1, 2, 3, 999]), "large")
    head, body = data.split(b"\n", 1)
    head = json.loads(head)
    assert [p for p, _ in head["pages"]] == [1, 2, 3] and head["dpi"] == driver.DRAW["large"][0]
    assert body[:3] == b"\xff\xd8\xff" and len(body) == sum(n for _, n in head["pages"])
    small = driver.draw(json.dumps([1]), "small")
    assert len(small.split(b"\n", 1)[1]) < head["pages"][0][1]
    # the chapter about to be turned to is built without becoming the open one
    other = next(c["file"] for c in driver.STATE["book"]["chapters"] if c["end"] >= c["start"] and c["file"] != name)
    driver.chapter(other, lambda *_: None, prepare=True)
    assert driver.STATE["open"] == name


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
        # the bookmarks: the same rule, and the library lists them with the book
        marks = {"bookmarks": [{"page": 31, "node": "n7", "chapter": "ch02.html", "at": 2500}]}
        status, body = site.call("PUT", f"books/{bid}/bookmarks",
                                 json.dumps({"data": marks, "updated": 2500}).encode())
        assert status == 200 and json.loads(body) == {"data": marks, "updated": 2500}
        status, body = site.call("PUT", f"books/{bid}/bookmarks",
                                 json.dumps({"data": {"bookmarks": []}, "updated": 2400}).encode())
        assert json.loads(body)["data"] == marks
        assert json.loads(site.call("GET", f"books/{bid}/bookmarks")[1]) == {"data": marks, "updated": 2500}
        listed = json.loads(site.call("GET", "books")[1])["books"][0]
        assert listed["bookmarks"] == {"data": marks, "updated": 2500}
        assert site.call("PUT", f"books/{bid}/notes", b"{}")[0] == 405
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
        assert site.call("GET", f"books/{bid}/bookmarks")[0] == 404
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
            "the place reaches the server at once when the page is hidden",
            "the page loaded again comes back to the book at the move, from the server's library",
            "removed books are gone from the library"} <= names
    print(json.dumps(res["timings"], indent=1))
    print("\n".join(res["notes"]))
