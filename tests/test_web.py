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


def test_the_top_bar_keeps_its_state_through_a_turn_and_a_new_line(tmp_path):
    """A page turn into another chapter keeps the top bar as it is (the reader
    lands where the reading goes on, not at its top); while the bar is away, a
    line that comes under it or goes changes its offset with it, and the slip
    under it goes with it; the words of work under way go to the small book."""
    page = build(tmp_path)
    show = re.search(r"\nfunction show\(name, hash, htmlText\) \{(.*?)\n\}", page, re.S).group(1)
    assert 'if (!/[#&]turn=/.test(hash || "")) TOPBAR.show();' in show
    topbar = re.search(r"const TOPBAR = \(\(\) => \{(.*?)\n\}\)\(\);", page, re.S).group(1)
    assert "new ResizeObserver(" in topbar and "if (a) { clearTimeout(tipTimer); $(\"tip\").hidden = true; }" in topbar
    assert 'progress(e.data.open === "index.html" ? "Opening the contents." :' in page
    assert "progress(text); toView({ progress: text });" in page


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


def test_the_driver_names_the_other_place_of_a_move_of_the_other_side(tmp_path, monkeypatch):
    """read_region() on "Qe4", printed in a note after 7...Ke6 of the game that
    ends with 8.Nc3: after 8.Nc3, where it is Black's move, the text reads only
    as the pawn move 8...e4 (unsure, as it drops the queen); before 8.Nc3,
    the other place, it reads as 8.Qe4 without doubt, and the answer names
    that place."""
    import json
    import pymupdf
    driver = _driver(tmp_path, monkeypatch)
    from test_assemble import make_book
    from test_corrections import MISSED
    pdf = make_book(tmp_path / "missed.pdf", note7=MISSED)
    driver.process(str(pdf), lambda *_: None)
    with pymupdf.open(pdf) as doc:
        q = next([round(v, 1) for v in w[:4]] for w in doc[3].get_text("words") if w[4] == "Qe4")
    rect = [q[0] - 1, q[1] - 1, q[2] + 1, q[3] + 1]
    book = driver.STATE["book"]
    nc3_id, nc3 = next((k, n) for k, n in book["nodes"].items() if n["san"] == "Nc3" and n["main"]
                       and not any(book["nodes"][c]["main"] for c in n["children"]))
    ke6 = book["nodes"][nc3["parent"]]
    out = json.loads(driver.read_region(4, json.dumps(rect), nc3_id, "after", ke6["fen"]))
    assert out["text"] == "Qe4" and all(c["unsure"] for c in out["candidates"])
    assert out["other"] == {"side": "before", "fen": ke6["fen"], "san": ["Qe4"]}
    # without the other place, nothing is named
    assert json.loads(driver.read_region(4, json.dumps(rect), nc3_id, "after"))["other"] is None


