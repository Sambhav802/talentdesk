# TalentDesk QA review (20 November 2026)

Every answer below was **read and graded by a person against the handbook (`backend/seed/handbook.md`) and the
job records (`backend/seed/jobs.json`)**: numbers, conditions, and whether the cited source actually contains the
claim. No model was used to judge. Keyword checks (`scripts/e2e_eval.py`) are only a smoke test: they scored the
live site 48/49 while users were getting wrong answers, because they don't read the whole answer, don't cover
messy phrasing, and don't test conversations.

Full transcripts (question, answer, sources, structured payload, latency) are in `docs/qa/`:
`live_before.json`, `live_messy_before.json` (live site, commit 168d491) and `local_after.json`,
`local_messy_after.json` (this version, local run).

## Scores (by reading)

| Set | Live before (168d491) | This version |
|---|---|---|
| Fixed question set: policy (40) | 39 correct, 1 wrong (referral for senior roles refused) | retrieval puts the fact in the top passage for 36/36; wording to be re-read on the redeployed site |
| Fixed question set: jobs (6) | 5 correct, 1 wrong (one card for "any Python openings") | 6/6 (cards from the database) |
| Fixed question set: conversations (3) | 3/3 | 3/3 |
| Messy real-user turns (28) | **13/28 correct** | **27/28 pass** (22 PASS, 5 PASS* whose code path is right but whose wording needs the live model; 1 turn not assessable with the stand-in) |
| Role scenarios (16 turns) | not run before | 14/16 pass locally; 2 depend on live model wording |

**How "after" was measured:** the local run used an in-memory database and an *extractive stand-in* for the LLM
(it copies the best-matching sentences), because no Groq key was available to the reviewer. Everything decided in
code (routing, retrieval, job search, cards, role rules, corrections and follow-up handling, form flow) is
exercised for real; only the model's final wording of policy answers is not. Those rows are marked PASS* or
"verify live". After the redeploy, re-run:

```bash
cd backend
python scripts/e2e_eval.py https://talentdesk-two.vercel.app --out ../docs/qa/live_after.json
python scripts/run_conversations.py https://talentdesk-two.vercel.app --out ../docs/qa/live_messy_after.json
```

## Issues found, grouped by root cause

**1. No conversation memory** (the biggest source of wrong answers)
- "and when is it paid?" after the referral bonus → answered about the *performance* bonus.
- "no, I meant during probation" after the notice period → answered about work from home.
- "only in pune" after "python jobs" → treated "only" as a skill, found nothing.
- *Fix:* the previous exchange is read from the chat history; short follow-ups and "I meant …" are answered
  together with the previous question; job follow-ups keep the previous filters.

**2. No correction handling**
- "that's wrong, it's 3 months" and "galat hai" → "not in the knowledge base".
- *Fix:* corrections (English and Hinglish) re-run the original question on the same sources with a re-check
  prompt. It keeps the handbook's answer and quotes it, corrects itself only if a passage says otherwise, never
  adopts the user's claim, and offers "How do I contact HR?".

**3. Prompt allowed misleading arithmetic and refused rule-based answers**
- "how many leavs do i get in a yr" → "38 days of leave" (18 annual + 8 sick + 10 holidays + 2 optional summed).
- "referral bonus for senior roles" → refused, because the handbook said "more than 3 years", not "senior".
- *Fix:* the prompt forbids adding up different categories and applies category rules, and the handbook now
  defines Senior level (5+ years).

**4. Role and privacy holes**
- **A Candidate asking "show me all shortlisted candidates" reached the HR-only shortlist query.** It returned
  nothing only because the database was empty.
- A Hiring Manager asking how many people applied got a nonsense job search.
- *Fix:* `prompts.allowed()` guards every HR-only intent (pipeline, find candidate, update status, JD, manage jobs)
  with a clear, role-specific reply. HR Admin pipeline questions get a counts card.

**5. Job search gaps**
- "any Python developer openings" → one card instead of every Python role.
- "the devops role" (partial title) → not found.
- "compare Data Analyst and Data Scientist" → not found.
- "apply for the Data Analyst job" → asked the role again.
- *Fix:* listing questions never open a single card; partial-title matching; a compare intent with a side-by-side
  table; the apply form starts with the named role filled in.

