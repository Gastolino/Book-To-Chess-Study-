"""The browser app reads a book progressively (chessbook/progressive.py):
chapters open and show first readings while the book is assembled, and the
final book must be the one build_book makes, with the corrections made
meanwhile. These tests drive a progressive.Job the way web/driver.py does
(open chapters before the first pass reaches them, correct a move while
the book is read) and compare its final book with build_book's.

Stage 1 runs inside the job (as in the browser, where no Stage 1 results
are stored), page by page and out of order. The corpus books are used
when they are present (they are kept out of git).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from chessbook import assemble, corrections, live, progressive, reader  # noqa: E402

BOOKS = {"ivanchuk": ROOT / "corpus" / "ivanchuk.pdf", "gpa": ROOT / "corpus" / "gpa.pdf",
         "primer": ROOT / "primer.pdf"}


def _open(job, k):
    book = job.source(k)
    ch = book["chapters"][k]
    job.opened(ch["file"], live.snapshot(reader.chapter_data(book, ch, "")))
    return ch["file"]


def _a_move(data):
    """The key of a decoded main-line move, with moves before and after it."""
    for lid in data["lineOrder"]:
        nid, k = data["lines"][lid]["root"], 0
        while nid:
            n = data["nodes"][nid]
            nxt = next((c for c in n["children"] if data["nodes"].get(c, {}).get("main")), None)
            if k >= 3 and n.get("key") and n["status"] == "ok" and nxt:
                return n["key"]
            nid, k = nxt, k + 1
    return None


def _progressive(pdf, tmp, monkeypatch, correct=True):
    """Read pdf as the app does; returns (final book, corrections made, job, events)."""
    monkeypatch.setattr(assemble, "OUTPUT_DIR", tmp / "shared")     # Stage 1 runs in the job
    job = progressive.Job(pdf, tmp / "out", tmp / "books")
    events, fix, steps = [], None, 0
    later = None
    while not job.done:
        events += job.step()
        steps += 1
        if job.plain is not None and job.open is None:
            _open(job, 1)                       # the first chapter, at once
            chs = [c for c in job.chapters() if c["end"] >= c["start"]]
            later = chs[-1]["index"] if len(chs) > 2 else None
        if later is not None and job.has_reading(1) and job.ctx.get("pass_no", 0) == 0:
            # a later chapter, before the first pass begins: it jumps the queue
            name = _open(job, later)
            assert not job.has_reading(later)
            while not job.has_reading(later):
                events += job.step()
            assert job.ctx.get("pass_no", 0) <= 1
            key = _a_move(job.data[name]) if correct else None
            if key:
                fix = corrections.empty()
                fix["disconnect"][key] = {"start": "here"}
                res = job.correct(fix, name)
                assert res["patch"] and not res["queued"]
                nodes = res["patch"]["nodes"]
                assert any(n.get("key") == key and n.get("corrected") == "split" for n in nodes.values())
            later = None
    return job.final, fix, job, events


def _same(a, b):
    for part in ("lines", "nodes", "pages", "chapters", "unattached", "waiting", "dismissed",
                 "attached"):
        assert json.loads(json.dumps(a[part])) == json.loads(json.dumps(b[part])), part


@pytest.mark.parametrize("name", ["little", "ivanchuk", "gpa", "primer"])
def test_progressive_equals_build_book(name, tmp_path, monkeypatch):
    if name == "little":
        from test_assemble import make_book
        from test_corrections import GARBLED, NOTE
        pdf = make_book(tmp_path / "garbled.pdf", game=GARBLED, note7=NOTE, second=True)
    else:
        pdf = BOOKS[name]
        if not pdf.exists():
            pytest.skip(f"{pdf.name} is not here")
    book, fix, job, events = _progressive(pdf, tmp_path / "p", monkeypatch)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "index" and kinds[-1] == "done"
    # the first chapter got its first reading, then the final one, as patches
    assert [e["reading"] for e in events if e["type"] == "patch"]
    assert "chapter 1 read alone" in job.timeline
    assert job.timeline["contents"] < job.timeline["chapter 1 read alone"] < job.timeline["final"]
    monkeypatch.undo()
    ref = assemble.build_book(pdf, output_dir=tmp_path / "r", books_dir=tmp_path / "rb",
                              write=False, corrections=fix)
    _same(book, ref)
    if fix:
        assert book["corrections"]["disconnect"] == fix["disconnect"]


def test_final_patch_keeps_the_move(tmp_path, monkeypatch):
    """The final reading reaches the open chapter as a patch that renames
    every move of the first reading to the move printed at the same place."""
    from test_assemble import make_book
    from test_corrections import GARBLED, NOTE
    pdf = make_book(tmp_path / "garbled.pdf", game=GARBLED, note7=NOTE, second=True)
    _, _, job, events = _progressive(pdf, tmp_path, monkeypatch, correct=False)
    patches = [e for e in events if e["type"] == "patch"]
    last = patches[-1]["chapter"]          # the chapter open at the end
    mine = [e["result"]["patch"] for e in patches if e["chapter"] == last]
    first, final = mine[0], mine[-1]
    assert first["reading"] == "first" and final["reading"] is None
    keyed = {k: v["key"] for k, v in first["nodes"].items() if v.get("key")}
    assert keyed and all(k in final["removed"] for k in first["nodes"])
    for old, key in keyed.items():
        new = final["renamed"].get(old)
        assert new and final["nodes"][new]["key"] == key


def test_the_reading_goes_on_from_the_open_chapter():
    """Before the first pass, the chapter read ahead is the one after the
    open chapter (the reader goes on from where it is), not the first one
    of the book; with the front matter or nothing open, it is the first."""
    job = progressive.Job.__new__(progressive.Job)
    chapters = [{"start": 1, "end": 4}] + [{"start": 5 + 10 * i, "end": 14 + 10 * i} for i in range(5)]
    for i, c in enumerate(chapters):
        c["file"] = f"ch{i:02d}.html"
    job.plain, job.changed, job.solo, job.prov, job.ctx = {"chapters": chapters}, False, {}, {}, {}
    job.open = None
    assert job._wanted() == 1
    job.open = "ch00.html"
    assert job._wanted() == 0                   # the open front matter itself
    job.solo[0] = {}
    assert job._wanted() == 1
    job.open = "ch03.html"
    assert job._wanted() == 3                   # the open chapter first
    job.solo[3] = {}
    assert job._wanted() == 4                   # then the one after it, not chapter 1
    job.solo[4] = {}
    assert job._wanted() is None
    job.open = "ch05.html"
    job.solo[5] = {}
    assert job._wanted() is None                # the last chapter: nothing after it
    job.ctx["pass_no"] = 1
    job.open = "ch02.html"
    assert job._wanted() == 2                   # during the pass, only the open chapter
    job.solo[2] = {}
    assert job._wanted() is None
