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

async def ctx_for(app_state, run_id: str) -> RunContext:
    """Rebuild the run's context (state + page) from the database, as every follow-up phase needs it."""
    db = app_state.db
    doc = await db.runs.find_one({"_id": ObjectId(run_id)})
    state = RunState.model_validate(doc["state"])
    ctx = RunContext(run_id=run_id, settings=app_state.settings, llm=app_state.llm, state=state,
                     sink=DBEventSink(db, run_id), storage=app_state.storage,
                     checkpoint=lambda c, st: _checkpoint(db, c, st),
                     tokens_used=doc.get("tokens_used", 0), steps=0)   # steps reset per phase; token budget stays cumulative
    if state.html_key:
        state.html = (await app_state.storage.load(state.html_key)).decode("utf-8")
    return ctx


async def _keep_last_good(app_state, run_id: str, ctx: RunContext, exc: Exception, label: str) -> None:
    """A failed follow-up phase must not destroy the run: return to the gate with the last good version."""
    msg = (str(exc) or exc.__class__.__name__)[:300]
    log.exception("%s of run %s failed", label, run_id)
    await app_state.db.runs.update_one({"_id": ObjectId(run_id)},
                                       {"$set": {"status": "awaiting_approval", "updated_at": now()}})
    await ctx.emit("agent_message", agent="system",
                   message=f"{label} failed: {msg}. Your last version is still available to approve.")
    await ctx.emit("awaiting_approval", message=f"{label} failed - previous version kept.",
                   remaining_errors=ctx.state.check_summary.get("errors", 0), html_version=ctx.state.html_version)


async def revise_pipeline(app_state, run_id: str, instruction: str, target: str) -> None:
    """Apply the user's feedback. Runs only after POST /revise flipped the run from 'awaiting_approval' to 'running'."""
    ctx = await ctx_for(app_state, run_id)
    try:
        await Orchestrator(ctx).revise(instruction, target)
    except Exception as exc:  # noqa: BLE001
        await _keep_last_good(app_state, run_id, ctx, exc, "Revision")


async def debug_pipeline(app_state, run_id: str) -> None:
    """Autonomous debugging: re-check the live page and repair what fails (POST /debug)."""
    ctx = await ctx_for(app_state, run_id)
    try:
        await Orchestrator(ctx).debug()
    except Exception as exc:  # noqa: BLE001
        await _keep_last_good(app_state, run_id, ctx, exc, "Debug pass")


async def audit_pipeline(app_state, run_id: str, kinds: list[str]) -> None:
    """Measure the live page against the audit crew. Reads only - the page is not rebuilt (POST /audit)."""
    ctx = await ctx_for(app_state, run_id)
    try:
        await Orchestrator(ctx).audit(kinds)
    except Exception as exc:  # noqa: BLE001
        await _keep_last_good(app_state, run_id, ctx, exc, "Audit")


async def repair_pipeline(app_state, run_id: str, kinds: list[str]) -> None:
    """Apply the current audits' fix instructions, rebuild through the normal routed-fix path, re-audit."""
    ctx = await ctx_for(app_state, run_id)
    try:
        await Orchestrator(ctx).repair(kinds)
    except Exception as exc:  # noqa: BLE001
        await _keep_last_good(app_state, run_id, ctx, exc, "Audit repair")


async def restore_pipeline(app_state, run_id: str, version: int) -> None:
    """Roll back to a saved version without spending tokens (POST /restore)."""
    ctx = await ctx_for(app_state, run_id)
    try:
        await Orchestrator(ctx).restore(version)
    except Exception as exc:  # noqa: BLE001
        await _keep_last_good(app_state, run_id, ctx, exc, "Restore")


async def workspace_apply_pipeline(app_state, run_id: str, changes: list[dict], request: str) -> None:
    """File-level patch: snapshot, apply, publish, re-check (POST /workspace/apply)."""
    ctx = await ctx_for(app_state, run_id)
    try:
        await Orchestrator(ctx).apply_workspace_changes(changes, request)
    except Exception as exc:  # noqa: BLE001
        await _keep_last_good(app_state, run_id, ctx, exc, "Workspace change")


async def workspace_restore_pipeline(app_state, run_id: str, w: int) -> None:
    """Roll the whole file set back to a captured snapshot (POST /workspace/restore)."""
    ctx = await ctx_for(app_state, run_id)
    try:
        await Orchestrator(ctx).restore_workspace_snapshot(w)
    except Exception as exc:  # noqa: BLE001
        await _keep_last_good(app_state, run_id, ctx, exc, "Workspace restore")


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
