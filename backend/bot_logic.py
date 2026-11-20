import os
import re
import json
import datetime
import logging

import config
import llm
from database import (job_openings_collection, candidates_collection, hiring_requests_collection,
                      chat_history_collection, sessions_collection, resume_files_collection)
from rag import store as kb
from rag import answer as kb_answer
import job_search
import phrasing
import prompts
from router import (POLICY as POLICY_HINT, is_correction, is_follow_up, is_rephrase,
                    rule_intent)

logger = logging.getLogger(__name__)

# Short classification / extraction calls. GROQ_MODEL may be a reasoning model (default openai/gpt-oss-120b) that
# spends tokens thinking before it answers: a cap of ~10 tokens returns an EMPTY answer, so keep room for that.
SHORT_ANSWER_TOKENS = 300

# In-request cache of the multi-step form state. The source of truth is MongoDB (chat_sessions), so a
# conversation survives serverless cold starts and requests landing on different instances.
sessions = {}


class _GroqShim:
    """Keeps the original `groq_client.chat.completions.create(...)` call sites; the client is created lazily
    and the model always comes from GROQ_MODEL."""

    class _Completions:
        def create(self, **kwargs):
            kwargs.pop("model", None)
            return llm.create(purpose="flow", model=config.GROQ_MODEL, **kwargs)

    class _Chat:
        def __init__(self):
            self.completions = _GroqShim._Completions()

    def __init__(self):
        self.chat = _GroqShim._Chat()


groq_client = _GroqShim()


async def _load_session(session_id: str) -> dict:
    doc = await sessions_collection.find_one({"_id": session_id})
    if doc:
        return {"intent": doc.get("intent"), "step": doc.get("step"), "data": doc.get("data") or {}}
    return {"intent": None, "step": None, "data": {}}


async def _save_session(session_id: str, state: dict) -> None:
    if not state.get("intent"):
        await sessions_collection.delete_one({"_id": session_id})
        return
    data = {k: v for k, v in (state.get("data") or {}).items() if k != "_id"}
    await sessions_collection.update_one(
        {"_id": session_id},
        {"$set": {"intent": state.get("intent"), "step": state.get("step"), "data": data,
                  "updated_at": datetime.datetime.now(datetime.timezone.utc)}},
        upsert=True)


async def _resume_text(path: str) -> str:
    """Resumes are parsed at upload time and stored in MongoDB; the chat message carries
    'uploads/<file id>/<file name>.pdf'. A local file path still works for older local setups."""
    m = re.match(r"^uploads/([0-9a-f]{24})/", path)
    if m:
        from bson import ObjectId
        doc = await resume_files_collection.find_one({"_id": ObjectId(m.group(1))}, {"text": 1})
        if doc:
            return doc.get("text") or ""
    if os.path.isfile(path):
        from pypdf import PdfReader
        return "".join(page.extract_text() or "" for page in PdfReader(path).pages)
    raise FileNotFoundError(path)


async def _reindex_jobs_safely():
    try:
        await kb.reindex_jobs()
    except Exception as e:  # noqa: BLE001 - the job change itself already succeeded
        logger.warning("job re-index failed: %s", e)


GREETINGS = {
    "Candidate": "Hi! 👋 I can show open roles (try *\"Python jobs in Pune\"* or *\"remote jobs\"*), help you apply, "
                 "check your application status, and answer questions about our hiring process and policies.",
    "Hiring Manager": "Hello! I can raise a hiring request for your team and answer HR policy questions "
                      "(leave, notice period, referral bonus, probation and more).",
    "HR Admin": "Welcome back. Ask about candidates and hiring requests, generate a job description, manage openings, "
                "or ask anything covered by the HR knowledge base.",
}


async def answer_from_kb(question: str, user_role: str = "Candidate", follow_up: tuple | None = None) -> dict:
    """RAG: retrieve from the HR knowledge base and answer with citations (or say it is not covered).
    Policy questions search the handbook and uploaded documents first; job postings only if nothing matches."""
    try:
        hits = await kb.search(question, doc_type="document") or await kb.search(question)
    except Exception as e:  # noqa: BLE001
        logger.warning("KB search failed: %s", e)
        hits = []
    return kb_answer.answer(question, hits, user_role=user_role, follow_up=follow_up)


def _general_rule_question(message: str) -> tuple[str, str]:
    """Personal-record questions ("how many leaves do I have left") become the general-rule question."""
    m = message.lower()
    if re.search(r"salary|ctc|payslip|tankh|vetan|pay\b", m):
        return "salary and payslips", "When is salary credited and where are payslips available?"
    if re.search(r"apprais|rating|increment|hike|promotion", m):
        return "rating", "How do performance reviews, increments and promotions work?"
    if re.search(r"sick", m):
        return "sick leave balance", "How many days of sick leave do employees get and do they carry forward?"
    return "leave balance", "How many days of annual and sick leave do employees get and how much carries forward?"


async def _pipeline_counts() -> dict:
    """HR Admin: candidate counts by screening status, straight from the database."""
    groups = [("Shortlisted", r"Shortlisted"), ("Awaiting interview", r"interview|Awaiting"),
              ("Pending review", r"Pending"), ("Not suitable / rejected", r"Not suitable|Missing|Reject")]
    total = await candidates_collection.count_documents({})
    rows = []
    for label, rx in groups:
        rows.append((label, await candidates_collection.count_documents(
            {"screening_status": {"$regex": rx, "$options": "i"}})))
    reqs = await hiring_requests_collection.count_documents({})
    jobs = await job_openings_collection.count_documents({})
    table = "| Stage | Candidates |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in rows) + \
            f"\n| **Total** | **{total}** |"
    text = (f"**{total} candidate{'s' if total != 1 else ''} in the pipeline**, {jobs} open roles and "
            f"{reqs} pending hiring request{'s' if reqs != 1 else ''}.\n\n{table}")
    return {"text": text, "type": "stats", "citations": [], "cards": [
        {"kind": "stats", "title": "Hiring pipeline", "rows": [{"label": k, "value": v} for k, v in rows],
         "total": total, "open_roles": jobs, "pending_requests": reqs}],
        "suggestions": ["Shortlisted candidates", "Pending hiring requests", "Show all candidates"], "intro": ""}

