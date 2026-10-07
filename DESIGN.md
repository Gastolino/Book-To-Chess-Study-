# Design guide

Every HTML page this project produces (the reader, the contents and selection
page, and the stage reports) follows this guide. The owner of the project set
the direction: a simple, minimal interface in a modern style, with elegant
use of type, fine lines as dividers, and a clear distinction between text and
chess notation.

## Type

- **DM Sans** sets all interface text and all of the book's prose (notes,
  comments, headings, explanations). Use the variable font at weights 400 and
  500 only. Headings differ from body text by size and weight 500, never by
  bold 700.
- **Geist Mono** sets all chess notation: moves, move numbers, FENs, square
  names in running text. Main-line moves use Geist Mono 500; variation moves
  use Geist Mono 400 in the secondary text colour. (DM Mono was the first
  choice, but its lowercase f descends below the line, so "Nf3" reads as
  "Nƒ3".)
- The fonts live in `chessbook/assets/fonts/` with their SIL Open Font
  Licence files and are embedded in each page as base64 `@font-face` rules,
  so pages work offline. Declare system fallbacks after them.
- Sentence case everywhere. No all-caps text, no small caps, and no added
  letter spacing. Headings may tighten slightly (`letter-spacing: -0.01em`).
- A restrained scale: 15px body, 13px secondary text, 17px, 20px and 26px
  for headings. Line height 1.5 for prose and 1.7 for move lists.
- Use tabular figures for numbers that align in columns.

## Lines, space and surfaces

- Separate regions with 1px hairlines in the line colour. Use whitespace,
  not boxes, to group things.
- No cards, no shadows, no gradients, no rounded "pill" shapes, no badges
  with filled backgrounds. Corners are square or at most 2px.
- Buttons are plain text or a single-line icon with no background; hover
  shows an underline or a change of colour, and keyboard focus shows a 1px
  outline.
- Status (decoded, chosen between readings, failed, waiting) appears as a
  thin coloured outline or a small coloured dot beside the item, with the
  meaning written out in words once on the page. Colour never carries the
  meaning alone.

## Colour

Define every colour as a custom property on `:root`, redefine them under
`@media (prefers-color-scheme: dark)` guarded by
`:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`.
Give `body` an explicit background.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#fbfbfa` | `#141414` | page background |
| `--fg` | `#1b1b1b` | `#e8e8e6` | text |
| `--muted` | `#6f6f6c` | `#9a9a96` | secondary text, variations |
| `--line` | `#e3e3e0` | `#2c2c2b` | hairlines |
| `--accent` | `#2f55c8` | `#8aa6ff` | current move, links, focus |
| `--ok` | `#3d8a5a` | `#6fbf8c` | decoded |
| `--doubt` | `#b8860b` | `#d9ab3c` | chosen between readings |
| `--fail` | `#b4413a` | `#e0756d` | failed |
| `--board-light` | `#ecebe6` | `#b9b8b2` | light squares |
| `--board-dark` | `#bdbab2` | `#8f8d87` | dark squares |
| `--bookmark` | `#f2b705` | `#f2b705` | the bookmark icon when set, and the ribbon |

The bookmark is the only element that uses the warm yellow; nothing else may
use it. It keeps the same value in dark mode, since it is meant to stand out
from everything else on the page.

In dark mode, pictures of the book (page images, thumbnails, diagram crops)
are dimmed slightly and never inverted.

## The board

Flat squares in the two board colours (kept light enough in dark mode that
black pieces stay visible), a 1px outline in the line colour,
coordinates in DM Sans at 10px in the secondary colour, and the piece
drawings from python-chess. No shadows or textures.
The eval bar of the analysis stands along the board's side as a strip in
the two board colours with a 1px outline in the line colour, White's share
from the bottom, and its figure in Geist Mono at 10px at its foot; the
engine's lines are rows of notation, the suggested move at weight 500.

## The sign of work

An open book seen from the front: two pages side by side, each a chequer of
three columns and four rows in the two board colours, with hairline edges in
the secondary colour over a thin cover line (`chessbook/style.py`,
`book_svg`). While the app works, a third page turns over from right to left
(a transform only, 1.2 s a turn with its pause); with reduced motion it
stands still. On the start page it stands about 88 px wide over a 2px bar in
the accent colour on a hairline track (the part done, where the app knows
it, else a sliding segment), with the words of the work under it in the
secondary colour; in the reader it stands 24 px wide at the right of the top
bar, over the same line along the bar's foot, and takes its room whether it
shows or not. Still, on the page background, it is the app's icon.

## Layout

The book page sits on the left and the board panel on the right, divided by a
hairline. The panel holds, from top to bottom: the board, the line's title,
the move list, and the comment on the current move, each separated by a
hairline. On narrow screens the board and its controls follow the page
picture and stay at the foot of the window, just above the bar of the current
move, while the page scrolls by; at the end of the page picture they scroll up
with the line's title and the move list, and the page's foot (the lines on
the page, the chapters) comes last. Pages must work at
390px width with a 16px side margin and no horizontal scroll.

## Turning the page

A swipe across the page moves it with the finger; let go past a quarter of
its width (or flicked), it slides out the way it was swiped while the next
page slides in from the other edge, the two as one strip with a 24 px gap,
in about 300 ms on an easing curve, and below that it springs back. The page
arrows and Page Up and Page Down turn with the same slide. Only transforms
move. A page whose picture has not come slides in as its light sheet, and
the picture fades in over it. On an enlarged page the reading goes on at the
next page's top left after a turn forward and at the previous page's bottom
right after a turn back, above the board and the bar at the foot of the
window. With reduced motion nothing slides or fades: the page changes at
once.

## Writing on the pages

Formal written English addressed to a reader who does not program. Every
sentence has a subject and a finite verb; no em-dashes; no hedging words; no
figures that the code did not count.
