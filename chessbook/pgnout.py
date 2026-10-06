"""PGN files from an assembled book (see assemble.build_book).

write_pgn(book, out_dir) writes one file per chapter, out_dir/chNN.pgn, with
each decoded line as a PGN game: the header fields come from the book's game
header where it has one, SetUp and FEN tags are written when the line does not
start from the initial position, and the line's variations and the book's
notes come along as PGN variations and comments. Every file is read back with
python-chess and checked against the book.

Lines that wait for a diagram position (Stage 3) cannot be written as PGN
yet, because their start position is unknown; they are counted and left out.

A move the program could not read is written as the move it assumed (with a
comment that says so) when it assumed one, and as a comment only otherwise.
Where the book's text lacks moves (a gap in its numbering), the game stops
there with a comment that quotes the rest of the printed score, and its
result is "*". Notes whose moves branch off after the last move of the game
are written as a variation that repeats that move, never as moves played.
The variations the reader added on the board (corrections.py "added") are
variations like the book's, with the comment "Added by the reader." on their
first move.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import chess
import chess.pgn

_NAG_FOR = {"!": chess.pgn.NAG_GOOD_MOVE, "?": chess.pgn.NAG_MISTAKE,
            "!!": chess.pgn.NAG_BRILLIANT_MOVE, "??": chess.pgn.NAG_BLUNDER,
            "!?": chess.pgn.NAG_SPECULATIVE_MOVE, "?!": chess.pgn.NAG_DUBIOUS_MOVE}


def _clean(text):
    """Text safe inside a PGN comment: no braces, no control characters."""
    t = (text or "").replace("{", "(").replace("}", ")")
    t = "".join(ch if ch >= " " or ch == "\n" else "▫" for ch in t)
    return re.sub(r"\s+", " ", t).strip()


def _tag(text):
    t = _clean(text).replace('"', "'").replace("\\", "/")
    return t or "?"


def _raw_display(raw):
    return _clean(raw)


def _printed_page(book, page):
    off = book.get("folio_offset")
    if off is None or page - off < 1:
        return None
    return page - off


def _broken(book, line):
    """True when the line's main line reaches a gap in the book's text."""
    nodes = book["nodes"]
    nid = line["root"]
    while True:
        kids = [c for c in nodes[nid]["children"] if nodes[c]["main"]]
        if not kids:
            return False
        nid = kids[0]
        n = nodes[nid]
        if n["status"] == "failed" and not n.get("fen") and not n.get("san"):
            return True


def line_headers(book, line):
    h = line.get("header") or {}
    ch = book["chapters"][line["chapter"]]
    printed = _printed_page(book, line["page"])
    tags = {
        "Event": _tag(h.get("event") or line["title"]),
        "Site": _tag(h.get("site") or "?"),
        "Date": f"{h['year']}.??.??" if h.get("year") else "????.??.??",
        "Round": "?",
        "White": _tag(h.get("white") or "?"),
        "Black": _tag(h.get("black") or "?"),
        "Result": "*" if _broken(book, line) else (line.get("result") or "*"),
        "Annotator": _tag(book.get("title") or "?"),
        "Chapter": _tag(ch.get("title") or ""),
        "BookPage": str(printed if printed is not None else line["page"]),
        "PDFPage": str(line["page"]),
        "LineId": line["id"],
    }
    if line.get("diagram"):
        tags["Diagram"] = line["diagram"]
    if not h:
        tags["Event"] = _tag(line["title"])
    return tags


def line_game(book, line):
    """The PGN game of one decoded line (None for a line still waiting)."""
    if line.get("status") == "waiting" or not line.get("start_fen"):
        return None
    nodes = book["nodes"]
    game = chess.pgn.Game()
    for k, v in line_headers(book, line).items():
        game.headers[k] = v
    board = chess.Board(line["start_fen"])
    if line["start_fen"] != chess.STARTING_FEN:
        game.setup(board)
    root = nodes[line["root"]]
    if root.get("comment"):
        game.comment = _clean(root["comment"])

    def add_children(pgn_node, nid, board):
        node = nodes[nid]
        kids = node["children"]
        if (node["main"] and nid != line["root"] and kids
                and not any(nodes[c]["main"] for c in kids) and pgn_node.parent is not None):
            # Notes after the last move of the game: a variation that repeats
            # that move, so that no note reads as a move played.
            for cid in kids:
                again = pgn_node.parent.add_variation(pgn_node.move)
                add_move(again, cid, board, main=True)
            return
        for k, cid in enumerate(kids):
            add_move(pgn_node, cid, board, main=(k == 0))

    def add_gap(pgn_parent, nid):
        """The book's text lacks moves here: stop, and quote the rest."""
        n = nodes[nid]
        rest, cur = [], nid
        while True:
            kids = [c for c in nodes[cur]["children"] if nodes[c]["main"]]
            if not kids:
                break
            cur = kids[0]
            m = nodes[cur]
            num = (f"{m['number']}{'...' if m['black'] else '.'}"
                   if m.get("number") is not None else "")
            rest.append(num + _raw_display(m.get("raw")))
        text = n.get("reason") or "The book's text lacks moves here."
        text += " The score is not complete."
        if rest:
            text += " The book's text goes on with: " + " ".join(rest) + "."
        pgn_parent.comment = (pgn_parent.comment + " " + text).strip()

    def add_move(pgn_parent, nid, board, main):
        n = nodes[nid]
        comment = _clean(n.get("comment"))
        move = None
        notes = []
        if n["status"] == "failed" and not n.get("fen") and not n.get("san"):
            add_gap(pgn_parent, nid)
            return
        if n.get("san"):
            try:
                move = board.parse_san(n["san"])
            except ValueError:
                move = None
                notes.append(f"The program read \"{_raw_display(n['raw'])}\" as {n['san']}, "
                             "which is not legal here.")
            if n["status"] == "inserted":
                notes.append("This move is missing from the book's text; the program "
                             "supplied it.")
            if n.get("corrected") == "added" and \
                    nodes[n["parent"]].get("corrected") != "added":
                notes.append("Added by the reader.")
        elif n.get("assumed"):
            try:
                move = board.parse_san(n["assumed"])
            except ValueError:
                move = None
            notes.append(f"The book's text here, \"{_raw_display(n['raw'])}\", could not be "
                         f"read. The program assumed {n['assumed']} so that the line could go on.")
        else:
            notes.append(f"The book's text here, \"{_raw_display(n['raw'])}\", could not be "
                         "read as a move.")
        if move is None:
            # no move: the note goes on the parent and the children follow from it
            text = " ".join(notes + ([comment] if comment else []))
            if text:
                pgn_parent.comment = (pgn_parent.comment + " " + text).strip()
            add_children(pgn_parent, nid, board)
            return
        child = pgn_parent.add_variation(move)
        ann = re.findall(r"[!?]{1,2}$", n.get("raw", "").rstrip("+t#†‡.,;:)"))
        if ann and ann[0] in _NAG_FOR:
            child.nags.add(_NAG_FOR[ann[0]])
        text = " ".join(notes + ([comment] if comment else []))
        if text:
            child.comment = text
        b2 = board.copy(stack=False)
        b2.push(move)
        add_children(child, nid, b2)

    add_children(game, line["root"], board)
    return game


