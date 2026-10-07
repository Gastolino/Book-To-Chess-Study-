# Book to Chess Study

This project turns a chess book in PDF form into FENs and PGNs, and from those
into private Lichess studies. It works on any chess book; *The Soviet Chess
Primer* (Maizelis) is the first book used to test it.

Each stage writes an HTML report for checking before the next stage runs.

| Stage | Script | What it does |
|---|---|---|
| 1 | `stage1_inspect.py` | Finds out what kind of PDF the book is, finds the board pictures and lists every diagram number in the text. |
| 2 | to come | Cuts out every board. |
| 3 | `chessbook/boards.py` | Reads each board picture into a FEN, with a confidence for every square. |
| 4 | to come | Decodes the moves in the text into legal moves. |
| 5 | to come | Assembles one PGN chapter per diagram or game. |
| 6 | to come | Uploads the chapters to Lichess. |

## Kinds of PDF

Stage 1 sorts every page into one of these kinds, and later stages choose
their method page by page:

- **scan**: the page is one photograph, usually with an invisible OCR layer.
- **pictures**: the text is type (typeset, or redrawn from a scan by Acrobat
  ClearScan) and each diagram is a separate embedded picture.
- **text**: typeset pages whose diagrams are drawn from shapes or a chess font.

A diagram printed as text in a chess diagram font (as ChessBase and Fritz
export them, and as the Chess Merida, Chess Alpha and similar fonts print
them) holds its position in the text layer. Stage 1 reads such a diagram
directly into a FEN (`chessbook/textdiagram.py`), takes the side to move from
the text around it, and lists it with the board pictures, so the moves after
it decode at once.