# --- GLOBALLY DEFINED BACKGROUND EMAIL FUNCTION ---
async def send_hr_email_notification(candidate_name, role, current_status):
    print("\n" + "="*50)
    print(f"📧 EMAIL SENT TO: hr-team@company.com")
    print(f"Subject: New Application - {candidate_name} for {role}")
    print(f"Body: A new candidate has applied. Screening status: {current_status}. Please check the admin dashboard.")
    print("="*50 + "\n")

# --- HR ADMIN CLASSIFIER (only for HR Admin messages the rule router could not place) ---
ADMIN_INTENTS = ["hr_admin_queries", "hr_find_candidate", "hr_update_status", "hr_generate_jd", "hr_manage_jobs",
                 "view_jobs", "hr_knowledge"]


def classify_admin(message: str) -> str | None:
    try:
        raw = llm.complete([{"role": "user", "content": prompts.CLASSIFIER.format(message=message)}],
                           purpose="classify", model=config.PHRASE_MODEL or config.GROQ_MODEL,
                           temperature=0, max_tokens=SHORT_ANSWER_TOKENS)
    except Exception as e:  # noqa: BLE001
        logger.warning("classifier skipped: %s", e)
        return None
    raw = (raw or "").strip().lower()
    return next((k for k in ADMIN_INTENTS if k in raw), None)


def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def is_valid_phone(phone):
    clean = re.sub(r'\D', '', phone)
    return len(clean) >= 10

def is_numeric(val):
    try:
        float(val)
        return True
    except ValueError:
        return False

# --- CANDIDATE EVALUATION MATRIX ---
async def evaluate_candidate(data: dict):
    job = await job_openings_collection.find_one({"title": {"$regex": data.get('preferred_role', ''), "$options": "i"}})
    if not job:
        return "Role not found in active database, but profile saved.", "Pending Review"

    job_exp_str = str(job.get("experience_required", "0"))
    nums = re.findall(r'\d+\.?\d*', job_exp_str)
    req_exp_min = float(nums[0]) if nums else 0.0
    req_exp_max = float(nums[1]) if len(nums) > 1 else 99.0
    
    cand_exp_str = str(data.get("total_experience", "0"))
    cand_nums = re.findall(r'\d+\.?\d*', cand_exp_str)
    cand_exp = float(cand_nums[0]) if cand_nums else 0.0

    exp_match = (req_exp_min <= cand_exp <= req_exp_max) or (len(nums) == 1 and cand_exp >= req_exp_min)

    req_skills = [s.lower() for s in job.get("skills_required", [])]
    
    raw_skills = data.get("skills", "")
    if isinstance(raw_skills, list):
        cand_skills = [str(s).strip().lower() for s in raw_skills]
    else:
        cand_skills = [s.strip().lower() for s in str(raw_skills).split(",")]
        
    matched_skills = [s for s in cand_skills if any(req in s or s in req for req in req_skills)]
    skill_match = len(matched_skills) >= 2

    job_loc = job.get("location", "").lower()
    cand_loc = data.get("location", "").lower()
    loc_match = (job_loc in cand_loc) or (cand_loc in job_loc) or ('remote' in job_loc) or ('any' in job_loc)

    if exp_match and skill_match and loc_match:
        status = "Shortlisted for next step"
    elif not exp_match:
        status = "Not suitable based on required experience"
    elif not skill_match:
        status = "Missing required skills (minimum 2 needed)"
    else:
        status = "Not suitable based on location"

    job_title = job.get('title', data.get('preferred_role', 'N/A'))
    job_loc_final = job.get('location', 'N/A')

    summary = f"""
    **Application Summary**
    • Name: {data.get('full_name', 'N/A')}
    • Evaluated For: **{job_title}** (📍 {job_loc_final})
    • Experience: {cand_exp} years
    • Skills Matched: {len(matched_skills)}
    • Location Match: {'Yes' if loc_match else 'No'}
    • Screening Status: **{status}**
    """
    return summary, status

def _result(text: str, type_: str = "message", **kw) -> dict:
    out = {"text": text, "type": type_, "citations": [], "cards": [], "suggestions": [], "intro": ""}
    out.update(kw)
    return out


async def _previous_turn(session_id: str) -> dict | None:
    """The last completed exchange of this conversation (the current message is already stored, so skip it)."""
    try:
        docs = await chat_history_collection.find({"session_id": session_id}).sort("timestamp", -1).to_list(5)
    except Exception:  # noqa: BLE001
        return None
    older = docs[1:]
    bot = next((d for d in older if d.get("role") == "bot"), None)
    user = next((d for d in older if d.get("role") == "user"), None)
    if not bot or not user:
        return None
    return {"user": user.get("message", ""), "bot": bot.get("message", ""), "type": bot.get("type", ""),
            "history": [d.get("message", "") for d in reversed(older) if d.get("role") == "user"]}


