"""The pipeline as the browser app runs it, inside Pyodide.

The worker writes the uploaded PDF to /books, calls process() once, and calls
chapter() whenever the reader opens a chapter. Chapters are built on demand,
so a book becomes readable as soon as its moves are decoded.

correct() applies the reader's corrections to the book in memory at once
(chessbook/live.py) and returns a patch for the open chapter reader;
correct_more() finishes a piece-symbol correction in the other chapters, a
few at a time. The corrections are saved as well, so that reading the book
again gives the same result.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

from chessbook import assemble, corrections, live, reader  # noqa: E402

OUT = Path("/out")
CFG = Path("/cfg")
STATE = {}


def process(path, say, selection_json=None, corrections_json=None):
    """Assemble the book and build its contents page. Returns the page's HTML.
    selection_json is the selection the reader stored in the browser, if any;
    corrections_json holds the reader's corrections stored there (diagrams,
    moves, sequences and piece symbols, see chessbook/corrections.py)."""
    pdf = Path(path)
    from chessbook import corrections
    fix_path = corrections.corrections_path(pdf, CFG)
    if corrections_json:
        try:
            corrections.save(corrections.parse_corrections_text(corrections_json), fix_path)
        except ValueError as exc:
            say(f"The stored corrections were not used: {exc}")
    elif fix_path.exists():
        fix_path.unlink()
    if selection_json:
        from chessbook import selection
        target = selection.selection_path(pdf, CFG)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(selection.parse_selection_text(selection_json)),
                          encoding="utf-8")
    keep = {}
    book = assemble.build_book(pdf, output_dir=OUT, books_dir=CFG, progress=say, state=keep)
    out = OUT / pdf.stem / "reader"
    say("Drawing the page thumbnails")
    reader.build_reader(book, pdf, out, chapters=set(), progress=say, app=True)
    STATE.clear()
    STATE.update(book=book, pdf=pdf, out=out, built=set(), keep=keep, data={},
                 fix_path=fix_path, index_stale=False)
    return (out / "index.html").read_text(encoding="utf-8")


def chapter(name, say, small=False):
    """The HTML of chapter file name (such as "ch07.html"), built on first use.
    small draws the pages at a lower resolution, for phones."""
    out = STATE["out"]
    if name not in STATE["built"]:
        k = int(name[2:-5])
        dpi, quality = reader.PAGE_DPI, reader.PAGE_QUALITY
        if small:
            reader.PAGE_DPI, reader.PAGE_QUALITY = 90, 55
        try:
            reader.build_reader(STATE["book"], STATE["pdf"], out, chapters={k},
                                progress=say, with_index=False)
        finally:
            reader.PAGE_DPI, reader.PAGE_QUALITY = dpi, quality
        STATE["built"].add(name)
        k = int(name[2:-5])
        ch = STATE["book"]["chapters"][k]
        STATE["data"][name] = reader.chapter_data(STATE["book"], ch, "")
    return (out / name).read_text(encoding="utf-8")


def index():
    if STATE.get("index_stale"):
        reader.build_reader(STATE["book"], STATE["pdf"], STATE["out"], chapters=set(), app=True)
        STATE["index_stale"] = False
    return (STATE["out"] / "index.html").read_text(encoding="utf-8")


def _chapter_of(name):
    return STATE["book"]["chapters"][int(name[2:-5])]


def correct(corrections_json, name):
    """Apply the reader's corrections (the whole set, as the reader stores
    it) to the book in memory. Returns JSON: {"patch": the changes for
    chapter file name, "pending": chapters whose lines a changed piece
    symbol still has to reach (see correct_more), "seconds"}."""
    t0 = time.perf_counter()
    fix = corrections.parse_corrections_text(corrections_json)
    corrections.save(fix, STATE["fix_path"])
    ch = _chapter_of(name)
    res = live.apply(STATE["keep"], STATE["book"], fix, chapters={ch["index"]})
    patch, data = live.chapter_patch(STATE["book"], ch, STATE["data"].get(name))
    STATE["data"][name] = data
    _stale(res, keep=name)
    return json.dumps({"patch": patch, "pending": res["pending"],
                       "chapters": len([c for c in STATE["book"]["chapters"]
                                        if c["end"] >= c["start"]]),
                       "seconds": round(time.perf_counter() - t0, 3)})


def correct_more(chapters_json, name):
    """Replay the lines of the given chapters (a JSON list of indices) that a
    changed piece symbol touches; returns the same JSON as correct(), with
    the patch for chapter file name when its data changed."""
    t0 = time.perf_counter()
    todo = set(json.loads(chapters_json))
    fix = STATE["book"]["corrections"]
    res = live.apply(STATE["keep"], STATE["book"], fix, chapters=todo)
    patch = None
    if name and name in STATE["data"]:
        ch = _chapter_of(name)
        if ch["index"] in todo:
            patch, STATE["data"][name] = live.chapter_patch(STATE["book"], ch, STATE["data"][name])
    _stale(res, keep=name)
    return json.dumps({"patch": patch, "pending": res["pending"],
                       "seconds": round(time.perf_counter() - t0, 3)})


def _stale(res, keep=None):
    """Chapter files written before the change are built again when opened."""
    pages = set(res["pages"])
    lines = set(res["lines"]) | set(res["removed"])
    book = STATE["book"]
    hit = set()
    for c in book["chapters"]:
        if any(c["start"] <= p <= c["end"] for p in pages):
            hit.add(c["file"])
    for L in book["lines"]:
        if L["id"] in lines:
            hit.add(book["chapters"][L["chapter"]]["file"])
    for f in hit:
        if f != keep:
            STATE["built"].discard(f)
    if keep:
        # the open reader holds the patched data; its file is written again on the next opening
        STATE["built"].discard(keep)
    STATE["index_stale"] = True
