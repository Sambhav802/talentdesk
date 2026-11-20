"""Rule-based intent routing that runs before the LLM classifier.

Clear cases are decided here, so they never depend on a model's guess: an HR-policy question is never routed into
the job application form, and a job search never reaches a free-text model answer. Anything unclear returns None
and goes to the LLM classifier as before."""
import re

POLICY = re.compile(r"\b(leave|leaves|holiday|holidays|vacation|days? off|time off|sick|maternity|paternity|adoption|"
                    r"bereavement|notice period|notice|probation|referral|refer|bonus|salary|salaries|payroll|payslips?|"
                    r"paid|payday|pay day|tax|form 16|insurance|mediclaim|medical|health|benefits?|allowance|"
                    r"reimburse\w*|expenses?|travel|hotel|work from home|wfh|hybrid|policy|policies|handbook|"
                    r"internal (job|opening|posting|transfer)\w*|transfer|working hours|office hours|timings?|"
                    r"core hours|shifts?|night shift|attendance|late|appraisals?|increments?|hike|promotions?|"
                    r"performance review|learning|training|certifications?|courses?|dress code|dress|laptop|"
                    r"resign\w*|resignation|exit|full and final|relieving|harassment|complaint|grievance|"
                    r"code of conduct|ticket|contact hr|documents?|joining|onboarding|induction|interview process|"
                    r"hiring process|interview|offer letter|offer|background verification|meal|cab)\b", re.I)
QUESTION = re.compile(r"^\s*(what|what's|whats|how|when|where|who|whom|which|why|can|could|do|does|did|is|are|am|"
                      r"will|would|should|shall|may|tell me|explain|i want to know|any idea|is there|are there)\b|\?\s*$",
                      re.I)
JOB_WORDS = re.compile(r"\b(jobs?|openings?|vacanc\w*|roles?|positions?|internships?|requisitions?|hiring for|"
                       r"opportunit\w*|careers?)\b", re.I)
JOB_CUE = re.compile(r"\b(show|list|view|see|any|open|available|which|what|find|search|looking for|have|are there|"
                     r"do you|in [a-z]+|remote|fresher|freshers|for me|current)\b", re.I)
APPLY = re.compile(r"(\b(i want to|i'?d like to|i would like to|want to|wanna|help me|let me|how (do|can) i|"
                   r"start (my|an|the)?\s*)\s*apply\b|^\s*apply\b|\bsubmit (my )?(application|resume|cv)\b)", re.I)
STATUS = re.compile(r"\b(status of my|my application status|application status|check (my )?status|"
                    r"track (my )?application|where is my application|status)\b", re.I)
HIRING_REQUEST = re.compile(r"\b(raise|create|open|submit|new)\b.*\bhiring request\b|\bneed to hire\b|"
                            r"\bhiring request\b(?!s)", re.I)
WRITE_JD = re.compile(r"\b(generate|create|write|draft|prepare)\b.*\b(jd|job description)\b|\bjob description\b",
                      re.I)
HR_ACTION = re.compile(r"\b(delete|remove|close|approve|reject|shortlist|update|change)\b.*\b(job|opening|request|"
                       r"candidate|status)\b|\b(shortlisted|rejected|pending)\b.*\b(candidates?|requests?)\b", re.I)
GREETING = re.compile(r"^\s*(hi|hii+|hello|hey|hola|namaste|good (morning|afternoon|evening)|thanks|thank you|"
                      r"thank u|ok|okay|cool|great|bye|goodbye)\b[\s!.,]*\w{0,12}[\s!.]*$", re.I)


def rule_intent(message: str, user_role: str) -> str | None:
    m = message.strip()
    if GREETING.match(m):
        return "greeting"
    if WRITE_JD.search(m) or HR_ACTION.search(m):
        return None                          # HR admin actions: the LLM classifier knows those intents
    policy_q = bool(POLICY.search(m)) and bool(QUESTION.search(m))
    # "can I apply for an internal job posting?" is a policy question, not the application form
    if re.search(r"\binternal\b", m, re.I) and policy_q:
        return "hr_knowledge"
    if user_role == "Candidate" and APPLY.search(m) and not policy_q:
        return "apply_job"
    if user_role == "Candidate" and STATUS.search(m) and re.search(r"\b(my|application|applied|status)\b", m, re.I) \
            and not POLICY.search(m):
        return "check_status"
    if user_role in ("Hiring Manager", "HR Admin") and HIRING_REQUEST.search(m) and not re.search(
            r"\b(pending|show|list|approve)\b", m, re.I):
        return "raise_hiring_request"
    if JOB_WORDS.search(m) and JOB_CUE.search(m) and not policy_q:
        return "view_jobs"
    if policy_q:
        return "hr_knowledge"
    return None
