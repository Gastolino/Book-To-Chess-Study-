"""Build the browser app: a static site where a reader drops a chess book PDF
and reads it beside a live board. Every book is processed on the reader's own
device; nothing is uploaded anywhere.

Usage:
    python3 tools/build_web.py [--out output/site] [--local PYODIDE_DIR]
                               [--pymupdf WHEEL] [--chess WHEEL]

By default the site loads Pyodide from its CDN and PyMuPDF from PyPI, so the
site itself stays small. --local copies a Pyodide distribution into the site
and --pymupdf copies the PyMuPDF wheel, for hosts or tests without those
networks.
"""
import argparse
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook import style  # noqa: E402

PYODIDE_VERSION = "0.29.5"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
# Packages of the Pyodide distribution itself that board reading needs.
PYODIDE_PACKAGES = ["numpy", "opencv-python"]
PYMUPDF_WHEEL = "pymupdf-1.28.2-cp313-abi3-pyemscripten_2025_0_wasm32.whl"

SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chess Book Reader</title>
<style>__CSS__
html,body{height:100%}
body{margin:0;display:flex;flex-direction:column}
#start{max-width:620px;margin:0 auto;padding:72px 16px 32px;width:100%;box-sizing:border-box}
#start h1{font-size:26px;margin-bottom:10px}
#start p{margin:0 0 10px;color:var(--muted)}
#drop{margin-top:28px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);
  padding:40px 0;text-align:center;cursor:pointer}
#drop.over{border-color:var(--accent)}
#drop .big{font-size:17px;font-weight:500;color:var(--fg)}
#drop .small{font-size:13px;color:var(--muted);margin-top:6px}
#file{position:absolute;left:-9999px}
#status{margin-top:20px;font-size:13px;color:var(--muted);min-height:1.5em;
  font-variant-numeric:tabular-nums}
#status.error{color:var(--fail)}
#bar{height:1px;background:var(--line);margin-top:8px;position:relative;overflow:hidden}
#bar i{position:absolute;left:0;top:0;bottom:0;width:30%;background:var(--accent);
  animation:run 1.4s linear infinite;display:none}
#bar.on i{display:block}
@keyframes run{from{left:-30%}to{left:100%}}
#view{flex:1;border:0;width:100%;display:none}
#top{display:none;align-items:center;gap:20px;padding:10px 16px;border-bottom:1px solid var(--line);
  font-size:13px;color:var(--muted)}
#top b{font-weight:500;color:var(--fg)}
#top button{font:inherit;color:var(--fg);background:none;border:0;padding:0;cursor:pointer}
#top button:hover{text-decoration:underline}
#top .gap{flex:1}
</style></head>
<body>
<div id="top"><b id="bookname"></b><span id="took"></span><span class="gap"></span>
<button id="again" type="button">Read again</button>
<button id="another" type="button">Open another book</button></div>
<main id="start">
<h1>Chess Book Reader</h1>
<p>This page turns a chess book in PDF form into a reader: the book's pages beside a
live board that follows the moves and variations.</p>
<p>Your book stays on this device. The page reads it here and sends it nowhere.</p>
<div id="drop" tabindex="0" role="button" aria-label="Choose a chess book PDF">
<div class="big">Drop a chess book here</div>
<div class="small">or click to choose a PDF file</div></div>
<input id="file" type="file" accept="application/pdf,.pdf">
<div id="status">Preparing the reader. The first visit downloads about 40 MB; later visits
start at once.</div>
<div id="bar" class="on"><i></i></div>
</main>
<iframe id="view" title="Book reader"></iframe>
<script>
const CFG = __CFG__;
const $ = (id) => document.getElementById(id);
const worker = new Worker("worker.js");
let ready = false, busy = false, current = null, lastFile = null;

// Links inside the reader pages ask this page to open another page.
const NAV = `<script>document.addEventListener("click",function(e){var a=e.target.closest("a[href]");
if(!a)return;var h=a.getAttribute("href"),m=h.match(/^(index\\.html|ch\\d+\\.html)(#.*)?$/);
if(m){e.preventDefault();parent.postMessage({open:m[1],hash:m[2]||""},"*");}},true);<\\/script>`;

