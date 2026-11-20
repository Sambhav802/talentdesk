"""Structured payloads, role rules, corrections, follow-ups and the low-cost wording layer."""
import asyncio

import httpx
import pytest

import config
import llm
import phrasing
import prompts
from database import candidates_collection, job_openings_collection
from main import app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def ask(client, msg, role="Candidate", session="c1"):
    r = await client.post("/chat", json={"session_id": session, "message": msg, "user_role": role})
    assert r.status_code == 200, r.text
    out = r.json()
    out["text"] = out["response"]
    return out


def systems(fake):
    return [next((m["content"] for m in c["messages"] if m["role"] == "system"), "") for c in fake.calls]


# ---------- structured job payloads: cards come from the database, not from model text ----------

async def test_job_list_payload_matches_the_database(client):
    out = await ask(client, "Which jobs are open in Pune?")
    assert out["type"] == "jobs" and out["cards"] and out["intro"]
    for card in out["cards"]:
        assert card["kind"] == "job" and card["location"] == "Pune"
        db = await job_openings_collection.find_one({"title": card["title"], "location": "Pune"})
        assert card["salary"] == db["budget"] and card["openings"] == db["openings"]
        assert card["skills"] == db["skills_required"]
    assert out["suggestions"] and all(isinstance(s, str) for s in out["suggestions"])


async def test_listing_question_returns_every_match_not_one_card(client):
    out = await ask(client, "Do you have any Python developer openings?")
    assert out["type"] == "jobs" and len(out["cards"]) > 1
    assert all("python" in (c["title"] + " " + " ".join(c["skills"])).lower() for c in out["cards"])


async def test_partial_title_and_salary_question(client):
    out = await ask(client, "tell me about the devops role")
    assert out["type"] == "job_detail" and out["cards"][0]["title"] == "DevOps Engineer"
    out = await ask(client, "what's the salary for the data analyst job?", session="c2")
    assert out["cards"][0]["title"] == "Data Analyst" and out["cards"][0]["salary"] in out["fallback"]


async def test_compare_two_jobs(client):
    out = await ask(client, "compare the Data Analyst and Data Scientist roles")
    assert out["type"] == "compare" and [c["title"] for c in out["cards"]] == ["Data Analyst", "Data Scientist"]
    assert "| Salary |" in out["text"]


async def test_job_follow_up_keeps_the_previous_filter(client):
    await ask(client, "show me python jobs", session="f")
    out = await ask(client, "only in pune", session="f")
    assert out["type"] == "jobs" and out["cards"]
    assert all(c["location"] == "Pune" for c in out["cards"])
    assert all("python" in (c["title"] + " ".join(c["skills"])).lower() for c in out["cards"])


async def test_apply_with_a_named_role_skips_the_role_question(client):
    out = await ask(client, "I want to apply for the Data Analyst job")
    assert "Data Analyst" in out["text"] and "'No'" in out["text"] and out["type"] == "form"


# ---------- policy answers: structured card, follow-ups, corrections ----------

async def test_policy_answer_is_a_card_with_sources(client):
    out = await ask(client, "How many days of annual leave do employees get?")
    assert out["type"] == "policy" and out["citations"]
    card = out["cards"][0]
    assert card["kind"] == "policy" and card["key"] and card["sources"][0]["n"] == 1
    assert card["title"] == out["citations"][0]["section"]


async def test_follow_up_is_read_with_the_previous_question(client, fresh_env):
    await ask(client, "What is the referral bonus?", role="Hiring Manager", session="r")
    await ask(client, "and when is it paid?", role="Hiring Manager", session="r")
    last_user = fresh_env.calls[-1]["messages"][-1]["content"]
    assert "referral bonus" in last_user.lower() and "when is it paid" in last_user.lower()


async def test_rephrase_uses_the_previous_question(client, fresh_env):
    await ask(client, "what is the notice period?", role="Hiring Manager", session="n")
    await ask(client, "no, I meant during probation", role="Hiring Manager", session="n")
    q = fresh_env.calls[-1]["messages"][-1]["content"].lower()
    assert "notice period" in q and "during probation" in q


async def test_correction_rechecks_the_source_and_never_adopts_the_claim(client, fresh_env):
    await ask(client, "How long is probation?", role="Hiring Manager", session="w")
    out = await ask(client, "that's wrong, it's 3 months", role="Hiring Manager", session="w")
    assert "previous answer was wrong" in systems(fresh_env)[-1]
    user = fresh_env.calls[-1]["messages"][-1]["content"]
    assert "Original question: How long is probation?" in user and "User's objection: that's wrong" in user
    assert out["type"] == "correction" and out["citations"]
    assert "How do I contact HR?" in out["suggestions"]


