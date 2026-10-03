"""Stage 1: inspect a chess book PDF.

Usage:  python stage1_inspect.py BOOK.pdf

Writes output/<book>/stage1/inspect.html, 300 dpi renders of sample pages with
every board picture outlined, and two JSON files for Stage 2: diagrams.json
(one record per embedded board picture) and numbers.json (every diagram
number found in the text).

Chess books reach us as PDFs of three kinds, and a single book can mix them:
  scan      each page is one photograph, usually with an invisible OCR layer;
  pictures  the text is real type (typeset, or redrawn from a scan by Acrobat
            ClearScan) and each diagram is a separate embedded picture;
  text      typeset pages whose diagrams are drawn from vector shapes or a
            chess font, with no pictures at all.
Stage 2 cuts boards out of embedded pictures where they exist and otherwise
searches the rendered page for them.
"""
import argparse
import base64
import html
import json
import re
from collections import Counter
from pathlib import Path

import pymupdf

DPI = 300
MAX_SAMPLES = 12

# OCR reads 1 as l or I, and 8 as S or B, inside numbers.
DIGIT_FIX = str.maketrans({"l": "1", "I": "1", "S": "8", "B": "8"})
NUM = r"[0-9lISB]{1,3}(?:[.\-][0-9lISB]{1,3})?[a-d]?"
# A diagram label standing on its own line: a bare number ("14", "14a",
# "3.12") or a number after a caption word, in several languages and with
# common OCR misspellings ("Dlagram", "Diagrarn").
CAPTION = (r"(?:[DO][il1]a?gr[ae](?:m|rn|in)(?:m|a|e)?|Diag\.|Dia\.|Fig(?:ure|\.)?|"
           r"Pos(?:ition|\.)|No\.|Nr\.|#)")
LABEL_RE = re.compile(rf"^(?:{CAPTION}\s*)?({NUM})$", re.I)
# "Diagram 14" or "see Diagram 14" anywhere in the running text.
REF_RE = re.compile(rf"\b[DO][il1]a?gr[ae](?:m|rn|in)(?:m|a|e|s)?\s+({NUM})\b", re.I)
# A circled number beside a board: real circled digits, digits in brackets,
# or the symbols OCR makes of a circle.
CIRCLE_RE = re.compile(r"^(?:[①-⑳⓵-⓾]|\(\d{1,3}\)|\(?(?:@|®|©|G\)|CD))")
RESULTS = {"1-0", "0-1", "l-0", "0-l"}  # game results, which look like "3-12" labels
MAX_GAP = 90       # points between a label and the edge of its picture
FULL_PAGE = 0.85   # a picture covering this share of the page is a page scan


def text_lines(page):
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 0:
            for line in b["lines"]:
                yield "".join(s["text"] for s in line["spans"]).strip(), pymupdf.Rect(line["bbox"])


def page_pictures(page):
    """Return (page_scan_cover, board_pictures) for one page.

    A picture covering most of the page is a photograph of the whole page;
    smaller pictures are candidate boards, sorted into reading order.
    """
    area = abs(page.rect)
    cover, boards = 0.0, []
    for img in page.get_images(full=True):
        for r in page.get_image_rects(img[0]):
            r = r & page.rect
            share = abs(r) / area
            if share >= FULL_PAGE:
                cover = max(cover, share)
            elif r.width > 20 and r.height > 20:
                boards.append((r, img[2], img[3]))
    # Left column top to bottom, then right column. Stage 2 reorders boards
    # that sit side by side in one row.
    mid = page.rect.width / 2
    boards.sort(key=lambda t: ((t[0].x0 + t[0].x1) / 2 > mid, t[0].y0))
    return cover, boards


def page_kind(chars, cover, boards, invisible):
    if cover:
        return "scan"
    if boards:
        return "pictures"
    if chars:
        return "text"
    return "blank"


def between_boards(r, pic):
    """True for a label printed between two boards stacked in one tall picture."""
    cx = (r.x0 + r.x1) / 2
    return (pic.height > 1.3 * pic.width
            and pic.x0 + 0.3 * pic.width < cx < pic.x1 - 0.3 * pic.width
            and pic.y0 + 0.2 * pic.height < r.y0)


