"""A little EPUB chess book, built with zipfile: a title page, a chapter with
a game (its main line in <b>, a note in <i>), two exercise boards as PNG
pictures (or, with svg, as SVG drawings, which give no board picture) and
their solutions. tests/test_epub.py and the library tests read it."""
import sys
import zipfile
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_assemble import GAME_EN, PROSE  # noqa: E402

MIMETYPE = b"application/epub+zip"
CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def board_png(px=240):
    """The chequered board of test_assemble._Writer.picture, px pixels wide."""
    sq = px // 8
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, px, px), False)
    pix.clear_with(255)
    for r in range(8):
        for c in range(8):
            if (r + c) % 2:
                pix.set_rect(pymupdf.IRect(c * sq, r * sq, c * sq + sq, r * sq + sq), (110,))
    return pix.tobytes("png")


def board_svg(px=240):
    sq = px // 8
    dark = "".join(f'<rect x="{c * sq}" y="{r * sq}" width="{sq}" height="{sq}" fill="#6e6e6e"/>'
                   for r in range(8) for c in range(8) if (r + c) % 2)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{px}">'
            f'<rect width="{px}" height="{px}" fill="#fff"/>{dark}</svg>')


def _page(title, body):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>{title}</title></head>
<body>{body}</body>
</html>"""


def _prose(n):
    return " ".join(PROSE[k % len(PROSE)] for k in range(n))


def make_epub(path, title="Little Epub", game=GAME_EN, svg=False, encrypted=False):
    """Write the book to path and return it. encrypted adds
    META-INF/encryption.xml, as a seller's lock does."""
    path = Path(path)
    if svg:
        board = lambda n: f"<p>{n}</p><div>{board_svg()}</div><p>White to move</p>"  # noqa: E731
    else:
        board = lambda n: (f'<p>{n}</p><p><img src="board{n}.png" width="240" height="240" '  # noqa: E731
                           f'alt="Diagram {n}"/></p><p>White to move</p>')
    pages = {
        "title.xhtml": _page(title, f"<h1>{title}</h1><p>A chess book for beginners.</p>"),
        "ch1.xhtml": _page("Chapter 1", (
            f"<h1>Chapter 1</h1><p>{_prose(60)}</p><h2>SHORT GAMES</h2>"
            f"<p><b>Smith - Jones,</b> London 1901</p><p><b>{game[0]}</b></p>"
            "<p><i>Better is 3...Bc5 4.c3 Nf6 with a quiet game.</i></p>"
            f"<p><b>{game[1]}</b></p><p><b>{game[2]}</b></p>"
            "<p><i>The king has to walk into the open.</i></p>"
            f"<p><b>{game[3]}</b></p><p>White has a strong attack.</p><p><b>1-0</b></p>"
            f"<p>{_prose(80)}</p>")),
        "ex.xhtml": _page("Exercises", f"<h2>EXERCISES</h2>{board(1)}<p>{_prose(30)}</p>{board(2)}"),
        "sol.xhtml": _page("Solutions", (
            "<h2>SOLUTIONS</h2><p><b>1. 1.Rd8+ Kh7 2.Rd7</b></p><p>2. White wins with 1.Nf6+.</p>"
            f"<p>{_prose(40)}</p>")),
    }
    nav = _page("Contents", (
        '<nav epub:type="toc"><ol><li><a href="ch1.xhtml">Chapter 1</a></li>'
        '<li><a href="ex.xhtml">Exercises</a></li></ol></nav>'))
    ncx = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head/><docTitle><text>T</text></docTitle>
<navMap><navPoint id="n1" playOrder="1"><navLabel><text>Chapter 1</text></navLabel><content src="ch1.xhtml"/></navPoint>
<navPoint id="n2" playOrder="2"><navLabel><text>Exercises</text></navLabel><content src="ex.xhtml"/></navPoint>
</navMap></ncx>"""
    items = "".join(f'<item id="{n[:-6]}" href="{n}" media-type="application/xhtml+xml"/>' for n in pages)
    pics = "" if svg else "".join(f'<item id="b{n}" href="board{n}.png" media-type="image/png"/>'
                                  for n in (1, 2))
    spine = "".join(f'<itemref idref="{n[:-6]}"/>' for n in pages)
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">little-epub</dc:identifier>
<dc:title>{title}</dc:title><dc:language>en</dc:language></metadata>
<manifest>{items}{pics}<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>
<spine toc="ncx">{spine}</spine>
</package>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), MIMETYPE, compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER)
        if encrypted:
            z.writestr("META-INF/encryption.xml", '<encryption xmlns="urn:oasis:names:tc:opendocument:'
                                                  'xmlns:container"/>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/toc.ncx", ncx)
        for name, text in pages.items():
            z.writestr("OEBPS/" + name, text)
        if not svg:
            png = board_png()
            for n in (1, 2):
                z.writestr(f"OEBPS/board{n}.png", png)
    return path