def _count_moves(game):
    main = sum(1 for _ in game.mainline_moves())
    total = 0
    stack = [game]
    while stack:
        g = stack.pop()
        for v in g.variations:
            total += 1
            stack.append(v)
    return main, total


def chapter_pgn(book, chapter_index):
    """(PGN text, games written, lines left out because they wait for Stage 3)."""
    out, written, waiting = [], [], 0
    for line in book["lines"]:
        if line["chapter"] != chapter_index:
            continue
        g = line_game(book, line)
        if g is None:
            waiting += 1
            continue
        exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
        out.append(g.accept(exporter))
        written.append((line, g))
    return "\n\n".join(out) + ("\n" if out else ""), written, waiting


def validate(text, written):
    """Read a PGN text back with python-chess and compare it with the games
    that were written. Returns a list of problems (empty when all is well)."""
    problems = []
    stream = io.StringIO(text)
    for line, g in written:
        back = chess.pgn.read_game(stream)
        if back is None:
            problems.append(f"{line['id']}: the game is missing when the file is read back.")
            continue
        if back.errors:
            problems.append(f"{line['id']}: {back.errors[0]}")
        if _count_moves(back) != _count_moves(g):
            problems.append(f"{line['id']}: the moves read back differ from the moves written.")
        if back.headers.get("LineId") != line["id"]:
            problems.append(f"{line['id']}: the games are out of order when read back.")
    if chess.pgn.read_game(stream) is not None:
        problems.append("The file holds more games than were written.")
    return problems


def write_pgn(book, out_dir, chapters=None):
    """Write out_dir/chNN.pgn for every chapter (or those in chapters). Returns
    {index: {"path", "games", "waiting", "moves", "problems"}}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {}
    for ch in book["chapters"]:
        i = ch["index"]
        if chapters is not None and i not in chapters:
            continue
        if ch["end"] < ch["start"]:
            continue
        text, written, waiting = chapter_pgn(book, i)
        path = out_dir / ch["pgn"]
        path.write_text(text, encoding="utf-8")
        problems = validate(path.read_text(encoding="utf-8"), written)
        moves = sum(_count_moves(g)[1] for _, g in written)
        report[i] = {"path": str(path), "games": len(written), "waiting": waiting,
                     "moves": moves, "problems": problems}
    return report
