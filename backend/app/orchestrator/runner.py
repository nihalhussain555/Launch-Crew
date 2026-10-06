"""DB-backed glue: persist run state/events, run the pipeline as a background task, handle approval."""
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ReturnDocument

from app.config import Settings
from app.orchestrator.graph import Orchestrator
from app.orchestrator.state import GuardrailError, RunContext, RunState
from app.utils.logger import get_logger

log = get_logger("runner")
TERMINAL = {"deployed", "failed"}


def now():
    return datetime.now(timezone.utc)


class DBEventSink:
    """Appends events to `run_events` with an atomic per-run sequence number (SSE reads from here)."""

    def __init__(self, db, run_id: str):
        self.db, self.run_id = db, run_id

    async def __call__(self, type_: str, data: dict) -> None:
        doc = await self.db.runs.find_one_and_update(
            {"_id": ObjectId(self.run_id)}, {"$inc": {"event_seq": 1}},
            return_document=ReturnDocument.AFTER, projection={"event_seq": 1})
        await self.db.run_events.insert_one(
            {"run_id": self.run_id, "seq": doc["event_seq"], "type": type_, "data": data, "ts": now()})


async def _checkpoint(db, ctx: RunContext, status: str | None) -> None:
    update = {"state": ctx.state.persisted(), "tokens_used": ctx.tokens_used, "steps": ctx.steps, "updated_at": now()}
    if status:
        update["status"] = status
    await db.runs.update_one({"_id": ObjectId(ctx.run_id)}, {"$set": update})


async def _fail(db, ctx: RunContext, exc: Exception) -> None:
    msg = str(exc) or exc.__class__.__name__
    log.exception("run %s failed", ctx.run_id)
    await db.runs.update_one({"_id": ObjectId(ctx.run_id)}, {"$set": {"status": "failed", "error": msg[:500], "updated_at": now()}})
    await ctx.emit("failed", error=msg[:500], guardrail=isinstance(exc, GuardrailError))


async def run_pipeline(app_state, run_id: str) -> None:
    """Idea -> research -> ... -> critic loop -> awaiting_approval."""
    db, settings = app_state.db, app_state.settings
    doc = await db.runs.find_one({"_id": ObjectId(run_id)})
    ctx = RunContext(run_id=run_id, settings=settings, llm=app_state.llm, state=RunState(idea=doc["idea"]),
                     sink=DBEventSink(db, run_id), storage=app_state.storage,
                     checkpoint=lambda c, st: _checkpoint(db, c, st))
    try:
        await Orchestrator(ctx).run_until_approval()
    except Exception as exc:  # noqa: BLE001 - every failure must surface in the UI
        await _fail(db, ctx, exc)


async def launch_pipeline(app_state, run_id: str) -> None:
    """Runs only after POST /approve flipped status to 'deploying'."""
    db = app_state.db
    doc = await db.runs.find_one({"_id": ObjectId(run_id)})
    state = RunState.model_validate(doc["state"])
    ctx = RunContext(run_id=run_id, settings=app_state.settings, llm=app_state.llm, state=state,
                     sink=DBEventSink(db, run_id), storage=app_state.storage,
                     checkpoint=lambda c, st: _checkpoint(db, c, st),
                     tokens_used=doc.get("tokens_used", 0), steps=doc.get("steps", 0))
    try:
        state.html = (await app_state.storage.load(state.html_key)).decode("utf-8")
        await Orchestrator(ctx).launch()
    except Exception as exc:  # noqa: BLE001
        await _fail(db, ctx, exc)

async def revise_pipeline(app_state, run_id: str, instruction: str, target: str) -> None:
    """Apply the user's feedback. Runs only after POST /revise flipped the run from 'awaiting_approval' to 'running'."""
    db = app_state.db
    doc = await db.runs.find_one({"_id": ObjectId(run_id)})
    state = RunState.model_validate(doc["state"])
    ctx = RunContext(run_id=run_id, settings=app_state.settings, llm=app_state.llm, state=state,
                     sink=DBEventSink(db, run_id), storage=app_state.storage,
                     checkpoint=lambda c, st: _checkpoint(db, c, st),
                     tokens_used=doc.get("tokens_used", 0), steps=0)   # steps reset per phase; token budget stays cumulative
    try:
        state.html = (await app_state.storage.load(state.html_key)).decode("utf-8")
        await Orchestrator(ctx).revise(instruction, target)
    except Exception as exc:  # noqa: BLE001
        # A failed revision must not destroy the run: go back to the approval gate with the last good checkpoint.
        msg = (str(exc) or exc.__class__.__name__)[:300]
        log.exception("revision of run %s failed", run_id)
        await db.runs.update_one({"_id": ObjectId(run_id)}, {"$set": {"status": "awaiting_approval", "updated_at": now()}})
        await ctx.emit("agent_message", agent="system", message=f"Revision failed: {msg}. Your last version is still available to approve.")
        await ctx.emit("awaiting_approval", message="Revision failed - previous version kept.",
                       remaining_errors=state.check_summary.get("errors", 0), html_version=state.html_version)


async def claim_for_revision(db, run_id: str, user_id: str) -> bool:
    """Atomic gate: only a run in 'awaiting_approval' can be revised (blocks concurrent revise/approve)."""
    res = await db.runs.find_one_and_update(
        {"_id": ObjectId(run_id), "user_id": user_id, "status": "awaiting_approval"},
        {"$set": {"status": "running", "updated_at": now()}})
    return res is not None

async def claim_for_deploy(db, run_id: str, user_id: str) -> bool:
    """Atomic gate: only a run in 'awaiting_approval' can move to 'deploying' (blocks double-approve/skips)."""
    res = await db.runs.find_one_and_update(
        {"_id": ObjectId(run_id), "user_id": user_id, "status": "awaiting_approval"},
        {"$set": {"status": "deploying", "updated_at": now()}})
    return res is not None


async def fail_stale_runs(db) -> int:
    """On startup: runs left mid-flight by a crashed/restarted server can never finish."""
    res = await db.runs.update_many({"status": {"$in": ["queued", "running", "deploying"]}},
                                    {"$set": {"status": "failed", "error": "Server restarted while this run was in progress."}})
    return res.modified_count
