"""Gather the results of book-audit workflow runs (their output files) into one.

Usage:
    python3 tools/audit/runs.py OUT.json RUN_OUTPUT [RUN_OUTPUT ...]

Each RUN_OUTPUT is the output file of a run of .claude/workflows/book-audit.js
in "find" mode; OUT.json gets their coverage, confirmed, refuted and
unverified findings together, and the counts are printed, so that a
"solve" run can take the confirmed findings as its args.findings.
"""
import collections
import json
import sys


def result_of(path):
    text = open(path, encoding="utf-8").read()
    data, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
    return data.get("result", data)


def main():
    out, paths = sys.argv[1], sys.argv[2:]
    merged = {"coverage": [], "confirmed": [], "refuted": [], "unverified": []}
    for p in paths:
        r = result_of(p)
        for k in merged:
            merged[k] += r.get(k) or []
    json.dump(merged, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print({k: len(v) for k, v in merged.items()})
    sev = collections.Counter((f["book"], f["severity"]) for f in merged["confirmed"])
    for (book, s), n in sorted(sev.items()):
        print(f"  {book:<10} {s:<13} {n}")


if __name__ == "__main__":
    main()
