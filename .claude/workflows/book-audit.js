export const meta = {
  name: 'book-audit',
  description: 'Audit how the program reads the corpus books and answers corrections, verify each failure on the page, then find and test fixes',
  whenToUse: 'To check the reader against the printed books after a change, or when the program still fails on a book: finds failures, refutes the false ones, groups them by cause, fixes each cause on its own branch with a test, and reviews every fix against all the books.',
  phases: [
    { title: 'Find', detail: 'one auditor per book and lens (reading, correcting) and per app run' },
    { title: 'Verify', detail: 'skeptics, up to six findings each, every one checked on the page' },
    { title: 'Diagnose', detail: 'group the confirmed findings by their cause in the code' },
    { title: 'Fix', detail: 'one branch with a test per cause, in its own worktree' },
    { title: 'Review', detail: 'an adversarial review of each fix against all the books' },
    { title: 'Report', detail: 'what fails, why, and what each fix gains' },
  ],
}

// args (all optional):
//   mode       "full" (default), "find" (find and verify only), "solve" (diagnose, fix, review: needs findings),
//              "fix" (fix and review the causes given in args.causes, as the diagnosis wrote them; a cause
//              with "prior": {branch, problems} goes on from that branch and the reviewer's problems)
//   books      the books to audit (tools/audit/books.py BOOKS); default all but the control, ivanchuk
//   lenses     ["reading", "correcting"] by default
//   app        [{book, device}] runs of the browser app; default [{book: "planning", device: "ipad"}]
//   base       the code digest of the readings to compare with (tools/audit/books.py code_digest())
//   findings   confirmed findings from earlier "find" runs (mode "solve"; tools/audit/runs.py gathers them)
//   findingsFile  the JSON file that holds them in full (runs.py's output): the diagnosis gets a short
//              form of each finding, and the fixers and reviewers read the full one from this file
//   briefFile  a JSON file with the short forms (runs.py --brief): with it, "solve" needs no findings in
//              its args, and the diagnosis and the report read the findings from the files
//   maxCauses  how many causes to fix, worst first (default 8)
//   stamp      a name for the report file (output/audit/reports/<stamp>.md)
//   trailer    the lines that end each commit message (the session's attribution), if any
//   causes     the causes to fix (mode "fix")
//   main       the main checkout, which holds the books (corpus/, primer.pdf) and local/ for worktrees
const A = args || {}
const MODE = A.mode || 'full'
const ALL_BOOKS = ['gpa', 'tangborn', 'brunthaler', 'planning', 'alekhine', 'kia', 'primer']
const BOOKS = A.books || ALL_BOOKS
const LENSES = A.lenses || ['reading', 'correcting']
const APP = A.app || [{ book: 'planning', device: 'ipad' }]
const BASE = A.base || '(run: python3 -c "import sys; sys.path.insert(0, \'tools/audit\'); import books; print(books.code_digest())")'
const MAX_CAUSES = A.maxCauses || 8
const MAIN = A.main || '/home/user/Book-To-Chess-Study-'
const STAMP = A.stamp || 'latest'
const TRAILER = A.trailer ? `, ending with the lines\n   ${A.trailer.split('\n').join('\n   ')}\n  ` : ''

const COMMON = `You are part of an audit of this repository's chess-book reader against the printed books.
Read tools/audit/README.md before anything else: it names the books, the tools, how to judge a reading
against the print, the severities, and what a finding holds. The readings of the books with the current
code are built already (output/audit/${BASE}/); do not run tools/audit/build.py unless you are told to.
The print is the truth: judge only what you have seen on a page picture (tools/audit/page.py, then Read
the PNG it writes; enlarge with --clip). The text layer and the scan are leads, never evidence alone.
Do not change any file under chessbook/, web/, tests/ or tools/ unless you are told to fix.
In a git worktree the books are missing, and the tests that read them are SKIPPED without a word: before
any test or tool, link them (they are ignored by git): ln -sfn ${MAIN}/corpus corpus; ln -sfn
${MAIN}/primer.pdf primer.pdf; ln -sfn ${MAIN}/local local.
The audit's success rate (python3 tools/audit/score.py CODE [CODE]) is the share of each book's printed
moves that the program shows green and reads as printed, with the whole line before them; the aim is 85%.`

