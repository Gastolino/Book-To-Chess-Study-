"""Why the moves of a book are not read: unplaced (by reason), not ok, green but
wrong, or broken earlier in their line (by the status of the first bad move).

Usage: python3 tools/audit/why.py CODE BOOK [BOOK ...]
"""
import sys, collections, re
sys.path.insert(0, "tools/audit"); import books, score as s
code = sys.argv[1]
for name in sys.argv[2:]:
    b = books.load(name, code=code); N = b["nodes"]; g = s.glyph_pieces(b)
    tw = name in s.TWIN_BOOKS
    def fits(k, raw):
        n = N[k]; p = n.get("parent"); fen = N[p]["fen"] if p in N else None
        return s.agrees_here(raw, n.get("san"), fen, g) if tw else s.agrees(raw, n.get("san"))
    memo = {}
    def first_bad(k):
        chain = []; cur = k
        while cur is not None:
            chain.append(cur); cur = N[cur].get("parent")
        bad = None
        for x in reversed(chain):
            n = N[x]
            if n.get("san") and n.get("raw") and not fits(x, n["raw"]): bad = x; break
        return bad
    c = collections.Counter()
    for pg in b["pages"]:
        for m in pg["marks"]:
            raw = m.get("raw") or ""
            if m["status"] == "unattached" and not (s.squares(s._joined(raw)) or s.CASTLE.search(raw) or s.whole_square(raw)): continue
            n = N.get(m.get("node")) if m.get("node") else None
            if m["status"] == "unattached" or not n:
                r = (m.get("reason") or n and n.get("reason") or "?")
                r = re.sub(r"\d+", "N", str(r))[:60]
                c["unplaced: " + r] += 1; continue
            if m["status"] != "ok": c["not ok: " + m["status"]] += 1; continue
            if not fits(m["node"], raw): c["green wrong"] += 1; continue
            fb = first_bad(m["node"])
            if fb: c["broken earlier at " + N[fb]["status"]] += 1
    print("==", name, sum(c.values()))
    for k, v in c.most_common(14): print(f"{v:6} {k}")
