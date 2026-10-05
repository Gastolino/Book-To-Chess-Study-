"""The library of the Cloudflare site: a stored reading opens a book without
reading it again (web/driver.py save_reading and restore), the server's
functions refuse a request without Cloudflare Access (tests/server_test.mjs),
and the whole library runs end to end under `wrangler pages dev`
(tests/library_e2e.js)."""
import functools
import json
import os
import shutil
import socket
import subprocess
import sys
import time
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
