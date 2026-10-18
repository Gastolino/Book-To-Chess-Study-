"""The books an audit reads, and the cached readings of them.

Every tool of the audit reads a book through load(): the program's reading
of it (book.json as a dict) and, when asked, the builder's state, with
which the corrections replay as they do in the app (chessbook/live.py).
build() makes the reading once for each version of the reading code and
keeps it under output/audit/<code>/, where <code> is a digest of the files
that decide what is read (web/driver.py READING_FILES). A change to that
code reads the books afresh; a worktree with the same code reuses the
readings of the main checkout.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # a listing piped into head ends quietly
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

READING_FILES = ("chessbook/assemble.py", "chessbook/movetext.py", "chessbook/boards.py",
                 "chessbook/figshapes.py", "chessbook/figurines.py", "chessbook/pdftext.py",
                 "chessbook/textdiagram.py", "chessbook/selection.py", "chessbook/corrections.py",
                 "chessbook/live.py", "chessbook/region.py", "chessbook/assets", "stage1_inspect.py")


def main_root() -> Path:
    """The main checkout (a worktree finds the books and the shared cache there)."""
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        return Path(common).parent
    except Exception:
        return ROOT


MAIN = main_root()

# name -> PDF, relative to the main checkout
BOOKS = {
    "ivanchuk": "corpus/ivanchuk.pdf",      # 5 pages, one annotated game, letters
    "gpa": "corpus/gpa.pdf",
    "planning": "corpus/planning.pdf",      # Art of Planning: OCR junk figurines
    "alekhine": "corpus/alekhine.pdf",
    "kia": "corpus/kia.pdf",
    "primer": "primer.pdf",                 # The Soviet Chess Primer, scanned
    "brunthaler": "corpus/archive3/brunthaler.pdf",
    "tangborn": "corpus/archive3/tangborn.pdf",
}


def pdf_path(name: str) -> Path:
    if name not in BOOKS:
        raise SystemExit(f"Unknown book {name!r}; the books are {', '.join(BOOKS)}.")
    p = Path(os.environ.get("AUDIT_BOOKS_ROOT", MAIN)) / BOOKS[name]
    if not p.exists():
        raise SystemExit(f"Cannot find {p}.")
    return p


def code_digest(root: Path = ROOT) -> str:
    h = hashlib.sha1()
    for rel in READING_FILES:
        p = root / rel
        files = sorted(q for q in p.rglob("*") if q.is_file()) if p.is_dir() else [p]
        for q in files:
            if "__pycache__" in q.parts:
                continue
            h.update(str(q.relative_to(root)).encode())
            h.update(q.read_bytes())
    return h.hexdigest()[:12]


def cache_dir(code: str | None = None) -> Path:
    base = Path(os.environ.get("AUDIT_CACHE", MAIN / "output" / "audit"))
    d = base / (code or code_digest())
    d.mkdir(parents=True, exist_ok=True)
    return d


def png_dir() -> Path:
    d = Path(os.environ.get("AUDIT_PNG", MAIN / "output" / "audit" / "png"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def build(name: str, force: bool = False, code: str | None = None) -> dict:
    """Read the book with the current code (no saved corrections) and keep the
    reading, the builder's state and a summary. Returns the summary."""
    from chessbook import assemble
    d = cache_dir(code)
    summ_path = d / f"{name}.summary.json"
    if not force and summ_path.exists() and (d / f"{name}.pkl").exists():
        return json.loads(summ_path.read_text())
    pdf = pdf_path(name)
    empty = d / "books_empty"
    empty.mkdir(exist_ok=True)
    state = {}
    t0 = time.perf_counter()
    summary = {"book": name, "pdf": str(pdf), "code": d.name}
    try:
        book = assemble.build_book(pdf, output_dir=d / "out", books_dir=empty, state=state,
                                   write=False, corrections={})
    except Exception as e:
        summary.update(error=repr(e), traceback=traceback.format_exc(),
                       seconds=round(time.perf_counter() - t0, 1))
        summ_path.write_text(json.dumps(summary, indent=1))
        return summary
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    b = state["builder"]
    b.doc = None
    keep = {k: v for k, v in state.items() if k != "doc"}
    with open(d / f"{name}.pkl", "wb") as f:
        pickle.dump((book, keep), f, protocol=pickle.HIGHEST_PROTOCOL)
    (d / f"{name}.json").write_text(json.dumps(book, ensure_ascii=False))
    summary.update(page_count=book["page_count"], title=book["title"], stats=book["stats"],
                   chapters=len(book["chapters"]), moves_font=bool(b.moves_font))
    summ_path.write_text(json.dumps(summary, indent=1))
    return summary


def load(name: str, state: bool = False, code: str | None = None):
    """The reading of the book (book.json as a dict), and with state=True also
    the builder's state, ready for chessbook.live (a fresh copy each call)."""
    d = cache_dir(code)
    if state:
        p = d / f"{name}.pkl"
        if not p.exists():
            build(name, code=code)
        import pymupdf
        with open(p, "rb") as f:
            book, keep = pickle.load(f)
        keep["builder"].doc = pymupdf.open(pdf_path(name))
        return book, keep
    p = d / f"{name}.json"
    if not p.exists():
        build(name, code=code)
    return json.loads(p.read_text())


def node_label(n: dict) -> str:
    if not n:
        return "?"
    return f"{n.get('number')}{'...' if n.get('black') else '.'}{n.get('san') or '?'}"
