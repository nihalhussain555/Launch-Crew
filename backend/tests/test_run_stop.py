"""Stopping a run that is building: the flag, the in-process interrupt, and what each phase keeps.

A Stop is the user's decision, so these tests are mostly about what must *survive* it: the page version the
crew had already published, the run's place at the approval gate, the tokens it spent, and the ability to
revise or approve afterwards. Nothing here asserts that a stop looks like a failure.
"""
import asyncio
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.api import routes_runs
from app.db.mongo import create_client
from app.llm.client import LLMClient
from app.main import app
from app.orchestrator import cancel, runner
from app.orchestrator.graph import Orchestrator
from app.orchestrator.state import RunCancelled
from app.tools import browser_checks
from app.tools.file_writer import LocalStorage
from tests.conftest import GOOD_CHECKS, make_settings
from tests.test_orchestrator import patch_checks


# ---------------------------------------------------------------- fakes and fixtures
def event_types(events) -> list[str]:
    return [t for t, _ in events]


async def read_events(db, run_id: str):
    return [(e["type"], e["data"]) async for e in db.run_events.find({"run_id": run_id}).sort("seq", 1)]


@pytest.fixture
def state(tmp_path):
    """The pieces every pipeline call takes, on a fresh in-memory database and artifact store."""
    settings = make_settings(storage_dir=str(tmp_path))
    return SimpleNamespace(settings=settings, db=create_client(settings)[settings.mongo_db],
                           llm=LLMClient(settings), storage=LocalStorage(str(tmp_path)))


async def queue_run(app_state, idea="A habit tracker for night-shift workers") -> str:
    """The run document POST /projects/{id}/runs writes, so a pipeline can be driven straight from it."""
    doc = {"project_id": "project-1", "user_id": "user-1", "idea": idea, "spec": {}, "status": "queued",
           "state": {}, "tokens_used": 0, "steps": 0, "event_seq": 0, "error": None,
           "created_at": runner.now(), "updated_at": runner.now()}
    doc["_id"] = (await app_state.db.runs.insert_one(doc)).inserted_id
    return str(doc["_id"])


async def status_of(app_state, run_id: str) -> dict:
    return await app_state.db.runs.find_one({"_id": ObjectId(run_id)})


def stop_at_checks(monkeypatch, db, run_id: str, *, after: int = 1):
    """Ask for the stop from inside the browser checks: the step in flight finishes, the next boundary sees it."""
    calls = {"n": 0}

    async def fake(html):
        calls["n"] += 1
        if calls["n"] == after:
            await db.runs.update_one({"_id": ObjectId(run_id)}, {"$set": {"cancel_requested": True}})
        return GOOD_CHECKS, {"desktop": b"d", "mobile": b"m"}

    monkeypatch.setattr(browser_checks, "run_checks", fake)
    return calls


async def delayed(event, seconds: float):
    await asyncio.sleep(seconds)
    event.set()


