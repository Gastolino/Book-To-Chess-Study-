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

from chessbook import reader, style  # noqa: E402
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
    assert '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){' in text
    assert ':root[data-theme="dark"]{' in text
    assert re.search(r"body\{[^}]*background:var\(--bg\)", text)
    # every colour of the design guide, light and dark
    for k, (light, dark) in style.TOKENS.items():
        assert f"--{k}:{light}" in text and f"--{k}:{dark}" in text, k
    # DM Sans (variable, upright and italic) and Geist Mono 400 and 500, embedded
    assert text.count("src:url(data:font/woff2;base64,") == 4
    assert 'font-family:"DM Sans";' in text and 'font-family:"Geist Mono";' in text
    assert "font-weight:100 1000" in text
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
                   "ArrowRight", "Board reading (Stage 3) could not read that diagram", "href=\"index.html\"",
                   'id="showread"', ">Show reading<", ">On this page<", ">Contents<",
                   'id="chips"', 'id="dpanel"'):
        assert needle in text, needle
    # the dropdown and the pill chips are gone
    assert 'id="linesel"' not in text and 'class="chip' not in text
    # the move controls are line icons drawn as strokes
    assert text.count("<svg viewBox='0 0 20 20' aria-hidden='true'>") >= 7
    # python-chess's own piece drawings
    assert 'id="white-knight"' in text and 'id="black-queen"' in text


def test_index_page(little):
    out, book, _ = little
    text = (out / "index.html").read_text(encoding="utf-8")
    assert text.count('class="pcb"') == book["page_count"]
    n_diag = sum(len(p["diagrams"]) for p in book["pages"])
    assert text.count('<button class="d"') == n_diag
    assert text.count('class="ccb"') == sum(1 for c in book["chapters"] if c["end"] >= c["start"])
    assert text.count("<details>") == text.count('class="ccb"')
    for needle in ("Copy selection", "Download selection.json", "Undo changes",
                   "paste it into the chat", 'href="ch01.html"', '>Open</a>',
                   reader.page_range(reader._folios(book), 3, 9)):
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
        subprocess.run([sys.executable, str(ROOT / "make_reader.py"), str(PDF), "--chapters", "0,7"],
                       cwd=str(ROOT), check=True)
        return
    book = json.loads(book_path.read_text(encoding="utf-8"))
    if "symbols" not in book or "corrections" not in book:
        # written before the reader could review and correct: assemble again
        subprocess.run([sys.executable, str(ROOT / "make_reader.py"), str(PDF), "--chapters", "0,7"],
                       cwd=str(ROOT), check=True)
        return
    ch = next(c for c in book["chapters"] if c["start"] <= 250 <= c["end"])
    # the browser test also opens the front matter (chapter 0)
    if not all((PRIMER_READER / f).exists() for f in ("index.html", ch["file"], "ch00.html")):
        subprocess.run([sys.executable, str(ROOT / "make_reader.py"), str(PDF), "--reuse",
                        "--chapters", f"0,{ch['index']}"], cwd=str(ROOT), check=True)


@pytest.mark.skipif(not PDF.exists(), reason="primer.pdf is not in the project folder")
@pytest.mark.skipif(not _browser_ready(), reason="node, Playwright or Chromium is missing")
def test_primer_reader_in_chromium(tmp_path, monkeypatch):
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
    assert len(res["checks"]) >= 50
    for shot in ("reader_1280.png", "reader_390.png", "index_1280.png", "index_390.png",
                 "index_chapter_1280.png"):
        assert (screens / shot).stat().st_size > 10000, shot
    # the selection the index page builds reads back with selection.py
    sel = Selection(parse_selection_text(res["selection"]))
    assert not sel.page_selected(250) and sel.page_selected(251)
    assert not sel.page_selected(5)
    for shot in ("review_move_1280_light.png", "review_move_390_dark.png", "review_diagram_390_light.png",
                 "review_diagram_1280_dark.png", "review_symbol_390_light.png"):
        assert (screens / shot).stat().st_size > 10000, shot
    print(json.dumps({k: res[k] for k in ("chapter", "clicked", "advanced", "diagram", "symbol")}))
    _read_again_from_the_command_line(res, tmp_path, monkeypatch)


