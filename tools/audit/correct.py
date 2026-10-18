"""Make corrections as the reader makes them in the app, and show what the
program does with them.

Usage:
    python3 tools/audit/correct.py BOOK [corrections ...] [--read-on KEY] [--suggest KEY]

Each run starts from the book's reading with no corrections (or the set in
--start FILE), applies the corrections given, and replays them through
chessbook/live.py, the code the app's worker runs:

    --board KEY=SAN        the reader makes the move SAN on the board for the
                           printed move KEY (a move correction), and the
                           program reads on from it, as the app does after
                           every correction (live.read_on, the open chapter,
                           at least 5 pages)
    --move KEY=SAN         a move correction alone (live.apply)
    --connect "KEY->AFTER[|SAN,SAN]"   join the run at KEY after the move AFTER
                           (a key or a node id), with the moves the text lacks
                           between them
    --gap KEY=SAN[,SAN]    moves missing after the move KEY
    --disconnect KEY[=here|remove|DIAGRAM]
    --attach KEY=TO|dismiss   tie an unattached sequence to a main-line move
    --diagram ID=FEN       the position a diagram shows
    --glyph JUNK=P         a garbled piece symbol and its piece (K Q R B N P)
    --read-on KEY          read on from KEY after the corrections
    --skip KEY             a correction of the program's that the reader removed
    --suggest KEY          what the program offers to follow KEY (live.suggest),
                           once the corrections given are applied

Keys hold colons, commas and sometimes "=" (a printed promotion), so every
option also takes "KEY->VALUE": "--board '7:30,88:e8=Q->e8=Q'".

The report gives the time, the lines that changed with their statuses
before and after, what read_on joined and filled and where it stopped, the
moves of the line from the corrected move on, and the move the app would
ask the reader about next (the first doubtful or unread move after it).
--json writes the whole result as well.
"""
import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books  # noqa: E402

from chessbook import corrections as fixes, live  # noqa: E402


def chapter_of_key(book, key):
    page = int(str(key).split(":")[0]) if ":" in str(key) else book["nodes"][key]["page"]
    pg = next(p for p in book["pages"] if p["page"] == page)
    return pg["chapter"]


def line_counts(book):
    by = {}
    for n in book["nodes"].values():
        by.setdefault(n["line"], Counter())[n["status"]] += 1
    return by


def branch(b, nid, limit=40):
    out, cur = [], nid
    for _ in range(limit):
        out.append(cur)
        nxt = b.branch_of(cur)
        if not nxt:
            break
        cur = nxt[0]
    return out


def fmt(b, nid):
    n = b.nodes[nid]
    s = f"{books.node_label(n)}[p{n['page']}"
    if n["status"] not in ("ok", "root"):
        s += f" {n['status']}"
    if n.get("raw") and n["status"] != "ok":
        s += f" raw={n['raw']!r}"
    if n.get("corrected"):
        s += f" corr={n['corrected']}"
    if n.get("auto"):
        s += " auto"
    return s + "]"


