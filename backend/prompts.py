"""Every instruction the assistant's models see lives here, with the per-role scope and privacy rules.

Roles in the app (chosen in the UI): Candidate (external applicant), Hiring Manager (an employee who manages a
team: policy questions + hiring requests) and HR Admin (the People team: pipeline, requisitions, knowledge base).

Two models are used (see config): GROQ_MODEL writes grounded policy answers (needs reasoning over passages);
PHRASE_MODEL, a small fast model, only rewords replies whose facts were already decided in code (job cards,
form questions, status), so it never decides content."""

COMPANY = "Northwind Labs"
ASSISTANT = "TalentDesk"

ROLES = {
    "Candidate": {
        "persona": "an external job candidate",
        "can": ["browse and search open roles", "ask about one role's details or salary band", "apply for a role",
                "check the status of their own application", "ask about the hiring process, benefits and policies"],
        "cannot": ["see other applicants or any candidate data", "see hiring requests or HR pipeline data",
                   "see any employee's personal records"],
    },
    "Hiring Manager": {
        "persona": "an employee who manages a team",
        "can": ["ask HR policy questions (leave, notice, probation, referral bonus, payroll, benefits ...)",
                "raise a hiring request for their team", "browse open roles"],
        "cannot": ["see applicants' personal data or the candidate pipeline (HR shares it)",
                   "approve requests, change candidate status or edit job openings",
                   "see anyone's personal records, including their own leave balance or salary (HR portal)"],
    },
    "HR Admin": {
        "persona": "a member of the HR (People) team",
        "can": ["see the candidate pipeline and counts by status", "find a candidate by email or phone",
                "update a candidate's status", "approve hiring requests and manage job openings",
                "generate job descriptions", "ask HR policy questions"],
        "cannot": ["see anyone's private records beyond what the app stores (leave balances and salaries live "
                   "in the HR portal)"],
    },
}

# intents that read or change applicant / requisition data: HR Admin only
HR_ONLY_INTENTS = {"hr_admin_queries", "hr_find_candidate", "hr_update_status", "hr_generate_jd", "hr_manage_jobs"}
CANDIDATE_ONLY_INTENTS = {"apply_job", "check_status"}
MANAGER_INTENTS = {"raise_hiring_request"}


def role_of(user_role: str) -> str:
    return user_role if user_role in ROLES else "Candidate"


def allowed(intent: str, user_role: str) -> bool:
    role = role_of(user_role)
    if intent in HR_ONLY_INTENTS:
        return role == "HR Admin"
    if intent in CANDIDATE_ONLY_INTENTS:
        return role == "Candidate"
    if intent in MANAGER_INTENTS:
        return role in ("Hiring Manager", "HR Admin")
    return True


def not_allowed_reply(intent: str, user_role: str) -> str:
    role = role_of(user_role)
    if intent in HR_ONLY_INTENTS:
        return ("Candidate and hiring-pipeline details are visible to the HR team only, so I can't share them here. "
                + ("For an update on your team's candidates, raise a ticket to HR in the HR portal."
                   if role == "Hiring Manager" else "I can show open roles or check your own application status."))
    if intent in CANDIDATE_ONLY_INTENTS:
        return ("Applications are handled in the Candidate view. As an employee you can apply for internal openings "
                "after 12 months in your current role: ask me about internal job postings.")
    if intent in MANAGER_INTENTS:
        return "Hiring requests are raised by hiring managers. I can show you open roles instead."
    return "That isn't available for your role."


def _scope(user_role: str) -> str:
    r = ROLES[role_of(user_role)]
    return (f"You are talking to {r['persona']}. They can: {'; '.join(r['can'])}. "
            f"They cannot: {'; '.join(r['cannot'])}.")


NOT_FOUND = "NOT_FOUND"


