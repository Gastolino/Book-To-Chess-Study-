"""The browser app's start page (tools/build_web.py)."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(tmp_path):
    chess = tmp_path / "chess-1.11.2-py3-none-any.whl"
    pymupdf = tmp_path / "pymupdf-test.whl"
    chess.write_bytes(b"x")
    pymupdf.write_bytes(b"x")
    out = tmp_path / "site"
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(out),
                    "--chess", str(chess), "--pymupdf", str(pymupdf)], check=True)
    return (out / "index.html").read_text(encoding="utf-8")


def test_chapter_links_reach_the_app(tmp_path):
    page = build(tmp_path)
    nav = re.search(r"const NAV = String\.raw`(.*?)`;", page, re.S)
    assert nav, "the link handler must be a String.raw template, or \\d loses its backslash"
    pattern = re.search(r"h\.match\(/(.*?)/\)", nav.group(1)).group(1)
    for href in ("ch01.html", "ch12.html#page=5", "index.html"):
        assert re.match(pattern, href), href
    assert '<${"/"}script>' in nav.group(1)


def test_book_name_wraps(tmp_path):
    page = build(tmp_path)
    assert "flex-wrap:wrap" in page and "overflow-wrap:anywhere" in page


def test_read_again_passes_the_stored_corrections(tmp_path):
    page = build(tmp_path)
    assert 'k.startsWith("chessbook-corrections:" + name + ":")' in page
    assert "corrections: storedCorrections(name)" in page
    worker = (ROOT / "web" / "worker.js").read_text(encoding="utf-8")
    assert "msg.corrections" in worker


def test_driver_applies_the_corrections(tmp_path, monkeypatch):
    """web/driver.py writes the corrections the browser stored where build_book
    reads them, and drops them when the browser holds none."""
    import json
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "web"))
    sys.path.insert(0, str(ROOT / "tests"))
    import driver
    from test_assemble import make_book
    monkeypatch.setattr(driver, "OUT", tmp_path / "out")
    monkeypatch.setattr(driver, "CFG", tmp_path / "cfg")
    pdf = make_book(tmp_path / "little.pdf")
    fix = {"version": 1, "diagrams": {"p5-1": {"fen": "6k1/5pp1/7p/8/8/8/5PPP/3R2K1 w - - 0 1"}},
           "moves": {}, "unattached": {}, "glyphs": {}}
    html = driver.process(str(pdf), lambda *_: None, None, json.dumps(fix))
    assert "The run used your corrections of" in html
    book = driver.STATE["book"]
    assert book["pages"][4]["diagrams"][0]["status"] == "corrected"
    assert (tmp_path / "cfg" / "little" / "corrections.json").exists()
    driver.process(str(pdf), lambda *_: None, None, None)
    assert not (tmp_path / "cfg" / "little" / "corrections.json").exists()
    assert driver.STATE["book"]["pages"][4]["diagrams"][0]["status"] == "unread"