const FINDING = {
  type: 'object',
  properties: {
    title: { type: 'string', description: 'one line: what goes wrong, in the reader\'s terms' },
    severity: { type: 'string', enum: ['silent-wrong', 'lost', 'correction', 'app', 'minor'] },
    pages: { type: 'array', items: { type: 'integer' }, description: 'PDF pages (1-based)' },
    keys: { type: 'array', items: { type: 'string' }, description: 'token keys of the moves concerned' },
    printed: { type: 'string', description: 'what the book prints there, as seen on the page picture' },
    program: { type: 'string', description: 'what the program did' },
    expected: { type: 'string', description: 'what it should have done' },
    evidence: { type: 'string', description: 'the commands run and the lines of output that show it' },
    count: { type: 'integer', description: 'how often the pattern occurs in the book (best count you made)' },
    count_method: { type: 'string' },
    cause: { type: 'string', description: 'module, function and why it goes wrong; say "guess" if you did not read the code' },
    repro: { type: 'string', description: 'exact commands that show the failure' },
  },
  required: ['title', 'severity', 'pages', 'printed', 'program', 'expected', 'evidence', 'count', 'cause', 'repro'],
}
const FINDINGS = {
  type: 'object',
  properties: {
    coverage: { type: 'string', description: 'what you examined: pages, lines, corrections, app steps' },
    healthy: { type: 'string', description: 'what the program does right in this book, briefly' },
    findings: { type: 'array', items: FINDING },
  },
  required: ['coverage', 'findings'],
}
const VERDICT = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['confirmed', 'refuted', 'book-error', 'uncertain'] },
    reproduced: { type: 'boolean' },
    what_the_page_shows: { type: 'string' },
    severity: { type: 'string', enum: ['silent-wrong', 'lost', 'correction', 'app', 'minor'] },
    count: { type: 'integer', description: 'your own count of the pattern in the book' },
    cause: { type: 'string', description: 'module, function, lines and mechanism, from reading the code' },
    reason: { type: 'string' },
  },
  required: ['verdict', 'reproduced', 'what_the_page_shows', 'reason'],
}
const VERDICTS = {
  type: 'object',
  properties: {
    verdicts: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, ...VERDICT.properties },
                                        required: ['id', ...VERDICT.required] } },
  },
  required: ['verdicts'],
}
const CAUSES = {
  type: 'object',
  properties: {
    causes: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'a short slug, used in the branch name audit/<id>' },
          title: { type: 'string' },
          where: { type: 'string', description: 'modules and functions' },
          mechanism: { type: 'string', description: 'how the code produces the failures' },
          findings: { type: 'array', items: { type: 'string' }, description: 'finding ids' },
          books: { type: 'array', items: { type: 'string' } },
          impact: { type: 'string', description: 'how many moves or lines it costs, across the books, and how badly' },
          fix: { type: 'string', description: 'the change that would remove the cause' },
          test: { type: 'string', description: 'a generated book that shows it (tests/test_assemble.py make_book and kin)' },
          risk: { type: 'string', description: 'what the fix may break' },
        },
        required: ['id', 'title', 'where', 'mechanism', 'findings', 'books', 'impact', 'fix', 'test', 'risk'],
      },
    },
    unexplained: { type: 'array', items: { type: 'string' }, description: 'finding ids whose cause stays unclear' },
  },
  required: ['causes'],
}
const FIX = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['fixed', 'partial', 'not-fixed'] },
    branch: { type: 'string' },
    commit: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    change: { type: 'string', description: 'what the change does, in a few sentences' },
    test: { type: 'string', description: 'the test added, and that it failed before the fix' },
    tests_run: { type: 'string', description: 'the commands and their results' },
    new_code: { type: 'string', description: 'the code digest of the fixed readings' },
    compare: { type: 'string', description: 'compare.py summary: gains and losses per book' },
    losses_checked: { type: 'string', description: 'every loss, checked on the page, and why it is acceptable or not' },
    score: { type: 'string', description: 'score.py: the success rate of each book before and after' },
    notes: { type: 'string' },
  },
  required: ['status', 'branch', 'change', 'tests_run', 'compare'],
}
const REVIEW = {
  type: 'object',
  properties: {
    decision: { type: 'string', enum: ['approve', 'changes-needed', 'reject'] },
    test_fails_before: { type: 'boolean' },
    test_passes_after: { type: 'boolean' },
    checked_pages: { type: 'string', description: 'gains and losses you looked at on the page, and what you saw' },
    problems: { type: 'array', items: { type: 'string' } },
    reason: { type: 'string' },
  },
  required: ['decision', 'problems', 'reason'],
}

