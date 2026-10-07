"""The browser app's start page (tools/build_web.py)."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_top_bar_names_the_book_on_one_line(tmp_path):
    """The top bar is one line: the book's title (never its file name), then the
    small book, then Library in the corner. The words of the work stay out of it
    (#took keeps them for a tap on the small book), and the notes, the way back
    from the contents and Read again go under the line."""
    page = build(tmp_path)
    assert "textContent = file.name" not in page
    top = re.search(r'<div id="top">(.*?)<main id="start">', page, re.S).group(1)
    at = [top.index(x) for x in ('id="booktitle"', 'id="busy"', 'id="another"', 'id="sub"')]
    assert at == sorted(at)
    sub = re.search(r'<div id="sub">(.*?)</div>', top, re.S).group(1)
    assert all(f'id="{x}"' in sub for x in ("note", "backbtn", "again"))
    assert '<span id="took" hidden></span>' in top
    assert "#booktitle{flex:1 1 0;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" in page
    # the title the library knows, or the reading's
    assert "bookTitle(LIB.on && LIB.current ? LIB.titleOf(LIB.current.book)" in page


def test_the_reader_in_the_app_leaves_the_book_name_to_the_top_bar(tmp_path):
    """The app adds a rule after the reader page's own style that hides the
    book's name in the reader's bar; the reader written to disk keeps it."""
    from chessbook import reader
    page = build(tmp_path)
    assert 'const APP_STYLE = "<style>.where .book{display:none}</style>";' in page
    assert '.replace("</head>", APP_STYLE + "</head>")' in page
    html = reader.CHAPTER_HTML
    assert 'class="book"' in html and html.index("<style>") < html.index("</head>")


def test_the_top_bar_comes_back_only_at_the_top(tmp_path):
    """On a phone the top bar goes away as the page scrolls down and comes back
    only within a few pixels of the top, not on every scroll up."""
    page = build(tmp_path)
    topbar = re.search(r"const TOPBAR = \(\(\) => \{(.*?)\n\}\)\(\);", page, re.S).group(1)
    assert "const TOP = 4;" in topbar and "if (y <= TOP) set(false);" in topbar
    assert "d < 0" not in topbar


def test_the_page_keeps_clear_of_the_home_indicator(tmp_path):
    # the reader's frame is told no safe area: the app's page pads itself, so that the bar at the
    # foot of the reader sits above the iPhone's home indicator
    page = build(tmp_path)
    assert "viewport-fit=cover" in page
    body = re.search(r"\nbody\{margin:0;display:flex;flex-direction:column;[^}]*\}", page).group(0)
    for side in ("top", "right", "bottom", "left"):
        assert f"env(safe-area-inset-{side})" in body
    assert "box-sizing:border-box" in body
    # the bar is lifted a little above the home indicator, less than the whole safe area
    assert "max(0px, calc(env(safe-area-inset-bottom) - 14px))" in body


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


def test_the_app_flag_comes_before_the_page_script(tmp_path):
    """The reader's script reads window.CHESSBOOK_APP while it starts (to send
    corrections stored in the browser that the book does not hold yet), so
    the app puts the flag at the top of the head, not after the script."""
    page = build(tmp_path)
    assert 'htmlText.replace("<head>", "<head>" + FLAG)' in page
    assert ('const FLAG = "<script>window.CHESSBOOK_APP=true;window.CHESSBOOK_ENGINE=" + '
            'JSON.stringify(CFG.engine) + ";<" + "/script>";') in page
    # without --engine the reader is told that no engine is installed
    assert re.search(r"packages: \[[^\]]*\], engine: null\}", page)


def test_one_chain_of_symbol_batches(tmp_path):
    page = build(tmp_path)
    assert "if (!moreBusy) {" in page and "moreBusy = true;" in page
    worker = (ROOT / "web" / "worker.js").read_text(encoding="utf-8")
    assert "during: msg.type" in worker and "py.loadedPackages" in worker


def _driver(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "web"))
    sys.path.insert(0, str(ROOT / "tests"))
    import driver
    monkeypatch.setattr(driver, "OUT", tmp_path / "out")
    monkeypatch.setattr(driver, "CFG", tmp_path / "cfg")
    return driver


def test_a_diagram_correction_reaches_the_open_chapter(tmp_path, monkeypatch):
    """The patch holds the corrected diagram even when no move of its page
    changes: the chapter data the driver keeps shares no object with the book."""
    import json
    driver = _driver(tmp_path, monkeypatch)
    from test_assemble import ENDING_FEN, make_book
    pdf = make_book(tmp_path / "little.pdf")
    driver.process(str(pdf), lambda *_: None)
    name = next(c["file"] for c in driver.STATE["book"]["chapters"] if c["start"] <= 6 <= c["end"])
    driver.chapter(name, lambda *_: None)
    fix = json.dumps({"version": 1, "diagrams": {"p6-1": {"fen": ENDING_FEN}}})
    out = json.loads(driver.correct(fix, name))
    d = next(x for x in out["patch"]["pages"]["6"]["diagrams"] if x["id"] == "p6-1")
    assert d["corrected"] and d["fen"] == ENDING_FEN
    # the same corrections again: nothing of the page changes
    out = json.loads(driver.correct(fix, name))
    assert "6" not in out["patch"]["pages"]


def test_a_gap_correction_reaches_the_open_chapter(tmp_path, monkeypatch):
    """The worker's driver applies the moves the reader gave for a gap in the
    text at once: the patch holds them, and the moves after the gap decode."""
    import json
    driver = _driver(tmp_path, monkeypatch)
    from test_assemble import make_book
    from test_corrections import GAPPED, SANS
    pdf = make_book(tmp_path / "gapped.pdf", game=GAPPED)
    driver.process(str(pdf), lambda *_: None)
    name = next(c["file"] for c in driver.STATE["book"]["chapters"] if c["start"] <= 4 <= c["end"])
    driver.chapter(name, lambda *_: None)
    key = next(n["gap"] for n in driver.STATE["book"]["nodes"].values() if n.get("gap") and not n["san"])
    out = json.loads(driver.correct(json.dumps({"version": 1, "gaps": {key: {"san": ["Nxd5", "Nxf7"]}}}), name))
    nodes = out["patch"]["nodes"]
    assert [n["san"] for n in nodes.values() if n.get("corrected") == "filled"] == ["Nxd5", "Nxf7"]
    after = next(n for n in nodes.values() if n.get("key") == key)
    assert after["san"] == "Kxf7" and after["status"] == "ok"
    assert out["patch"]["corrections"]["gaps"] == {key: {"san": ["Nxd5", "Nxf7"]}}
    game = [n["san"] for n in driver.STATE["book"]["nodes"].values()
            if n["main"] and n["san"] and n["page"] == 4]
    assert game[:len(SANS)] == SANS


def test_a_variation_added_on_the_board_reaches_the_open_chapter(tmp_path, monkeypatch):
    """A piece moved on the board adds a variation (corrections.py "added"): the
    worker's driver replays its line at once, the patch holds the new moves,
    and a longer variation keeps the reader's place on its moves."""
    import json
    driver = _driver(tmp_path, monkeypatch)
    from test_assemble import make_book
    pdf = make_book(tmp_path / "little.pdf")
    driver.process(str(pdf), lambda *_: None)
    name = next(c["file"] for c in driver.STATE["book"]["chapters"] if c["start"] <= 4 <= c["end"])
    driver.chapter(name, lambda *_: None)
    key = next(n["key"] for n in driver.STATE["book"]["nodes"].values() if n["san"] == "Nf3" and n["main"])
    out = json.loads(driver.correct(json.dumps({"version": 1, "added": {key: [{"san": ["d6"]}]}}), name))
    (d6, node), = [(k, n) for k, n in out["patch"]["nodes"].items() if n.get("corrected") == "added"]
    assert node["san"] == "d6" and node["added"] == key and not node["main"]
    assert out["patch"]["corrections"]["added"] == {key: [{"san": ["d6"]}]}
    out = json.loads(driver.correct(json.dumps({"version": 1, "added": {key: [{"san": ["d6", "d4"]}]}}), name))
    added = {k: n["san"] for k, n in out["patch"]["nodes"].items() if n.get("corrected") == "added"}
    assert sorted(added.values()) == ["d4", "d6"]
    assert added[out["patch"]["renamed"].get(d6, d6)] == "d6"
    out = json.loads(driver.correct(json.dumps({"version": 1, "added": {}}), name))
    assert not [n for n in out["patch"]["nodes"].values() if n.get("corrected") == "added"]
    assert driver.STATE["book"]["stats"]["corrected"]["added_moves"] == 0


