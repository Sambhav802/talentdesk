"""API smoke tests against the real FastAPI app with in-memory MongoDB and a fake Groq model."""
import io

import httpx
import pytest
from pypdf import PdfWriter

from database import hiring_requests_collection, kb_documents_collection, resume_files_collection
from main import app

ADMIN = {"X-User-Role": "HR Admin"}


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_root_and_bootstrap_seeds_demo_data(client):
    r = await client.get("/")
    assert r.status_code == 200 and r.json()["rag"]["embeddings"] == "none"
    r = await client.get("/admin/dashboard")          # first real request triggers the lazy bootstrap
    assert r.status_code == 200
    assert len(r.json()["jobs"]) == 42
    docs = (await client.get("/kb/documents")).json()["documents"]
    assert [d["source"] for d in docs] == ["seed:handbook.md"]
    assert await kb_documents_collection.count_documents({"type": "job"}) == 42


async def test_kb_search_returns_scored_chunks(client):
    r = await client.post("/kb/search", json={"query": "referral bonus for senior roles"})
    res = r.json()["results"]
    assert res and res[0]["section"] == "Employee referral bonus"
    assert {"score", "bm25", "text", "title"} <= set(res[0])


async def test_kb_writes_need_hr_admin(client):
    files = {"file": ("travel_policy.md", b"# Travel\n\nEconomy class for trips under 6 hours.", "text/markdown")}
    assert (await client.post("/kb/upload", files=files)).status_code == 403
    assert (await client.post("/kb/upload", files=files, headers={"X-User-Role": "Candidate"})).status_code == 403
    r = await client.post("/kb/upload", files=files, headers=ADMIN)
    assert r.status_code == 200
    doc_id = r.json()["document"]["id"]
    hits = (await client.post("/kb/search", json={"query": "economy class trips"})).json()["results"]
    assert hits[0]["title"] == "travel policy"
    assert (await client.delete(f"/kb/documents/{doc_id}")).status_code == 403
    assert (await client.delete(f"/kb/documents/{doc_id}", headers=ADMIN)).json() == {"success": True}
    assert (await client.post("/kb/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")},
                              headers=ADMIN)).status_code == 415


async def test_chat_policy_question_is_grounded_with_citations(client, fresh_env):
    r = await client.post("/chat", json={"session_id": "s1", "message": "How much annual leave do I get?",
                                         "user_role": "Candidate"})
    body = r.json()
    assert r.status_code == 200
    assert "[1]" in body["response"] and "**Sources**" in body["response"]
    assert body["citations"][0]["n"] == 1 and body["citations"][0]["snippet"]
    rag_call = fresh_env.calls[-1]
    assert "numbered context passages" in rag_call["messages"][0]["content"]
    assert rag_call["model"] == "openai/gpt-oss-120b"            # GROQ_MODEL default


async def test_chat_unknown_topic_says_not_in_kb(client):
    r = await client.post("/chat", json={"session_id": "s2", "message": "What is the leave policy on Mars?"})
    body = r.json()
    assert "couldn't find that in the HR knowledge base" in body["response"] and body["citations"] == []


async def test_multi_step_form_survives_across_requests(client):
    """Form state lives in MongoDB, so each step can be served by a different serverless instance."""
    import bot_logic
    r1 = await client.post("/chat", json={"session_id": "s3", "message": "I want to apply for a job"})
    assert "Which role" in r1.json()["response"]
    bot_logic.sessions.clear()                            # simulate a fresh instance
    r2 = await client.post("/chat", json={"session_id": "s3", "message": "Data Analyst"})
    assert "autofill" in r2.json()["response"]
    r3 = await client.post("/chat", json={"session_id": "s3", "message": "No"})
    assert "Full Name" in r3.json()["response"]


async def test_resume_upload_is_kept_in_mongo_not_disk(client):
    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.write(buf)
    r = await client.post("/upload", files={"file": ("My CV.pdf", buf.getvalue(), "application/pdf")})
    url = r.json()["file_url"]
    assert url.startswith("uploads/") and url.endswith("/My_CV.pdf")
    assert await resume_files_collection.count_documents({}) == 1
    got = await client.get("/" + url)
    assert got.status_code == 200 and got.content.startswith(b"%PDF")


async def test_approve_request_reindexes_jobs(client):
    await client.get("/admin/dashboard")
    res = await hiring_requests_collection.insert_one({
        "role_required": "Prompt Engineer", "department": "Tech", "job_location": "Remote",
        "required_experience": "1-3 yrs", "required_skills": "Python, LLMs", "budget": "12 LPA", "reason": "New team"})
    r = await client.post(f"/admin/requests/{res.inserted_id}/approve")
    assert r.json() == {"success": True}
    hits = (await client.post("/kb/search", json={"query": "prompt engineer LLMs remote"})).json()["results"]
    assert hits[0]["title"] == "Job: Prompt Engineer (Remote)"
    assert (await client.post("/admin/requests/notanid/approve")).status_code == 400


async def test_export_csv(client):
    r = await client.get("/export", params={"type": "hiring_requests"})
    assert r.status_code == 200 and r.text.startswith("Department,Role Required")


async def test_cors_uses_allowed_origins(client):
    r = await client.options("/chat", headers={"Origin": "http://localhost:5173",
                                                "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    r = await client.options("/chat", headers={"Origin": "https://evil.example",
                                                "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers
