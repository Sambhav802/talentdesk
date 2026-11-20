"""Job questions answered from the job_openings collection itself (no LLM decides content, so no invented roles,
salaries or numbers). Every result is structured: {"type", "text", "intro", "cards", "suggestions", "facts"}.

list_jobs("python jobs in pune")                 -> openings filtered by city, department, level and role/skill words
job_detail("salary for the data analyst job")    -> one opening's card when the message names (part of) a title
compare_jobs("compare data analyst and data scientist") -> two cards side by side
"""
import re

from database import job_openings_collection

CITY_ALIASES = {
    "noida": "Noida", "gurugram": "Gurugram", "gurgaon": "Gurugram", "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru", "pune": "Pune", "hyderabad": "Hyderabad", "remote": "Remote",
    "work from home": "Remote", "wfh": "Remote", "anywhere": "Remote", "ghar se": "Remote",
}
DEPT_WORDS = {
    "HR": ["hr", "human resources", "recruit", "recruiter", "recruitment", "talent", "people team", "payroll"],
    "BPO": ["bpo", "support", "customer service", "call center", "call centre", "voice", "chat process", "collections"],
    "Tech": ["tech", "engineering", "engineer", "developer", "software", "programming", "it jobs", "coding"],
    "Finance": ["finance", "accounts", "accounting", "accountant"],
    "Sales": ["sales"],
    "Marketing": ["marketing", "seo", "content"],
    "Design": ["design", "designer", "ui/ux", "ux"],
    "Product": ["product manager", "product management", "business analyst"],
}
# words that only say "a job" (or are filler in a follow-up) and carry no role or skill
GENERIC = set("""show me list all any the a an in at for of and or with that are is jobs job openings opening roles
role positions position vacancies vacancy open available current currently what which do you have there please can
i see view find get want looking based near work from home remote onsite hybrid city location company your some new
latest hiring hire options opportunities opportunity apply applying career careers team department dept level my we
us our need am who here good suitable right now today only just also too aur sirf bhi mein me ke ki ka liye koi hai
hain kya batao dikhao naukri naukriyan about tell more details detail salary ctc pay package skills required
requirements require experience how much what's whats it does this those these them other""".split())
TOPIC_SYNONYMS = {
    "ai": ["ai", "ml", "machine learning", "llm", "generative"], "ml": ["ml", "machine learning", "ai"],
    "ai/ml": ["ai", "ml", "machine learning", "generative"], "genai": ["generative", "llm", "rag"],
    "developer": ["developer", "engineer"], "developers": ["developer", "engineer"], "engineer": ["engineer", "developer"],
    "frontend": ["frontend", "react", "ui"], "backend": ["backend", "api", "python", "java"],
    "data": ["data"], "analyst": ["analyst", "analytics"], "qa": ["qa", "test", "testing", "quality"],
    "testing": ["test", "qa"], "tester": ["test", "qa"], "devops": ["devops", "kubernetes", "aws", "reliability"],
    "fresher": [], "freshers": [], "intern": ["intern"], "internship": ["intern"], "internships": ["intern"],
}
LIST_CUE = re.compile(r"\b(jobs|openings|vacanc\w*|roles|positions|any|show|list|all|which|kaun|koi)\b", re.I)
DETAIL_WORDS = re.compile(r"\b(skill|skills|require|requirement|requirements|experience|salary|ctc|pay|package|"
                          r"budget|location|where|eligib\w*|qualif\w*|details?|describe|description|about|"
                          r"responsibilit\w*|deadline|last date|apply by|tell me|kitni|kitna|kya hai)\b", re.I)
COMPARE = re.compile(r"\b(compare|comparison|vs\.?|versus|difference between|better)\b", re.I)


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").lower()).strip()


def _city(msg: str, known: set) -> str | None:
    m = _norm(msg)
    for alias, city in CITY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", m):
            return city
    for city in known:                       # any other location an HR admin has added
        if city and re.search(rf"\b{re.escape(city.lower())}\b", m):
            return city
    return None


def _dept(msg: str) -> str | None:
    m = _norm(msg)
    for dept, words in DEPT_WORDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", m) for w in words):
            return dept
    return None


