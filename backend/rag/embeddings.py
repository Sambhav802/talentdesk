"""Embedding providers behind one function. Any failure (no key, network, quota) returns None so callers
fall back to lexical BM25 retrieval and the app keeps working."""
import asyncio
import logging

import httpx

import config

logger = logging.getLogger(__name__)


def model_id() -> str:
    """Identifier stored with every vector; only vectors with the same id are compared."""
    p = config.EMBEDDINGS_PROVIDER
    if p == "hf" and config.HF_TOKEN:
        return f"hf:{config.HF_EMBED_MODEL}"
    if p == "gemini" and config.GEMINI_API_KEY:
        return f"gemini:{config.GEMINI_EMBED_MODEL}:{config.GEMINI_EMBED_DIM}"
    return ""


def enabled() -> bool:
    return bool(model_id())


async def _post(client: httpx.AsyncClient, url: str, **kw) -> dict | list:
    last = None
    for attempt in range(3):
        try:
            r = await client.post(url, timeout=config.EMBED_TIMEOUT_S, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            last = e
            await asyncio.sleep(0.6 * (attempt + 1))
    raise last


def _mean_pool(item):
    """HF feature-extraction returns one vector per text for sentence-transformers models, but token-level
    vectors for some others: average those."""
    if item and isinstance(item[0], list):
        n = len(item)
        return [sum(col) / n for col in zip(*item)]
    return item


async def _hf(client, texts):
    url = config.HF_EMBED_URL.format(model=config.HF_EMBED_MODEL)
    data = await _post(client, url, headers={"Authorization": f"Bearer {config.HF_TOKEN}"},
                       json={"inputs": texts, "options": {"wait_for_model": True}})
    return [_mean_pool(v) for v in data]


async def _gemini(client, texts):
    model = config.GEMINI_EMBED_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
    body = {"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t}]},
                          "outputDimensionality": config.GEMINI_EMBED_DIM} for t in texts]}
    data = await _post(client, url, headers={"x-goog-api-key": config.GEMINI_API_KEY}, json=body)
    return [e["values"] for e in data["embeddings"]]


async def embed(texts: list[str]) -> list[list[float]] | None:
    """Embed texts in batches. Returns None when embeddings are off or the provider fails."""
    if not texts or not enabled():
        return None
    fn = _hf if config.EMBEDDINGS_PROVIDER == "hf" else _gemini
    out: list[list[float]] = []
    try:
        async with httpx.AsyncClient() as client:
            for i in range(0, len(texts), config.EMBED_BATCH):
                out.extend(await fn(client, texts[i:i + config.EMBED_BATCH]))
    except Exception as e:  # noqa: BLE001 - any provider error means "use BM25"
        logger.warning("embeddings unavailable (%s): falling back to BM25", e)
        return None
    if len(out) != len(texts):
        logger.warning("embeddings returned %d vectors for %d texts: ignoring", len(out), len(texts))
        return None
    return out
