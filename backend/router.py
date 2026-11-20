"""Rule-based intent routing that runs before any model.

Clear cases are decided here, so they never depend on a model's guess: an HR-policy question is never routed into
the job application form, a job search never reaches a free-text answer, a "that's wrong" re-checks the previous
answer, and a short follow-up ("and when is it paid?", "only in pune") is read together with the previous turn.
Anything unclear returns None (HR Admin: small-model classifier; other roles: the knowledge base answers)."""
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
                    r"hiring process|interview|offer letter|offer|background verification|meal|cab|"
                    # Hinglish
                    r"chutti\w*|chhutti\w*|chuttiy\w*|tankha\w*|tankhwah|vetan|bimari|beemar\w*|"
                    r"chhod\w*)\b", re.I)
QUESTION = re.compile(r"^\s*(what|what's|whats|how|when|where|who|whom|which|why|can|could|do|does|did|is|are|am|"
                      r"will|would|should|shall|may|tell me|explain|i want to know|any idea|is there|are there)\b|\?\s*$|"
                      r"\b(kitn[aie]|kya|kab|kaise|kaun|kahan|kyun|batao|bataiye|milti|milta|milte)\b", re.I)
JOB_WORDS = re.compile(r"\b(jobs?|openings?|vacanc\w*|roles?|positions?|internships?|requisitions?|hiring for|"
                       r"opportunit\w*|careers?|naukri\w*)\b", re.I)
JOB_CUE = re.compile(r"\b(show|list|view|see|any|open|available|which|what|find|search|looking for|have|are there|"
                     r"do you|in [a-z]+|remote|fresher|freshers|for me|current|dikhao|batao|koi|hai)\b", re.I)
APPLY = re.compile(r"(\b(i want to|i'?d like to|i would like to|want to|wanna|help me|let me|how (do|can) i|"
                   r"start (my|an|the)?\s*)\s*apply\b|^\s*apply\b|\bsubmit (my )?(application|resume|cv)\b|"
                   r"\bapply karna\b)", re.I)
STATUS = re.compile(r"\b(status of my|my application status|application status|check (my )?status|"
                    r"track (my )?application|where is my application|status)\b", re.I)
HIRING_REQUEST = re.compile(r"\b(raise|create|open|submit|new)\b.*\bhiring request\b|\bneed to hire\b|"
                            r"\bhiring request\b(?!s)", re.I)
WRITE_JD = re.compile(r"\b(generate|create|write|draft|prepare)\b.*\b(jd|job description)\b|"
                      r"^\s*(generate )?job description\b", re.I)
PIPELINE = re.compile(r"\b(candidates?|applicants?|pipeline|shortlisted|rejected|awaiting interview|"
                      r"who (has )?applied|how many (people )?applied)\b", re.I)
EMAIL_OR_PHONE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\b\d{10}\b")
UPDATE_STATUS = re.compile(r"\b(update|change|set|mark|move)\b.*\b(status|shortlist\w*|reject\w*|interview)\b", re.I)
MANAGE_JOBS = re.compile(r"\b(approve|delete|remove|close)\b.*\b(request|job|opening|role|position)\b", re.I)
GREETING = re.compile(r"^\s*(hi|hii+|hello|hey|hola|namaste|good (morning|afternoon|evening)|thanks|thank you|"
                      r"thank u|ok|okay|cool|great|bye|goodbye)\b[\s!.,]*\w{0,12}[\s!.]*$", re.I)
PERSONAL = re.compile(r"\b(how many|kitn[aie])\b.*\b(leaves?|chutti\w*|days?)\b.*\b(left|remaining|baki|bachi|"
                      r"balance|have)\b|\bmy (leave |sick leave )?balance\b|\b(my|mera|meri) (salary|ctc|payslip|"
                      r"rating|increment|appraisal)\b|\bleaves? (left|remaining|baki)\b", re.I)
CORRECTION = re.compile(r"\b(that'?s (wrong|not right|incorrect|not correct)|you'?re wrong|wrong answer|incorrect|"
                        r"not (right|correct|true)|that'?s not it|galat|galt|sahi nahi|wrong)\b", re.I)
REPHRASE = re.compile(r"^\s*(no[,.!]?\s*)?(i meant|i mean|what i meant|i was asking|i'?m asking|mera matlab|"
                      r"matlab)\b", re.I)
FOLLOW_UP = re.compile(r"^\s*(and|also|aur|what about|how about|only|just|sirf|but|then|toh|in that case)\b|"
                       r"\b(it|that|this|those|them|uska|iska|wo|woh)\b.*\?|^\s*(when|how|kab|kaise)\b.{0,25}\?\s*$",
                       re.I)
COMPARE = re.compile(r"\b(compare|comparison|vs\.?|versus|difference between)\b", re.I)


def is_correction(message: str) -> bool:
    return bool(CORRECTION.search(message)) and len(message.split()) <= 14


def is_rephrase(message: str) -> bool:
    return bool(REPHRASE.search(message))


def is_follow_up(message: str) -> bool:
    """Short messages that only make sense with the previous turn."""
    m = message.strip()
    if len(m.split()) > 9 or GREETING.match(m):
        return False
    return bool(FOLLOW_UP.search(m))


def rule_intent(message: str, user_role: str) -> str | None:
    m = message.strip()
    if GREETING.match(m):
        return "greeting"
    if COMPARE.search(m):
        return "compare_jobs"
    if WRITE_JD.search(m):
        return "hr_generate_jd"
    if PERSONAL.search(m):
        return "personal_data"
    policy_q = bool(POLICY.search(m)) and bool(QUESTION.search(m))
    # "can I apply for an internal job posting?" is a policy question, not the application form
    if re.search(r"\binternal\b", m, re.I) and policy_q:
        return "hr_knowledge"
    if MANAGE_JOBS.search(m):
        return "hr_manage_jobs"
    if UPDATE_STATUS.search(m) and re.search(r"\b(candidate|applicant|status)\b", m, re.I) \
            and not re.search(r"\bmy\b", m, re.I):
        return "hr_update_status"
    if EMAIL_OR_PHONE.search(m) and re.search(r"\b(candidate|applicant|find|details?|profile|summary)\b", m, re.I):
        return "hr_find_candidate"
    if re.search(r"\bhiring requests\b", m, re.I):
        return "hr_admin_queries"
    if APPLY.search(m) and not policy_q:
        return "apply_job"
    if STATUS.search(m) and re.search(r"\b(my|application|applied)\b", m, re.I) and not POLICY.search(m):
        return "check_status"
    if PIPELINE.search(m) and not policy_q:
        return "hr_admin_queries"            # the role guard decides who may see it
    if HIRING_REQUEST.search(m):
        return "raise_hiring_request"
    if JOB_WORDS.search(m) and JOB_CUE.search(m) and not policy_q:
        return "view_jobs"
    if policy_q:
        return "hr_knowledge"
    return None