def _level(msg: str):
    m = _norm(msg)
    # "fresher" means no experience needed: only openings marked 0 years ("Freshers welcome")
    if re.search(r"\b(fresher|freshers|entry[- ]level|graduate|no experience|0 years?|beginner)\b", m):
        return "fresher", lambda e: e == 0
    if re.search(r"\b(intern|internship|internships)\b", m):
        return "intern", lambda e: e == 0
    if re.search(r"\b(senior|lead|leadership|manager|director|head)\b", m):
        return "senior", lambda e: e >= 5
    return None, None


def _topic_terms(msg: str, city: str | None, dept: str | None) -> list[list[str]]:
    """Role/skill words left after removing generic words, the city and the department words; each term with
    its synonyms (any synonym may match)."""
    m = _norm(msg)
    for alias in CITY_ALIASES:
        m = re.sub(rf"\b{re.escape(alias)}\b", " ", m)
    if dept:
        for w in DEPT_WORDS[dept]:
            m = re.sub(rf"\b{re.escape(w)}\b", " ", m)
    m = re.sub(r"\b(fresher|freshers|entry[- ]level|senior|junior|lead)\b", " ", m)
    out = []
    for w in (x.strip(".,?!'\"()") for x in re.findall(r"[a-z0-9+#/.\-']+", m)):
        if not w or w in GENERIC or len(w) < 2 or w.isdigit():
            continue
        syn = TOPIC_SYNONYMS.get(w)
        if syn == []:
            continue
        out.append(syn or [w])
    return out


def _haystack(j: dict) -> tuple[str, str, str]:
    skills = j.get("skills_required") or []
    skills = " ".join(skills) if isinstance(skills, list) else str(skills)
    return _norm(j.get("title", "")), _norm(skills), _norm(j.get("description", ""))


def _score(j: dict, terms: list[list[str]]) -> int:
    title, skills, desc = _haystack(j)
    total = 0
    for alternatives in terms:
        best = 0
        for t in alternatives:
            pat = rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])"
            if re.search(pat, title):
                best = max(best, 3)
            elif re.search(pat, skills):
                best = max(best, 2)
            elif re.search(pat, desc):
                best = max(best, 1)
        if best == 0:
            return 0                         # every role/skill word must match somewhere
        total += best
    return total


def _exp(j: dict) -> float:
    try:
        return float(j.get("experience_required") or 0)
    except (TypeError, ValueError):
        return 0.0


def _exp_label(j: dict) -> str:
    e = _exp(j)
    return "Freshers welcome" if e == 0 else f"{e:g}+ yrs"


def _salary(j: dict) -> str:
    ctc = str(j.get("budget") or j.get("ctc") or "").strip()
    if not ctc:
        return "Not disclosed"
    return ctc if re.search(r"lpa|annum|month|stipend", ctc, re.I) else f"{ctc} per annum"


def to_card(j: dict) -> dict:
    """The structured job card the frontend renders (and the source for the markdown fallback)."""
    skills = j.get("skills_required") or []
    return {"kind": "job", "id": str(j.get("_id", "")), "title": j.get("title", ""),
            "department": j.get("department", "General"), "location": j.get("location", "Not specified"),
            "remote": _norm(j.get("location")) == "remote", "employment_type": j.get("employment_type", "Full-time"),
            "experience": _exp_label(j), "experience_years": _exp(j), "salary": _salary(j),
            "openings": j.get("openings"), "apply_by": j.get("apply_by"), "posted_on": j.get("posted_on"),
            "skills": skills if isinstance(skills, list) else [str(skills)],
            "description": j.get("description", "")}


def card_md(c: dict, admin: bool = False) -> str:
    """Plain-text version of a card for clients that can't render cards (no emoji)."""
    extra = []
    if c.get("openings"):
        extra.append(f"{c['openings']} opening{'s' if c['openings'] != 1 else ''}")
    if c.get("apply_by"):
        extra.append(f"apply by {c['apply_by']}")
    line = (f"- **{c['title']}** · {c['department']} · {c['location']} · {c['experience']} · "
            f"{'Budget' if admin else 'CTC'} {c['salary']}")
    return line + (f" · {', '.join(extra)}" if extra else "")


def fallback_text(intro: str, cards: list[dict], admin: bool = False, tail: str = "") -> str:
    return f"{intro}\n\n" + "\n".join(card_md(c, admin) for c in cards) + (f"\n\n{tail}" if tail else "")


