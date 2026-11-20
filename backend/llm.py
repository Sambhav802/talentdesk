"""Thin wrapper around Groq so the client is created lazily (importing the app never needs the key) and the
model name comes from config. Tests replace `complete` / `client`.

Token usage of every call in a chat turn is collected in a context variable (`start_turn` / `turn_usage`), so the
chat endpoint can log and store it per turn."""
import contextvars
import logging

from groq import Groq

import config

logger = logging.getLogger(__name__)
_client = None
_usage = contextvars.ContextVar("turn_usage", default=None)


def client():
    global _client
    if _client is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def start_turn() -> None:
    _usage.set([])


def turn_usage() -> list[dict]:
    return list(_usage.get() or [])


def record(comp, model: str, purpose: str) -> None:
    """Keep the token counts of one completion (no-op when the response carries no usage, e.g. in tests)."""
    u = getattr(comp, "usage", None)
    row = {"model": model, "purpose": purpose,
           "prompt_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
           "completion_tokens": int(getattr(u, "completion_tokens", 0) or 0)}
    bucket = _usage.get()
    if bucket is not None:
        bucket.append(row)
    if u is not None:
        logger.info("llm usage %s", row)


def create(purpose: str = "chat", model: str | None = None, **kwargs):
    model = model or config.GROQ_MODEL
    if purpose in ("phrase", "classify") and model.startswith("openai/gpt-oss"):
        kwargs.setdefault("reasoning_effort", "low")      # short rewrites need little thinking: fewer tokens
    comp = client().chat.completions.create(model=model, **kwargs)
    record(comp, model, purpose)
    return comp


def complete(messages: list[dict], purpose: str = "answer", model: str | None = None, **kwargs) -> str:
    """One chat completion; returns the message text."""
    comp = create(purpose=purpose, model=model, messages=messages, **kwargs)
    return comp.choices[0].message.content or ""