async def test_hinglish_correction_is_recognised(client, fresh_env):
    await ask(client, "how many sick leaves?", session="g")
    out = await ask(client, "galat hai", session="g")
    assert "previous answer was wrong" in systems(fresh_env)[-1] and out["type"] == "correction"


async def test_personal_records_point_to_the_hr_portal(client):
    out = await ask(client, "how many leaves do I have left?", role="Hiring Manager")
    assert "HR portal" in out["text"]


async def test_not_found_offers_follow_up_questions(client):
    out = await ask(client, "What is the capital of France?")
    assert out["type"] == "not_found" and 2 <= len(out["suggestions"]) <= 3


# ---------- role rules ----------

async def _one_candidate():
    await candidates_collection.insert_one({"full_name": "Asha Verma", "email": "asha@example.com",
                                            "preferred_role": "Data Analyst",
                                            "screening_status": "Shortlisted for next step"})


async def test_candidate_never_sees_other_applicants(client):
    await _one_candidate()
    out = await ask(client, "show me all shortlisted candidates", role="Candidate")
    assert out["type"] == "refusal" and "Asha" not in out["text"] and "asha@example.com" not in out["text"]


async def test_hiring_manager_pipeline_question_gets_a_clear_answer(client):
    await _one_candidate()
    out = await ask(client, "how many candidates applied for my open roles?", role="Hiring Manager")
    assert out["type"] == "refusal" and "HR team" in out["text"] and "Asha" not in out["text"]


async def test_candidate_cannot_raise_hiring_requests(client):
    out = await ask(client, "I want to raise a hiring request", role="Candidate")
    assert out["type"] == "refusal"


async def test_hr_admin_gets_pipeline_counts(client):
    await _one_candidate()
    out = await ask(client, "how many candidates are shortlisted?", role="HR Admin")
    assert out["type"] == "stats" and out["cards"][0]["total"] == 1
    assert {"label": "Shortlisted", "value": 1} in out["cards"][0]["rows"]


def test_role_rules_in_prompts():
    for role in prompts.ROLES:
        p = prompts.policy_system(role)
        assert "ONLY from the numbered context passages" in p and prompts.NOT_FOUND in p
        assert "Hinglish" in p and "[1]" in p
    assert "see other applicants" in prompts.policy_system("Candidate")
    assert "candidate pipeline" in prompts.policy_system("HR Admin")
    assert "Never accept the user's claim" in prompts.correction_system("Candidate")
    assert prompts.allowed("hr_admin_queries", "HR Admin") and not prompts.allowed("hr_admin_queries", "Candidate")
    assert not prompts.allowed("hr_find_candidate", "Hiring Manager")
    assert prompts.allowed("apply_job", "Candidate") and not prompts.allowed("apply_job", "HR Admin")
    assert prompts.allowed("raise_hiring_request", "Hiring Manager") and not prompts.allowed("raise_hiring_request",
                                                                                              "Candidate")
    assert prompts.role_of("Employee") == "Candidate"      # unknown roles get the most restricted view


# ---------- wording layer: small model, one call per turn, fallbacks ----------

@pytest.fixture
def phrasing_on(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "test")
    monkeypatch.setattr(config, "PHRASE_MODEL", "small-model")
    phrasing._cache.clear()
    calls = []

    def fake_complete(messages, purpose="answer", model=None, **kw):
        calls.append({"purpose": purpose, "model": model, "kw": kw, "messages": messages})
        draft = messages[-1]["content"].split("DRAFT: ", 1)[-1]
        return "Good news! " + draft
    monkeypatch.setattr(llm, "complete", fake_complete)
    return calls


async def test_job_intro_is_reworded_but_cards_stay_from_data(client, phrasing_on):
    out = await ask(client, "Which jobs are open in Pune?")
    assert out["intro"].startswith("Good news!") and out["text"].startswith("Good news!")
    assert all(c["location"] == "Pune" for c in out["cards"])
    call = phrasing_on[-1]
    assert call["model"] == "small-model" and call["kw"]["max_tokens"] <= 300 and call["kw"]["temperature"] == 0.3
    assert "FACTS:" in call["messages"][-1]["content"]              # compact summary, not full cards
    assert len(phrasing_on) == 1


