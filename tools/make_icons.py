"""Render the app's icons from one SVG source, web/icon.svg: the open book
with two pages of a 3 by 4 chequer (chessbook/style.py, book_svg), still, on
the page background of DESIGN.md's light tokens (a Home Screen icon cannot
follow the dark scheme).

    python3 tools/make_icons.py            render web/icons/*.png and favicon.svg
    python3 tools/make_icons.py --svg      write web/icon.svg again from style.py first

Writes, into web/icons/: icon-180.png (apple-touch-icon), icon-192.png and
icon-512.png (the manifest), icon-maskable-512.png (the manifest's maskable
icon: the book inside the middle 60 %, the safe zone of any mask),
icon-32.png and favicon.svg (the browser tab). PyMuPDF draws the PNGs. The
site build (tools/build_web.py) copies the files; they are committed, so that
the build needs no drawing.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCE = ROOT / "web" / "icon.svg"
OUT = ROOT / "web" / "icons"
LIGHT = {"bg": "#fbfbfa", "light": "#ecebe6", "dark": "#bdbab2", "line": "#6f6f6c"}


def source_svg():
    """web/icon.svg as style.book_svg draws it: square, with a margin."""
    from chessbook import style
    svg = style.book_svg(cls="icon", animated=False, light=LIGHT["light"], dark=LIGHT["dark"],
                         line=LIGHT["line"], bg=LIGHT["bg"], pad=8)
    # the background reaches far beyond the view box, so that a wider view (maskable) keeps it
    return re.sub(r'<rect x="[^"]+" y="[^"]+" width="[^"]+" height="[^"]+" fill="#fbfbfa"/>',
                  '<rect x="-1000" y="-1000" width="2064" height="2044" fill="#fbfbfa"/>', svg, count=1)


def widened(svg, factor):
    """The same icon with the view box widened by factor about its centre."""
    m = re.search(r'viewBox="([-\d. ]+)"', svg)
    x, y, w, h = (float(v) for v in m.group(1).split())
    cx, cy = x + w / 2, y + h / 2
    w2, h2 = w * factor, h * factor
    return svg.replace(m.group(0), f'viewBox="{cx - w2 / 2:g} {cy - h2 / 2:g} {w2:g} {h2:g}"')


def render(svg, size):
    import pymupdf
    m = re.search(r'viewBox="([-\d. ]+)"', svg)
    w = float(m.group(1).split()[2])
    svg = svg.replace("<svg ", f'<svg width="{w:g}" height="{w:g}" ', 1)
    doc = pymupdf.open(stream=svg.encode("utf-8"), filetype="svg")
    page = doc[0]
    zoom = size / page.rect.width
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("png")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--svg" in argv or not SOURCE.exists():
        SOURCE.write_text(source_svg() + "\n", encoding="utf-8")
    svg = SOURCE.read_text(encoding="utf-8").strip()
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (180, 192, 512):
        (OUT / f"icon-{size}.png").write_bytes(render(svg, size))
    # the browser tab's icon is tiny: the book fills more of it
    (OUT / "icon-32.png").write_bytes(render(widened(svg, 0.84), 32))
    # the book's width is about 80 % of the icon: widened by 1.4 it keeps inside the middle 60 %
    (OUT / "icon-maskable-512.png").write_bytes(render(widened(svg, 1.4), 512))
    (OUT / "favicon.svg").write_text(svg + "\n", encoding="utf-8")
    print("Icons written to", OUT)


if __name__ == "__main__":
    main()
