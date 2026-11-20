"""Knowledge base in MongoDB: ingest documents (chunk + embed), keep job openings indexed, hybrid search.

kb_documents: {_id, title, source, type: "document"|"job", uploaded_at, chunks, embed_model}
kb_chunks:    {_id, doc_id, title, source, type, section, chunk_index, text, embedding?, embed_model?}
"""
import datetime
import logging
import re

from bson import ObjectId

import config
from database import job_openings_collection, kb_chunks_collection, kb_documents_collection
from rag import embeddings, scoring
from rag.chunking import chunk_text

logger = logging.getLogger(__name__)


async def ingest_text(title: str, text: str, source: str, doc_type: str = "document") -> dict:
    chunks = chunk_text(text, config.RAG_CHUNK_CHARS, config.RAG_CHUNK_OVERLAP)
    if not chunks:
        raise ValueError("no text could be extracted from the document")
    vectors = await embeddings.embed([c.text for c in chunks])
    mid = embeddings.model_id() if vectors else ""
    doc = {"title": title, "source": source, "type": doc_type, "chunks": len(chunks), "embed_model": mid,
           "uploaded_at": datetime.datetime.now(datetime.timezone.utc)}
    res = await kb_documents_collection.insert_one(doc)
    rows = []
    for i, c in enumerate(chunks):
        row = {"doc_id": res.inserted_id, "title": title, "source": source, "type": doc_type,
               "section": c.section, "chunk_index": c.index, "text": c.text}
        if vectors:
            row["embedding"], row["embed_model"] = vectors[i], mid
        rows.append(row)
    await kb_chunks_collection.insert_many(rows)
    doc["_id"] = res.inserted_id
    return serialize_doc(doc)


async def replace_source(title: str, text: str, source: str) -> dict:
    """Re-ingest a document that has a stable source key (the bundled handbook): drop the old copy first."""
    for d in await kb_documents_collection.find({"source": source}).to_list(100):
        await kb_chunks_collection.delete_many({"doc_id": d["_id"]})
    await kb_documents_collection.delete_many({"source": source})
    return await ingest_text(title, text, source)


# Everyday words people use for HR topics, mapped to the words the handbook uses. Only the lexical (BM25) query
# is expanded; a question that already uses the handbook's words is unaffected. Keys are matched as whole words.
SYNONYMS = {
    "days off": "annual leave", "day off": "annual leave", "vacation": "annual leave", "vacations": "annual leave",
    "holiday": "public holidays leave", "holidays": "public holidays", "pto": "annual leave", "leaves": "leave",
    "time off": "leave", "sick": "sick leave medical", "unwell": "sick leave", "ill": "sick leave",
    "baby": "maternity paternity leave", "pregnant": "maternity leave", "father": "paternity leave",
    "quit": "resignation notice period", "resign": "resignation notice period", "resigning": "resignation notice period",
    "leaving": "resignation notice period exit", "serve": "notice period",
    "salary": "salary payroll", "pay": "salary payroll", "paid": "salary payroll credited", "payday": "salary credited payroll",
    "payslip": "payslips payroll", "tax": "income tax payroll", "form 16": "form 16 tax",
    "insurance": "health insurance", "medical": "health insurance medical", "mediclaim": "health insurance",
    "hospital": "health insurance hospitals", "benefits": "benefits insurance allowance",
    "wfh": "work from home", "remote": "work from home remote", "hybrid": "work from home",
    "training": "learning development budget", "course": "learning budget courses", "courses": "learning budget courses",
    "certification": "learning certifications budget", "upskill": "learning development",
    "appraisal": "performance reviews appraisals increments", "increment": "appraisals increments",
    "hike": "appraisals increments", "promotion": "promotions appraisals", "bonus": "bonus",
    "refer": "referral bonus", "referring": "referral bonus", "friend": "referral",
    "expense": "reimbursements expenses", "expenses": "reimbursements", "travel": "travel reimbursements",
    "hotel": "hotel travel", "dress": "dress code", "clothes": "dress code", "laptop": "laptop equipment IT",
    "timing": "working hours", "timings": "working hours", "office hours": "working hours", "shift": "shifts working hours",
    "join": "joining documents", "joining": "joining documents offer", "onboarding": "joining induction",
    "documents": "documents joining", "transfer": "internal job postings transfer", "internal": "internal job postings",
    "harassment": "harassment internal committee", "complaint": "complaints harassment ticket", "contact": "contact HR ticket",
    "ticket": "tickets contact HR portal answered", "tickets": "tickets contact HR portal answered",
    "query": "contact HR ticket", "queries": "contact HR ticket", "reach hr": "contact HR ticket",
    "probation": "probation", "confirmation": "probation confirmation", "hiring process": "interview process",
    "interview": "interview process stages", "selection": "interview process", "offer": "offer letter offers",
}
_SYN_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(SYNONYMS, key=len, reverse=True)) + r")\b", re.I)


def expand_query(query: str) -> str:
    extra = {SYNONYMS[m.group(1).lower()] for m in _SYN_RE.finditer(query)}
    return f"{query} {' '.join(sorted(extra))}" if extra else query


def _lexical_text(c: dict) -> str:
    """What BM25 scores: the section heading counts like the text (questions often name the topic)."""
    sec = c.get("section") or ""
    return f"{sec}. {sec}. {c['text']}" if sec else c["text"]


async def delete_document(doc_id: str) -> bool:
    oid = ObjectId(doc_id)
    res = await kb_documents_collection.delete_one({"_id": oid})
    await kb_chunks_collection.delete_many({"doc_id": oid})
    return res.deleted_count > 0