async def test_policy_turn_makes_no_extra_wording_call(client, phrasing_on, fresh_env):
    await ask(client, "How many days of annual leave do employees get?")
    assert phrasing_on and all(c["purpose"] != "phrase" for c in phrasing_on)


async def test_wording_failure_falls_back_to_the_template(client, monkeypatch, phrasing_on):
    def boom(*a, **k):
        raise RuntimeError("rate limited")
    monkeypatch.setattr(llm, "complete", boom)
    out = await ask(client, "I want to apply for a job")
    assert out["text"] == "Sure. Which role are you interested in?"


async def test_wording_timeout_falls_back(monkeypatch, phrasing_on):
    monkeypatch.setattr(config, "PHRASE_TIMEOUT_S", 0.05)

    def slow(*a, **k):
        import time
        time.sleep(0.3)
        return "too late"
    monkeypatch.setattr(llm, "complete", slow)
    assert await phrasing.phrase("Please enter your **Email ID**.", "Candidate") == "Please enter your **Email ID**."


async def test_rewording_that_drops_facts_is_rejected(monkeypatch, phrasing_on):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "Sure, tell me more!")
    draft = "Type **'No'** to fill the form manually, or upload your resume."
    assert await phrasing.phrase(draft, "Candidate") == draft


async def test_identical_wording_requests_are_cached(phrasing_on):
    a = await phrasing.phrase("Here are **3 open roles** in **Pune**:", "Candidate", "jobs in pune")
    b = await phrasing.phrase("Here are **3 open roles** in **Pune**:", "Candidate", "jobs in pune")
    assert a == b and len(phrasing_on) == 1


async def test_usage_is_reported_per_turn(client):
    out = await ask(client, "How many days of annual leave do employees get?")
    assert out["usage"]["calls"] == 1                              # exactly one model call for a policy answer
    out = await ask(client, "Which jobs are open in Pune?", session="u2")
    assert out["usage"]["calls"] == 0                              # job search is free (no key in tests)


def test_phrasing_never_runs_without_a_key(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    assert asyncio.run(phrasing.phrase("Hello", "Candidate")) == "Hello"


async def test_rewording_that_is_much_shorter_is_rejected(monkeypatch, phrasing_on):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "ok")
    draft = "Candidate and hiring-pipeline details are visible to the HR team only, so I can't share them here."
    assert await phrasing.phrase(draft, "Candidate") == draft


async def test_typos_still_find_the_policy(client):
    from rag import store
    await ask(client, "hello")                                       # seeds the knowledge base
    hits = await store.search("how many leavs do i get in a yr", doc_type="document")
    assert hits and hits[0]["section"] == "Leave policy"
    hits = await store.search("how long is probaton", doc_type="document")
    assert hits and hits[0]["section"] == "Probation"


# ---------- round 3: rewording keeps the purpose, fresher filter, follow-ups, reply shape ----------

async def test_hiring_request_rewrite_that_changes_the_action_is_rejected(client, monkeypatch, phrasing_on):
    bad = "Sure thing! Just let me know the department name, and I'll pull up the candidate count for your team."
    monkeypatch.setattr(llm, "complete", lambda *a, **k: bad)
    out = await ask(client, "I want to raise a hiring request", role="Hiring Manager")
    assert out["text"] == "I can help with that. Please enter the department name."


async def test_rewrite_must_keep_the_required_field(monkeypatch, phrasing_on):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "Sure, which team are you hiring for today?")
    draft = "I can help with that. Please enter the department name."
    assert await phrasing.phrase(draft, "Hiring Manager", purpose="ask for the department",
                                 must_keep=["department"]) == draft


async def test_form_step_rewrite_gets_its_purpose(client, phrasing_on):
    out = await ask(client, "I want to raise a hiring request", role="Hiring Manager")
    prompt = phrasing_on[-1]["messages"][-1]["content"]
    assert "PURPOSE: ask for the department name of the new hiring request" in prompt
    assert "MUST KEEP: department" in prompt and out["text"].startswith("Good news!")


async def test_unlisted_form_steps_keep_the_template(client, phrasing_on):
    out = await ask(client, "find candidate details for asha@example.com", role="HR Admin")
    assert out["type"] == "form"                                  # hr_find_candidate / ask_identifier: not listed
    assert not [c for c in phrasing_on if c["purpose"] == "phrase"]