function findPrompt(book, lens) {
  if (lens === 'reading') return `${COMMON}

Audit how the program READS the book "${book}". Run python3 tools/audit/scan.py ${book} and read its
candidates (all of them are in output/audit/${BASE}/${book}.scan.json). Then look at pages, at least 15:
- the first entries of "silent" and "diagrams" (for each, find the FIRST move where the line went wrong,
  which is often several moves before the candidate; the line tool shows the line around it),
- the first "breaks" and "hot_pages",
- at least five pages of your own choosing spread over the book (front, middle, end; game pages and
  explanatory pages), so that you see what the scan cannot flag: printed moves the program did not mark
  at all (page.py --text shows the text layer), variations tied to the wrong move, notes read as the
  game, a game cut into pieces, wrong game headers or chapters, diagrams tied to the wrong move.
For every failure: what the book prints, what the program made of it, the first wrong step, the cause in
the code (read the functions concerned), and how often the pattern occurs in the book (filter the scan
lists or write a short script over books.load("${book}")). Report distinct patterns (at most 12), each
with its clearest instance in the fields and up to two more instances in the evidence. Put the worst
first. If the book reads well, say so and report what little fails.`
  return `${COMMON}

Audit how the program ANSWERS THE READER'S CORRECTIONS in the book "${book}". The reader opens a page,
taps a doubtful move (or a place where the line stops) and makes the right move on the board; the app
then reads on by itself (live.read_on) and asks about the next doubtful or missing move. Reproduce that
with python3 tools/audit/correct.py ${book} --board KEY=SAN (and --connect, --gap, --attach where the
reader would join a sequence; --start FILE and --json FILE let you chain the steps of one session: the
JSON's result.corrections is the set to start the next step from).
Take at least 10 places from the scan's "breaks" and "silent" lists, spread over the book (do not take
two from one game). At each: look at the page, decide what the book prints, make the correction the
reader would make, and judge against the page what the program does: does the line go on correctly,
are the moves it joins and fills those the book prints, does it stop where it should, is the next
question the right one, does an error or a slow answer (over 5 seconds) occur? Go on as the reader would
for up to 4 corrections in a session where the line keeps failing. Also try one correction that the
reader gets wrong (a legal but wrong move) and its removal, and one correction of a diagram's position.
For each failure: the steps, what the book prints, what the program did, what it should do, the cause in
the code (read the functions concerned: assemble._Builder.read_on and its helpers, apply_checked,
suggest, live.read_on), and how often it would occur. Report distinct patterns (at most 12), worst first.`
}

function appPrompt(book, device) {
  return `${COMMON}

Audit the BROWSER APP on the real book "${book}", on a ${device}. tools/audit/app_lib.js opens the book
in Chromium (its head comment lists the helpers; run your scripts with
NODE_PATH=/opt/node22/lib/node_modules node SCRIPT.js; write scripts in output/audit/app/${book}/).
The first open reads the book in the app, which takes minutes: give it a timeout of an hour and run it
once, in the background, while you plan. tests/readon_e2e.js and tests/thread_e2e.js show the sheet's
buttons and the thread's steps.
Do what a reader does: open pages with doubtful moves (python3 tools/audit/scan.py ${book} lists them),
turn Show reading on, tap a doubtful box, make the right move on the board, read the sheet, follow its
next question for a few steps, use Undo, turn pages, reload (open again) and check that the
corrections and the place are kept. Take screenshots and look at them. Compare what the app shows (the
sheet's words, the move list, the board, the outlines) with the reading (tools/audit/correct.py gives
the same correction outside the app) and with the page. Note every console error, every step that
takes more than 5 seconds, anything hidden, stuck or contradictory. For every failure give the steps,
the screenshot paths, what should happen, and the cause in the code where you can find it
(chessbook/review_js.py, chessbook/reader.py, web/driver.py, tools/build_web.py). At most 12 patterns.`
}

