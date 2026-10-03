"""Stage 1: inspect the book.

Usage:  python stage1_inspect.py [primer.pdf]

Writes output/stage1/inspect.html, 300 dpi renders of sample pages with every
board picture outlined, and output/stage1/diagrams.json for Stage 2.

This PDF was made with Adobe ClearScan, which replaced the scanned lettering
with redrawn type but left each chess diagram as a separate grey-scale picture.
The script therefore finds boards through the embedded pictures and finds
diagram numbers as short numeric labels printed just above a picture.
"""
import base64
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

PDF = Path(sys.argv[1] if len(sys.argv) > 1 else "primer.pdf")
OUT = Path("output/stage1")
DPI = 300
SAMPLES = [21, 51, 79, 201, 250, 301, 383]  # printed-page index + 1; extra evenly spaced pages are added

# A diagram label is a number with an optional letter ("14", "14a"). OCR may
# read 1 as l or I, and 8 as S or B.
LABEL_RE = re.compile(r"^[0-9lISB]{1,3}[a-d]?$")
DIGIT_FIX = str.maketrans({"l": "1", "I": "1", "S": "8", "B": "8"})
# "Diagram 14" in the running text, allowing for OCR misspellings.
REF_RE = re.compile(r"\b[DO][il1]a?gr[ae](?:m|rn|in)s?\s+([0-9lISB]{1,3}[a-d]?)\b")
CIRCLE_RE = re.compile(r"^\(?(?:@|®|©|G\)|CD|0)")
MAX_GAP = 90  # points between a label and the top of its picture


def text_lines(page):
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 0:
            for line in b["lines"]:
                yield "".join(s["text"] for s in line["spans"]).strip(), pymupdf.Rect(line["bbox"])


def board_pictures(page):
    rects = []
    for img in page.get_images(full=True):
        for r in page.get_image_rects(img[0]):
            r = r & page.rect
            if r.width > 20 and r.height > 20:
                rects.append((r, img[2], img[3]))
    # Reading order: left column top to bottom, then right column.
    mid = page.rect.width / 2
    return sorted(rects, key=lambda t: ((t[0].x0 + t[0].x1) / 2 > mid, t[0].y0))


def between_boards(r, pic):
    """True for a label printed between two boards stacked in one tall picture."""
    cx = (r.x0 + r.x1) / 2
    return (pic.height > 1.3 * pic.width and pic.x0 + 0.3 * pic.width < cx < pic.x1 - 0.3 * pic.width
            and pic.y0 + 0.2 * pic.height < r.y0)


def label_for(pic, labels, used):
    """Nearest unused label sitting above the picture and over its middle third."""
    best = None
    for k, (text, r) in enumerate(labels):
        if k in used:
            continue
        gap = pic.y0 - r.y1
        cx = (r.x0 + r.x1) / 2
        if -2 <= gap <= MAX_GAP and pic.x0 - 25 <= cx <= pic.x1 + 25:
            if best is None or gap < best[0]:
                best = (gap, k)
    return best[1] if best else None


def label_order(s):
    """Sort key for labels such as 14, 14a and 15."""
    return int(re.sub(r"\D", "", s) or 0), s


def main_series(labelled):
    """Indices of the labels that belong to the book's main numbered series.

    The book numbers its teaching diagrams in one series running through the
    whole book; exercises and model games restart at 1 inside it. Walking
    page by page, a label joins the main series when it is a little above the
    last main number, and otherwise belongs to a shorter series.
    """
    order = sorted(range(len(labelled)),
                   key=lambda k: (labelled[k]["page"], label_order(labelled[k]["label"])))
    last, out = (0, ""), set()
    for k in order:
        v = label_order(labelled[k]["label"])
        # The series must open at 1; this skips the page numbers in the contents.
        if last < v and v[0] - last[0] <= (12 if out else 1):
            out.add(k)
            last = v
    return out


def series_name(d):
    if d["label"]:
        return "main" if d["series"] == "main" else "exercise or game"
    return "circled" if d["circled"] else "none"


