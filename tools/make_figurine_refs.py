"""Collect reference figurines for reading piece figurines by their shape
(chessbook/figshapes.py), and save them as chessbook/assets/figurines.npz.

Usage:
    python3 tools/make_figurine_refs.py [BOOK.pdf ...] [--montage DIR]
                                        [--sample N --sample-out FILE]

Each book is read as the reader reads it (assemble.build_steps), without the
references this tool makes. The groups of figurines that the book's own
moves named surely (at least MIN_VOTES votes of their own and confidence
SURE) give their shapes (the mean of the group's cuts) as references of the
piece they were named, at most PER_PIECE groups per piece and book, the
largest first. A book whose moves cannot name its figurines (a book of
exercises whose solutions the program cannot link to their diagrams) thus
gets its names from the books that can.

--montage writes, for each book, one picture of its groups of cuts with the
piece each was named (groups_<book>.png), for checking by eye. --sample
draws N cuts of each book at random and writes them (book, page, key, piece
read, "?" for a cut the book could not name) to FILE, with a picture of the
numbered cuts (sample_<book>.png): the start of a truth set
(tests/data/figurine_truth.json) once each row is checked against the
picture and corrected.
"""
import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook import assemble, figshapes  # noqa: E402

OUT = ROOT / "chessbook" / "assets" / "figurines.npz"
BOOKS = ["primer", "kia", "planning"]
MIN_VOTES = 3
SURE = 0.95
PER_PIECE = 4


def find_book(name):
    p = Path(name)
    if p.suffix == ".pdf" and p.exists():
        return p
    for f in (ROOT, ROOT / "corpus", ROOT / "corpus" / "archive3"):
        if (f / f"{name}.pdf").exists():
            return f / f"{name}.pdf"
    return None


def read_book(pdf, tmp, refs=False):
    """The figshapes.Shapes of a book, read without references (or with the
    shipped ones)."""
    figshapes._REFS = None if refs else (np.zeros((0, figshapes.S ** 2), np.float32), [])
    ctx = {}
    assemble._drain(assemble.build_steps(pdf, output_dir=tmp, books_dir=tmp / "books", ctx=ctx,
                                         progress=lambda m: print("  ", m, flush=True)))
    return ctx.get("shapes")


def tile(v):
    return np.pad(255 - (v.reshape(figshapes.S, figshapes.S) * 255).astype(np.uint8), 1,
                  constant_values=160)


def montage(rows, path, width=30):
    """rows: [(label, [vectors])]; one row of tiles per label (wrapped)."""
    lines = []
    for label, vs in rows:
        for k in range(0, max(len(vs), 1), width):
            part = [tile(v) for v in vs[k:k + width]]
            part += [np.full((figshapes.S + 2, figshapes.S + 2), 255, np.uint8)] * (width - len(part))
            head = np.full((figshapes.S + 2, 70), 255, np.uint8)
            cv2.putText(head, label if k == 0 else "", (2, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, 0, 1)
            lines.append(np.hstack([head] + part))
    if lines:
        img = np.vstack(lines)
        cv2.imwrite(str(path), cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("books", nargs="*", default=BOOKS)
    ap.add_argument("--montage", type=Path, default=None)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--sample-out", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--tmp", type=Path, default=Path("/tmp/figurine_refs"))
    ap.add_argument("--with-refs", action="store_true",
                    help="read the books with the shipped references (to sample and check them)")
    args = ap.parse_args(argv)
    shapes, pieces, sources = [], [], []
    samples = {}
    rng = random.Random(1)
    for name in args.books:
        pdf = find_book(name)
        if pdf is None:
            print(f"{name}: not found")
            continue
        print(f"{name}: reading {pdf}", flush=True)
        sh = read_book(pdf, args.tmp / pdf.stem, args.with_refs)
        if sh is None:
            print(f"{name}: no figurines to read")
            continue
        for p in figshapes.PIECES:
            good = [x for x in sh.groups if x["piece"] == p and x["confidence"] >= SURE
                    and sum(x["votes"].values()) >= MIN_VOTES and x["votes"].get(p, 0) >= MIN_VOTES]
            good.sort(key=lambda x: -len(x["members"]))
            for x in good[:PER_PIECE]:
                shapes.append(sh.centres[x["index"]])
                pieces.append(p)
                sources.append(f"{pdf.stem}:{len(x['members'])}")
            print(f"   {p}: {len(good[:PER_PIECE])} references from {len(good)} sure groups")
        if args.montage:
            args.montage.mkdir(parents=True, exist_ok=True)
            rows = []
            for x in sorted(sh.groups, key=lambda x: (str(x["piece"]), -len(x["members"]))):
                vs = [sh.X[sh.keys.index(k)] for k in x["members"][:60]]
                rows.append((f"{x['piece'] or '?'}{len(x['members'])}", vs))
            montage(rows, args.montage / f"groups_{pdf.stem}.png")
        if args.sample and sh.keys:
            def read(k):
                piece, conf = sh.by_key.get(k, ("?", 0))
                return piece if conf >= figshapes.USE_MIN else "?"
            pick = sorted(rng.sample(sh.keys, min(args.sample, len(sh.keys))),
                          key=lambda k: (read(k), k))
            samples[pdf.stem] = [{"page": int(k.split(":")[0]), "key": k, "piece": read(k)}
                                 for k in pick]
            if args.montage:
                rows = [(f"{i}:{read(k)}", [sh.X[sh.keys.index(k)]])
                        for i, k in enumerate(pick)]
                # ten numbered cuts a row
                lines = []
                for i in range(0, len(rows), 10):
                    part = []
                    for lab, vs in rows[i:i + 10]:
                        head = np.full((figshapes.S + 2, 60), 255, np.uint8)
                        cv2.putText(head, lab, (2, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, 0, 1)
                        part.append(np.hstack([head, tile(vs[0])]))
                    part += [np.full_like(part[0], 255)] * (10 - len(part))
                    lines.append(np.hstack(part))
                img = np.vstack(lines)
                cv2.imwrite(str(args.montage / f"sample_{pdf.stem}.png"),
                            cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    if shapes and not args.with_refs:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(args.out, shapes=np.clip(np.array(shapes) * 255, 0, 255).astype(np.uint8),
                            pieces=np.array(pieces), sources=np.array(sources))
        print(f"saved {len(shapes)} references to {args.out} ({args.out.stat().st_size} bytes)")
    if args.sample and args.sample_out:
        args.sample_out.write_text(json.dumps(samples, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
