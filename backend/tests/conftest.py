import os

# Must be set before app modules read settings.
os.environ.update({"MOCK_LLM": "true", "MONGO_URI": "mock://", "JWT_SECRET": "test-secret",
                   "STORAGE_DIR": "/tmp/launchcrew-test-artifacts", "LLM_BACKOFF_BASE_S": "0.01"})

import pytest

from app.config import Settings
from app.llm.client import LLMClient
from app.orchestrator.state import RunContext, RunState
from app.tools.file_writer import LocalStorage

GOOD_CHECKS = [{"id": "overflow", "label": "x", "viewport": "mobile", "passed": True, "severity": "error", "detail": ""}]
BAD_CHECKS = [{"id": "contrast", "label": "x", "viewport": "desktop", "passed": False, "severity": "error", "detail": "bad"}]


def make_settings(**kw) -> Settings:
    base = dict(mock_llm=True, mongo_uri="mock://", jwt_secret="test-secret", storage_dir="/tmp/launchcrew-test-artifacts")
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def make_ctx(tmp_path):
    def _make(idea="A habit tracker for night-shift workers", **settings_kw):
        events: list[tuple[str, dict]] = []

        async def sink(t, d):
            events.append((t, d))

        s = make_settings(storage_dir=str(tmp_path), **settings_kw)
        ctx = RunContext(run_id="run1", settings=s, llm=LLMClient(s), state=RunState(idea=idea),
                         sink=sink, storage=LocalStorage(str(tmp_path)))
        return ctx, events
    return _make
