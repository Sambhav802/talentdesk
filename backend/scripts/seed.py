"""Seed demo jobs, ingest the sample HR handbook and (re)index job openings into the knowledge base.

    cd backend && python -m scripts.seed            # idempotent
    cd backend && python -m scripts.seed --force    # re-ingest the handbook and re-index jobs
    cd backend && python -m scripts.seed --file policies.pdf   # add any PDF/TXT/MD to the knowledge base
"""
import argparse
import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bootstrap  # noqa: E402
from rag import store  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--file", help="ingest one more document into the knowledge base")
    a = ap.parse_args()
    print(await bootstrap.run(force=a.force))
    if a.file:
        data = open(a.file, "rb").read()
        if a.file.lower().endswith(".pdf"):
            from pypdf import PdfReader
            text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
        else:
            text = data.decode("utf-8", errors="replace")
        title = os.path.splitext(os.path.basename(a.file))[0].replace("_", " ")
        print(await store.ingest_text(title, text, source=os.path.basename(a.file)))


if __name__ == "__main__":
    asyncio.run(main())
