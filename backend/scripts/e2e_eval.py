"""End-to-end evaluation of the TalentDesk chatbot over HTTP.

Sends every question in scripts/eval_set.json to POST <base>/chat (a fresh session per question, the role the
question names), grades the answer against the expected facts, then runs the multi-turn flows.

    python scripts/e2e_eval.py https://your-backend.vercel.app
    python scripts/e2e_eval.py http://localhost:8000 --only leave-annual,jobs-remote --out results.json

Needs only the standard library. Grading: every regex in "all" must match, at least one in "any" (if given),
none in "none"; "refuse": true expects the not-in-the-knowledge-base reply. Exit code 1 when anything fails.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFUSAL = re.compile(r"couldn.?t find that in the HR knowledge base|not (?:in|covered by) (?:the|our) (?:HR )?knowledge base",
                     re.I)


LAST = {}          # citations / structured payload of the last reply (kept for the transcript dump)


def chat(base: str, session: str, message: str, role: str, timeout: float = 90) -> str:
    body = json.dumps({"session_id": session, "message": message, "user_role": role}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/chat", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
                LAST.clear()
                LAST.update({k: v for k, v in data.items() if k != "response"})
                return data.get("response", "")
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            if e.code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            try:
                return json.loads(text).get("response", text)
            except ValueError:
                return f"HTTP {e.code}: {text[:300]}"
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 2:
                time.sleep(5)
                continue
            return f"ERROR: {e}"
    return "ERROR: no response"


def grade(answer: str, spec: dict) -> tuple[bool, str]:
    """(passed, reason) for one answer against one spec."""
    if answer.startswith(("ERROR", "HTTP ", "Chat Error")):
        return False, "request failed"
    refused = bool(REFUSAL.search(answer))
    if spec.get("refuse"):
        return (True, "") if refused else (False, "answered instead of refusing")
    if refused:
        return False, "refused (retrieval miss or KB gap)"
    for pat in spec.get("all", []):
        if not re.search(pat, answer, re.I):
            return False, f"missing /{pat}/"
    if spec.get("any") and not any(re.search(p, answer, re.I) for p in spec["any"]):
        return False, f"none of /{'|'.join(spec['any'])}/"
    for pat in spec.get("none", []):
        if re.search(pat, answer, re.I):
            return False, f"unexpected /{pat}/"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="backend base URL, e.g. https://talentdesk-backend.vercel.app")
    ap.add_argument("--set", default=str(HERE / "eval_set.json"))
    ap.add_argument("--only", default="", help="comma-separated question/flow ids")
    ap.add_argument("--out", default="", help="write full results as JSON")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between requests (model rate limits)")
    a = ap.parse_args()

    spec = json.loads(Path(a.set).read_text(encoding="utf-8"))
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    run_id = uuid.uuid4().hex[:8]
    results = []

    for q in spec["questions"]:
        if only and q["id"] not in only:
            continue
        t = time.time()
        ans = chat(a.base, f"eval-{run_id}-{q['id']}", q["q"], q.get("role", "Candidate"))
        ok, why = grade(ans, q)
        results.append({"id": q["id"], "kind": q.get("kind", "policy"), "kb": q.get("kb", "existing"), "ok": ok,
                        "why": why, "secs": round(time.time() - t, 1), "q": q["q"], "role": q.get("role", "Candidate"),
                        "answer": ans, "extra": dict(LAST)})
        print(f"{'PASS' if ok else 'FAIL'}  {q['id']:<20} {why}", flush=True)
        time.sleep(a.pause)

    for f in spec.get("flows", []):
        if only and f["id"] not in only:
            continue
        session, ok, why, transcript = f"eval-{run_id}-{f['id']}", True, "", []
        for n, step in enumerate(f["steps"], 1):
            t = time.time()
            ans = chat(a.base, session, step["say"], f.get("role", "Candidate"))
            transcript.append({"say": step["say"], "answer": ans, "secs": round(time.time() - t, 1), "extra": dict(LAST)})
            s_ok, s_why = grade(ans, step)
            if not s_ok:
                ok, why = False, f"step {n}: {s_why}"
                break
            time.sleep(a.pause)
        results.append({"id": f["id"], "kind": "flow", "kb": "existing", "ok": ok, "why": why, "transcript": transcript})
        print(f"{'PASS' if ok else 'FAIL'}  {f['id']:<20} {why}", flush=True)

    passed = sum(r["ok"] for r in results)
    print(f"\n{passed}/{len(results)} passed")
    for kind in ("policy", "jobs", "flow"):
        rs = [r for r in results if r["kind"] == kind]
        if rs:
            print(f"  {kind:<7} {sum(r['ok'] for r in rs)}/{len(rs)}")
    if a.out:
        Path(a.out).write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
