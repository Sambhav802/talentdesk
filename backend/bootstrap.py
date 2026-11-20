"""Idempotent setup: seed job openings, ingest the employee handbook and index the jobs into the knowledge base.
Runs lazily on the first request of a cold start (serverless-friendly) and from scripts/seed.py.

A marker document in `meta` makes repeated runs a single cheap lookup. SEED_VERSION is bumped whenever the
bundled handbook or job list changes, so an existing database picks up the new content on the next cold start
(the handbook is replaced, missing jobs are added, the job index is rebuilt)."""
import asyncio
import logging

import config
from database import SEED_DIR, kb_documents_collection, meta_collection, seed_jobs
from rag import store

logger = logging.getLogger(__name__)

SEED_VERSION = 3
HANDBOOK_SOURCE = "seed:handbook.md"
HANDBOOK_TITLE = "Northwind Labs Employee Handbook"

_done = False
_lock = asyncio.Lock()


async def run(force: bool = False) -> dict:
    report = {"jobs_seeded": 0, "handbook_ingested": False, "jobs_indexed": None, "seed_version": SEED_VERSION}
    marker = await meta_collection.find_one({"_id": "bootstrap"}) or {}
    outdated = marker.get("version", 1) < SEED_VERSION
    report["jobs_seeded"] = await seed_jobs()
    if force or outdated or not await kb_documents_collection.find_one({"source": HANDBOOK_SOURCE}):
        text = (SEED_DIR / "handbook.md").read_text(encoding="utf-8")
        await store.replace_source(HANDBOOK_TITLE, text, HANDBOOK_SOURCE)
        report["handbook_ingested"] = True
    if force or outdated or report["jobs_seeded"] or not await kb_documents_collection.find_one({"type": "job"}):
        report["jobs_indexed"] = await store.reindex_jobs()
    await meta_collection.update_one({"_id": "bootstrap"}, {"$set": {"done": True, "version": SEED_VERSION}},
                                     upsert=True)
    return report


async def ensure() -> None:
    """Called at the start of requests; does real work at most once per database and seed version."""
    global _done
    if _done or not config.AUTO_SEED:
        return
    async with _lock:
        if _done:
            return
        try:
            marker = await meta_collection.find_one({"_id": "bootstrap"}) or {}
            if not marker.get("done") or marker.get("version", 1) < SEED_VERSION:
                logger.info("bootstrap: %s", await run())
            _done = True
        except Exception as e:  # noqa: BLE001 - never block a request on seeding
            logger.warning("bootstrap skipped: %s", e)