async def list_documents(include_jobs: bool = False) -> list[dict]:
    query = {} if include_jobs else {"type": {"$ne": "job"}}
    docs = await kb_documents_collection.find(query).sort("uploaded_at", -1).to_list(500)
    return [serialize_doc(d) for d in docs]


def serialize_doc(d: dict) -> dict:
    out = {k: v for k, v in d.items() if k != "_id"}
    out["id"] = str(d["_id"])
    if isinstance(out.get("uploaded_at"), datetime.datetime):
        out["uploaded_at"] = out["uploaded_at"].isoformat()
    return out


def job_text(j: dict) -> str:
    skills = j.get("skills_required") or []
    skills = ", ".join(skills) if isinstance(skills, list) else str(skills)
    parts = [
        f"Job opening: {j.get('title', 'Untitled')}",
        f"Department: {j.get('department', 'N/A')}",
        f"Location: {j.get('location', 'N/A')}",
        f"Experience required: {j.get('experience_required', 'N/A')} years",
        f"Skills required: {skills or 'N/A'}",
    ]
    if j.get("employment_type"):
        parts.append(f"Employment type: {j['employment_type']}")
    if j.get("budget"):
        parts.append(f"Salary: {j['budget']}")
    if j.get("openings"):
        parts.append(f"Openings: {j['openings']}")
    if j.get("apply_by"):
        parts.append(f"Apply by: {j['apply_by']}")
    if j.get("description"):
        parts.append(f"Description: {j['description']}")
    return ". ".join(parts) + "."


async def reindex_jobs() -> int:
    """Rebuild the 'job' entries of the knowledge base from the job_openings collection.
    One chunk per opening (they are short), embedded in batches."""
    await kb_chunks_collection.delete_many({"type": "job"})
    await kb_documents_collection.delete_many({"type": "job"})
    jobs = await job_openings_collection.find({}).to_list(1000)
    if not jobs:
        return 0
    texts = [job_text(j) for j in jobs]
    vectors = await embeddings.embed(texts)
    mid = embeddings.model_id() if vectors else ""
    now = datetime.datetime.now(datetime.timezone.utc)
    docs = [{"title": f"Job: {j.get('title', 'Untitled')} ({j.get('location', 'N/A')})",
             "source": f"job:{j['_id']}", "type": "job", "chunks": 1, "embed_model": mid, "uploaded_at": now}
            for j in jobs]
    res = await kb_documents_collection.insert_many(docs)
    rows = []
    for i, (doc_id, d) in enumerate(zip(res.inserted_ids, docs)):
        row = {"doc_id": doc_id, "title": d["title"], "source": d["source"], "type": "job", "section": "",
               "chunk_index": 0, "text": texts[i]}
        if vectors:
            row["embedding"], row["embed_model"] = vectors[i], mid
        rows.append(row)
    await kb_chunks_collection.insert_many(rows)
    return len(rows)


async def _atlas_vector_scores(qv: list[float], mid: str, limit: int) -> dict:
    pipeline = [
        {"$vectorSearch": {"index": config.ATLAS_VECTOR_INDEX, "path": "embedding", "queryVector": qv,
                           "numCandidates": max(100, limit * 10), "limit": limit,
                           "filter": {"embed_model": mid}}},
        {"$project": {"_id": 1, "score": {"$meta": "vectorSearchScore"}}},
    ]
    rows = await kb_chunks_collection.aggregate(pipeline).to_list(limit)
    # Atlas cosine scores are (1 + cos) / 2; convert back to cosine so both paths use one scale
    return {r["_id"]: 2 * r["score"] - 1 for r in rows}


async def search(query: str, top_k: int | None = None, min_score: float | None = None,
                 doc_type: str | None = None) -> list[dict]:
    top_k = top_k or config.RAG_TOP_K
    min_score = config.RAG_MIN_SCORE if min_score is None else min_score
    flt = {"type": doc_type} if doc_type else {}
    chunks = await kb_chunks_collection.find(flt).to_list(20000)
    if not chunks or not query.strip():
        return []

    bm25 = scoring.BM25([_lexical_text(c) for c in chunks]).scores(expand_query(query))

    vec: dict = {}
    qv = await embeddings.embed([query]) if embeddings.enabled() else None
    if qv:
        mid = embeddings.model_id()
        if config.ATLAS_VECTOR_INDEX:
            try:
                vec = await _atlas_vector_scores(qv[0], mid, top_k * 5)
            except Exception as e:  # noqa: BLE001 - no index / not Atlas: use local cosine
                logger.warning("Atlas $vectorSearch failed (%s); using local cosine", e)
        if not vec:
            with_vec = [c for c in chunks if c.get("embed_model") == mid and c.get("embedding")]
            sims = scoring.cosine_matrix(qv[0], [c["embedding"] for c in with_vec])
            vec = {c["_id"]: s for c, s in zip(with_vec, sims)}

    candidates = []
    for c, lex in zip(chunks, bm25):
        v = vec.get(c["_id"]) if vec else None
        score = scoring.fuse(v, lex, config.RAG_HYBRID_ALPHA)
        candidates.append({
            "chunk_id": str(c["_id"]), "doc_id": str(c["doc_id"]), "title": c.get("title", ""),
            "source": c.get("source", ""), "type": c.get("type", "document"), "section": c.get("section", ""),
            "chunk_index": c.get("chunk_index", 0), "text": c["text"], "score": round(score, 4),
            "vector_score": None if v is None else round(v, 4), "bm25": round(lex, 3),
        })
    return scoring.rank(candidates, top_k, min_score, config.RAG_RELATIVE_CUTOFF)
