"""Benchmark the move-text decoder on games rendered as noisy book text.

Usage:
    python tools/corrupt_bench.py                    # full bench -> output/movetext_bench.txt
    python tools/corrupt_bench.py --games 20         # quick run on 20 games
    python tools/corrupt_bench.py --book primer.pdf  # real-book check -> output/movetext_primer.txt

Every game (the known games in tests/data/known_games.pgn plus random legal
games from python-chess with a fixed seed) is printed as book text in two
notations: English piece letters, and figurine junk of the kind OCR makes of
a figurine font (each piece replaced by a random junk variant, the glyph
sometimes lost, OCR confusions in squares, split and glued move numbers, "t"
for the check sign). The text then goes through the whole decoder:
tokenize -> find_sequences -> decode, from the initial position. Decoding is
done twice per corpus: the first pass knows nothing of the junk, the second
uses a GlyphModel learnt from the first pass with GlyphModel.learn_run().

The real-book check (--book) decodes every run that starts at move 1 with
White from the initial position, chains later runs to those games
(continuations and variations), learns a GlyphModel from the first pass and
decodes again; it also measures how the book prints moves, which is what the
bench's medium noise level is set from.
"""
from __future__ import annotations

import argparse
import io
import random
import sys
import time
from collections import Counter
from pathlib import Path

import chess
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chessbook.movetext import GlyphModel, clean_run, decode, find_sequences  # noqa: E402

KNOWN = ROOT / "tests" / "data" / "known_games.pgn"

# Junk that a figurine font turns into after OCR (as seen in a ClearScan book).
JUNK = {
    "N": ["\x18", "tLl", "ti)", "lt)", "tt:l"],
    "Q": ["\x1b", "YlY", "'i!Y", "'ilY", "Wf", "1W", "V"],
    "K": ["\x14", "®", "lt>", "<.!.>", "\\t>", "Wi>"],
    "R": ["J3", ":B:", "J\x1d:", "l:t", ".1':!:", "I:t", ":"],
    "B": ["i.", ".i", "A", "J.", "h", ",h"],
}
FILE_CONF = {"c": ["e"], "e": ["c"], "b": ["h"], "h": ["b"], "f": ["t", "£"], "g": ["q"],
             "a": ["o"]}
RANK_CONF = {"1": ["l", "I", "i", "!"], "8": ["B", "S", "s"], "6": ["b", "G"], "5": ["S"]}

# Per-move probabilities. f_pound: an f-file square printed with "£" or "t";
# sq: any other OCR confusion of a square character (c/e, b/h, g/q, a/o, 6/b,
# 5/S ...); l1 and s8: "l" for 1 and "s" for 8, common in figurine OCR. The
# medium level matches the rates measured on the Soviet Chess Primer
# (python tools/corrupt_bench.py --book primer.pdf): about 5% of files and 4%
# of ranks misprinted, 7% of captures without "x", glyphs rarely lost.
LEVELS = {
    "low": dict(drop=0.003, f_pound=0.15, sq=0.007, l1=0.15, s8=0.05, xdrop=0.03,
                chkdrop=0.01, split=0.05, glue=0.02, ocrnum=0.05, black_repeat=0.02, xvar=0.05),
    "medium": dict(drop=0.01, f_pound=0.3, sq=0.02, l1=0.3, s8=0.15, xdrop=0.07,
                   chkdrop=0.03, split=0.15, glue=0.05, ocrnum=0.15, black_repeat=0.04,
                   xvar=0.15),
    "high": dict(drop=0.03, f_pound=0.5, sq=0.06, l1=0.5, s8=0.3, xdrop=0.15, chkdrop=0.08,
                 split=0.25, glue=0.10, ocrnum=0.3, black_repeat=0.06, xvar=0.3),
}


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------
def load_known(path: Path = KNOWN):
    """(name, [SAN]) for every game in the PGN that python-chess accepts in full."""
    games, dropped = [], []
    f = io.StringIO(path.read_text(encoding="utf-8"))
    while True:
        g = chess.pgn.read_game(f)
        if g is None:
            break
        name = f"{g.headers.get('White', '?')} - {g.headers.get('Black', '?')}"
        if g.errors:
            dropped.append(name)
            continue
        b = g.board()
        sans = []
        for mv in g.mainline_moves():
            if mv not in b.legal_moves:
                break
            sans.append(b.san(mv))
            b.push(mv)
        else:
            games.append((name, sans))
            continue
        dropped.append(name)
    return games, dropped


