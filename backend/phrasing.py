"""Natural wording for replies whose facts were decided in code (job results, form questions, status, refusals).

Cost rules: one small-model call (config.PHRASE_MODEL) with a short prompt, max ~200 output tokens, temperature
0.3, the last 2 user turns at most, no retrieval. Identical requests are cached for 10 minutes. If the call fails,
times out (config.PHRASE_TIMEOUT_S) or returns something unusable, the code's own draft is used, so a
conversation never breaks. Set PHRASE_MODEL="" to turn rephrasing off entirely."""
import asyncio
import hashlib
import json
import logging
import re
import time

import config
import llm
import prompts

logger = logging.getLogger(__name__)
_cache: dict[str, tuple[float, str]] = {}
CACHE_TTL_S = 600
CACHE_MAX = 500


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _keeps_essentials(draft: str, out: str) -> bool:
    """The rewrite must keep the draft's bold words, quoted options and numbers (e.g. **'No'**, 18, INR 6-9 LPA)."""
    must = re.findall(r"\*\*(.+?)\*\*", draft) + re.findall(r"'([^']{1,30})'", draft)
    must += re.findall(r"\d[\d,.\-]*", draft)
    low = out.lower()
    return all(m.strip("*").lower() in low for m in must if m.strip())


async def phrase(draft: str, user_role: str, user_message: str = "", facts: dict | None = None,
                 history: list[str] | None = None, cache: bool = True) -> str:
    """Reword `draft` naturally (same facts). Returns the draft itself on any problem."""
    if not config.PHRASE_MODEL or not config.GROQ_API_KEY:
        return draft
    key = _key(draft, user_role, user_message.strip().lower(), facts)
    hit = _cache.get(key) if cache else None
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    recent = "\n".join(f"User: {h}" for h in (history or [])[-2:])
    user = (f"{recent}\nUser: {user_message}\n\n" if user_message else "") + \
           (f"FACTS: {json.dumps(facts, ensure_ascii=False)}\n" if facts else "") + f"DRAFT: {draft}"
    try:
        out = await asyncio.wait_for(asyncio.to_thread(
            llm.complete, [{"role": "system", "content": prompts.phrase_system(user_role)},
                           {"role": "user", "content": user}],
            purpose="phrase", model=config.PHRASE_MODEL, temperature=0.3, max_tokens=config.PHRASE_MAX_TOKENS),
            timeout=config.PHRASE_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - timeout, rate limit, network: keep the draft
        logger.info("phrasing skipped (%s)", type(e).__name__)
        return draft
    out = (out or "").strip().strip('"')
    if not out or len(out) < 0.4 * len(draft) or len(out) > 3 * len(draft) + 200 \
            or not _keeps_essentials(draft, out):
        return draft
    if cache:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.time(), out)
    return out