function verifyPrompt(fs) {
  return `${COMMON}

You are a skeptic. Another auditor reports these failures of the program; try to REFUTE each of them,
one at a time, as if it were the only one (they come from one book, and one may be right where its
neighbour is wrong):
${JSON.stringify(fs, null, 1)}

For each: reproduce it yourself from scratch with the commands given (and your own). Look at the page
picture and say what the book prints there, in your own words, before you read the finding's claim
again. Refute it when the page shows the program right, when the claim rests on the text layer or a scan
entry alone, when you cannot reproduce it, or when the "failure" is how the program is meant to work by
its own documented rules (read the docstring of the function concerned; a documented rule that misleads
the reader is still a failure). Say "book-error" when the book itself misprints. If it stands, read the
code and state the cause precisely (module, function, the lines, the mechanism), correct the severity if
it is wrong, and make your own count of the pattern in the book. When in doubt, answer "uncertain",
never "confirmed". Return one verdict for every finding, with its id.`
}

function diagnosePrompt(confirmed) {
  return `${COMMON}

These failures of the program were found in the books and confirmed by a second auditor on the page:
${confirmed ? JSON.stringify(confirmed, null, 1) : `they are the "confirmed" list of ${BRIEF} (read all of it)`}
${FULL}
Group them by their cause in the code: one cause is one mechanism that a single change can remove,
whatever books it shows in. Read the code of each cause (chessbook/movetext.py, chessbook/assemble.py,
chessbook/pdftext.py, chessbook/boards.py, chessbook/live.py, chessbook/review_js.py, chessbook/reader.py,
web/driver.py) until you can state the mechanism and the change that removes it, and say how a
generated test book (tests/test_assemble.py make_book, tests/test_read_on.py, tests/test_thread.py)
would show it. Rank the causes by what they cost the reader across the books: silent-wrong before lost
before correction before app before minor, then by count. Keep separate causes separate even when they
live in one function. List the findings you cannot explain.`
}

function branchOf(c) { return c.prior ? `audit/${c.id}-r2` : `audit/${c.id}` }

function fixPrompt(c, round, notes) {
  const br = branchOf(c)
  const start = c.prior ? `
A first attempt is on the branch ${c.prior.branch}, made on older code. Create ${br} from your worktree's
HEAD (git checkout -b ${br}; HEAD holds the fixes merged since), merge ${c.prior.branch} into it, resolve
any conflict in favour of the newer code's behaviour, and then remove what its reviewer found wrong:
${(c.prior.problems || []).join('\n')}
` : `
Create the branch ${br} in your worktree (git checkout -b ${br}).`
  const again = round > 1 ? `
This is round ${round}. The branch ${br} holds the previous attempt: run git checkout ${br}
in your worktree and continue from it (if git says it is checked out elsewhere, run
git worktree list, and git -C <that worktree> checkout --detach, then try again). The
reviewer asked for:
${notes}
` : start
  return `${COMMON}

You are told to FIX one cause of the program's failures, in your own git worktree.
${JSON.stringify(c, null, 1)}
${FULL}
${again}
1. Write a test with a generated book that shows the failure (the tests named in the cause, and the
   README's "Fixing"); run it and see it fail before you change the code.
2. Make the smallest change that removes the cause. No special case for one book: the program reads any
   chess book. Keep the code's style (read the module's docstrings and neighbouring code first).
3. Run the test (it must pass) and the fast tests of the modules you touched (python3 -m pytest
   tests/test_<module>.py -q -x; the browser tests only if you changed the reader or the app; avoid the
   slow e2e suite otherwise).
4. Read the books with your code: python3 tools/audit/build.py ${c.books.join(' ')} first, then all the
   books (python3 tools/audit/build.py; about 15 minutes), and compare: python3 tools/audit/compare.py
   ${BASE} and python3 tools/audit/score.py ${BASE} <your digest>. Look at the page of at least three gains
   and of every loss (page.py with --code for either reading). The success rate must not fall in any
   book; a fall or a loss you cannot justify on the page means the fix is not done: change it.
5. Commit on ${br} with a message in the repository's style${TRAILER}. Then run
   git checkout --detach, so that the branch is free for the reviewer's worktree. Do not push. Report the branch, the commit, the code digest of your readings (compare.py prints the
   folders; python3 -c "import sys; sys.path.insert(0,'tools/audit'); import books; print(books.code_digest())"),
   the comparison and the success rates before and after, book by book.`
}

