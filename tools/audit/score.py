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
read as the square they show, and so does "C4" for c4 (the gpa and KIA
text layers). In the scanned books (Planning, KIA, the Primer), a letter
that OCR confuses with another (b and h, c and e, "t" for f) reads as its
twin only where the print, read literally, is no legal move in the position
and the twin leaves the program's move as the one legal move it shows. The
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
FILE_SLIP = {"£": "f", "C": "c"}
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


# The scanned books, whose text layer is OCR's: only there may a letter be
# another letter's twin.
TWIN_BOOKS = {"planning", "kia", "primer"}

# OCR's slips that change a square's letter into another square's letter
# (b/h and c/e in ClearScan, "t" for f, "C" for c, "l" for 1, 2 or 7): such a
# print may show either square, so it counts as the program's move only where
# the print read literally is no legal move in the position and the slip
# leaves the program's move as the one legal move it can show.
FILE_TWIN = {"C": "c", "t": "f", "H": "f", "k": "c", "r": "f", "£": "f",
             "b": "bh", "h": "bh", "c": "ce", "e": "ce"}
RANK_TWIN = {"l": "127", "i": "17", "I": "17", "t": "17", "!": "1", "|": "1",
             "s": "58", "S": "58", "B": "8", "Z": "2", "z": "2"}


def twin_squares(raw):
    out = []
    for i in range(len(raw) - 1):
        files = FILE_TWIN.get(raw[i], raw[i] if raw[i] in "abcdefgh" else "")
        r = raw[i + 1]
        ranks = r if r in "12345678" else RANK_TWIN.get(r, "")
        found = {f + x for f in files for x in ranks}
        if found:
            out.append((i, found))
    return out


def twin_agrees(raw, san):
    raw = _joined(_norm(raw)).replace("'", "")
    ss = SQ.findall(_norm(san).split("=")[0])
    sq = twin_squares(raw)
    if not ss or not sq or ss[-1] not in sq[-1][1]:
        return False
    # a pawn's print ("h4", "cs", "exf6") stays a pawn's move
    if re.match(r"[a-h][1-8xsSlIiBZz]", raw) and not san[:1].islower():
        return False
    if re.match(r"[KQRBN][a-hx]", raw) and raw[:1] != (san[:1] if san[:1] in "KQRBN" else ""):
        return False
    pos = sq[-1][0]
    return not ("x" in raw[max(0, pos - 2):pos] and "x" not in san)


def agrees_here(raw, san, fen):
    """The move san agrees with raw, read literally or, where the literal
    reading is no legal move in the position fen, read with a twin slip that
    leaves san the one legal move it shows."""
    if agrees(raw, san):
        return True
    if not fen or not san or san.startswith("O-O"):
        return False
    import chess
    try:
        board = chess.Board(fen if len(fen.split()) > 4 else fen + " - 0 1")
        legal = [board.san(m) for m in board.legal_moves]
    except ValueError:
        return False
    if any(agrees(raw, m) for m in legal):
        return False
    return [m for m in legal if twin_agrees(raw, m)] == [san]


def score(book, twins=False):
    nodes = book["nodes"]
    good = {}

    def fen_before(nid):
        p = nodes[nid].get("parent")
        return nodes[p].get("fen") if p in nodes else None

    def fits(nid, raw):
        n = nodes[nid]
        if not twins:
            return agrees(raw, n.get("san"))
        return agrees_here(raw, n.get("san"), fen_before(nid))

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
                ok = ok and fits(x, n["raw"])
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
            if fits(m["node"], raw):
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
            s = score(books.load(name, code=c), twins=name in TWIN_BOOKS)
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
