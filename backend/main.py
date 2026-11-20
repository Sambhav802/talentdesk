import csv
import datetime
import io
import logging
import re
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import bootstrap
import config
from bot_logic import process_message
from database import (candidates_collection, chat_history_collection, hiring_requests_collection,
                      job_openings_collection, resume_files_collection)
from rag import store as kb

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="HR Chatbot API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def lazy_bootstrap(request: Request, call_next):
    """Seed demo data and the knowledge base on the first request of a cold start (no long-running server)."""
    if request.method != "OPTIONS" and request.url.path not in ("/", "/health"):
        await bootstrap.ensure()
    return await call_next(request)


def _oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="invalid id")


def require_hr_admin(x_user_role: Optional[str] = Header(default=None)):
    """The app has no real authentication: roles are chosen in the UI (see README). Knowledge-base writes
    are limited to requests that declare the HR Admin role, the same trust model as the chat endpoint."""
    if (x_user_role or "").strip().lower() != "hr admin":
        raise HTTPException(status_code=403, detail="HR Admin role required")


@app.get("/")
async def root():
    return {"status": "HR Chatbot API is running", "version": "2.0.0",
            "rag": {"embeddings": config.EMBEDDINGS_PROVIDER, "atlas_vector_search": bool(config.ATLAS_VECTOR_INDEX)}}


@app.get("/health")
async def health():
    return {"ok": True}


class ChatRequest(BaseModel):
    session_id: str
    message: str
    user_role: Optional[str] = "Candidate"


class LoginRequest(BaseModel):
    email: str
    phone: str
    role: str


class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = None
    min_score: Optional[float] = None


# --- UNIVERSAL ROLE LOGIN ---
@app.post("/login")
async def universal_login(request: LoginRequest):
    email = request.email.strip()
    past_sessions = await chat_history_collection.find({
        "role": "user",
        "message": email,
        "user_role": request.role
    }).to_list(length=20)

    history = []
    last_session_id = None
    if past_sessions:
        past_sessions.sort(key=lambda x: x["timestamp"], reverse=True)
        last_session_id = past_sessions[0]["session_id"]
        chats = await chat_history_collection.find({"session_id": last_session_id}).sort("timestamp", 1).to_list(length=100)
        for c in chats:
            history.append({"role": c["role"], "text": c["message"], "citations": c.get("citations", [])})
    return {"success": True, "session_id": last_session_id, "history": history}


# --- REAL-TIME NOTIFICATIONS ---
@app.get("/notifications")
async def get_notifications(role: str, email: Optional[str] = None):
    notifications = []
    if role == "Candidate" and email:
        apps = await candidates_collection.find({"email": email}).to_list(100)
        for app_data in apps:
            role_name = app_data.get("preferred_role", "Unknown Role")
            status = app_data.get("screening_status", "Pending Review")
            email_summary = f"""
**📧 EMAIL NOTIFICATION**
━━━━━━━━━━━━━━━━━━━━━━
**To:** {app_data.get('full_name')} ({email})
**From:** HR Team <hr-team@company.com>
**Subject:** Update on your application for {role_name}

Dear {app_data.get('full_name')},

We are writing to inform you that your application status for the **{role_name}** position has been updated.

**Current Status:** {status}

Thank you for your interest!
**HR Admin Team**
            """
            notifications.append({"text": f"Status for {role_name}: {status}", "details": email_summary.strip()})

    elif role == "HR Admin":
        shortlisted = await candidates_collection.count_documents({"screening_status": "Shortlisted for next step"})
        if shortlisted:
            notifications.append({"text": f"🎉 {shortlisted} candidate(s) Shortlisted!",
                                  "details": "🌟 Shortlisted candidates updated."})
        reqs = await hiring_requests_collection.count_documents({})
        if reqs:
            notifications.append({"text": f"📝 {reqs} new Hiring Request(s) pending.",
                                  "details": "Check dashboard for details."})
    return {"notifications": notifications}


# --- ADMIN DASHBOARD ---
def _serialize(docs):
    for doc in docs or []:
        doc["_id"] = str(doc["_id"])
    return docs or []