@pytest.mark.skipif(not _browser_ready(), reason="node, Playwright or Chromium is missing")
def test_pencil_in_chromium(tmp_path):
    """The pencil, joining and splitting lines, and a correction applied live
    (tests/pencil_e2e.js), on the generated book with a garbled game."""
    from chessbook import live
    from test_corrections import GARBLED, NOTE, game_nodes, key_of
    pdf = make_book(tmp_path / "garbled.pdf", game=GARBLED, note7=NOTE)
    state = {}
    book = build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books",
                      state=state)
    out = tmp_path / "output" / "garbled" / "reader"
    reader.build_reader(book, pdf, out)
    ch = book["chapters"][1]
    old = reader.chapter_data(book, ch, "")
    _, nodes = game_nodes(book)
    live.apply(state, book, {"moves": {key_of(nodes, "Zq9"): {"san": "Nxd5"}}})
    patch, _ = live.chapter_patch(book, ch, old)
    (tmp_path / "patch.json").write_text(json.dumps(patch), encoding="utf-8")
    screens = ROOT / "output" / "screens"
    env = dict(os.environ, NODE_PATH=NODE_PATH)
    proc = subprocess.run([NODE, str(ROOT / "tests" / "pencil_e2e.js"), str(out / ch["file"]),
                           str(tmp_path / "patch.json"), str(screens)],
                          capture_output=True, text=True, env=env, timeout=300)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, proc.stdout + proc.stderr
    res = json.loads(lines[-1])
    failed = [c for c in res["checks"] if not c["ok"]]
    assert res["ok"], (res.get("failure"), failed, res["errors"])
    assert res["errors"] == []
    for name in ("pencil_move_1280_light.png", "pencil_line_1280_dark.png",
                 "pencil_move_390_light.png", "pencil_move_390_dark.png",
                 "pencil_patched_1280_light.png"):
        assert (screens / name).stat().st_size > 10000, name


@pytest.mark.skipif(not _browser_ready(), reason="node, Playwright or Chromium is missing")
def test_gap_in_chromium(tmp_path):
    """A tap on a red move opens its corrector, and a gap in the text is filled
    (tests/gap_e2e.js), on the generated book whose game lacks two moves."""
    from chessbook import live
    from test_corrections import GAPPED, gap_of
    pdf = make_book(tmp_path / "gapped.pdf", game=GAPPED)
    state = {}
    book = build_book(pdf, output_dir=tmp_path / "output", books_dir=tmp_path / "books",
                      state=state)
    out = tmp_path / "output" / "gapped" / "reader"
    reader.build_reader(book, pdf, out)
    ch = book["chapters"][1]
    old = reader.chapter_data(book, ch, "")
    live.apply(state, book, {"gaps": {gap_of(book)["gap"]: {"san": ["Nxd5", "Nxf7"]}}})
    patch, _ = live.chapter_patch(book, ch, old)
    (tmp_path / "patch.json").write_text(json.dumps(patch), encoding="utf-8")
    screens = ROOT / "output" / "screens"
    env = dict(os.environ, NODE_PATH=NODE_PATH)
    proc = subprocess.run([NODE, str(ROOT / "tests" / "gap_e2e.js"), str(out / ch["file"]),
                           str(tmp_path / "patch.json"), str(screens)],
                          capture_output=True, text=True, env=env, timeout=300)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert lines, proc.stdout + proc.stderr
    res = json.loads(lines[-1])
    failed = [c for c in res["checks"] if not c["ok"]]
    assert res["ok"], (res.get("failure"), failed, res["errors"])
    for name in ("gap_move_1280_light.png", "gap_filled_1280_light.png", "gap_patched_1280_light.png",
                 "gap_move_390_light.png", "gap_fill_390_light.png"):
        assert (screens / name).stat().st_size > 10000, name


