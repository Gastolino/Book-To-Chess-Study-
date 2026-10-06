"""Tests for chessbook.selection on the first test book, The Soviet Chess Primer."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402

from chessbook import pdftext as pt  # noqa: E402
from chessbook import selection as sl  # noqa: E402

PDF = ROOT / "primer.pdf"
DIAGRAMS = ROOT / "output" / "primer" / "stage1" / "diagrams.json"
pytestmark = pytest.mark.skipif(not PDF.exists(), reason="primer.pdf is not in the project folder")


@pytest.fixture(scope="module")
def diagrams():
    if not DIAGRAMS.exists():
        subprocess.run([sys.executable, "stage1_inspect.py", "primer.pdf"], cwd=ROOT, check=True)
    return json.loads(DIAGRAMS.read_text())


@pytest.fixture(scope="module")
def structure():
    return pt.book_structure(pymupdf.open(PDF))


@pytest.fixture(scope="module")
def defaults(structure, diagrams):
    return sl.default_selection(structure, diagrams)


def test_diagram_ids(diagrams):
    ids = sl.diagram_ids(diagrams)
    assert len(ids) == len(set(ids)) == len(diagrams)
    assert ids[0] == "p2-1"
    assert [i for i in ids if i.startswith("p201-")] == ["p201-1", "p201-2", "p201-3"]


def test_defaults_include_front_matter(defaults, diagrams):
    """The front matter is read like the rest of the book: every page is in,
    and its pictures are sorted by the rules of the chapters' pictures."""
    assert defaults["version"] == 1
    assert defaults["pages"]["exclude"] == []
    sel = sl.Selection(None, defaults)
    assert all(sel.page_selected(p) for p in range(1, 403))
    assert "p2-1" in defaults["diagrams"]["exclude"]          # the publisher's logo
    assert not sel.diagram_selected("p2-1")
    assert sl.picture_kinds(diagrams, 14)["p2-1"] == "partial"     # no whole board
    assert "pages 1 to" not in defaults["note"]
    # the reader's own choice still leaves the front matter out
    mine = sl.Selection({"pages": {"exclude": [[1, 13]]}}, defaults)
    assert not any(mine.page_selected(p) for p in range(1, 14)) and mine.page_selected(14)


def test_defaults_exclude_partial_boards(defaults, diagrams, structure):
    sel = sl.Selection(None, defaults)
    kinds = sl.picture_kinds(diagrams, structure["chapters"][0]["start"])
    ids = sl.diagram_ids(diagrams)
    partial = [i for i, d in zip(ids, diagrams) if d["partial"] and kinds[i] == "partial"]
    assert len(partial) > 40
    assert not any(sel.diagram_selected(i) for i in partial)
    # A strip of piece icons, a three-rank strip and a half board.
    for did in ("p15-2", "p28-1", "p53-1", "p64-1"):
        assert kinds[did] == "partial", did
        assert not sel.diagram_selected(did), did
    # Drawings across the page are not boards.
    assert kinds["p163-1"] == "illustration" and not sel.diagram_selected("p163-1")
    # Not square, yet holding whole boards: stacked boards, a board with text
    # printed beneath it, and a composition framed by its circled number.
    for did in ("p159-2", "p79-1", "p192-1", "p379-4"):
        assert kinds[did] == "board_plus", did
        assert sel.diagram_selected(did), did
    # Every ordinary board on a chapter page is in.
    boards = [i for i, d in zip(ids, diagrams) if not d["partial"] and d["page"] >= 14
              and kinds[i] == "board"]
    assert len(boards) > 700 and all(sel.diagram_selected(i) for i in boards)
    assert sel.diagram_selected("p201-1")


