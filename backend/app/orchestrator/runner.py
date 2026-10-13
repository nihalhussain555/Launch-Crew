"""DB-backed glue: persist run state/events, run the pipeline as a background task, handle approval."""
import asyncio
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ReturnDocument

from app.agents import variants
from app.config import Settings
from app.orchestrator import cancel
from app.orchestrator.graph import Orchestrator
from app.orchestrator.state import GuardrailError, RunCancelled, RunContext, RunState
from app.services import feature_build, ide_assistant, theme_edit, visual_edit, workspace_manager
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


def _watch(app_state, run_id: str, ctx: RunContext) -> asyncio.Event:
    """Put a stop watch on this pipeline: the in-process event, and the run's flag behind it.

    Call it once per pipeline and pair it with `cancel.disarm` in a finally, or a later phase of the same
    run would inherit a stop nobody asked for.
    """
    ctx.cancel_event = cancel.arm(run_id)
    ctx.cancel_probe = lambda: cancel.requested(app_state.db, run_id)
    return ctx.cancel_event


async def _stopped(db, run_id: str, ctx: RunContext, exc: RunCancelled) -> None:
    """End the phase where the stop landed. A stop is a choice the user made, not a failure.

    Whatever the run had already checkpointed stays: the state, the tokens it spent, and - if the engineer
    got that far - the page version it published. A run with a page goes back to the approval gate, where
    the user can review, revise or approve it; a run with no page yet ends as `cancelled`, because there is
    nothing at a gate to approve. Either way the run's own event stream says where it stopped.
    """
    s = ctx.state
    has_page = s.html_version > 0
    status = "awaiting_approval" if has_page else "cancelled"
    log.info("run %s stopped: %s", run_id, exc)
    await ctx.checkpoint(status)
    await cancel.clear(db, run_id)
    steps, tokens = ctx.steps, f"{ctx.tokens_used:,}"
    message = (f"{exc} It stopped before every step had run, so the checks may not have seen this build. "
               f"Page v{s.html_version} is kept and is waiting for you at the approval gate - review it, "
               f"revise it, or approve it from there." if has_page else
               f"{exc} Nothing had been published yet, so there is no page to approve and this run ends "
               f"cancelled. The {steps} step(s) that did finish, and the {tokens} tokens they cost, "
               f"stay recorded on it.")
    await ctx.emit("stopped", message=message, agent=exc.agent, status=status,
                   html_version=s.html_version, steps=ctx.steps, tokens_used=ctx.tokens_used)


async def run_pipeline(app_state, run_id: str) -> None:
    """Idea -> research -> ... -> critic loop -> awaiting_approval."""
    db, settings = app_state.db, app_state.settings
    doc = await db.runs.find_one({"_id": ObjectId(run_id)})
    state = RunState(idea=doc["idea"], spec=doc.get("spec") or {})
    ctx = RunContext(run_id=run_id, settings=settings, llm=app_state.llm, state=state,
                     sink=DBEventSink(db, run_id), storage=app_state.storage,
                     checkpoint=lambda c, st: _checkpoint(db, c, st))
    _watch(app_state, run_id, ctx)
    try:
        await Orchestrator(ctx).run_until_approval()
    except RunCancelled as exc:  # noqa: BLE001 - the stop is reported, not retried
        await _stopped(db, run_id, ctx, exc)
    except Exception as exc:  # noqa: BLE001 - every failure must surface in the UI
        await _fail(db, ctx, exc)
    finally:
        cancel.disarm(run_id)


async def launch_pipeline(app_state, run_id: str) -> None:
    """Runs only after POST /approve flipped status to 'deploying'."""
    db = app_state.db
    doc = await db.runs.find_one({"_id": ObjectId(run_id)})
    state = RunState.model_validate(doc["state"])
    ctx = RunContext(run_id=run_id, settings=app_state.settings, llm=app_state.llm, state=state,
                     sink=DBEventSink(db, run_id), storage=app_state.storage,
                     checkpoint=lambda c, st: _checkpoint(db, c, st),
                     tokens_used=doc.get("tokens_used", 0), steps=doc.get("steps", 0))
    _watch(app_state, run_id, ctx)
    try:
        state.html = (await app_state.storage.load(state.html_key)).decode("utf-8")
        await Orchestrator(ctx).launch()
    except RunCancelled as exc:  # a stopped deploy leaves the page exactly as the gate had it
        await _stopped(db, run_id, ctx, exc)
    except Exception as exc:  # noqa: BLE001
        await _fail(db, ctx, exc)
    finally:
        cancel.disarm(run_id)

