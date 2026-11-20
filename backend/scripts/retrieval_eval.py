"""Retrieval check: for each policy question in eval_set.json, does POST /kb/search return a passage that holds the
expected fact? Needs no LLM key, so it works against any deployment (or a local server).

    python scripts/retrieval_eval.py https://your-backend.vercel.app
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def search(base: str, query: str) -> list[dict]:
    req = urllib.request.Request(base.rstrip("/") + "/kb/search", data=json.dumps({"query": query}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("results", [])


def main() -> int:
    base = sys.argv[1]
    spec = json.loads((HERE / "eval_set.json").read_text(encoding="utf-8"))
    hit1 = hitk = n = 0
    for q in spec["questions"]:
        if q.get("kind", "policy") != "policy" or q.get("refuse") or not q.get("all"):
            continue
        n += 1
        res = search(base, q["q"])
        texts = [r["text"] for r in res]
        has = [all(re.search(p, t, re.I) for p in q["all"]) for t in texts]
        joined = all(re.search(p, " ".join(texts), re.I) for p in q["all"])
        hit1 += bool(has and has[0])
        hitk += joined
        print(f"{'top1' if has and has[0] else ('topk' if joined else 'MISS')}  {q['id']:<18} "
              f"{' | '.join((r.get('section') or r.get('title', ''))[:24] for r in res[:3])}")
    print(f"\nfact in top passage: {hit1}/{n}   fact in retrieved passages: {hitk}/{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
