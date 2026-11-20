# What changed (November 2026)

## Why answers were wrong

An end-to-end check of the live site (46 questions + 3 conversations, `backend/scripts/e2e_eval.py`) found:

1. **Invented answers.** Questions the router did not recognise went to the model with no context ("What is the
   capital of France?" -> "Paris"), and questions asked in the middle of the application form were answered the same
   way (probation came back as "three months"; the handbook says 6 months).
2. **Wrong routing.** "Can I apply for an internal job posting?" started the job application form.
3. **Job search ignored the role.** Any message containing "job opening" listed every opening in the city, so
   "Python jobs in Noida" also showed support and recruiter roles.
4. **Messy answers and sources.** The model wrote citations as 【1】 and used special spaces/hyphens; citations
   then fell back to "every retrieved passage", so unrelated sections appeared under Sources.
5. **Missing content.** Payroll dates, health insurance, learning budget, appraisals, exit, travel, dress code and
   more were not in the handbook, so those questions could not be answered.

## Fixes

- `backend/router.py` (new): rules decide clear cases before the LLM classifier: policy questions, job searches,
  apply, status, hiring requests, greetings.
- `backend/job_search.py` (new): job listings come straight from the database, filtered by city, department,
  experience level and role/skill words; questions about one named opening ("skills for the Data Analyst role")
  answer from that opening's record. No model involved, so no invented roles or salaries.
- `backend/bot_logic.py`: no free-text model answers anywhere: unknown questions and questions asked inside a form
  are answered only from the knowledge base, or get "I couldn't find that in the HR knowledge base".
- `backend/rag/answer.py`: stricter grounded prompt (direct answer with the exact number first), output clean-up
  (citations, spaces, hyphens), only the passages actually cited are listed, room for the reasoning model's tokens.
- `backend/rag/store.py`: section headings count in lexical search, HR synonym expansion ("days off" -> annual
  leave, "quit" -> notice period, "payday" -> salary credited ...), handbook re-ingest helper; config: top 5 passages.
- `backend/seed/handbook.md`: full employee handbook (payroll, benefits and insurance, learning, appraisals, exit,
  reimbursements and travel, holidays list, code of conduct, IT, offers) consistent with the existing policies.
- `backend/seed/jobs.json`: 67 openings (25 new; Hyderabad added; Finance, Sales, Marketing, Product, Design teams),
  every opening with a salary band, number of openings, posting date and apply-by date.
- Seeding is versioned and idempotent (`bootstrap.SEED_VERSION`): an existing database gets the new handbook and the
  missing openings on the next cold start; existing jobs only get fields they don't have; nothing is deleted.
- `backend/config.py`: the hardcoded MongoDB connection string was removed. **That password was public on GitHub:
  change it in MongoDB Atlas (Database Access) and set the new string only in Vercel as `MONGO_URI`.**
- Tests: 58 passing (24 new: routing, job filters, no ungrounded answers, form interruption, seeding).
- `backend/scripts/e2e_eval.py` + `eval_set.json` and `backend/scripts/retrieval_eval.py` to measure quality on any
  deployment.

## Results

| Check | Live site before | This version |
|---|---|---|
| End-to-end questions + flows (real model) | 30 / 49 | run after redeploy (needs the Groq key) |
| Retrieval: fact in the top passage | 32 / 36 | 36 / 36 |
| Job searches | 5 / 6 | 6 / 6 |

## Deploy

1. Rotate the MongoDB Atlas password (see above).
2. Copy these files over your repo, commit and push. Both Vercel projects redeploy.
3. Backend environment variables in Vercel: `GROQ_API_KEY`, `MONGO_URI`, `ALLOWED_ORIGINS` (your frontend URL),
   optional `EMBEDDINGS_PROVIDER` + key. Frontend: `VITE_API_URL` = the backend URL.
4. Open the site once: the first request upgrades the seed data. Or call
   `POST <backend>/admin/bootstrap` with header `X-User-Role: HR Admin`.
5. Check: `cd backend && python scripts/e2e_eval.py https://<backend>.vercel.app`.
