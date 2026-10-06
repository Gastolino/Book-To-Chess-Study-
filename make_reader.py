"""Build the interactive book reader for a chess book PDF.

Usage:
    python3 make_reader.py BOOK.pdf [--chapters 5,7] [--selection FILE]
                           [--corrections FILE] [--letters English] [--passes 3] [--reuse]
                           [--engine DIR]

Writes, under output/<book>/:
    book.json           every line, move, variation and comment the program assembled
    pgn/chNN.pgn        one PGN file per chapter (decoded lines only)
    reader/index.html   contents, page thumbnails and the page and diagram selection
    reader/chNN.html    one reader per chapter: book page beside a live board

--chapters limits the chapter readers to the given chapter numbers (the NN of
chNN.html; 0 is the front matter). The whole book is always assembled,
because the program learns the book's move glyphs from all of it.
--selection reads a selection pasted from the reader's "Copy selection"
button (a file holding the pasted text) and saves it as the book's
selection before building.
--corrections reads corrections pasted from the contents page's "Copy
corrections" button (a file holding the pasted text) and saves them as the
book's corrections (books/<book>/corrections.json) before building; the
build always applies the book's saved corrections.
--reuse skips the assembly when output/<book>/book.json already exists.
--engine DIR copies the chess engine (tools/fetch_engine.py fetches it into
DIR) into reader/engine/, so that the chapter readers offer analysis with
Stockfish; a reader whose folder already holds engine/ offers it as well.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from chessbook import assemble, corrections, engine_files, reader, selection  # noqa: E402
from chessbook.movetext import LETTER_SETS  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the interactive reader of a chess book PDF.")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--chapters", default=None,
                    help="comma-separated chapter numbers (the NN of chNN.html)")
    ap.add_argument("--selection", type=Path, default=None,
                    help="file holding a selection copied from the reader")
    ap.add_argument("--corrections", type=Path, default=None,
                    help="file holding corrections copied from the reader")
    ap.add_argument("--letters", default=None, choices=sorted(LETTER_SETS),
                    help="piece letters of the book's notation (default English)")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--reuse", action="store_true", help="reuse output/<book>/book.json")
    ap.add_argument("--engine", type=Path, default=None,
                    help="folder holding the chess engine files, copied next to the reader")
    args = ap.parse_args(argv)
    pdf = args.pdf
    if not pdf.exists():
        raise SystemExit(f"Cannot find {pdf}.")
    t0 = time.perf_counter()
    if args.selection:
        data = selection.parse_selection_text(args.selection.read_text(encoding="utf-8"))
        path = selection.Selection(data).save(selection.selection_path(pdf))
        print(f"Saved the selection to {path}")
    if args.corrections:
        data = corrections.parse_corrections_text(args.corrections.read_text(encoding="utf-8"))
        path = corrections.save(data, corrections.corrections_path(pdf))
        n = corrections.count(data)
        print(f"Saved the corrections to {path}: {n['diagrams']} diagrams, {n['moves']} moves, "
              f"{n['unattached']} sequences, {n['glyphs']} piece symbols")
    out_root = assemble.OUTPUT_DIR / pdf.stem
    book_path = out_root / "book.json"
    if args.reuse and book_path.exists():
        book = json.loads(book_path.read_text(encoding="utf-8"))
        print(f"Reused {book_path}")
    else:
        book = assemble.build_book(pdf, letters=args.letters, passes=args.passes, progress=print)
        print(f"Wrote {book_path}")
    chapters = None
    if args.chapters:
        chapters = {int(x) for x in args.chapters.replace(" ", "").split(",") if x}
    if args.engine:
        engine_files.copy(args.engine, out_root / "reader" / "engine")
        print(f"Copied the engine into {out_root / 'reader' / 'engine'}")
    engine = engine_files.present(out_root / "reader" / "engine")
    rep = reader.build_reader(book, pdf, out_root / "reader", chapters=chapters, progress=print,
                              engine=engine)
    st = book["stats"]
    print(json.dumps({"lines": st["lines"], "games": st["games"], "fragments": st["fragments"],
                      "line_status": st["line_status"], "moves": st["moves"],
                      "variations": st["variations"], "unattached": st["unattached"],
                      "waiting": st["waiting"], "corrected": st.get("corrected")}, indent=1))
    bad = {k: v["problems"] for k, v in rep["pgn"].items() if v["problems"]}
    print("PGN files:", ", ".join(f"ch{k:02d}: {v['games']} games" for k, v in rep["pgn"].items()))
    if bad:
        print("PGN problems:", json.dumps(bad, indent=1))
    print(f"Open {out_root / 'reader' / 'index.html'} ({time.perf_counter() - t0:.0f} s)")


if __name__ == "__main__":
    main()
