"""The pipeline as the browser app runs it, inside Pyodide.

The worker writes the uploaded PDF to /books and calls start(); it then
calls step() again and again, and between two steps it answers the reader
(chapter(), index(), correct()), so that the book can be read while it is
assembled (chessbook/progressive.py). The contents page shows as soon as
the chapters are known, every chapter opens at once as pages, and the
moves appear chapter by chapter; when the whole book is read, the open
chapter receives the final reading as a patch.

correct() applies the reader's corrections to the book in memory at once
(chessbook/live.py) and returns a patch for the open chapter reader;
correct_more() finishes a piece-symbol correction in the other chapters, a
few at a time. A chapter that opens before correct_more() reaches it gets
the correction when it is built. The corrections are saved as well, so that
reading the book again gives the same result. While the book is still
read, a correction applies to a reading of the open chapter alone, and the
final book holds every correction.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

from chessbook import corrections, live, progressive, reader, selection  # noqa: E402

OUT = Path("/out")
CFG = Path("/cfg")
STATE = {}
BATCH_PAGES = 10        # pages of lines a piece-symbol correction replays per call (correct_more)


def start(path, selection_json=None, corrections_json=None):
    """Begin to read the book at path; step() does the work. selection_json
    is the selection the reader stored in the browser, if any;
    corrections_json holds the reader's corrections stored there (diagrams,
    moves, sequences and piece symbols, see chessbook/corrections.py). A
    selection or corrections file that an earlier reading of the same book
    left in the worker is removed when the browser holds none. Returns
    JSON: the messages for the page ({"type": "error"} when the stored
    corrections cannot be used)."""
    pdf = Path(path)
    notes = []
    fix_path = corrections.corrections_path(pdf, CFG)
    if fix_path.exists():
        fix_path.unlink()
    if corrections_json:
        try:
            corrections.save(corrections.parse_corrections_text(corrections_json), fix_path)
        except ValueError as exc:
            notes.append({"type": "progress", "text": f"The stored corrections were not used: {exc}"})
    target = selection.selection_path(pdf, CFG)
    if target.exists():
        target.unlink()
    if selection_json:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(selection.parse_selection_text(selection_json)),
                          encoding="utf-8")
    STATE.clear()
    STATE.update(job=progressive.Job(pdf, OUT, CFG), pdf=pdf, out=OUT / pdf.stem / "reader",
                 built=set(), built_from={}, data={}, fix_path=fix_path, index_stale=False, pending=set(),
                 open=None, book=None, keep=None, t0=time.perf_counter())
    return json.dumps(notes)


def process(path, say, selection_json=None, corrections_json=None):
    """start() and every step() at once: the book read to its end, as the
    worker reads it with no reader in between. Returns the contents page's
    HTML."""
    for note in json.loads(start(path, selection_json, corrections_json)):
        say(note["text"])
    while not json.loads(step())["done"]:
        pass
    return index()


def step():
    """One small piece of the work. Returns JSON {"events": [...], "done"}:
    the messages for the page (see progressive.Job.step), with the contents
    page's HTML in "index" and, at the end, in "done" when the contents page
    is open."""
    job = STATE["job"]
    if job.done:
        return json.dumps({"events": [], "done": True})
    events = []
    for ev in job.step():
        if ev["type"] == "index":
            ev["html"] = _index_html()
        elif ev["type"] == "patch":
            STATE["data"][ev["chapter"]] = job.data[ev["chapter"]]
            # the reader holds the new reading; its file is written again when opened
            STATE["built"].discard(ev["chapter"])
        elif ev["type"] == "done":
            _finished(job)
            if STATE["open"] is None:
                ev["html"] = index()
        events.append(ev)
    return json.dumps({"events": events, "done": job.done})


def _finished(job):
    """The final book: every chapter file written before it is stale."""
    STATE.update(book=job.final, keep=job.keep, built=set(), index_stale=True)
    data = {}
    if STATE["open"] and STATE["open"] in job.data and not job.changed:
        data[STATE["open"]] = job.data[STATE["open"]]
    STATE["data"] = data


def _loading():
    return STATE.get("book") is None


def _index_html():
    """The contents page while the book is read: the chapters as pages."""
    job = STATE["job"]
    reader.build_reader(job.plain, STATE["pdf"], STATE["out"], chapters=set(), app=True,
                        thumbs=job.thumbs, loading=True)
    return (STATE["out"] / "index.html").read_text(encoding="utf-8")


def chapter(name, say, small=False):
    """The HTML of chapter file name (such as "ch07.html"), built on first use.
    small draws the pages at a lower resolution, for phones. A chapter that a
    changed piece symbol has not reached yet (see correct_more) gets it first,
    so that it opens with every correction applied. While the book is read,
    the chapter opens with its best reading so far (pages only, or a first
    reading), and its reading comes first."""
    out = STATE["out"]
    k = int(name[2:-5])
    loading = _loading()
    if not loading and k in STATE["pending"]:
        res = live.apply(STATE["keep"], STATE["book"], STATE["book"]["corrections"], chapters={k})
        STATE["pending"] = set(res["pending"])
        _stale(res)
    book = STATE["job"].source(k) if loading else STATE["book"]
    if loading and STATE["built_from"].get(name) is not book:
        STATE["built"].discard(name)        # written from another reading
    if name not in STATE["built"]:
        dpi, quality = reader.PAGE_DPI, reader.PAGE_QUALITY
        if small:
            reader.PAGE_DPI, reader.PAGE_QUALITY = 90, 55
        try:
            reader.build_reader(book, STATE["pdf"], out, chapters={k},
                                progress=say, with_index=False)
        finally:
            reader.PAGE_DPI, reader.PAGE_QUALITY = dpi, quality
        STATE["built"].add(name)
        STATE["built_from"][name] = book
        ch = book["chapters"][k]
        STATE["data"][name] = live.snapshot(reader.chapter_data(book, ch, ""))
    STATE["open"] = name
    if loading:
        STATE["job"].opened(name, STATE["data"][name])
    return (out / name).read_text(encoding="utf-8")


def index():
    STATE["open"] = None
    if _loading():
        STATE["job"].closed()
        return _index_html()
    if STATE.get("index_stale"):
        job = STATE["job"]
        doc = job.ctx["doc"]
        for p in range(1, doc.page_count + 1):
            if p not in job.thumbs:
                job.thumbs[p] = reader.thumb(doc, p)
        reader.build_reader(STATE["book"], STATE["pdf"], STATE["out"], chapters=set(), app=True,
                            thumbs=job.thumbs)
        STATE["index_stale"] = False
    return (STATE["out"] / "index.html").read_text(encoding="utf-8")


def _chapter_of(name):
    return STATE["book"]["chapters"][int(name[2:-5])]


def correct(corrections_json, name):
    """Apply the reader's corrections (the whole set, as the reader stores
    it) to the book in memory. Returns JSON: {"patch": the changes for
    chapter file name, "pending": chapters whose lines a changed piece
    symbol still has to reach (see correct_more), "chapter": name,
    "seconds"}. While the book is read, "queued" says that the correction
    waits for the chapter's reading."""
    t0 = time.perf_counter()
    fix = corrections.parse_corrections_text(corrections_json)
    corrections.save(fix, STATE["fix_path"])
    if _loading():
        res = STATE["job"].correct(fix, name)
        STATE["data"][name] = STATE["job"].data.get(name, STATE["data"].get(name))
        STATE["built"].discard(name)
        return json.dumps({"patch": res["patch"], "pending": [], "chapter": name,
                           "queued": res["queued"], "seconds": round(time.perf_counter() - t0, 3)})
    ch = _chapter_of(name)
    res = live.apply(STATE["keep"], STATE["book"], fix, chapters={ch["index"]})
    STATE["pending"] = set(res["pending"])
    patch, data = live.chapter_patch(STATE["book"], ch, STATE["data"].get(name))
    STATE["data"][name] = data
    _stale(res, keep=name)
    return json.dumps({"patch": patch, "pending": res["pending"], "chapter": name,
                       "chapters": len([c for c in STATE["book"]["chapters"]
                                        if c["end"] >= c["start"]]),
                       "seconds": round(time.perf_counter() - t0, 3)})