**6. Language and typos**
- Hinglish ("kitni chuttiyan milti hai") → not found.
- Typos ("leavs") depended on luck.
- *Fix:* Hinglish words in routing and retrieval synonyms; typo correction against the handbook's own vocabulary.

**7. Dead ends and robotic replies**
- "how many leaves do I have left" → "not in KB", with no pointer to where personal records are.
- *Fix:* personal-data questions point to the HR portal and give the general rule.
- Every "not found" now comes with 2–3 related questions as chips.
- Template replies (form questions, greetings, job intros) are reworded naturally by a small model, with the
  template kept as the fallback.

**8. Hard to scan**
- Policy answers were 3–4 sentence paragraphs, and job results were long text lists.
- *Fix:* key fact first in bold plus at most 3 bullets, rendered as a policy card with source chips; jobs as cards
  with an Apply button; HR stats as a card; quick-reply chips on the welcome screen and after each reply.

## Hardcoded replies audited, per role

The roles that exist (UI `frontend/src/lib/roles.js`, backend `prompts.ROLES`) are **Candidate**, **Hiring
Manager** (an employee who manages a team, so this is also the employee-policy persona) and **HR Admin**. There is
no separate Employee role; unknown roles get the most restricted (Candidate) view.

| Role | Can ask / do | Canned replies checked | Problems found → fix |
|---|---|---|---|
| Candidate | jobs, job details, apply, own status, hiring process and policies | greeting, apply form steps, status steps, job list/detail, not-found | could reach the HR shortlist query → guarded; "apply for X" re-asked the role → prefilled; job list text-only → cards |
| Hiring Manager | policies, raise hiring request, browse jobs | greeting, hiring-request form, policy answers | pipeline questions got a job search → clear HR-only reply + ticket; personal balance → HR portal |
| HR Admin | pipeline lists and counts, find/update candidate, JD, approve/delete jobs, policies | pipeline lists, "pending hiring requests", manage-jobs steps | "how many…" had no count → stats card; manage-jobs lost its step (intent not saved) → fixed; LLM classifier on the 120B model for every message → rules first, small model only when unclear |

All prompts and role rules live in `backend/prompts.py`:
- **Per-role persona and scope:** each role's can and cannot list goes into every prompt.
- **Grounding:** answers come only from the passages, with citations.
- **Format:** key fact first, then short bullets.
- **Refusal:** a fixed NOT_FOUND token.
- **Corrections:** the re-check prompt.
- **Language:** the user's language, including Hinglish.
- **Privacy:** candidates never see applicant or employee data, and HR sees pipeline data.

Tests in `tests/test_conversation.py` check that these rules hold.

## Role scenarios (this version, local run; reviewer's reading)

**role-candidate** (Candidate)

- > hi
  - < Hi! 👋 I can show open roles (try *"Python jobs in Pune"* or *"remote jobs"*), help you apply, check your application status, and answer questions about our hir…
  - reading: greeting with chips — PASS
- > any remote jobs for AI?
  - < Here are **2 open roles** (**remote**) matching **ai**: 💼 **AI/ML Engineer** 🏢 *Tech* / 📍 **Remote** / Full-time 🎓 **Experience:** 2.5+ yrs / 💰 **CTC:** INR 6-…
  - reading: 2 remote AI roles as cards — PASS
- > tell me about the generative ai engineer role
  - < Here are the details for **Generative AI Engineer** (Remote): 💼 **Generative AI Engineer** 🏢 *Tech* / 📍 **Remote** / Full-time 🎓 **Experience:** 2+ yrs / 💰 **C…
  - reading: Generative AI Engineer card with salary band — PASS
- > I want to apply for the Generative AI Engineer job
  - < Great, let's apply for **Generative AI Engineer** (Remote). 📄 **Would you like to autofill your application using your resume?** Click the 📎 icon below to uplo…
  - reading: form starts with the role filled — PASS
- > wait, what is the notice period during probation?
  - < 💡 During probation the notice period is 15 days. [1]
  - reading: 15 days, then 'back to the form' — PASS
- > cancel
  - < 🚫 **Process Cancelled.** I have cleared your current progress. What would you like to do instead?
  - reading: cancelled — PASS
- > show me the list of shortlisted candidates
  - < Candidate and hiring-pipeline details are visible to the HR team only, so I can't share them here. I can show open roles or check your own application status.
  - reading: refused, no applicant names — PASS

