"""Show a line as the program assembled it: its moves, variations and pages.

Usage:
    python3 tools/audit/line.py BOOK WHAT [--depth N] [--from-move N]
    python3 tools/audit/line.py BOOK --list [--chapter N]

WHAT is a line id (L12), a node id (L12.40) or a token key (14:52,96:Nf3):
the line that holds it. Each move shows as

    12.Nf3 p14                      a move read as printed, on page 14
    12.Nf3 p14 [failed raw='tLlf3'] a doubtful one, with the printed text
    12.Nf3 p14 {corrected=assumed auto}   a move the program supplied

and each variation is indented under the move it replaces. --depth limits
the variations shown (0: the main line alone). --list lists the lines of
the book (or of one chapter) with their kind, pages, status and title.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books  # noqa: E402


def find_line(book, what):
    if what in {L["id"] for L in book["lines"]}:
        return what
    if what in book["nodes"]:
        return book["nodes"][what]["line"]
    for n in book["nodes"].values():
        if n.get("key") == what:
            return n["line"]
    for pg in book["pages"]:
        for m in pg["marks"]:
            if m["key"] == what:
                if m.get("line"):
                    return m["line"]
                raise SystemExit(f"{what} is placed in no line (status {m['status']}).")
    raise SystemExit(f"Cannot find {what}.")


def fmt(n):
    s = f"{books.node_label(n)} p{n['page']}"
    raw = (n.get("raw") or "")
    extra = []
    if n["status"] not in ("ok", "root"):
        extra.append(n["status"])
    if raw and (n["status"] != "ok" or (n["san"] or "").rstrip("+#") not in raw):
        extra.append(f"raw={raw!r}")
    if extra:
        s += f" [{' '.join(extra)}]"
    tags = [f"corrected={n['corrected']}" if n.get("corrected") else "",
            "auto" if n.get("auto") else "", f"assumed={n['assumed']}" if n.get("assumed") else ""]
    tags = [t for t in tags if t]
    if tags:
        s += " {" + " ".join(tags) + "}"
    return s


def show(book, lid, depth=99, from_move=0):
    nodes = book["nodes"]
    L = next(L for L in book["lines"] if L["id"] == lid)
    print(f"{lid} {L['kind']} {L['title']!r} chapter {L['chapter']} pages {L['page']}-{L['end_page']}"
          f" status {L['status']} result {L['result']} diagram {L['diagram']}")
    print(f"  start {L['start_fen']}  ({L['start_note']})")
    if L.get("header"):
        print(f"  header {L['header']}")

    def walk(nid, indent, d):
        cur = nid
        while cur:
            n = nodes[cur]
            kids = [c for c in n["children"] if c in nodes]
            is_root = n.get("parent") is None and not n.get("san")
            if not is_root and (indent or (n.get("number") or 0) >= from_move):
                print("  " * indent + "  " + fmt(n) + f"   {cur} key={n.get('key')}")
            if not kids:
                return
            main = kids[0]
            if d < depth:
                for v in kids[1:]:
                    print("  " * (indent + 1) + "  (")
                    walk(v, indent + 2, d + 1)
                    print("  " * (indent + 1) + "  )")
            cur = main
    walk(L["root"], 0, 0)


def list_lines(book, chapter=None):
    for L in book["lines"]:
        if chapter is not None and L["chapter"] != chapter:
            continue
        print(f"{L['id']:<6} ch{L['chapter']:<3} {L['kind']:<9} p{L['page']}-{L['end_page']:<5}"
              f" {L['status']:<9} {L['moves']:>4} moves {L['variations']:>3} var  {L['title'][:50]!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("what", nargs="?")
    ap.add_argument("--depth", type=int, default=99)
    ap.add_argument("--from-move", type=int, default=0)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--chapter", type=int, default=None)
    ap.add_argument("--code", default=None)
    a = ap.parse_args()
    book = books.load(a.book, code=a.code)
    if a.list or not a.what:
        list_lines(book, a.chapter)
        return
    show(book, find_line(book, a.what), a.depth, a.from_move)


if __name__ == "__main__":
    main()
