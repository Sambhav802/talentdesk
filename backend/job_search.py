"""Job questions answered from the job_openings collection itself (no LLM, so no invented roles or numbers).

list_jobs("python jobs in pune")          -> openings filtered by city, department, level and role/skill words
job_detail("skills for the data analyst role") -> one opening's card, when the message names an existing title
"""
import re

from database import job_openings_collection

CITY_ALIASES = {
    "noida": "Noida", "gurugram": "Gurugram", "gurgaon": "Gurugram", "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru", "pune": "Pune", "hyderabad": "Hyderabad", "remote": "Remote",
    "work from home": "Remote", "wfh": "Remote", "anywhere": "Remote",
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
# words that only say "a job" and carry no role or skill
GENERIC = set("""show me list all any the a an in at for of and or with that are is jobs job openings opening roles
role positions position vacancies vacancy open available current currently what which do you have there please can
i see view find get want looking based near work from home remote onsite hybrid city location company your some new
latest hiring hire for openings? jobs? roles? options opportunities opportunity apply applying career careers
team department dept level my me we us our need am who here good suitable right now today""".split())
TOPIC_SYNONYMS = {
    "ai": ["ai", "ml", "machine learning", "llm", "generative"], "ml": ["ml", "machine learning", "ai"],
    "ai/ml": ["ai", "ml", "machine learning", "generative"], "genai": ["generative", "llm", "rag"],
    "developer": ["developer", "engineer"], "developers": ["developer", "engineer"], "engineer": ["engineer", "developer"],
    "frontend": ["frontend", "react", "ui"], "backend": ["backend", "api", "python", "java"],
    "data": ["data"], "analyst": ["analyst", "analytics"], "qa": ["qa", "test", "testing", "quality"],
    "testing": ["test", "qa"], "tester": ["test", "qa"], "devops": ["devops", "kubernetes", "aws", "reliability"],
    "fresher": [], "freshers": [], "intern": ["intern"], "internship": ["intern"], "internships": ["intern"],
}
DETAIL_WORDS = re.compile(r"\b(skill|skills|require|requirement|requirements|experience|salary|ctc|pay|package|budget|"
                          r"location|where|eligib\w*|qualif\w*|details?|describe|description|about|responsibilit\w*|"
                          r"openings|deadline|last date|apply by|tell me)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _city(msg: str, known: set[str]) -> str | None:
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
    if re.search(r"\b(fresher|freshers|entry[- ]level|graduate|no experience|0 years?|beginner)\b", m):
        return lambda e: e <= 1
    if re.search(r"\b(intern|internship|internships)\b", m):
        return lambda e: e <= 1
    if re.search(r"\b(senior|lead|leadership|manager|director|head)\b", m):
        return lambda e: e >= 5
    return None


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
    words = [w.strip(".,?!'\"()") for w in re.findall(r"[a-z0-9+#/.\-]+", m)]
    out = []
    for w in words:
        if not w or w in GENERIC or len(w) < 2:
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


def _ctc(j: dict) -> str:
    ctc = str(j.get("budget") or j.get("ctc") or "").strip()
    if not ctc:
        return "Not disclosed"
    return ctc if re.search(r"lpa|annum|month|stipend", ctc, re.I) else f"{ctc} per annum"


def _exp(j: dict) -> str:
    e = j.get("experience_required")
    try:
        e = float(e)
        return "Freshers welcome" if e == 0 else f"{e:g}+ yrs"
    except (TypeError, ValueError):
        return str(e or "Not specified")


def card(j: dict, admin: bool = False) -> str:
    skills = j.get("skills_required") or []
    skills = ", ".join(skills) if isinstance(skills, list) else str(skills)
    lines = [f"💼 **{j.get('title')}**",
             f"🏢 *{j.get('department', 'General')}* | 📍 **{j.get('location', 'Not specified')}** | "
             f"{j.get('employment_type', 'Full-time')}",
             f"🎓 **Experience:** {_exp(j)} | 💰 **{'Budget' if admin else 'CTC'}:** {_ctc(j)}",
             f"🛠️ **Skills:** {skills or 'Not specified'}"]
    extra = []
    if j.get("openings"):
        extra.append(f"**Openings:** {j['openings']}")
    if j.get("apply_by"):
        extra.append(f"**Apply by:** {j['apply_by']}")
    if extra:
        lines.append("📌 " + " | ".join(extra))
    if j.get("description"):
        lines.append(f"📝 *{j['description']}*")
    return "\n".join(lines)


async def list_jobs(message: str, user_role: str = "Candidate", limit: int = 10) -> str:
    jobs = await job_openings_collection.find({}).to_list(1000)
    if not jobs:
        return "There are no open positions right now. Please check back soon."
    city = _city(message, {j.get("location", "") for j in jobs})
    dept = _dept(message)
    level = _level(message)
    terms = _topic_terms(message, city, dept)

    pool = jobs
    if city:
        pool = [j for j in pool if _norm(j.get("location")) == city.lower()]
    if level:
        def exp(j):
            try:
                return float(j.get("experience_required") or 0)
            except (TypeError, ValueError):
                return 0.0
        pool = [j for j in pool if level(exp(j))]
    if dept and not terms:
        in_dept = [j for j in pool if _norm(j.get("department")) == dept.lower()]
        # "HR roles": the HR department; "support roles": the BPO department
        pool = in_dept or [j for j in pool if _score(j, [[w] for w in DEPT_WORDS[dept][:1]])]
    elif dept:
        pool = [j for j in pool if _norm(j.get("department")) == dept.lower()] or pool
    if terms:
        scored = sorted(((_score(j, terms), j) for j in pool), key=lambda x: -x[0])
        pool = [j for s, j in scored if s > 0]

    where = f" in **{city}**" if city and city != "Remote" else (" (**remote**)" if city == "Remote" else "")
    if not pool:
        what = " ".join(t[0] for t in terms) if terms else (dept or "")
        what = f"**{what}** " if what else ""
        return (f"I couldn't find any {what}openings{where} right now. "
                f"Try another city or role, or ask me to **show all job openings**.")

    admin = user_role == "HR Admin"
    shown = pool[:limit]
    head = (f"🗂️ **Open requisitions{where}** ({len(pool)})" if admin
            else f"Here {'is' if len(pool) == 1 else 'are'} **{len(pool)} open role{'' if len(pool) == 1 else 's'}**{where}:")
    body = "\n━━━━━━━━━━━━━━━━━━━━━━\n".join(card(j, admin) for j in shown)
    more = (f"\n\n…and {len(pool) - limit} more. Narrow it down by city, team or skill (for example "
            f"*\"Python jobs in Pune\"*)." if len(pool) > limit else "")
    tail = ("\n\n💡 *You can ask me to generate a job description for any of these roles.*" if admin
            else "\n\nReady? Reply **\"I want to apply for a job\"** to start your application.")
    return f"{head}\n\n{body}{more}{tail}"


async def find_named_job(message: str) -> dict | None:
    """The opening whose title the message names (longest title wins), if any."""
    m = _norm(message)
    best = None
    for j in await job_openings_collection.find({}).to_list(1000):
        title = _norm(j.get("title"))
        core = re.sub(r"\s*\(.*?\)\s*", " ", title).strip()       # "HR Business Partner (HRBP)" -> core title
        for t in {title, core}:
            if t and re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", m):
                if not best or len(t) > best[0]:
                    best = (len(t), j)
    return best[1] if best else None


async def job_detail(message: str, user_role: str = "Candidate") -> str | None:
    """Card for the named opening when the message asks about it; None when no existing title is named."""
    if not DETAIL_WORDS.search(message) or re.search(
            r"\b(generate|create|write|draft|delete|remove|close|approve|apply)\b", message, re.I):
        return None
    j = await find_named_job(message)
    if not j:
        return None
    return (f"Here are the details for this opening:\n\n{card(j, user_role == 'HR Admin')}\n\n"
            "Reply **\"I want to apply for a job\"** to apply.")
