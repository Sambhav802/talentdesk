"""Grounded answers: the LLM sees only retrieved chunks, must cite them as [n], and says NOT_FOUND otherwise.

The reply format (see prompts.policy_system) is a bold key-fact line plus up to 3 bullets; it is also returned as a
structured "policy" card {title, key, points, sources} that the frontend renders as a compact card."""
import re

import llm
import prompts

NOT_FOUND = prompts.NOT_FOUND
NOT_IN_KB = ("I couldn't find that in the HR knowledge base. Please check with the HR team, "
             "or ask me about our policies, hiring process or open roles.")
SYSTEM = prompts.policy_system("Candidate")          # kept for callers/tests that read the default prompt

# characters reasoning models like to emit that break matching and look odd in the chat window
_CHAR_FIX = str.maketrans({" ": " ", " ": " ", " ": " ", " ": " ", "‑": "-", "‐": "-",
                           "‒": "-", "–": "-", "−": "-", "【": "[", "】": "]"})


def clean(text: str) -> str:
    """Normalise model output: plain spaces and hyphens, [n] citations (models sometimes write 【1】 or [1†L3])."""
    text = (text or "").translate(_CHAR_FIX)
    text = re.sub(r"\[(\d+)[^\]\d][^\]]*\]", r"[\1]", text)       # [1†source] -> [1]
    text = re.sub(r"(\w|\.|\*)\[(\d+)\]", r"\1 [\2]", text)          # "days[1]" -> "days [1]"
    return text.strip()


def source_label(hit: dict) -> str:
    label = hit.get("title") or hit.get("source") or "Document"
    if hit.get("section"):
        label += f" · {hit['section']}"
    return label


def build_context(hits: list[dict]) -> str:
    return "\n\n".join(f"[{i}] ({source_label(h)})\n{h['text']}" for i, h in enumerate(hits, 1))


def cited_numbers(answer: str, n_hits: int) -> list[int]:
    nums = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    return [n for n in nums if 1 <= n <= n_hits]


def make_citations(hits: list[dict], answer: str) -> list[dict]:
    """Citations for the passages the answer actually cites (the best passage if it cited none)."""
    used = cited_numbers(answer, len(hits)) or [1]
    out = []
    for n in used:
        h = hits[n - 1]
        snippet = h["text"] if len(h["text"]) <= 600 else h["text"][:600].rsplit(" ", 1)[0] + " …"
        out.append({"n": n, "title": h.get("title", ""), "section": h.get("section", ""),
                    "source": h.get("source", ""), "type": h.get("type", "document"),
                    "chunk_index": h.get("chunk_index", 0), "doc_id": h.get("doc_id"),
                    "score": h.get("score"), "label": source_label(h), "snippet": snippet})
    return out


def sources_block(citations: list[dict]) -> str:
    if not citations:
        return ""
    return "\n\n**Sources**\n" + "\n".join(f"[{c['n']}] {c['label']}" for c in citations)


def to_card(reply: str, citations: list[dict]) -> dict:
    """Split the model's reply into the key fact (first line) and bullet points."""
    lines = [ln.strip() for ln in reply.splitlines() if ln.strip()]
    key = lines[0] if lines else reply
    bullet = re.compile(r"^[-*•]\s+")
    points = [bullet.sub("", ln) for ln in lines[1:]]       # prose lines stay visible as points too
    title = next((c["section"] for c in citations if c.get("section")), "") or "HR policy"
    return {"kind": "policy", "title": title, "key": key, "points": points,
            "sources": [{"n": c["n"], "label": c["label"]} for c in citations]}


def related_questions(hits: list[dict], exclude: str = "", limit: int = 3) -> list[str]:
    out = []
    for h in hits:
        q = prompts.SECTION_QUESTIONS.get(h.get("section", ""))
        if q and q not in out and h.get("section") != exclude:
            out.append(q)
    return out[:limit]


def not_found(hits: list[dict], user_role: str) -> dict:
    sugg = related_questions(hits) or prompts.DEFAULT_SUGGESTIONS[prompts.role_of(user_role)][:3]
    return {"text": NOT_IN_KB, "citations": [], "type": "not_found", "cards": [], "suggestions": sugg}


def answer(question: str, hits: list[dict], complete=None, user_role: str = "Candidate",
           correction: str | None = None, previous: str | None = None) -> dict:
    """Returns {"text", "citations", "type", "cards", "suggestions"}. `complete` is injectable for tests.
    With `correction` (the user's objection) and `previous` (the answer they object to), the model re-checks."""
    if not hits:
        return not_found(hits, user_role)
    complete = complete or llm.complete
    if correction:
        system = prompts.correction_system(user_role)
        user = (f"Context passages:\n\n{build_context(hits)}\n\nOriginal question: {question}\n"
                f"Previous answer: {previous or '(not available)'}\nUser's objection: {correction}")
    else:
        system = prompts.policy_system(user_role)
        user = f"Context passages:\n\n{build_context(hits)}\n\nQuestion: {question}"
    # a reasoning model (default openai/gpt-oss-120b) spends tokens thinking before it answers: leave room
    reply = clean(complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                           temperature=0, max_tokens=1500))
    if not reply or NOT_FOUND in reply[:40]:
        return not_found(hits, user_role)
    cites = make_citations(hits, reply)
    card = to_card(reply, cites)
    return {"text": reply + sources_block(cites), "citations": cites, "type": "policy", "cards": [card],
            "suggestions": related_questions(hits, exclude=card["title"])}