@app.get("/admin/dashboard")
async def get_admin_dashboard():
    try:
        stats = {
            "total": await candidates_collection.count_documents({}),
            "hired": await candidates_collection.count_documents({"screening_status": {"$regex": "Hired", "$options": "i"}}),
            "rejected": await candidates_collection.count_documents(
                {"screening_status": {"$regex": "Reject|Not suitable|Missing", "$options": "i"}}),
            "pending": await candidates_collection.count_documents(
                {"screening_status": {"$regex": "Pending|Awaiting", "$options": "i"}}),
        }
        jobs = await job_openings_collection.find({}).sort("_id", -1).to_list(100)
        candidates = await candidates_collection.find({}).sort("_id", -1).to_list(100)
        requests = await hiring_requests_collection.find({}).sort("_id", -1).to_list(100)
        return {"stats": stats, "jobs": _serialize(jobs), "candidates": _serialize(candidates),
                "requests": _serialize(requests)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/admin/jobs/{job_id}")
async def delete_job(job_id: str):
    res = await job_openings_collection.delete_one({"_id": _oid(job_id)})
    if res.deleted_count:
        await _reindex_quietly()
    return {"success": bool(res.deleted_count)}


@app.post("/admin/requests/{req_id}/approve")
async def approve_request(req_id: str):
    req = await hiring_requests_collection.find_one({"_id": _oid(req_id)})
    if not req:
        return JSONResponse({"success": False, "error": "Request not found"}, status_code=404)
    new_job = {
        "title": req.get("role_required"),
        "department": req.get("department"),
        "location": req.get("job_location", "Any"),
        "experience_required": req.get("required_experience", "0"),
        "skills_required": [s.strip() for s in str(req.get("required_skills", "")).split(",") if s.strip()],
        "budget": req.get("budget", "Not specified"),
        "description": req.get("reason", "New opening approved by HR."),
    }
    await job_openings_collection.insert_one(new_job)
    await hiring_requests_collection.delete_one({"_id": req["_id"]})
    await _reindex_quietly()
    return {"success": True}


@app.put("/admin/candidates/{cand_id}/status")
async def update_candidate_status(cand_id: str, status: str):
    res = await candidates_collection.update_one({"_id": _oid(cand_id)}, {"$set": {"screening_status": status}})
    return {"success": bool(res.matched_count)}


@app.post("/admin/bootstrap", dependencies=[Depends(require_hr_admin)])
async def run_bootstrap(force: bool = False):
    """Seed demo jobs, ingest the sample handbook and index jobs (idempotent; force re-ingests)."""
    return await bootstrap.run(force=force)


async def _reindex_quietly():
    try:
        await kb.reindex_jobs()
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("job re-index failed: %s", e)


# --- CHAT ---
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        await chat_history_collection.insert_one({
            "session_id": request.session_id, "role": "user", "user_role": request.user_role,
            "message": request.message, "timestamp": now,
        })
        result = await process_message(request.session_id, request.message, request.user_role)
        if isinstance(result, dict):
            text, citations = result.get("text", ""), result.get("citations", [])
        else:
            text, citations = str(result), []
        await chat_history_collection.insert_one({
            "session_id": request.session_id, "role": "bot", "user_role": request.user_role,
            "message": text, "citations": citations,
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
        })
        return {"response": text, "citations": citations}
    except Exception as e:
        logging.getLogger(__name__).exception("chat failed")
        return JSONResponse({"response": f"Chat Error: {e}", "citations": []}, status_code=500)


# --- RESUME UPLOAD (in memory; nothing is written to disk) ---
def _safe_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "resume").strip())[:80].strip("._")
    return base or "resume"


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    return "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"file larger than {config.MAX_UPLOAD_MB:g} MB")
    name = _safe_name(file.filename)
    text = ""
    if name.lower().endswith(".pdf"):
        try:
            text = _pdf_text(data)
        except Exception:  # noqa: BLE001 - unreadable PDF: the chat falls back to the manual form
            text = ""
    res = await resume_files_collection.insert_one({
        "filename": name, "content_type": file.content_type or "application/octet-stream",
        "size": len(data), "text": text, "data": data,
        "uploaded_at": datetime.datetime.now(datetime.timezone.utc),
    })
    return {"file_url": f"uploads/{res.inserted_id}/{name}"}


