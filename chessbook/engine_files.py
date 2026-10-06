"""The chess engine the reader analyses with: Stockfish 19 as Stockfish.js by
Nathan Rugg (the npm package "stockfish" 19.0.0, GPLv3), in its lite
single-threaded build. That build runs in Safari on iOS 16 and macOS 11 and
later and in every current browser without the cross-origin isolation
headers that GitHub Pages cannot send; it is 1.8 MB.

The two files, the licence text and their checksums are named here once,
for tools/fetch_engine.py (which downloads them), tools/build_web.py and
make_reader.py (which copy them next to the pages) and the tests.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

VERSION = "19.0.0"
NAME = "Stockfish 19"
BUILD = "lite single-threaded build of Stockfish.js"
TARBALL = f"https://registry.npmjs.org/stockfish/-/stockfish-{VERSION}.tgz"
JS = "stockfish-19-lite-single.js"
WASM = "stockfish-19-lite-single.wasm"
LICENCE = "Copying.txt"
SHA256 = {
    JS: "d3344124ab067fb0b90ee77873bb8e9fbf5fc01bc525fe714b0f942581e889e6",
    WASM: "57ac2d72312aba346760e3f173f687a8c211208e97a87268436f7f0e10bb5387",
}
FILES = (JS, WASM, LICENCE)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(folder):
    """The engine folder holds both files with the right checksums and the
    licence; raises ValueError naming what is wrong."""
    folder = Path(folder)
    for name in FILES:
        if not (folder / name).is_file():
            raise ValueError(f"{folder / name} is missing")
    for name, want in SHA256.items():
        got = sha256(folder / name)
        if got != want:
            raise ValueError(f"{folder / name} has checksum {got}, not {want}")
    return True


def present(folder):
    """True when the folder holds the engine files (checksums included)."""
    try:
        return check(folder)
    except (ValueError, OSError):
        return False


def copy(src, dest):
    """Copy the engine files from src into dest (an "engine" folder beside the
    pages) after checking them."""
    check(src)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copyfile(Path(src) / name, dest / name)
    return dest
