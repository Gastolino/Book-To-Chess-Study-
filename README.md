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

## Using the app

Open the published site, drop a chess book PDF on the page, and read it beside
a live board. The book is processed in your own browser (Python runs there
through Pyodide) and is never uploaded. The first visit downloads about 30 MB;
later visits start at once. The Primer (402 pages) takes about three minutes
on a desktop browser; each chapter then opens in about two seconds.

The workflow in `.github/workflows/pages.yml` rebuilds and publishes the site
whenever `main` changes. `python3 tools/build_web.py --help` builds it by hand.

## Correcting what the program could not read

Each chapter reader has a Review button. It lists, in page order, every place
where the program is unsure: diagrams with doubtful squares or no reading,
moves chosen between several readings, moves it could not read, and moves
that it placed in no line. Above them it lists the piece symbols that the
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
- a piece symbol: one of the six pieces. The choice applies to every move of
  the book printed with that symbol (the eye on the page opens the same
  choice).

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

In the browser app every correction applies at once: the worker replays only
the lines it touches and sends the open chapter its changes, so the board,
the move list, the outlines on the page and the Review list change while the
page and the chosen move stay put. A piece symbol reaches the open chapter
first and then the other chapters, one at a time, while the reader goes on
reading. Read again is needed only after a change of the selection (pages
and diagrams included or left out). The browser keeps the corrections for
each book, and reading the book again applies them with the same result.

In a reader built from the command line, the contents page's "Copy
corrections" button copies the corrections; `python3 make_reader.py book.pdf
--corrections FILE` saves the pasted text as `books/<book>/corrections.json`,
which every later run applies (`chessbook/corrections.py` describes the
format). A corrected item shows in the colour of a decoded move, with the
words "Corrected by you", and the contents page counts the corrections a run
used.

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
a line of their own, instead of standing unread in the line before.

## Running it from the command line

```
pip install --use-pep517 -r requirements.txt
python3 make_reader.py path/to/book.pdf
```

One command inspects the book, decodes its moves and writes the reader to
`output/<book name>/reader/index.html`, with one reader per chapter beside
it. The Primer (402 pages) takes about 100 seconds; a short typeset book
takes a few seconds. Book PDFs and the output folder are kept out of git.
