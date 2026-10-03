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
