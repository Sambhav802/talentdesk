"""Thin wrapper around Groq so the client is created lazily (importing the app never needs the key) and the
model name comes from GROQ_MODEL. Tests replace `complete` / `client`."""
from groq import Groq

import config

_client = None


def client():
    global _client
    if _client is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def complete(messages: list[dict], **kwargs) -> str:
    """One chat completion; returns the message text."""
    comp = client().chat.completions.create(model=config.GROQ_MODEL, messages=messages, **kwargs)
    return comp.choices[0].message.content or ""
