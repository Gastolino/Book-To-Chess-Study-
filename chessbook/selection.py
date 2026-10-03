"""Which pages and board pictures of a book the reader and the extraction use.

A book's selection lives in books/<pdf stem>/selection.json:

    {"version": 1,
     "pages": {"exclude": [[1, 13], [400, 402]]},
     "diagrams": {"exclude": ["p2-1", "p15-2"], "include": ["p28-2"]},
     "note": "Why the selection looks the way it does."}

Page ranges are 1-based and inclusive. Diagram ids are "p{page}-{k}", where
k is the 1-based position of the picture on its page in Stage 1's
diagrams.json. A picture that holds several boards stacked one above another
(Stage 1 lists them under "boards") stands for one diagram per board, with
ids "p{page}-{k}a", "p{page}-{k}b", ... (see expand_boards). A diagram is
used when its page is used and it is either on the include list or not on
the exclude list; the include list therefore overrides the defaults, while
an excluded page excludes every diagram on it.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOOKS_DIR = PROJECT_ROOT / "books"
ID_RE = re.compile(r"^p(\d+)-(\d+)([a-z]?)$")
VERSION = 1

# Kinds of picture that the default selection leaves out.
EXCLUDED_KINDS = ("partial", "illustration", "icon", "front")


def selection_path(pdf_path, books_dir=None):
    """books/<pdf stem>/selection.json (books_dir defaults to <project>/books)."""
    return Path(books_dir or BOOKS_DIR) / Path(pdf_path).stem / "selection.json"


def diagram_ids(diagrams):
    """The id of every record in a Stage 1 diagrams.json list, in its order
    (also of a list that expand_boards made: its boards get letters)."""
    seen, out = Counter(), []
    for d in diagrams:
        sub = d.get("sub") or ""
        if sub in ("", "a"):
            seen[d["page"]] += 1
        out.append(f"p{d['page']}-{seen[d['page']]}{sub}")
    return out


def expand_boards(diagrams):
    """Stage 1's records with each picture of stacked boards replaced by one
    record per board (rect, label and series of that board, "sub" its letter
    and "picture" the id of the picture)."""
    out = []
    for did, d in zip(diagram_ids(diagrams), diagrams):
        boards = d.get("boards") or []
        if len(boards) < 2:
            out.append(d)
            continue
        for j, b in enumerate(boards):
            r = b["rect"]
            w, h = r[2] - r[0], r[3] - r[1]
            px = (d.get("pixels") or [0, 0])
            k = h / max(d["rect"][3] - d["rect"][1], 1e-6)
            rec = {k2: v for k2, v in d.items() if k2 != "boards"}
            rec.update({"rect": r, "label": b.get("label"), "label_repaired": False,
                        "circled": False, "partial": b.get("partial", abs(w / h - 1) > 0.12),
                        "tall": h > 1.3 * w, "series": b.get("series", "other"),
                        "coords": b.get("coords"), "pixels": [px[0], round(px[1] * k)],
                        "sub": "abcdefghijklmnopqrstuvwxyz"[j], "picture": did})
            out.append(rec)
    return out


def id_page(did):
    m = ID_RE.match(did)
    if not m:
        raise ValueError(f"{did!r} is not a diagram id such as 'p201-1'.")
    return int(m.group(1))


def id_key(did):
    """Sort key of a diagram id: page, picture, board."""
    m = ID_RE.match(did)
    return (int(m.group(1)), int(m.group(2)), m.group(3)) if m else (10 ** 9, 0, "")


_id_key = id_key


def board_size(diagrams, first_page=1):
    """The usual printed size of a whole board in points: the median shorter
    side of the square pictures from first_page on (None without any)."""
    sides = [min(d["rect"][2] - d["rect"][0], d["rect"][3] - d["rect"][1])
             for d in diagrams if not d.get("partial") and d["page"] >= first_page]
    return statistics.median(sides) if sides else None


def picture_kinds(diagrams, first_page=1):
    """Sort every picture into one kind, keyed by diagram id.

    board         a square picture of about board size, or smaller when the
                  file letters or rank numbers printed around it show a whole
                  board
    board_plus    not square, but as wide as a whole board and at least as tall:
                  boards stacked in one picture, a board with printed text
                  beneath it, or a board framed by a number or a margin
    partial       part of a board only, such as a corner or a strip of files;
                  also a square picture well below board size around which
                  fewer than seven file letters and rank numbers are printed
    illustration  far larger than a board, such as a drawing across the page
    icon          far smaller than a board, such as an ornament
    front         any picture before first_page (covers and publisher logos)
    """
    B = board_size(diagrams, first_page)
    out = {}
    for did, d in zip(diagram_ids(diagrams), diagrams):
        w, h = d["rect"][2] - d["rect"][0], d["rect"][3] - d["rect"][1]
        if d["page"] < first_page:
            kind = "front"
        elif B is None:
            kind = "partial" if d.get("partial") else "board"
        elif max(w, h) < 0.3 * B:
            kind = "icon"
        elif min(w, h) > 1.8 * B:
            kind = "illustration"
        elif not d.get("partial"):
            files, ranks = (d.get("coords") or [None, None])[:2]
            whole = files is not None and (files >= 7 or ranks >= 7)
            kind = "partial" if (min(w, h) < 0.7 * B and not whole) else "board"
        elif 0.9 * B <= w <= 1.35 * B and 0.9 * B <= h <= 4.2 * B:
            kind = "board_plus"
        elif w > 1.35 * B and h > 1.35 * B:
            kind = "illustration"
        else:
            kind = "partial"
        out[did] = kind
    return out


def _plural(n, one, many=None):
    return f"{n} {one if n == 1 else many or one + 's'}"


def default_selection(structure, diagrams):
    """The selection used until the reader saves one: front matter pages and
    the pictures on them are left out, and so are pictures that show part of a
    board only, illustrations and ornaments."""
    chapters = structure.get("chapters") or []
    first = chapters[0]["start"] if chapters else 1
    front_end = int(structure.get("front_matter_end") or 0)
    kinds = picture_kinds(diagrams, first)
    exclude = [did for did, k in kinds.items() if k in EXCLUDED_KINDS]
    counts = Counter(kinds[did] for did in exclude)
    parts = []
    if front_end >= 1:
        parts.append(f"It leaves out pages 1 to {front_end}, which come before the first "
                     "chapter" + (f", together with {_plural(counts['front'], 'picture')} on "
                                  "those pages." if counts["front"] else "."))
    if counts["partial"]:
        parts.append(f"It {'also ' if parts else ''}leaves out "
                     f"{_plural(counts['partial'], 'picture')} that show only part of a board.")
    if counts["illustration"] or counts["icon"]:
        parts.append(f"It {'also ' if parts else ''}leaves out "
                     f"{_plural(counts['illustration'] + counts['icon'], 'picture')} that are "
                     "drawings or ornaments rather than boards.")
    note = " ".join(["The program made this selection."] + parts
                    + ["Every other page and picture is included."])
    return normalise({"version": VERSION,
                      "pages": {"exclude": [[1, front_end]] if front_end >= 1 else []},
                      "diagrams": {"exclude": exclude, "include": []},
                      "note": note})


def _ranges(items):
    out = []
    for it in items or []:
        if isinstance(it, bool):
            raise ValueError(f"{it!r} is not a page range.")
        if isinstance(it, int):
            a, b = it, it
        elif isinstance(it, str):
            m = re.fullmatch(r"\s*(\d+)\s*(?:[-–]\s*(\d+)\s*)?", it)
            if not m:
                raise ValueError(f"{it!r} is not a page range.")
            a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        elif isinstance(it, (list, tuple)) and 1 <= len(it) <= 2:
            a, b = int(it[0]), int(it[-1])
        else:
            raise ValueError(f"{it!r} is not a page range.")
        if a > b:
            a, b = b, a
        if a < 1:
            raise ValueError(f"Page {a} does not exist; pages start at 1.")
        out.append([a, b])
    out.sort()
    merged = []
    for a, b in out:
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def _ids(items):
    out = set()
    for it in items or []:
        if not isinstance(it, str) or not ID_RE.match(it.strip()):
            raise ValueError(f"{it!r} is not a diagram id such as 'p201-1'.")
        out.add(it.strip())
    return sorted(out, key=_id_key)


def normalise(data):
    """Check a selection dict and return it in canonical form (merged, sorted
    page ranges; sorted unique diagram ids). Missing parts stay missing."""
    if not isinstance(data, dict):
        raise ValueError("A selection must be a JSON object.")
    out = {"version": int(data.get("version", VERSION))}
    if "pages" in data:
        pages = data["pages"] or {}
        if isinstance(pages, list):
            pages = {"exclude": pages}
        out["pages"] = {"exclude": _ranges(pages.get("exclude"))}
    if "diagrams" in data:
        dg = data["diagrams"] or {}
        out["diagrams"] = {}
        for key in ("exclude", "include"):
            if key in dg:
                out["diagrams"][key] = _ids(dg[key])
    if "note" in data:
        out["note"] = str(data["note"] or "")
    return out


class Selection:
    """The pages and diagrams in use for one book.

    Parts missing from a saved file fall back to the defaults, so a file that
    holds only {"diagrams": {"include": [...]}} still leaves out the front
    matter and the partial boards.
    """

    def __init__(self, data=None, defaults=None, path=None):
        d = normalise(defaults) if defaults else {}
        s = normalise(data) if data else {}
        self.path = Path(path) if path else None
        self.from_file = bool(data)
        self.page_exclude = s.get("pages", d.get("pages", {"exclude": []}))["exclude"]
        sd, dd = s.get("diagrams", {}), d.get("diagrams", {})
        self.diagram_exclude = set(sd.get("exclude", dd.get("exclude", [])))
        self.diagram_include = set(sd.get("include", dd.get("include", [])))
        self.note = s.get("note", d.get("note", ""))

    def page_selected(self, page):
        return not any(a <= page <= b for a, b in self.page_exclude)

    def diagram_selected(self, did):
        if not self.page_selected(id_page(did)):
            return False
        if did in self.diagram_include:
            return True
        m = ID_RE.match(did)
        if m and m.group(3) and f"p{m.group(1)}-{m.group(2)}" in self.diagram_exclude:
            return False                # the whole picture of stacked boards is left out
        return did not in self.diagram_exclude

    def selected_diagrams(self, ids):
        return [did for did in ids if self.diagram_selected(did)]

    def exclude_pages(self, first, last=None):
        self.page_exclude = _ranges(self.page_exclude + [[first, last or first]])

    def include_pages(self, first, last=None):
        last = last or first
        keep = []
        for a, b in self.page_exclude:
            if b < first or a > last:
                keep.append([a, b])
                continue
            if a < first:
                keep.append([a, first - 1])
            if b > last:
                keep.append([last + 1, b])
        self.page_exclude = _ranges(keep)

    def set_diagram(self, did, selected):
        id_page(did)
        if selected:
            self.diagram_exclude.discard(did)
            self.diagram_include.add(did)
        else:
            self.diagram_include.discard(did)
            self.diagram_exclude.add(did)

    def to_dict(self):
        return {"version": VERSION,
                "pages": {"exclude": [list(r) for r in self.page_exclude]},
                "diagrams": {"exclude": sorted(self.diagram_exclude, key=_id_key),
                             "include": sorted(self.diagram_include, key=_id_key)},
                "note": self.note}

    def save(self, path=None):
        path = path or self.path
        if path is None:
            raise ValueError("No path to save the selection to.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        self.path = path
        return path


def load_selection(pdf_path, structure, diagrams, books_dir=None):
    """The book's saved selection, or the default one when no file exists."""
    path = selection_path(pdf_path, books_dir)
    defaults = default_selection(structure, diagrams)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return Selection(data, defaults, path)
    return Selection(None, defaults, path)