def pair(item):
    """KEY and VALUE of "KEY->VALUE", or of "KEY=VALUE" (split at the last "=")."""
    if "->" in item:
        k, v = item.split("->", 1)
    else:
        k, v = item.rsplit("=", 1)
    return k.strip(), v.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    for f in ("board", "move", "connect", "gap", "disconnect", "attach", "diagram", "glyph", "skip"):
        ap.add_argument(f"--{f}", action="append", default=[])
    ap.add_argument("--read-on", default=None)
    ap.add_argument("--suggest", default=None)
    ap.add_argument("--start", type=Path, default=None, help="a corrections file to start from")
    ap.add_argument("--pages", type=int, default=None)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--code", default=None)
    a = ap.parse_args()

    t0 = time.perf_counter()
    book, state = books.load(a.book, state=True, code=a.code)
    b = state["builder"]
    print(f"loaded in {time.perf_counter() - t0:.1f} s")
    fix = fixes.normalise(json.loads(a.start.read_text()) if a.start else {})
    read_from = a.read_on
    for item in a.board:
        k, san = pair(item)
        fix["moves"][k] = {"san": san}
        read_from = k
    for item in a.move:
        k, san = pair(item)
        fix["moves"][k] = {"san": san}
    for item in a.connect:
        if "->" not in item:
            raise SystemExit('--connect takes "KEY->AFTER" or "KEY->AFTER|SAN,SAN" (keys hold colons).')
        k, rest = pair(item)
        after, _, before = rest.partition("|")
        e = {"after": after.strip()}
        if before:
            e["before"] = [s for s in before.split(",") if s]
        fix["connect"][k] = e
    for item in a.gap:
        k, sans = pair(item)
        fix["gaps"][k] = {"san": [s for s in sans.split(",") if s]}
    for item in a.disconnect:
        if "->" in item:
            k, how = pair(item)
        else:
            m = re.match(r"(.*)=(here|remove|p\d+-\d+)$", item)
            k, how = (m.group(1), m.group(2)) if m else (item, "here")
        fix["disconnect"][k] = {"remove": True} if how == "remove" else {"start": how}
    for item in a.attach:
        k, to = pair(item)
        fix["unattached"][k] = {"attach_to": to}
    for item in a.diagram:
        k, fen = item.split("->", 1) if "->" in item else item.split("=", 1)
        fix["diagrams"][k.strip()] = {"fen": fen.strip()}
    for item in a.glyph:
        k, p = pair(item)
        fix["glyphs"][k] = p
    fix = fixes.normalise(fix)

    before = line_counts(book)
    result = {}
    t = time.perf_counter()
    try:
        if a.suggest:
            if any(fix[k] for k in fix if isinstance(fix[k], dict)):
                live.apply(state, book, fix)
            res = live.suggest(state, a.suggest)
            print(json.dumps(res, indent=1, default=str)[:6000])
            result["suggest"] = res
            if a.json:
                a.json.write_text(json.dumps(result, indent=1, default=str))
            return
        if read_from:
            ch = chapter_of_key(book, read_from)
            res = live.read_on(state, book, fix, read_from, chapters={ch}, pages=a.pages,
                               skip=a.skip)
        else:
            res = live.apply(state, book, fix)
    except Exception as e:
        import traceback
        print("ERROR", repr(e))
        traceback.print_exc()
        sys.exit(2)
    dt = time.perf_counter() - t
    result["result"] = res
    print(f"replayed in {dt:.2f} s; lines changed {res.get('lines')} removed {res.get('removed')}"
          f" pending {res.get('pending')}")
    after = line_counts(book)
    for lid in sorted(set(res.get("lines", [])) | set(res.get("removed", []))):
        print(f"  {lid}: {dict(before.get(lid, {}))} -> {dict(after.get(lid, {}))}")
    if read_from:
        for j in res.get("joined", []):
            print(f"  JOINED {j}")
        for f in res.get("filled", []):
            print(f"  FILLED {f}")
        print(f"  moves read on: {res.get('moves')}  until page {res.get('until')}  end {res.get('end')}")
        print(f"  stop: {json.dumps(res.get('stop'), default=str)[:700]}")
        nid = b.node_of(read_from)
        if nid is None:
            print("  the corrected move is in no line now")
        else:
            br = branch(b, nid)
            print("  line from the move:", " ".join(fmt(b, x) for x in br))
            nxt = next((x for x in br[1:] if b.nodes[x]["status"] not in ("ok", "root")), None)
            stop = res.get("stop") or {}
            if nxt:
                print(f"  NEXT QUESTION: the doubtful move {fmt(b, nxt)} key={b.nodes[nxt].get('key')}")
            elif stop and not stop.get("done"):
                print(f"  NEXT QUESTION: what follows, at {stop.get('raw')!r} page {stop.get('page')}"
                      f" ({stop.get('reason')})")
            else:
                print("  NEXT QUESTION: none (the line reads to its end)")
    print("corrections now:", json.dumps(res.get("corrections") or book.get("corrections"))[:1500])
    if a.json:
        a.json.write_text(json.dumps(result, indent=1, default=str))


if __name__ == "__main__":
    main()
