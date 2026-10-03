"""Tests for chessbook.reader and make_reader.py.

The generated book of test_assemble checks the files the reader writes; the
Primer's reader is checked in Chromium by tests/reader_e2e.js (Playwright).
"""
import html as htmlmod
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from chessbook import reader  # noqa: E402
from chessbook.assemble import build_book  # noqa: E402
from chessbook.selection import Selection, parse_selection_text  # noqa: E402
from test_assemble import make_book  # noqa: E402

PDF = ROOT / "primer.pdf"
PRIMER_READER = ROOT / "output" / "primer" / "reader"
NODE = shutil.which("node") or "/opt/node22/bin/node"
NODE_PATH = "/opt/node22/lib/node_modules"
CHROMIUM = Path("/opt/pw-browsers/chromium")
HEDGES = ("probably", "perhaps", "arguably", "possibly", "somewhat")


@pytest.fixture(scope="module")
def little(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("reader")
    pdf = make_book(tmp / "little.pdf")
    book = build_book(pdf, output_dir=tmp / "output", books_dir=tmp / "books")
    out = tmp / "output" / "little" / "reader"
    rep = reader.build_reader(book, pdf, out)
    return out, book, rep


def script_json(text, sid):
    m = re.search(r'<script type="application/json" id="' + sid + r'">(.*?)</script>', text, re.S)
    assert m, sid
    return json.loads(m.group(1).replace("<\\/", "</"))


def visible_text(text):
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<svg.*?</svg>", " ", text, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return htmlmod.unescape(re.sub(r"\s+", " ", t))


def test_files(little):
    out, book, rep = little
    assert (out / "index.html").exists() and (out / "ch01.html").exists()
    assert (out.parent / "pgn" / "ch01.pgn").exists()
    assert set(rep["files"]) >= {"index.html", "ch01.html"}
    for name, size in rep["files"].items():
        assert size < reader.MAX_BYTES, name


@pytest.mark.parametrize("name", ["index.html", "ch01.html"])
def test_self_contained_and_themed(little, name):
    out, _, _ = little
    text = (out / name).read_text(encoding="utf-8")
    urls = re.findall(r"https?://[^\s\"'<>)]+", text)
    assert set(urls) <= {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink"}, urls
    assert "<link" not in text and "@import" not in text
    assert re.search(r":root\{[^}]*--bg:", text)
    assert "@media (prefers-color-scheme:dark){:root{" in text
    assert re.search(r"body\{[^}]*background:var\(--bg\)", text)
    assert 'name="viewport"' in text
    assert re.search(r"<title>[^<]{3,60}</title>", text)


def test_chapter_page(little):
    out, book, _ = little
    text = (out / "ch01.html").read_text(encoding="utf-8")
    data = script_json(text, "data")
    images = script_json(text, "images")
    ch = book["chapters"][1]
    assert set(map(int, images)) == set(range(ch["start"], ch["end"] + 1))
    assert set(map(int, data["pages"])) == set(range(ch["start"], ch["end"] + 1))
    for p in data["pages"].values():
        for m in p["marks"]:
            assert m["node"] is None or m["node"] in data["nodes"]
    game = next(x for x in data["lines"].values() if x["title"].startswith("Smith - Jones"))
    assert game["root"] in data["nodes"]
    assert "[White \"Smith\"]" in data["pgn"] and data["pgnName"] == "ch01.pgn"
    for needle in ("window.readerState", "Download PGN", "Chess board", "id=\"bflip\"",
                   "ArrowRight", "Board reading (Stage 3) has not run yet", "href=\"index.html\""):
        assert needle in text, needle
    # python-chess's own piece drawings
    assert 'id="white-knight"' in text and 'id="black-queen"' in text


def test_index_page(little):
    out, book, _ = little
    text = (out / "index.html").read_text(encoding="utf-8")
    assert text.count('class="pcb"') == book["page_count"]
    n_diag = sum(len(p["diagrams"]) for p in book["pages"])
    assert text.count('class="dcb"') == n_diag
    assert text.count('class="ccb"') == sum(1 for c in book["chapters"] if c["end"] >= c["start"])
    for needle in ("Copy selection", "Download selection.json", "paste the copied text into the chat",
                   'href="ch01.html"', "pages 3 to 9"):
        assert needle in text, needle
    data = script_json(text, "data")
    assert data["pageCount"] == book["page_count"]
    assert data["excludedKinds"] == ["partial", "illustration", "icon", "front"]


def test_writing_style(little):
    out, _, _ = little
    for name in ("index.html", "ch01.html"):
        t = visible_text((out / name).read_text(encoding="utf-8"))
        assert "—" not in t, name
        low = t.lower()
        for w in HEDGES:
            assert not re.search(r"\b" + w + r"\b", low), (name, w)
    for chunk in (reader.CHAPTER_JS, reader.INDEX_JS):
        for s in re.findall(r'"([A-Z][^"]{20,})"', chunk):
            assert "—" not in s and not any(re.search(r"\b" + w + r"\b", s.lower())
                                                for w in HEDGES), s


def test_make_reader_selection_option(tmp_path, monkeypatch):
    """make_reader --selection saves a pasted selection as the book's selection."""
    import make_reader
    from chessbook import selection as selmod
    pasted = tmp_path / "pasted.txt"
    pasted.write_text("Here it is:\n```json\n{\"version\": 1, \"pages\": {\"exclude\": [[1, 2]]},"
                      " \"diagrams\": {\"exclude\": [\"p5-1\"], \"include\": []}}\n```\n",
                      encoding="utf-8")
    saved = {}

    def fake_build(*a, **k):
        raise SystemExit(0)

    monkeypatch.setattr(selmod, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(make_reader.assemble, "build_book", fake_build)
    pdf = make_book(tmp_path / "little.pdf")
    with pytest.raises(SystemExit):
        make_reader.main([str(pdf), "--selection", str(pasted)])
    path = tmp_path / "books" / "little" / "selection.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["pages"]["exclude"] == [[1, 2]] and saved["diagrams"]["exclude"] == ["p5-1"]


# ------------------------------------------------------------------ the Primer in a browser

def _browser_ready():
    if not Path(NODE).exists() or not CHROMIUM.exists():
        return False
    return Path(NODE_PATH, "playwright").exists()


def _ensure_primer_reader():
    """The Primer's reader for the chapter holding page 250 and the index."""
    book_path = ROOT / "output" / "primer" / "book.json"
    if not book_path.exists():
        subprocess.run([sys.executable, str(ROOT / "make_reader.py"), str(PDF), "--chapters", "7"],
                       cwd=str(ROOT), check=True)
        return
    book = json.loads(book_path.read_text(encoding="utf-8"))
    ch = next(c for c in book["chapters"] if c["start"] <= 250 <= c["end"])
    if not (PRIMER_READER / "index.html").exists() or not (PRIMER_READER / ch["file"]).exists():
        subprocess.run([sys.executable, str(ROOT / "make_reader.py"), str(PDF), "--reuse",
                        "--chapters", str(ch["index"])], cwd=str(ROOT), check=True)


@pytest.mark.skipif(not PDF.exists(), reason="primer.pdf is not in the project folder")
@pytest.mark.skipif(not _browser_ready(), reason="node, Playwright or Chromium is missing")
def test_primer_reader_in_chromium():
    _ensure_primer_reader()
    screens = PRIMER_READER / "screens"
    env = dict(os.environ, NODE_PATH=NODE_PATH)
    proc = subprocess.run([NODE, str(ROOT / "tests" / "reader_e2e.js"), str(PRIMER_READER), "250",
                           str(screens)], capture_output=True, text=True, env=env, timeout=300)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, proc.stdout + proc.stderr
    res = json.loads(lines[-1])
    failed = [c for c in res["checks"] if not c["ok"]]
    assert res["ok"], (res.get("failure"), failed, res["errors"])
    assert proc.returncode == 0
    assert res["errors"] == []
    names = {c["name"] for c in res["checks"]}
    assert {"readerState.fen equals the move's FEN", "ArrowRight advances to the next move",
            "clicking a diagram opens the diagram panel", "no sideways scroll at 390 px",
            "no console errors"} <= names
    for shot in ("reader_1280.png", "reader_390.png", "index_1280.png", "index_390.png"):
        assert (screens / shot).stat().st_size > 10000, shot
    # the selection the index page builds reads back with selection.py
    sel = Selection(parse_selection_text(res["selection"]))
    assert not sel.page_selected(250) and sel.page_selected(251)
    assert not sel.page_selected(5)
    print(json.dumps({k: res[k] for k in ("chapter", "clicked", "advanced", "diagram")}))


@pytest.mark.skipif(not PRIMER_READER.exists(), reason="the Primer's reader has not been built")
def test_primer_reader_sizes():
    files = sorted(PRIMER_READER.glob("ch*.html"))
    assert files
    for f in files:
        assert f.stat().st_size < reader.MAX_BYTES, f.name