@app.get("/uploads/{file_id}/{name}")
async def download_upload(file_id: str, name: str):
    doc = await resume_files_collection.find_one({"_id": _oid(file_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="file not found")
    return Response(content=bytes(doc["data"]), media_type=doc.get("content_type", "application/octet-stream"),
                    headers={"Content-Disposition": f'inline; filename="{doc["filename"]}"'})


# --- KNOWLEDGE BASE (RAG) ---
KB_TYPES = {".pdf": "pdf", ".txt": "text", ".md": "markdown", ".markdown": "markdown"}


@app.post("/kb/upload", dependencies=[Depends(require_hr_admin)])
async def kb_upload(file: UploadFile = File(...)):
    name = _safe_name(file.filename)
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in KB_TYPES:
        raise HTTPException(status_code=415, detail="upload a PDF, TXT or Markdown file")
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"file larger than {config.MAX_UPLOAD_MB:g} MB")
    try:
        text = _pdf_text(data) if ext == ".pdf" else data.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(status_code=422, detail="could not read the file")
    title = re.sub(r"[_-]+", " ", name.rsplit(".", 1)[0]).strip() or name
    try:
        doc = await kb.ingest_text(title, text, source=name, doc_type=KB_TYPES[ext])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"success": True, "document": doc}


@app.get("/kb/documents")
async def kb_documents(include_jobs: bool = False):
    return {"documents": await kb.list_documents(include_jobs)}


@app.delete("/kb/documents/{doc_id}", dependencies=[Depends(require_hr_admin)])
async def kb_delete(doc_id: str):
    _oid(doc_id)
    return {"success": await kb.delete_document(doc_id)}


@app.post("/kb/search")
async def kb_search(req: SearchRequest):
    hits = await kb.search(req.query, top_k=req.top_k, min_score=req.min_score)
    return {"query": req.query, "embeddings": config.EMBEDDINGS_PROVIDER, "results": hits}


@app.post("/kb/reindex-jobs", dependencies=[Depends(require_hr_admin)])
async def kb_reindex_jobs():
    return {"indexed": await kb.reindex_jobs()}


# --- CSV EXPORT ---
@app.get("/export")
async def export_data(type: str = "all_candidates"):
    output = io.StringIO()
    writer = csv.writer(output)
    if type == "hiring_requests":
        reqs = await hiring_requests_collection.find({}).to_list(1000)
        writer.writerow(["Department", "Role Required", "Positions", "Experience", "Skills", "Location", "Budget", "Urgency", "Manager"])
        for r in reqs:
            writer.writerow([r.get("department", ""), r.get("role_required", ""), r.get("positions", ""),
                             r.get("required_experience", ""), r.get("required_skills", ""), r.get("job_location", ""),
                             r.get("budget", ""), r.get("urgency", ""), r.get("reporting_manager", "")])
    else:
        query = {}
        if type == "hired":
            query = {"screening_status": {"$regex": "Hired", "$options": "i"}}
        elif type == "rejected":
            query = {"screening_status": {"$regex": "Reject|Not suitable|Missing", "$options": "i"}}
        elif type == "shortlisted":
            query = {"screening_status": {"$regex": "Shortlisted", "$options": "i"}}
        elif type == "interview_done":
            query = {"screening_status": {"$regex": "Interview Done", "$options": "i"}}
        elif type == "pending":
            query = {"screening_status": {"$regex": "Pending|Awaiting", "$options": "i"}}
        candidates = await candidates_collection.find(query).to_list(1000)
        writer.writerow(["Name", "Email", "Phone", "Role Applied", "Experience (Yrs)", "Skills", "Expected CTC", "Status"])
        for c in candidates:
            writer.writerow([c.get("full_name", ""), c.get("email", ""), c.get("phone", ""), c.get("preferred_role", ""),
                             c.get("total_experience", ""), c.get("skills", ""), c.get("expected_ctc", ""),
                             c.get("screening_status", "")])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=export_{type}.csv"})


@app.get("/export/candidates")
async def export_candidates_fallback():
    return await export_data(type="all_candidates")
