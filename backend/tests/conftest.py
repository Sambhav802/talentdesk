"""Test setup: in-memory MongoDB (mongomock-motor), fake Groq, no network. Every test gets a fresh database."""
import os
import re
import sys
from types import SimpleNamespace

import pytest

os.environ["EMBEDDINGS_PROVIDER"] = "none"
os.environ["GROQ_API_KEY"] = ""
os.environ["ATLAS_VECTOR_INDEX"] = ""
os.environ["ALLOWED_ORIGINS"] = "http://localhost:5173"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import bootstrap  # noqa: E402
import database  # noqa: E402
import llm  # noqa: E402


class FakeGroq:
    """Answers like the real model would for each prompt type used by the app."""

    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    @staticmethod
    def _reply(text):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    def create(self, model, messages, **kw):
        self.calls.append({"model": model, "messages": messages, **kw})
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user = messages[-1]["content"]
        if "Classify their message" in user:
            msg = re.search(r'Message: "(.*)"', user).group(1).lower()
            if "leave" in msg or "referral" in msg or "notice period" in msg or "mars" in msg:
                return self._reply("hr_knowledge")
            if "apply" in msg:
                return self._reply("apply_job")
            return self._reply("general_faq")
        if "numbered context passages" in system:
            if "mars" in user.lower():
                return self._reply("NOT_FOUND")
            return self._reply("Employees get 18 days of paid annual leave per year [1].")
        if "Reply STRICTLY with 'ANSWER' or 'QUESTION'" in user:
            return self._reply("ANSWER")
        return self._reply("ok")


@pytest.fixture(autouse=True)
def fresh_env(monkeypatch):
    database.set_client_factory(AsyncMongoMockClient)
    fake = FakeGroq()
    monkeypatch.setattr(llm, "_client", fake)
    bootstrap._done = False
    yield fake
    database.set_client_factory(database._default_factory)