def label_for(pic, labels, used):
    """The nearest unused label above the picture, or failing that just below it."""
    best = None
    for k, (_, r) in enumerate(labels):
        if k in used:
            continue
        cx = (r.x0 + r.x1) / 2
        if not pic.x0 - 25 <= cx <= pic.x1 + 25:
            continue
        above, below = pic.y0 - r.y1, r.y0 - pic.y1
        # Books that caption below the board put the label close under it, so a
        # label below counts only within a third of the distance allowed above.
        if -2 <= above <= MAX_GAP:
            score = above
        elif -2 <= below <= MAX_GAP / 3:
            score = MAX_GAP + below
        else:
            continue
        if best is None or score < best[0]:
            best = (score, k)
    return best[1] if best else None


def label_order(s):
    """Sort key for labels such as 14, 14a, 15 and 3.12."""
    return tuple(int(x) for x in re.findall(r"\d+", s)) or (0,), s


def follows(prev, cur):
    """True when label cur can come next after prev in one numbered series."""
    if prev is None:
        return cur[0] in ((1,), (1, 1))
    (p, ps), (c, cs) = prev, cur
    if len(p) != len(c) or (p, ps) >= (c, cs):
        return False
    if len(c) == 1:
        return c[0] - p[0] <= 12
    # Chapter-numbered labels such as 3.12: the same chapter a little further
    # on, or the next chapter starting again near 1.
    return (c[0] == p[0] and c[1] - p[1] <= 12) or (c[0] == p[0] + 1 and c[1] <= 2)


def main_series(numbers):
    """Indices of the labels that belong to the book's main numbered series.

    Most books number their diagrams in one series, while exercises and model
    games restart at 1 inside it. Walking page by page, a label joins the main
    series when it comes a little after the last main label; any other label
    belongs to a shorter series or is a stray number from the text.
    """
    order = sorted(range(len(numbers)),
                   key=lambda k: (numbers[k]["page"], label_order(numbers[k]["label"])))
    last, out = None, set()
    for k in order:
        v = label_order(numbers[k]["label"])
        if follows(last, v):
            out.add(k)
            last = v
    return out


def series_name(d):
    if d["label"]:
        return "main" if d["series"] == "main" else "other"
    return "circled" if d["circled"] else "none"


def pick_samples(n, pages, diagrams):
    """Pages that show the reader each kind of thing the report counts."""
    want = []
    def first(pred):
        for d in diagrams:
            if pred(d):
                return d["page"]
    by_count = Counter(d["page"] for d in diagrams)
    want += [first(lambda d: True), by_count.most_common(1)[0][0] if by_count else None]
    want += [first(lambda d: d[k]) for k in ("partial", "tall", "circled")]
    want += [first(lambda d: not d["label"] and not d["circled"] and d["page"] > 3)]
    want += [next((p["page"] for p in pages if p["kind"] == "scan"), None)]
    want += list(range(1, n + 1, max(1, n // 5)))
    out = []
    for p in want:
        if p and p not in out:
            out.append(p)
    return sorted(out[:MAX_SAMPLES])


def plural(k, one, many=None):
    return f"<b>{k}</b> {one if k == 1 else many or one + 's'}"


def main():
    ap = argparse.ArgumentParser(description="Inspect a chess book PDF (Stage 1).")
    ap.add_argument("pdf", type=Path)
    args = ap.parse_args()
    pdf = args.pdf
    if not pdf.exists():
        raise SystemExit(f"Cannot find {pdf}.")
    out_dir = Path("output") / pdf.stem / "stage1"
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    n = doc.page_count
    producer = " ".join(filter(None, (doc.metadata.get("creator"), doc.metadata.get("producer"))))

    pages, diagrams, numbers, refs = [], [], [], Counter()
    for i, page in enumerate(doc):
        lines = list(text_lines(page))
        chars = sum(len(t) for t, _ in lines)
        cover, pics = page_pictures(page)
        invisible = any(t.get("type") == 3 for t in page.get_texttrace())
        head = page.rect.height * 0.06  # running head with the page number
        # OCR sometimes splits a number with a space ("1 15" for 115). Lines that
        # touch a picture are its rank and file letters, so they are left out.
        labels = []
        for t, r in lines:
            m = LABEL_RE.match(t.replace(" ", "") if len(t) <= 8 else t)
            if (m and m.group(1) not in RESULTS and (r.y0 + r.y1) / 2 > head
                    and not any(r.intersects(p + (-12, -4, 12, 4)) and not between_boards(r, p)
                                for p, _, _ in pics)):
                labels.append((m.group(1), r))
        for raw, r in labels:
            numbers.append({"page": i + 1, "label": raw.translate(DIGIT_FIX),
                            "repaired": raw != raw.translate(DIGIT_FIX),
                            "rect": [round(v, 1) for v in r]})
        used = set()
        for pic, w, h in pics:
            k = label_for(pic, labels, used)
            raw = labels[k][0] if k is not None else None
            if k is not None:
                used.add(k)
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
        pages.append({"page": i + 1, "chars": chars, "pictures": len(pics),
                      "kind": page_kind(chars, cover, pics, invisible),
                      "ocr_layer": invisible})

    main_ids = main_series(numbers)
    for k, x in enumerate(numbers):
        x["series"] = "main" if k in main_ids else "other"
    main_keys = {(x["page"], x["label"]) for x in numbers if x["series"] == "main"}
    for d in diagrams:
        d["series"] = "main" if (d["page"], d["label"]) in main_keys else "other"
    (out_dir / "diagrams.json").write_text(json.dumps(diagrams, indent=1))
    (out_dir / "numbers.json").write_text(json.dumps(numbers, indent=1))
    (out_dir / "pages.json").write_text(json.dumps(pages, indent=1))

    # Sample renders, each picture outlined in red with its label underneath.
    samples = pick_samples(n, pages, diagrams)
    thumbs = {}
    for p in samples:
        page = doc[p - 1]
        for d in (x for x in diagrams if x["page"] == p):
            r = pymupdf.Rect(d["rect"])
            page.draw_rect(r, color=(1, 0, 0), width=1.2)
            page.insert_text((r.x0, r.y1 + 9), f"[{d['label'] or '?'}]", fontsize=8,
                             color=(1, 0, 0))
        page.get_pixmap(dpi=DPI).save(out_dir / f"page_{p:04d}.png")
        # A smaller JPEG copy goes inside the HTML so that the report opens on its own.
        thumbs[p] = base64.b64encode(
            page.get_pixmap(dpi=110).tobytes("jpg", jpg_quality=80)).decode()

    kinds = Counter(p["kind"] for p in pages)
    main_labels = [x["label"] for x in numbers if x["series"] == "main"]
    simple = [label_order(s)[0][0] for s in main_labels if len(label_order(s)[0]) == 1]
    main_gaps = sorted(set(range(1, max(simple) + 1)) - set(simple)) if simple else []
    others = [x for x in numbers if x["series"] == "other"]
    labelled = [d for d in diagrams if d["label"]]
    tall = [d for d in diagrams if d["tall"]]
    circled = [d for d in diagrams if d["circled"]]
    unlabelled = [d for d in diagrams if not d["label"] and not d["circled"]]
    partial = [d for d in diagrams if d["partial"]]
    blank = [p["page"] for p in pages if p["kind"] == "blank"]
    def where(rows):
        return ", ".join(str(p) for p in sorted({d["page"] for d in rows})[:3])

    e = html.escape
    out = [
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>Stage 1 Inspection</title><style>"
        ":root{--bg:#fff;--fg:#222;--line:#bbb;--warn:#fff1c2;--bad:#fdd}"
        "@media (prefers-color-scheme:dark){:root{--bg:#1b1b1b;--fg:#ddd;"
        "--line:#555;--warn:#4a3d10;--bad:#4a1c1c}}"
        "body{font:16px/1.55 Georgia,serif;max-width:1100px;margin:auto;padding:16px;"
        "background:var(--bg);color:var(--fg)}table{border-collapse:collapse;font-size:14px}"
        "td,th{border:1px solid var(--line);padding:2px 8px}.warn{background:var(--warn)}"
        ".bad{background:var(--bad)}img{max-width:100%;border:1px solid var(--line)}"
        "figure{display:inline-block;width:250px;margin:6px;vertical-align:top}"
        ".scroll{max-height:480px;overflow:auto}.nums{font-size:14px}</style>",
        f"<h1>Stage 1: {e(pdf.name)}</h1>",
        "<h2>What the pages are</h2>",
        f"<p>The PDF has <b>{n}</b> pages. I sorted them into four kinds.</p><table>"
        "<tr><th>Kind</th><th>Pages</th><th>What it means for the next stages</th></tr>"
        f"<tr><td>scan</td><td>{kinds['scan']}</td><td>The page is one photograph. Stage 2 "
        "searches the photograph for boards, and the moves come from the OCR layer, or from "
        "Tesseract where the scan has none.</td></tr>"
        f"<tr><td>pictures</td><td>{kinds['pictures']}</td><td>The text is real type and each "
        "diagram is a separate picture. Stage 2 cuts the boards straight out of the "
        "pictures.</td></tr>"
        f"<tr><td>text</td><td>{kinds['text']}</td><td>The page has type and no pictures. Any "
        "diagram on it is drawn from shapes or a chess font, and Stage 2 searches the rendered "
        "page for it.</td></tr>"
        f"<tr><td>blank</td><td>{kinds['blank']}</td><td>The page has neither type nor "
        f"pictures{': PDF pages ' + e(', '.join(map(str, blank[:12]))) if blank else ''}."
        "</td></tr></table>",
    ]
    if "clearscan" in producer.lower():
        out.append("<p>The PDF records that Adobe Acrobat's ClearScan made it. ClearScan "
                   "recognised the letters of a scan and redrew them as type, so the text you "
                   "see on screen is itself the OCR result, errors included.</p>")
    elif producer:
        out.append(f"<p>The PDF records its producer as <i>{e(producer)}</i>.</p>")
    scan_ocr = sum(p["kind"] == "scan" and p["chars"] > 0 for p in pages)
    if kinds["scan"]:
        out.append(f"<p>Of the {plural(kinds['scan'], 'scanned page')}, {scan_ocr} carry an "
                   "OCR text layer.</p>")

    out.append("<h2>Board pictures</h2>")
    if diagrams:
        out.append(
            f"<p>I found {plural(len(diagrams), 'embedded picture')} smaller than a page. "
            "Nearly all are boards; a cover or a publisher's logo also lands here and Stage 2 "
            f"discards it. I matched {plural(len(labelled), 'picture')} to a diagram number "
            "printed above or just below it.</p><ul>"
            f"<li>{plural(len(partial), 'picture')} show part of a board only, such as a corner "
            f"or a strip of files{' (first on PDF pages ' + where(partial) + ')' if partial else ''}."
            "</li>"
            f"<li>{plural(len(tall), 'picture')} are much taller than wide. Some hold two or "
            "three boards stacked in one image and others a narrow strip of a board; Stage 2 "
            f"cuts them into single boards{' (first on PDF pages ' + where(tall) + ')' if tall else ''}."
            "</li>"
            f"<li>{plural(len(circled), 'picture')} carry a circled number beside the board. "
            "OCR usually reads a circle as a symbol such as &ldquo;@&rdquo; or "
            "&ldquo;&reg;&rdquo;, so these numbers will come from their order on the page"
            f"{' (first on PDF pages ' + where(circled) + ')' if circled else ''}.</li>"
            f"<li>{plural(len(unlabelled), 'picture')} have no number at all. Books commonly "
            "print a position reached during a game without a number"
            f"{' (first on PDF pages ' + where(unlabelled) + ')' if unlabelled else ''}.</li>"
            "</ul>")
    else:
        out.append("<p>The PDF holds no board pictures, so Stage 2 will search the rendered "
                   "pages for boards.</p>")

    out.append("<h2>How the book numbers its diagrams</h2>")
    if main_labels:
        out.append(
            f"<p>The longest series of diagram numbers runs from {e(main_labels[0])} to "
            f"{e(main_labels[-1])} and has {plural(len(main_labels), 'entry', 'entries')}, "
            "counting lettered ones such as 14a separately. "
            + (f"These numbers are missing from it: <b>{e(', '.join(map(str, main_gaps)))}</b>. "
               "A missing number means that the book skips it, that OCR misread it, or that it "
               "is printed inside a picture; the table below lets you check."
               if main_gaps else "No number in its range is missing.") + "</p>")
    else:
        out.append("<p>I found no numbered series of diagrams in the text.</p>")
    out.append(
        f"<p>{plural(len(others), 'further number')} stand on lines of their own outside that "
        "series. In most books they belong to shorter series that start again at 1, such as "
        "chapter exercises, model games and solutions; a few are stray numbers from the text. "
        "Because numbers repeat, from Stage 2 onward each board is named by its page as well "
        "as its number.</p>"
        f"<p>The running text refers to {plural(len(refs), 'diagram')} by name, as in "
        "&ldquo;Diagram 14&rdquo;.</p>")

    out.append("<h2>Sample pages at 300 dpi</h2><p>I chose these pages to show each kind of "
               "picture counted above. Each board picture is outlined in red, with the number I "
               "matched to it underneath; <b>[?]</b> means no number. Clicking a page opens the "
               "full 300 dpi image when this report sits beside its output folder.</p>")
    for p in samples:
        f = f"page_{p:04d}.png"
        out.append(f"<figure><a href='{f}'><img src='data:image/jpeg;base64,{thumbs[p]}'></a>"
                   f"<figcaption>PDF page {p} ({pages[p - 1]['kind']})</figcaption></figure>")

    if diagrams:
        out.append("<h2>Every board picture</h2><p>Yellow rows show part of a board only; red "
                   "rows have no number. A star marks a number repaired from an OCR "
                   "misreading.</p><div class=scroll><table><tr><th>PDF page</th>"
                   "<th>Number</th><th>Series</th><th>Pixels</th><th>Whole board?</th></tr>")
        for d in diagrams:
            cls = "bad" if not d["label"] and not d["circled"] else "warn" if d["partial"] else ""
            out.append(
                f"<tr class='{cls}'><td>{d['page']}</td><td>{e(d['label'] or '')}"
                f"{'*' if d['label_repaired'] else ''}</td><td>{series_name(d)}</td>"
                f"<td>{d['pixels'][0]}&times;{d['pixels'][1]}</td>"
                f"<td>{'no' if d['partial'] else 'yes'}</td></tr>")
        out.append("</table></div>")

    out.append("<h2>Every diagram number in the text</h2><p>The main series, each number "
               "followed by the PDF page on which it is printed. A star marks a number "
               "repaired from an OCR misreading.</p><p class=nums>")
    out.append(" &middot; ".join(
        f"<b>{e(x['label'])}</b>{'*' if x['repaired'] else ''}&nbsp;p{x['page']}"
        for x in numbers if x["series"] == "main"))
    out.append("</p><p>The other numbers, grouped by PDF page.</p><div class=scroll><table>"
               "<tr><th>PDF page</th><th>Numbers</th></tr>")
    by_page = {}
    for x in others:
        by_page.setdefault(x["page"], []).append(x["label"])
    for p, labs in by_page.items():
        out.append(f"<tr><td>{p}</td><td>{e(', '.join(labs))}</td></tr>")
    out.append("</table></div>")
    (out_dir / "inspect.html").write_text("\n".join(out), encoding="utf-8")

    print(f"{n} pages: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()))
    print(f"{len(diagrams)} board pictures: {len(labelled)} numbered, {len(circled)} circled, "
          f"{len(unlabelled)} unnumbered, {len(partial)} partial, {len(tall)} tall")
    if main_labels:
        print(f"Main series {main_labels[0]}-{main_labels[-1]}: {len(main_labels)} labels, "
              f"missing {main_gaps}")
    print(f"Open {out_dir / 'inspect.html'}")


if __name__ == "__main__":
    main()