def facts_of(cards: list[dict], limit: int = 5) -> list[dict]:
    """Compact summary for the phrasing model (never the full cards)."""
    return [{"title": c["title"], "city": c["location"], "exp": c["experience"], "salary": c["salary"]}
            for c in cards[:limit]]


async def _all_jobs() -> list[dict]:
    return await job_openings_collection.find({}).to_list(1000)


async def list_jobs(message: str, user_role: str = "Candidate", limit: int = 10) -> dict:
    jobs = await _all_jobs()
    admin = user_role == "HR Admin"
    if not jobs:
        text = "There are no open positions right now. Please check back soon."
        return {"type": "not_found", "text": text, "intro": text, "cards": [], "suggestions": [], "facts": {}}
    city = _city(message, {j.get("location", "") for j in jobs})
    dept = _dept(message)
    level_name, level = _level(message)
    terms = _topic_terms(message, city, dept)

    pool = jobs
    if city:
        pool = [j for j in pool if _norm(j.get("location")) == city.lower()]
    if level:
        pool = [j for j in pool if level(_exp(j))]
    if dept and not terms:
        in_dept = [j for j in pool if _norm(j.get("department")) == dept.lower()]
        pool = in_dept or [j for j in pool if _score(j, [[w] for w in DEPT_WORDS[dept][:1]])]
    elif dept:
        pool = [j for j in pool if _norm(j.get("department")) == dept.lower()] or pool
    if terms:
        scored = sorted(((_score(j, terms), j) for j in pool), key=lambda x: -x[0])
        pool = [j for s, j in scored if s > 0]

    where = f" in **{city}**" if city and city != "Remote" else (" (**remote**)" if city == "Remote" else "")
    what = " ".join(t[0] for t in terms) if terms else (level_name or dept or "")
    facts = {"city": city, "team": dept, "level": level_name, "role_words": what, "count": len(pool)}
    if not pool:
        text = (f"I couldn't find any {('**' + what + '** ') if what else ''}openings{where} right now. "
                f"Try another city or role, or ask me to **show all job openings**.")
        sugg = ["Show all job openings"] + ([f"{what.title()} jobs" if what else "Remote jobs"] if city else
                                            ["Jobs in Bengaluru", "Remote jobs"])
        return {"type": "not_found", "text": text, "intro": text, "cards": [], "suggestions": sugg[:3], "facts": facts}

    cards = [to_card(j) for j in pool]
    shown = cards[:limit]
    n = len(cards)
    showing = f" (showing the first {limit}; narrow it down by city, team or skill)" if n > limit else ""
    intro = (f"**Open requisitions{where}**: {n}{showing}." if admin
             else f"Here {'is' if n == 1 else 'are'} **{n} open role{'' if n == 1 else 's'}**{where}"
                  + (f" matching **{what}**" if what else "") + f"{showing}.")
    tail = ("You can ask me to generate a job description for any of these roles." if admin
            else "Tap **Apply** on a role, or reply \"I want to apply for the <role> job\".")
    text = intro
    sugg = [] if admin else [f"Apply for {shown[0]['title']}"]
    if not city:
        sugg.append(f"{(what or 'All').title()} jobs in Bengaluru")
    if not level:
        sugg.append("Jobs for freshers")
    facts["top"] = facts_of(shown)
    return {"type": "jobs", "text": text, "intro": intro, "cards": shown, "suggestions": sugg[:3], "facts": facts,
            "total": n, "fallback": fallback_text(intro, shown, admin, tail)}


async def find_named_jobs(message: str) -> list[dict]:
    """Openings whose title the message names, best first: the full title, the title without its bracket/dash
    part, or (for partial titles like "the devops role") every distinctive word of the title's head."""
    m = _norm(message)
    words = set(re.findall(r"[a-z0-9+#/.\-]+", m))
    found = []
    for j in await _all_jobs():
        title = _norm(j.get("title"))
        core = re.sub(r"\s*(\(.*|- .*)$", "", title).strip()       # "tech lead - ai" -> "tech lead"
        score = 0
        for t, s in ((title, 3), (core, 2)):
            if t and re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", m):
                score = max(score, s * 100 + len(t))
        if not score:
            head = [w for w in re.findall(r"[a-z0-9+#/.]+", core) if w not in GENERIC and len(w) > 2]
            distinctive = [w for w in head if w not in ("engineer", "developer", "executive", "manager", "specialist",
                                                        "lead", "senior", "junior", "analyst", "associate")]
            if distinctive and all(w in words for w in distinctive):
                score = 50 + len(distinctive)
        if score:
            found.append((score, j))
    found.sort(key=lambda x: -x[0])
    if found and found[0][0] >= 100:                 # an exact title was named: drop weaker partial matches
        found = [f for f in found if f[0] >= 100]
    return [j for _, j in found]