def random_games(n: int, seed: int = 20261003, lo: int = 30, hi: int = 80):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        target = rng.randint(lo, hi)
        b = chess.Board()
        sans = []
        while len(sans) < target and not b.is_game_over():
            mv = rng.choice(list(b.legal_moves))
            sans.append(b.san(mv))
            b.push(mv)
        if len(sans) >= lo:
            out.append((f"random {len(out) + 1}", sans))
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _square(sq: str, nz: dict, rng: random.Random, junk: bool) -> str:
    f, r = sq[0], sq[1]
    if f == "f" and rng.random() < nz["f_pound"]:
        f = "£" if rng.random() < 0.8 else "t"
    elif rng.random() < nz["sq"] and f in FILE_CONF:
        f = rng.choice(FILE_CONF[f])
    if junk and r == "1" and rng.random() < nz["l1"]:
        r = "l"
    elif junk and r == "8" and rng.random() < nz["s8"]:
        r = "s"
    elif rng.random() < nz["sq"] and r in RANK_CONF:
        r = rng.choice(RANK_CONF[r])
    return f + r


def corrupt_move(san: str, notation: str, nz: dict, rng: random.Random) -> str:
    junk = notation == "junk"
    check = ""
    while san and san[-1] in "+#":
        check = san[-1] + check
        san = san[:-1]
    if check and rng.random() < nz["chkdrop"]:
        check = ""
    if junk:
        check = check.replace("+", "t")
    if san.startswith("O-O"):
        body = san.replace("O", "0") if (junk or rng.random() < 0.5) else san
        return body + check
    promo = ""
    if "=" in san:
        san, promo = san.split("=")
    piece = san[0] if san[0] in "KQRBN" else ""
    rest = san[1:] if piece else san
    cap = "x" in rest
    dis, dest = rest.replace("x", "")[:-2], rest[-2:]
    out_piece = piece
    if piece:
        if junk:
            out_piece = rng.choice(JUNK[piece])
        if rng.random() < nz["drop"]:
            out_piece = ""
    xmark = ""
    if cap:
        xmark = "x"
        if rng.random() < nz["xdrop"] or (junk and out_piece == "h" and rng.random() < 0.5):
            xmark = ""
        elif junk and rng.random() < nz["xvar"]:
            xmark = rng.choice(["x:", ":x", "x:"])
    sq = _square(dest, nz, rng, junk)
    if promo:
        p = rng.choice(JUNK[promo]) if junk else promo
        promo = ("=" if rng.random() < 0.8 else "") + p
    return out_piece + dis + xmark + sq + promo + check


def _number(n: int, nz: dict, rng: random.Random, junk: bool):
    """A White move number as printed: (text, split by a space?)."""
    s = str(n)
    if rng.random() < nz["ocrnum"]:
        s = s.replace("1", rng.choice("lI")).replace("0", rng.choice("Oo"))
        if s == "8" and junk:
            s = "s"
    split = len(s) >= 2 and rng.random() < nz["split"]
    if split:
        s = " ".join(s)
    sep = "."
    if junk and rng.random() < nz["split"] / 2:
        sep = " ."
        split = True
    return s + sep, split


