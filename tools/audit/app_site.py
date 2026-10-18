"""Build the browser app for the audit, once for each version of its code.

Usage:
    python3 tools/audit/app_site.py            prints the folder of the built site

The site goes to output/audit/site/<digest>/, where <digest> covers web/,
chessbook/ and tools/build_web.py, so that a change of the app or of the
reading code builds it again. It uses the local Pyodide and wheels
(local/pyodide, local/wheels, and local/engine for Stockfish when it is
there), as tests/test_app_e2e.py does. tools/audit/app_lib.js calls this
before it opens a book.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import books  # noqa: E402

ROOT = books.ROOT
LOCAL = books.MAIN / "local"


def digest():
    h = hashlib.sha1()
    for base in ("web", "chessbook"):
        for q in sorted((ROOT / base).rglob("*")):
            if q.is_file() and "__pycache__" not in q.parts:
                h.update(str(q.relative_to(ROOT)).encode())
                h.update(q.read_bytes())
    h.update((ROOT / "tools" / "build_web.py").read_bytes())
    return h.hexdigest()[:12]


def wheel(pattern):
    found = sorted((LOCAL / "wheels").glob(pattern))
    if not found:
        raise SystemExit(f"No {pattern} in {LOCAL / 'wheels'}.")
    return found[-1]


def main():
    out = books.MAIN / "output" / "audit" / "site" / digest()
    if not (out / "index.html").exists():
        cmd = [sys.executable, str(ROOT / "tools" / "build_web.py"), "--out", str(out),
               "--local", str(LOCAL / "pyodide"), "--pymupdf", str(wheel("pymupdf-*.whl")),
               "--chess", str(wheel("chess-*.whl"))]
        if (LOCAL / "engine").is_dir() and any((LOCAL / "engine").iterdir()):
            cmd += ["--engine", str(LOCAL / "engine")]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    print(out)


if __name__ == "__main__":
    main()
