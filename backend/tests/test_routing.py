"""Routing, job search, grounded fallbacks and versioned seeding (the fixes for wrong or invented answers)."""
import httpx
import pytest

import bootstrap
import job_search
from database import job_openings_collection, kb_documents_collection, meta_collection
from main import app
from router import rule_intent


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def chat(client, msg, role="Candidate", session="s1"):
    r = await client.post("/chat", json={"session_id": session, "message": msg, "user_role": role})
    assert r.status_code == 200
    return r.json()["response"]


@pytest.mark.parametrize("msg,role,intent", [
    ("Can I apply for an internal job posting?", "Hiring Manager", "hr_knowledge"),
    ("How long is probation?", "Hiring Manager", "hr_knowledge"),
    ("When is salary credited each month?", "Hiring Manager", "hr_knowledge"),
    ("What is the CEO's salary?", "Hiring Manager", "hr_knowledge"),
    ("Is work from home allowed?", "Candidate", "hr_knowledge"),
    ("Show me remote jobs", "Candidate", "view_jobs"),
    ("Any job openings for Python in Noida?", "Candidate", "view_jobs"),
    ("Are there any HR roles open?", "Candidate", "view_jobs"),
    ("I want to apply for a job", "Candidate", "apply_job"),
    ("Check my application status", "Candidate", "check_status"),
    ("I want to raise a hiring request", "Hiring Manager", "raise_hiring_request"),
    ("hello", "Candidate", "greeting"),
    ("Generate a job description for a Data Analyst", "HR Admin", "hr_generate_jd"),
    ("Show shortlisted candidates", "HR Admin", "hr_admin_queries"),
    ("how many leaves do I have left?", "Hiring Manager", "personal_data"),
    ("mujhe saal me kitni chuttiyan milti hai?", "Hiring Manager", "hr_knowledge"),
    ("compare the Data Analyst and Data Scientist roles", "Candidate", "compare_jobs"),
    ("how many candidates applied for my open roles?", "Hiring Manager", "hr_admin_queries"),
])
def test_rule_intent(msg, role, intent):
    assert rule_intent(msg, role) == intent


async def _seed():
    await bootstrap.run()


async def test_job_search_filters_city_and_skill():
    await _seed()
    res = await job_search.list_jobs("Any job openings for Python in Noida?")
    out = res["fallback"]
    assert "Python" in out and "Customer Support" not in out and "Recruiter" not in out
    assert {c["location"] for c in res["cards"]} == {"Noida"}


async def test_job_search_remote_and_department():
    await _seed()
    remote = await job_search.list_jobs("Show me remote jobs")
    assert {c["location"] for c in remote["cards"]} == {"Remote"}
    hr = (await job_search.list_jobs("Are there any HR roles open?"))["fallback"]
    assert "Recruit" in hr and "Python Developer" not in hr


async def test_job_search_no_match_says_so():
    await _seed()
    out = (await job_search.list_jobs("Any Rust developer openings in Pune?"))["text"]
    assert out.startswith("I couldn't find any")


async def test_job_detail_uses_the_record():
    await _seed()
    res = await job_search.job_detail("What skills are required for the Data Analyst role?")
    assert res["text"] == res["intro"] and "Data Analyst" in res["intro"]
    assert "SQL" in res["cards"][0]["skills"] and "CTC" in res["fallback"]
    assert await job_search.job_detail("What is the leave policy?") is None


async def test_out_of_scope_is_refused_not_invented(client, fresh_env):
    out = await chat(client, "What is the capital of France?")
    assert "couldn't find that in the HR knowledge base" in out
    # no free-text completion: every model call was the classifier or a grounded (numbered-context) answer
    for call in fresh_env.calls:
        system = next((m["content"] for m in call["messages"] if m["role"] == "system"), "")
        user = call["messages"][-1]["content"]
        assert "Classify their message" in user or "numbered context passages" in system


async def test_internal_posting_question_does_not_open_the_form(client):
    out = await chat(client, "Can I apply for an internal job posting?", role="Hiring Manager")
    assert "Which role are you interested in" not in out


async def test_question_inside_the_form_is_answered_from_the_kb(client, fresh_env):
    assert "role" in (await chat(client, "I want to apply for a job", session="f1")).lower()
    out = await chat(client, "Wait, how long is probation?", session="f1")
    assert "back to your form" in out and "Sources" in out
    assert any("numbered context passages" in next((m["content"] for m in c["messages"] if m["role"] == "system"), "")
               for c in fresh_env.calls)


async def test_job_list_from_chat_matches_the_question(client):
    r = await client.post("/chat", json={"session_id": "s1", "message": "Which jobs are open in Pune?", "user_role": "Candidate"})
    cards = r.json()["cards"]
    assert cards and {c["location"] for c in cards} == {"Pune"}


async def test_seeding_is_idempotent_and_fills_missing_fields():
    first = await bootstrap.run()
    n = await job_openings_collection.count_documents({})
    assert first["jobs_seeded"] == n
    await job_openings_collection.update_one({"title": "Data Analyst"}, {"$unset": {"budget": ""}})
    second = await bootstrap.run()
    assert second["jobs_seeded"] == 1 and await job_openings_collection.count_documents({}) == n
    assert (await job_openings_collection.find_one({"title": "Data Analyst"}))["budget"]
    assert await kb_documents_collection.count_documents({"source": bootstrap.HANDBOOK_SOURCE}) == 1


async def test_old_seed_version_gets_the_new_handbook():
    await bootstrap.run()
    await kb_documents_collection.update_many({"source": bootstrap.HANDBOOK_SOURCE}, {"$set": {"title": "old"}})
    await meta_collection.update_one({"_id": "bootstrap"}, {"$set": {"version": 1}})
    report = await bootstrap.run()
    assert report["handbook_ingested"]
    docs = await kb_documents_collection.find({"source": bootstrap.HANDBOOK_SOURCE}).to_list(10)
    assert [d["title"] for d in docs] == [bootstrap.HANDBOOK_TITLE]
