"""Stage 1: inspect a chess book PDF.

Usage:  python stage1_inspect.py BOOK.pdf

Writes output/<book>/stage1/inspect.html, 300 dpi renders of sample pages with
every board picture outlined, and two JSON files for Stage 2: diagrams.json
(one record per embedded board picture; a picture that holds several boards
stacked one above another lists them under "boards", each with its rect and
label) and numbers.json (every diagram number found in the text).

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

from chessbook import style, textdiagram

DPI = 300
MAX_SAMPLES = 12

# OCR reads 1 as l or I, and 8 as S or B, inside numbers. The stand-ins are
# matched case-sensitively: a lone "b" under a board is a file letter.
DIGIT_FIX = str.maketrans({"l": "1", "I": "1", "S": "8", "B": "8"})
_D = r"(?-i:[0-9lISB])"
NUM = rf"(?=[^\s]*\d|[lI]$){_D}{{1,3}}(?:[.\-]{_D}{{1,3}})?[a-d]?"
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
ACCENT = (0x2f / 255, 0x55 / 255, 0xc8 / 255)  # --accent of DESIGN.md, for the sample outlines


def text_lines(page):
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 0:
            for line in b["lines"]:
                yield "".join(s["text"] for s in line["spans"]).strip(), pymupdf.Rect(line["bbox"])


def _page_pictures(page):
    """(page_scan_cover, [(Rect, px_w, px_h, xref), ...]) in reading order."""
    area = abs(page.rect)
    cover, boards = 0.0, []
    # An image placed twice on a page is listed once per placement, and each
    # listing returns every placement's rectangle: take each image once.
    for img in {img[0]: img for img in page.get_images(full=True)}.values():
        for r in page.get_image_rects(img[0]):
            r = r & page.rect
            share = abs(r) / area
            if share >= FULL_PAGE:
                cover = max(cover, share)
            elif r.width > 20 and r.height > 20:
                boards.append((r, img[2], img[3], img[0]))
    # Left column top to bottom, then right column. Stage 2 reorders boards
    # that sit side by side in one row.
    mid = page.rect.width / 2
    boards.sort(key=lambda t: ((t[0].x0 + t[0].x1) / 2 > mid, t[0].y0))
    return cover, boards


def page_pictures(page):
    """Return (page_scan_cover, board_pictures) for one page.

    A picture covering most of the page is a photograph of the whole page;
    smaller pictures are candidate boards, sorted into reading order.
    """
    cover, boards = _page_pictures(page)
    return cover, [(r, w, h) for r, w, h, _ in boards]


def stacked_boards(doc, xref, rect):
    """Rectangles of the boards in a picture that holds several of them
    stacked with text between (ClearScan keeps such a stretch of the page as
    one picture), or [] for a picture holding one board.

    Boards are the bands of rows with ink in them; the white rows between are
    where the text was. A band counts as a board when it is at least a third
    as tall as the picture is wide, and the bands must be of about one height.
    """
    try:
        pix = pymupdf.Pixmap(doc, xref)
        if pix.n - pix.alpha != 1:
            pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
        data, row, step = pix.samples, pix.stride, pix.n
    except (RuntimeError, ValueError):
        return []
    # A row is inked when more than 3% of its pixels are darker than mid-grey.
    dark = bytes(1 if v < 128 else 0 for v in range(256))
    inked = [sum(data[y * row:y * row + pix.w * step:step].translate(dark)) > 0.03 * pix.w
             for y in range(pix.h)]
    bands, start = [], None
    for y, v in enumerate(list(inked) + [False]):
        if v and start is None:
            start = y
        elif not v and start is not None:
            if y - start >= pix.w / 3:
                bands.append((start, y))
            start = None
    if len(bands) < 2:
        return []
    hs = [b - a for a, b in bands]
    if min(hs) < 0.8 * max(hs):
        return []
    k = rect.height / pix.h
    return [pymupdf.Rect(rect.x0, rect.y0 + a * k, rect.x1, rect.y0 + b * k) for a, b in bands]


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


MOVE_DOTS = ".•…·"


def continues_as_move(r, others):
    """True when a bare number at r is a move number whose dot and move OCR
    split off into a text line of their own on the same row ("17" and
    "• .ixf6t ..."): such a number is not a diagram label."""
    h = r.y1 - r.y0
    for t, o in others:
        if o is r or not t or t.lstrip(" ")[:1] not in MOVE_DOTS:
            continue
        overlap = min(r.y1, o.y1) - max(r.y0, o.y0)
        if (o.x0 > (r.x0 + r.x1) / 2 and o.x0 - r.x1 <= 15
                and overlap >= 0.5 * min(h, o.y1 - o.y0)):
            return True
    return False


def board_coords(pic, lines):
    """(files, ranks): how many distinct file letters are printed under a
    picture and rank digits beside it. A whole board shows eight of each; a
    corner of a board fewer."""
    files, ranks = set(), set()
    for t, r in lines:
        t = t.strip()
        if len(t) != 1:
            continue
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if t in "abcdefgh" and pic.x0 - 5 <= cx <= pic.x1 + 5 and pic.y1 - 4 <= r.y0 <= pic.y1 + 16:
            files.add(t)
        elif t in "12345678" and pic.y0 - 2 <= cy <= pic.y1 + 2 and (
                pic.x0 - 16 <= r.x1 <= pic.x0 + 4 or pic.x1 - 4 <= r.x0 <= pic.x1 + 16):
            ranks.add(t)
    return len(files), len(ranks)


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
        return "Main" if d["series"] == "main" else "Other"
    return "Circled" if d["circled"] else "None"


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
    return f"<span class=\"num\">{k}</span> {one if k == 1 else many or one + 's'}"


def num(text):
    """A figure or a list of figures in running text, in tabular numerals."""
    return f"<span class=\"num\">{html.escape(str(text))}</span>"


REPORT_CSS = r"""
.wrap{max-width:1040px;margin:0 auto;padding:48px 32px 64px}
header{max-width:64ch}
.lede{margin-top:8px}
section{border-top:1px solid var(--line);margin-top:32px;padding-top:24px}
section h2{margin-bottom:16px}
section p{max-width:64ch;margin:0 0 8px}
section ul{max-width:64ch;margin:0 0 8px;padding-left:20px}
section li{margin:4px 0}
table{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;width:auto;max-width:100%}
th{font-weight:400;color:var(--muted);text-align:left;padding:6px 24px 6px 0;
border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:6px 24px 6px 0;border-bottom:1px solid var(--line);vertical-align:top}
th:last-child,td:last-child{padding-right:0}
td.desc{max-width:60ch}
th.r,td.r{text-align:right;white-space:nowrap}
td:has(.dot){white-space:nowrap}
thead th{position:sticky;top:0;background:var(--bg)}
.scroll{overflow:auto;margin:8px 0 16px}
.scroll.tall{max-height:480px}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:8px;vertical-align:1px}
.dot.ok{background:var(--ok)}.dot.doubt{background:var(--doubt)}.dot.fail{background:var(--fail)}
.samples{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:24px 16px;
margin-top:16px}
figure{margin:0}
figure img{display:block;width:100%;height:auto;outline:1px solid var(--line)}
figcaption{font-size:13px;color:var(--muted);margin-top:8px}
.nums{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));column-gap:16px;
font-size:13px;line-height:1.5;max-width:none;font-variant-numeric:tabular-nums;margin-bottom:16px}
.lab{white-space:nowrap}
@media (max-width:700px){.wrap{padding:32px 16px 48px}th,td{padding-right:16px}
.pictures th:nth-child(4),.pictures td:nth-child(4){display:none}
.pictures td:has(.dot){white-space:normal}}
"""


def analyse(pdf, out_dir):
    """Find the board pictures, their labels and every diagram number of a
    book, and write diagrams.json, numbers.json and pages.json to out_dir.
    Returns what the report needs. The browser app calls this alone."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    n = doc.page_count
    producer = " ".join(filter(None, (doc.metadata.get("creator"), doc.metadata.get("producer"))))

    pages, diagrams, numbers, refs = [], [], [], Counter()
    for i, page in enumerate(doc):
        lines = list(text_lines(page))
        chars = sum(len(t) for t, _ in lines)
        cover, xpics = _page_pictures(page)
        # Diagrams printed as text in a chess font count as board pictures
        # with no image (a (diagram, FEN) pair in place of the xref), sorted into the same reading order.
        tds = textdiagram.page_text_diagrams(lines)
        for td, fen in tds:
            xpics.append((pymupdf.Rect(td.rect), 0, 0, (td, fen)))
        if tds:
            mid = page.rect.width / 2
            xpics.sort(key=lambda t: ((t[0].x0 + t[0].x1) / 2 > mid, t[0].y0))
        pics = [(r, w, h) for r, w, h, _ in xpics]
        invisible = any(t.get("type") == 3 for t in page.get_texttrace())
        head = page.rect.height * 0.06  # running head with the page number
        # OCR sometimes splits a number with a space ("1 15" for 115). Lines that
        # touch a picture are its rank and file letters, so they are left out.
        labels = []
        for t, r in lines:
            m = LABEL_RE.match(t.replace(" ", "") if len(t) <= 8 else t)
            if (m and m.group(1) not in RESULTS and (r.y0 + r.y1) / 2 > head
                    and not any(r.intersects(p + (-12, -4, 12, 4)) and not between_boards(r, p)
                                for p, _, _ in pics)
                    and not continues_as_move(r, lines)):
                labels.append((m.group(1), r))
        for raw, r in labels:
            numbers.append({"page": i + 1, "label": raw.translate(DIGIT_FIX),
                            "repaired": raw != raw.translate(DIGIT_FIX),
                            "rect": [round(v, 1) for v in r]})
        used = set()
        for pic, w, h, xref in xpics:
            k = label_for(pic, labels, used)
            raw = labels[k][0] if k is not None else None
            if k is not None:
                used.add(k)
            if isinstance(xref, tuple):
                td, fen = xref
                ink = textdiagram.ink_rect(page, pic)
                diagrams.append({
                    "page": i + 1, "rect": [round(v, 1) for v in ink], "pixels": [0, 0],
                    "label": raw.translate(DIGIT_FIX) if raw else None,
                    "label_repaired": bool(raw) and raw != raw.translate(DIGIT_FIX),
                    "circled": False, "partial": False, "tall": False, "coords": [0, 0],
                    "text": True, "fen": fen, "encoding": td.encoding})
                continue
            stack = stacked_boards(doc, xref, pic) if pic.height > 1.3 * pic.width else []
            sub = []
            for j, br in enumerate(stack):
                if j == 0:
                    lab = raw
                else:
                    kk = label_for(br, labels, used)
                    lab = labels[kk][0] if kk is not None else None
                    if kk is not None:
                        used.add(kk)
                sub.append({"rect": [round(v, 1) for v in br],
                            "label": lab.translate(DIGIT_FIX) if lab else None,
                            "partial": abs(br.width / br.height - 1) > 0.12,
                            "coords": list(board_coords(br, lines))})
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
                "coords": list(board_coords(pic, lines)),
            })
            if sub:
                diagrams[-1]["boards"] = sub
        for m in REF_RE.finditer(page.get_text()):
            refs[m.group(1).translate(DIGIT_FIX)] += 1
        pages.append({"page": i + 1, "chars": chars, "pictures": len(pics) - len(tds),
                      "text_diagrams": len(tds),
                      "kind": page_kind(chars, cover, [x for x in xpics if not isinstance(x[3], tuple)],
                                        invisible),
                      "ocr_layer": invisible})

    main_ids = main_series(numbers)
    for k, x in enumerate(numbers):
        x["series"] = "main" if k in main_ids else "other"
    main_keys = {(x["page"], x["label"]) for x in numbers if x["series"] == "main"}
    for d in diagrams:
        d["series"] = "main" if (d["page"], d["label"]) in main_keys else "other"
        for b in d.get("boards", []):
            b["series"] = "main" if (d["page"], b["label"]) in main_keys else "other"
    (out_dir / "diagrams.json").write_text(json.dumps(diagrams, indent=1))
    (out_dir / "numbers.json").write_text(json.dumps(numbers, indent=1))
    (out_dir / "pages.json").write_text(json.dumps(pages, indent=1))

    return doc, n, producer, pages, diagrams, numbers, refs


