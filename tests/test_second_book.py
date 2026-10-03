"""A second, typeset book: one column, English letters, no pictures.

It guards against code that only works on the Primer.
"""
import sys
from pathlib import Path

import chess.pgn
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chessbook import assemble  # noqa: E402

PAGES = [
    [("h", "Chapter 1"), ("n", "Open games and the centre.")],
    [("g", "Morphy - Duke of Brunswick and Count Isouard, Paris 1858"),
     ("m", "1.e4 e5 2.Nf3 d6 3.d4 Bg4"),
     ("n", "Black should prefer 3...exd4 4.Nxd4 Nf6, keeping the balance."),
     ("m", "4.dxe5 Bxf3 5.Qxf3 dxe5 6.Bc4 Nf6 7.Qb3 Qe7 8.Nc3 c6 9.Bg5 b5"),
     ("n", "Or 9...Qb4 10.Qxb4 Bxb4 11.Bxf6 gxf6 with a worse ending."),
     ("m", "10.Nxb5 cxb5 11.Bxb5+ Nbd7 12.O-O-O Rd8 13.Rxd7 Rxd7 14.Rd1 Qe6"),
     ("m", "15.Bxd7+ Nxd7 16.Qb8+ Nxb8 17.Rd8# 1-0")],
    [("h", "Chapter 2"), ("n", "Attack on the king.")],
    [("g", "Anderssen - Kieseritzky, London 1851"),
     ("m", "1.e4 e5 2.f4 exf4 3.Bc4 Qh4+ 4.Kf1 b5 5.Bxb5 Nf6 6.Nf3 Qh6 7.d3 Nh5"),
     ("m", "8.Nh4 Qg5 9.Nf5 c6 10.g4 Nf6 11.Rg1 cxb5 12.h4 Qg6 13.h5 Qg5 14.Qf3 Ng8"),
     ("m", "15.Bxf4 Qf6 16.Nc3 Bc5 17.Nd5 Qxb2 18.Bd6 Bxg1 19.e5 Qxa1+ 20.Ke2 Na6"),
     ("m", "21.Nxg7+ Kd8 22.Qf6+ Nxf6 23.Be7# 1-0")],
]
STYLE = {"h": ("Times-Bold", 16), "g": ("Times-Bold", 11),
         "m": ("Times-Bold", 10.5), "n": ("Times-Roman", 10)}


def make_book(path):
    doc = pymupdf.open()
    for lines in PAGES:
        p = doc.new_page(width=420, height=640)
        p.insert_text((40, 30), str(len(doc)), fontsize=8, fontname="Times-Roman")
        y = 70
        for kind, text in lines:
            font, size = STYLE[kind]
            p.insert_text((40, y), text, fontsize=size, fontname=font)
            y += size + 9
    doc.save(path)


def test_typeset_book_end_to_end(tmp_path):
    pdf = tmp_path / "classics.pdf"
    make_book(pdf)
    book = assemble.build_book(pdf, output_dir=tmp_path / "output",
                               books_dir=tmp_path / "books")
    games = [l for l in book["lines"] if l["kind"] == "game"]
    assert len(games) == 2
    assert all(l["status"] == "ok" for l in games)
    assert len(book["unattached"]) == 0
    for line in games:
        node, plies = book["nodes"][line["root"]], 0
        while node["children"]:
            node = book["nodes"][node["children"][0]]
            plies += 1
        assert chess.Board(node["fen"]).is_checkmate()
        assert plies in (33, 45)
    titles = " ".join(l["title"] for l in games)
    assert "Duke of Brunswick" in titles and "Kieseritzky" in titles
