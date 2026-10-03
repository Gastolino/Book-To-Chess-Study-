"""The pipeline as the browser app runs it, inside Pyodide.

The worker writes the uploaded PDF to /books, calls process() once, and calls
chapter() whenever the reader opens a chapter. Chapters are built on demand,
so a book becomes readable as soon as its moves are decoded.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from chessbook import assemble, reader  # noqa: E402

OUT = Path("/out")
CFG = Path("/cfg")
STATE = {}


def process(path, say, selection_json=None):
    """Assemble the book and build its contents page. Returns the page's HTML.
    selection_json is the selection the reader stored in the browser, if any."""
    pdf = Path(path)
    if selection_json:
        from chessbook import selection
        target = selection.selection_path(pdf, CFG)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(selection.parse_selection_text(selection_json)),
                          encoding="utf-8")
    book = assemble.build_book(pdf, output_dir=OUT, books_dir=CFG, progress=say)
    out = OUT / pdf.stem / "reader"
    say("Drawing the page thumbnails")
    reader.build_reader(book, pdf, out, chapters=set(), progress=say, app=True)
    STATE.update(book=book, pdf=pdf, out=out, built=set())
    return (out / "index.html").read_text(encoding="utf-8")


def chapter(name, say):
    """The HTML of chapter file name (such as "ch07.html"), built on first use."""
    out = STATE["out"]
    if name not in STATE["built"]:
        k = int(name[2:-5])
        reader.build_reader(STATE["book"], STATE["pdf"], out, chapters={k},
                            progress=say, with_index=False)
        STATE["built"].add(name)
    return (out / name).read_text(encoding="utf-8")


def index():
    return (STATE["out"] / "index.html").read_text(encoding="utf-8")