function status(text, error) {
  $("status").textContent = text;
  $("status").classList.toggle("error", !!error);
}
function show(name, hash, htmlText) {
  const blob = new Blob([htmlText.replace("</body>", NAV + "</body>")], { type: "text/html" });
  if (current) URL.revokeObjectURL(current);
  current = URL.createObjectURL(blob);
  $("view").src = current + (hash || "");
  $("start").style.display = "none";
  $("view").style.display = "block";
  $("top").style.display = "flex";
}
worker.onmessage = (e) => {
  const m = e.data;
  if (m.type === "progress") status(m.text);
  else if (m.type === "ready") {
    ready = true;
    $("bar").classList.remove("on");
    status("Ready. Choose a book.");
  } else if (m.type === "index") {
    busy = false;
    $("bar").classList.remove("on");
    $("took").textContent = "read in " + Math.round(m.seconds) + " seconds";
    show("index.html", "", m.html);
  } else if (m.type === "page") {
    $("bar").classList.remove("on");
    show(m.name, m.hash, m.html);
  } else if (m.type === "error") {
    busy = false;
    $("bar").classList.remove("on");
    status("The book could not be read: " + m.text, true);
  }
};
window.addEventListener("message", (e) => {
  if (!e.data || !e.data.open) return;
  status("Opening " + e.data.open);
  worker.postMessage(e.data.open === "index.html"
    ? { type: "index", hash: e.data.hash }
    : { type: "chapter", name: e.data.open, hash: e.data.hash });
});
async function take(file) {
  if (!file || busy) return;
  if (!/\\.pdf$/i.test(file.name)) { status("Please choose a PDF file.", true); return; }
  if (!ready) { status("The reader is still starting. Try again in a moment."); return; }
  busy = true;
  lastFile = file;
  $("bookname").textContent = file.name.replace(/\\.pdf$/i, "");
  $("bar").classList.add("on");
  status("Reading " + file.name);
  const bytes = await file.arrayBuffer();
  const name = file.name.replace(/[^\\w.\\-]+/g, "_");
  worker.postMessage({ type: "process", name, bytes, selection: storedSelection(name) }, [bytes]);
}
$("drop").addEventListener("click", () => $("file").click());
$("drop").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") $("file").click(); });
$("file").addEventListener("change", (e) => take(e.target.files[0]));
["dragenter", "dragover"].forEach((t) => $("drop").addEventListener(t, (e) => {
  e.preventDefault(); $("drop").classList.add("over"); }));
["dragleave", "drop"].forEach((t) => $("drop").addEventListener(t, (e) => {
  e.preventDefault(); $("drop").classList.remove("over"); }));
$("drop").addEventListener("drop", (e) => take(e.dataTransfer.files[0]));
$("another").addEventListener("click", () => location.reload());
$("again").addEventListener("click", () => {
  if (!lastFile || busy) return;
  $("start").style.display = "block"; $("view").style.display = "none"; $("top").style.display = "none";
  take(lastFile);
});
// The reader keeps a changed selection under "chessbook-selection:<file>:<pages>".
function storedSelection(name) {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith("chessbook-selection:" + name + ":")) {
        const v = JSON.parse(localStorage.getItem(k));
        if (v && v.selection) return JSON.stringify(v.selection);
      }
    }
  } catch (e) { /* no storage */ }
  return null;
}
worker.postMessage({ type: "init", cfg: CFG });
</script>
</body></html>
"""


def app_zip(dest):
    """The project's Python code (and fonts) as one archive for the browser."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted((ROOT / "chessbook").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                z.write(path, path.relative_to(ROOT).as_posix())
        z.write(ROOT / "stage1_inspect.py", "stage1_inspect.py")
        z.write(ROOT / "web" / "driver.py", "web/driver.py")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "site")
    ap.add_argument("--local", type=Path, default=None,
                    help="a Pyodide distribution folder to copy into the site")
    ap.add_argument("--pymupdf", type=Path, default=None, help="PyMuPDF wheel to copy")
    ap.add_argument("--chess", type=Path, required=True, help="python-chess wheel to copy")
    ap.add_argument("--pymupdf-url", default=None,
                    help="where browsers fetch the PyMuPDF wheel when it is not copied")
    args = ap.parse_args(argv)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "wheels").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "web" / "worker.js", out / "worker.js")
    app_zip(out / "app.zip")
    shutil.copyfile(args.chess, out / "wheels" / args.chess.name)
    wheels = ["wheels/" + args.chess.name]
    if args.pymupdf:
        shutil.copyfile(args.pymupdf, out / "wheels" / args.pymupdf.name)
        wheels.insert(0, "wheels/" + args.pymupdf.name)
    elif args.pymupdf_url:
        wheels.insert(0, args.pymupdf_url)
    else:
        raise SystemExit("Give --pymupdf or --pymupdf-url.")
    if args.local:
        shutil.copytree(args.local, out / "pyodide", dirs_exist_ok=True)
        index_url = "pyodide/"
    else:
        index_url = PYODIDE_CDN
    # Wheel paths are made absolute against the site, because the worker
    # resolves them from its own location.
    cfg = ("{indexURL: new URL(%r, location.href).href, appZip: new URL('app.zip', location.href).href, "
           "wheels: %s.map(w => new URL(w, location.href).href), packages: %s}") % (
               index_url, wheels, PYODIDE_PACKAGES)
    text = SHELL.replace("__CSS__", style.page_css()).replace("__CFG__", cfg)
    (out / "index.html").write_text(text, encoding="utf-8")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"Site written to {out} ({size / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
