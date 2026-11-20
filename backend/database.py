"""MongoDB access.

The client is created lazily and re-created when the running event loop changes: on serverless platforms
(Vercel) an instance can serve requests from a new event loop, and a Motor client is bound to the loop it
was first used on. Collections are module-level proxies, so the rest of the code keeps using
`job_openings_collection.find(...)` etc. Tests swap the client factory with `set_client_factory`.
"""
import asyncio
import json
import logging
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

import config

logger = logging.getLogger(__name__)

_client = None
_client_loop = None


def _default_factory():
    return AsyncIOMotorClient(config.MONGO_URI, serverSelectionTimeoutMS=8000)


_factory = _default_factory


def set_client_factory(factory):
    """Used by tests (e.g. mongomock-motor)."""
    global _factory, _client, _client_loop
    _factory, _client, _client_loop = factory, None, None


def get_db():
    global _client, _client_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _client is None or (loop is not None and loop is not _client_loop):
        _client = _factory()
        _client_loop = loop
    return _client[config.MONGO_DB]


class _Collection:
    """Resolves the real collection on every attribute access (cheap) so the client follows the event loop."""

    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, attr):
        return getattr(get_db()[self._name], attr)


job_openings_collection = _Collection("job_openings")
candidates_collection = _Collection("candidates")
hiring_requests_collection = _Collection("hiring_requests")
chat_history_collection = _Collection("chat_history")
sessions_collection = _Collection("chat_sessions")        # multi-step form state (serverless-safe)
resume_files_collection = _Collection("resume_files")     # uploaded resumes: extracted text + original bytes
kb_documents_collection = _Collection("kb_documents")
kb_chunks_collection = _Collection("kb_chunks")
meta_collection = _Collection("meta")

SEED_DIR = Path(__file__).resolve().parent / "seed"


async def seed_jobs() -> int:
    """Insert the demo job openings only when the collection is empty (never deletes existing jobs)."""
    if await job_openings_collection.count_documents({}) > 0:
        return 0
    jobs = json.loads((SEED_DIR / "jobs.json").read_text(encoding="utf-8"))
    await job_openings_collection.insert_many(jobs)
    logger.info("seeded %d demo job openings", len(jobs))
    return len(jobs)
