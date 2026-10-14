"""Read the audit's books with the current code and keep the readings.

Usage:
    python3 tools/audit/build.py [BOOK ...] [--force] [--jobs 2]

Without names it reads all the books (tools/audit/books.py BOOKS), the
smallest first. Each reading goes to output/audit/<code>/<book>.json, with
the builder's state (<book>.pkl) and a summary (<book>.summary.json: time,
statistics, or the error and its traceback when the reading failed).
"""
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books  # noqa: E402

ORDER = ["ivanchuk", "gpa", "tangborn", "brunthaler", "planning", "alekhine", "kia", "primer"]


def one(name, force):
    cmd = [sys.executable, __file__, "--one", name] + (["--force"] if force else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        return {"book": name, "error": (r.stderr or r.stdout)[-2000:]}
    return json.loads(r.stdout.strip().splitlines()[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("books", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--one", default=None, help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.one:
        print(json.dumps(books.build(a.one, force=a.force)))
        return
    names = a.books or [n for n in ORDER if n in books.BOOKS]
    print("code", books.code_digest(), "cache", books.cache_dir(), flush=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        for s in ex.map(lambda n: one(n, a.force), names):
            if "error" in s:
                print(f"{s['book']}: FAILED {s['error'][-600:]}", flush=True)
            else:
                st = s["stats"]
                print(f"{s['book']}: {s['page_count']} pages, {s['seconds']} s, {st['lines']} lines "
                      f"({st['games']} games), moves {st['moves']}, unattached {st['unattached']}",
                      flush=True)


if __name__ == "__main__":
    main()
