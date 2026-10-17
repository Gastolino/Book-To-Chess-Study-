"""The audit's success rate: how much of each book the program reads as printed.

Usage:
    python3 tools/audit/score.py [CODE ...] [--books a,b] [--json OUT]

For each printed move token of a book (every box the program draws, less
the boxes placed in no line that hold no square and no castling: words
such as "ANSWER:" that are not moves), the token counts as READ when

  - the program shows it green (ok), in a line, and
  - its move agrees with the print: the same last square, and the same
    piece where the print names a piece by a letter, and
  - every move before it in its line agrees with the print in the same way
    (a move that only looks right in a line gone wrong does not count).

OCR's slips of shape that change no move ("cs" for c5, "Khl" for Kh1,
"£4" for f4, "o-o" for castling, a space inside a square: "Ng4-e 3+", and
ClearScan's signs for f3 and f1 after a figurine: "tLlo", "tLlfJ", "tLln")
read as the square they show. The
success rate of a book is READ / TOKENS. It also prints the moves shown
green against the print (WRONG), the measure of the silent errors. The
check compares squares and piece letters with the text layer, so in a
scanned book an OCR slip outside those listed can count a right move as
wrong; the rate is checked against page pictures each round
(tools/audit/page.py).
With several codes, the books are compared column by column.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books  # noqa: E402

SQ = re.compile(r"[a-h][1-8]")
CASTLE = re.compile(r"[0Oo]-?[0Oo]")
# OCR's slips of shape, which change no move: the letter or sign OCR prints
# for a file or a rank character. A move whose printed square reads so is
# the same move; any other difference of square or piece is a misreading.
FILE_SLIP = {"£": "f"}
RANK_SLIP = {"l": "1", "I": "1", "i": "1", "!": "1", "|": "1", "t": "1",
             "s": "58", "S": "58", "B": "8", "Z": "2", "z": "2", "O": "0"}


def _norm(s):
    return (s or "").replace("–", "-")


def _joined(raw):
    """raw without the spaces OCR set inside a move ("Ng4-e 3+", "Kf2-e l")."""
    return (raw or "").replace(" ", "")


def squares(raw):
    """Every square the printed token raw may show, OCR's slips of shape read."""
    out = []
    for i in range(len(raw) - 1):
        f = FILE_SLIP.get(raw[i], raw[i])
        if f not in "abcdefgh":
            continue
        r = raw[i + 1]
        ranks = r if r in "12345678" else RANK_SLIP.get(r, "")
        found = {f + x for x in ranks if x in "12345678"}
        if found:
            out.append((i, found))
    return out


# ClearScan's signs for a whole square, after a figurine's junk: "tLlo",
# "'bO", "tLlfJ" for f3 and "tLln" for f1. They count only after a short
# prefix (the figurine) and where the token shows no other square.
WHOLE_SQUARE = (("fJ", "f3"), ("o", "f3"), ("O", "f3"), ("n", "f1"))


def whole_square(raw):
    core = raw.rstrip("!?+#t ")
    for sign, sq in WHOLE_SQUARE:
        if core.endswith(sign) and 1 <= len(core) - len(sign) <= 4:
            return sq
    return None


def agrees(raw, san):
    """The move san agrees with the printed token raw."""
    raw, san = _joined(_norm(raw)), _norm(san)
    if not san:
        return False
    if san.startswith("O-O"):
        m = CASTLE.search(raw)
        long_ = bool(re.search(r"[0Oo]-?[0Oo]-?[0Oo]", raw))
        return bool(m) and long_ == san.startswith("O-O-O")
    ss = SQ.findall(san.split("=")[0])
    sq = squares(raw)
    if not sq and whole_square(raw):
        sq = [(len(raw), {whole_square(raw)})]
    if not ss or not sq or ss[-1] not in sq[-1][1]:
        return False
    if raw[:1] in "KQRBN" and san[:1] in "KQRBN" and raw[:1] != san[:1]:
        return False
    # a capture mark printed before the square ("Rxe7+", "tDxf6") makes a capture
    pos = sq[-1][0]
    if "x" in raw[max(0, pos - 2):pos] and "x" not in san:
        return False
    if raw[:1] in "KQRBN" and san[:1].islower():
        return False
    return True


def score(book):
    nodes = book["nodes"]
    good = {}

    def path_ok(nid):
        if nid in good:
            return good[nid]
        chain, cur = [], nid
        while cur is not None and cur not in good:
            chain.append(cur)
            cur = nodes[cur].get("parent")
        ok = good.get(cur, True)
        for x in reversed(chain):
            n = nodes[x]
            if n.get("san") and n.get("raw"):
                ok = ok and agrees(n["raw"], n["san"])
            good[x] = ok
        return good[nid]

    tokens = read = wrong = 0
    for pg in book["pages"]:
        for m in pg["marks"]:
            raw = m.get("raw") or ""
            if m["status"] == "unattached" and not (squares(_joined(raw)) or CASTLE.search(raw)
                                                    or whole_square(raw)):
                continue
            tokens += 1
            n = nodes.get(m.get("node")) if m.get("node") else None
            if m["status"] != "ok" or not n:
                continue
            if agrees(raw, n.get("san")):
                if path_ok(m["node"]):
                    read += 1
            else:
                wrong += 1
    return {"tokens": tokens, "read": read, "wrong": wrong,
            "rate": round(100.0 * read / tokens, 1) if tokens else 100.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*")
    ap.add_argument("--books", default=None)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()
    codes = a.codes or [books.code_digest()]
    names = a.books.split(",") if a.books else list(books.BOOKS)
    out = {}
    print(f"{'book':<11}" + "".join(f"{c:>26}" for c in codes))
    tot = {c: [0, 0, 0] for c in codes}
    for name in names:
        row = f"{name:<11}"
        for c in codes:
            if not (books.cache_dir(c) / f"{name}.json").exists():
                row += f"{'-':>26}"
                continue
            s = score(books.load(name, code=c))
            out.setdefault(c, {})[name] = s
            tot[c][0] += s["tokens"]; tot[c][1] += s["read"]; tot[c][2] += s["wrong"]
            row += f"{s['rate']:>9}% ({s['read']}/{s['tokens']}, {s['wrong']} wrong)".rjust(26)
        print(row)
    row = f"{'ALL':<11}"
    for c in codes:
        t, r, w = tot[c]
        row += (f"{round(100.0 * r / t, 1) if t else 0:>9}% ({r}/{t}, {w} wrong)").rjust(26)
        out.setdefault(c, {})["ALL"] = {"tokens": t, "read": r, "wrong": w,
                                        "rate": round(100.0 * r / t, 1) if t else 0}
    print(row)
    if a.json:
        a.json.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
