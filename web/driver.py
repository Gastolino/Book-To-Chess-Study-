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

In the app's library (on the device, or on the Cloudflare site, see
docs/CLOUDFLARE.md) a book is read once: save_reading() gives the finished
reading as bytes, which the app stores, and restore() opens the book from
them without reading it again. A stored reading holds what the reading
produced (the book, as book.json holds it, and the builder's state that
applies corrections live), never the reader's pages: the contents page and
the chapter readers are always built from it by the reader code of the day,
so a change of the reader, the app or their look keeps every stored reading.
A stored reading names the VERSION of the reading code that made it (a
digest of the modules that decide what is read, READING_FILES) and the
selection it was made with. restore() refuses one made with another
selection (the user asked for Read again); one made by other reading code
opens all the same, marked "outdated", and the app offers to read the book
again ("An improved reading is available"). When the builder's state of a
stored reading cannot be loaded by this program, the book opens from the
stored book alone, for reading, and corrections need the book read again.

The pages are not part of the chapter readers: the app asks draw() for the
pictures of ten pages at a time (a window), around the page shown, and
keeps them in the device's library.
"""
import base64
import gc
import hashlib
import io
import json
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

from chessbook import corrections, live, progressive, reader, region, selection  # noqa: E402

OUT = Path("/out")
CFG = Path("/cfg")
STATE = {}
BATCH_PAGES = 10        # pages of lines a piece-symbol correction replays per call (correct_more)
READING_MAGIC = b"chessbook-reading\n"          # format 1: one pickle of {"book", "keep"}
READING_MAGIC2 = b"chessbook-reading/2\n"       # format 2: the book, then the keep (save_reading)
PARTIAL_MAGIC = b"chessbook-partial/1\n"        # the parts of an unfinished reading (checkpoint)
COVER_WIDTH = 240       # pixels across the cover picture of the library
# Chapter readers kept built (their file, and the data their reader holds) after the reader leaves them: the last few, so that
# going back is quick, and the rest of the book takes no memory. An iPhone
# drops a page that takes too much, and the reader then loses its place.
KEEP_CHAPTERS = 3


# The files whose change can change what the program reads in a book: the
# reading itself, the layout and the board and figurine pictures, the
# selection and the corrections. Everything else (the reader, its scripts,
# its look, the app) builds pages from a reading and leaves it valid.
READING_FILES = ("chessbook/assemble.py", "chessbook/movetext.py", "chessbook/boards.py",
                 "chessbook/figshapes.py", "chessbook/figurines.py", "chessbook/pdftext.py",
                 "chessbook/textdiagram.py", "chessbook/selection.py", "chessbook/corrections.py",
                 "chessbook/live.py", "chessbook/region.py", "chessbook/assets", "stage1_inspect.py")
# The form of a stored reading (save_reading); raised by hand when it changes.
READING_FORMAT = 2


def _version(files=READING_FILES, root=None):
    """A digest of the reading code (the files under root, the project by
    default): a stored reading made by other reading code opens all the
    same, and the app offers to read the book again."""
    root = Path(root) if root else Path(corrections.__file__).resolve().parents[1]
    paths = []
    for name in files:
        p = root / name
        if p.is_dir():
            paths += sorted(q for q in p.rglob("*") if q.is_file() and "__pycache__" not in q.parts)
        elif p.exists():
            paths.append(p)
    h = hashlib.sha256(str(READING_FORMAT).encode("ascii"))
    for p in paths:
        h.update(p.relative_to(root).as_posix().encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


VERSION = _version()


def _selection_key(selection_json):
    """The selection as one canonical text (None for the default), to tell
    whether a stored reading was made with the selection in use now."""
    if not selection_json:
        return None
    data = selection.parse_selection_text(selection_json)
    data.pop("note", None)
    return json.dumps(data, sort_keys=True)


def start(path, selection_json=None, corrections_json=None, partial_path=None):
    """Begin to read the book at path; step() does the work. selection_json
    is the selection the reader stored in the browser, if any;
    corrections_json holds the reader's corrections stored there (diagrams,
    moves, sequences and piece symbols, see chessbook/corrections.py). A
    selection or corrections file that an earlier reading of the same book
    left in the worker is removed when the browser holds none. Returns
    JSON: the messages for the page ({"type": "error"} when the stored
    corrections cannot be used). partial_path names the parts of an earlier,
    unfinished reading of the book (checkpoint()): what of them this code
    made, and for the same selection, is not read again."""
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
    _clear()
    job = progressive.Job(pdf, OUT, CFG)
    saved = _resume_parts(pdf, partial_path, _selection_key(selection_json), job) if partial_path else set()
    if saved:
        notes.append({"type": "progress", "text": "The earlier reading of this book is taken up where it "
                      "stopped: " + ("the pages and the boards are" if "boards" in saved
                                     else "the pages are") + " read already."})
    STATE.update(job=job, pdf=pdf, out=OUT / pdf.stem / "reader", thumbs=job.thumbs,
                 built=set(), built_from={}, data={}, recent=[], fix_path=fix_path, index_stale=False,
                 pending=set(), open=None, book=None, keep=None, t0=time.perf_counter(),
                 selection=_selection_key(selection_json), restored=False, timeline={},
                 saved=saved, reading_version=None)
    return json.dumps(notes)


STAGE1_FILES = ("diagrams.json", "numbers.json", "pages.json")


def checkpoint():
    """The parts of the reading under way that cost the most and are done
    (Stage 1's findings, then the board readings), as bytes: a header line
    (JSON: the VERSION of the reading code, the selection, the PDF's name
    and page count, the parts), then one pickle of plain values. Stored by
    the app until the reading is finished, so that a reading cut short (the
    app closed, the phone took the memory back) goes on from them."""
    job = STATE["job"]
    if job is None:
        raise ValueError("No book is being read.")
    ctx = job.ctx
    dest = OUT / STATE["pdf"].resolve().stem / "stage1"
    stage1 = {n: (dest / n).read_text(encoding="utf-8") for n in STAGE1_FILES if (dest / n).exists()}
    if ctx.get("diagrams") is None or "diagrams.json" not in stage1:
        raise ValueError("Nothing of the reading is finished yet.")
    readings = ctx.get("readings") if ctx.get("boards_read") else None
    parts = ["stage1"] + (["boards"] if readings is not None else [])
    header = {"version": VERSION, "selection": STATE.get("selection"), "pdf": STATE["pdf"].name,
              "pages": ctx["doc"].page_count, "parts": parts}
    out = io.BytesIO()
    out.write(PARTIAL_MAGIC + json.dumps(header).encode("utf-8") + b"\n")
    pickle.dump({"stage1": stage1, "readings": readings}, out, protocol=pickle.HIGHEST_PROTOCOL)
    return out.getvalue()


def _resume_parts(pdf, partial_path, selection_key, job):
    """Put back the parts of an unfinished reading (checkpoint()) that this
    code made: Stage 1's files where the build finds them, and the board
    readings when the selection is the same (the first pass, which teaches
    the board reader, depends on it). Returns the parts put back."""
    try:
        with open(partial_path, "rb") as f:
            if f.read(len(PARTIAL_MAGIC)) != PARTIAL_MAGIC:
                return set()
            header = json.loads(f.readline())
            data = pickle.load(f)
    except Exception:
        return set()
    if header.get("version") != VERSION or header.get("pdf") != pdf.name:
        return set()
    stage1 = data.get("stage1") or {}
    if "diagrams.json" not in stage1 or "pages.json" not in stage1:
        return set()
    dest = OUT / pdf.resolve().stem / "stage1"
    dest.mkdir(parents=True, exist_ok=True)
    for name in STAGE1_FILES:
        if (dest / name).exists():
            (dest / name).unlink()
        if name in stage1:
            (dest / name).write_text(stage1[name], encoding="utf-8")
    saved = {"stage1"}
    if data.get("readings") is not None and header.get("selection") == selection_key:
        job.ctx["stored_readings"] = data["readings"]
        saved.add("boards")
    return saved


def _clear():
    """Forget the book before (its document, its readers' files), and give
    the memory back before the next one takes its own."""
    doc = STATE.get("doc")
    if doc is None and STATE.get("job") is not None:
        doc = STATE["job"].ctx.get("doc")
    out = STATE.get("out")
    STATE.clear()
    if doc is not None:
        try:
            doc.close()
        except Exception:
            pass
    if out is not None:
        for f in out.glob("ch*.html"):
            f.unlink()
    _lighten()


def _lighten(full=False):
    """Give back what is no longer needed: PyMuPDF's cache of the pages it
    drew (it would keep up to 256 MB of them, and in the browser the memory
    Python has once taken is never given back to the system), and, when
    full, Python's cycles. A full collection walks every object (about a
    second for the Primer, more in the browser), so it is made only once a
    book is in memory, and the objects alive then are frozen: a later
    collection skips them and costs nothing. Building a chapter leaves no
    cycles behind, measured on the Primer."""
    try:
        import pymupdf
        pymupdf.TOOLS.store_shrink(100)
    except Exception:
        pass
    if full:
        gc.unfreeze()
        gc.collect()
        gc.freeze()


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
    if STATE.get("restored"):
        return _restored_step()
    job = STATE["job"]
    if job is None or job.done:
        return json.dumps({"events": [], "done": True})
    events = []
    for ev in job.step():
        if ev["type"] == "index":
            ev["html"] = _index_html()
            ev.update(title=job.plain["title"], pages=job.plain["page_count"], **_chapter_list(job.plain))
        elif ev["type"] == "patch":
            STATE["data"][ev["chapter"]] = job.data[ev["chapter"]]
            # the reader holds the new reading; its file is written again when opened
            STATE["built"].discard(ev["chapter"])
        elif ev["type"] == "done":
            _finished(job)
            if STATE["open"] is None:
                ev["html"] = index()
        events.append(ev)
    if not job.done:
        # a part of the reading finished: the app stores it (checkpoint())
        saved = STATE["saved"]
        if "stage1" not in saved and job.ctx.get("diagrams") is not None:
            saved.add("stage1")
            events.append({"type": "checkpoint", "parts": sorted(saved)})
        elif "boards" not in saved and job.ctx.get("boards_read"):
            saved.add("boards")
            events.append({"type": "checkpoint", "parts": sorted(saved)})
    # the pages drawn in this step are not needed again: without this the
    # cache grows to 256 MB while the book is read, and that memory stays taken
    if STATE.get("job") is not None:      # (the job is let go when the book is done)
        _lighten()
    return json.dumps({"events": events, "done": job.done})


def _finished(job):
    """The final book: every chapter file written before it is stale. The
    job itself is let go: what it learnt while reading (the pages' findings,
    the figurine cuts, the readings of each pass) is not needed to show the
    book, and takes much memory."""
    STATE.update(book=job.final, keep=job.keep, built=set(), index_stale=True, doc=job.ctx["doc"],
                 timeline=job.timeline, job=None)
    data = {}
    if STATE["open"] and STATE["open"] in job.data and not job.changed:
        data[STATE["open"]] = job.data[STATE["open"]]
    STATE["data"] = data
    STATE["recent"] = [n for n in STATE.get("recent", []) if n in data]
    for f in STATE["out"].glob("ch*.html"):
        f.unlink()
    _lighten(full=True)


def _loading():
    return STATE.get("book") is None


def _index_html():
    """The contents page while the book is read: the chapters as pages."""
    job = STATE["job"]
    reader.build_reader(job.plain, STATE["pdf"], STATE["out"], chapters=set(), app=True,
                        thumbs=job.thumbs, loading=True)
    return (STATE["out"] / "index.html").read_text(encoding="utf-8")


def chapter(name, say, small=False, prepare=False):
    """The HTML of chapter file name (such as "ch07.html"), built on first use,
    without its page pictures (the app asks draw() for them, ten pages at a
    time). small is kept for older pages of the app and changes nothing now.
    A chapter that a changed piece symbol has not reached yet (see
    correct_more) gets it first, so that it opens with every correction
    applied. While the book is read, the chapter opens with its best reading
    so far (pages only, or a first reading), and its reading comes first.
    prepare builds the chapter that the reader is about to turn to, without
    making it the open one (the app shows it at once when the page turns)."""
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
        reader.build_reader(book, STATE["pdf"], out, chapters={k},
                            progress=say, with_index=False, images=False)
        STATE["built"].add(name)
        STATE["built_from"][name] = book
        ch = book["chapters"][k]
        STATE["data"][name] = live.snapshot(reader.chapter_data(book, ch, ""))
        _lighten()
    if not prepare:
        STATE["open"] = name
        if loading:
            STATE["job"].opened(name, STATE["data"][name])
    _forget_old(name, keep_open=prepare)
    return (out / name).read_text(encoding="utf-8")


# The resolution of the page pictures for each kind of screen: a phone, and
# anything larger (reader.PAGE_DPI and PAGE_QUALITY).
DRAW = {"small": (90, 55), "large": (reader.PAGE_DPI, reader.PAGE_QUALITY)}


def draw(pages_json, size="large"):
    """The pictures of the given pages (a JSON list of PDF page numbers), as
    one bytes object: a header line (JSON {"pages": [[page, length], ...],
    "size", "dpi"}) and the JPEGs one after another. size is "small" for a
    phone and "large" otherwise."""
    dpi, quality = DRAW.get(size, DRAW["large"])
    doc = _doc()
    parts, index = [], []
    for p in json.loads(pages_json):
        if not isinstance(p, int) or not 1 <= p <= doc.page_count:
            continue
        jpg = reader.page_jpeg(doc, p, dpi, quality)
        parts.append(jpg)
        index.append([p, len(jpg)])
    _lighten()
    head = json.dumps({"pages": index, "size": size, "dpi": dpi}).encode("utf-8")
    return head + b"\n" + b"".join(parts)


def _forget_old(name, keep_open=False):
    """Chapter name is open (or about to open): the chapters left longest
    ago, beyond KEEP_CHAPTERS, lose their built file and their data (they
    are built again when they open). keep_open spares the open chapter."""
    recent = [n for n in STATE.get("recent", []) if n != name] + [name]
    if keep_open and STATE.get("open") in recent:
        recent.remove(STATE["open"])
        recent.append(STATE["open"])
    for old in recent[:-KEEP_CHAPTERS]:
        STATE["built"].discard(old)
        STATE["built_from"].pop(old, None)
        STATE["data"].pop(old, None)
        job = STATE.get("job")
        if job is not None:
            job.data.pop(old, None)
        f = STATE["out"] / old
        if f.exists():
            f.unlink()
    STATE["recent"] = recent[-KEEP_CHAPTERS:]


def index():
    STATE["open"] = None
    if _loading():
        STATE["job"].closed()
        return _index_html()
    if STATE.get("index_stale"):
        doc = _doc()
        for p in range(1, doc.page_count + 1):
            if p not in STATE["thumbs"]:
                STATE["thumbs"][p] = reader.thumb(doc, p)
        reader.build_reader(STATE["book"], STATE["pdf"], STATE["out"], chapters=set(), app=True,
                            thumbs=STATE["thumbs"])
        STATE["index_stale"] = False
        _lighten()
    return (STATE["out"] / "index.html").read_text(encoding="utf-8")


def _doc():
    """The open PDF document of the book."""
    return STATE.get("doc") or STATE["job"].ctx["doc"]


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
    _no_state()
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
    _settle()
    if _loading() or STATE.get("keep") is None:
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


# ---------------------------------------------------------------- a section of a page

def words(page, x0, y0, x1, y1, near=0):
    """The words of the text layer of PDF page `page` in and near the
    rectangle (x0, y0)-(x1, y1), in PDF points, with their boxes (see
    chessbook/region.py words()), as JSON: the reader's selection snaps to
    the word under a tap."""
    return json.dumps(region.words(_doc(), int(page), [x0, y0, x1, y1], float(near or 0)))


def _region_decoder():
    """The book's own decoder: its glyph model and letters, with the piece
    symbols the reader named. While the book is read, the glyph model learnt
    so far (or the one every book starts from)."""
    if STATE.get("book") is not None:
        _settle()
        if STATE.get("keep") is not None:
            return STATE["keep"]["builder"].dec
    from chessbook import assemble
    from chessbook.movetext import GlyphModel
    job = STATE.get("job")
    ctx = job.ctx if job is not None else {}
    letters = ctx.get("letters") or (STATE.get("book") or {}).get("letters")
    return assemble._Decoder(ctx.get("glyphs") or GlyphModel(seed=True), letters)


def _position_at(at, side):
    """The position that the moves of a section start from: at is a FEN, or
    the id or token key of a move of the book, and side "after" or "before"
    that move."""
    if "/" in at:
        return at
    book = STATE.get("book")
    if book is None and STATE.get("job") is not None and STATE.get("open"):
        book = STATE["job"].source(int(STATE["open"][2:-5]))
    nodes = (book or {}).get("nodes") or {}
    n = nodes.get(at) or next((v for v in nodes.values() if v.get("key") == at), None)
    if n is None:
        raise ValueError("The program no longer finds the move that the section follows.")
    if side == "before":
        n = nodes.get(n["parent"]) if n.get("parent") is not None else None
    if n is None or not n.get("fen"):
        raise ValueError("The position at that move is unknown, so the program cannot read moves from it.")
    return n["fen"]


def read_region(page, rect_json, at, side="after", other=None):
    """What the program reads in a section of PDF page `page` (rect_json: the
    rectangle [x0, y0, x1, y1] in PDF points): the text printed there and the
    move sequences it reads as, decoded with the book's own decoder from the
    position after (or before) the move at (a FEN, a node id or a token
    key), legal there, best first. other is the position of the other place
    the moves may go (before the move rather than after it, or after rather
    than before), when there is one: when nothing reads without doubt from
    the chosen place but a reading does from the other, "other" names that
    place and its best reading (a printed "Qe4" is White's move, so the
    moves go before Black's move rather than after it). Returns JSON
    {"text", "words", "fen", "candidates": [{"san", "cost", "unsure"}],
    "other": {"side", "fen", "san"} or null, "seconds"}."""
    t0 = time.perf_counter()
    rect = [float(v) for v in json.loads(rect_json)]
    doc = _doc()
    found = [w for w in region.words(doc, int(page), rect) if w["inside"]]
    text = " ".join(w["text"] for w in found)
    fen = _position_at(str(at), side)
    dec = _region_decoder() if text else None
    cands = region.read(dec, fen, text) if text else []
    alt = None
    if text and other and not any(c["unsure"] == 0 for c in cands):
        sure = [c for c in region.read(dec, str(other), text) if c["unsure"] == 0]
        if sure:
            alt = {"side": "before" if side == "after" else "after", "fen": str(other), "san": sure[0]["san"]}
    return json.dumps({"text": text, "words": found, "fen": fen, "candidates": cands, "other": alt,
                       "seconds": round(time.perf_counter() - t0, 3)})


def timeline():
    """What happened when while the book was read (seconds from start())."""
    job = STATE.get("job")
    return json.dumps(job.timeline if job is not None else STATE.get("timeline") or {})


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


# ---------------------------------------------------------------- the library

def save_reading():
    """The finished reading of the book as bytes, to open it again later
    without reading it (restore()): a header line (JSON: the VERSION of the
    reading code, the format, the selection used, the PDF's name and page
    count), then two pickles in one stream: the book (book.json as a dict:
    plain values only, so that any later program loads it) and the state
    that applies corrections live (live.py: the builder, whose classes a
    later program may have changed). One pickler writes both, so that what
    they share stays shared. The PDF itself is not part of it: restore()
    opens it again."""
    if _loading():
        raise ValueError("The book is still being read.")
    _settle()
    keep = STATE["keep"]
    if keep is None:
        raise ValueError("The book was opened without the state that applies corrections.")
    b = keep["builder"]
    book = STATE["book"]
    # a reading saved again (with the thumbnails drawn since) keeps the version of the code that
    # made it, so that the app still offers to read it again with today's code
    header = {"version": STATE.get("reading_version") or VERSION, "format": READING_FORMAT,
              "selection": STATE.get("selection"), "pdf": STATE["pdf"].name,
              "pages": book["page_count"], "thumbs": True}
    doc, b.doc = b.doc, None
    out = io.BytesIO()
    out.write(READING_MAGIC2 + json.dumps(header).encode("utf-8") + b"\n")
    try:
        p = pickle.Pickler(out, protocol=pickle.HIGHEST_PROTOCOL)
        p.dump(book)
        # the contents page's thumbnails, so that a book opened again draws none
        # (as JPEG bytes: base64 would take a third more room)
        p.dump({k: base64.b64decode(v) for k, v in (STATE.get("thumbs") or {}).items()})
        p.dump({k: v for k, v in keep.items() if k != "doc"})
    finally:
        b.doc = doc
    return out.getvalue()


def reading_version():
    """The VERSION that save_reading() writes in its header: that of the code
    that read the book (a stored reading saved again keeps it)."""
    return STATE.get("reading_version") or VERSION


def reading_header(path):
    """The header of a stored reading (save_reading), or None when the file
    is not one. A reading of format 1 has no "format" in its header."""
    with open(path, "rb") as f:
        head = f.read(len(READING_MAGIC2))
        if head == READING_MAGIC2:
            pass
        elif head[:len(READING_MAGIC)] == READING_MAGIC:
            f.seek(len(READING_MAGIC))
        else:
            return None
        try:
            h = json.loads(f.readline())
        except ValueError:
            return None
        h["format"] = 2 if head == READING_MAGIC2 else 1      # the form of the file is its first line
        return h


class _Later:
    """The state that applies corrections, left in a stored reading until it
    is needed (_settle): loading it takes most of the time of opening a book,
    and its figurine shapes need numpy and OpenCV, which the app loads after
    it is ready. It shares objects with the book, so the same unpickler
    loads it, from the reading kept in memory meanwhile."""

    def __init__(self, unpickler, buf):
        self.unpickler, self.buf = unpickler, buf

    def load(self):
        try:
            return self.unpickler.load()
        finally:
            self.unpickler = self.buf = None


def _load_reading(path, header, later=False):
    """(book, keep, thumbs) from a stored reading; keep is None when this
    program cannot load the builder's state, and book None when it cannot
    load the book either. thumbs is {} for a reading saved without them.
    With later, keep is a _Later (for a reading of format 2) instead."""
    if later and header["format"] >= 2:
        buf = io.BytesIO(Path(path).read_bytes())
        buf.read(len(READING_MAGIC2))
        buf.readline()
        u = pickle.Unpickler(buf)
        try:
            book = u.load()
        except Exception:
            return None, None, {}
        try:
            thumbs = u.load() if header.get("thumbs") else {}
        except Exception:
            return book, None, {}           # nor can the state that follows load
        return book, _Later(u, buf), {k: base64.b64encode(v).decode("ascii") for k, v in thumbs.items()}
    with open(path, "rb") as f:
        f.read(len(READING_MAGIC2) if header["format"] >= 2 else len(READING_MAGIC))
        f.readline()
        u = pickle.Unpickler(f)
        if header["format"] < 2:
            try:
                data = u.load()
            except Exception:
                return None, None, {}
            return data["book"], data["keep"], {}
        try:
            book = u.load()
        except Exception:
            return None, None, {}
        thumbs = {}
        if header.get("thumbs"):
            try:
                thumbs = {k: base64.b64encode(v).decode("ascii") for k, v in u.load().items()}
            except Exception:
                return book, None, {}
        try:
            keep = u.load()
        except Exception:
            keep = None
        return book, keep, thumbs


def restore(path, reading_path, selection_json=None, corrections_json=None):
    """Open the book at path from its stored reading (the bytes of
    save_reading() in the file reading_path) instead of reading it. The
    corrections stored in the browser are applied live when they differ
    from those the reading holds. Returns JSON: the messages for the page,
    [{"type": "stale", "why"}] when the reading cannot be used (it is
    damaged, or it was made with another selection), or the contents page
    ({"type": "index"}), whose "outdated" names why the book could be read
    better ("code": other reading code made it; "state": this program
    cannot apply corrections to it). step() then draws the page thumbnails
    and ends with {"type": "done"}, as when the book is read."""
    pdf = Path(path)
    header = reading_header(reading_path)
    if header is None:
        return json.dumps([{"type": "stale", "why": "The stored reading is damaged."}])
    if header.get("selection") != _selection_key(selection_json):
        return json.dumps([{"type": "stale", "why": "The selection of pages and diagrams changed "
                                                    "since the stored reading was made."}])
    t0 = time.perf_counter()
    book, later, thumbs = _load_reading(reading_path, header, later=True)
    if book is None:
        return json.dumps([{"type": "stale", "why": "The stored reading was made by a version of "
                                                    "the program that this one cannot open."}])
    import pymupdf
    _clear()
    doc = pymupdf.open(pdf)
    fix_path = corrections.corrections_path(pdf, CFG)
    fix = corrections.parse_corrections_text(corrections_json) if corrections_json else \
        corrections.empty()
    corrections.save(fix, fix_path)
    old = corrections.normalise(book.get("corrections") or {})
    differ = any(fix[k] != old[k] for k in corrections.PARTS)
    # the state that applies corrections is loaded now only when corrections made since the
    # reading was stored must be applied before the book shows; otherwise after it shows
    keep = _settle_keep(later, doc, pdf) if differ or not isinstance(later, _Later) else None
    outdated = None
    if keep is None and (differ or not isinstance(later, _Later)):
        outdated = "state"
    elif header.get("version") != VERSION:
        outdated = "code"
    if keep is not None and differ:
        try:
            live.apply(keep, book, fix)
        except Exception:
            # the builder of other reading code: the book opens as it was stored
            outdated = "state"
            keep = None
    target = selection.selection_path(pdf, CFG)
    if target.exists():
        target.unlink()
    if selection_json:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(selection.parse_selection_text(selection_json)),
                          encoding="utf-8")
    STATE.update(job=None, pdf=pdf, out=OUT / pdf.stem / "reader", doc=doc, thumbs=thumbs,
                 built=set(), built_from={}, data={}, recent=[], fix_path=fix_path, index_stale=False,
                 pending=set(), open=None, book=book, keep=keep, t0=t0,
                 selection=header.get("selection"), restored=True, timeline={}, outdated=outdated,
                 reading_version=header.get("version"), thumbs_drawn=False,
                 keep_later=later if keep is None and outdated != "state" else None)
    reader.build_reader(book, pdf, STATE["out"], chapters=set(), app=True, thumbs=STATE["thumbs"])
    html = (STATE["out"] / "index.html").read_text(encoding="utf-8")
    _lighten(full=True)
    return json.dumps([dict({"type": "index", "html": html, "title": book["title"],
                             "pages": book["page_count"], "restored": True, "outdated": outdated,
                             "seconds": round(time.perf_counter() - t0, 2)}, **_chapter_list(book))])


def _settle_keep(later, doc, pdf):
    """The state that applies corrections, from a _Later (or as loaded), tied
    to the open document; None when this program cannot load it."""
    try:
        keep = later.load() if isinstance(later, _Later) else later
    except Exception:
        keep = None
    if keep is not None:
        keep.update(doc=doc, pdf=pdf)
        keep["builder"].doc = doc
    return keep


def _settle():
    """Load the state that applies corrections of a book opened from its
    stored reading, if it waits still. Returns "state" when it cannot be
    loaded (the book shows as stored, and corrections need it read again)."""
    later = STATE.pop("keep_later", None)
    if later is None:
        return None
    keep = _settle_keep(later, STATE["doc"], STATE["pdf"])
    STATE["keep"] = keep
    if keep is None:
        STATE["outdated"] = "state"
        return "state"
    return None


def _chapter_list(book):
    """The chapters for the app (which chapter file holds which pages), and
    the file of the chapter that holds page 1, where a new book opens."""
    chs = [{"file": c["file"], "start": c["start"], "end": c["end"]}
           for c in book["chapters"] if c["end"] >= c["start"]]
    first = next((c["file"] for c in chs if c["start"] <= 1 <= c["end"]), chs[0]["file"] if chs else None)
    return {"chapters": chs, "first": first}


def _no_state():
    _settle()
    if STATE.get("book") is not None and STATE.get("keep") is None:
        raise ValueError("This copy of the book was read by an earlier version of the program, which "
                         "this one cannot correct. Read again reads the book anew and keeps your "
                         "corrections, bookmarks and place.")


def _restored_step():
    """After restore(): the state that applies corrections, the page
    thumbnails of the contents page (a batch at a time), then "done"."""
    if STATE.get("keep_later") is not None:
        why = _settle()
        return json.dumps({"events": [{"type": "outdated", "why": why}] if why else [], "done": False})
    doc = STATE["doc"]
    todo = [p for p in range(1, doc.page_count + 1) if p not in STATE["thumbs"]]
    todo = todo[:progressive.THUMB_BATCH]
    if todo:
        got = {p: reader.thumb(doc, p) for p in todo}
        STATE["thumbs"].update(got)
        STATE["thumbs_drawn"] = True
        return json.dumps({"events": [{"type": "thumbs", "thumbs": got}], "done": False})
    STATE["restored"] = False
    STATE["index_stale"] = True
    # a reading stored without its thumbnails is stored again with them (by the app)
    ev = {"type": "done", "restored": True,
          "resave": bool(STATE.get("thumbs_drawn")) and STATE.get("keep") is not None}
    if STATE["open"] is None:
        ev["html"] = index()
    _lighten()
    return json.dumps({"events": [ev], "done": True})


def memory():
    """What Python holds now, as JSON (for measurements): the objects after
    a collection, and the size of PyMuPDF's cache of decoded pages."""
    import gc
    gc.collect()
    import pymupdf
    return json.dumps({"objects": len(gc.get_objects()), "store": pymupdf.TOOLS.store_size(),
                       "chapters": sorted(STATE.get("built") or []),
                       "data": sorted((STATE.get("data") or {}).keys())})


def cover(path):
    """A small colour JPEG of the book's first page, for the library."""
    import pymupdf
    doc = pymupdf.open(path)
    page = doc[0]
    zoom = COVER_WIDTH / max(page.rect.width, 1)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False)
    return pix.tobytes("jpg", jpg_quality=70)