def render(sans: list, notation: str, level: str, rng: random.Random) -> str:
    """The game as book text: "1.e4 e5 2.Nf3 ..." with line breaks and noise."""
    nz = LEVELS[level]
    junk = notation == "junk"
    parts = []                    # (text, starts with an unsplit White number)
    for i, san in enumerate(sans):
        n = i // 2 + 1
        mv = corrupt_move(san, notation, nz, rng)
        if i % 2 == 0:
            num, split = _number(n, nz, rng, junk)
            parts.append((num + mv, not split))
        elif rng.random() < nz["black_repeat"]:
            dots = rng.choice(["...", " ... ", " .. . ", "…"])
            parts.append((f"{n}{dots}{mv}".replace("  ", " "), False))
        else:
            parts.append((mv, False))
    text = []
    for k, (p, _) in enumerate(parts):
        text.append(p)
        if k + 1 < len(parts):
            if parts[k + 1][1] and rng.random() < nz["glue"] and p[-1:] in "12345678t#":
                continue                      # "xd4t10.Kc3"
            text.append("\n" if rng.random() < 0.12 else " ")
    return "".join(text)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def decode_game(text: str, n_plies: int, glyphs, letters=None, true_sans=None):
    """Decode a rendered game. Returns (decoded by ply, decoded runs, breaks)."""
    seqs = [s for s in find_sequences(text) if s.depth == 0 and s.first_number is not None]
    board = chess.Board()
    ply = 0
    by_ply = {}
    runs = []
    breaks = 0
    for seq in seqs:
        start = (seq.first_number - 1) * 2 + int(seq.black_first)
        if start != ply:
            breaks += 1
            if true_sans is None or start < 0 or start > n_plies:
                continue
            board = chess.Board()            # oracle restart at the true position
            for s in true_sans[:start]:
                board.push_san(s)
            ply = start
        decs = decode(board, seq.tokens, glyphs=glyphs, letters=letters)
        runs.append(decs)
        last_board = None
        for d in decs:
            if d.number is None:
                continue
            p = (d.number - 1) * 2 + int(d.black)
            by_ply.setdefault(p, d)
            if d.fen:
                last_board = chess.Board(d.fen)
                ply = p + 1
        if last_board is not None:
            board = last_board
    return by_ply, runs, breaks


def run_corpus(games, notation, level, seed, glyphs, letters=None):
    rng = random.Random(seed)
    texts = [render(sans, notation, level, rng) for _, sans in games]
    stats = Counter()
    statuses = Counter()
    t0 = time.perf_counter()
    all_runs = []
    wrong_examples = []
    for (name, sans), text in zip(games, texts):
        by_ply, runs, breaks = decode_game(text, len(sans), glyphs, letters, sans)
        all_runs.extend(runs)
        statuses.update(d.status for r in runs for d in r)
        good = 0
        for p, san in enumerate(sans):
            d = by_ply.get(p)
            if d is not None and d.san == san:
                good += 1
            elif len(wrong_examples) < 12:
                wrong_examples.append((name, p, san, d.raw if d else None,
                                       d.san if d else None, d.status if d else "missing"))
        stats["moves"] += len(sans)
        stats["correct"] += good
        stats["games"] += 1
        stats["exact"] += good == len(sans)
        stats["breaks"] += breaks
    stats["seconds"] = time.perf_counter() - t0
    return stats, statuses, all_runs, wrong_examples, texts


def fmt_row(label, st, sc):
    acc = st["correct"] / max(1, st["moves"])
    ex = st["exact"] / max(1, st["games"])
    ms = 1000 * st["seconds"] / max(1, st["moves"])
    sc_txt = ", ".join(f"{k} {sc[k]}" for k in ("ok", "guessed", "ambiguous", "failed"))
    return (f"{label:<28} moves {st['moves']:>6}  per-move {100 * acc:6.2f}%  "
            f"games exact {100 * ex:6.2f}% ({st['exact']}/{st['games']})  "
            f"{ms:5.2f} ms/move  runs restarted {st['breaks']}  [{sc_txt}]")