async def ctx_for(app_state, run_id: str) -> RunContext:
    """Rebuild the run's context (state + page) from the database, as every follow-up phase needs it."""
    db = app_state.db
    doc = await db.runs.find_one({"_id": ObjectId(run_id)})
    state = RunState.model_validate(doc["state"])
    ctx = RunContext(run_id=run_id, settings=app_state.settings, llm=app_state.llm, state=state,
                     sink=DBEventSink(db, run_id), storage=app_state.storage,
                     checkpoint=lambda c, st: _checkpoint(db, c, st),
                     tokens_used=doc.get("tokens_used", 0), steps=0,   # steps reset per phase; budget stays cumulative
                     # A follow-up phase reads the flag rather than holding an event of its own: it ends in
                     # one or two steps, so honouring a stop at its next boundary is prompt enough, and an
                     # event nobody disarms would outlive the phase that armed it.
                     cancel_probe=lambda: cancel.requested(db, run_id))
    if state.html_key:
        state.html = (await app_state.storage.load(state.html_key)).decode("utf-8")
    return ctx


async def _keep_last_good(app_state, run_id: str, ctx: RunContext, exc: Exception, label: str) -> None:
    """A failed follow-up phase must not destroy the run: return to the gate with the last good version.

    A stop is reported through here too, in its own words: that phase ended because someone asked it to,
    not because the crew could not do the work. Either way the run goes back to the gate unchanged.
    """
    stopped = isinstance(exc, RunCancelled)
    msg = (str(exc) or exc.__class__.__name__)[:300]
    if stopped:
        log.info("%s of run %s stopped: %s", label, run_id, msg)
        await cancel.clear(app_state.db, run_id)
    else:
        log.exception("%s of run %s failed", label, run_id)
    await app_state.db.runs.update_one({"_id": ObjectId(run_id)},
                                       {"$set": {"status": "awaiting_approval", "updated_at": now()}})
    await ctx.emit("agent_message", agent="system",
                   message=(f"{msg} Your last version is still available to approve." if stopped
                            else f"{label} failed: {msg}. Your last version is still available to approve."))
    await ctx.emit("stopped" if stopped else "awaiting_approval",
                   message=(f"{label} stopped by you - the last version is kept." if stopped
                            else f"{label} failed - previous version kept."),
                   remaining_errors=ctx.state.check_summary.get("errors", 0),
                   html_version=ctx.state.html_version, status="awaiting_approval",
                   **({"agent": getattr(exc, "agent", ""), "steps": ctx.steps} if stopped else {}))


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


async def visual_apply_pipeline(app_state, run_id: str, changes: list[dict], request: str,
                                proposal_id: str) -> None:
    """Apply a reviewed visual patch and write the outcome back on the proposal (POST /visual/apply).

    The change itself is the workspace pipeline's, so it gets the same pre-change checkpoint, the same
    sanitizer and Chromium pass afterwards, and the same "last version is still yours" recovery if it
    fails. Only the attribution differs: history records this as a visual edit, and the proposal says
    which element it was about.
    """
    ctx = await ctx_for(app_state, run_id)
    try:
        plan = await Orchestrator(ctx).apply_workspace_changes(changes, request, kind="visual edit")
        entry = visual_edit.find_proposal(ctx.state, proposal_id)
        entry["plan"] = plan["id"]
        visual_edit.mark_proposal(entry, "applied", **plan["result"])
        await ctx.checkpoint()
    except Exception as exc:  # noqa: BLE001
        try:
            entry = visual_edit.find_proposal(ctx.state, proposal_id)
            visual_edit.mark_proposal(entry, "rejected",
                                       error=(getattr(exc, "message", None) or str(exc))[:300])
            await ctx.checkpoint()
        except Exception:  # noqa: BLE001 - the proposal is a record, never a reason to lose the page
            log.warning("visual proposal %s on run %s could not be marked", proposal_id, run_id)
        await _keep_last_good(app_state, run_id, ctx, exc, "Visual edit")