Books set with figurine fonts (for example ChessBase's "CB...Link" fonts)
often give each piece figurine as a private character code. The program
learns from the book which code stands for which piece and reads the letter
in its place (`chessbook/figurines.py`), so "Nxe6" is read as printed.

Some converters write the book's title into its text. calibre printed the
title of Tangborn's book inside a line of moves, glued to the move number
and followed by a scrap of its header template ("10A Chess Opening for
White: ... a Fischer Favoriterend:>.Nf1 Bd7"). The program takes the title
that the PDF records out of a line where it stands glued to other words, so
that the line reads "10.Nf1 Bd7"; a title page and a sentence that names the
book keep it (`chessbook/pdftext.py`, `drop_injected`).

## Reading the boards

Stage 3 reads every board picture without any labelling by hand. It finds the
8 by 8 grid in the picture (and reports a picture that shows only part of a
board), separates the pieces from the squares, hatched or plain, and groups
the piece drawings of the whole book, since a book draws each piece the same
way every time. It then names the groups from where their pieces stand
(kings on g1, rooks on a1, no pawns on the first rank), from the outline of
reference pieces, from the rule of one king a side, and from positions the
book already gives (a printed initial position, or a position that a decoded
line reaches at a diagram). Squares it is unsure of are listed as doubtful,
and the reader marks them with a dashed outline. Printed coordinates show
when a board is drawn from Black's side, and a caption such as "(B)" or
"Black to move" gives the side to move.

`tools/make_piece_refs.py` draws the reference pieces into
`chessbook/assets/pieces.npz`; `tests/data/board_truth.json` holds 76
positions checked by eye against the pictures of five books.

## Reading figurines by their shape

Scanned books print their moves with piece figurines, and the text
recognition turns each figurine into junk: "i>" or "\x14" for a king, "tLl"
for a knight, "i." for a bishop. The program learns from the book which junk
stands for which piece, but junk that it sees seldom, or junk that stands for
two pieces, would leave the piece to legal play alone. So the program also
reads the picture of every such figurine (`chessbook/figshapes.py`), as it
reads the pieces of the diagrams, without any labelling by hand:

- it finds where the junk characters stand on the page, draws that part of
  the page as it is displayed (the redrawn type of a ClearScan page, the
  picture of a scanned page) and cuts the figurine out of the ink;
- it groups the cuts of the whole book, since a book prints each figurine
  the same way every time (five pieces, in each style of figurine the book
  uses);
- it names each group from the moves it already reads with certainty (a move
  whose square only one kind of piece can reach in that position), and a
  group with too few such moves from reference figurines of other books
  (`chessbook/assets/figurines.npz`);
- the decoder then reads the piece that the picture shows unless legal play
  rules it out, and the reader puts no eye on a symbol whose picture names
  its piece surely.

Books whose text names the pieces (letters, or a figurine font) are left as
they are, and so is every book when OpenCV is missing. The figurines are
read after the first reading of the moves (in the app, with the board
pictures, before the final reading) and add about six seconds to the
reading of the Primer. `tools/make_figurine_refs.py` collects the reference
figurines from books that name their figurines well;
`tests/data/figurine_truth.json` holds 240 cuts of four books checked by eye.

## Using the app

Open the published site (<https://gastolino.github.io/Book-To-Chess-Study-/>),
choose **Add a book** and pick a chess book PDF, and read it beside a live
board. The book is processed in your own browser (Python runs there through
Pyodide) and is never uploaded. The first visit downloads about 40 MB; later
visits start at once.

### Opening a book

A book opens as a book does in the Books app: at its first page (the cover
and the front matter), in the reader, as soon as that page can be shown,
even while the program still reads the book; the moves appear on the pages
as they are read. A book opened again from the library opens at the page
and move last read, and a bookmark opens it at the bookmark. The contents
(the chapters, their pages and the selection) open only with **Contents**
in the reader's top bar; **Back to page 31** at the top, or the browser's
back, returns to the page.

The front matter is read like the rest of the book: its pages are ticked in
the contents, and the moves of an introduction (its games and diagrams) are
read. Its table of contents gives no moves: a sequence that the program
cannot place, such as "2...Nc6" listed with a page number, stands in no line
and is listed in the Review. Untick the pages to leave them out.

### One book, page after page

The pages run on from one chapter to the next: the arrows, a swipe and Page
Down on the last page of a chapter show the first page of the next chapter
(the reader of that chapter is built while you read the last pages of the
one before, and takes its place without an empty page between them), and
going back from a chapter's first page shows the last page of the chapter
before. The page counter counts the whole book ("47 of 386"), and a page
number typed into it opens that page in whatever chapter holds it.

A page turns by sliding: during a swipe the page follows the finger, and let
go past a quarter of its width (or flicked) it slides out while the next
page slides in from the other edge; a shorter swipe puts it back. The arrows
and Page Up and Page Down turn with the same slide. On an enlarged page the
reading goes on where it naturally does: a turn forward shows the next
page's top left, and a turn back the previous page's bottom right, just
above the board at the foot of the screen. A turn into the next chapter
does the same: the place of the next page slides in, and the next chapter
shows that page there. With the system's setting for reduced motion the
page changes at once.

The pictures of the pages are drawn ten pages at a time: the ten pages
around the page shown first, then the ten after them, then the ten before.
A page whose picture has not come yet shows a light sheet of its size, which
fills in when the picture comes; the moves, the board, the bookmarks and the
corrections work on it at once. The app keeps the pictures of those thirty
pages only, so that a phone keeps the reader open. The pictures it draws
are kept on the device (in the browser's storage, apart for a phone and for
a larger screen), so the next opening shows them without drawing them; they
go with the book when it is removed, and when the device has no room left,
the app stops keeping them and says so once. On the Cloudflare site the
pictures are kept on each device as well, not on the site.

### The sign of work

While the app starts, and while a book is read before its first page shows,
the start page shows an open book whose two pages are chequered like a
board, with a page turning over, above a thin bar that fills as far as the
work has come where the app knows it, and the words of the work under it.
In the reader, the same small book stands at the right of the top bar while
the program works (reading the moves, drawing pages, saving the reading); a
tap on it says what it is doing, and it goes when the work is done. With
reduced motion set on the device, the page does not turn. The book with its
two chequered pages is also the app's icon (`web/icon.svg`;
`tools/make_icons.py` draws the icons of the Home Screen, the manifest and
the browser tab).

### Your library on each device

The start page is your library on this device: each book with a picture of
its first page, its title, the page last read ("Page 47 of 402") and the day
it was last opened. The browser keeps the books itself (in its IndexedDB
storage), so nothing leaves the device:

- **Add a book** reads a PDF once, as described below, and then keeps the
  PDF, the program's finished reading (compressed), the cover picture, the
  title and the page count. The browser is asked at the same time to keep
  this storage for good.
- A tap on a book opens it from the kept reading without reading it again,
  with your corrections and selection, at the chapter, page and move last
  read. A small book opens in about a second; the Primer opened in 9
  seconds in Chromium on a desktop, where reading it took six minutes in
  the same test.
- The kept reading is what the program read in the book, never the pages
  built from it: the reader and the contents are built from it by the
  program of the day, so a new version of the reader, the app or their look
  keeps every reading. When the code that reads the books has improved
  since, the book opens from its kept reading all the same, with one line,
  "An improved reading is available", and **Read again** in the top bar;
  the book is read again only when you press it, with your corrections,
  bookmarks and place. A reading that the new program cannot take
  corrections on opens for reading, and the line says that corrections need
  the book read again.
- **Remove** deletes the book, its reading, its corrections, its selection,
  its place and the pictures of its pages, after a question.
- A quiet line under the books says how much room the library takes. The
  Primer takes about 15 MB: the PDF 11 MB and the reading 4 MB. When the device has no room left,
  the app says so and opens the book for the moment without keeping it.

### Coming back to the open book

An iPhone or iPad drops a page left in the background for too long, and
the app then starts afresh when it is opened again. The app keeps a small
note of where the reader was (the book, the chapter, the page, the move and
how far the page and the move list were scrolled), written a moment after
each change and at once when the app goes to the background. When the app
starts again within a day, it skips the library page and opens that book at
that place from its stored reading, with one line in the top bar ("Back to
The Soviet Chess Primer, page 31") and the **Library** link beside it. A
book whose reading was not finished when the system closed the app is read
again, from the same page, and the line says so. The place last read is
written to the library at once as well when the app goes to the background,
so nothing is lost. **Library** forgets the note. On a site where the
browser keeps no library (a private window), the start page says that the
book has to be chosen again; chosen again, it opens at that place.

On an iPhone or iPad, Safari may clear the storage of a site that has not
been opened for seven days. An app added to the Home Screen keeps its
storage: open the site in Safari, choose the share button and **Add to Home
Screen**, then open the app from the Home Screen and add your books there.
The Home Screen app has a library of its own, apart from Safari's; the
library page says this in one line (with **Hide this note**) until the app
runs from the Home Screen.

### Moving a book to another device

Each device keeps its own library; nothing is copied between devices by
itself. To move a book, choose **Save to Files** next to it (on a Mac,
**Save a copy**). The app writes one file, "<title>.chessbook", that holds
the PDF, the program's reading, your corrections, your selection, your
place, the cover and the title. On an iPhone or iPad the share sheet opens:
choose **Save to Files** (for instance into iCloud Drive) or AirDrop; on a
Mac the file goes to the Downloads folder. On the other device, choose **Add
a book** and pick that file: the book opens at once from the reading in it,
with the corrections, at the same place, and stays in that device's library.
If the file was made by another version of the program, the book is read
again, with the corrections. If the library holds the book already (the same
PDF), the newer of the two sets of corrections wins, and the page says which.
The file is an ordinary zip archive; `book.pdf` inside it is the book.

### Bookmarks

The bookmark icon in the reader's top bar (and in the bar at the foot of a
phone screen) marks the page shown, with the move chosen on it. The icon
fills in a warm yellow on a bookmarked page, and a yellow ribbon hangs from
the top edge of the page picture, in the margin beside the moves. A tap on
the ribbon (or on the filled icon) removes the bookmark; one line over the
page's corner says "Bookmark removed" with Undo for a few seconds. A book
holds any number of bookmarks, one per page. The contents page lists them
("Bookmarks: page 31, page 57"), each a link that opens the chapter at that
page and move, and the library lists them under each book ("Bookmarks on
pages 31 and 57"), where a tap opens the book there. The bookmarks are kept
with the corrections: in the browser, in the site's library, and in the book
file, so that they travel to another device; the newer copy wins.

The reader names the book by its title in words. It takes the title the PDF
records (without the "Microsoft Word -" that some converters put before it),
else the title page's largest type with its subtitle ("The Art of Planning in
Chess: Move by Move"), else a title made from the file's name, without the
underscores and the author's names in front ("lakdawala_cyrus_the_alekhine_defence"
gives "The Alekhine Defence").

The book can be read while it is processed. As soon as the program knows the
book's chapters (a few seconds), the book opens at its first page, and every
page can be turned and swiped. The top bar says how far the
reading has come ("Reading the moves: chapter 3 of 11") above a thin moving
line. The moves then appear chapter by chapter, the first chapters first; a
chapter that the reader opens is read before the others. These first readings
use what the program has learnt so far, and reading mode ("Show reading") says
so. When the program has read the whole book (its glyph passes, the figurines
and the board pictures), the open chapter receives the final reading in place, and
the page and the chosen move stay put; the other chapters receive it when
they open. Corrections made meanwhile apply at once to the open chapter and are
part of the final book, which is the same book the command line makes. The
Primer (402 pages) takes about three minutes in all on a desktop browser; each
chapter then opens in about two seconds. `chessbook/progressive.py` describes
how the work is divided.

The workflow in `.github/workflows/pages.yml` rebuilds and publishes the site
whenever `main` changes. `python3 tools/build_web.py --help` builds it by hand.
`tests/test_app_e2e.py` runs the whole app in Chromium (`tests/app_e2e.js`)
with a local Pyodide folder (`CHESSBOOK_PYODIDE`) and the PyMuPDF and
python-chess wheels for Pyodide (`CHESSBOOK_WHEELS`); `CHESSBOOK_APP_BOOK`
names another book to read than the generated test book.
`tests/test_book_flow.py` runs the book flow on an iPhone 13 and an iPad
held sideways (`tests/flow_e2e.js`): the sign of work, a new book at its
first page, the pages across chapters, the pictures ten at a time with
their placeholder, and a kept reading made by other reading code.

## A private library on Cloudflare (optional)

The library on each device, above, needs no account anywhere. The same app,
published on Cloudflare (`.github/workflows/cloudflare.yml`),
keeps a library for one person behind Cloudflare Access. Its start page lists
the books with a picture of the first page, the title, the page last read
("Page 47 of 402") and the day the book was last opened; "Add a book" adds
one, and "Remove" deletes one after a question. A book is still read in the
browser, once; the site stores the PDF, the program's finished reading (for
the Primer about 4 MB, compressed from 19 MB), the cover picture, the
corrections, the selection and the place last read. Another device then
opens the book from the stored reading without reading it again, with the
corrections, at the page and move last read. A stored reading made by an
older version of the program is replaced: the book is read again when it
opens.

Corrections, the selection and the place are written to the browser's
storage as before and sent to the site a moment later; a change made offline
is sent when the connection returns, and on opening a book the newer copy
wins. The site only stores: `server/app.js` (Pages Functions, with an R2
bucket for the files and a D1 database for the records, `server/schema.sql`)
answers under `/api/`, and the app finds out from `/api/books` whether it
runs there. Anywhere else (GitHub Pages, or the built site opened from a
folder) the library lives in the browser, as described above, and nothing
leaves the device. Both libraries are one page and one code path in
`web/library.js`, with two stores: the server's and the browser's.
`docs/CLOUDFLARE.md` gives the setup in plain steps; `tests/test_library.py`
runs the server under `wrangler pages dev` and the library end to end
(`tests/library_e2e.js`). `tests/test_device_library.py` runs the library in
the browser on the static site (`tests/device_library_e2e.js`): adding,
opening after the browser starts again, the book file into a fresh profile,
and removing.

## Correcting what the program could not read

Each chapter reader has a Review button. It lists, in page order, every place
where the program is unsure: diagrams with doubtful squares or no reading,
moves chosen between several readings, moves it could not read, moves that
the book's text lacks, and moves that it placed in no line. Above them it lists the piece symbols that the
text recognition could not name (in scanned books a figurine often becomes
junk such as "tLl"), the most frequent in the book first. A click on an item
shows it on the page and on the board, with the choices to correct it:

- a diagram: a tap on a square, then on one of thirteen pieces (or the empty
  square), and the side to move; the program accepts only a position with one
  king of each colour;
- a move: one of the readings the program considered, or a move typed in the
  book's letters, which the program accepts only when it is legal there;
- a sequence placed in no line: the move of the line it replaces, "Not a
  variation", or "Continue a line…";
- a gap in the text: the moves the text lacks, one at a time (see below);
- a piece symbol: one of the six pieces. The choice applies to every move of
  the book printed with that symbol (the eye on the page opens the same
  choice).

A tap on a move that the program could not read (a red move, on the page or
in the move list) opens its corrector at once, pencil or no pencil; on a
phone it opens as a sheet above the bar at the foot of the screen. A tap on
another move only chooses it. A piece moved on the board corrects a move as
well (see "Correcting by moving pieces on the board" below).

Where the book's text lacks a move (the move list shows "…" in its place),
the program cannot follow the line, and the moves after it stay red: their
position is unknown. The board then shows the last position the program
knows, before the gap. A tap on the gap, or the button "Give Black's move
10" in the corrector of a red move after it, opens the gap's corrector: it
lists the legal moves of the position before the gap and takes a typed move.
When the text lacks several moves, the corrector asks for them one at a
time; "Remove the moves you gave" takes them back. The program never
supplies such a move itself. Once the moves are given, the line reads on
from them, and the moves after the gap decode; the Review list names every
gap of the chapter.

The pencil in the reader's top bar (and in the bar at the foot of a phone
screen) corrects anything on the page, not only what the program doubts.
With the pencil on, a tap on a move, a diagram or a sequence opens its
corrector. The corrector of a move also changes the line it belongs to:

- "Start a new line here" starts a separate line with this move, from the
  position before it; "Start a new line here from a diagram" starts it from a
  diagram of this page or the page before;
- "Not part of this line" takes the moves from this one to the end of the
  line out of the line, so that they stand in no line;
- "Continue the line…" joins the line (from its first move) to another line:
  a tap on the move after which it follows, on this page, another page or in
  the move list, completes the join. The moves continue that line when the
  move ends it, and form a variation from it otherwise. The program refuses
  a join whose first move is not legal there and says why.

A move printed without its move number after a comment ("10.Nd3 Every swap
helps Black. b5 11.Bb3"), which the program could not confirm as the line's
next move (see "Lines that go on"), stands in no line and is an item of the
Review list. Its corrector offers "Continue the line after 10.Nd3", the move
the text prints it after, as the first choice; a tap on it joins the move
there, and the numbered moves after it then go on from it, since the
numbering now fits (the join is applied right after the move it follows, so
the moves printed after it find the line gone on). The other choices stay:
another move of a line, "Continue a line…" with a tap on any move, or "Not
a variation".

Moves that the book prints but the program found nowhere (no box on the
page) are read with "Read a section", the dashed rectangle beside the
pencil in reading mode (and in the bar at the foot of a tablet's screen).
With it on, a drag across the moves draws a rectangle round them, and a tap
takes the word under the finger; with the pencil on, a tap on the page where
no box stands does the same. The rectangle keeps its place on the page when
the page is enlarged; its corners change its size and a drag inside it moves
it. The sheet that opens says what the program reads there (in the browser
app, which reads the page's text with the book's own reading of its piece
symbols) and offers its readings as buttons, and it takes the moves typed in
standard notation, checked move by move as they are typed: a move that is
not legal is named with the reason. The moves go after the chosen move or
before it, as alternatives to it; after the last move of the main line they
continue the main line, or form a variation, as you choose. A tap on another
move, on the page or in the move list, chooses that move instead. The moves
then stand in the move list and in the PGN, each with a box on the page (the
box of its printed word when the section prints as many moves, else the
rectangle), and a tap on a box with the pencil opens the section again to
change or remove it. A reader built from the command line shows such moves
at once; the next run writes them into the book.

In the browser app every correction applies at once: the worker replays only
the lines it touches and sends the open chapter its changes, so the board,
the move list, the outlines on the page and the Review list change while the
page and the chosen move stay put. A piece symbol reaches the open chapter
first and then the other chapters, one at a time, while the reader goes on
reading; a chapter opened before its turn gets the piece first. A chapter
that opens with corrections stored in the browser that the book does not
hold yet sends them at once. Read again is needed only after a change of the
selection (pages and diagrams included or left out). The browser keeps the corrections for
each book, and reading the book again applies them with the same result.

In a reader built from the command line, the contents page's "Copy
corrections" button copies the corrections; `python3 make_reader.py book.pdf
--corrections FILE` saves the pasted text as `books/<book>/corrections.json`,
which every later run applies (`chessbook/corrections.py` describes the
format). A corrected item shows in the colour of a decoded move, with the
words "Corrected by you", and the contents page counts the corrections a run
used.

### Correcting by moving pieces on the board

The board in the panel takes moves: drag a piece to its new square, or tap
the piece (it gets a thin blue outline, and a small dot marks each square it
can reach) and then tap that square. On a phone the small board in the bar
at the foot of the screen takes moves as well, and so does the board of a
diagram that starts a line. The board accepts only legal moves from the
position it shows; a piece dropped anywhere else goes back to its square. A
pawn that reaches the last rank asks for the piece it becomes. What a move
does depends on the line:

- the move the line plays next (or a variation the book gives there) steps
  to it, as the arrow does;
- where the book's text lacks a move, the move fills the gap, as the gap's
  corrector does;
- any other move opens a short choice, above the bar on a phone and below the
  board elsewhere: "Correct the main line: 12.Nf3 instead of 12.Nd2" makes
  the book's move read as yours, and the program reads the rest of the line
  from it; inside a variation the same choice reads "Correct this
  variation"; "Add a new variation" keeps your move as a variation of your
  own, branching here; "Cancel" puts the board back.

A variation you added shows in the move list with a green dot before its
first move and the words "Added by you". Further moves from its last position
make it longer without a question. "Change your variation" below a move of
it opens its corrector, with "Remove this variation" and, for a later move of
it, "Remove from 14.Be2 on". The Review list names each place where you added variations, the PGN
download holds them as variations with the comment "Added by the reader",
and they travel with the other corrections (part "added" of the
corrections), through Read again, the book file and a new build. In a reader
built from the command line the board shows your move at once, and the next
run, with the corrections copied into the chat, adds it to the line.

## Analysis with Stockfish

The board panel of every chapter reader carries a small processor icon next
to the icon that turns the board round. A tap on it turns analysis on: the
chess engine Stockfish 19 (Stockfish.js by Nathan Rugg, the lite
single-threaded build, free software under the GNU General Public License,
version 3; see `docs/THIRD_PARTY.md`) analyses the position the board
shows, whatever it is: a move of the book, a variation you added on the
board, or the preview of a move you have just made. The engine runs on
your own device, in a worker of the browser, and sends nothing anywhere.

- A thin bar along the left side of the board shows the evaluation, White's
  share from the bottom (from the top when the board is turned round), with
  the figure at its foot: "+0.8" for White, "−1.3" for Black, "M3" for a
  mate in three. The figure is always from White's point of view.
- A section between the board's controls and the title of the line lists
  the engine's lines, one row each: its evaluation and its moves, numbered
  from the shown position. A tap on a row plays its first move on the
  board, through the same choice as a piece moved by hand: the book's move
  steps, any other move corrects the line or adds a variation of your own.
  So the evaluation of a new variation is one tap away. A quiet line above
  says how deep the engine has looked; "Deeper" lifts the limit for this
  position.
- Stepping through the moves analyses each position after a short pause;
  the engine stops when its limit is reached, pauses while the page is
  hidden, and stops when analysis is turned off or the chapter is left, so
  that it drains no phone. On a phone the processor icon stands in the bar
  at the foot of the screen as well, and the figure shows next to the
  current move.
- What the engine finds is kept on the device, for each position and number
  of lines (the deepest result so far, for at most 5000 positions, the ones
  used longest ago going first). A position shown again shows its kept
  result at once, with "kept from an earlier analysis", and the engine
  searches it only when the limit in the settings asks for more; "Deeper"
  always searches. A reader built from the command line keeps them too
  where the browser allows storage, and in memory otherwise.
- The gear beside the icon opens the settings: the number of lines (1 to
  5), where the search stops (a depth, 18 by default, or a time per
  position), whether every shown position is analysed or only the one shown
  when the icon is pressed, an arrow for the best move on the board, and the
  engine's memory (16 or 32 MB). The settings are kept in the browser. The
  foot of the settings names the engine and its licence.

The engine (1.8 MB) is loaded the first time analysis is turned on, not
before, so the site stays light; the browser then keeps its two files in
its storage, and analysis works offline afterwards, in the Home Screen app
as well. Safari on iOS 16 and macOS 11 and later and every current browser
run it. `.github/workflows/pages.yml` fetches the engine with
`tools/fetch_engine.py`, which checks the files against pinned checksums,
and `tools/build_web.py --engine` copies them into the site. A reader built
from the command line offers analysis when the engine files stand beside
it: `python3 tools/fetch_engine.py local/engine` once, then
`python3 make_reader.py book.pdf --engine local/engine`; without them the
processor icon says that the engine is not installed. A reader opened as a
file (not through a web server or the app) cannot start the engine in most
browsers. `tests/engine_e2e.js` runs the analysis in Chromium.

## Lines that go on

A line stays one line across columns, pages and chapter files while its
moves go on: a run that continues the numbering of a line that stopped
earlier ("4… e4" after a digression with other moves or a diagram) and reads
as legal play from where it stopped continues it, unless a word such as
"Or", "Instead", "If" or "After", or a bracket, makes it an alternative.
When a page opens in the middle of a line, the reader lists that line first
under "On this page" and shows its position at the top of the page.

Moves printed in long notation ("e2-e4", "Ng1-f3", "Bf1–b5", "d2xd3")
are read strictly: the piece must stand on the square the text names. The
structure of the sentence decides what such a move without a move number
is. Right after numbered moves of a note and joined to them by "and then",
"followed by", "then", "with" or "and" ("8.Rd1 and then Nb1–c3"), it goes on
with that variation when it is legal there, and otherwise stays text in it.
Introduced by "Or", "Instead", "If", "after", "then" or a bracket with other
moves, or printed next to a move of the other side ("...d5xe4 and d3xe4"),
it is a variation where the line stands, or stands in no line with the
reason. Alone in a sentence ("the potential to gain space with f2-f4"), it
is text. A move that the line played ("once Black has played ...e7-e6")
names that move, and a tap on it shows that position: the move must leave
the same square for the same square, and be the most recent such move of
the main line or of a variation of the same note.

Games are told apart by their headers, whether on one line ("Alekhine -
N.N., New York 1924") or on one line a player ("White: V. Kramnik" over
"Black: D. Sadvakasov"); after a header, no line of the game before gives
the starting position of the moves. Books that set the main moves in one
style of a type and the moves of the notes in another (bold and italic of
one family) have their italic moves read as notes, never as moves of the
game. A line whose moves stop reading (the text lacks a move, or two moves
in a row cannot be read) takes up again at the next diagram printed among
its moves: the moves after the diagram start from the position it shows, as
a line of their own, instead of standing unread in the line before. The
same holds for a run of moves from move 1 that does not read from the
initial position: its moves after a diagram printed among them start from
the diagram. A diagram printed among the moves a line has read does not end
it when a run of the main font that follows reads as a variation where its
numbering puts it ("25...fxe5" after the line has gone on to move 34); such
a run is a variation there, even if it would also read as legal play at the
line's end. A run that only offers another move for the line's last move is
no such variation: that last move is more likely a stray of a note before the
diagram, and the run goes on with the game from the diagram.

Inside a bracket, a run whose numbering goes on from the variation before it
in the same bracket continues that variation: in "1.Ra7+ Kg8 (1...Kh6 is met
by the waiting move 2.Rb7, while if 1...Kh8 then 2.Kg6) 2.Kf6", 2.Rb7 follows
1...Kh6 and 2.Kf6 stays the move after 1...Kg8.

Annotators often follow a move with a comment and print the reply without
its move number: "10.Nd3 Every swap helps Black, so White retreats. b5
11.Bb3 a5 12.a3". Such a bare move is the line's next move when the text
and the moves agree: it is the last word before a numbered run (the words
between may only join them: "b5, and then 11.Bb3"), it looks like a move
with its rank printed and carries no stop or comma, it is the only move in
its sentence, no word such as "Threat", "idea", "plan", "intending" or
"in mind" stands in its clause ("Threat: Qxf7 mate!" stays text), the
numbered run after it continues the numbering of the line in progress
exactly (the next move number, the other side), the bare move is legal for
the side to move at that line's end, and the run reads cleanly after it.
It then goes with the line even where the run would also read as a
variation elsewhere, since a legal bare move that makes the numbering fit
is the stronger evidence. The line in progress is the latest variation of
the same note and bracket, or the main line's end; in the game itself the
reply may stand in the notes' font between the moves of the move font
("7.Bd3 Every swap helps Black. Nbd7 8.Qc2"), and the run is then read in
two parts. A bare move that ends a variation inside a bracket, with no run
after it, is read only in the narrow case where a colon introduces it
("walks into a trick which all Alekhiners should be familiar with: Qxd4!
picking off ..."), it is the only move of its sentence, no such cue stands
in the clause before the colon and it is legal at the variation's end;
anywhere else a bare move with no numbered run after it stays text. In the
reader, a bare move that passes the text's tests and is legal at the line's
end, but whose numbered run does not read on from it, is listed as a
sequence placed in no line, with "Continue the line after 10.Nd3" as its
first choice (see the pencil below).

In the reader, an eye marks a piece symbol on the page only when the program
is unsure of that symbol; a move it doubts for another reason (its square,
say) whose symbol the book has taught it well shows no eye. The eye is drawn
on the move's corner, sized to the print, so it hides no other words.

## Running it from the command line

```
pip install --use-pep517 -r requirements.txt
python3 make_reader.py path/to/book.pdf
```

One command inspects the book, decodes its moves and writes the reader to
`output/<book name>/reader/index.html`, with one reader per chapter beside
it. Each chapter file holds the pictures of its pages, so the folder works
offline, opened as files; the page arrows and a swipe run on from one
chapter file to the next, as in the app. The Primer (402 pages) takes about 100 seconds; a short typeset book
takes a few seconds. Book PDFs and the output folder are kept out of git.