async def process_message(session_id: str, message: str, user_role: str = "Candidate") -> dict:
    """Returns {"text", "type", "citations", "cards", "suggestions", "intro"}; `text` is always a complete markdown
    reply (older clients show only that), the rest lets the frontend render cards and quick replies."""
    sessions[session_id] = await _load_session(session_id)
    try:
        prev = await _previous_turn(session_id)
        raw = await _process_message(session_id, message, user_role, prev)
        state = sessions.get(session_id) or {}
        in_form = bool(state.get("intent"))
        res = raw if isinstance(raw, dict) else _result(str(raw), "form" if in_form else "message")
        res.setdefault("type", "message")
        for k, v in (("citations", []), ("cards", []), ("suggestions", []), ("intro", "")):
            res.setdefault(k, v)
        step = (state.get("intent"), state.get("step")) if in_form else None
        return await _natural_wording(res, message, user_role, prev, step)
    finally:
        await _save_session(session_id, sessions.pop(session_id, {"intent": None}))


async def _natural_wording(res: dict, message: str, user_role: str, prev: dict | None,
                           step: tuple | None = None) -> dict:
    """Let the small model reword code-written replies, keeping their purpose (never policy answers, never when a
    model was already called this turn, never long lists, never a form step without a declared purpose). The
    rewrite is checked (required words kept, no new actions); on any doubt the template stays."""
    facts = res.pop("facts", None)
    kind = res["type"]
    prose = kind not in ("policy", "correction", "stats")
    if prose:
        res["text"] = phrasing.limit_emoji(res["text"])
        res["intro"] = phrasing.limit_emoji(res.get("intro", ""))
    if llm.turn_usage():
        return res
    history = (prev or {}).get("history", [])
    if kind in ("jobs", "job_detail", "compare") and res.get("intro"):
        new = await phrasing.phrase(res["intro"], user_role, message, facts=facts, history=history,
                                    purpose=prompts.REPLY_PURPOSE[kind])
        if new != res["intro"]:
            res["text"] = res["text"].replace(res["intro"], new, 1)
            res["intro"] = new
        return res
    if kind == "form":
        spec = prompts.FORM_STEPS.get(step or ())
        if not spec or "\n- " in res["text"] or "|" in res["text"]:
            return res                                   # unknown step or a list/summary: keep the template
        purpose, must_keep = spec
        # form answers can hold personal data (email, phone): never cache those rewrites
        res["text"] = await phrasing.phrase(res["text"], user_role, message, history=history, cache=False,
                                            purpose=purpose, must_keep=must_keep)
        return res
    if kind in ("message", "greeting", "refusal", "not_found") and len(res["text"]) <= 450 \
            and "\n- " not in res["text"] and "\n• " not in res["text"] and "|" not in res["text"]:
        res["text"] = await phrasing.phrase(res["text"], user_role, message, history=history,
                                            purpose=prompts.REPLY_PURPOSE[kind])
    return res


async def _recheck(prev: dict, message: str, user_role: str) -> dict:
    """The user says the last answer was wrong: re-read the sources for the same question; never adopt the claim
    blindly, never double down without quoting the handbook, and offer a way to reach HR."""
    if prev.get("type") in ("jobs", "job_detail", "compare") or (
            prev.get("type") == "not_found" and not POLICY_HINT.search(prev["user"])):
        return _result("Sorry about that. The roles I show come straight from our current openings. Tell me the "
                       "role, city or experience level you had in mind and I'll search again.", "message",
                       suggestions=["Show all job openings", "Remote jobs", "Jobs for freshers"])
    try:
        hits = await kb.search(prev["user"], doc_type="document") or await kb.search(prev["user"])
    except Exception as e:  # noqa: BLE001
        logger.warning("KB search failed: %s", e)
        hits = []
    res = kb_answer.answer(prev["user"], hits, user_role=user_role, correction=message, previous=prev["bot"])
    if res["type"] == "not_found":
        res["text"] = ("Thanks for flagging it. I couldn't find this in the HR knowledge base, so I can't confirm "
                       "either answer. Please raise a ticket in the HR portal and the HR team will confirm.")
    res["suggestions"] = (res.get("suggestions") or [])[:2] + ["How do I contact HR?"]
    if res["type"] == "policy":
        res["type"] = "correction"
    return res