async def ide_apply_pipeline(app_state, run_id: str, changes: list[dict], request: str,
                             proposal_id: str) -> None:
    """Apply a reviewed assistant edit and write the outcome back on the proposal (POST /ide/apply).

    Same pipeline as a typed or clicked patch - checkpoint, sanitizer, publish, Chromium checks, readiness -
    because an AI patch gets no free pass. The proposal is marked from the plan the pipeline recorded, and a
    failure says so on the proposal instead of leaving the page mid-change.
    """
    ctx = await ctx_for(app_state, run_id)
    try:
        plan = await Orchestrator(ctx).apply_workspace_changes(changes, request, kind="assistant edit")
        entry = ide_assistant.find_entry(ctx.state, proposal_id)
        entry["plan"] = plan["id"]
        ide_assistant.mark_proposal(entry, "applied", **plan["result"])
        await ctx.checkpoint()
    except Exception as exc:  # noqa: BLE001
        try:
            entry = ide_assistant.find_entry(ctx.state, proposal_id)
            ide_assistant.mark_proposal(entry, "rejected",
                                        error=(getattr(exc, "message", None) or str(exc))[:300])
            await ctx.checkpoint()
        except Exception:  # noqa: BLE001 - the proposal is a record, never a reason to lose the page
            log.warning("assistant proposal %s on run %s could not be marked", proposal_id, run_id)
        await _keep_last_good(app_state, run_id, ctx, exc, "Assistant edit")


async def theme_apply_pipeline(app_state, run_id: str, proposal_id: str) -> None:
    """Apply a reviewed token patch, then make the run's own design say it too (POST /theme/apply).

    The page and the brief are two halves of the same promise: patching the `:root` block restyles what
    is live now, and writing the theme onto the run's direction and spec is what keeps the next revision
    or rebuild from quietly drawing the old skin back. Both happen here, after the workspace pipeline has
    proved the patch survives the sanitizer and the Chromium checks - a failed theme edit leaves the
    direction alone, because the page it belongs to was not changed either.
    """
    ctx = await ctx_for(app_state, run_id)
    try:
        entry = theme_edit.find_proposal(ctx.state, proposal_id)
        before = {"style": dict(ctx.state.style), "spec_theme": (ctx.state.spec or {}).get("theme") or {}}
        plan = await Orchestrator(ctx).apply_workspace_changes(entry["changes"],
                                                               entry.get("request") or entry["summary"],
                                                               kind="theme edit")
        direction = variants.retheme(variants.from_dict(ctx.state.style), entry["theme"],
                                     color=(ctx.state.spec or {}).get("color", ""))
        ctx.state.style = variants.as_dict(direction)
        ctx.state.spec = {**(ctx.state.spec or {}), "theme": entry["theme"]}
        entry["plan"] = plan["id"]
        # Both designs are recorded so an undo or a redo can put the run's own direction back the way it
        # was: the page in the snapshot and the design in the state have to move together.
        entry["design_before"] = before
        entry["design_after"] = {"style": dict(ctx.state.style), "spec_theme": entry["theme"]}
        theme_edit.mark_proposal(entry, "applied", **plan["result"])
        await ctx.emit("agent_message", agent="system",
                       message=f"Theme applied as v{ctx.state.html_version}: {entry['summary']}. "
                               f"{plan['result'].get('lines_added', 0)} lines up, "
                               f"{plan['result'].get('lines_removed', 0)} down.")
        await ctx.checkpoint()
    except Exception as exc:  # noqa: BLE001
        try:
            entry = theme_edit.find_proposal(ctx.state, proposal_id)
            theme_edit.mark_proposal(entry, "rejected",
                                     error=(getattr(exc, "message", None) or str(exc))[:300])
            await ctx.checkpoint()
        except Exception:  # noqa: BLE001 - the proposal is a record, never a reason to lose the page
            log.warning("theme proposal %s on run %s could not be marked", proposal_id, run_id)
        await _keep_last_good(app_state, run_id, ctx, exc, "Theme edit")