def correct_more(chapters_json, name=""):
    """Replay the lines of the given chapters (a JSON list of indices) that a
    changed piece symbol touches; returns the same JSON as correct(), with
    the patch for the chapter the worker opened last (name when it has
    opened none since the contents page) when its lines changed."""
    t0 = time.perf_counter()
    if _loading():
        return json.dumps({"patch": None, "pending": [], "chapter": name, "seconds": 0})
    todo = set(json.loads(chapters_json))
    fix = STATE["book"]["corrections"]
    res = live.apply(STATE["keep"], STATE["book"], fix, chapters=todo, window=BATCH_PAGES)
    STATE["pending"] = set(res["pending"])
    name = STATE.get("open") or name
    patch = None
    if name and name in STATE["data"]:
        ch = _chapter_of(name)
        touched = set(res["lines"]) | set(res["removed"])
        if ch["index"] in todo or touched & set(STATE["data"][name]["lines"]):
            patch, STATE["data"][name] = live.chapter_patch(STATE["book"], ch, STATE["data"][name])
    _stale(res, keep=name)
    return json.dumps({"patch": patch, "pending": res["pending"], "chapter": name,
                       "seconds": round(time.perf_counter() - t0, 3)})


def timeline():
    """What happened when while the book was read (seconds from start())."""
    return json.dumps(STATE["job"].timeline if STATE.get("job") else {})


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