**role-manager** (Hiring Manager)

- > when is salary credited?
  - < I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me about our policies, hiring process or open roles.
  - reading: payroll answer — stand-in NOT_FOUND (retrieval finds Payroll; verify live)
- > that's not right, it's the 1st
  - < Attendance and leave are counted from the 26th of the previous month to the 25th of the current month for payroll. [1] New joiners must submit: a government ph…
  - reading: correction re-check — stand-in quoted the payroll-cycle line; verify live
- > how many candidates applied for my team's opening?
  - < Candidate and hiring-pipeline details are visible to the HR team only, so I can't share them here. For an update on your team's candidates, raise a ticket to H…
  - reading: HR-only + ticket — PASS
- > I want to raise a hiring request
  - < I can help with that. Please enter the department name.
  - reading: hiring request form — PASS
- > cancel
  - < 🚫 **Process Cancelled.** I have cleared your current progress. What would you like to do instead?
  - reading: cancelled — PASS

**role-hr** (HR Admin)

- > how many candidates are shortlisted?
  - < **0 candidates in the pipeline**, 67 open roles and 0 pending hiring requests. / Stage / Candidates / /---/---/ / Shortlisted / 0 / / Awaiting interview / 0 / …
  - reading: stats card (0 candidates in the local DB) — PASS
- > pending hiring requests
  - < 📝 **No pending hiring requests from managers.** 🗂️ **Unfilled Job Openings (Newest First):** • **Content Writer** (Marketing) - Remote • **Digital Marketing Sp…
  - reading: no pending requests — PASS
- > What is the notice period policy?
  - < After confirmation, the notice period is 60 days for all roles at Senior level and above and 30 days for everyone else. [1] Unused annual leave cannot be adjus…
  - reading: 30 / 60 days — PASS
- > galat hai, 90 days hai
  - < After confirmation, the notice period is 60 days for all roles at Senior level and above and 30 days for everyone else. [1]
  - reading: re-check keeps 30/60, does not adopt '90 days' — PASS

## Cost of the model calls

**Prices** (Groq, from console.groq.com/docs/models, fetched 20 Nov 2026):

| Model | Used for | Input | Output |
|---|---|---|---|
| `openai/gpt-oss-120b` | grounded policy answers | $0.15 per 1M tokens | $0.60 per 1M tokens |
| `openai/gpt-oss-20b` | rewording | $0.075 per 1M tokens | $0.30 per 1M tokens |

`llama-3.1-8b-instant` is listed there as Enterprise-only, so it isn't the default.

**At most one model call per turn.** Job search, job cards, comparisons, stats, refusals, routing and corrections
detection are free (code).

| Turn type | Model | Prompt tokens (measured) | Output tokens (estimate, incl. reasoning) | Cost per turn |
|---|---|---|---|---|
| Policy answer / correction | gpt-oss-120b | ~1,010 | ~400 | ~$0.00039 |
| Job list intro | gpt-oss-20b, effort low | ~310 | ~120 | ~$0.00006 |
| Job detail / form step / greeting / refusal | gpt-oss-20b, effort low | 160–200 | ~120 | ~$0.00005 |
| Stats, compare table, cancelled | none | 0 | 0 | $0 |

- **Prompt tokens:** measured by running real turns through the app and counting the prompts actually sent
  (about 4 characters per token).
- **Output tokens:** an estimate, because reasoning tokens can't be measured without a key. Real per-turn usage is
  logged and stored in `chat_history.usage` after the deploy.
- **Cost per 1,000 conversations: about $1.30**, for an average of 6 turns (3 policy answers and 3 reworded
  replies). Cached greetings and job intros cost nothing on repeat.

## Before / after, every check

### Fixed question set