def test_include_overrides_defaults(defaults):
    sel = sl.Selection({"diagrams": {"include": ["p15-2", "p2-1"]}}, defaults)
    assert sel.diagram_selected("p15-2")                       # include beats default exclude
    assert sel.diagram_selected("p2-1")
    assert sel.page_selected(5)                                # pages fall back to defaults
    sel = sl.Selection({"pages": {"exclude": [[1, 13]]}, "diagrams": {"include": ["p2-1"]}}, defaults)
    assert not sel.diagram_selected("p2-1")                    # its page is excluded
    assert not sel.diagram_selected("p28-1")                   # other defaults still apply
    sel = sl.Selection({"pages": {"exclude": [[200, 201]]},
                        "diagrams": {"exclude": ["p250-1"], "include": ["p201-1"]}}, defaults)
    assert not sel.diagram_selected("p201-1")                  # excluded page wins
    assert not sel.diagram_selected("p250-1")
    assert sel.diagram_selected("p250-2")
    # Each part present in the file replaces that part of the defaults.
    assert sel.page_selected(5)
    assert sel.diagram_selected("p28-1")


def test_editing_helpers(defaults):
    sel = sl.Selection(None, defaults)
    sel.exclude_pages(398, 402)
    sel.exclude_pages(14)
    assert sel.to_dict()["pages"]["exclude"] == [[14, 14], [398, 402]]
    sel.include_pages(400)
    assert sel.to_dict()["pages"]["exclude"] == [[14, 14], [398, 399], [401, 402]]
    sel.set_diagram("p15-2", True)
    sel.set_diagram("p201-2", False)
    assert sel.diagram_selected("p15-2") and not sel.diagram_selected("p201-2")


def test_load_and_save(tmp_path, structure, diagrams):
    sel = sl.load_selection(PDF, structure, diagrams, books_dir=tmp_path)
    assert not sel.from_file
    assert sel.path == tmp_path / "primer" / "selection.json"
    assert sl.selection_path(PDF) == ROOT / "books" / "primer" / "selection.json"
    sel.set_diagram("p15-2", True)
    sel.note = "Checked by hand."
    path = sel.save()
    again = sl.load_selection(PDF, structure, diagrams, books_dir=tmp_path)
    assert again.from_file and again.to_dict() == sel.to_dict()
    data = json.loads(path.read_text())
    assert set(data) == {"version", "pages", "diagrams", "note"}
    assert data["diagrams"]["include"] == ["p15-2"]


def test_parse_selection_text_fenced(defaults):
    blob = json.dumps({"version": 1, "pages": {"exclude": [[1, 13], [400, 402]]},
                       "diagrams": {"exclude": ["p15-2"], "include": ["p28-1"]},
                       "note": "Mine."}, indent=2)
    text = f"Here is my selection for the Primer:\n\n```json\n{blob}\n```\n\nPlease use it."
    got = sl.parse_selection_text(text)
    assert got == {"version": 1, "pages": {"exclude": [[1, 13], [400, 402]]},
                   "diagrams": {"exclude": ["p15-2"], "include": ["p28-1"]}, "note": "Mine."}
    # The result feeds straight into a Selection.
    assert sl.Selection(got, defaults).diagram_selected("p28-1")


def test_parse_selection_text_tolerance():
    plain = 'I copied this: {"pages": {"exclude": [[5, 3], [1, 2]]}, "diagrams": {"exclude": []}} ok'
    assert sl.parse_selection_text(plain)["pages"]["exclude"] == [[1, 5]]
    smart = 'Selection: {“pages”: {“exclude”: [[1, 13],]}, “diagrams”: {“include”: [“p5-1”]}}'
    got = sl.parse_selection_text(smart)
    assert got["pages"]["exclude"] == [[1, 13]] and got["diagrams"]["include"] == ["p5-1"]
    nested = 'noise {"a": 1} then ```\n{"version": 1, "diagrams": {"exclude": ["p9-2", "p9-1"]}}\n```'
    assert sl.parse_selection_text(nested)["diagrams"]["exclude"] == ["p9-1", "p9-2"]
    with pytest.raises(ValueError):
        sl.parse_selection_text("There is no selection in this message.")
    with pytest.raises(ValueError):
        sl.parse_selection_text('{"diagrams": {"exclude": ["page 9"]}}')