def _read_again_from_the_command_line(res, tmp_path, monkeypatch):
    """The corrections the browser test made, pasted into make_reader
    --corrections (the command line's Read again): every kind is applied."""
    import make_reader
    from chessbook import assemble, corrections
    from chessbook import selection as selmod
    fix = corrections.parse_corrections_text(res["corrections"])
    assert all(fix[k] for k in ("diagrams", "moves", "unattached", "glyphs")), fix
    pasted = tmp_path / "pasted.txt"
    pasted.write_text("Here are my corrections:\n```json\n" + res["corrections"] + "\n```\n", encoding="utf-8")
    monkeypatch.setattr(selmod, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(corrections, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(assemble, "OUTPUT_DIR", tmp_path / "output")
    make_reader.main([str(PDF), "--corrections", str(pasted), "--chapters", "7"])
    book = json.loads((tmp_path / "output" / "primer" / "book.json").read_text(encoding="utf-8"))
    assert book["corrections"] == fix
    (key, v), = fix["moves"].items()
    node = next(n for n in book["nodes"].values() if n.get("key") == key)
    assert node["corrected"] == "move" and node["san"] == v["san"]
    (did, d), = fix["diagrams"].items()
    dg = next(x for p in book["pages"] for x in p["diagrams"] if x["id"] == did)
    assert dg["status"] == "corrected" and dg["fen"] == d["fen"]
    for key, v in fix["unattached"].items():
        placed = [u for u in book["attached"] + book["dismissed"] if u["key"] == key]
        left = [u for u in book["unattached"] if u["key"] == key]
        # a sequence goes where the reader tied it when its moves are legal there, and says
        # why not otherwise
        assert placed or (left and "you tied it to" in left[0]["reason"]), (key, v)
        if v["attach_to"] == "dismiss":
            assert placed and placed[0] in book["dismissed"]
    assert book["stats"]["corrected"]["symbols"] == 1 and book["stats"]["corrected"]["symbol_moves"] > 0
    index = (tmp_path / "output" / "primer" / "reader" / "index.html").read_text(encoding="utf-8")
    assert "The run used your corrections of" in index


@pytest.mark.skipif(not PRIMER_READER.exists(), reason="the Primer's reader has not been built")
def test_primer_reader_sizes():
    files = sorted(PRIMER_READER.glob("ch*.html"))
    assert files
    for f in files:
        assert f.stat().st_size < reader.MAX_BYTES, f.name


def test_reader_after_the_audit(little):
    """The selection is kept in the browser and shared by both kinds of page,
    the contents page previews each diagram, and the wording names what the
    text recognition read instead of claiming what the book prints."""
    out, book, _ = little
    index = (out / "index.html").read_text(encoding="utf-8")
    chapter = (out / "ch01.html").read_text(encoding="utf-8")
    for text in (index, chapter):
        assert "localStorage" in text and "chessbook-selection:" in text
    # the contents page holds no diagram previews; its outlines switch a diagram on and off
    assert 'id="crops"' not in index and 'id="lightbox"' not in index
    assert "is now left out" in index and "is left out." in index
    assert "Use this diagram" in chapter
    for needle in ('id="usepage"', "usediag", "hashchange", "The text recognition read",
                   "The program places this diagram after", 'id="mini"', "sideStep"):
        assert needle in chapter, needle
    assert "The book prints" not in chapter
    data = script_json(chapter, "data")
    assert data["selBase"] == script_json(index, "data")["selBase"]
    # no internal diagram ids or picture-kind codes in the visible text
    seen = visible_text(index) + visible_text(chapter)
    assert not re.search(r"\bp\d+-\d+\b", seen) and "board_plus" not in seen
    # the chapter heading has no colon between book, chapter and title
    assert "<h1>Chapter 1, First Steps</h1>" in chapter


def test_chapter_heading_and_plurals():
    ch = {"label": "Chapter 7", "subtitle": "How to Begin a Game", "title": "Chapter 7: How to Begin a Game"}
    assert reader.chapter_heading(ch) == "Chapter 7, How to Begin a Game"
    counts = {"lines": 1, "games": 1, "fragments": 0, "variations": 2, "unattached": 1, "waiting": 1,
              "moves": {"ok": 1, "guessed": 0, "ambiguous": 0, "failed": 0, "waiting": 1}}
    t = reader._counts_line(counts)
    assert '<span class="num">1</span> line ·' in t and '<span class="num">1</span> move read' in t
    assert '<span class="num">1</span> waiting for board reading' in t
    counts["lines"] = 2400
    assert '<span class="num">2,400</span> lines' in reader._counts_line(counts)
    # figures of 0 are left out of the line, and the columns hold all five
    assert "chosen" not in t and "not read" not in t
    assert reader._count_cells(counts).count('class="cn small num"') == 5
    # pages without a printed number are named by their PDF page
    assert reader.page_range([None, 1, 2, 3], 1, 4) == "PDF page 1, pages 1 to 3"
    assert reader.page_range([None, None], 1, 2) == "pages 1 to 2"
    assert reader.page_range([5, 6, None], 1, 3) == "pages 5 to 6, PDF page 3"
    assert reader.page_label([None, 7], 2) == "7"
    assert reader.page_label([None, 7], 1) == "PDF 1"


def _css_of(text):
    return "".join(re.findall(r"<style>(.*?)</style>", text, flags=re.S))


def test_design_guide(little):
    """The rules of DESIGN.md that a style sheet can break: no all-caps or
    letter-spaced text, no shadows, gradients or rounded shapes, weights 400
    and 500 only, and every page on the shared fonts and colour tokens."""
    import stage1_inspect
    out, _, _ = little
    sheets = {name: _css_of((out / name).read_text(encoding="utf-8"))
              for name in ("index.html", "ch01.html")}
    sheets["stage1"] = style.page_css() + stage1_inspect.REPORT_CSS
    for name, css in sheets.items():
        css = re.sub(r"@font-face\{[^}]*\}", "", css)
        # the tint of selected text is the browser's, not a fill of an element
        low = re.sub(r"::selection\{[^}]*\}", "", css).lower()
        assert "uppercase" not in low and "small-caps" not in low, name
        assert "box-shadow" not in low and "text-shadow" not in low, name
        assert "gradient(" not in low, name
        # check boxes are drawn in hairlines, not as the browser's filled control
        assert "accent-color" not in low and "appearance:none" in low, name
        # buttons and outlines carry no fill: no background other than none, transparent or
        # the page colour
        for v in re.findall(r"background(?:-color)?:([^;}]+)", low):
            assert v.strip() in ("none", "transparent", "var(--bg)") or v.strip().startswith("var(--ok)") \
                or v.strip() in ("var(--doubt)", "var(--fail)", "var(--muted)"), (name, v)
        # prose sets 1.5 and the move list 1.7
        for v in re.findall(r"line-height:([^;}]+)", low):
            assert v.strip() in ("1.5", "1.7", "1.35", "1.3", "1.25", "0"), (name, v)
        for v in re.findall(r"letter-spacing:([^;}]+)", low):
            assert v.strip() in ("0", "-0.01em"), (name, v)
        for v in re.findall(r"border-radius:([^;}]+)", low):
            assert v.strip() in ("0", "1px", "2px", "50%"), (name, v)
        for v in re.findall(r"font-weight:([^;}]+)", low):
            assert v.strip() in ("400", "500"), (name, v)
        assert "bold" not in low, name
        assert style.base_css() in css and style.tokens_css() in css, name


STAGE1_REPORT = ROOT / "output" / "primer" / "stage1" / "inspect.html"


@pytest.mark.skipif(not STAGE1_REPORT.exists(), reason="the Stage 1 report has not been written")
def test_stage1_report_follows_the_guide():
    """The Stage 1 report uses the shared fonts and colours, marks each row's
    status with a dot and words instead of a coloured row, and keeps to the
    writing rules."""
    text = STAGE1_REPORT.read_text(encoding="utf-8")
    assert style.page_css() in text
    assert "<tr class=" not in text
    rows = re.findall(r'<i class="dot (ok|doubt|fail)"></i>([A-Z][^<]+)</td>', text)
    assert rows and {k for k, _ in rows} <= {"ok", "doubt", "fail"}
    assert all(words.strip() for _, words in rows)
    # figures in the prose are not bold, and the series names are in sentence case
    assert not re.search(r"<b[ >]", text.split("</style>", 1)[1])
    assert not re.search(r"<td>(main|other|none|circled)</td>", text)
    # no paragraph without a verb, no figure the program did not count, no claim about books
    for s in ("The main series, each number", "The other numbers, grouped",
              "two or three boards", "A book prints many positions"):
        assert s not in text, s
    seen = visible_text(text)
    assert "—" not in seen
    for w in HEDGES + ("usually", "commonly", "nearly"):
        assert not re.search(r"\b" + w + r"\b", seen.lower()), w
    assert not re.search(r"\bI\b", seen)