GPA = ROOT / "corpus" / "gpa.pdf"


@pytest.mark.skipif(not GPA.exists(), reason="corpus/gpa.pdf is not in the project folder")
def test_a_pending_chapter_gets_the_piece_symbol_when_it_opens(tmp_path, monkeypatch):
    """A piece symbol named in one chapter reaches the others in batches; a
    chapter opened before its batch replays its lines first, so it opens
    corrected and no batch is needed for it afterwards."""
    import json
    driver = _driver(tmp_path, monkeypatch)
    driver.process(str(GPA), lambda *_: None)
    say = lambda *_: None
    driver.chapter("ch02.html", say)
    nodes = driver.STATE["data"]["ch02.html"]["nodes"]
    sym = next(n["symbol"] for n in nodes.values() if n.get("symbol") and n.get("key"))
    out = json.loads(driver.correct(json.dumps({"version": 1, "glyphs": {sym: "N"}}), "ch02.html"))
    later = [k for k in out["pending"]]
    assert later
    k = later[-1]
    name = f"ch{k:02d}.html"
    driver.chapter(name, say)
    assert k not in driver.STATE["pending"]
    out = json.loads(driver.correct_more(json.dumps([k]), name))
    assert out["patch"] is None or not out["patch"]["nodes"]


def test_read_again_drops_a_selection_the_browser_no_longer_holds(tmp_path, monkeypatch):
    import json
    driver = _driver(tmp_path, monkeypatch)
    from chessbook import selection
    from test_assemble import make_book
    pdf = make_book(tmp_path / "little.pdf")
    sel = {"pages": {"exclude": [5]}, "diagrams": {"exclude": [], "include": []}}
    driver.process(str(pdf), lambda *_: None, json.dumps(sel))
    assert selection.selection_path(pdf, tmp_path / "cfg").exists()
    driver.process(str(pdf), lambda *_: None, None)
    assert not selection.selection_path(pdf, tmp_path / "cfg").exists()


def test_the_library_uses_the_server_only_when_the_site_answers(tmp_path):
    """The shell loads web/library.js and asks it to start; the library keeps
    its books on the server only when /api/books answers with a list of
    books (the Cloudflare site), and in the browser's IndexedDB otherwise
    (GitHub Pages), with the same library page."""
    page = build(tmp_path)
    # the shell hands the library the session record, so that it can go back to the open book
    assert '<script src="library.js"></script>' in page and "LIB.start(SESSION.pending())" in page
    assert "if (LIB.message(m)) return;" in page and "if (LIB.on) { LIB.add(file); return; }" in page
    lib = (tmp_path / "site" / "library.js").read_text(encoding="utf-8")
    assert 'fetch("api/books"' in lib
    assert "if (!data || !Array.isArray(data.books)) return null;" in lib
    assert "if (books) store = serverStore;" in lib and "store = deviceStore();" in lib
