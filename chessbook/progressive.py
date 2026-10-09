"""Read a book in the browser app while it is assembled.

assemble.build_steps does the work of build_book in small steps. A Job
drives those steps, one at a time, and between them the browser app's
worker answers the reader (a chapter to open, a correction). The reader
sees the book in three states:

1. Pages: as soon as the layout and the chapters are known, the contents
   page shows and every chapter opens as plain pages (reader.chapter_data
   "reading": "pages").
2. First readings: chapter by chapter, the moves of the book appear
   ("reading": "first"). The first pass of the assembly reads the chapters
   in order, and the Job copies each chapter from it as the pass leaves it.
   A chapter the reader opens before the pass reaches it is read at once on
   its own (a "solo" reading, with what the build has learnt so far), and so
   is the first chapter of the book before the pass begins. A correction in
   a chapter makes a solo reading of it too, which then takes further
   corrections live (live.py), as the final book does.
3. The final book: when the whole-book learning has finished, the open
   chapter receives the final reading as a patch (live.chapter_patch with
   replace), and the page and the chosen move stay put. The final book is
   the book build_book makes, with the corrections made meanwhile applied.

The Job knows nothing of the browser: the driver (web/driver.py) turns its
events into messages for the page.
"""
from __future__ import annotations

import copy
import json
import time

from . import assemble, corrections as fixes, live, reader
from . import selection as sel

THUMB_BATCH = 24        # page thumbnails drawn per step


def chapter_part(book, k, plain_pages):
    """The part of book (book.json as a dict) that the reader of chapter k
    reads (reader.chapter_data), copied so that it shares nothing with the
    book; the pages of the other chapters are plain_pages (without marks)."""
    ch = book["chapters"][k]

    def inside(p):
        return ch["start"] <= p <= ch["end"]

    lines = [L for L in book["lines"]
             if L["chapter"] == k or (L["page"] <= ch["end"] and L["end_page"] >= ch["start"])]
    ids = {L["id"] for L in lines}
    part = {key: v for key, v in book.items() if key not in ("lines", "nodes", "pages")}
    part.update(lines=lines, nodes={nid: n for nid, n in book["nodes"].items() if n["line"] in ids},
                pages=[pg for pg in book["pages"] if inside(pg["page"])],
                unattached=[u for u in book["unattached"] if u.get("chapter") == k],
                dismissed=[u for u in book["dismissed"] if u.get("chapter") == k],
                attached=[u for u in book["attached"] if u.get("chapter") == k],
                waiting=[u for u in book["waiting"] if u.get("chapter") == k])
    part = json.loads(json.dumps(part))
    own = {pg["page"]: pg for pg in part["pages"]}
    part["pages"] = [own.get(pg["page"], pg) for pg in plain_pages]
    return part


def partial_diagrams(found):
    """Stage 1's diagrams (expanded as build_steps expands them) of the pages
    it has inspected so far (found: page index -> inspect_page findings), in
    page order. The series of the numbers is that of these pages alone."""
    import stage1_inspect
    keys = sorted(found)
    numbers = [dict(x) for i in keys for x in found[i][2]]
    diagrams = copy.deepcopy([d for i in keys for d in found[i][1]])
    main_ids = stage1_inspect.main_series(numbers)
    main_keys = {(x["page"], x["label"]) for k, x in enumerate(numbers) if k in main_ids}
    for d in diagrams:
        d["series"] = "main" if (d["page"], d["label"]) in main_keys else "other"
        for b in d.get("boards", []):
            b["series"] = "main" if (d["page"], b["label"]) in main_keys else "other"
    return sel.expand_boards(diagrams)


