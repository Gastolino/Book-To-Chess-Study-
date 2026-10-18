# The audit plan: cycles to 85%

The audit hunts the program's errors on the eight books and fixes them, in
cycles, until the owner says "thanks". Each cycle ends with the measures
below taken again, so that every cycle shows what it gained.

## The targets

| measure | how it is taken | start | now | target |
|---|---|---|---|---|
| Success rate, all books | `tools/audit/score.py`: printed moves shown green and read as printed, with the whole line before them | 62.5% | 79.4% | **85%** |
| Success rate, each book | the same, book by book | see below | see below | **85% each** |
| Problems solved | confirmed findings whose causes are fixed and merged | 0 of 140 | 10 of 140 | **119 of 140 (85%)** |
| Silent errors | green moves that the print contradicts (`score.py`, "wrong") | 1,001 | 281 | **under 100** |
| App failures | confirmed app findings still open | 7 | 0 | **0** |
| Tests | the fast suite and the browser tests | pass | pass | **pass, every cycle** |

The success rate of each book, and the milestone each book must reach:

| book | start | now | after cycle 3 | after cycle 5 | end |
|---|---|---|---|---|---|
| Ivanchuk (the control) | 100.0% | 100.0% | 100% | 100% | 100% |
| Alekhine | 86.9% | 91.0% | 88% | 90% | 90% |
| Tangborn | 75.3% | 88.3% | 82% | 85% | 85% |
| Grand Prix | 67.6% | 86.4% | 75% | 82% | 85% |
| Primer | 61.0% | 75.4% | 68% | 78% | 85% |
| KIA | 44.7% | 69.9% | 62% | 75% | 85% |
| Planning | 29.6% | 48.9% | 45% | 65% | 85% |
| Brunthaler | 0.0% | 73.8% | 30% | 60% | 85% |
| **All books** | 62.5% | 79.4% | **70%** | **78%** | **85%** |

A fix that lowers any book's rate is sent back, unless the pages show
that the moves it loses were wrong.

## The cycle

Each cycle has seven steps, in this order.

1. **Measure.** `score.py` gives every book's rate on the merged code, and
   `scan.py` gives the candidates of each book.
2. **Choose.** Up to fifteen causes, taken from the diagnosis
   (`output/audit/runs/solve.json`) and from the latest hunt. The causes
   that cost the most moves in the books furthest below their milestone go
   first, and every fix sent back by a reviewer goes again with the
   reviewer's notes.
3. **Fix.** The workflow's "fix" mode, in three parallel runs of up to five
   causes each. Each fixer works in a separate copy of the repository with
   the books linked, writes a test that fails before the fix, makes the
   fix, reads all eight books and runs `compare.py` and `score.py`.
4. **Review.** A reviewer checks every fix: the test fails before the fix
   and passes after it, the tests that read the real books pass, the gains
   are true on the page, and no book's rate falls without a reason.
5. **Merge.** The approved fixes go on `claude/audit-fixes`. The fast suite
   runs, the books are read again, and `score.py` and `compare.py` compare
   the cycle's end with its start.
6. **Check on the page.** Twenty moves of each book that changed status are
   looked at on the page, so that the measure stays honest.
7. **Report.** The table above, filled in; what was fixed; what was sent
   back and why.

Every second cycle, and whenever the list of causes runs short, the cycle
begins with a **hunt**: the workflow's "find" mode on the three books
furthest below their milestone, and on the app, so that new errors come in
as old ones go out.

## The cycles

| cycle | contents | state |
|---|---|---|
| 1 | Hunt on all books (140 findings confirmed, 12 refuted), diagnosis into 89 causes, eight fixes; four merged: typeset books read as printed, capital C as the c-file, "!" read as "1", notes kept with their game | done: 63.8% |
| 2 | Five fixes merged: Tangborn's running heads, the b/h and c/e twins decided by a diagram, taps after a gap, the eye on the phone, saving the reading. The other causes of the cycle stopped at the usage limit and move to cycle 3. From here on, one fixer works at a time and scripts check each fix | done: 66.5% |
| 3 | Seven causes fixed, one fixer at a time, checked by scripts: Brunthaler's captions, split squares and moves font (0% to 53%); KIA's glued moves and moves at a line's end (53% to 56%); printed move numbers anchor the line; Planning's numbers beside a board, ClearScan's signs for f3 and f1, and wide boards (36% to 44%); Undo at a missing move and the silent board. The score learnt OCR's split squares and ClearScan's square signs | done: 70.7% |
| 4 | Brunthaler and Tangborn: the white queen on a dark square read as a black piece, the side-to-move marker. KIA and Grand Prix: a diagram that contradicts its line corrects it. Primer: move numbers in OCR forms, capture marks swallowed by the figurine. The score learnt "C4" for c4 and, in the scanned books, OCR's twin letters where the print is no legal move (70.9% to 73.9% on the same readings). Then: notes after a diagram hang from the line that starts there; the game goes on from the diagram before its next move, across notes or an Exercise box; "13 .. .f6" is a pawn's move; an old reading of the decoder returns only if it read its own token nearly as well. The score learnt the Primer's lost f-file letter and a figurine's junk, and dropped the b/h and c/e twins, which hid wrong moves (KIA pp. 95, 144). KIA: Black's moves in the body font and glued numbers; a confident diagram overrules a doubtful line. Brunthaler: boards read with ClearScan's glyphs drawn over them (221 to 312 boards), long notation read by both its squares. Alekhine: Black's numberless move after a heading or an answer (674 moves, no loss). Primer: Black's move number whose dots OCR set apart. A move read through a slip of its square or capture mark turns amber where the line went wrong (silent errors 418 to 294; ten sampled on the page, all wrong as read). The score learnt the Primer's "ffi" for f8. Tried and left out: placing a run around one unreadable move (two runs placed, no gain). KIA: a game goes on from a diagram among its unplaced moves; OCR's letters for a move number read by the numbering around them; a line goes on from a sure diagram whose next moves read from it. Checked on the page and left as they are: amber twin guesses (8 of the 15 costliest are right, so the score's rate is a lower bound) and the fill of a failed move (already chosen with the moves after it). Next: threats and plans shown as variations | running |
| 5 | Hunt on the three lowest books; fixes by cost | |
| 6 and after | Fixes by cost, a hunt every second cycle, until every target is met and the owner says "thanks" | |

## Where things are

- The auditor: `tools/audit/`, `.claude/workflows/book-audit.js`,
  `.claude/agents/book-auditor.md`.
- The merged fixes: branch `claude/audit-fixes`.
- Each fix on its own branch, `audit/<cause>`, approved or not.
- The findings, the causes and the reports: `output/audit/runs/` and
  `output/audit/reports/` in the working copy (not in git).