@pytest.fixture
def client(monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gate_run(client):
    """A real run that reached the approval gate, as the API sees it."""
    r = client.post("/api/auth/register", json={"email": "stop@example.com", "password": "supersecret1", "name": "Stop"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A tiny CRM for solo founders"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    run = client.get(f"/api/runs/{rid}", headers=h).json()
    assert run["status"] == "awaiting_approval"
    return client, h, rid


# ---------------------------------------------------------------- the endpoint
def test_stop_is_refused_while_nothing_is_building(gate_run):
    """At the gate there is no build to stop; saying so beats pretending the button did something."""
    client, h, rid = gate_run
    res = client.post(f"/api/runs/{rid}/stop", headers=h)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "awaiting_approval" in detail and "revised" in detail
    assert client.get(f"/api/runs/{rid}", headers=h).json()["status"] == "awaiting_approval"


def test_stop_needs_a_login(gate_run):
    client, _, rid = gate_run
    assert client.post(f"/api/runs/{rid}/stop").status_code == 401


def test_another_users_run_cannot_be_stopped(client, gate_run):
    _, _, rid = gate_run
    other = client.post("/api/auth/register",
                        json={"email": "other@example.com", "password": "supersecret2", "name": "Other"})
    h2 = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.post(f"/api/runs/{rid}/stop", headers=h2).status_code == 404


async def test_pressing_stop_marks_the_run_and_records_it_on_the_stream(state):
    """The flag and the event are the whole promise of the endpoint: what it reached is said in its own words."""
    rid = await queue_run(state)
    await state.db.runs.update_one({"_id": ObjectId(rid)}, {"$set": {"status": "running"}})
    user = {"_id": "user-1"}

    out = await routes_runs.stop(rid, db=state.db, user=user)
    assert out["requested"] is True and out["already"] is False
    assert out["interrupts_now"] is False                       # no pipeline of this worker's to cut into
    assert "next agent boundary" in out["message"]
    assert out["run"].stop_requested is True
    assert (await status_of(state, rid))["cancel_requested"] is True

    events = await read_events(state.db, rid)
    assert event_types(events) == ["stop_requested"]
    assert "boundary" in events[0][1]["message"]

    again = await routes_runs.stop(rid, db=state.db, user=user)
    assert again["already"] is True
    assert "already requested" in (await read_events(state.db, rid))[-1][1]["message"]


async def test_a_queued_run_can_be_stopped_before_its_first_step(state):
    """A run waiting for a worker is still a build the user asked to end, and the flag is how it learns."""
    rid = await queue_run(state)
    out = await routes_runs.stop(rid, db=state.db, user={"_id": "user-1"})
    assert out["requested"] is True and out["interrupts_now"] is False
    assert (await status_of(state, rid))["cancel_requested"] is True


# ---------------------------------------------------------------- the orchestrator
async def test_a_stop_at_a_boundary_is_not_charged_for_the_step_it_prevented(make_ctx):
    ctx, events = make_ctx()
    asked = {"n": 0}

    async def probe():
        asked["n"] += 1
        return asked["n"] > 3              # the crew gets three steps in, then the stop is seen

    ctx.cancel_probe = probe
    with pytest.raises(RunCancelled):
        await Orchestrator(ctx).run_until_approval()
    assert ctx.steps == 3 and event_types(events).count("agent_started") == 3


async def test_a_stop_before_the_first_step_leaves_the_build_untouched(make_ctx):
    ctx, events = make_ctx()

    async def always():
        return True

    ctx.cancel_probe = always
    with pytest.raises(RunCancelled):
        await Orchestrator(ctx).run_until_approval()
    assert events == [] and ctx.steps == 0 and ctx.state.html_version == 0


async def test_a_stop_while_a_step_is_waiting_for_the_model_abandons_that_step(make_ctx):
    """The fast path: the build is this process's, so the call in flight is cut rather than finished."""
    ctx, events = make_ctx()
    ctx.cancel_event = cancel.arm("run1")

    class SlowAgent:
        name = "engineer"

        async def run(self, ctx):
            await asyncio.sleep(30)
            return "never returned"

    try:
        stopper = asyncio.ensure_future(delayed(ctx.cancel_event, 0.05))
        with pytest.raises(RunCancelled) as ei:
            await Orchestrator(ctx)._run(SlowAgent())
        await stopper
    finally:
        cancel.disarm("run1")

    assert ei.value.agent == "engineer"
    assert "while engineer was working" in str(ei.value)
    assert event_types(events) == ["agent_started"]          # the abandoned step reported nothing else
    assert ctx.state.html is None


async def test_a_page_that_was_published_survives_the_stop(make_ctx, monkeypatch):
    """Checks run after the page exists, so a stop asked for there keeps v1 instead of throwing it away."""
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    ctx.cancel_probe = lambda: _after_page(ctx)

    with pytest.raises(RunCancelled):
        await Orchestrator(ctx).run_until_approval()

    assert ctx.state.html_version == 1 and ctx.state.html_key
    assert event_types(events)[-1] != "deployed"


async def _after_page(ctx) -> bool:
    return ctx.state.html_version > 0


# ---------------------------------------------------------------- the pipeline, end to end
async def test_a_stopped_build_returns_to_the_gate_with_its_page(state, monkeypatch):
    calls = stop_at_checks(monkeypatch, state.db, rid := await queue_run(state))
    await runner.run_pipeline(state, rid)

    doc = await status_of(state, rid)
    assert calls["n"] == 1                                   # it stopped at the boundary, not mid-check
    assert doc["status"] == "awaiting_approval" and doc["error"] is None
    assert doc["state"]["html_version"] == 1 and doc["steps"] >= 5
    assert doc["cancel_requested"] is False                  # the stop is spent, not left hanging

    events = await read_events(state.db, rid)
    last_type, last = events[-1]
    assert last_type == "stopped"
    assert last["status"] == "awaiting_approval" and last["html_version"] == 1
    # A boundary stop names no agent in flight - the message says which step it stopped short of instead.
    assert last["agent"] == "" and "before panel could start" in last["message"]
    assert "Page v1 is kept" in last["message"] and "failed" not in event_types(events)


async def test_a_stopped_build_with_no_page_ends_cancelled_not_failed(state):
    rid = await queue_run(state)
    await state.db.runs.update_one({"_id": ObjectId(rid)}, {"$set": {"cancel_requested": True}})
    await runner.run_pipeline(state, rid)

    doc = await status_of(state, rid)
    assert doc["status"] == "cancelled" and doc["error"] is None and doc["state"]["html_version"] == 0
    events = await read_events(state.db, rid)
    assert event_types(events)[-1] == "stopped"
    assert events[-1][1]["status"] == "cancelled" and "ends cancelled" in events[-1][1]["message"]
    assert "failed" not in event_types(events)


async def test_a_run_nobody_stopped_still_finishes_its_build(state, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    rid = await queue_run(state)
    await runner.run_pipeline(state, rid)

    doc = await status_of(state, rid)
    assert doc["status"] == "awaiting_approval" and doc["state"]["html_version"] == 1
    assert "stopped" not in event_types(await read_events(state.db, rid))


async def test_a_stopped_run_can_still_be_revised_and_approved(state, monkeypatch):
    """The gate a stop returns to is a real gate: the follow-up phases must not inherit the old stop."""
    stop_at_checks(monkeypatch, state.db, rid := await queue_run(state))
    await runner.run_pipeline(state, rid)
    await state.db.runs.update_one({"_id": ObjectId(rid)}, {"$set": {"cancel_requested": True}})

    assert await runner.claim_for_revision(state.db, rid, "user-1") is True
    assert (await status_of(state, rid))["cancel_requested"] is False


async def test_a_stop_in_a_revision_keeps_the_version_that_revision_reached(state, monkeypatch):
    """A Stop pressed during a revision ends it at the next boundary with the revised page, not the old one."""
    patch_checks(monkeypatch, [GOOD_CHECKS])
    rid = await queue_run(state)
    await runner.run_pipeline(state, rid)
    first = (await status_of(state, rid))["state"]["html_version"]

    stop_at_checks(monkeypatch, state.db, rid)                 # the stop lands inside the revision
    await runner.claim_for_revision(state.db, rid, "user-1")
    await runner.revise_pipeline(state, rid, 'Change the headline to "Own the night shift"', "copy")

    doc = await status_of(state, rid)
    assert doc["status"] == "awaiting_approval" and doc["error"] is None
    assert doc["state"]["html_version"] == first + 1           # the revision had published before the stop
    assert doc["cancel_requested"] is False
    events = await read_events(state.db, rid)
    assert event_types(events)[-1] == "stopped" and events[-1][1]["status"] == "awaiting_approval"
    assert any(t == "agent_message" and "Your last version is still available" in d["message"]
               for t, d in events[-2:])


async def test_a_stop_that_arrives_when_nothing_is_left_to_stop_is_forgotten_not_carried(state, monkeypatch):
    """The one case a flag cannot reach: it lands after the phase's last boundary.

    The revision finishes normally with its new page, the request stays recorded on the run, and the next
    phase that claims the run forgets it - so a stop nobody could act on never kills later work.
    """
    patch_checks(monkeypatch, [GOOD_CHECKS])
    rid = await queue_run(state)
    await runner.run_pipeline(state, rid)
    first = (await status_of(state, rid))["state"]["html_version"]

    stop_at_checks(monkeypatch, state.db, rid)
    await runner.claim_for_revision(state.db, rid, "user-1")
    await runner.revise_pipeline(state, rid, "Make the hero button bigger", "page")   # no agent step after the review

    doc = await status_of(state, rid)
    assert doc["status"] == "awaiting_approval" and doc["state"]["html_version"] == first + 1
    assert doc["cancel_requested"] is True
    assert await runner.claim_for_revision(state.db, rid, "user-1") is True
    assert (await status_of(state, rid))["cancel_requested"] is False