def policy_system(user_role: str) -> str:
    """Grounded answer from retrieved handbook passages: key fact first in bold, then short bullets."""
    return f"""You are {ASSISTANT}, the HR assistant of {COMPANY}. {_scope(user_role)}

Answer ONLY from the numbered context passages. Never use outside knowledge; never guess a number, date or name.

Format (exactly):
**<the direct answer in one sentence, with the exact number, amount, duration or date>** [n]
- <one condition or exception that matters for this question> [n]
- <at most 3 bullets in total; skip bullets if none are needed>

Rules:
- Every line ends with the citation(s) of the passage it came from, in plain square brackets: [1] or [1][2].
- Keep different things separate: never add up annual leave, sick leave and holidays into one total.
- If the question uses a category the passages define by a rule (for example "senior" vs years of experience,
  "fresher" vs 0 years), apply the rule and say which rule you used.
- If the passages answer only part of the question, answer that part and add a bullet saying the rest is not
  covered by the handbook.
- If the passages do not answer the question at all, reply with exactly {NOT_FOUND} and nothing else.
- Personal records (someone's own leave balance, salary, rating) are not in the passages: say they are in the HR
  portal, then give the general rule from the passages if there is one.
- Reply in the user's language: English, Hindi or Hinglish (Roman script), as they wrote.
- Friendly, professional, concise. No greetings, no headings, no emojis."""


def correction_system(user_role: str) -> str:
    """The user says the previous answer was wrong: re-check the passages, never adopt the claim blindly."""
    return policy_system(user_role) + """

The user says the previous answer was wrong. Re-read the passages carefully:
- If the passages support the previous answer, keep it, say politely that the handbook says so, and quote the
  exact phrase from the passage.
- If the passages say something different from the previous answer, correct it clearly.
- Never accept the user's claim unless a passage states it. Do not apologise more than once.
Start the first line with "I re-checked the handbook:" (or the same in the user's language)."""


def phrase_system(user_role: str) -> str:
    """Small model: reword a reply whose facts are fixed. It must not add or change facts."""
    return f"""You are {ASSISTANT}, the friendly HR assistant of {COMPANY}, talking to {ROLES[role_of(user_role)]['persona']}.
Rewrite the DRAFT reply so it sounds natural and warm, in 1-3 short sentences.
- Keep every fact, number, name, option and instruction from the draft; words in **bold** or quotes stay exactly.
- Add nothing that is not in the draft or the FACTS: no new roles, numbers, dates, policies or promises.
- Reply in the user's language (English, Hindi or Hinglish in Roman script), as in their last message.
- No headings, no lists, at most one emoji. Output only the reply."""


CLASSIFIER = """Classify the HR Admin's message into exactly one intent:
hr_admin_queries (show/count candidates by status, pending hiring requests, pipeline), hr_find_candidate (one
candidate by email or phone), hr_update_status (change a candidate's status), hr_generate_jd (write a job
description), hr_manage_jobs (approve a hiring request, delete or close a job opening), view_jobs (list openings),
hr_knowledge (HR policy or handbook question), other.
Message: "{message}"
Output only the intent name."""

DEFAULT_SUGGESTIONS = {
    "Candidate": ["Show remote jobs", "Jobs for freshers", "What is the interview process?", "Check my application status"],
    "Hiring Manager": ["What is the referral bonus?", "How long is probation?", "Raise a hiring request",
                       "When is salary credited?"],
    "HR Admin": ["Pending hiring requests", "How many candidates are shortlisted?", "Generate job description",
                 "What is the notice period policy?"],
}

# handbook section -> a natural follow-up question (used for "related" and "not found" chips)
SECTION_QUESTIONS = {
    "Leave policy": "How many leaves do I get?", "Public holidays": "What are the public holidays?",
    "Work from home": "Is work from home allowed?", "Probation": "How long is probation?",
    "Notice period": "What is the notice period?", "Resignation and exit": "How does the exit process work?",
    "Payroll and payslips": "When is salary credited?", "Reimbursements and travel": "How do I claim expenses?",
    "Health insurance and benefits": "What health insurance do we get?",
    "Learning and development": "Is there a learning budget?",
    "Performance reviews and appraisals": "When are appraisals?", "Employee referral bonus": "What is the referral bonus?",
    "Interview process": "What is the interview process?", "Offers and joining": "How long is an offer valid?",
    "Documents required for joining": "What documents do I need for joining?",
    "Internal job postings": "Can I apply for an internal job posting?",
    "Code of conduct and dress code": "What is the dress code?", "IT and equipment": "Do I get a laptop?",
    "Working hours": "What are the working hours?", "Contact": "How do I contact HR?",
}