async def test_job_intro_rewrite_that_lists_jobs_is_rejected(monkeypatch, phrasing_on):
    listy = "Here are 3 roles in Pune:\n- **Python Developer**\n- **DevOps Engineer**"
    monkeypatch.setattr(llm, "complete", lambda *a, **k: listy)
    draft = "Here are **3 open roles** in **Pune**."
    assert await phrasing.phrase(draft, "Candidate", purpose=prompts.REPLY_PURPOSE["jobs"]) == draft


async def test_freshers_means_zero_experience(client):
    out = await ask(client, "any jobs for freshers in noida?")
    assert out["cards"] and all(c["experience_years"] == 0 for c in out["cards"])
    assert all(c["location"] == "Noida" for c in out["cards"])
    assert "Recruitment Coordinator" not in [c["title"] for c in out["cards"]]


async def test_follow_up_answers_only_the_sub_question(client, fresh_env):
    await ask(client, "What is the referral bonus?", role="Hiring Manager", session="fu")
    await ask(client, "and when is it paid?", role="Hiring Manager", session="fu")
    system = systems(fresh_env)[-1]
    user = fresh_env.calls[-1]["messages"][-1]["content"]
    assert "Answer ONLY the specific point the follow-up asks" in system
    assert "Earlier question (context only): What is the referral bonus?" in user
    assert user.rstrip().endswith("Question: and when is it paid?")


async def test_job_reply_text_is_the_intro_and_cards_carry_the_details(client):
    out = await ask(client, "Which jobs are open in Pune?")
    assert out["text"] == out["intro"] and "💼" not in out["text"] and "━" not in out["text"]
    assert out["fallback"].count("\n- **") == len(out["cards"])


async def test_at_most_one_emoji_in_prose(client):
    import re as _re
    emoji = _re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿←-⇿⌀-⏿]")
    for msg in ("I want to apply for a job", "cancel", "hello", "I want to apply for the Data Analyst job"):
        out = await ask(client, msg, session="e")
        assert len(emoji.findall(out["text"])) <= 1, out["text"]
    await ask(client, "I want to apply for a job", session="e2")
    out = await ask(client, "wait, how long is probation?", session="e2")
    assert len(emoji.findall(out["text"])) <= 1 and "back to your form" in out["text"]


async def test_leave_balance_goes_straight_to_the_policy(client, fresh_env):
    out = await ask(client, "how many leaves do I have left?", role="Hiring Manager")
    q = fresh_env.calls[-1]["messages"][-1]["content"]
    assert "How many days of annual and sick leave do employees get" in q and "left" not in q.split("Question:")[-1]
    assert out["text"].count("HR portal") == 1


async def test_job_intro_rewrite_that_names_the_jobs_is_rejected(monkeypatch, phrasing_on):
    inline = "Here are **3 open roles** in **Noida**: Junior Python Developer, Customer Support Executive and more."
    monkeypatch.setattr(llm, "complete", lambda *a, **k: inline)
    draft = "Here are **3 open roles** in **Noida**."
    facts = {"top": [{"title": "Junior Python Developer"}, {"title": "Customer Support Executive"}]}
    assert await phrasing.phrase(draft, "Candidate", facts=facts, purpose=prompts.REPLY_PURPOSE["jobs"]) == draft


async def test_job_detail_answers_the_asked_attribute_first(client):
    out = await ask(client, "What skills are required for the Data Analyst role?")
    card = out["cards"][0]
    assert out["text"].startswith("**Data Analyst** (Bengaluru) needs:") and all(k in out["text"] for k in card["skills"])
    assert "skills:" in out["fallback"]
    out = await ask(client, "what's the salary for the data analyst job?", session="sal")
    assert f"**{out['cards'][0]['salary']}**" in out["text"]


async def test_refusal_rewrite_cannot_borrow_an_old_topic(monkeypatch, phrasing_on):
    bad = ("I'm sorry, but the notice period during probation isn't available for your role. However, I can show "
           "you the open roles or check your own application status.")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: bad)
    draft = prompts.not_allowed_reply("hr_admin_queries", "Candidate")
    assert await phrasing.phrase(draft, "Candidate", "show me the list of shortlisted candidates",
                                 purpose=prompts.REPLY_PURPOSE["refusal"]) == draft


async def test_rewording_prompt_carries_no_earlier_turns(phrasing_on):
    await phrasing.phrase("Please enter the department name.", "Hiring Manager", "I want to raise a hiring request",
                          history=["what is the notice period during probation?"], purpose="ask for the department",
                          must_keep=["department"])
    assert "notice period" not in phrasing_on[-1]["messages"][-1]["content"]