async def _process_message(session_id: str, message: str, user_role: str = "Candidate", prev: dict | None = None):
    message_lower = message.lower().strip()
    role = prompts.role_of(user_role)

    if session_id not in sessions:
        sessions[session_id] = {"intent": None, "step": None, "data": {}}
    session = sessions[session_id]

    # 1. Check for Cancel/Stop
    if message_lower in ["cancel", "stop", "exit", "quit", "abort", "ruko", "band karo"]:
        sessions[session_id] = {"intent": None, "step": None, "data": {}}
        return _result("🚫 **Process Cancelled.**\n\nI have cleared your current progress. What would you like to do instead?",
                       "message", suggestions=prompts.DEFAULT_SUGGESTIONS[role][:3])

    # 2. Check for Chat Reset
    reset_phrases = ["start over", "scrap this chat", "lets start", "let's start",
                     "restart", "start again", "clear chat", "scrap chat"]
    if message_lower in reset_phrases:
        sessions[session_id] = {"intent": None, "step": None, "data": {}}
        return _result("🔄 **Chat Reset!**\n\nWhat would you like to ask?", "message",
                       suggestions=prompts.DEFAULT_SUGGESTIONS[role][:3])

    # 3. A question asked in the middle of a form is answered from the knowledge base or the job data (never a
    #    free model answer), then the form continues where it was. Decided by rules: no extra model call.
    if session["intent"] and not message.startswith("uploads/"):
        ri = rule_intent(message, user_role)
        if ri in ("hr_knowledge", "view_jobs", "personal_data", "compare_jobs") or (ri is None and "?" in message):
            if ri == "view_jobs":
                inner = await job_search.list_jobs(message, user_role)
            else:
                inner = (await job_search.job_detail(message, user_role)) or (await answer_from_kb(message, user_role))
            step_friendly_name = session['step'].replace('ask_', '').replace('_', ' ').title()
            back = (f"\n\n---\n**Now, back to your form.** Please provide your: **{step_friendly_name}**")
            inner["text"] = f"{inner['text']}{back}"
            inner["suggestions"] = ["cancel"]
            return inner

    # --- 1. DETERMINE INTENT ---
    query = message
    follow_up = None
    if not session["intent"]:
        # the user says the previous answer was wrong: re-check it against the sources
        if prev and is_correction(message) and not is_rephrase(message):
            return await _recheck(prev, message, user_role)
        # "no, I meant during probation" / "and when is it paid?" / "only in pune": read with the previous turn
        if prev and (is_rephrase(message) or is_follow_up(message)) and prev.get("type") not in ("form", "greeting"):
            query = f"{prev['user']} — {message}"
            follow_up = (message, prev["user"])
            if prev.get("type") in ("jobs", "job_detail", "compare") and not POLICY_HINT.search(message):
                return await job_search.list_jobs(query, user_role)

        cmp = await job_search.compare_jobs(query)
        if cmp:
            return cmp
        detail = await job_search.job_detail(query, user_role)
        if detail:
            return detail
        intent = rule_intent(query, user_role)
        if intent is None and role == "HR Admin":
            intent = classify_admin(message)
        intent = intent or "hr_knowledge"     # everything else is answered from the knowledge base or refused

        if not prompts.allowed(intent, user_role):
            return _result(prompts.not_allowed_reply(intent, user_role), "refusal",
                           suggestions=prompts.DEFAULT_SUGGESTIONS[role][:3])

        if intent == "greeting":
            return _result(GREETINGS.get(role, GREETINGS["Candidate"]), "greeting",
                           suggestions=prompts.DEFAULT_SUGGESTIONS[role])

        if intent == "compare_jobs":
            return await job_search.list_jobs(query, user_role)

        if intent == "personal_data":
            general = _general_rule_question(query)
            note = f"I can't see your personal records: your {general[0]} is in the **HR portal**. The policy:"
            res = await answer_from_kb(general[1], user_role)
            if res["type"] == "policy":
                res["text"] = f"{note}\n\n{res['text']}"
                res["intro"] = note
            else:
                res["text"] = ("I can't see personal records like your leave balance or salary: you'll find them in "
                               "the **HR portal**. Raise a ticket there if something looks off.")
            return res

        if intent == "view_jobs":
            return await job_search.list_jobs(query, user_role)

        elif intent == "apply_job":
            session["intent"] = "apply_job"
            named = await job_search.find_named_jobs(message)
            if named:
                title = named[0].get("title")
                session["data"]["preferred_role"] = title
                session["step"] = "ask_autofill"
                return _result(f"Great, let's apply for **{title}** ({named[0].get('location', '')}). "
                               "**Would you like to autofill your application using your resume?**\n\n"
                               "Click the 📎 icon below to upload a PDF, or type **'No'** to fill out the form manually.",
                               "form", suggestions=["No", "cancel"])
            session["step"] = "ask_role"
            return _result("Sure. Which role are you interested in?", "form",
                           suggestions=["Data Analyst", "Python Developer", "Customer Support Executive"])

        elif intent == "raise_hiring_request":
            session["intent"] = "raise_hiring_request"
            session["step"] = "ask_dept"
            return _result("I can help with that. Please enter the department name.", "form",
                           suggestions=["Tech", "HR", "BPO", "cancel"])

        elif intent == "check_status":
            session["intent"] = "check_status"
            session["step"] = "ask_email"
            return _result("I can help you check your application status! 📋 Please enter your registered **Email ID**.",
                           "form", suggestions=["cancel"])

        elif intent == "hr_admin_queries":
            if re.search(r"\b(how many|count|number of|stats|summary|pipeline|kitne)\b", message_lower):
                return await _pipeline_counts()
            if "shortlisted" in message_lower:
                cands = await candidates_collection.find({"screening_status": "Shortlisted for next step"}).to_list(10)
                if not cands: return "No shortlisted candidates found."
                return "✅ **Shortlisted Candidates:**\n" + "\n".join([f"• {c.get('full_name', 'Unknown')} - {c.get('preferred_role', 'Unknown')} ({c.get('email', '')})" for c in cands])
            
            elif "rejected" in message_lower or "not suitable" in message_lower:
                cands = await candidates_collection.find({"screening_status": {"$regex": "Not suitable|Missing|Reject", "$options": "i"}}).to_list(10)
                if not cands: return "No rejected candidates found."
                return "❌ **Rejected Candidates:**\n" + "\n".join([f"• {c.get('full_name', 'Unknown')} - {c.get('preferred_role', 'Unknown')} ({c.get('email', '')}) | Status: *{c.get('screening_status', 'Unknown')}*" for c in cands])
            
            elif "awaiting" in message_lower or "interview" in message_lower:
                cands = await candidates_collection.find({"screening_status": {"$regex": "interview|Awaiting", "$options": "i"}}).to_list(10)
                if not cands: return "No candidates currently awaiting an interview."
                return "⏳ **Awaiting Interview:**\n" + "\n".join([f"• {c.get('full_name', 'Unknown')} - {c.get('preferred_role', 'Unknown')} ({c.get('email', '')})" for c in cands])
            
            elif "candidate" in message_lower and "pending" in message_lower:
                cands = await candidates_collection.find({"screening_status": {"$regex": "Pending", "$options": "i"}}).to_list(10)
                if not cands: return "No candidates currently have a pending review status."
                return "👀 **Candidates Pending HR Review:**\n" + "\n".join([f"• {c.get('full_name', 'Unknown')} - {c.get('preferred_role', 'Unknown')} ({c.get('email', '')})" for c in cands])
            
            elif "pending" in message_lower or "hiring request" in message_lower:
                reqs = await hiring_requests_collection.find({}).sort("_id", -1).to_list(10)
                jobs = await job_openings_collection.find({}).sort("_id", -1).to_list(10)
                res = ""
                if reqs:
                    res += "📝 **Pending Hiring Requests (From Managers):**\n" + "\n".join([f"• **{r.get('role_required', 'Unknown')}** ({r.get('department', 'Unknown')}) - {r.get('positions', 1)} pos." for r in reqs]) + "\n\n"
                else: res += "📝 **No pending hiring requests from managers.**\n\n"
                if jobs:
                    res += "🗂️ **Unfilled Job Openings (Newest First):**\n" + "\n".join([f"• **{j.get('title', 'Unknown')}** ({j.get('department', 'Unknown')}) - {j.get('location', 'Unknown')}" for j in jobs])
                else: res += "🗂️ **No unfilled job openings found.**"
                return res
                
            elif "all" in message_lower or "every" in message_lower or "list" in message_lower:
                cands = await candidates_collection.find({}).sort("_id", -1).to_list(50)
                if not cands: return "No candidates found in the database."
                return "📋 **Master Candidate Database (Newest First):**\n" + "\n".join([f"• {c.get('full_name', 'Unknown')} - {c.get('preferred_role', 'Unknown')} ({c.get('email', '')}) | Status: *{c.get('screening_status', 'Pending')}*" for c in cands])
                
            else:
                return "Please specify what you'd like to see: All Candidates, Shortlisted, Rejected, Awaiting Interview, Pending Candidates, or Pending Hiring Requests."

        elif intent == "hr_find_candidate":
            session["intent"] = "hr_find_candidate"
            session["step"] = "ask_identifier"
            return "Please provide the candidate's **Email ID** or **Phone Number**."

        elif intent == "hr_update_status":
            session["intent"] = "hr_update_status"
            session["step"] = "ask_identifier"
            return "I can help update a candidate's status. Please provide the candidate's **Email ID** or **Phone Number**."
            
        elif intent == "hr_generate_jd":
            session["intent"] = "hr_generate_jd"
            session["step"] = "ask_role"
            return "I can help you generate a Job Description. What is the **Job Title**?"

        elif intent == "hr_manage_jobs":
            session["intent"] = "hr_manage_jobs"
            step = session["step"]
            if not step:
                session["step"] = "ask_manage_action"
                return "I can help you manage the database. Do you want to **Approve a Hiring Request** or **Delete a Job Opening**?"
            elif step == "ask_manage_action":
                if "approve" in message_lower or "request" in message_lower:
                    session["data"]["manage_action"] = "approve"
                    session["step"] = "ask_manage_role"
                    return "Which **Role Name** from the pending hiring requests do you want to approve?"
                elif "delete" in message_lower or "remove" in message_lower or "job" in message_lower:
                    session["data"]["manage_action"] = "delete"
                    session["step"] = "ask_manage_role"
                    return "Which **Job Title** do you want to remove from the active job openings?"
                else:
                    return "Please specify if you want to 'Approve' a request or 'Delete' a job."
            elif step == "ask_manage_role":
                action = session["data"]["manage_action"]
                target_role = message
                
                if action == "approve":
                    req = await hiring_requests_collection.find_one({"role_required": {"$regex": target_role, "$options": "i"}})
                    if req:
                        new_job = {
                            "title": req.get("role_required"),
                            "department": req.get("department"),
                            "location": req.get("job_location", "Any"),
                            "experience_required": req.get("required_experience", "0"),
                            "skills_required": [s.strip() for s in str(req.get("required_skills", "")).split(",")],
                            "budget": req.get("budget", "Not specified"),
                            "description": req.get("reason", "Approved by HR.")
                        }
                        await job_openings_collection.insert_one(new_job)
                        await hiring_requests_collection.delete_one({"_id": req["_id"]})
                        await _reindex_jobs_safely()
                        sessions[session_id] = {"intent": None, "step": None, "data": {}}
                        return f"✅ Success! The hiring request for **{req.get('role_required')}** has been approved and turned into an active Job Opening."
                    else:
                        sessions[session_id] = {"intent": None, "step": None, "data": {}}
                        return f"❌ I couldn't find a pending hiring request for '{target_role}'."
                        
                elif action == "delete":
                    job = await job_openings_collection.find_one({"title": {"$regex": target_role, "$options": "i"}})
                    if job:
                        await job_openings_collection.delete_one({"_id": job["_id"]})
                        await _reindex_jobs_safely()
                        sessions[session_id] = {"intent": None, "step": None, "data": {}}
                        return f"🗑️ Success! The job opening for **{job.get('title')}** has been removed from the database."
                    else:
                        sessions[session_id] = {"intent": None, "step": None, "data": {}}
                        return f"❌ I couldn't find an active job opening for '{target_role}'."

        elif intent == "hr_knowledge":
            return await answer_from_kb(query, user_role, follow_up=follow_up)

        # --- FALLBACK: answered only from the knowledge base (handbook + job openings), never from the model's
        #     general knowledge, so it cannot invent policies, numbers or roles ---
        else:
            return await answer_from_kb(query, user_role, follow_up=follow_up)

    # --- 2. CANDIDATE FLOW ---
    if session["intent"] == "apply_job":
        step = session["step"]
        if step == "ask_role":
            session["data"]["preferred_role"] = message
            session["step"] = "ask_autofill"
            return "Great choice! 📄 **Would you like to autofill your application using your resume?**\n\nClick the 📎 icon below to upload a PDF, or type **'No'** to fill out the form manually."
            
        elif step == "ask_autofill":
            if "uploads/" in message and message.endswith(".pdf"):
                try:
                    text = await _resume_text(message)
                    if not text.strip():
                        raise ValueError("empty resume text")
                    
                    sys_prompt = """You are an expert HR resume parser. Extract the following details from the text and return ONLY a valid JSON object.
                    Required keys: 'full_name', 'email', 'phone', 'skills', 'experiences' (list of objects with 'start' and 'end' keys strictly in 'YYYY-MM' format. If currently working there, set 'end' to 'Present')."""
                    
                    comp = groq_client.chat.completions.create(
                        model=config.GROQ_MODEL,
                        messages=[
                            {"role": "system", "content": sys_prompt}, 
                            {"role": "user", "content": f"Resume Text:\n{text[:3500]}"}
                        ],
                        response_format={"type": "json_object"}
                    )
                    parsed_data = json.loads(comp.choices[0].message.content)
                    
                    total_months = 0
                    current_date = datetime.datetime.now()
                    
                    for exp in parsed_data.get("experiences", []):
                        try:
                            start_str = exp.get("start", "")
                            end_str = exp.get("end", "")
                            start_date = datetime.datetime.strptime(start_str, "%Y-%m")
                            if end_str.lower() == "present":
                                end_date = current_date
                            else:
                                end_date = datetime.datetime.strptime(end_str, "%Y-%m")
                                
                            months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
                            if months > 0: total_months += months
                        except Exception as e:
                            continue
                            
                    calculated_years = round(total_months / 12.0, 1)
                    
                    session["data"].update(parsed_data)
                    session["data"]["total_experience"] = str(calculated_years)
                    session["data"]["resume_link"] = message
                    session["step"] = "ask_parsed_location"
                    
                    return f"✅ **Resume Parsed Successfully!**\n\n👤 Name: {session['data'].get('full_name')}\n📧 Email: {session['data'].get('email')}\n🎓 Exp: **{calculated_years} yrs**\n🛠️ Skills: {session['data'].get('skills')}\n\n📍 To ensure we match you with the right office, what is your **Current or Preferred Location**?"
                    
                except Exception as e:
                    session["step"] = "ask_name"
                    return "Sorry, I couldn't read that PDF. Let's do it manually. Please share your **Full Name**."
            else:
                session["step"] = "ask_name"
                return "No problem! Let's do it manually. Please share your **Full Name**."

        elif step == "ask_parsed_location":
            session["data"]["location"] = message
            session["step"] = "ask_current_ctc"
            return "Got it! Just two more questions. What is your **Current CTC**? (Enter a number)"

        elif step == "ask_name":
            session["data"]["full_name"] = message
            session["step"] = "ask_email"
            return f"Thanks {message}. Please share your email ID."
        elif step == "ask_email":
            if not is_valid_email(message): return "Please provide a valid email format."
            session["data"]["email"] = message
            session["step"] = "ask_phone"
            return "Please share your phone number."
        elif step == "ask_phone":
            if not is_valid_phone(message): return "Please provide a valid phone number (at least 10 digits)."
            session["data"]["phone"] = message
            session["step"] = "ask_location"
            return "What is your current location?"
        elif step == "ask_location":
            session["data"]["location"] = message
            session["step"] = "ask_qualification"
            return "What is your highest qualification?"
        elif step == "ask_qualification":
            session["data"]["highest_qualification"] = message
            session["step"] = "ask_total_exp"
            return "How many years of total experience do you have? (Enter a number)"
        elif step == "ask_total_exp":
            if not is_numeric(message): return "Experience must be a numeric value."
            session["data"]["total_experience"] = message
            session["step"] = "ask_relevant_exp"
            return "How many years of relevant experience do you have for this role?"
        elif step == "ask_relevant_exp":
            if not is_numeric(message): return "Must be a numeric value."
            session["data"]["relevant_experience"] = message
            session["step"] = "ask_skills"
            return "Please list your key skills (separated by commas)."
        elif step == "ask_skills":
            session["data"]["skills"] = message
            session["step"] = "ask_current_ctc"
            return "What is your current CTC? (Enter a number)"
        elif step == "ask_current_ctc":
            if not is_numeric(message.replace(',','')): return "CTC must be numeric."
            session["data"]["current_ctc"] = message
            session["step"] = "ask_expected_ctc"
            return "What is your expected CTC?"
        elif step == "ask_expected_ctc":
            if not is_numeric(message.replace(',','')): return "CTC must be numeric."
            session["data"]["expected_ctc"] = message
            session["step"] = "ask_notice_period"
            return "What is your notice period (in days)?"
        elif step == "ask_notice_period":
            session["data"]["notice_period"] = message
            
            if "resume_link" in session["data"]:
                summary, status = await evaluate_candidate(session["data"])
                session["data"]["screening_status"] = status
                await candidates_collection.insert_one(session["data"])
                
                await (send_hr_email_notification(session["data"].get("full_name"), session["data"].get("preferred_role"), status))
                sessions[session_id] = {"intent": None, "step": None, "data": {}}
                
                return f"Thank you. Based on your profile, you are **{status}**. Your application has been successfully saved.\n\n{summary}"
            else:
                session["step"] = "ask_resume"
                return "Finally, please provide a link to your resume, or click the attachment (📎) icon below to upload a PDF."
                
        elif step == "ask_resume":
            session["data"]["resume_link"] = message
            summary, status = await evaluate_candidate(session["data"])
            session["data"]["screening_status"] = status
            
            await candidates_collection.insert_one(session["data"])
            await (send_hr_email_notification(session["data"].get("full_name"), session["data"].get("preferred_role"), status))
            sessions[session_id] = {"intent": None, "step": None, "data": {}}
            
            return f"Thank you. Based on your profile, you are **{status}**. Your application has been successfully saved.\n\n{summary}"

    # --- 3. HIRING MANAGER FLOW ---
    if session["intent"] == "raise_hiring_request":
        step = session["step"]
        if step == "ask_dept":
            session["data"]["department"] = message
            session["step"] = "ask_role"
            return "What role do you want to hire for?"
        elif step == "ask_role":
            session["data"]["role_required"] = message
            session["step"] = "ask_positions"
            return "How many positions are required?"
        elif step == "ask_positions":
            if not is_numeric(message): return "Please enter a valid number."
            session["data"]["positions"] = int(message)
            session["step"] = "ask_exp"
            return "What is the required experience range? (e.g., '0-2', '3-5', or 'fresher')"
            
        elif step == "ask_exp":
            try:
                comp = groq_client.chat.completions.create(
                    model=config.GROQ_MODEL,
                    messages=[
                        {
                            "role": "system", 
                            "content": "You extract experience ranges. Output ONLY the range in 'X-Y yrs' format. Convert 'fresher' to '0-1 yrs'. Convert '4+' to '4-99 yrs'. Do not output any other text or repeat the prompt."
                        },
                        {"role": "user", "content": message}
                    ],
                    temperature=0, max_tokens=SHORT_ANSWER_TOKENS
                )
                formatted_exp = comp.choices[0].message.content.strip().replace("\"", "")
                
                if len(formatted_exp) > 15:
                    formatted_exp = f"{message.strip()} yrs"
            except Exception:
                formatted_exp = f"{message.strip()} yrs"
            
            session["data"]["required_experience"] = formatted_exp
            session["step"] = "ask_skills"
            return f"Got it, experience requirement set to **{formatted_exp}**. What skills are required? (Comma separated)"
            
        elif step == "ask_skills":
            session["data"]["required_skills"] = message
            session["step"] = "ask_location"
            return "What is the job location?"
            
        elif step == "ask_location":
            session["data"]["job_location"] = message
            session["step"] = "ask_budget"
            return "What is the budget range for this role? (Please specify as per annum, e.g., '10-15 LPA' or '12 Lakhs per annum')"
        elif step == "ask_budget":
            session["data"]["budget"] = message
            session["step"] = "ask_manager"
            return "Who is the reporting manager?"
        elif step == "ask_manager":
            session["data"]["reporting_manager"] = message
            session["step"] = "ask_urgency"
            return "What is the urgency level? (e.g., High, Medium, Low)"
        elif step == "ask_urgency":
            session["data"]["urgency"] = message
            session["step"] = "ask_reason"
            return "What is the reason for hiring?"
        elif step == "ask_reason":
            session["data"]["reason"] = message
            session["step"] = "ask_replacement"
            return "Is this a replacement or a new position?"
        elif step == "ask_replacement":
            session["data"]["position_type"] = message
            
            await hiring_requests_collection.insert_one(session["data"])
            
            summary = f"""
            **Hiring Request Summary**
            • Department: {session['data']['department']}
            • Role Required: {session['data']['role_required']}
            • Number of Openings: {session['data']['positions']}
            • Required Skills: {session['data']['required_skills']}
            • Budget: {session['data']['budget']}
            • Urgency: {session['data']['urgency']}
            • Submitted By: {session['data']['reporting_manager']}
            """
            sessions[session_id] = {"intent": None, "step": None, "data": {}}
            return f"Your hiring request has been created successfully.\n\n{summary}"

    # --- 4. CHECK STATUS FLOW ---
    if session["intent"] == "check_status":
        step = session["step"]
        if step == "ask_email":
            if not is_valid_email(message): return "Please provide a valid email format."
            session["data"]["email"] = message
            session["step"] = "ask_phone"
            return "Got it. Now, please enter your registered **Phone Number** to verify your identity."
            
        elif step == "ask_phone":
            if not is_valid_phone(message): return "Please provide a valid phone number."
            session["data"]["phone"] = message
            
            profile_query = {"email": session["data"]["email"], "phone": session["data"]["phone"]}
            applications = await candidates_collection.find(profile_query).to_list(length=10)
            
            past_sessions = await chat_history_collection.find({
                "message": session["data"]["email"],
                "user_role": "Candidate"
            }).to_list(length=50)
            
            past_session_ids = list(set([s["session_id"] for s in past_sessions]))
            past_session_ids.append(session_id)
            
            recent_chats = await chat_history_collection.find(
                {"session_id": {"$in": past_session_ids}}
            ).sort("timestamp", -1).to_list(length=8)
            recent_chats.reverse()
            
            sessions[session_id] = {"intent": None, "step": None, "data": {}}
            
            if applications:
                name = applications[0].get("full_name", "Candidate")
                res = f"**Identity Verified! Welcome back, {name}** 🎉\n\n"
                
                res += "📋 **YOUR APPLICATIONS:**\n"
                for idx, app in enumerate(applications, 1):
                    role = app.get("preferred_role", "Unknown Role")
                    status = app.get("screening_status", "Pending HR Review")
                    res += f"**{idx}. 💼 Role:** {role} | 📊 **Status:** {status}\n"
                
                res += "\n━━━━━━━━━━━━━━━━━━━━\n"
                res += "📜 **YOUR RECENT CHAT HISTORY:**\n"
                if recent_chats:
                    for chat in recent_chats:
                        role_icon = "👤" if chat['role'] == 'user' else "🤖"
                        msg_text = chat['message'].replace('\n', ' ') 
                        short_msg = msg_text[:65] + "..." if len(msg_text) > 65 else msg_text
                        res += f"{role_icon} *{short_msg}*\n"
                else:
                    res += "*No previous chat history found.*\n"
                    
                res += "\nOur team will contact you soon regarding the next steps!"
                return res
            else:
                return "❌ **Verification Failed.** I couldn't find any applications matching that Email and Phone Number."

    # --- 5. HR FIND CANDIDATE / SUMMARY FLOW ---
    if session["intent"] == "hr_find_candidate":
        step = session["step"]
        if step == "ask_identifier":
            session["data"]["identifier"] = message
            cand = await candidates_collection.find_one({
                "$or": [{"email": message}, {"phone": message}]
            })
            sessions[session_id] = {"intent": None, "step": None, "data": {}}
            if cand:
                return f"**Candidate Details & Summary** 📄\n\n👤 **Name:** {cand.get('full_name')}\n📧 **Email:** {cand.get('email')}\n📞 **Phone:** {cand.get('phone')}\n📍 **Location:** {cand.get('location')}\n💼 **Role Applied:** {cand.get('preferred_role')}\n🎓 **Exp:** {cand.get('total_experience')} yrs\n🛠️ **Skills:** {cand.get('skills')}\n💰 **Expected CTC:** {cand.get('expected_ctc')}\n📊 **Screening Status:** **{cand.get('screening_status')}**\n🔗 **Resume:** {cand.get('resume_link')}"
            else:
                return "❌ No candidate found with that email or phone number."

    # --- 6. HR GENERATE JOB DESCRIPTION FLOW ---
    if session["intent"] == "hr_generate_jd":
        step = session["step"]
        if step == "ask_role":
            session["data"]["jd_role"] = message
            session["step"] = "ask_skills"
            return "What are the key skills required for this role?"
        elif step == "ask_skills":
            session["data"]["jd_skills"] = message
            session["step"] = "ask_exp"
            return "What is the required experience level (in years)?"
        elif step == "ask_exp":
            prompt = f"Generate a highly professional, engaging, and concise Job Description for a '{session['data']['jd_role']}'. Required Skills: {session['data']['jd_skills']}. Required Experience: {message} years. Include brief sections for Responsibilities and Requirements. Do not make it overly long."
            comp = groq_client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[{"role": "system", "content": "You are an expert HR copywriter."}, {"role": "user", "content": prompt}]
            )
            sessions[session_id] = {"intent": None, "step": None, "data": {}}
            return f"**Here is your AI-Generated Job Description:** ✨\n\n{comp.choices[0].message.content}"

    # --- 7. HR UPDATE CANDIDATE STATUS FLOW ---
    if session["intent"] == "hr_update_status":
        step = session["step"]
        if step == "ask_identifier":
            cand = await candidates_collection.find_one({
                "$or": [{"email": message}, {"phone": message}]
            })
            if cand:
                session["data"]["target_email"] = cand["email"]
                session["step"] = "ask_new_status"
                return f"✅ Candidate found: **{cand['full_name']}**\n📊 Current Status: *{cand.get('screening_status', 'Pending')}*\n\nWhat should their **New Status** be? (Choose one: **'Interview Done'**, **'Hired'**, or **'Rejected'**)"
            else:
                sessions[session_id] = {"intent": None, "step": None, "data": {}}
                return "❌ No candidate found with that email or phone number. Please try again."
                
        elif step == "ask_new_status":
            new_status = message
            target_email = session["data"]["target_email"]
            await candidates_collection.update_many(
                {"email": target_email},
                {"$set": {"screening_status": new_status}}
            )
            sessions[session_id] = {"intent": None, "step": None, "data": {}}
            return f"🔄 Success! The status for **{target_email}** has been updated to **{new_status}**."

    # --- 8. HR MANAGE JOBS LOGIC FLOW ---
    if session["intent"] == "hr_manage_jobs":
        step = session["step"]
        if not step:
            session["step"] = "ask_manage_action"
            return "I can help you manage the database. Do you want to **Approve a Hiring Request** or **Delete a Job Opening**?"
        elif step == "ask_manage_action":
            if "approve" in message_lower or "request" in message_lower:
                session["data"]["manage_action"] = "approve"
                session["step"] = "ask_manage_role"
                return "Which **Role Name** from the pending hiring requests do you want to approve?"
            elif "delete" in message_lower or "remove" in message_lower or "job" in message_lower:
                session["data"]["manage_action"] = "delete"
                session["step"] = "ask_manage_role"
                return "Which **Job Title** do you want to remove from the active job openings?"
            else:
                return "Please specify if you want to 'Approve' a request or 'Delete' a job."
        elif step == "ask_manage_role":
            action = session["data"]["manage_action"]
            target_role = message
            
            if action == "approve":
                req = await hiring_requests_collection.find_one({"role_required": {"$regex": target_role, "$options": "i"}})
                if req:
                    new_job = {
                        "title": req.get("role_required"),
                        "department": req.get("department"),
                        "location": req.get("job_location", "Any"),
                        "experience_required": req.get("required_experience", "0"),
                        "skills_required": [s.strip() for s in str(req.get("required_skills", "")).split(",")],
                        "budget": req.get("budget", "Not specified"),
                        "description": req.get("reason", "Approved by HR.")
                    }
                    await job_openings_collection.insert_one(new_job)
                    await hiring_requests_collection.delete_one({"_id": req["_id"]})
                    await _reindex_jobs_safely()
                    sessions[session_id] = {"intent": None, "step": None, "data": {}}
                    return f"✅ Success! The hiring request for **{req.get('role_required')}** has been approved and turned into an active Job Opening."
                else:
                    sessions[session_id] = {"intent": None, "step": None, "data": {}}
                    return f"❌ I couldn't find a pending hiring request for '{target_role}'."
                    
            elif action == "delete":
                job = await job_openings_collection.find_one({"title": {"$regex": target_role, "$options": "i"}})
                if job:
                    await job_openings_collection.delete_one({"_id": job["_id"]})
                    await _reindex_jobs_safely()
                    sessions[session_id] = {"intent": None, "step": None, "data": {}}
                    return f"🗑️ Success! The job opening for **{job.get('title')}** has been removed from the database."
                else:
                    sessions[session_id] = {"intent": None, "step": None, "data": {}}
                    return f"❌ I couldn't find an active job opening for '{target_role}'."

    return "I didn't quite understand. You can ask to view jobs, apply for a job, raise a hiring request, or check shortlisted candidates."