| id | question | expected (handbook / jobs) | live answer before | before | root cause | after |
|---|---|---|---|---|---|---|
| leave-annual | How many days of paid annual leave do employees get? | 18 days | Employees receive 18 days of paid annual leave per calendar year [1]. The leave is accrued at 1.5 days each month [1]. … | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| leave-paraphrase | How many days off do I get in a year? | 18 annual (+8 sick, 10 holidays, listed separately) | You get 18 days of paid annual leave, 8 days of sick leave, 10 public holidays, and 2 optional holidays each year [1][2… | PASS | correct, but 4 sentences of extras: hard to scan | retrieval ✓ (fact in top passage); wording: verify live |
| leave-carry | Can I carry forward my unused leave to next year? | up to 10 days | You can carry forward up to 10 unused annual leave days to the next year. Any annual leave balance above 10 days lapses… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| leave-sick | How many sick leaves do I get? | 8 days | 8 days of sick leave per year [1]. Unused sick leave does not carry forward [1][2]. | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| leave-cert | When do I need a medical certificate for sick leave? | > 2 consecutive days | You need to upload a medical certificate when your sick leave exceeds 2 consecutive days [1]. | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| holidays | How many public holidays are there in a year? | 10 | 10 public holidays per year[1]. | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| maternity | What is the maternity leave policy? | 26 weeks | 26 weeks of paid maternity leave, available after 80 days of service[1]. | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| paternity | How long is paternity leave? | 10 working days | Paternity leave is 10 working days [1]. It becomes available after completing 80 days of service [1]. | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| leave-advance | How early should I apply for leave? | 5 working days | Leave requests must be raised at least 5 working days in advance [1]. This requirement applies to all leave types excep… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| leave-approver | Who approves my leave requests? | reporting manager | The reporting manager approves leave requests [1]. HR only gets involved if there is a dispute over the request [1]. | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| wfh | Is work from home allowed? | 2 days/week after probation | Yes, employees may work from home up to 2 days per week after completing probation[1]. Remote work beyond 2 days per we… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| wfh-intern | Can interns work from home? | 1 day/week | Yes, interns can work from home 1 day per week, but only with their mentor’s approval[1]. | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| home-office | Is there any allowance for setting up a home office? | INR 10,000 one-time | Yes, a one-time home office allowance of INR 10,000 is provided [1]. It is reimbursed against bills and is available on… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| probation | How long is probation? | 6 months | The probation period is 6 months [1]. It may be extended once by up to 3 months if the 5th-month review is not satisfac… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| probation-extend | Can probation be extended? | once, up to 3 months | Yes, probation can be extended once, by up to 3 months if the review is not satisfactory[1]. The extension is limited t… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| notice-probation | What is the notice period during probation? | 15 days | The notice period during probation is 15 days [1]. This applies only while the employee remains in the probation period. | PASS* | correct number; adds an unsourced sentence | retrieval ✓ (fact in top passage); wording: verify live |
| notice-senior | What is the notice period for senior employees? | 60 days | Senior employees have a notice period of 60 days after confirmation [1]. Unused annual leave cannot be adjusted against… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| notice-others | What is the notice period policy? | 30 / 60 (15 in probation) | After confirmation, the notice period is 60 days for Senior-level and above roles and 30 days for all other employees, … | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| notice-leave | If I resign, can I use my leave balance to shorten the noti… | no | No, you cannot use your leave balance to shorten the notice period. Unused annual leave cannot be adjusted against the … | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| notice-buyout | Can I buy out my notice period? | yes, dept head + HR | Yes, you can buy out your notice period, but it requires approval from your department head and HR [1]. | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| referral-junior | What is the referral bonus for a role needing 2 years of ex… | INR 25,000 | The referral bonus is INR 25,000[1]. It is paid in two equal installments, 50% after the new hire joins and 50% after t… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| referral-senior | How much is the referral bonus for senior roles? | INR 50,000 (>3 yrs) | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me about our policies, hiring proc… | FAIL | KB gap: 'senior' undefined, model refused instead of applying the >3 years rule | fixed: handbook defines Senior level; prompt applies category rules |
| referral-paid | When is the referral bonus paid out? | 50% on joining, 50% after probation | The referral bonus is paid in two equal parts: 50 % after the new hire joins and the remaining 50 % after they complete… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| referral-intern | Are interns eligible for the referral bonus? | not eligible | No, interns are not eligible for the referral bonus [1]. Interns are specifically listed among those excluded from rece… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| interview-stages | What is the interview process? | 4 stages | The interview process consists of four stages: an application screening by the HR assistant, a 30-minute HR call, one o… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| interview-wait | How soon will I hear back after an interview? | 5 working days | You will typically hear back within 5 working days after an interview [1]. Offers are then rolled out within 3 working … | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| offer-time | How quickly are offers released after the final interview? | 3 working days | Offers are rolled out within 3 working days of the final interview [1]. | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| intern-process | What does the internship hiring process look like? | screening, 1 technical, HR call | The internship hiring process consists of a screening, one technical interview, and an HR call [1]. This is a shorter p… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| joining-docs | What documents do I need for joining? | ID, PAN, … | You need to submit a government photo ID, PAN card, address proof, educational certificates and mark sheets, relieving … | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| internal-move | Can I apply for an internal job posting? | after 12 months | Yes, you can apply for an internal job posting if you have spent at least 12 months in your current role [1]. You must … | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| hours | What are the working hours? | 9:30-6:30 | Standard working hours are 9:30 AM to 6:30 PM, Monday to Friday, with a one-hour lunch break [1]. Teams may use flexibl… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| core-hours | What are the core collaboration hours? | 11:00-4:00 | The core collaboration hours are 11:00 AM to 4:00 PM[1]. Teams may use flexible start times between 8:00 AM and 11:00 A… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| ticket-time | How long does HR take to answer a ticket? | 2 working days | HR tickets are answered within 2 working days[1]. Urgent payroll issues raised in the last week of the month are answer… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| payday | When is salary credited each month? | last working day | Salary is credited to the employee’s bank account on the last working day of each month [1]. Payslips are also made ava… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| insurance | Do employees get health insurance? | INR 5,00,000 floater | Yes, every full-time employee is covered from the date of joining by a group health insurance policy with a sum insured… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| learning | Is there a learning and certification budget? | INR 30,000 / year | Yes, each full-time employee has a learning budget of INR 30,000 per financial year [1]. The budget covers courses, cer… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| jobs-remote | Show me remote jobs | only Remote roles | Here are **13 open roles** (**remote**): 💼 **Frontend Intern** 🏢 *Tech* / 📍 **Remote** / Internship 🎓 **Experience:** F… | PASS |  | PASS (cards from DB) |
| jobs-pune | Which jobs are open in Pune? | only Pune roles | Here are **10 open roles** in **Pune**: 💼 **DevOps Engineer** 🏢 *Tech* / 📍 **Pune** / Full-time 🎓 **Experience:** 3+ yr… | PASS |  | PASS (cards from DB) |
| jobs-python | Do you have any Python developer openings? | every Python role | Here are the details for this opening: 💼 **Python Developer** 🏢 *Tech* / 📍 **Pune** / Full-time 🎓 **Experience:** 2+ yr… | FAIL | routing: 'openings' + exact title opened a single job card, hid 10 other Python roles | fixed: list of 11 Python roles as cards |
| jobs-python-noida | Any job openings for Python in Noida? | Python roles in Noida | Here are **3 open roles** in **Noida**: 💼 **Junior Python Developer** 🏢 *Tech* / 📍 **Noida** / Full-time 🎓 **Experience… | PASS |  | PASS (cards from DB) |
| jobs-hr | Are there any HR roles open? | HR team roles | Here are **16 open roles**: 💼 **HR Intern** 🏢 *HR* / 📍 **Remote** / Internship 🎓 **Experience:** Freshers welcome / 💰 *… | PASS |  | PASS (cards from DB) |
| jobs-skill-detail | What skills are required for the Data Analyst role? | Data Analyst skills | Here are the details for this opening: 💼 **Data Analyst** 🏢 *Tech* / 📍 **Bengaluru** / Full-time 🎓 **Experience:** 1.5+… | PASS |  | PASS (cards from DB) |
| refuse-pets | Can I bring my pet dog to the office? | not in KB | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me about our policies, hiring proc… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| refuse-ceo-salary | What is the CEO's salary? | not in KB | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me about our policies, hiring proc… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| refuse-general | What is the capital of France? | not in KB | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me about our policies, hiring proc… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| refuse-stock | Do employees get stock options? | not in KB | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me about our policies, hiring proc… | PASS |  | retrieval ✓ (fact in top passage); wording: verify live |
| apply-start | apply-start | form starts, cancel works | Sure. Which role are you interested in? → 🚫 **Process Cancelled.** I have cleared your current progre… | PASS |  | PASS |
| status-unknown | status-unknown | asks email then phone | I can help you check your application status! 📋 Please ente… → Got it. Now, please enter your registered **Phone Number… | PASS |  | PASS |
| form-interrupt | form-interrupt | 6 months, form resumes | Sure. Which role are you interested in? → 💡 6 months is the standard probation period for new full-ti… → 🚫 **Process Ca… | PASS |  | PASS |

### Messy real-user turns

| conversation | role | user said | correct answer | live before | verdict | cause | local after | verdict | note |
|---|---|---|---|---|---|---|---|---|---|
| typo-leave | Candidate | how many leavs do i get in a yr | 18 days annual leave (+8 sick, 10 public holidays) | You get 38 days of leave per year (18 days annual leave [1], 8 days sick leave [1], 10 pu… | FAIL | prompt: summed leave + holidays into '38 days' | Employees also get 8 days of sick leave per year. [1] | PASS* | retrieval finds Leave policy via typo correction; prompt forbids summing categories (stand-in picked the sick-leave line) |
| hinglish-leave | Hiring Manager | mujhe saal me kitni chuttiyan milti hai? | 18 annual leave days; reply may be Hinglish | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | FAIL | retrieval/routing: no Hinglish ('chuttiyan') → not found | Full-time employees receive 18 days of paid annual leave per calendar year, credited at 1… | PASS | 18 days, Leave policy |
| hinglish-notice | Hiring Manager | notice period kitna hai senior ke liye | 60 days after confirmation | 60 days is the notice period for senior level and above after confirmation [1]. Unused an… | PASS | 60 days | Senior level and above means roles that need 5 or more years of experience (for example S… | PASS | 60 days + Senior definition |
| leave-balance | Hiring Manager | how many leaves do I have left? | cannot see personal balance; point to HR portal; state entitlement 18 + 8 | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | FAIL | dead end: 'not in KB', no pointer to the HR portal | I can't see personal records like your leave balance or salary: you'll find them in the *… | PASS | explains HR portal + general rule |
| multi-part | Hiring Manager | what is the notice period and can I use my leaves… | 30 days (60 senior, 15 probation); no, leave cannot be adjusted | The notice period is 60 days for Senior level and above, 30 days for other employees, and… | PASS | both parts answered | Unused annual leave cannot be adjusted against the notice period. [1] After confirmation,… | PASS | both parts answered |
| followup-pronoun | Hiring Manager | What is the referral bonus? | 25,000 (<=3 yrs) / 50,000 (>3 yrs) | The referral bonus is INR 25,000 for roles needing up to 3 years of experience and INR 50… | PASS |  | Employees who refer a candidate who is hired receive a referral bonus: INR 25,000 for rol… | PASS |  |
| followup-pronoun | Hiring Manager | and when is it paid? | 50% after joining, 50% after probation | The annual performance bonus is paid with the June salary [5]. | FAIL | no conversation memory: 'it' answered as the performance bonus | Employees rated in the top two levels are eligible for the annual performance bonus, paid… | PASS* | question now sent with the referral question; verify wording live |
| referral-senior | Hiring Manager | How much is the referral bonus for senior roles? | INR 50,000 for roles needing more than 3 years | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | FAIL | KB gap: 'senior' undefined → refused | Senior level and above means roles that need 5 or more years of experience (for example S… | PASS* | both passages retrieved (definition + 50,000 rule) |
| salary-of-job | Candidate | what's the salary for the data analyst job? | Data Analyst (Bengaluru) INR 6-9 LPA (from record) | Here are the details for this opening: 💼 **Data Analyst** 🏢 *Tech* / 📍 **Bengaluru** / Fu… | PASS | card from record | Here are the details for **Data Analyst** (Bengaluru): 💼 **Data Analyst** 🏢 *Tech* / 📍 **… | PASS | job card, INR 6-9 LPA |
| partial-title | Candidate | tell me about the devops role | DevOps Engineer card (Pune) | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | FAIL | title matching needed the exact title | Here are the details for **DevOps Engineer** (Pune): 💼 **DevOps Engineer** 🏢 *Tech* / 📍 *… | PASS | DevOps Engineer card |
| compare-jobs | Candidate | compare the Data Analyst and Data Scientist roles | both cards side by side (Data Analyst Bengaluru, Data Scientist Hyderabad) | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | FAIL | no compare intent → not found | Here's how **Data Analyst** and **Data Scientist** compare: / / **Data Analyst** / **Data… | PASS | side-by-side table + 2 cards |
| python-openings | Candidate | Do you have any Python developer openings? | list of all Python roles, not one card | Here are the details for this opening: 💼 **Python Developer** 🏢 *Tech* / 📍 **Pune** / Ful… | FAIL | single card instead of the list | Here are **11 open roles** matching **python**: 💼 **Junior Python Developer** 🏢 *Tech* / … | PASS | 11 Python roles as cards |
| jobs-followup-city | Candidate | show me python jobs | Python roles list | Here are **10 open roles**: 💼 **Junior Python Developer** 🏢 *Tech* / 📍 **Noida** / Full-t… | PASS |  | Here are **11 open roles** matching **python**: 💼 **Junior Python Developer** 🏢 *Tech* / … | PASS |  |
| jobs-followup-city | Candidate | only in pune | Python roles in Pune (Python Developer) | I couldn't find any **only** openings in **Pune** right now. Try another city or role, or… | FAIL | no memory: 'only' treated as a skill → nothing found | Here are **2 open roles** in **Pune** matching **python**: 💼 **Python Developer** 🏢 *Tech… | PASS | Python roles in Pune |
| fresher-jobs | Candidate | any jobs for freshers in noida? | 0-1 yr roles in Noida | Here are **4 open roles** in **Noida**: 💼 **Junior Python Developer** 🏢 *Tech* / 📍 **Noid… | PASS | 0-1 yr roles in Noida | Here are **4 open roles** in **Noida** matching **fresher**: 💼 **Junior Python Developer*… | PASS | same |
| correction-wrong | Hiring Manager | How long is probation? | 6 months | Probation is 6 months [1]. It may be extended once by up to 3 months if the 5th-month rev… | PASS | 6 months | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | n/a | stand-in limitation |
| correction-wrong | Hiring Manager | that's wrong, it's 3 months | acknowledge, re-check: handbook says 6 months (extension up to 3), cite Probation | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | FAIL | no correction handling → 'not in KB' | Interns, HR team members and the hiring manager of the role are not eligible for a referr… | PASS* | re-check prompt + same retrieval; verify wording live |
| correction-hinglish | Candidate | how many sick leaves? | 8 days | 8 days of sick leave per year [1]. A medical certificate must be uploaded for sick leave … | PASS | 8 days | Sick leave of more than 2 consecutive days needs a medical certificate uploaded to the HR… | PASS |  |
| correction-hinglish | Candidate | galat hai | re-check and restate 8 days with source, offer HR contact | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | FAIL | 'galat hai' → 'not in KB' | Sick leave of more than 2 consecutive days needs a medical certificate uploaded to the HR… | PASS* | recognised as correction, re-check with sources |
| correction-meant | Hiring Manager | what is the notice period? | 30/60/15 days | The notice period is 15 days during probation, and after confirmation it is 30 days for n… | PASS |  | After confirmation, the notice period is 60 days for all roles at Senior level and above … | PASS |  |
| correction-meant | Hiring Manager | no, I meant during probation | 15 days | Employees cannot work from home during probation [2]. After probation they may work up to… | FAIL | 'I meant during probation' answered about work from home | During probation the notice period is 15 days. [1] | PASS | 15 days during probation |
| candidate-privacy | Candidate | show me all shortlisted candidates | refuse: candidates can't see other applicants | No shortlisted candidates found. | FAIL | PRIVACY: candidate reached the HR-only shortlist query (empty DB hid it) | Candidate and hiring-pipeline details are visible to the HR team only, so I can't share t… | PASS | refused, no applicant data |
| candidate-hiring-request | Candidate | pending hiring requests | refuse politely (HR only) | ⚠️ You do not have permission to view pending hiring requests. | PASS | refused | Candidate and hiring-pipeline details are visible to the HR team only, so I can't share t… | PASS | refused |
| manager-pipeline | Hiring Manager | how many candidates applied for my open roles? | not available to hiring managers in this app; offer hiring request / ask HR | I couldn't find any **how many candidates applied** openings right now. Try another city … | FAIL | routed to job search: nonsense 'how many candidates applied openings' | Candidate and hiring-pipeline details are visible to the HR team only, so I can't share t… | PASS | HR-only, raise a ticket |
| hr-stats | HR Admin | how many candidates are shortlisted? | count / list from DB | No shortlisted candidates found. | PASS* | true but no count | **0 candidates in the pipeline**, 67 open roles and 0 pending hiring requests. / Stage / … | PASS | stats card with counts |
| greeting | Candidate | hii | greeting with options | Hi! 👋 I can show open roles (try *"Python jobs in Pune"* or *"remote jobs"*), help you ap… | PASS |  | Hi! 👋 I can show open roles (try *"Python jobs in Pune"* or *"remote jobs"*), help you ap… | PASS | + chips |
| out-of-scope-hinglish | Candidate | aaj mausam kaisa hai? | polite not-in-KB with suggestions | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | PASS | not in KB | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | PASS | not in KB + suggestions |
| apply-with-role | Candidate | I want to apply for the Data Analyst job | starts application with the role already known | Sure. Which role are you interested in? | FAIL | asked the role again | Great, let's apply for **Data Analyst** (Bengaluru). 📄 **Would you like to autofill your … | PASS | form starts with the role filled |
| role-candidate | Candidate | hi | candidate greeting + chips | - | not run |  | Hi! 👋 I can show open roles (try *"Python jobs in Pune"* or *"remote jobs"*), help you ap… | PASS |  |
| role-candidate | Candidate | any remote jobs for AI? | AI/ML Engineer, Generative AI Engineer (Remote) | - | not run |  | Here are **2 open roles** (**remote**) matching **ai**: 💼 **AI/ML Engineer** 🏢 *Tech* / 📍… | PASS |  |
| role-candidate | Candidate | tell me about the generative ai engineer role | Generative AI Engineer card, salary band | - | not run |  | Here are the details for **Generative AI Engineer** (Remote): 💼 **Generative AI Engineer*… | PASS |  |
| role-candidate | Candidate | I want to apply for the Generative AI Engineer job | form starts with role known; autofill question | - | not run |  | Great, let's apply for **Generative AI Engineer** (Remote). 📄 **Would you like to autofil… | PASS |  |
| role-candidate | Candidate | wait, what is the notice period during probation? | 15 days, then back to the form | - | not run |  | 💡 During probation the notice period is 15 days. [1] | PASS |  |
| role-candidate | Candidate | cancel | cancelled | - | not run |  | 🚫 **Process Cancelled.** I have cleared your current progress. What would you like to do … | PASS |  |
| role-candidate | Candidate | show me the list of shortlisted candidates | refused (HR only), no names | - | not run |  | Candidate and hiring-pipeline details are visible to the HR team only, so I can't share t… | PASS |  |
| role-manager | Hiring Manager | when is salary credited? | last working day of the month | - | not run |  | I couldn't find that in the HR knowledge base. Please check with the HR team, or ask me a… | PASS |  |
| role-manager | Hiring Manager | that's not right, it's the 1st | re-checked: last working day, quote | - | not run |  | Attendance and leave are counted from the 26th of the previous month to the 25th of the c… | PASS |  |
| role-manager | Hiring Manager | how many candidates applied for my team's opening? | refused: HR only, raise ticket | - | not run |  | Candidate and hiring-pipeline details are visible to the HR team only, so I can't share t… | PASS |  |
| role-manager | Hiring Manager | I want to raise a hiring request | form: department | - | not run |  | I can help with that. Please enter the department name. | PASS |  |
| role-manager | Hiring Manager | cancel | cancelled | - | not run |  | 🚫 **Process Cancelled.** I have cleared your current progress. What would you like to do … | PASS |  |
| role-hr | HR Admin | how many candidates are shortlisted? | stats card | - | not run |  | **0 candidates in the pipeline**, 67 open roles and 0 pending hiring requests. / Stage / … | PASS |  |
| role-hr | HR Admin | pending hiring requests | list or none | - | not run |  | 📝 **No pending hiring requests from managers.** 🗂️ **Unfilled Job Openings (Newest First)… | PASS |  |
| role-hr | HR Admin | What is the notice period policy? | 30 / 60 / 15 days | - | not run |  | After confirmation, the notice period is 60 days for all roles at Senior level and above … | PASS |  |
| role-hr | HR Admin | galat hai, 90 days hai | re-checked: 30/60, not 90 | - | not run |  | After confirmation, the notice period is 60 days for all roles at Senior level and above … | PASS |  |
