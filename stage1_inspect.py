"""Stage 1: inspect the scanned book.

Usage:  python stage1_inspect.py [primer.pdf]

Writes output/stage1/inspect.html plus 300 dpi renders of sample pages.
"""
import html
import re
import sys
from collections import defaultdict
from pathlib import Path

import pymupdf as fitz

PDF = Path(sys.argv[1] if len(sys.argv) > 1 else "primer.pdf")
OUT = Path("output/stage1")
DPI = 300
SAMPLES = 8

# OCR commonly turns "Diagram" into Dlagram, Diagrarn, Diagrain, Oiagram, Diag.
DIAGRAM_RE = re.compile(
    r"\b[DO0][il1|!]a?g(?:r[ae](?:m|rn|in|nn)|\.)\s*(?:N[o0]\.?\s*)?([0-9lIOoSsB]{1,4})\b"
)
# Characters OCR substitutes for digits inside a number.
DIGIT_FIX = str.maketrans({"l": "1", "I": "1", "O": "0", "o": "0", "S": "8", "s": "8", "B": "8"})


def classify_page(page):
    """Return (is_scan, image_cover, text_chars, invisible_text)."""
    area = abs(page.rect)
    cover = 0.0
    for img in page.get_images(full=True):
        for r in page.get_image_rects(img[0]):
            cover = max(cover, abs(r & page.rect) / area)
    text = page.get_text()
    # Text drawn in render mode 3 is invisible: the usual sign of an OCR layer.
    invisible = any(t.get("type") == 3 for t in page.get_texttrace())
    return cover >= 0.85, cover, len(text.strip()), invisible


def main():
    if not PDF.exists():
        sys.exit(f"Cannot find {PDF}. Put the book in this folder or pass its path.")
    OUT.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(PDF)
    n = doc.page_count

    rows, found = [], defaultdict(list)
    for i, page in enumerate(doc):
        is_scan, cover, chars, invisible = classify_page(page)
        rows.append((i + 1, is_scan, cover, chars, invisible))
        for m in DIAGRAM_RE.finditer(page.get_text()):
            raw = m.group(1)
            fixed = raw.translate(DIGIT_FIX)
            if fixed.isdigit():
                found[int(fixed)].append((i + 1, m.group(0), raw != fixed))

    step = max(1, n // SAMPLES)
    samples = list(range(0, n, step))[:SAMPLES]
    for i in samples:
        doc[i].get_pixmap(dpi=DPI).save(OUT / f"page_{i + 1:04d}.png")

    scans = sum(r[1] for r in rows)
    with_text = sum(r[3] > 0 for r in rows)
    nums = sorted(found)
    gaps = [k for k in range(1, nums[-1] + 1) if k not in found] if nums else []

    e = html.escape
    parts = [
        "<!doctype html><meta charset=utf-8><title>Stage 1 Inspection</title>",
        "<style>body{font:15px/1.5 Georgia,serif;max-width:1100px;margin:auto;padding:16px;"
        "background:#fff;color:#222}table{border-collapse:collapse}td,th{border:1px solid #bbb;"
        "padding:2px 8px}.bad{background:#fdd}.warn{background:#ffe9b0}img{max-width:100%;"
        "border:1px solid #888}figure{display:inline-block;width:260px;margin:6px;vertical-align:top}"
        "@media (prefers-color-scheme:dark){body{background:#1b1b1b;color:#ddd}}</style>",
        f"<h1>Stage 1: {e(PDF.name)}</h1>",
        f"<p>The PDF has <b>{n}</b> pages. On <b>{scans}</b> of them a single picture covers at "
        f"least 85% of the page, which means the page is a scan. <b>{with_text}</b> pages carry "
        f"an OCR text layer.</p>",
        f"<p>I found <b>{len(nums)}</b> different diagram numbers, running from "
        f"{nums[0] if nums else '-'} to {nums[-1] if nums else '-'}. "
        f"<b>{len(gaps)}</b> numbers in that range never appear in the OCR text; "
        "Stage 2 will look for those boards in the images instead.</p>",
        f"<p><b>Missing numbers:</b> {e(', '.join(map(str, gaps))) or 'none'}</p>",
        f"<h2>Sample pages at {DPI} dpi</h2><p>Click a page to open it full size.</p>",
    ]
    for i in samples:
        f = f"page_{i + 1:04d}.png"
        parts.append(f"<figure><a href='{f}'><img src='{f}'></a><figcaption>Page {i + 1}"
                     "</figcaption></figure>")
    parts.append("<h2>Every diagram number</h2><p>Yellow rows were repaired from an OCR "
                 "misreading. Red rows occur on more than one page.</p>"
                 "<table><tr><th>Diagram</th><th>Page(s)</th><th>Text as OCR read it</th></tr>")
    for k in nums:
        hits = found[k]
        pages = sorted({p for p, _, _ in hits})
        cls = "bad" if len(pages) > 1 else "warn" if any(fx for _, _, fx in hits) else ""
        parts.append(f"<tr class='{cls}'><td>{k}</td><td>{', '.join(map(str, pages))}</td>"
                     f"<td>{e(' | '.join(sorted({t for _, t, _ in hits})))}</td></tr>")
    parts.append("</table><h2>Every page</h2><table><tr><th>Page</th><th>Scan?</th>"
                 "<th>Picture covers</th><th>OCR characters</th><th>Invisible text</th></tr>")
    for p, s, c, t, inv in rows:
        cls = "" if s and t else "warn"
        parts.append(f"<tr class='{cls}'><td>{p}</td><td>{'yes' if s else 'no'}</td>"
                     f"<td>{c:.0%}</td><td>{t}</td><td>{'yes' if inv else 'no'}</td></tr>")
    parts.append("</table>")
    (OUT / "inspect.html").write_text("\n".join(parts), encoding="utf-8")
    print(f"{n} pages, {scans} scans, {len(nums)} diagram numbers, {len(gaps)} missing")
    print(f"Open {OUT / 'inspect.html'}")


if __name__ == "__main__":
    main()