def test_the_driver_reads_a_section_of_a_page(tmp_path, monkeypatch):
    """The reader's "Read a section": words() gives the words of the text layer
    around a tap (the selection snaps to the one under it), and read_region()
    reads the words of a section as moves with the book's own decoder and
    glyph model, from the position after (or before) a move, legal there,
    best first. A section read by the reader then reaches the open chapter
    as a patch, with its box on the page."""
    import json
    import chess
    import pymupdf
    driver = _driver(tmp_path, monkeypatch)
    from test_assemble import make_book
    from test_corrections import GARBLED, NOTE
    pdf = make_book(tmp_path / "garbled.pdf", game=GARBLED, note7=NOTE)
    driver.process(str(pdf), lambda *_: None)
    with pymupdf.open(pdf) as doc:
        box = {w[4]: [round(v, 1) for v in w[:4]] for w in doc[3].get_text("words")}
    a, b = box["2.tLlf3"], box["tLlc6"]
    # words(): the word under a tap, with its box, and those near it
    cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    got = json.loads(driver.words(4, cx - 4, cy - 4, cx + 4, cy + 4))
    assert got == [{"text": "2.tLlf3", "box": a, "inside": True}]
    near = json.loads(driver.words(4, cx - 4, cy - 4, cx + 4, cy + 4, 20))
    assert [w["text"] for w in near if w["inside"]] == ["2.tLlf3"]
    assert {"e5", "tLlc6"} <= {w["text"] for w in near if not w["inside"]}
    assert json.loads(driver.words(99, 0, 0, 10, 10)) == []
    # read_region(): "2.tLlf3 tLlc6", garbled knights, after 1...e5
    book = driver.STATE["book"]
    e5_id, e5 = next((k, n) for k, n in book["nodes"].items() if n["san"] == "e5" and n["main"]
                     and n["page"] == 4)
    rect = [a[0] - 1, a[1] - 1, b[2] + 1, b[3] + 1]
    out = json.loads(driver.read_region(4, json.dumps(rect), e5_id, "after"))
    assert out["text"] == "2.tLlf3 tLlc6" and out["fen"] == e5["fen"]
    assert out["candidates"][0]["san"] == ["Nf3", "Nc6"]
    for c in out["candidates"]:
        board = chess.Board(e5["fen"])
        for san in c["san"]:
            board.push_san(san)             # every reading is legal from the position
    # by the move's token key and by the position itself, the same reading
    by_key = json.loads(driver.read_region(4, json.dumps(rect), e5["key"], "after"))
    by_fen = json.loads(driver.read_region(4, json.dumps(rect), e5["fen"], "after"))
    assert by_key["candidates"] == by_fen["candidates"] == out["candidates"]
    # before 2.tLlf3: the moves start from the position before it
    nf3_id = next(c for c in e5["children"] if book["nodes"][c]["main"])
    before = json.loads(driver.read_region(4, json.dumps(rect), nf3_id, "before"))
    assert before["fen"] == e5["fen"] and before["candidates"] == out["candidates"]
    # a section of prose reads as no move
    prose = json.loads(driver.read_region(4, json.dumps(box["attack."]), e5_id, "after"))
    assert prose["text"] == "attack." and prose["candidates"] == [] and prose["other"] is None
    # read with the other place offered (before 1...e5, White to move): the moves read without doubt
    # where they were chosen, so the other place is not named
    both = json.loads(driver.read_region(4, json.dumps(rect), e5_id, "after", book["nodes"][e5["parent"]]["fen"]))
    assert both["candidates"] == out["candidates"] and both["other"] is None
    with pytest.raises(ValueError):
        driver.read_region(4, json.dumps(rect), "n999999", "after")
    # a section the reader read after the game's last move (8.tLlc3) and attached to it: the patch
    # holds the move, in the main line, and its box on the page (the section's, as it prints no move)
    name = next(c["file"] for c in book["chapters"] if c["start"] <= 4 <= c["end"])
    driver.chapter(name, lambda *_: None)
    last = next(n for n in book["nodes"].values() if n["main"] and n["raw"] == "tLlc3")
    entry = {"san": ["Nb4"], "page": 4, "rect": box["attack."], "main": True}
    res = json.loads(driver.correct(json.dumps({"version": 1, "added": {last["key"]: [entry]}}), name))
    patch = res["patch"]
    assert patch["corrections"]["added"][last["key"]] == [entry]
    (nid, node), = [(k, n) for k, n in patch["nodes"].items() if n.get("region")]
    assert node["san"] == "Nb4" and node["main"] and node["region"] == {"page": 4, "rect": box["attack."]}
    assert [m["bbox"] for m in patch["pages"]["4"]["marks"] if m["node"] == nid] == [box["attack."]]


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


def test_the_icons_are_the_revolving_book_at_their_sizes():
    """The app's icons (tools/make_icons.py) are the revolving book that
    chessbook/style.py draws: web/icon.svg is that drawing, still, on the page
    background, and favicon.svg the same; every PNG is there at its size and is
    web/icon.svg as it renders now; the book's chequer is in both of its tones
    (the darker board tone and the secondary text colour); and the maskable icon
    keeps it inside the middle 60 % and inside the circle that any mask keeps."""
    import struct
    import cv2
    import numpy as np
    sys.path.insert(0, str(ROOT / "tools"))
    import make_icons
    icons = ROOT / "web" / "icons"
    svg = (ROOT / "web" / "icon.svg").read_text(encoding="utf-8").strip()
    assert svg == make_icons.source_svg()
    assert (icons / "favicon.svg").read_text(encoding="utf-8").strip() == svg
    sizes = {"icon-32.png": 32, "icon-180.png": 180, "icon-192.png": 192, "icon-512.png": 512,
             "icon-maskable-512.png": 512}
    drawn = make_icons.pictures(svg)
    assert set(drawn) == set(sizes)
    pics = {}
    for name, size in sizes.items():
        data = (icons / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", data[16:24]) == (size, size), name
        pics[name] = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).astype(int)
        # drawn from the SVG as it is now (another PyMuPDF may smooth the edges a little otherwise)
        now = cv2.imdecode(np.frombuffer(drawn[name], np.uint8), cv2.IMREAD_COLOR).astype(int)
        assert np.abs(now - pics[name]).mean() < 2, name
    big = pics["icon-512.png"]
    share = lambda img, rgb: (np.abs(img - np.array(rgb[::-1])).max(axis=2) <= 6).mean()  # noqa: E731
    assert share(big, (0xbd, 0xba, 0xb2)) > 0.12 and share(big, (0x6f, 0x6f, 0x6c)) > 0.12
    # the maskable icon: what differs from the background lies in the middle 60 %, and within 40 %
    # of the icon's width from its centre
    mask = pics["icon-maskable-512.png"]
    ys, xs = np.nonzero(np.abs(mask - np.array([0xfa, 0xfb, 0xfb])).max(axis=2) > 8)
    assert xs.min() >= 0.2 * 512 and xs.max() < 0.8 * 512 and ys.min() >= 0.2 * 512 and ys.max() < 0.8 * 512
    assert np.hypot(xs - 255.5, ys - 255.5).max() <= 0.4 * 512
