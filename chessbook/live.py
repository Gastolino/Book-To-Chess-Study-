"""Apply the reader's corrections to an assembled book at once.

The browser app keeps the assembled book (assemble.build_book with a state
dict) in its worker. apply() takes the reader's corrections as they stand
now, lets the builder replay only the lines they touch
(assemble._Builder.apply_fix) and brings book.json up to date in place;
chapter_patch() then says what changed for one chapter reader, in the form
the reader's applyPatch() takes, so that the board, the move list, the
outlines on the page and the Review list change without leaving the page.

A correction of a piece symbol touches lines all over the book: apply()
replays the lines of the chapters it is given first, and names the other
chapters as pending, for later calls (one or a few chapters at a time) to
finish while the reader goes on reading.

The result is always that of a fresh build with the same corrections, since
build_book applies them through the same replay.
"""
from __future__ import annotations

import json
import time
from collections import Counter

from . import assemble, corrections as fixes, pgnout, reader


def _node_out(n):
    nn = dict(n)
    if nn["status"] == "root":
        nn["status"] = "ok"
    return nn


def apply(state, book, fix, chapters=None, window=None):
    """Apply the corrections fix to the book (book.json as a dict, changed in
    place). chapters limits the replay of lines that a changed piece symbol
    touches to those chapters, and window to the lines that start within
    that many pages of the first of them (a small batch). Returns {"lines",
    "removed", "pages", "pending", "seconds"}."""
    t0 = time.perf_counter()
    b = state["builder"]
    fix = fixes.normalise(fix or {})
    res = b.apply_fix(fix, chapters, window)
    gone = set(res["lines"]) | set(res["removed"])
    nodes = book["nodes"]
    for nid in [k for k, n in nodes.items() if n["line"] in gone]:
        del nodes[nid]
    for lid in res["lines"]:
        for nid in b.by_line.get(lid, []):
            nodes[nid] = _node_out(b.nodes[nid])
    lines = b.line_dicts()
    lines.sort(key=lambda d: (d["chapter"], d["_offset"]))
    for d in lines:
        d.pop("_offset")
    book["lines"] = lines
    diagram_lines = {}
    for d in lines:
        if d["diagram"]:
            diagram_lines.setdefault(d["diagram"], []).append(d["id"])
    changed = set(res["pages"])
    readings = state.get("readings") or {}
    for pg in book["pages"]:
        p = pg["page"]
        if p in changed:
            pg["marks"] = assemble.page_marks(b, p)
        for d in pg["diagrams"]:
            did = d["id"]
            fen = b.fix_diagrams.get(did) or b.diagram_fens.get(did)
            for k in ("fen", "status", "corrected", "reading"):
                d.pop(k, None)
            d.update(assemble._diagram_reading(did, fen, readings.get(did), did in fix["diagrams"]))
            d["after_node"] = b.after_node.get(did)
            d["checked"] = did in b.checked
            d["lines"] = diagram_lines.get(did, [])
    book["unattached"] = assemble.public_list(b.unattached)
    book["dismissed"] = assemble.public_list(b.dismissed)
    book["attached"] = assemble.public_list(b.attached)
    book["waiting"] = assemble.public_list(b.waiting)
    book["corrections"] = fix
    book["symbols"] = dict(assemble._symbol_counts(
        {pg["page"]: pg["marks"] for pg in book["pages"]}, book.get("letters"),
        fix["glyphs"]).most_common())
    _recount(book, b, fix)
    res["seconds"] = round(time.perf_counter() - t0, 3)
    return res


def _recount(book, b, fix):
    """The counts of every chapter and of the book (as _book_dict has them)."""
    counts = {c["index"]: assemble._empty_counts() for c in book["chapters"]}
    for d in book["lines"]:
        c = counts[d["chapter"]]
        c["lines"] += 1
        c[d["kind"] + "s"] += 1
        c["line_status"][d["status"]] += 1
        c["variations"] += d["variations"]
    line_chapter = {d["id"]: d["chapter"] for d in book["lines"]}
    for n in book["nodes"].values():
        if n["parent"] is None:
            continue
        c = counts[line_chapter[n["line"]]]
        what = assemble.CORRECTED_COUNTS.get(n.get("corrected"))
        if what:
            c["corrected"][what] += 1
        if n.get("corrected") == "added":
            continue            # (the moves the reader added are not moves of the book)
        c["moves"][n["status"]] += 1
        if not n["main"]:
            c["variation_moves"] += 1
    for u in book["unattached"]:
        counts[u["chapter"]]["unattached"] += 1
    for u in book["dismissed"] + book["attached"]:
        counts[u["chapter"]]["corrected"]["sequences"] += 1
    chapter_of = {}
    for c in book["chapters"]:
        for p in range(c["start"], c["end"] + 1):
            chapter_of[p] = c["index"]
    for pg in book["pages"]:
        for d in pg["diagrams"]:
            if d.get("corrected") and chapter_of.get(pg["page"]) in counts:
                counts[chapter_of[pg["page"]]]["corrected"]["diagrams"] += 1
    for w in book["waiting"]:
        counts[w["chapter"]]["waiting"] += 1
    total = assemble._empty_counts()
    for c in book["chapters"]:
        k = counts[c["index"]]
        for key in ("lines", "games", "fragments", "variations", "variation_moves",
                    "unattached", "waiting"):
            total[key] += k[key]
        for part in ("moves", "line_status", "corrected"):
            total[part].update(k[part])
        k["line_status"] = dict(k["line_status"])
        k["moves"] = {s: k["moves"].get(s, 0) for s in assemble.STATUSES}
        k["corrected"] = dict(k["corrected"])
        c["counts"] = k
    stats = book.get("stats") or {}
    for key in ("lines", "games", "fragments", "variations", "variation_moves", "unattached",
                "waiting"):
        stats[key] = total[key]
    stats["moves"] = {s: total["moves"].get(s, 0) for s in assemble.STATUSES}
    stats["line_status"] = dict(total["line_status"])
    stats["corrected"] = dict(total["corrected"], symbols=len(fix["glyphs"]))
    book["stats"] = stats