def bench(n_games: int | None, out: Path, seed: int = 7, quiet=False,
          notations=("english", "junk"), levels=("low", "medium", "high")):
    known, dropped = load_known()
    rand = random_games(300)
    games = known + rand
    if n_games is not None:
        games = games[:n_games]
    lines = []
    w = lines.append
    w("Move-text decoder benchmark")
    w("===========================")
    w(f"Known games in {KNOWN.relative_to(ROOT)}: {len(known)} legal, {len(dropped)} dropped"
      + (f" ({'; '.join(dropped)})" if dropped else ""))
    w(f"Random legal games: {len(rand)} (30-80 plies, seed 20261003)")
    w(f"Games in this run: {len(games)}, plies: {sum(len(s) for _, s in games)}")
    w("")
    w("Noise per level (probabilities per move or per square character):")
    for lv, nz in LEVELS.items():
        w(f"  {lv:<7} " + ", ".join(f"{k}={v}" for k, v in nz.items()))
    w("")
    results = {}
    for notation in notations:
        for level in levels:
            g1 = GlyphModel()
            st1, sc1, runs1, wr1, texts = run_corpus(games, notation, level, seed, g1)
            g2 = GlyphModel()
            learnt = sum(g2.learn_run(r) for r in runs1)
            st2, sc2, decs2, wr2, _ = run_corpus(games, notation, level, seed, g2)
            results[(notation, level)] = (st1, sc1, st2, sc2, wr2, learnt, texts)
            row1 = fmt_row(f"{notation}/{level} pass 1", st1, sc1)
            row2 = fmt_row(f"{notation}/{level} pass 2", st2, sc2)
            w(row1)
            w(row2 + f"  (pairs learnt: {learnt})")
            if not quiet:
                print(row1, flush=True)
                print(row2, flush=True)
    w("")
    w("Pass 1 decodes with no knowledge of the glyph junk; pass 2 uses a GlyphModel")
    w("learnt from pass 1 over the same corpus, as for a book (GlyphModel.learn_run():")
    w("glyphs and square habits from the 'ok' moves of runs that read cleanly).")
    w("Per-move accuracy counts a move as right when the decoded SAN equals the true SAN;")
    w("a game is exact when every move is right.")
    w("'runs restarted' counts runs of moves that did not continue where the previous")
    w("run stopped; the bench then restarts from the true position, and the moves in")
    w("between count as wrong.")
    w("")
    for (notation, level), (st1, sc1, st2, sc2, wr2, learnt, texts) in results.items():
        if wr2:
            w(f"Wrong moves after pass 2, {notation}/{level} (first {len(wr2)}):")
            for name, p, san, raw, got, status in wr2:
                w(f"  {name:<34} ply {p + 1:>3}  true {san:<8} raw {raw!r:<16} "
                  f"decoded {got!s:<8} {status}")
            w("")
    sample = results.get(("junk", "medium"))
    if sample:
        w("Sample of junk/medium text (first game):")
        w(sample[6][0][:600])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


# ---------------------------------------------------------------------------
# Real-book check
# ---------------------------------------------------------------------------
def _history(decs):
    """Positions before each ply of a decoded run, up to its first failed move."""
    hist = {}
    for d in decs:
        if d.status == "failed" or d.number is None or not d.fen:
            break
        hist[(d.number - 1) * 2 + int(d.black) + 1] = d.fen
    return hist


def chain_runs(pages, glyphs):
    """Decode the runs that continue or branch from a game begun at move 1.

    After a run that starts at move 1 and reads as play, later runs on the
    same or following pages are decoded from the game's position at their
    first move: a run that starts where the game stopped continues it (main
    line), a run that starts earlier is a variation. Returns
    [(page, text, seq, decoded, kind, fits)], kind being "start",
    "continuation" or "variation", and fits whether the run reads as play
    from that position.
    """
    out = []
    hist = None                     # ply -> FEN before that ply
    for i, text in enumerate(pages):
        for s in find_sequences(text):
            if s.first_number is None:
                continue
            ply = (s.first_number - 1) * 2 + int(s.black_first)
            if ply == 0:
                decs = decode(chess.Board(), s.tokens, glyphs=glyphs)
                fits = clean_run(decs, max_failed=0.25, max_mean_cost=2.0)
                out.append((i + 1, text, s, decs, "start", fits))
                hist = {0: chess.STARTING_FEN, **_history(decs)} if fits else None
                continue
            if hist is None or ply not in hist:
                continue
            last = max(hist)
            kind = "continuation" if ply == last and s.depth == 0 else "variation"
            decs = decode(chess.Board(hist[ply]), s.tokens, glyphs=glyphs)
            fits = clean_run(decs, max_failed=0.25, max_mean_cost=2.0)
            out.append((i + 1, text, s, decs, kind, fits))
            if fits and kind == "continuation":
                hist.update(_history(decs))
    return out


