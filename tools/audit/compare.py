"""Compare two readings of the books: before and after a change of the code.

Usage:
    python3 tools/audit/compare.py BASE_CODE [NEW_CODE] [--books a,b] [--examples 12]

BASE_CODE and NEW_CODE are code digests (the folders of output/audit/);
NEW_CODE defaults to the digest of the code checked out here, whose
readings tools/audit/build.py makes. For every book read by both, the
comparison counts each printed move token whose status or move changed
(failed -> ok is a gain, ok -> failed a loss, a move changed while it
stays ok is to be looked at on the page), and the changes in the scan's
counts (silent misreadings, diagrams that disagree, breaks, unplaced
sequences). It prints the counts and examples of each kind of change, and
exits with status 1 when a book lost more certain moves than it gained or
when a reading failed.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books  # noqa: E402
import scan as sc  # noqa: E402

RANK = {"ok": 4, "guessed": 3, "ambiguous": 2, "waiting": 1, "failed": 1, "unattached": 0}


def marks(book):
    out = {}
    for pg in book["pages"]:
        for m in pg["marks"]:
            n = book["nodes"].get(m.get("node")) if m.get("node") else None
            out[m["key"]] = (m["status"], n["san"] if n else None, books.node_label(n) if n else None,
                             m.get("line"))
    return out


def compare_book(name, base, new, examples):
    d0, d1 = books.cache_dir(base), books.cache_dir(new)
    s0, s1 = d0 / f"{name}.summary.json", d1 / f"{name}.summary.json"
    if not s0.exists() or not s1.exists():
        return None
    j0, j1 = json.loads(s0.read_text()), json.loads(s1.read_text())
    if "error" in j1:
        print(f"{name}: THE NEW READING FAILED: {j1['error']}")
        return {"book": name, "failed": True}
    if "error" in j0:
        print(f"{name}: the base reading failed; the new one reads.")
        return {"book": name, "fixed": True}
    b0, b1 = books.load(name, code=base), books.load(name, code=new)
    m0, m1 = marks(b0), marks(b1)
    kinds = Counter()
    ex = {}
    for k in set(m0) | set(m1):
        a, b = m0.get(k), m1.get(k)
        if a == b:
            continue
        if a is None or b is None:
            kind = "token only in base" if b is None else "token only in new"
        elif a[0] != b[0]:
            kind = ("gain " if RANK.get(b[0], 0) > RANK.get(a[0], 0) else "loss ") + f"{a[0]}->{b[0]}"
        elif a[1] != b[1]:
            kind = f"move changed, still {a[0]}"
        else:
            kind = "same move, other line"
        kinds[kind] += 1
        ex.setdefault(kind, []).append((k, a, b))
    sc0, sc1 = sc.scan(b0), sc.scan(b1)
    print(f"\n{name}: seconds {j0.get('seconds')} -> {j1.get('seconds')}")
    print(f"  moves {j0['stats']['moves']}\n     -> {j1['stats']['moves']}")
    print(f"  lines {j0['stats']['line_status']} -> {j1['stats']['line_status']};"
          f" unplaced {j0['stats']['unattached']} -> {j1['stats']['unattached']}")
    for kind in ("breaks", "silent", "diagrams", "jumps", "unplaced"):
        print(f"  scan {kind}: {len(sc0[kind])} -> {len(sc1[kind])}")
    gains = sum(c for k, c in kinds.items() if k.startswith("gain"))
    losses = sum(c for k, c in kinds.items() if k.startswith("loss"))
    for kind, c in kinds.most_common():
        print(f"  {kind}: {c}")
        for k, a, b in ex[kind][:examples]:
            print(f"      {k}: {a} -> {b}")
    return {"book": name, "gains": gains, "losses": losses, "kinds": dict(kinds),
            "silent": [len(sc0["silent"]), len(sc1["silent"])],
            "diagrams": [len(sc0["diagrams"]), len(sc1["diagrams"])]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("new", nargs="?")
    ap.add_argument("--books", default=None)
    ap.add_argument("--examples", type=int, default=12)
    a = ap.parse_args()
    new = a.new or books.code_digest()
    names = a.books.split(",") if a.books else list(books.BOOKS)
    res = [r for r in (compare_book(n, a.base, new, a.examples) for n in names) if r]
    if not res:
        raise SystemExit("No book is read by both versions; run tools/audit/build.py first.")
    bad = [r["book"] for r in res if r.get("failed") or r.get("losses", 0) > r.get("gains", 0)]
    print("\nsummary:", json.dumps(res))
    if bad:
        print("WORSE:", ", ".join(bad))
        sys.exit(1)


if __name__ == "__main__":
    main()
