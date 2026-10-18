"""Gather the results of book-audit workflow runs (their output files) into one.

Usage:
    python3 tools/audit/runs.py OUT.json RUN_OUTPUT [RUN_OUTPUT ...] [--brief BRIEF.json]

Each RUN_OUTPUT is the output file of a run of .claude/workflows/book-audit.js
in "find" mode; OUT.json gets their coverage, confirmed, refuted and
unverified findings together, and the counts are printed, so that a
"solve" run can take the confirmed findings as its args.findings. --brief
also writes the short form of each confirmed finding (and the refuted
ones), which a "solve" run reads from args.briefFile.
"""
import collections
import json
import sys


def result_of(path):
    text = open(path, encoding="utf-8").read()
    data, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
    return data.get("result", data)


def cut(x, n):
    return x[:n] + "…" if isinstance(x, str) and len(x) > n else x


def brief(f):
    return {"id": f["id"], "book": f["book"], "lens": f["lens"], "severity": f["severity"], "title": f["title"],
            "pages": (f.get("pages") or [])[:6], "keys": (f.get("keys") or [])[:3],
            "printed": cut(f.get("printed"), 300), "program": cut(f.get("program"), 400),
            "expected": cut(f.get("expected"), 300), "count": f.get("count"), "cause": cut(f.get("cause"), 700)}


def main():
    args = sys.argv[1:]
    brief_path = None
    if "--brief" in args:
        i = args.index("--brief")
        brief_path = args[i + 1]
        del args[i:i + 2]
    out, paths = args[0], args[1:]
    merged = {"coverage": [], "confirmed": [], "refuted": [], "unverified": []}
    for p in paths:
        r = result_of(p)
        for k in merged:
            merged[k] += r.get(k) or []
    json.dump(merged, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    if brief_path:
        json.dump({"confirmed": [brief(f) for f in merged["confirmed"]], "refuted": merged["refuted"]},
                  open(brief_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print({k: len(v) for k, v in merged.items()})
    sev = collections.Counter((f["book"], f["severity"]) for f in merged["confirmed"])
    for (book, s), n in sorted(sev.items()):
        print(f"  {book:<10} {s:<13} {n}")


if __name__ == "__main__":
    main()