class Job:
    """One book read progressively. step() does one small piece of work and
    returns the events for the page: {"type": "index"} (the contents page,
    once, as soon as the chapters are known), "status" (the line of the top
    bar), "reading" (a new reading of the open chapter, as a patch),
    "thumbs" (page thumbnails for the contents page) and "done" (the final
    book is ready). The driver builds a chapter's reader from source(k)
    and reports it with opened(); correct() takes the reader's corrections."""

    def __init__(self, pdf, out_dir, books_dir=None, corrections=None, progress=None):
        self.pdf = pdf
        self.ctx = {"first_pages": self._first_pages}
        self.keep = {}
        self.fix = fixes.normalise(corrections) if corrections is not None else \
            fixes.load(pdf, books_dir)
        self.say = progress or (lambda *_: None)
        self.steps = assemble.build_steps(pdf, output_dir=out_dir, books_dir=books_dir,
                                          progress=self.say, state=self.keep, ctx=self.ctx)
        self.t0 = time.perf_counter()
        self.plain = None           # the book as pages only
        self.prov = {}              # chapter index -> its first reading (a book dict)
        self.solo = {}              # chapter index -> {"book", "keep"}: a solo reading
        self.data = {}              # chapter file -> the data its open reader holds
        self.open = None            # the chapter file open in the reader (None: contents)
        self.thumbs = {}            # page -> thumbnail
        self.final = None
        self.changed = False        # the final chapters differ from the first ones
        self.status = ""
        self.last = None            # the last event of build_steps
        self.timeline = {}          # what happened when, in seconds from the start

    # ------------------------------------------------------------ queries
    @property
    def done(self):
        return self.final is not None

    def chapters(self):
        return self.plain["chapters"] if self.plain else []

    def chapter_index(self, name):
        return int(name[2:-5])

    def source(self, k):
        """The book dict to build the reader of chapter k from."""
        if self.final is not None:
            return self.final
        if k in self.solo:
            return self.solo[k]["book"]
        if k in self.prov:
            return self.prov[k]
        return self.plain

    def has_reading(self, k):
        return k in self.solo or k in self.prov

    # ------------------------------------------------------------ the reader
    def opened(self, name, data):
        """The reader of chapter file name opened with data (chapter_data)."""
        self.open = name
        self.data[name] = data

    def closed(self):
        """The reader went to the contents page."""
        self.open = None

    def correct(self, fix, name):
        """Apply the reader's corrections (the whole set) while the book is
        read: to the solo reading of the chapter, made now when the chapter
        has none. Returns {"patch", "pending", "queued"}; the final book
        gets every correction (build_steps ctx["fix"])."""
        self.fix = fixes.normalise(fix)
        self.ctx["fix"] = self.fix
        k = self.chapter_index(name)
        if k in self.solo:
            s = self.solo[k]
            live.apply(s["keep"], s["book"], self.fix, chapters={k})
            ch = s["book"]["chapters"][k]
            patch, self.data[name] = live.chapter_patch(s["book"], ch, self.data.get(name))
            return {"patch": patch, "pending": [], "queued": False}
        if self._can_solo(k):
            self._solo(k)
            patch = self._patch(name, "Your correction is applied.")
            return {"patch": patch, "pending": [], "queued": False}
        return {"patch": None, "pending": [], "queued": True}

    def read_on(self, fix, name, after, pages=None, skip=()):
        """Apply the reader's corrections (the whole set) and read on by
        itself from the move after (live.read_on) while the book is read:
        in the solo reading of the chapter, made now when the chapter has
        none (the corrected chapter comes first; the pages read are then the
        chapter's). The corrections the program made join the set that the
        final book gets. Returns live.read_on's result with "patch" and
        "queued" (no reading of the chapter can be made yet: nothing read)."""
        self.fix = fixes.normalise(fix)
        self.ctx["fix"] = self.fix
        k = self.chapter_index(name)
        fresh = k not in self.solo
        if fresh:
            if not self._can_solo(k):
                return {"patch": None, "queued": True, "corrections": self.fix, "auto": {},
                        "joined": [], "filled": [], "moves": 0, "stop": None, "until": None,
                        "end": None}
            self._solo(k)
        s = self.solo[k]
        res = live.read_on(s["keep"], s["book"], self.fix, after, chapters={k}, pages=pages,
                           skip=skip)
        self.fix = res["corrections"]
        self.ctx["fix"] = self.fix
        if fresh:
            res["patch"] = self._patch(name, "Your correction is applied.")
        else:
            ch = s["book"]["chapters"][k]
            res["patch"], self.data[name] = live.chapter_patch(s["book"], ch, self.data.get(name))
        res["queued"] = False
        return res

    # ------------------------------------------------------------ the work
    def _first_pages(self):
        """The pages Stage 1 is to inspect first: those of the chapter wanted."""
        k = self._wanted()
        if k is None:
            return []
        ch = self.chapters()[k]
        return list(range(ch["start"], ch["end"] + 1))

    def _real(self, k):
        chs = self.chapters()
        return 0 <= k < len(chs) and chs[k]["end"] >= chs[k]["start"]

    def _wanted(self):
        """The chapter whose first reading is wanted now: the open one, or
        before the first pass begins, the chapter after it (the reader goes
        on from where it is: the first chapter of the book when the front
        matter or nothing is open)."""
        if self.plain is None or self.changed:
            return None
        here = 0
        if self.open is not None:
            k = self.chapter_index(self.open)
            if self._real(k) and not self.has_reading(k):
                return k
            here = k
        if self.ctx.get("pass_no", 0) == 0:
            for k in range(max(here + 1, 1), len(self.chapters())):
                if self._real(k):
                    return None if self.has_reading(k) else k
        return None

    def _can_solo(self, k):
        if self.changed or self.plain is None or not self._real(k):
            return False
        if self.ctx.get("diagrams") is not None:
            return True
        ch = self.chapters()[k]
        found = self.ctx.get("stage1_found") or {}
        return all(p - 1 in found for p in range(ch["start"], ch["end"] + 1))

    def _next_in_pass(self):
        """The chapter the first pass reads next (None outside it)."""
        if not self.ctx.get("first_pass") or self.ctx.get("pass_no") != 1:
            return None     # (after the figurines were learnt, the chapters are all read)
        return self._pass_at()

    def _pass_at(self):
        """The chapter the assembly pass at work reads now or next."""
        if self.last and self.last[0] == "part":
            return self.last[1][1]
        last = self.last[1][1] if self.last and self.last[0] == "chapter" else -1
        for k in range(last + 1, len(self.ctx["chapters"])):
            if 0 <= k < len(self.ctx["chapters"]) and \
                    self.ctx["chapters"][k]["end"] >= self.ctx["chapters"][k]["start"]:
                return k
        return None

    def _solo(self, k):
        """Read chapter k on its own with what the build knows now, and the
        corrections."""
        t = time.perf_counter()
        c = self.ctx
        diagrams = c.get("diagrams")
        if diagrams is None:
            diagrams = partial_diagrams(c["stage1_found"])
            selection = sel.load_selection(c["pdf"], c["structure"], diagrams, c["books_dir"])
            text = {did: d["fen"] for did, d in zip(sel.diagram_ids(diagrams), diagrams)
                    if d.get("fen")}
            fens = text or None
        else:
            selection, fens = c["selection"], c.get("diagram_fens")
        readings = c.get("readings") or {}
        b, _ = assemble._assemble(c["doc"], c["fonts"], c["chapters"], diagrams, selection,
                                  c["glyphs"], c["letters"], fens, only={k},
                                  dotless=c["numbering"]["dotless"], readings=readings)
        b.finalize(self.fix)
        book = assemble._book_dict(c["pdf"], c["doc"], c["chapters"], diagrams, selection, b,
                                   c["glyphs"], c["structure"], readings, b.fix, c["letters"])
        book["reading"] = "first"
        self.solo[k] = {"book": book, "keep": {"builder": b, "readings": readings}}
        self.timeline.setdefault(f"chapter {k} read alone", round(time.perf_counter() - self.t0, 1))
        self.say(f"chapter {k} read alone in {time.perf_counter() - t:.1f} s")

    def _snapshot(self, k):
        """Chapter k as the first pass has just left it."""
        c = self.ctx
        b = c["builder"]
        full = assemble._book_dict(c["pdf"], c["doc"], c["chapters"], c["diagrams"],
                                   c["selection"], b, c["glyphs"], c["structure"], c["readings"],
                                   fixes.empty(), c["letters"])
        part = chapter_part(full, k, self.plain["pages"])
        part["reading"] = "first"
        self.prov[k] = part

    def _patch(self, name, words, final=False):
        """The patch that brings the open reader of name to its new reading."""
        k = self.chapter_index(name)
        book = self.source(k)
        ch = book["chapters"][k]
        patch, self.data[name] = live.chapter_patch(book, ch, self.data.get(name), replace=True)
        patch["progress"] = words
        return patch

    def _reading_event(self, k, words):
        name = self.chapters()[k]["file"]
        if self.open != name or name not in self.data:
            return []
        return [{"type": "patch", "chapter": name, "reading": True,
                 "result": {"patch": self._patch(name, words), "pending": [], "chapter": name}}]

    def _set_status(self, text):
        if text == self.status:
            return []
        self.status = text
        return [{"type": "status", "text": text}]

    def _plain_book(self):
        """The book as pages, without diagrams or moves."""
        c = self.ctx
        selection = sel.load_selection(c["pdf"], c["structure"], [], c["books_dir"])
        b = assemble._Builder(c["doc"], c["fonts"], c["chapters"], [], selection,
                              assemble._Decoder(c["glyphs"], c["letters"]), {},
                              c["numbering"]["dotless"])
        book = assemble._book_dict(c["pdf"], c["doc"], c["chapters"], [], selection, b,
                                   c["glyphs"], c["structure"], {}, self.fix, c["letters"])
        book["reading"] = "pages"
        return book

    def step(self):
        """Do one piece of work; returns the events for the page."""
        if self.final is not None:
            return []
        k = self._wanted()
        if k is not None and self._can_solo(k) and self._next_in_pass() != k:
            out = self._set_status(f"Reading the moves of chapter {k}")
            self._solo(k)
            return out + self._reading_event(k, "The program has read the moves of this chapter. "
                                          "It goes on reading the rest of the book.")
        if self.plain is not None and len(self.thumbs) < self.plain["page_count"] \
                and self.has_reading(self._first_chapter()):
            doc = self.ctx["doc"]
            todo = [p for p in range(1, doc.page_count + 1) if p not in self.thumbs][:THUMB_BATCH]
            got = {p: reader.thumb(doc, p) for p in todo}
            self.thumbs.update(got)
            return [{"type": "thumbs", "thumbs": got}]
        try:
            ev = next(self.steps)
        except StopIteration as end:
            return self._finish(end.value)
        self.last = ev
        return self._on(ev)

    def _first_chapter(self):
        for k in range(1, len(self.chapters())):
            if self._real(k):
                return k
        return 0

    def _on(self, ev):
        kind, info = ev
        c = self.ctx
        out = []
        if c.get("shapes") is not None and "figurines read" not in self.timeline:
            # the figurines of the moves were read by their shape (figshapes.py)
            self.timeline["figurines read"] = round(time.perf_counter() - self.t0, 1)
            self.timeline["figurines named"] = len(c["shapes"].reading())
        if kind == "structure":
            self.plain = self._plain_book()
            self.timeline["contents"] = round(time.perf_counter() - self.t0, 1)
            out.append({"type": "index"})
            out += self._set_status("Reading the pages")
        elif kind == "stage1":
            out += self._set_status(f"Reading the pages: {info[0]} of {info[1]}")
        elif kind == "restructure":
            new = [(x["start"], x["end"], x["title"]) for x in c["chapters"]]
            old = [(x["start"], x["end"], x["title"]) for x in self.chapters()]
            self.changed = self.changed or new != old
        elif kind in ("chapter", "part"):
            pass_no, ci = info
            at = self._pass_at()
            last = len(c["chapters"]) - 1
            where = ("the front matter" if at == 0 else f"chapter {at} of {last}"
                     if at is not None else f"chapter {last} of {last}")
            # the first pass, and after the figurines were learnt, the first pass that
            # reads the book again with them
            first = c.get("first_pass") and (pass_no == 1 or c.get("figmap"))
            out += self._set_status(("Reading the moves: " if first else
                                     "Improving the reading: ") + where)
            if first and kind == "chapter":
                if pass_no > 1:
                    self.prov.pop(ci, None)
                if not self.changed and not self.has_reading(ci):
                    self._snapshot(ci)
                    self.timeline.setdefault(f"chapter {ci} read",
                                             round(time.perf_counter() - self.t0, 1))
                    out += self._reading_event(ci, "The program has read the moves of this "
                                                   "chapter. It goes on reading the rest of the "
                                                   "book.")
        elif kind == "boards":
            out += self._set_status(f"Reading the diagrams: {info[0]} of {info[1]}")
        elif kind == "shapes":
            out += self._set_status(f"Reading the piece figurines: page {info[0]} of {info[1]}")
        return out

    def _finish(self, book):
        """The final book: the open chapter gets it as a patch."""
        self.final = book
        self.timeline["final"] = round(time.perf_counter() - self.t0, 1)
        self.prov.clear()
        self.solo.clear()
        new = [(x["start"], x["end"], x["title"]) for x in book["chapters"]]
        old = [(x["start"], x["end"], x["title"]) for x in self.chapters()]
        self.changed = self.changed or new != old
        out = []
        if self.open is not None and self.open in self.data:
            if self.changed:
                out.append({"type": "reopen", "chapter": self.open})
            else:
                name = self.open
                patch = self._patch(name, "The program has read the whole book. This chapter "
                                          "now shows the final reading.")
                out.append({"type": "patch", "chapter": name, "reading": True,
                            "result": {"patch": patch, "pending": [], "chapter": name}})
        self.status = ""
        out.append({"type": "done", "seconds": round(time.perf_counter() - self.t0, 1),
                    "changed": self.changed})
        return out
