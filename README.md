# Book to Chess Study

This project turns a chess book in PDF form into FENs and PGNs, and from those
into private Lichess studies. It works on any chess book; *The Soviet Chess
Primer* (Maizelis) is the first book used to test it.

Each stage writes an HTML report for checking before the next stage runs.

| Stage | Script | What it does |
|---|---|---|
| 1 | `stage1_inspect.py` | Finds out what kind of PDF the book is, finds the board pictures and lists every diagram number in the text. |
| 2 | to come | Cuts out every board. |
| 3 | to come | Reads each board into a FEN. |
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
