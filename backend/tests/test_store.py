import hashlib
from pathlib import Path

import pytest

from database import job_openings_collection, kb_chunks_collection, kb_documents_collection
from rag import embeddings, scoring, store

HANDBOOK = (Path(__file__).resolve().parents[1] / "seed" / "handbook.md").read_text(encoding="utf-8")


def fake_vec(text: str, dim: int = 64) -> list[float]:
    """Hashed bag of words: a deterministic stand-in for a real embedding model."""
    v = [0.0] * dim
    for t in scoring.tokenize(text):
        v[int(hashlib.md5(t.encode()).hexdigest(), 16) % dim] += 1.0
    return v


@pytest.fixture
def fake_embeddings(monkeypatch):
    async def embed(texts):
        return [fake_vec(t) for t in texts]
    monkeypatch.setattr(embeddings, "embed", embed)
    monkeypatch.setattr(embeddings, "enabled", lambda: True)
    monkeypatch.setattr(embeddings, "model_id", lambda: "fake:hash64")


async def test_ingest_and_lexical_search():
    doc = await store.ingest_text("Handbook", HANDBOOK, "handbook.md")
    assert doc["chunks"] > 5 and doc["embed_model"] == ""
    assert await kb_chunks_collection.count_documents({}) == doc["chunks"]
    hits = await store.search("How many days of annual leave do employees get?")
    assert hits and hits[0]["section"] == "Leave policy"
    assert hits[0]["vector_score"] is None and hits[0]["score"] > 0.2
    assert len(hits) <= 4


async def test_irrelevant_query_returns_nothing():
    await store.ingest_text("Handbook", HANDBOOK, "handbook.md")
    assert await store.search("quantum chromodynamics lattice") == []


async def test_vector_path_and_hybrid(fake_embeddings):
    await store.ingest_text("Handbook", HANDBOOK, "handbook.md")
    chunk = await kb_chunks_collection.find_one({})
    assert chunk["embed_model"] == "fake:hash64" and len(chunk["embedding"]) == 64
    hits = await store.search("referral bonus amount")
    assert hits[0]["section"] == "Employee referral bonus"
    assert hits[0]["vector_score"] is not None
    assert hits[0]["score"] == pytest.approx(scoring.fuse(hits[0]["vector_score"], hits[0]["bm25"], 0.6), abs=1e-3)


async def test_embedding_failure_falls_back_to_bm25(monkeypatch):
    async def broken(texts):
        return None
    monkeypatch.setattr(embeddings, "embed", broken)
    monkeypatch.setattr(embeddings, "enabled", lambda: True)
    monkeypatch.setattr(embeddings, "model_id", lambda: "fake:broken")
    await store.ingest_text("Handbook", HANDBOOK, "handbook.md")
    hits = await store.search("notice period after confirmation")
    assert hits and hits[0]["section"] == "Notice period"


async def test_reindex_jobs_and_job_search():
    await job_openings_collection.insert_many([
        {"title": "Data Analyst", "department": "Tech", "location": "Bengaluru", "experience_required": 1.5,
         "skills_required": ["Excel", "SQL", "Tableau"], "description": "Analyse business data."},
        {"title": "Recruiter", "department": "HR", "location": "Noida", "experience_required": 2,
         "skills_required": ["Sourcing"], "description": "Hire great people."},
    ])
    assert await store.reindex_jobs() == 2
    assert await store.reindex_jobs() == 2                       # idempotent, no duplicates
    assert await kb_documents_collection.count_documents({"type": "job"}) == 2
    hits = await store.search("Tableau SQL analyst job", doc_type="job")
    assert hits[0]["title"] == "Job: Data Analyst (Bengaluru)"


async def test_delete_document_removes_chunks():
    doc = await store.ingest_text("Handbook", HANDBOOK, "handbook.md")
    assert await store.delete_document(doc["id"]) is True
    assert await kb_chunks_collection.count_documents({}) == 0
    assert await store.list_documents() == []
