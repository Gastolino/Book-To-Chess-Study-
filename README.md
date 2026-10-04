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

## Running it from the command line

```
pip install --use-pep517 -r requirements.txt
python3 make_reader.py path/to/book.pdf
```

One command inspects the book, decodes its moves and writes the reader to
`output/<book name>/reader/index.html`, with one reader per chapter beside
it. The Primer (402 pages) takes about 100 seconds; a short typeset book
takes a few seconds. Book PDFs and the output folder are kept out of git.