def book_check(pdf: Path, out: Path, quiet=False):
    import pymupdf
    doc = pymupdf.open(pdf)
    pages = [p.get_text() for p in doc]
    all_seqs = 0
    targets = []
    for i, text in enumerate(pages):
        seqs = find_sequences(text)
        all_seqs += len(seqs)
        for s in seqs:
            if s.first_number == 1 and not s.black_first:
                targets.append((i + 1, text, s))

    def run(glyphs):
        t0 = time.perf_counter()
        res = [(page, text, s, decode(chess.Board(), s.tokens, glyphs=glyphs))
               for page, text, s in targets]
        return res, time.perf_counter() - t0

    res1, t1 = run(GlyphModel())
    chain1 = chain_runs(pages, GlyphModel())
    g = GlyphModel()
    every1 = [decs for _, _, _, decs in res1] + [c[3] for c in chain1 if c[4] != "start"]
    learn_runs = [decs for decs in every1 if clean_run(decs)]
    learnt = sum(g.learn_run(decs) for decs in every1)
    res2, t2 = run(g)
    chain2 = chain_runs(pages, g)

    def summary(res):
        st = Counter()
        st_start = Counter()
        from_start = 0
        for _, _, _, decs in res:
            st.update(d.status for d in decs)
            if clean_run(decs, max_failed=0.25, max_mean_cost=2.0):
                from_start += 1
                st_start.update(d.status for d in decs)
        return st, st_start, from_start

    lines = []
    w = lines.append
    w(f"Real-book check: {pdf.name}")
    w("=" * (17 + len(pdf.name)))
    w(f"Pages: {len(pages)}")
    w(f"Runs of numbered moves found (find_sequences, all depths): {all_seqs}")
    w(f"Runs that start at move 1 with White: {len(targets)}")
    w("")
    for label, res, secs in (("Pass 1 (no glyph knowledge)", res1, t1),
                             ("Pass 2 (glyph model learnt from pass 1)", res2, t2)):
        st, st_start, from_start = summary(res)
        n = sum(st.values())
        w(f"{label}: {n} move tokens decoded in {secs:.1f} s")
        w("  all runs from move 1:         " + ", ".join(
            f"{k} {st[k]} ({100 * st[k] / max(1, n):.1f}%)"
            for k in ("ok", "guessed", "ambiguous", "failed")))
        n2 = sum(st_start.values())
        w(f"  runs that read as play from the initial position: {from_start} (first move")
        w("  decoded, at most a quarter of the moves failed, mean reading cost 2.0 or less)")
        w("  moves in those runs:          " + ", ".join(
            f"{k} {st_start[k]} ({100 * st_start[k] / max(1, n2):.1f}%)"
            for k in ("ok", "guessed", "ambiguous", "failed")))
        w("")
    w("Runs chained to a game begun at move 1 (decoded from the game's position at their")
    w("first move; a run 'fits' when it reads as play from there, as defined above):")
    for label, chain in (("pass 1", chain1), ("pass 2", chain2)):
        for kind in ("continuation", "variation"):
            rows = [c for c in chain if c[4] == kind]
            fit = [c for c in rows if c[5]]
            stc = Counter(d.status for c in fit for d in c[3])
            nm = sum(stc.values())
            w(f"  {label} {kind + 's':<14} {len(rows):>4} runs, {len(fit):>4} fit; moves in fitting runs: "
              + ", ".join(f"{k} {stc[k]} ({100 * stc[k] / max(1, nm):.1f}%)"
                          for k in ("ok", "guessed", "ambiguous", "failed")))
    w("")
    w(f"Pairs learnt in pass 1: {learnt}. Glyphs come from the {len(learn_runs)} runs (from move 1")
    w("or chained) that decoded with no failed move and a mean reading cost of 1.5 or less.")
    w("Most frequent junk and its piece:")
    for prefix, piece, n in g.top(25):
        w(f"  {prefix!r:<14} -> {piece}  ({n:g})")
    w("")
    w("Square printing habits learnt (slot, printed character, value, count; '-' = absent):")
    for slot, ch, val, n in g.square_habits(14):
        w(f"  {slot:<5} {ch!r:<6} -> {val}  ({n})")
    w("")
    w("Noise measured on pass 2, over the moves of runs that read as play from the initial")
    w("position (decoded moves only, so these rates are lower bounds):")
    for k, v in measure_noise([decs for _, _, _, decs in res2
                               if clean_run(decs, max_failed=0.25, max_mean_cost=2.0)]).items():
        w(f"  {k:<44} {v}")
    w("")
    w("A run whose first move fails is usually a solution or a fragment that starts")
    w("from a diagram position rather than from the initial position.")
    w("")
    w("First 40 failed move tokens of pass 2 (PDF page, raw token, 10 characters of")
    w("context on each side; control characters shown as escapes):")
    n = 0
    for page, text, s, decs in res2:
        for d in decs:
            if d.status == "failed":
                ctx = text[max(0, d.start - 10):d.end + 10]
                w(f"  p{page:<4} {d.raw!r:<18} {ctx!r}")
                n += 1
                if n >= 40:
                    break
        if n >= 40:
            break
    w("")
    w("Failed move tokens of pass 2 inside runs that read as play (from move 1 or chained),")
    w("first 25:")
    n = 0
    plays = [(page, text, decs) for page, text, _, decs in res2
             if clean_run(decs, max_failed=0.25, max_mean_cost=2.0)]
    plays += [(c[0], c[1], c[3]) for c in chain2 if c[5] and c[4] != "start"]
    for page, text, decs in plays:
        for d in decs:
            if d.status == "failed" and n < 25:
                ctx = text[max(0, d.start - 10):d.end + 10]
                w(f"  p{page:<4} {d.raw!r:<18} {ctx!r}  assumed: {', '.join(d.alternatives) or '-'}")
                n += 1
    w("")
    w("First 30 runs of pass 2 as decoded (PDF page: SAN; [g] guessed, [a] ambiguous,")
    w("[f] failed with '?' for the move):")
    for page, text, s, decs in res2[:30]:
        mv = " ".join((d.san or "?") + ("" if d.status == "ok" else f"[{d.status[0]}]")
                      for d in decs)
        w(f"  p{page:<4} {mv}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not quiet:
        print("\n".join(lines[:20]))
    return res2


def measure_noise(runs) -> dict:
    """How often decoded moves show each kind of print noise."""
    n = pieces = vanished = file_odd = rank_odd = caps = cap_unmarked = checks = check_unmarked = 0
    failed = 0
    for decs in runs:
        for d in decs:
            if d.status == "failed":
                failed += 1
                continue
            if not d.san or d.san.startswith("O-O"):
                continue
            n += 1
            core = d.san.rstrip("+#")
            if core[0] in "KQRBN":
                pieces += 1
                vanished += not d.glyph
            dest = core.split("=")[0][-2:]
            fch, rch = d.square_read
            file_odd += fch != dest[0]
            rank_odd += rch != dest[1]
            if "x" in d.san:
                caps += 1
                cap_unmarked += not any(ch in d.raw for ch in "x:×X")
            if d.san[-1] in "+#":
                checks += 1
                cap_raw = d.raw.rstrip("!?")
                check_unmarked += not (cap_raw[-1:] in "+t#†‡")
    pct = lambda a, b: f"{a}/{b} ({100 * a / max(1, b):.1f}%)"  # noqa: E731
    return {
        "moves decoded": n,
        "failed moves": failed,
        "piece moves printed without a glyph": pct(vanished, pieces),
        "file printed as another character or lost": pct(file_odd, n),
        "rank printed as another character or lost": pct(rank_odd, n),
        "captures printed without a capture mark": pct(cap_unmarked, caps),
        "checks printed without a check sign": pct(check_unmarked, checks),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--games", type=int, default=None, help="limit the number of games")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--book", type=Path, default=None, help="run the real-book check on a PDF")
    args = ap.parse_args(argv)
    if args.book:
        out = args.out or ROOT / "output" / f"movetext_{args.book.stem}.txt"
        book_check(args.book, out)
        print(f"Wrote {out}")
        return
    out = args.out or ROOT / "output" / "movetext_bench.txt"
    bench(args.games, out)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