def snapshot(data):
    """A copy of a chapter reader's data (reader.chapter_data) that shares no
    object with the book: apply() changes the book's diagrams in place, and a
    data dict that shares them would never see them change. JSON keys are
    strings, as the reader receives them."""
    return json.loads(json.dumps(data))


def chapter_patch(book, ch, old, with_pgn=True, replace=False):
    """(patch, new data): what changed in the chapter reader's data since old
    (reader.chapter_data as the reader holds it). The patch holds the nodes
    added or changed and those removed, every line of the chapter, the marks
    and diagrams of the pages that changed, and the lists that the Review
    view reads. renamed maps a removed node to the node that now holds the
    same printed move, so that the reader keeps its place.

    replace says that book is another reading of the chapter (a first
    reading, or the final one, while the browser app reads the book): its
    node ids say nothing about the old ones, so every old node is removed
    and renamed by its printed move, and the patch carries the reading's
    state (reader.chapter_data "reading")."""
    pgn = pgnout.chapter_pgn(book, ch["index"])[0] if with_pgn else (old or {}).get("pgn", "")
    new = snapshot(reader.chapter_data(book, ch, pgn))
    old = old or {}
    on, nn = old.get("nodes", {}), new["nodes"]
    if replace:
        changed, removed = dict(nn), list(on)
    else:
        changed = {k: v for k, v in nn.items() if on.get(k) != v}
        removed = [k for k in on if k not in nn]
    by_key = {v["key"]: k for k, v in nn.items() if v.get("key")}
    renamed = {k: by_key[on[k]["key"]] for k in removed
               if on[k].get("key") in by_key}
    # a move with no printed token (one the reader added or gave for a gap): the
    # move reached by the same moves from the start of its line
    by_path = {_path(nn, k): k for k, v in nn.items() if not v.get("key") and v.get("san")}
    for k in removed:
        if k not in renamed and not on[k].get("key") and on[k].get("san"):
            hit = by_path.get(_path(on, k))
            if hit:
                renamed[k] = hit
    for k in removed:
        if k not in renamed and on[k].get("parent") is None:
            line = on[k]["line"]
            if replace:
                # the root of a line: the line that now holds its first printed move
                first = next((on[c] for c in on[k].get("children") or []
                              if c in on and on[c].get("key") in by_key), None)
                if first is not None:
                    renamed[k] = nn[by_key[first["key"]]]["parent"]
            elif line in new["lines"]:
                renamed[k] = new["lines"][line]["root"]
    pages = {}
    for p, pg in new["pages"].items():
        if (old.get("pages") or {}).get(p) != pg:
            pages[p] = {"marks": pg["marks"], "diagrams": pg["diagrams"]}
    patch = {"nodes": changed, "removed": removed, "renamed": renamed,
             "lines": new["lines"], "lineOrder": new["lineOrder"], "pages": pages,
             "unattached": new["unattached"], "dismissed": new["dismissed"],
             "corrections": new["corrections"], "symbols": new["symbols"],
             "pgn": new["pgn"]}
    if replace:
        patch["reading"] = new.get("reading")
        patch["pages"] = {p: {"marks": pg["marks"], "diagrams": pg["diagrams"]}
                          for p, pg in new["pages"].items()}
    return patch, new


def _path(nodes, nid):
    """(line, the moves from the start of the line to node nid): a printed move
    by its token key, another by its SAN."""
    line, steps = nodes[nid]["line"], []
    while nid in nodes and nodes[nid].get("parent") is not None:
        n = nodes[nid]
        steps.append(n.get("key") or "san:" + (n.get("san") or ""))
        nid = n["parent"]
    return line, tuple(reversed(steps))


def counts_of(book):
    """Counts for messages: moves by status over the whole book."""
    return Counter({k: v for k, v in book["stats"]["moves"].items()})
