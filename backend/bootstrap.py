"""Idempotent demo setup: seed job openings, ingest the sample handbook and index the jobs into the knowledge
base. Runs lazily on the first request of a cold start (serverless-friendly) and from scripts/seed.py.
A marker document in `meta` makes repeated runs a single cheap lookup."""
import asyncio
import logging

import config
from database import SEED_DIR, kb_documents_collection, meta_collection, seed_jobs
from rag import store

logger = logging.getLogger(__name__)

_done = False
_lock = asyncio.Lock()
HANDBOOK_SOURCE = "seed:handbook.md"


async def run(force: bool = False) -> dict:
    report = {"jobs_seeded": 0, "handbook_ingested": False, "jobs_indexed": None}
    report["jobs_seeded"] = await seed_jobs()
    if force or not await kb_documents_collection.find_one({"source": HANDBOOK_SOURCE}):
        text = (SEED_DIR / "handbook.md").read_text(encoding="utf-8")
        await store.ingest_text("Northwind Labs Employee Handbook (sample)", text, HANDBOOK_SOURCE)
        report["handbook_ingested"] = True
    if force or report["jobs_seeded"] or not await kb_documents_collection.find_one({"type": "job"}):
        report["jobs_indexed"] = await store.reindex_jobs()
    await meta_collection.update_one({"_id": "bootstrap"}, {"$set": {"done": True}}, upsert=True)
    return report


async def ensure() -> None:
    """Called at the start of requests; does real work at most once per database."""
    global _done
    if _done or not config.AUTO_SEED:
        return
    async with _lock:
        if _done:
            return
        try:
            if not await meta_collection.find_one({"_id": "bootstrap", "done": True}):
                logger.info("bootstrap: %s", await run())
            _done = True
        except Exception as e:  # noqa: BLE001 - never block a request on demo seeding
            logger.warning("bootstrap skipped: %s", e)
