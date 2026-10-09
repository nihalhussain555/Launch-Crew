"""Workspace publishing, version bookkeeping and conversational routing."""
import asyncio

import pytest

from app.config import Settings
from app.orchestrator import artifacts
from app.orchestrator.graph import infer_target
from app.orchestrator.state import RunContext, RunState
from app.tools.file_writer import LocalStorage

HTML = ('<!DOCTYPE html><html lang="en"><head><title>T</title><style>body{margin:0}</style></head>'
        '<body><h1>Hi</h1><script>console.log(1);</script></body></html>')


class MemoryStorage(LocalStorage):
    """LocalStorage semantics without touching the disk."""

    def __init__(self):
        self.blobs = {}

    async def save(self, run_id, name, data):
        self.blobs[f"{run_id}/{name}"] = data
        return f"{run_id}/{name}"

    async def load(self, key):
        return self.blobs[key]

    async def delete(self, key):
        self.blobs.pop(key, None)


def make_ctx():
    async def sink(type_, data):
        pass

    state = RunState(idea="A tiny CRM for solo founders")
    state.html = HTML
    state.html_version = 1
    state.check_summary = {"errors": 0, "warnings": 2}
    return RunContext(run_id="run1", settings=Settings(_env_file=None), llm=None, state=state,
                      sink=sink, storage=MemoryStorage())


def run(coro):
    return asyncio.run(coro)


def test_publish_writes_the_file_set():
    c = make_ctx()
    files = run(artifacts.publish(c))
    assert [f["name"] for f in files] == ["index.html", "styles.css", "app.js", "README.md"]
    assert c.state.files == files
    assert all(f["key"] in c.storage.blobs for f in files)


def test_publish_snapshots_the_version():
    c = make_ctx()
    run(artifacts.publish(c, note="Initial build"))
    v = c.state.versions[-1]
    assert v["v"] == 1 and v["note"] == "Initial build"
    assert run(artifacts.load(c, 1)) == HTML


def test_state_note_is_used_then_cleared():
    c = make_ctx()
    c.state.note = "copy: sharper headline"
    run(artifacts.publish(c))
    assert c.state.versions[-1]["note"] == "copy: sharper headline"
    assert c.state.note == ""


def test_each_build_adds_its_own_snapshot():
    c = make_ctx()
    run(artifacts.publish(c))
    c.state.html_version = 2
    c.state.html = HTML.replace("Hi", "Hello")
    run(artifacts.publish(c))
    assert [v["v"] for v in c.state.versions] == [1, 2]
    assert run(artifacts.load(c, 2)).count("Hello") == 1
    assert run(artifacts.file_text(c, "styles.css")) == "body{margin:0}\n"   # assets end with a newline


def test_version_history_is_capped_and_old_blobs_dropped():
    c = make_ctx()
    for v in range(1, artifacts.KEEP_VERSIONS + 6):
        c.state.html_version = v
        run(artifacts.publish(c))
    assert len(c.state.versions) == artifacts.KEEP_VERSIONS
    assert c.state.versions[0]["v"] == 6
    assert "run1/history/v5.html" not in c.storage.blobs         # dropped with the cap
    assert f"run1/history/v{artifacts.KEEP_VERSIONS + 5}.html" in c.storage.blobs


def test_annotate_scores_the_newest_snapshot():
    c = make_ctx()
    run(artifacts.publish(c))
    c.state.readiness = {"total": 92}
    c.state.check_summary = {"errors": 1, "warnings": 0}
    run(artifacts.annotate(c))
    assert c.state.versions[-1]["readiness"] == 92
    assert c.state.versions[-1]["errors"] == 1


def test_annotate_ignores_versions_that_were_never_published():
    c = make_ctx()
    run(artifacts.publish(c))
    c.state.html_version = 5
    c.state.readiness = {"total": 70}
    run(artifacts.annotate(c))
    assert c.state.versions[-1]["v"] == 1 and c.state.versions[-1]["readiness"] is None


def test_publish_without_a_page_is_a_noop():
    c = make_ctx()
    c.state.html = None
    assert run(artifacts.publish(c)) == []


def test_load_unknown_version_raises():
    c = make_ctx()
    run(artifacts.publish(c))
    with pytest.raises(KeyError):
        run(artifacts.load(c, 99))


def test_file_text_rejects_unknown_names():
    c = make_ctx()
    run(artifacts.publish(c))
    with pytest.raises(KeyError):
        run(artifacts.file_text(c, "../../etc/passwd"))


@pytest.mark.parametrize("text,target", [
    ("Make the headline punchier", "copy"),
    ("try a warmer colour and a different font", "design"),
    ("add a pricing table", "copy"),
    ("add more spacing between the sections", "design"),
    ("", "page"),
    ("ship it", "page"),
])
def test_conversational_requests_route_to_the_right_agent(text, target):
    assert infer_target(text) == target