def main():
    ap = argparse.ArgumentParser(description="Inspect a chess book PDF (Stage 1).")
    ap.add_argument("pdf", type=Path)
    args = ap.parse_args()
    pdf = args.pdf
    if not pdf.exists():
        raise SystemExit(f"Cannot find {pdf}.")
    out_dir = Path("output") / pdf.stem / "stage1"
    out_dir.mkdir(parents=True, exist_ok=True)
    doc, n, producer, pages, diagrams, numbers, refs = analyse(pdf, out_dir)

    # Sample renders, each picture outlined in the accent blue of the design guide with its label underneath.
    samples = pick_samples(n, pages, diagrams)
    thumbs = {}
    for p in samples:
        page = doc[p - 1]
        for d in (x for x in diagrams if x["page"] == p):
            r = pymupdf.Rect(d["rect"])
            page.draw_rect(r, color=ACCENT, width=1.2)
            page.insert_text((r.x0, r.y1 + 9), f"[{d['label'] or '?'}]", fontsize=8,
                             color=ACCENT)
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
    stacked = [d for d in diagrams if d.get("boards")]
    circled = [d for d in diagrams if d["circled"]]
    unlabelled = [d for d in diagrams if not d["label"] and not d["circled"]]
    partial = [d for d in diagrams if d["partial"]]
    blank = [p["page"] for p in pages if p["kind"] == "blank"]
    def where(rows):
        return ", ".join(str(p) for p in sorted({d["page"] for d in rows})[:3])

    e = html.escape
    blank_pages = ((": PDF page " if len(blank) == 1 else ": PDF pages ")
                   + e(", ".join(map(str, blank[:12]))) if blank else "")
    out = [
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>Stage 1 Inspection</title>\n<style>{style.page_css()}{REPORT_CSS}</style>\n"
        "</head>\n<body>\n<main class=\"wrap\">",
        f"<header><h1>Stage 1, {e(pdf.name)}</h1><p class=\"lede\">This report shows what the "
        "program found in the PDF before it reads any moves: the kinds of page, the board "
        "pictures and the diagram numbers.</p></header>",
        "<section><h2>What the pages are</h2>",
        f"<p>The PDF has {plural(n, 'page')}, and the program sorts them into four kinds.</p>"
        "<div class=\"scroll\"><table><thead><tr><th>Kind</th><th class=\"r\">Pages</th>"
        "<th>What it means for the next stages</th></tr></thead><tbody>"
        f"<tr><td>Scan</td><td class=\"r\">{kinds['scan']}</td><td class=\"desc\">The page is one photograph. "
        "Stage 2 searches the photograph for boards, and the moves come from the OCR layer, or "
        "from Tesseract where the scan has none.</td></tr>"
        f"<tr><td>Pictures</td><td class=\"r\">{kinds['pictures']}</td><td class=\"desc\">The text is real type "
        "and each diagram is a separate picture. Stage 2 cuts the boards straight out of the "
        "pictures.</td></tr>"
        f"<tr><td>Text</td><td class=\"r\">{kinds['text']}</td><td class=\"desc\">The page has type and no "
        "pictures. Any diagram on it is drawn from shapes or a chess font, and Stage 2 searches "
        "the rendered page for it.</td></tr>"
        f"<tr><td>Blank</td><td class=\"r\">{kinds['blank']}</td><td class=\"desc\">The page has neither type "
        f"nor pictures{blank_pages}."
        "</td></tr></tbody></table></div>",
    ]
    if "clearscan" in producer.lower():
        out.append("<p>The PDF records that Adobe Acrobat’s ClearScan made it. ClearScan "
                   "recognised the letters of a scan and redrew them as type, so the text on "
                   "screen is itself the OCR result, errors included.</p>")
    elif producer:
        out.append(f"<p>The PDF records its producer as <i>{e(producer)}</i>.</p>")
    scan_ocr = sum(p["kind"] == "scan" and p["chars"] > 0 for p in pages)
    if kinds["scan"]:
        out.append(f"<p>Of the {plural(kinds['scan'], 'scanned page')}, "
                   f"{num(scan_ocr)} {'carries' if scan_ocr == 1 else 'carry'} an OCR text layer.</p>")
    out.append("</section>")

    out.append("<section><h2>Board pictures</h2>")
    if diagrams:
        out.append(
            f"<p>The program found {plural(len(diagrams), 'embedded picture')} smaller than a "
            "page. A cover or a publisher’s logo also counts as such a picture, and Stage 2 "
            f"discards it. The program matched {plural(len(labelled), 'picture')} to a "
            "diagram number printed above or just below it.</p><ul>"
            f"<li>{plural(len(partial), 'picture')} {'shows' if len(partial) == 1 else 'show'} part of a board only, such as a corner "
            f"or a strip of files{' (first on PDF pages ' + where(partial) + ')' if partial else ''}."
            "</li>"
            f"<li>{plural(len(tall), 'picture')} {'is' if len(tall) == 1 else 'are'} much taller "
            f"than wide{' (first on PDF pages ' + where(tall) + ')' if tall else ''}. Of these, "
            f"{plural(len(stacked), 'picture holds', 'pictures hold')} boards stacked one above "
            "another, and the program lists each of their boards with its own number, so that "
            "later stages treat each board on its "
            f"own{' (first on PDF pages ' + where(stacked) + ')' if stacked else ''}.</li>"
            f"<li>{plural(len(circled), 'picture')} {'carries' if len(circled) == 1 else 'carry'} a circled number beside the board. "
            "OCR reads a circle as a symbol such as &ldquo;@&rdquo; or "
            "&ldquo;&reg;&rdquo;, so these numbers come from their order on the page"
            f"{' (first on PDF pages ' + where(circled) + ')' if circled else ''}.</li>"
            f"<li>{plural(len(unlabelled), 'picture')} {'has' if len(unlabelled) == 1 else 'have'} "
            "no number at all"
            f"{' (first on PDF pages ' + where(unlabelled) + ')' if unlabelled else ''}.</li>"
            "</ul>")
    else:
        out.append("<p>The PDF holds no board pictures, so Stage 2 will search the rendered "
                   "pages for boards.</p>")
    out.append("</section>")

    out.append("<section><h2>How the book numbers its diagrams</h2>")
    if main_labels:
        out.append(
            f"<p>The longest series of diagram numbers runs from {num(main_labels[0])} to "
            f"{num(main_labels[-1])} and has {plural(len(main_labels), 'entry', 'entries')}, "
            "counting lettered ones such as 14a separately. "
            + (f"These numbers are missing from it: {num(', '.join(map(str, main_gaps)))}. "
               "A missing number means that the book skips it, that OCR misread it, or that it "
               "is printed inside a picture; the table below lets you check."
               if main_gaps else "No number in its range is missing.") + "</p>")
    else:
        out.append("<p>The program found no numbered series of diagrams in the text.</p>")
    out.append(
        f"<p>{plural(len(others), 'further number')} {'stands' if len(others) == 1 else 'stand'} on lines of their own outside that "
        "series. They belong to shorter series that start again at 1, such as chapter "
        "exercises, model games and solutions, or they are stray numbers from the text. "
        "Because numbers repeat, from Stage 2 onward each board is named by its page as well "
        "as its number.</p>"
        f"<p>The running text refers to {plural(len(refs), 'diagram')} by name, as in "
        "&ldquo;Diagram 14&rdquo;.</p></section>")

    out.append("<section><h2>Sample pages at 300 dpi</h2><p>The program chose these pages to "
               "show each kind of picture counted above. Each board picture is outlined in blue, "
               "with the number the program matched to it underneath; [?] means no number. A "
               "click on a page opens the full 300 dpi image when this report sits beside its "
               "output folder.</p><div class=\"samples\">")
    for p in samples:
        f = f"page_{p:04d}.png"
        out.append(f"<figure><a href='{f}'><img class='scan' alt='PDF page {p}' "
                   f"src='data:image/jpeg;base64,{thumbs[p]}'></a>"
                   f"<figcaption>PDF page <span class=\"num\">{p}</span>, "
                   f"{e(pages[p - 1]['kind'])}</figcaption></figure>")
    out.append("</div></section>")

    if diagrams:
        out.append("<section><h2>Every board picture</h2><p>Each row names what the program "
                   "found: a whole board with a number, part of a board only, or a picture "
                   "with no number. A star marks a number repaired from an OCR misreading.</p>"
                   "<div class=\"scroll tall\"><table class=\"pictures\"><thead><tr><th class=\"r\">PDF page</th>"
                   "<th class=\"r\">Number</th><th>Series</th><th class=\"r\">Pixels</th>"
                   "<th>Status</th></tr></thead><tbody>")
        for d in diagrams:
            no_number = not d["label"] and not d["circled"]
            if no_number and d["partial"]:
                cls, words = "fail", "Part of a board, with no number"
            elif no_number:
                cls, words = "fail", "No number"
            elif d["partial"]:
                cls, words = "doubt", "Part of a board only"
            else:
                cls, words = "ok", ("Whole board, circled number" if d["circled"] and not d["label"]
                                    else "Whole board")
            out.append(
                f"<tr><td class=\"r\">{d['page']}</td><td class=\"r\">{e(d['label'] or '')}"
                f"{'*' if d['label_repaired'] else ''}</td><td>{series_name(d)}</td>"
                + ("<td class=\"r\">text</td>" if d.get("text") else
                   f"<td class=\"r\">{d['pixels'][0]}&thinsp;&times;&thinsp;{d['pixels'][1]}</td>")
                + f"<td><i class=\"dot {cls}\"></i>{words}</td></tr>")
        out.append("</tbody></table></div></section>")

    out.append("<section><h2>Every diagram number in the text</h2><p>This list gives each "
               "number of the main series with the PDF page on which it is printed. A star marks "
               "a number repaired from an OCR misreading.</p><div class=\"nums\">")
    out.append(" ".join(
        f"<span class=\"lab\">{e(x['label'])}{'*' if x['repaired'] else ''} "
        f"<span class=\"muted\">p{x['page']}</span></span>"
        for x in numbers if x["series"] == "main"))
    out.append("</div><p>The table groups the other numbers by PDF page.</p>"
               "<div class=\"scroll tall\"><table>"
               "<thead><tr><th class=\"r\">PDF page</th><th>Numbers</th></tr></thead><tbody>")
    by_page = {}
    for x in others:
        by_page.setdefault(x["page"], []).append(x["label"])
    for p, labs in by_page.items():
        out.append(f"<tr><td class=\"r\">{p}</td><td class=\"num\">{e(', '.join(labs))}</td></tr>")
    out.append("</tbody></table></div></section></main>\n</body>\n</html>")
    (out_dir / "inspect.html").write_text("\n".join(out), encoding="utf-8")

    print(f"{n} pages: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()))
    print(f"{len(diagrams)} board pictures: {len(labelled)} numbered, {len(circled)} circled, "
          f"{len(unlabelled)} unnumbered, {len(partial)} partial, {len(tall)} tall, "
          f"{len(stacked)} holding stacked boards")
    if main_labels:
        print(f"Main series {main_labels[0]}-{main_labels[-1]}: {len(main_labels)} labels, "
              f"missing {main_gaps}")
    print(f"Open {out_dir / 'inspect.html'}")


if __name__ == "__main__":
    main()
