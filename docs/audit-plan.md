# The audit plan: cycles to 85%

The audit hunts the program's errors on the eight books and fixes them, in
cycles, until the owner says "thanks". Each cycle ends with the measures
below taken again, so that every cycle shows what it gained.

## The targets

| measure | how it is taken | start | now | target |
|---|---|---|---|---|
| Success rate, all books | `tools/audit/score.py`: printed moves shown green and read as printed, with the whole line before them | 62.5% | 63.8% | **85%** |
| Success rate, each book | the same, book by book | see below | see below | **85% each** |
| Problems solved | confirmed findings whose causes are fixed and merged | 0 of 140 | 10 of 140 | **119 of 140 (85%)** |
| Silent errors | green moves that the print contradicts (`score.py`, "wrong") | 1,001 | 828 | **under 100** |
| App failures | confirmed app findings still open | 7 | 7 | **0** |
| Tests | the fast suite and the browser tests | pass | pass | **pass, every cycle** |

The success rate of each book, and the milestone each book must reach:

| book | start | now | after cycle 3 | after cycle 5 | end |
|---|---|---|---|---|---|
| Ivanchuk (the control) | 100.0% | 100.0% | 100% | 100% | 100% |
| Alekhine | 86.9% | 86.6% | 88% | 90% | 90% |
| Tangborn | 75.3% | 79.1% | 82% | 85% | 85% |
| Grand Prix | 67.6% | 66.7% | 75% | 82% | 85% |
| Primer | 61.0% | 61.0% | 68% | 78% | 85% |
| KIA | 44.7% | 52.2% | 62% | 75% | 85% |
| Planning | 29.6% | 28.7% | 45% | 65% | 85% |
| Brunthaler | 0.0% | 0.0% | 30% | 60% | 85% |
| **All books** | 62.5% | 63.8% | **70%** | **78%** | **85%** |

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
| 2 | Planning: move-number anchor, b/h and c/e twins, numbers beside a board, ClearScan's f3, wide boards. Brunthaler, KIA, Grand Prix: diagram captions, split squares, moves font per page, glued moves, moves at a line's end. App: taps after a gap, the eye on the phone, saving the reading, Undo, the silent board | running |
| 3 | Hunt on Brunthaler, Planning, KIA and the app; then the fixes sent back in cycle 2 and the next causes by cost | |
| 4 | Fixes: the certainty ceiling (silent errors), the diagram that contradicts its line, reading on (stops at notes, refuses its own continuation) | |
| 5 | Hunt on the three lowest books; fixes by cost | |
| 6 and after | Fixes by cost, a hunt every second cycle, until every target is met and the owner says "thanks" | |

## Where things are

- The auditor: `tools/audit/`, `.claude/workflows/book-audit.js`,
  `.claude/agents/book-auditor.md`.
- The merged fixes: branch `claude/audit-fixes`.
- Each fix on its own branch, `audit/<cause>`, approved or not.
- The findings, the causes and the reports: `output/audit/runs/` and
  `output/audit/reports/` in the working copy (not in git).