_FENCE_RE = re.compile(r"```[ \t]*(?:json|JSON|javascript|js)?[ \t]*\r?\n?(.*?)```", re.S)
_KEYS = {"pages", "diagrams", "version"}


def _repair(text):
    t = (text.replace("“", '"').replace("”", '"').replace("„", '"')
         .replace("″", '"').replace(" ", " "))
    return re.sub(r",\s*([}\]])", r"\1", t)


def _objects(text):
    dec = json.JSONDecoder()
    for variant in dict.fromkeys((text, _repair(text))):
        i = variant.find("{")
        while i != -1:
            try:
                obj, end = dec.raw_decode(variant, i)
            except ValueError:
                i = variant.find("{", i + 1)
                continue
            yield obj
            i = variant.find("{", end)


def parse_selection_text(text):
    """Read a selection pasted from the reader's "Copy selection" button, even
    when it sits inside a chat message with prose or a ```json fence around it.
    Returns the selection in canonical form; raises ValueError when the text
    holds no selection."""
    chunks = [m.group(1) for m in _FENCE_RE.finditer(text)] + [text]
    for chunk in chunks:
        for obj in _objects(chunk):
            if isinstance(obj, dict) and _KEYS & obj.keys():
                return normalise(obj)
    raise ValueError("The text holds no selection: no JSON object with "
                     "\"pages\" or \"diagrams\" was found.")