def main():
    if not PDF.exists():
        sys.exit(f"Cannot find {PDF}. Put the book in this folder or pass its path.")
    OUT.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(PDF)
    n = doc.page_count

    pages, diagrams, numbers, refs = [], [], [], Counter()
    for i, page in enumerate(doc):
        lines = list(text_lines(page))
        chars = sum(len(t) for t, _ in lines)
        pics = board_pictures(page)
        # Skip the running head (page number) in the top 45 points.
        # OCR sometimes splits a number with a space ("1 15" for 115). Lines that
        # touch a picture are its rank and file letters, and lines in the top
        # 42 points are the running head, so both are left out.
        labels = [(t.replace(" ", ""), r) for t, r in lines
                  if LABEL_RE.match(t.replace(" ", "")) and (r.y0 + r.y1) / 2 > 42
                  and not any(r.intersects(p + (-12, -4, 12, 4)) and not between_boards(r, p)
                              for p, _, _ in pics)]
        for t, r in labels:
            numbers.append({"page": i + 1, "label": t.translate(DIGIT_FIX),
                            "repaired": t != t.translate(DIGIT_FIX)})
        used = set()
        for pic, w, h in pics:
            k = label_for(pic, labels, used)
            raw = labels[k][0] if k is not None else None
            if k is not None:
                used.add(k)
            # A circled number beside the board comes out of OCR as a symbol.
            circled = raw is None and any(
                CIRCLE_RE.match(t) and abs(r.y0 - pic.y0) < 25
                and ((r.x0 < pic.x0 - 5 and r.x1 < pic.x0 + 25)
                     or (r.x1 > pic.x1 + 5 and r.x0 > pic.x1 - 25))
                for t, r in lines)
            diagrams.append({
                "page": i + 1,
                "rect": [round(v, 1) for v in pic],
                "pixels": [w, h],
                "label": raw.translate(DIGIT_FIX) if raw else None,
                "label_repaired": bool(raw) and raw != raw.translate(DIGIT_FIX),
                "circled": circled,
                "partial": abs(pic.width / pic.height - 1) > 0.12,
                "tall": pic.height > 1.3 * pic.width,
            })
        for m in REF_RE.finditer(page.get_text()):
            refs[m.group(1).translate(DIGIT_FIX)] += 1
        pages.append({"page": i + 1, "chars": chars, "pictures": len(pics)})

    (OUT / "diagrams.json").write_text(json.dumps(diagrams, indent=1))

    # Sample renders with each picture outlined in red and its label written beside it.
    extra = list(range(1, n + 1, max(1, n // 6)))
    samples = sorted(set(SAMPLES + extra) & set(range(1, n + 1)))
    thumbs = {}
    for p in samples:
        page = doc[p - 1]
        for dgm in (x for x in diagrams if x["page"] == p):
            r = pymupdf.Rect(dgm["rect"])
            page.draw_rect(r, color=(1, 0, 0), width=1.2)
            page.insert_text((r.x0, r.y1 + 9), f"[{dgm['label'] or '?'}]", fontsize=8,
                             color=(1, 0, 0))
        pix = page.get_pixmap(dpi=DPI)
        pix.save(OUT / f"page_{p:04d}.png")
        # A smaller JPEG copy goes inside the HTML so that the page opens on its own.
        thumbs[p] = base64.b64encode(page.get_pixmap(dpi=110).tobytes("jpg", jpg_quality=80)).decode()

    labelled = [d for d in diagrams if d["label"]]
    main_ids = main_series(numbers)
    for k, x in enumerate(numbers):
        x["series"] = "main" if k in main_ids else "other"
    main_keys = {(x["page"], x["label"]) for x in numbers if x["series"] == "main"}
    for d in diagrams:
        d["series"] = "main" if (d["page"], d["label"]) in main_keys else "other"
    (OUT / "diagrams.json").write_text(json.dumps(diagrams, indent=1))
    (OUT / "numbers.json").write_text(json.dumps(numbers, indent=1))
    main_nums = [label_order(x["label"])[0] for x in numbers if x["series"] == "main"]
    main_gaps = sorted(set(range(1, max(main_nums) + 1)) - set(main_nums))
    others = [x for x in numbers if x["series"] == "other"]
    tall = [d for d in diagrams if d["tall"]]
    circled = [d for d in diagrams if d.get("circled")]
    unlabelled = [d for d in diagrams if not d["label"] and not d.get("circled")]
    partial = [d for d in diagrams if d["partial"]]
    text_pages = sum(p["chars"] > 0 for p in pages)
    blank = [p["page"] for p in pages if p["chars"] == 0]

    e = html.escape
    out = [
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>Stage 1 Inspection</title><style>"
        ":root{--bg:#fff;--fg:#222;--mut:#666;--line:#bbb;--warn:#fff1c2;--bad:#fdd}"
        "@media (prefers-color-scheme:dark){:root{--bg:#1b1b1b;--fg:#ddd;--mut:#999;"
        "--line:#555;--warn:#4a3d10;--bad:#4a1c1c}}"
        "body{font:16px/1.55 Georgia,serif;max-width:1100px;margin:auto;padding:16px;"
        "background:var(--bg);color:var(--fg)}table{border-collapse:collapse;font-size:14px}"
        "td,th{border:1px solid var(--line);padding:2px 8px}.warn{background:var(--warn)}"
        ".bad{background:var(--bad)}img{max-width:100%;border:1px solid var(--line)}"
        "figure{display:inline-block;width:250px;margin:6px;vertical-align:top}"
        ".scroll{max-height:480px;overflow:auto}.nums{font-size:14px}</style>",
        f"<h1>Stage 1: {e(PDF.name)}</h1>",
        "<h2>What the pages are</h2>",
        f"<p>The PDF has <b>{n}</b> pages. Adobe Acrobat's ClearScan built it from a scan: "
        "Acrobat recognised the letters and redrew them as type, so the text you see on screen "
        "is the OCR result itself and no longer the photographed page. The chess diagrams it "
        f"left as photographs. I found <b>{len(diagrams)}</b> pictures; all but the cover and "
        "the publisher's logo show boards or parts of boards. "
        f"<b>{text_pages}</b> pages carry text; pages {e(', '.join(map(str, blank)))} carry "
        "none.</p>",
        "<h2>How the book numbers its diagrams</h2>",
        "<p>The book prints a bare number, such as <i>14</i> or <i>14a</i>, above a board. "
        "It does not print the word &ldquo;Diagram&rdquo; there, so I looked for a short "
        f"number just above each picture. I matched <b>{len(labelled)}</b> pictures that "
        "way.</p>",
        f"<p>The book's teaching diagrams form one series, numbered 1 to {max(main_nums)}. "
        f"I found <b>{len(main_nums)}</b> of them, counting lettered ones such as 14a separately. These numbers in that range are missing: "
        f"<b>{e(', '.join(map(str, main_gaps))) or 'none'}</b>. A missing number means either "
        "that the book skips it or that OCR misread it; the table below lets you check.</p>",
        f"<p><b>{len(others)}</b> further numbers stand on lines of their own. Most belong to "
        "shorter series that start again at 1: the exercises in each chapter, the collections "
        "of model games and their solutions. "
        "A number alone therefore does not identify a diagram, so from Stage 2 onward I name "
        "every board by its page as well.</p>",
        f"<p><b>{len(circled)}</b> pictures, at the end of the book, carry a circled number "
        "beside the board instead of a number above it. OCR read those circles as symbols "
        "such as &ldquo;@&rdquo; and &ldquo;&reg;&rdquo;, so their numbers will have to be "
        "taken from their order on the page.</p>",
        f"<p><b>{len(unlabelled)}</b> pictures have no number at all. Most of them show a "
        "position reached in the middle of a game, which the book prints without a number; "
        "the cover and the publisher's logo are also among them. "
        f"<b>{len(partial)}</b> pictures show only part of a board (a corner or a strip of "
        "files), as in the exercises on PDF page 51 and the <i>en passant</i> strips on PDF "
        "page 21.</p>",
        "<h2>Sample pages at 300 dpi</h2><p>Each board picture is outlined in red, with the "
        "number I matched to it written underneath; <b>[?]</b> means no number. Clicking a page "
        "opens the full 300 dpi image when this page sits beside the output folder.</p>",
    ]
    for p in samples:
        f = f"page_{p:04d}.png"
        out.append(f"<figure><a href='{f}'><img src='data:image/jpeg;base64,{thumbs[p]}'></a>"
                   f"<figcaption>PDF page {p}</figcaption></figure>")
    out.append("<h2>Every board picture</h2><p>Yellow rows show part of a board only; red rows "
               "have no number. A star marks a number repaired from an OCR misreading.</p>"
               "<div class=scroll><table><tr><th>PDF page</th><th>Number</th><th>Series</th>"
               "<th>Pixels</th><th>Whole board?</th></tr>")
    for d in diagrams:
        cls = "bad" if not d["label"] and not d["circled"] else "warn" if d["partial"] else ""
        star = "*" if d["label_repaired"] else ""
        out.append(f"<tr class='{cls}'><td>{d['page']}</td><td>{e(d['label'] or '')}{star}</td>"
                   f"<td>{series_name(d)}</td><td>{d['pixels'][0]}&times;{d['pixels'][1]}</td>"
                   f"<td>{'no' if d['partial'] else 'yes'}</td></tr>")
    out.append("</table></div><h2>Every diagram number in the OCR text</h2>"
               "<p>The main series, each number followed by the PDF page on which it is "
               "printed. A star marks a number repaired from an OCR misreading.</p><p class=nums>")
    out.append(" &middot; ".join(
        f"<b>{e(x['label'])}</b>{'*' if x['repaired'] else ''}&nbsp;p{x['page']}"
        for x in numbers if x["series"] == "main"))
    out.append("</p><p>The shorter series (exercises, model games and solutions), grouped by "
               "PDF page. Some entries here are stray numbers from the text, such as a move "
               "number standing alone on a line; Stage 2 discards any that sit by no board.</p>"
               "<div class=scroll><table><tr><th>PDF page</th><th>Numbers</th></tr>")
    by_page = {}
    for x in others:
        by_page.setdefault(x["page"], []).append(x["label"])
    for p, labs in by_page.items():
        out.append(f"<tr><td>{p}</td><td>{e(', '.join(labs))}</td></tr>")
    out.append("</table></div><h2>&ldquo;Diagram N&rdquo; in the running text</h2>"
               f"<p>The text refers to <b>{len(refs)}</b> diagrams by name: "
               f"{e(', '.join(sorted(refs, key=label_order)))}"
               "</p>")
    (OUT / "inspect.html").write_text("\n".join(out), encoding="utf-8")
    print(f"{n} pages, {len(diagrams)} board pictures, {len(labelled)} numbered, "
          f"{len(unlabelled)} unnumbered, {len(circled)} circled, {len(partial)} partial")
    print(f"Main series 1-{max(main_nums)}: {len(main_nums)} found, missing {main_gaps}")
    print(f"Open {OUT / 'inspect.html'}")


if __name__ == "__main__":
    main()