function reviewPrompt(c, fx) {
  return `${COMMON}

Review this fix adversarially, in your own git worktree. It claims to remove a cause of failures:
CAUSE: ${JSON.stringify(c, null, 1)}
FIX: ${JSON.stringify(fx, null, 1)}
${FULL}

Check out the branch's commit (git checkout --detach ${fx.branch}). Check that the new test fails on the base (check out
the base versions of the files the fix changed under chessbook/, web/ or tools/, run the test, restore
them) and passes on the branch. Run the fast tests of the modules it touched. Read the diff (git diff
HEAD~1 or the merge base) for a special case for one book, a threshold tuned to pass, a change broader
than the cause, or code that contradicts a docstring it leaves unchanged. The readings of the branch are
in output/audit/${fx.new_code || '<its digest>'}/; run python3 tools/audit/compare.py ${BASE} ${fx.new_code || '<its digest>'}
and python3 tools/audit/score.py ${BASE} ${fx.new_code || '<its digest>'} yourself, run the tests that read
the real books (with the books linked: they are skipped otherwise), and look on the page at three gains
and at every loss or changed move (page.py BOOK PAGE --code DIGEST). Approve only when the test shows the
cause, the gains are true on the page, no book's success rate falls without a reason shown on the page,
and no loss stands unexplained. Ask for changes when they are small and clear; reject when the approach is wrong.`
}

function reportPrompt(all) {
  return `Write the audit's report for the owner of this repository, a chess player who reads these books in the
app and corrects the program as they read. Write it in formal English, in full sentences, with a person
or the program acting in each, without em-dashes and without hedging. Write it in Markdown to
output/audit/reports/${STAMP}.md and return the same text.

Order: what the audit covered; the failures that cost the reader most, each with the book, the page,
what is printed and what the program does; their causes; each fix with its branch, what it gains on
which books, what it risks, and the reviewer's decision; what still fails and has no fix yet. Give the
counts that the auditors counted and no others.

The audit's results:
${JSON.stringify(all, null, 1)}
${BRIEF ? `The confirmed and refuted findings themselves are in ${BRIEF}${FILE ? ` (in full in ${FILE})` : ''}.` : ''}`
}

const FILE = A.findingsFile || ''
const cut = (x, n) => (typeof x === 'string' && x.length > n ? x.slice(0, n) + '…' : x)
const brief = (f) => ({ id: f.id, book: f.book, lens: f.lens, severity: f.severity, title: f.title, pages: (f.pages || []).slice(0, 6),
                        keys: (f.keys || []).slice(0, 3), printed: cut(f.printed, 300), program: cut(f.program, 400),
                        expected: cut(f.expected, 300), count: f.count, cause: cut(f.cause, 700) })
const FULL = FILE ? `\nThe full findings (evidence and the commands that reproduce them) are in ${FILE}, by id.` : ''
const idOf = (book, lens, i) => `${book}-${lens}-${i + 1}`

let confirmed = A.findings || []
let refuted = []
let unverified = []
let coverage = []