async def feature_apply_pipeline(app_state, run_id: str, proposal_id: str) -> None:
    """Apply a reviewed feature build: the page block, plus the source files that ship with it.

    Writing is the workspace pipeline's job, so a feature build gets the same pre-change snapshot, the
    same sanitizer and Chromium checks over the patched page, and the same readiness score after it. What
    is specific to features is the second half of the change - `server.py`, `schema.sql`, `SETUP.md` and
    the rest are handed over as authored source, and the orchestrator already rolls them back if the page
    patch is refused, because a half-written feature is the one thing this path must not report as done.

    The message that follows says what each capability actually reached. A build whose checkout still
    needs a payment account says so, in the catalog's own words, instead of printing "store added".
    """
    ctx = await ctx_for(app_state, run_id)
    try:
        entry = feature_build.find_proposal(ctx.state, proposal_id)
        texts = await workspace_manager.load_texts(ctx)
        texts.setdefault("index.html", ctx.state.html)
        feature_build.recheck(entry, texts)
        authored = feature_build.authored_for(entry)
        plan = await Orchestrator(ctx).apply_workspace_changes(entry["changes"],
                                                               entry.get("request") or entry["summary"],
                                                               kind="feature build", authored=authored)
        entry["plan"] = plan["id"]
        feature_build.mark_proposal(entry, "applied", **plan["result"])
        await ctx.checkpoint()
        waiting = [row["label"] for row in entry.get("features") or []
                   if row.get("status") != "generated"]
        await ctx.emit("agent_message", agent="system",
                       message=f"Feature build applied as v{ctx.state.html_version}: {entry['summary']} "
                               f"Written beside the page: {', '.join(item['name'] for item in authored)}. "
                               + (f"Still needing something from you: {', '.join(waiting)} - the steps are "
                                  f"in SETUP.md." if waiting else
                                  "Everything in it works in the published page as it stands."))
    except Exception as exc:  # noqa: BLE001
        try:
            entry = feature_build.find_proposal(ctx.state, proposal_id)
            feature_build.mark_proposal(entry, "rejected",
                                         error=(getattr(exc, "message", None) or str(exc))[:300])
            await ctx.checkpoint()
        except Exception:  # noqa: BLE001 - the proposal is a record, never a reason to lose the page
            log.warning("feature proposal %s on run %s could not be marked", proposal_id, run_id)
        await _keep_last_good(app_state, run_id, ctx, exc, "Feature build")


async def workspace_restore_pipeline(app_state, run_id: str, w: int) -> None:
    """Roll the whole file set back to a captured snapshot (POST /workspace/restore)."""
    ctx = await ctx_for(app_state, run_id)
    try:
        await Orchestrator(ctx).restore_workspace_snapshot(w)
    except Exception as exc:  # noqa: BLE001
        await _keep_last_good(app_state, run_id, ctx, exc, "Workspace restore")


async def step_pipeline(app_state, run_id: str, side: str) -> None:
    """Undo or redo one recorded change (POST /workspace/undo, POST /workspace/redo).

    The workspace snapshot the move left behind is what makes it reversible, so a failure here is
    reported against the timeline rather than silently leaving the run somewhere else.
    """
    ctx = await ctx_for(app_state, run_id)
    try:
        step = ctx.state.undo_stack[-1] if side == "undo" else ctx.state.redo_stack[-1]
        await (Orchestrator(ctx).undo() if side == "undo" else Orchestrator(ctx).redo())
    except Exception as exc:  # noqa: BLE001
        await _keep_last_good(app_state, run_id, ctx, exc, f"{'Undo' if side == 'undo' else 'Redo'} of w{step}")


async def claim_for_revision(db, run_id: str, user_id: str) -> bool:
    """Atomic gate: only a run in 'awaiting_approval' can be revised (blocks concurrent revise/approve).

    Claiming also forgets any stop asked for earlier: that stop belonged to the phase it ended, and a new
    phase must not be killed at its first boundary by a button pressed before it started.
    """
    res = await db.runs.find_one_and_update(
        {"_id": ObjectId(run_id), "user_id": user_id, "status": "awaiting_approval"},
        {"$set": {"status": "running", "cancel_requested": False, "updated_at": now()}})
    return res is not None

async def claim_for_deploy(db, run_id: str, user_id: str) -> bool:
    """Atomic gate: only a run in 'awaiting_approval' can move to 'deploying' (blocks double-approve/skips)."""
    res = await db.runs.find_one_and_update(
        {"_id": ObjectId(run_id), "user_id": user_id, "status": "awaiting_approval"},
        {"$set": {"status": "deploying", "cancel_requested": False, "updated_at": now()}})
    return res is not None


async def fail_stale_runs(db) -> int:
    """On startup: runs left mid-flight by a crashed/restarted server can never finish."""
    res = await db.runs.update_many({"status": {"$in": ["queued", "running", "deploying"]}},
                                    {"$set": {"status": "failed", "error": "Server restarted while this run was in progress."}})
    return res.modified_count
