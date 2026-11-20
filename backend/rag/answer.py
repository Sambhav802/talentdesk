"""Grounded answers: the LLM sees only retrieved chunks, must cite them as [n], and says NOT_FOUND otherwise."""
import re

import llm

NOT_FOUND = "NOT_FOUND"
NOT_IN_KB = ("I couldn't find that in the HR knowledge base. Please check with the HR team, "
             "or ask me about our policies, hiring process or open roles.")

SYSTEM = f"""You are the HR assistant of Northwind Labs. Answer the employee's or candidate's question using ONLY
the numbered context passages.
Rules:
- Start with the direct answer in the first sentence, including the exact number, amount, duration or date
  from the passages (for example "18 days", "INR 25,000", "6 months", "last working day of the month").
- Then add only the conditions or exceptions from the passages that matter for this question.
- Every sentence that states a fact ends with the citation of the passage it came from, like [1] or [2][3].
  Use plain square brackets.
- Do not use outside knowledge and never guess numbers, dates or names.
- If the passages answer only part of the question, answer that part and say the rest is not covered.
- If the passages do not contain the answer at all, reply with exactly {NOT_FOUND} and nothing else.
- Be concise: at most 4 short sentences or 5 bullet points."""

# characters reasoning models like to emit that break matching and look odd in the chat window
_CHAR_FIX = str.maketrans({" ": " ", " ": " ", " ": " ", " ": " ", "‑": "-", "‐": "-",
                           "‒": "-", "–": "-", "−": "-", "【": "[", "】": "]"})


def clean(text: str) -> str:
    """Normalise model output: plain spaces and hyphens, [n] citations (models sometimes write 【1】 or [1†L3])."""
    text = (text or "").translate(_CHAR_FIX)
    text = re.sub(r"\[(\d+)[^\]\d][^\]]*\]", r"[\1]", text)       # [1†source] -> [1]
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


def answer(question: str, hits: list[dict], complete=None) -> dict:
    """Returns {"text": markdown answer incl. Sources, "citations": [...]}. `complete` is injectable for tests."""
    if not hits:
        return {"text": NOT_IN_KB, "citations": []}
    complete = complete or llm.complete
    # a reasoning model (default openai/gpt-oss-120b) spends tokens thinking before it answers: leave room
    reply = clean(complete([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Context passages:\n\n{build_context(hits)}\n\nQuestion: {question}"},
    ], temperature=0, max_tokens=1500))
    if not reply or NOT_FOUND in reply[:40]:
        return {"text": NOT_IN_KB, "citations": []}
    cites = make_citations(hits, reply)
    return {"text": reply + sources_block(cites), "citations": cites}
