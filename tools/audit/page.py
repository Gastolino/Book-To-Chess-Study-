"""Show one page of a book as the program reads it, beside the print.

Usage:
    python3 tools/audit/page.py BOOK PAGE [--text] [--plain] [--clip x0,y0,x1,y1] [--zoom 2]

PAGE is the PDF page (1-based), not the printed folio. The listing gives
every move token the program marked on the page, in its order, numbered as
the boxes of the picture are: the text as the text layer reads it (raw),
the move the program made of it, its status, its line, whether it stands in
the main line or a variation, the move it follows, and its token key (the
key that corrections use). The diagrams of the page follow, with the
position read and the move they stand after.

The picture (output/audit/png/<book>_p<page>.png) draws each token's box in
the colour of its status, with its number, and the program's move above
every box whose move is doubtful or differs from the print:

    green ok, amber guessed, orange ambiguous, red failed, blue waiting,
    violet unattached (placed in no line), dashed box: a variation move.

--plain draws the page alone, --clip enlarges part of it (PDF points),
--text prints the page's text layer as well, so that printed moves the
program did not mark at all show.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books  # noqa: E402

COLOURS = {"ok": (0.1, 0.65, 0.2), "guessed": (0.95, 0.65, 0.0), "ambiguous": (1.0, 0.4, 0.0),
           "failed": (0.9, 0.0, 0.0), "waiting": (0.1, 0.35, 0.95), "unattached": (0.6, 0.1, 0.8)}


def describe(book, page):
    nodes = book["nodes"]
    pg = next((p for p in book["pages"] if p["page"] == page), None)
    if pg is None:
        raise SystemExit(f"The book has no page {page} (1..{book['page_count']}).")
    unatt = {u["key"]: u for u in book.get("unattached", [])}
    rows = []
    for i, m in enumerate(pg["marks"], 1):
        n = nodes.get(m.get("node")) if m.get("node") else None
        row = {"n": i, "key": m["key"], "raw": m["raw"], "status": m["status"], "bbox": m["bbox"],
               "line": m.get("line")}
        if n:
            par = nodes.get(n["parent"]) if n.get("parent") else None
            row.update(move=books.node_label(n), san=n["san"], main=n["main"],
                       after=books.node_label(par) if par and par.get("san") else "(start)",
                       node=m["node"], corrected=n.get("corrected"), auto=n.get("auto"),
                       assumed=n.get("assumed"), comment=(n.get("comment") or "")[:60])
        if m["key"] in unatt:
            row["unattached"] = unatt[m["key"]].get("reason")
        rows.append(row)
    return pg, rows


def listing(book, page, text=False):
    pg, rows = describe(book, page)
    ch = next((c for c in book["chapters"] if c["index"] == pg["chapter"]), None)
    print(f"{book['pdf']} page {page} (folio {pg['folio']}), chapter {pg['chapter']}"
          f" {ch['title']!r}" if ch else "", f"selected={pg['selected']}")
    lines = {r["line"] for r in rows if r.get("line")}
    for L in book["lines"]:
        if L["id"] in lines:
            print(f"  line {L['id']} {L['kind']} {L['title']!r} pages {L['page']}-{L['end_page']}"
                  f" status {L['status']} diagram {L['diagram']} moves {L['moves']}"
                  f" start {L['start_note'][:80]!r}")
    for r in rows:
        flags = " ".join(x for x in (
            "" if r.get("main", True) else "var",
            f"corrected={r['corrected']}" if r.get("corrected") else "",
            "auto" if r.get("auto") else "",
            f"assumed={r['assumed']}" if r.get("assumed") else "") if x)
        mv = r.get("move", "-")
        print(f"#{r['n']:<3} {r['raw']!r:<16} -> {mv:<14} [{r['status']}] {r.get('line') or ''}"
              f" after {r.get('after', '-')} {flags}  key={r['key']}"
              + (f"\n      unattached: {r['unattached']}" if r.get("unattached") else ""))
    for d in pg["diagrams"]:
        an = book["nodes"].get(d.get("after_node")) if d.get("after_node") else None
        print(f"  diagram {d['id']} {d['kind']} label={d['label']!r} status={d['status']}"
              f" selected={d['selected']} fen={d['fen']} after={books.node_label(an) if an else None}"
              f" lines={d['lines']}")
    if text:
        import pymupdf
        doc = pymupdf.open(books.pdf_path(BOOK))
        print("--- text layer ---")
        print(doc[page - 1].get_text("text"))
    return pg, rows


def picture(book, page, rows, plain=False, clip=None, zoom=2.0, tag=""):
    import pymupdf
    src = pymupdf.open(books.pdf_path(BOOK))
    doc = pymupdf.open()
    doc.insert_pdf(src, from_page=page - 1, to_page=page - 1)
    p = doc[0]
    if not plain:
        for r in rows:
            c = COLOURS.get(r["status"], (0.4, 0.4, 0.4))
            rect = pymupdf.Rect(*r["bbox"])
            sh = p.new_shape()
            sh.draw_rect(rect)
            sh.finish(color=c, width=0.9, dashes=None if r.get("main", True) else "[2] 0")
            sh.commit()
            p.insert_text((rect.x0, rect.y1 + 5.2), str(r["n"]), fontsize=5, color=c)
            raw = (r["raw"] or "").strip("!?+#")
            if r.get("san") and (r["status"] != "ok" or r["san"].strip("+#") not in raw):
                p.insert_text((rect.x0, rect.y0 - 1), r["san"], fontsize=5.5, color=c)
    kw = {"matrix": pymupdf.Matrix(zoom, zoom)}
    if clip:
        kw["clip"] = pymupdf.Rect(*clip)
    out = books.png_dir() / f"{BOOK}_p{page}{tag}{'_plain' if plain else ''}{'_clip' if clip else ''}.png"
    p.get_pixmap(**kw).save(out)
    return out


BOOK = None


def main():
    global BOOK
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("page", type=int)
    ap.add_argument("--text", action="store_true")
    ap.add_argument("--plain", action="store_true")
    ap.add_argument("--clip", default=None)
    ap.add_argument("--zoom", type=float, default=None)
    ap.add_argument("--code", default=None, help="the reading of another code digest")
    a = ap.parse_args()
    BOOK = a.book
    book = books.load(a.book, code=a.code)
    pg, rows = listing(book, a.page, a.text)
    clip = [float(x) for x in a.clip.split(",")] if a.clip else None
    out = picture(book, a.page, rows, a.plain, clip, a.zoom or (3.0 if clip else 2.0))
    print("picture:", out)


if __name__ == "__main__":
    main()