if (MODE === 'full' || MODE === 'find') {   // ("solve" and "fix" do not hunt)
  const items = []
  for (const book of BOOKS) for (const lens of LENSES) {
    if (book === 'brunthaler' && lens === 'correcting') continue   // it reads no line to correct
    items.push({ book, lens })
  }
  for (const r of APP) items.push({ book: r.book, lens: 'app', device: r.device || 'ipad' })
  log(`Auditing ${items.length} book-and-lens pairs: ${items.map((x) => x.book + '/' + x.lens).join(', ')}`)

  const results = await pipeline(
    items,
    (it) => agent(it.lens === 'app' ? appPrompt(it.book, it.device) : findPrompt(it.book, it.lens),
                  { label: `find:${it.book}/${it.lens}`, phase: 'Find', schema: FINDINGS }),
    (found, it) => {
      if (!found) return null
      coverage.push({ book: it.book, lens: it.lens, coverage: found.coverage, healthy: found.healthy || '' })
      const fs = (found.findings || []).map((f, i) => ({ id: idOf(it.book, it.lens, i), book: it.book, lens: it.lens, ...f }))
      log(`${it.book}/${it.lens}: ${fs.length} findings to verify`)
      const chunks = []
      for (let i = 0; i < fs.length; i += 6) chunks.push(fs.slice(i, i + 6))
      return parallel(chunks.map((ch, k) => () =>
        agent(verifyPrompt(ch), { label: `verify:${it.book}/${it.lens}#${k + 1}`, phase: 'Verify', schema: VERDICTS })
          .then((r) => ch.map((f) => ({ ...f, verdict: ((r && r.verdicts) || []).find((v) => v.id === f.id) || null })))))
        .then((rs) => rs.flat().filter(Boolean))
    },
  )
  const verified = results.filter(Boolean).flat().filter(Boolean)
  for (const f of verified) {
    const v = f.verdict || {}
    if (!f.verdict) { unverified.push(f); continue }
    if (v.verdict === 'confirmed') confirmed.push({ ...f, severity: v.severity || f.severity, cause: v.cause || f.cause,
                                                   page_shows: v.what_the_page_shows, count: v.count || f.count })
    else refuted.push({ id: f.id, title: f.title, verdict: v.verdict || 'no verdict', reason: v.reason || '' })
  }
  log(`${confirmed.length} findings confirmed, ${refuted.length} refuted or uncertain, ${unverified.length} not verified (an agent failed)`)
  if (MODE === 'find') return { coverage, confirmed, refuted, unverified }
}

const BRIEF = A.briefFile || ''
if (MODE !== 'fix' && !confirmed.length && !BRIEF) return { coverage, confirmed, refuted, unverified, causes: [], fixes: [] }

let diag = null
if (MODE !== 'fix') {
  phase('Diagnose')
  diag = await agent(diagnosePrompt(confirmed.length ? confirmed.map(brief) : null), { label: 'diagnose', phase: 'Diagnose', schema: CAUSES })
}
const causes = MODE === 'fix' ? (A.causes || []) : ((diag && diag.causes) || [])
const todo = causes.slice(0, MAX_CAUSES)
if (causes.length > todo.length) log(`Fixing the ${todo.length} worst causes; left for later: ${causes.slice(todo.length).map((c) => c.id).join(', ')}`)

const fixes = await pipeline(
  todo,
  (c) => agent(fixPrompt(c, 1, ''), { label: `fix:${c.id}`, phase: 'Fix', schema: FIX, isolation: 'worktree' }),
  (fx, c) => fx && fx.status !== 'not-fixed'
    ? agent(reviewPrompt(c, fx), { label: `review:${c.id}`, phase: 'Review', schema: REVIEW, isolation: 'worktree' })
        .then((rv) => ({ cause: c, fix: fx, review: rv }))
    : { cause: c, fix: fx, review: null },
  async (r) => {
    if (!r || !r.review || r.review.decision !== 'changes-needed') return r
    const fx2 = await agent(fixPrompt(r.cause, 2, r.review.problems.join('\n')),
                            { label: `fix2:${r.cause.id}`, phase: 'Fix', schema: FIX, isolation: 'worktree' })
    if (!fx2) return r
    const rv2 = await agent(reviewPrompt(r.cause, fx2), { label: `review2:${r.cause.id}`, phase: 'Review', schema: REVIEW, isolation: 'worktree' })
    return { cause: r.cause, fix: fx2, review: rv2, first: { fix: r.fix, review: r.review } }
  },
)

phase('Report')
const all = { coverage, confirmed: confirmed.map(brief), refuted, unverified: unverified.map(brief), causes, unexplained: (diag && diag.unexplained) || [],
              fixes: fixes.filter(Boolean), left: causes.slice(todo.length) }
const report = await agent(reportPrompt(all), { label: 'report', phase: 'Report' })
return { ...all, report }
