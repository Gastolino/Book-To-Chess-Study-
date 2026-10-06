# Third-party software in the pages

The pages this project writes embed or load the following software, each
under its own licence.

## Stockfish 19 (Stockfish.js)

Analysis in the chapter reader uses Stockfish 19, compiled to WebAssembly
as Stockfish.js by Nathan Rugg (the npm package `stockfish` 19.0.0, lite
single-threaded build, files `stockfish-19-lite-single.js` and
`stockfish-19-lite-single.wasm`). Stockfish is copyright its authors (T.
Romstad, M. Costalba, J. Kiiski, G. Linscott and the other contributors,
<https://github.com/official-stockfish/Stockfish>); Stockfish.js is
copyright Chess.com, LLC (<https://github.com/nmrugg/stockfish.js>). Both are
free software under the GNU General Public License, version 3 (GPLv3). The
licence text is shipped with the engine as `engine/Copying.txt` beside the
pages and linked from the foot of the analysis settings. The engine is not
modified; its source is available from the repositories above.

`chessbook/engine_files.py` names the files and their SHA-256 checksums;
`tools/fetch_engine.py` fetches them from the npm registry and checks them.
The files are not kept in this repository.

## Fonts

DM Sans and Geist Mono, embedded in every page, are under the SIL Open
Font License, version 1.1 (`chessbook/assets/fonts/LICENSE-DMSans.txt` and
`LICENSE-GeistMono.txt`).

## Piece drawings

The board's piece drawings are those of python-chess (`chess.svg`), by
Colin M. L. Burnett, under the GNU General Public License, version 3, as
python-chess is.

## In the browser app

The browser app runs the project's Python code through Pyodide (Mozilla
Public License 2.0) with PyMuPDF (GNU Affero General Public License,
version 3) and python-chess (GPLv3), loaded from their published builds.