async def job_detail(message: str, user_role: str = "Candidate") -> dict | None:
    """One opening's card when the message asks about a named role; None when it is a listing question, a
    comparison, an action, or no existing title is named."""
    if re.search(r"\b(generate|create|write|draft|delete|remove|close|approve|apply)\b", message, re.I):
        return None
    if COMPARE.search(message) or not DETAIL_WORDS.search(message):
        return None
    if re.search(r"\b(jobs|openings|vacanc\w*|positions)\b", message, re.I):
        return None                                  # "any Python developer openings?" is a list question
    named = await find_named_jobs(message)
    if not named:
        return None
    titles = {_norm(j.get("title")) for j in named}
    if len(titles) > 1 and not any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", _norm(message)) for t in titles):
        cards = [to_card(j) for j in named[:4]]      # a partial title matched several roles: let them pick
        intro = "I found a few roles that match. Which one do you mean?"
        return {"type": "jobs", "text": intro, "fallback": fallback_text(intro, cards), "intro": intro, "cards": cards, "suggestions": [f"Tell me about the {c['title']} role" for c in cards[:3]],
                "facts": {"top": facts_of(cards)}}
    c = to_card(named[0])
    admin = user_role == "HR Admin"
    intro = f"Here are the details for **{c['title']}** ({c['location']}):"
    text = intro
    tail = f"Tap **Apply** or reply \"I want to apply for the {c['title']} job\"." if user_role == "Candidate" else ""
    sugg = ([f"Apply for {c['title']}"] if user_role == "Candidate" else []) + \
           [f"Other jobs in {c['location']}" if not c["remote"] else "Other remote jobs", f"{c['department']} jobs"]
    return {"type": "job_detail", "text": text, "fallback": fallback_text(intro, [c], admin, tail), "intro": intro,
            "cards": [c], "suggestions": sugg[:3],
            "facts": {"top": facts_of([c])}}


async def compare_jobs(message: str) -> dict | None:
    if not COMPARE.search(message):
        return None
    uniq, seen = [], set()
    for j in await find_named_jobs(message):
        t = _norm(j.get("title"))
        if t not in seen:
            seen.add(t)
            uniq.append(j)
    if len(uniq) < 2:
        return None
    m = _norm(message)

    def mentioned_at(j):                     # keep the order the user named them in
        t = _norm(j.get("title"))
        core = re.sub(r"\s*(\(.*|- .*)$", "", t).strip()
        pos = [m.find(x) for x in (t, core) if x and m.find(x) >= 0]
        return min(pos) if pos else len(m)
    uniq = sorted(uniq[:4], key=mentioned_at)
    a, b = to_card(uniq[0]), to_card(uniq[1])
    rows = [("City", a["location"], b["location"]), ("Team", a["department"], b["department"]),
            ("Experience", a["experience"], b["experience"]), ("Salary", a["salary"], b["salary"]),
            ("Openings", a.get("openings") or "-", b.get("openings") or "-"),
            ("Key skills", ", ".join(a["skills"][:4]), ", ".join(b["skills"][:4]))]
    table = f"| | **{a['title']}** | **{b['title']}** |\n|---|---|---|\n" + \
            "\n".join(f"| {k} | {x} | {y} |" for k, x, y in rows)
    intro = f"Here's how **{a['title']}** and **{b['title']}** compare:"
    return {"type": "compare", "text": f"{intro}\n\n{table}", "fallback": f"{intro}\n\n{table}", "intro": intro,
            "cards": [a, b],
            "suggestions": [f"Apply for {a['title']}", f"Apply for {b['title']}"], "facts": {"top": facts_of([a, b])}}
