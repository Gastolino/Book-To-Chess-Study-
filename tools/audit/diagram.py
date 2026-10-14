"""Check a diagram: the position the program read from its picture, and the
position its line reaches where the diagram stands.

Usage:
    python3 tools/audit/diagram.py BOOK DIAGRAM_ID     (p31-2: page 31, second diagram)
    python3 tools/audit/diagram.py BOOK --page 31

Prints the reading (FEN, confidence, doubtful squares, side to move and
where the side came from), the move the diagram stands after and the
position the line has there, both as boards, with the squares on which
they differ. The picture of the diagram goes to
output/audit/png/<book>_<id>.png, for comparison by eye: a difference is a
misread picture, a line gone wrong before the diagram, or a diagram tied
to the wrong move.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books  # noqa: E402


def board_rows(fen):
    rows = []
    for r in fen.split()[0].split("/"):
        row = ""
        for ch in r:
            row += "." * int(ch) if ch.isdigit() else ch
        rows.append(row)
    return rows


def differences(f1, f2):
    a, b = board_rows(f1), board_rows(f2)
    out = []
    for i in range(8):
        for j in range(8):
            if a[i][j] != b[i][j]:
                out.append(f"{'abcdefgh'[j]}{8 - i}: {a[i][j]} vs {b[i][j]}")
    return out


def check(book, name, d):
    nodes = book["nodes"]
    print(f"diagram {d['id']} page {d['id'].split('-')[0][1:]} kind={d['kind']} label={d['label']!r}"
          f" status={d['status']} selected={d['selected']} checked={d.get('checked')} lines={d['lines']}")
    r = d.get("reading") or {}
    if r:
        print(f"  reading: confidence {r.get('confidence')} doubtful {r.get('doubtful')} turn"
              f" {r.get('turn')} (from {r.get('turn_from')}) flipped {r.get('flipped')}")
    print(f"  fen      {d['fen']}")
    an = nodes.get(d.get("after_node")) if d.get("after_node") else None
    line_fen = an["fen"] if an else None
    if an:
        print(f"  after    {books.node_label(an)} ({d['after_node']}, page {an['page']}, line {an['line']})")
        print(f"  line fen {line_fen}")
    if d["fen"] and line_fen:
        diff = differences(d["fen"], line_fen)
        side = (d["fen"].split()[1:2], line_fen.split()[1:2])
        print(f"  {'SAME placement' if not diff else 'DIFFERENT on ' + ', '.join(diff)};"
              f" side to move {side[0]} vs {side[1]}")
        if diff:
            for x, y in zip(board_rows(d["fen"]), board_rows(line_fen)):
                print(f"    {x}    {y}")
    elif d["fen"]:
        for x in board_rows(d["fen"]):
            print(f"    {x}")
    import pymupdf
    doc = pymupdf.open(books.pdf_path(name))
    pg = int(d["id"].split("-")[0][1:])
    rect = pymupdf.Rect(*d["rect"]) if d.get("rect") else None
    out = books.png_dir() / f"{name}_{d['id']}.png"
    doc[pg - 1].get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5), clip=rect).save(out)
    print(f"  picture: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("id", nargs="?")
    ap.add_argument("--page", type=int, default=None)
    ap.add_argument("--code", default=None)
    a = ap.parse_args()
    book = books.load(a.book, code=a.code)
    ds = [d for pg in book["pages"] for d in pg["diagrams"]
          if (a.id and d["id"] == a.id) or (a.page and d["id"].startswith(f"p{a.page}-"))]
    if not ds:
        raise SystemExit("No such diagram.")
    for d in ds:
        check(book, a.book, d)


if __name__ == "__main__":
    main()
