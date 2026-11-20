"""Natural wording for replies whose facts were decided in code (job results, form questions, status, refusals).

Cost rules: one small-model call (config.PHRASE_MODEL) with a short prompt, max ~300 output tokens, temperature
0.3, the last 2 user turns at most, no retrieval. Identical requests are cached for 10 minutes. If the call fails,
times out (config.PHRASE_TIMEOUT_S) or returns something unusable, the code's own draft is used, so a
conversation never breaks. Set PHRASE_MODEL="" to turn rephrasing off entirely.

Safety: every call states the reply's PURPOSE and the words it MUST keep. A rewrite is rejected (the template is
used) when it drops a required word, number, bold or quoted option, adds an action/topic the draft doesn't have
(e.g. offering "candidate counts" while asking for a department), becomes a list, or changes length wildly."""
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

# words that introduce a new action, data source or promise: a rewrite may use one only if the draft or the
# purpose already does (this is what turned "enter the department" into "I'll pull up the candidate count")
RISKY = set("""candidate candidates applicant applicants count counts pipeline shortlist shortlisted reject rejected
interview interviews schedule scheduled email emails mail call calls phone notify notification pull fetch check
status update updated approve approved salary ctc bonus offer offers refund guarantee guaranteed promise promised
deadline policy policies leave leaves job jobs role roles opening openings resume cv link portal ticket""".split())

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿←-⇿⌀-⏿️]")


FILLER = set("""sure thing happy glad help helping great thanks thank sorry unfortunately however please could would
should will shall just let know right away today here there your yours you that this these those with from into about
also okay alright absolutely certainly definitely gladly quick quickly simply first next then once share tell give
provide send type enter reply below above shown following like love want need able kindly feel free ahead start
started what which when where while still only it's i'm i'll can't don't isn't""".split())


def limit_emoji(text: str, keep: int = 1) -> str:
    """At most `keep` emoji in a reply's prose (the first ones stay)."""
    seen = 0

    def sub(m):
        nonlocal seen
        if m.group(0) == "️":
            return "" if seen > keep else m.group(0)
        seen += 1
        return m.group(0) if seen <= keep else ""
    out = _EMOJI.sub(sub, text or "")
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"^\s+(?=\S)", "", out, flags=re.M)).strip()


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def _keeps_essentials(draft: str, out: str) -> bool:
    """The rewrite must keep the draft's bold words, quoted options and numbers (e.g. **'No'**, 18, INR 6-9 LPA)."""
    must = re.findall(r"\*\*(.+?)\*\*", draft) + re.findall(r"'([^']{1,30})'", draft)
    must += re.findall(r"\d[\d,.\-]*", draft)
    low = out.lower()
    return all(m.strip("*").lower() in low for m in must if m.strip())


def acceptable(draft: str, out: str, purpose: str = "", must_keep: list[str] | None = None,
               user_message: str = "") -> bool:
    if not out or len(out) < 0.4 * len(draft) or len(out) > 3 * len(draft) + 200:
        return False
    if not _keeps_essentials(draft, out):
        return False
    low = out.lower()
    if any(k.lower() not in low for k in (must_keep or [])):
        return False
    if "\n" not in draft and re.search(r"\n\s*([-*•]|\d+\.)\s", "\n" + out):
        return False                                   # a one-paragraph draft must not become a list
    allowed = _words(draft) | _words(purpose) | _words(user_message)
    added = (_words(out) & RISKY) - allowed
    if added:
        return False
    # a rewrite may add friendly filler, not new subjects ("the notice period during probation isn't available")
    novel = {w for w in _words(out) - allowed - FILLER if len(w) >= 4}
    return len(novel) <= 2


async def phrase(draft: str, user_role: str, user_message: str = "", facts: dict | None = None,
                 history: list[str] | None = None, cache: bool = True, purpose: str = "",
                 must_keep: list[str] | None = None) -> str:
    """Reword `draft` naturally (same facts, same purpose). Returns the draft itself on any problem."""
    if not config.PHRASE_MODEL or not config.GROQ_API_KEY:
        return draft
    key = _key(draft, user_role, user_message.strip().lower(), facts, purpose)
    hit = _cache.get(key) if cache else None
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    # only the current message (to match the user's language): earlier turns leaked old topics into rewrites
    user = (f"User: {user_message}\n\n" if user_message else "") + \
           (f"PURPOSE: {purpose}\n" if purpose else "") + \
           (f"MUST KEEP: {', '.join(must_keep)}\n" if must_keep else "") + \
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
    out = limit_emoji((out or "").strip().strip('"'))
    # the cards show the jobs: an intro that names job titles (inline or as a list) repeats them
    titles = [t.get("title", "") for t in ((facts or {}).get("top") or []) if isinstance(t, dict)]
    if any(t and t.lower() in out.lower() and t.lower() not in draft.lower() for t in titles):
        logger.info("phrasing rejected (repeats the cards); using the template")
        return draft
    if not acceptable(draft, out, purpose, must_keep, user_message):
        logger.info("phrasing rejected (meaning/fields changed); using the template")
        return draft
    if cache:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.time(), out)
    return out
