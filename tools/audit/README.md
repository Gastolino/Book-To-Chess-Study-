# The book audit

The audit checks how the program reads the chess books in `corpus/` (and
`primer.pdf`), and how it answers the reader who corrects it, against what
the books print. The program reads a book into lines of moves; the reader
sees each printed move outlined on the page, in the colour of its status,
beside a live board, and corrects a doubtful move by making it on the
board, after which the program reads on by itself. A book the program
reads badly, or a correction it answers badly, is a failure, wherever it
comes from.

`.claude/workflows/book-audit.js` runs the whole audit with many agents
(find, verify, diagnose, fix, review), and `.claude/agents/book-auditor.md`
is one auditor for one book or one question. Both work with the tools
below.

## The books

| name | what it is |
|---|---|
| `ivanchuk` | 5 pages, one annotated game in letters: the control, read wholly |
| `gpa` | *Starting Out: Sicilian Grand Prix Attack*: typeset, letters |
| `tangborn` | Tangborn's opening book, converted by calibre |
| `brunthaler` | read into no game at all (2 lines, 1076 unplaced sequences) |
| `planning` | *The Art of Planning*: ClearScan, figurines read as OCR junk ("'iWb6") |
| `alekhine` | Alekhine's games, typeset |
| `kia` | a King's Indian Attack book, scanned |
| `primer` | *The Soviet Chess Primer* (Maizelis), scanned, 402 pages |

## The tools

Every tool takes the book's name and reads the cached reading of the code
checked out (`output/audit/<code>/`, built by `build.py`; a changed reading
code reads the books again). Page numbers are PDF pages, 1-based, which
differ from the printed folios.

```
python3 tools/audit/build.py [BOOK ...]          read the books with this code (minutes)
python3 tools/audit/scan.py BOOK [--top N]       candidates: breaks, silent, diagrams, jumps, unplaced, hot pages
python3 tools/audit/page.py BOOK PAGE [--text] [--clip x0,y0,x1,y1]
                                                 the page's moves as read, and a picture with the boxes
python3 tools/audit/line.py BOOK L12|KEY [--depth 0] [--from-move 20]
python3 tools/audit/line.py BOOK --list [--chapter N]
python3 tools/audit/diagram.py BOOK p13-1 | --page 13
python3 tools/audit/correct.py BOOK --board KEY=SAN [...]
                                                 a correction as the app makes it, and what follows
python3 tools/audit/compare.py BASE_CODE [NEW_CODE] [--books a,b]
                                                 two versions of the code, book by book
python3 tools/audit/score.py [CODE ...]          the success rate of each book (the aim is 85%)
```

The success rate of a book is the share of its printed moves that the
program shows green and reads as printed, with every move before them in
their line read as printed too (OCR's slips of shape, such as "cs" for c5,
count as printed). It is the audit's measure of progress, round after
round; `score.py` gives it for each book and for all of them.

A git worktree holds no books (they are not in git), and the tests that
read them are skipped without a word. Link them first:
`ln -sfn <main checkout>/corpus corpus; ln -sfn <main checkout>/primer.pdf
primer.pdf; ln -sfn <main checkout>/local local`.

`page.py` writes `output/audit/png/<book>_p<page>.png`. Read the picture
(the Read tool shows images): the boxes are green (ok), amber (guessed),
orange (ambiguous), red (failed), blue (waiting), violet (placed in no
line); a dashed box is a variation move; the small number under a box is
its row in the listing, and the small word above a box is the move the
program made of it, shown where the move is doubtful or differs from the
print. `--clip` enlarges a part of the page (points; the listing gives
each box's place in its key, `page:x,y:raw`).

`correct.py` replays corrections through `chessbook/live.py`, the code that
the app's worker runs: `--board KEY=SAN` is the reader making the move on
the board for the printed move KEY, after which the program reads on (the
open chapter, at least 5 pages), as in the app. It prints what changed,
what was joined and filled, the line from the corrected move on, and the
move the app asks about next. Other corrections: `--connect
"KEY->AFTER|SAN,SAN"` (keys hold colons, so a join is written with `->`,
and the moves the text lacks before the run follow `|`), `--gap`,
`--disconnect`, `--attach`, `--diagram`, `--glyph`, `--skip`, and
`--suggest KEY` (what the program offers after a move, with the
corrections given applied first). Every option takes `KEY->VALUE` as well
as `KEY=VALUE`.

`app_lib.js` opens a book in the browser app in Chromium (Pyodide, the
reader, the board, the sheet) and drives it as a reader does; its head
comment lists the helpers. The first open reads the book in the app
(minutes); later opens take seconds. Screenshots go to
`output/audit/app/<book>/`.

## How to judge

- **The print is the truth.** A finding holds only when you have seen the
  page (the picture, enlarged with `--clip` where needed) and can say what
  the book prints at that place. The text layer is no truth: scanned books
  read "c4" as "C4", figurines as junk, "0-0" as "O·O". A book's own
  misprint (an illegal move as printed) is the book's error, to be reported
  as such, and the program's failure only in how it answers it.
- **A scan candidate is no failure until you have looked.** The scan's
  "silent" list (a square or piece printed differs from the move made) and
  its "diagrams" list (a diagram disagrees with its line) are the richest
  sources: most entries mark the place where a line went wrong, often
  several moves before them. Find the first wrong move.
- **Severity**, worst first:
  1. `silent-wrong`: a move, line or position shown as certain (green) that
     the book does not print. The reader is misled and is not warned.
  2. `lost`: moves printed clearly that the program leaves doubtful,
     unplaced or out of their line, where a careful reading could have read
     them.
  3. `correction`: the program answers a correction wrongly: a wrong join or
     filled move, a wrong next question, a line that does not recover after
     the right move is given, an error, or an answer slower than 5 seconds.
  4. `app`: the app shows or does something wrong on a real book (an error,
     a sheet that sticks, a move list or board that disagrees with the
     reading, a layout that hides what is needed).
  5. `minor`: wrong but harmless (a title, a label).
- **Find the cause.** For a finding to be fixed, say where in the code the
  program goes wrong (module and function: `chessbook/movetext.py` decodes
  move tokens, `chessbook/assemble.py` builds lines, joins variations, ties
  diagrams and reads on, `chessbook/pdftext.py` reads the text layer,
  `chessbook/boards.py` reads diagram pictures, `chessbook/review_js.py` and
  `chessbook/reader.py` are the reader, `web/` the app). Read the code; a
  guess at the cause is labelled as one.
- **Count.** Say how often the pattern occurs in the book (a scan list
  filtered by the pattern, or a short script over `books.load(name)`), so
  that the fixes go to what costs the reader most.

## A finding

Each finding names the book, the PDF page(s), the token keys, what the
book prints, what the program did, what it should have done, the
evidence (the commands run and the lines of their output that show it),
the severity, how often it occurs, the cause in the code as far as it is
known, and the commands that reproduce it.

## Fixing

A fix goes on its own branch with a test. The tests of this repository
make their books (`tests/test_assemble.py make_book`, and the books of
`tests/test_read_on.py`, `tests/test_thread.py`): a fix comes with a
generated book that shows the failure, failing before the fix and passing
after it. Then: the fast tests of the modules touched, `build.py` for the
books, and `compare.py` against the base code's readings, which must show
gains and no losses (or losses explained one by one on the page).
