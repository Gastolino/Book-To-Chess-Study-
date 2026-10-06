"""Fetch the chess engine the reader analyses with (chessbook/engine_files.py):
the lite single-threaded build of Stockfish.js 19 from the npm registry, with
its GPLv3 licence text, checked against the pinned checksums.

Usage:
    python3 tools/fetch_engine.py DIR

Writes DIR/stockfish-19-lite-single.js, DIR/stockfish-19-lite-single.wasm and
DIR/Copying.txt. The site workflow (.github/workflows/pages.yml) runs it
before tools/build_web.py --engine DIR; for the command line, make_reader.py
--engine DIR copies the same files next to the reader. The files stay out
of git (local/ is ignored): `python3 tools/fetch_engine.py local/engine`.
"""
import argparse
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook import engine_files as ef  # noqa: E402


def fetch(dest, url=ef.TARBALL):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as r:
        data = r.read()
    wanted = {"package/bin/" + ef.JS: ef.JS, "package/bin/" + ef.WASM: ef.WASM,
              "package/" + ef.LICENCE: ef.LICENCE}
    found = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            name = wanted.get(member.name)
            if not name or not member.isfile():
                continue
            with tar.extractfile(member) as f:
                (dest / name).write_bytes(f.read())
            found.add(name)
    missing = set(wanted.values()) - found
    if missing:
        raise SystemExit(f"The package lacks {', '.join(sorted(missing))}.")
    ef.check(dest)
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dest", type=Path, help="the folder to write the engine files into")
    args = ap.parse_args(argv)
    fetch(args.dest)
    for name in ef.FILES:
        print(f"{args.dest / name}: {(args.dest / name).stat().st_size:,} bytes")
    print(f"{ef.NAME} ({ef.BUILD}) checked against the pinned checksums.")


if __name__ == "__main__":
    main()
