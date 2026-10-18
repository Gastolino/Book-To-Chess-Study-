"""Scan a book's reading for the places where it is likely wrong.

Usage:
    python3 tools/audit/scan.py BOOK [--top 15] [--chapter N]

The scan finds candidates, not failures: each one is to be looked at on
the page (page.py) before it counts. It writes every candidate to
output/audit/<code>/<book>.scan.json and prints the counts with the first
examples of each kind:

    breaks       the first doubtful move of each line that does not read to
                 its end: where the reading of a game or a note broke
    silent       moves read as certain (ok or guessed) whose printed square
                 differs from the move made of them, or whose printed piece
                 letter does: a misreading the reader is not warned of
    diagrams     diagrams whose position differs from the one their line has
                 at the move they stand after
    jumps        moves more than one page from the move before them, in the
                 same line: a join across pages, right or wrong
    unplaced     printed sequences placed in no line, longest first
    hot pages    the pages with the most doubtful and unplaced moves
    short games  lines taken for games that hold few moves
    chapters     the statuses of the moves chapter by chapter
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books  # noqa: E402
import diagram as dg  # noqa: E402

SQ = re.compile(r"[a-h][1-8]")


def san_dest(san):
    if not san or san.startswith("O-O"):
        return None
    s = san.split("=")[0]
    m = SQ.findall(s)
    return m[-1] if m else None


def raw_dest(raw):
    if not raw or re.search(r"[0O]-?[0O]", raw):
        return None
    m = SQ.findall(raw.replace("–", "-"))
    return m[-1] if m else None


def scan(book, chapter=None):
    nodes = book["nodes"]
    english = (book.get("letters") or "English") == "English"
    out = defaultdict(list)
    in_ch = (lambda n: True) if chapter is None else (lambda n: n.get("page") and any(
        pg["page"] == n["page"] and pg["chapter"] == chapter for pg in book["pages"]))
    page_ch = {pg["page"]: pg["chapter"] for pg in book["pages"]}

    # breaks: first non-ok main-line move of each line not wholly ok
    for L in book["lines"]:
        if chapter is not None and L["chapter"] != chapter:
            continue
        if L["status"] == "ok":
            continue
        cur, prev = L["root"], None
        while cur:
            n = nodes[cur]
            if n.get("san") is not None or n.get("parent"):
                if n["status"] not in ("ok", "root"):
                    out["breaks"].append({"line": L["id"], "kind": L["kind"], "title": L["title"][:40],
                                          "page": n["page"], "status": n["status"], "raw": n.get("raw"),
                                          "move": books.node_label(n), "key": n.get("key"),
                                          "after": books.node_label(nodes[prev]) if prev else None})
                    break
            kids = [c for c in n["children"] if c in nodes]
            prev, cur = cur, (kids[0] if kids else None)

    for nid, n in nodes.items():
        if not n.get("san") or not in_ch(n):
            continue
        if n["status"] in ("ok", "guessed") and n.get("raw"):
            rd, sd = raw_dest(n["raw"]), san_dest(n["san"])
            piece_raw = n["raw"][0] if english and n["raw"][:1] in "KQRBN" else None
            piece_san = n["san"][0] if n["san"][:1] in "KQRBN" else ("P" if n["san"][:1].islower() else None)
            why = []
            if rd and sd and rd != sd:
                why.append(f"square {rd} printed, {sd} made")
            if piece_raw and piece_san and piece_raw != piece_san and not n["san"].startswith("O-O"):
                why.append(f"piece {piece_raw} printed, {piece_san} made")
            if why:
                out["silent"].append({"page": n["page"], "raw": n["raw"], "move": books.node_label(n),
                                      "status": n["status"], "line": n["line"], "key": n.get("key"),
                                      "corrected": n.get("corrected"), "why": "; ".join(why)})
        par = nodes.get(n.get("parent")) if n.get("parent") else None
        if par and par.get("page") and n.get("page") and abs(n["page"] - par["page"]) > 1:
            out["jumps"].append({"line": n["line"], "from_page": par["page"], "page": n["page"],
                                 "move": books.node_label(n), "after": books.node_label(par),
                                 "key": n.get("key"), "main": n["main"]})

    for pg in book["pages"]:
        if chapter is not None and pg["chapter"] != chapter:
            continue
        for d in pg["diagrams"]:
            an = nodes.get(d.get("after_node")) if d.get("after_node") else None
            if an and d.get("fen") and an.get("fen"):
                diff = dg.differences(d["fen"], an["fen"])
                if diff:
                    out["diagrams"].append({"id": d["id"], "status": d["status"], "after": books.node_label(an),
                                            "line": an["line"], "squares": len(diff), "diff": diff[:6],
                                            "doubtful": (d.get("reading") or {}).get("doubtful")})

    for u in book.get("unattached", []):
        if chapter is not None and page_ch.get(u["page"]) != chapter:
            continue
        nmoves = len(re.findall(r"[a-h][1-8]", u.get("text", "")))
        out["unplaced"].append({"page": u["page"], "squares": nmoves, "text": u.get("text", "")[:160],
                                "reason": u.get("reason"), "key": u.get("key")})
    out["unplaced"].sort(key=lambda u: -u["squares"])

    hot = Counter()
    for pg in book["pages"]:
        if chapter is not None and pg["chapter"] != chapter:
            continue
        for m in pg["marks"]:
            if m["status"] != "ok":
                hot[pg["page"]] += 1
    marks_on = {pg["page"]: len(pg["marks"]) for pg in book["pages"]}
    out["hot_pages"] = [{"page": p, "doubtful_or_unplaced": c, "marks": marks_on[p]}
                        for p, c in hot.most_common(40)]

    for L in book["lines"]:
        if chapter is not None and L["chapter"] != chapter:
            continue
        if L["kind"] == "game" and L["moves"] < 12:
            out["short_games"].append({"line": L["id"], "title": L["title"][:50], "page": L["page"],
                                       "moves": L["moves"], "status": L["status"]})

    chs = defaultdict(Counter)
    for pg in book["pages"]:
        for m in pg["marks"]:
            chs[pg["chapter"]][m["status"]] += 1
    out["chapters"] = [{"chapter": c["index"], "title": c["title"][:40], "pages": f"{c['start']}-{c['end']}",
                        **dict(chs[c["index"]])} for c in book["chapters"]
                       if chapter is None or c["index"] == chapter]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--chapter", type=int, default=None)
    ap.add_argument("--code", default=None)
    a = ap.parse_args()
    book = books.load(a.book, code=a.code)
    out = scan(book, a.chapter)
    path = books.cache_dir(a.code) / f"{a.book}.scan.json"
    if a.chapter is None:
        path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    st = book["stats"]
    print(f"{a.book}: {book['page_count']} pages, {st['lines']} lines ({st['games']} games,"
          f" {st['fragments']} fragments), line statuses {st['line_status']}")
    print(f"  moves {st['moves']}; variations {st['variations']}; unplaced sequences {st['unattached']}")
    for kind in ("breaks", "silent", "diagrams", "jumps", "unplaced", "hot_pages", "short_games", "chapters"):
        items = out.get(kind, [])
        print(f"\n== {kind}: {len(items)}")
        for it in items[:a.top]:
            print("  ", json.dumps(it, ensure_ascii=False)[:300])
    print(f"\nall candidates: {path}")


if __name__ == "__main__":
    main()
