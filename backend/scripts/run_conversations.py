"""Run multi-turn conversations (scripts/messy_set.json by default) against a backend and dump full transcripts
(answer text, citations, structured payload, latency) for human review. No grading here: read the transcripts.

    python scripts/run_conversations.py https://your-backend.vercel.app --out transcripts.json
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_eval import LAST, chat  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--set", default=str(Path(__file__).resolve().parent / "messy_set.json"))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    spec = json.loads(Path(a.set).read_text(encoding="utf-8"))
    run, out = uuid.uuid4().hex[:6], []
    for conv in spec["conversations"]:
        session, turns = f"conv-{run}-{conv['id']}", []
        for t in conv["turns"]:
            t0 = time.time()
            ans = chat(a.base, session, t["say"], conv.get("role", "Candidate"))
            turns.append({"say": t["say"], "expect": t.get("expect", ""), "answer": ans,
                          "secs": round(time.time() - t0, 1), "extra": dict(LAST)})
            print(f"[{conv['id']}] > {t['say']}\n  < {ans[:600]}\n", flush=True)
        out.append({"id": conv["id"], "role": conv.get("role"), "turns": turns})
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
