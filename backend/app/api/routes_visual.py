"""Visual AI editing: select an element in the live preview, ask for a change, review the patch, apply it.

Three routes and at most one model call between them. `/locate` is free - it answers "where does this
come from?" from the workspace index and the published page. `/plan` asks the visual editor for one
minimal patch and proves it matches the file, stays small and is about the element that was picked,
without writing a byte. `/apply` hands that same verified patch to the workspace pipeline, so a visual
edit gets the checkpoint before it, the sanitizer and the Chromium checks after it, and history that
records it as a visual edit attributed to the run and the proposal.

Source mapping is the gate: when the clicked element cannot be found in the run's own files, the edit is
refused with the reason, and no path is invented to keep the request moving.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.base import AgentOutputError
from app.agents.visual_editor import VisualEditorAgent
from app.api.routes_runs import own_run
from app.api.routes_workspace import BUSY, _ctx, _diff_pair, _fail
from app.core.deps import get_current_user, get_db, get_settings_dep
from app.db.models import RunOut, oid, run_out
from app.orchestrator import runner
from app.services import change_impact, visual_edit, workspace_manager
from app.services.workspace_manager import WorkspaceError

router = APIRouter(prefix="/api/runs/{run_id}/visual", tags=["visual editor"])

MAX_REASON_CHARS = 300


class ElementIn(BaseModel):
    """What the sandboxed frame reports about the node that was clicked.

    The bounds here are the transport's (a browser should never send hundreds of classes); the smaller
    bounds the model gets are the service's, applied by `visual_edit.describe`, so an oversized selection
    is clipped rather than rejected.
    """
    tag: str = ""
    id: str = ""
    classes: list[str] = Field(default_factory=list, max_length=64)
    text: str = ""
    attrs: list[list[str]] = Field(default_factory=list, max_length=32)
    index: int | None = Field(default=None, ge=0)
    matches: int | None = Field(default=None, ge=0)
    path: str = ""


class LocateIn(BaseModel):
    element: ElementIn


class ProposeIn(BaseModel):
    element: ElementIn
    instruction: str = Field(min_length=3, max_length=500)
    base_version: int | None = None


class ProposalIn(BaseModel):
    """Which proposal, and the version the reviewer was looking at when they read it."""
    id: str = Field(min_length=1, max_length=12)
    reason: str = Field(default="", max_length=200)
    base_version: int | None = None


async def _selection(ctx, raw: dict) -> tuple[dict, dict, dict, dict]:
    """Read one selection back against the workspace: its texts, index and what `locate` concluded.

    Takes the described-or-wire element dict rather than the request model: `/apply` re-derives this from
    the proposal it stored, and a stored element is the same thing the frame sent, only rounded.
    """
    texts = await workspace_manager.load_texts(ctx)
    texts.setdefault("index.html", ctx.state.html)
    index = workspace_manager.index_texts(texts, version=ctx.state.html_version)
    element = visual_edit.describe(raw)
    return texts, element, visual_edit.locate(texts, element, index), index


def _require(located: dict) -> dict:
    """Turn a mapping refusal into the answer a route that cannot continue should give.

    `/locate` does not call this: "this element is not in the source" is the reply the user asked for,
    and the panel shows it. An edit route refuses instead, because a change with no known file to change
    is a change that would have to invent one.
    """
    if located["found"]:
        return located
    raise WorkspaceError(located["message"], 409 if located["reason"] in ("stale", "no-page") else 422)


@router.post("/locate")
async def locate(run_id: str, body: LocateIn, request: Request, db=Depends(get_db),
                 user=Depends(get_current_user)):
    """Where the selected element is declared, what styles it and what script reaches for it. No model, no write."""
    ctx = await _ctx(request, db, run_id, user)
    _texts, element, located, _index = await _selection(ctx, body.element.model_dump())
    return {"version": ctx.state.html_version, "element": element, **located}


@router.post("/plan")
async def plan(run_id: str, body: ProposeIn, request: Request, db=Depends(get_db), settings=Depends(get_settings_dep),
               user=Depends(get_current_user)):
    """One minimal patch for the selected element, reviewed before anything is written.

    Costs tokens (this is the only model call in the flow) and changes nothing: the patch is verified
    against the file it names, measured for impact, diffed and recorded as a proposal. The revision cap is
    checked here too, because a run that cannot apply a change should not be charged for proposing one.
    """
    ctx = await _ctx(request, db, run_id, user)
    if ctx.state.revisions >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve this "
                                 f"version or start a new run before asking for another change.")
    try:
        workspace_manager.check_base(ctx.state, body.base_version)
        texts, element, located, index = await _selection(ctx, body.element.model_dump())
        _require(located)
        report = change_impact.analyze(index, body.instruction, version=ctx.state.html_version)
        ctx.state.impact = report
        ask = visual_edit.prompt(el=element, located=located, texts=texts, instruction=body.instruction,
                                 impact=report.get("block") or "")
        try:
            verified = await VisualEditorAgent().patch(ctx, user=ask, texts=texts, located=located)
        except AgentOutputError as exc:
            raise WorkspaceError(f"The model produced no patch that fits this element: "
                                 f"{str(exc)[:MAX_REASON_CHARS]}", 502) from exc
        before, after, _page = await workspace_manager.prepare_changes(ctx, verified["changes"])
    except WorkspaceError as exc:
        _fail(exc)

    projection = workspace_manager.stats(before, after)
    diffs = {name: _diff_pair(before.get(name, ""), after.get(name, ""), f"before/{name}", f"after/{name}")
             for name in projection["changed"]}
    entry = visual_edit.record_proposal(ctx, instruction=body.instruction, element=element, located=located,
                                        verified=verified, report=report)
    await db.runs.update_one({"_id": oid(run_id)}, {"$set": {
        "state.visual_edits": ctx.state.visual_edits, "state.impact": ctx.state.impact,
        "updated_at": runner.now()}})
    return {"proposal": entry, "element": element, "source": located["source"],
            "styling": located["styling"], "scripting": located["scripting"],
            "patch": verified["patch"], "diffs": diffs, "projection": projection,
            "targeted": verified["targeted"], "region": verified["region"], "warning": verified["warning"],
            "affected_files": visual_edit.names_files(verified["changes"], located),
            "impact": report, "headline": change_impact.headline(report),
            "base_version": ctx.state.html_version, "undo": workspace_manager.undo_status(ctx.state),
            "safe_to_apply": not report["counts"]["errors"],
            "limits": {"ops": list(visual_edit.VISUAL_OPS), "max_patch_lines": visual_edit.MAX_PATCH_LINES,
                       "max_proposals": visual_edit.MAX_PROPOSALS,
                       "revisions_left": max(settings.max_revisions - ctx.state.revisions, 0)}}


@router.get("/proposals")
async def proposals(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Every visual edit this run has been offered, newest first, with what became of each one."""
    state = (await own_run(db, run_id, user)).get("state", {})
    entries = state.get("visual_edits") or []
    return {"version": state.get("html_version", 0), "proposals": entries[::-1]}


@router.post("/apply", response_model=RunOut, status_code=202)
async def apply_proposal(run_id: str, body: ProposalIn, request: Request, background: BackgroundTasks,
                         db=Depends(get_db), settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """Apply a proposal the user has read. Re-measured here: the patch must still mean the same thing.

    The version guard and the element lookup both run again, because a proposal reviewed at v4 must not
    be applied over a page that has moved to v5, and a patch whose element has disappeared is a different
    change than the one that was approved.
    """
    run = await own_run(db, run_id, user)
    if run.get("state", {}).get("revisions", 0) >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). "
                                 f"Approve this version or start a new run.")
    ctx = await _ctx(request, db, run_id, user)
    try:
        entry = visual_edit.find_proposal(ctx.state, body.id)
        if entry.get("status") != "proposed":
            raise WorkspaceError(f"Proposal {entry['id']} was already {entry.get('status')}. Ask for a new "
                                 f"one to change this element again.", 409)
        workspace_manager.check_base(ctx.state, body.base_version)
        if entry.get("version") != ctx.state.html_version:
            raise WorkspaceError(f"Conflict: proposal {entry['id']} was read at v{entry.get('version')} but "
                                 f"the workspace is at v{ctx.state.html_version}. Load the element again "
                                 f"and re-request the change.", 409)
        texts, _element, located, _index = await _selection(ctx, entry["element"])
        _require(located)
        verified = visual_edit.verify(entry["patch"], texts, located)
        await workspace_manager.prepare_changes(ctx, verified["changes"])
    except WorkspaceError as exc:
        _fail(exc)

    visual_edit.mark_proposal(entry, "applying")
    await db.runs.update_one({"_id": oid(run_id)},
                             {"$set": {"state.visual_edits": ctx.state.visual_edits, "updated_at": runner.now()}})
    if not await runner.claim_for_revision(db, run_id, str(user["_id"])):
        visual_edit.mark_proposal(entry, "proposed")
        await db.runs.update_one({"_id": oid(run_id)},
                                 {"$set": {"state.visual_edits": ctx.state.visual_edits}})
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(runner.visual_apply_pipeline, request.app.state, run_id, verified["changes"],
                        entry["instruction"], entry["id"])
    return run_out(await own_run(db, run_id, user))


@router.post("/reject")
async def reject_proposal(run_id: str, body: ProposalIn, request: Request, db=Depends(get_db),
                          user=Depends(get_current_user)):
    """Turn a proposal down. Nothing is written to the workspace; the record says it was rejected."""
    run = await own_run(db, run_id, user)
    if run["status"] in BUSY:
        raise HTTPException(409, f"The crew is {run['status']} on this run right now. Reject the proposal "
                                 f"once it is back at the approval gate.")
    ctx = await _ctx(request, db, run_id, user)
    try:
        entry = visual_edit.find_proposal(ctx.state, body.id)
        if entry.get("status") != "proposed":
            raise WorkspaceError(f"Proposal {entry['id']} is already {entry.get('status')}.", 409)
        visual_edit.mark_proposal(entry, "rejected", reason=body.reason[:200])
    except WorkspaceError as exc:
        _fail(exc)
    await db.runs.update_one({"_id": oid(run_id)},
                             {"$set": {"state.visual_edits": ctx.state.visual_edits, "updated_at": runner.now()}})
    return {"proposal": entry, "undo": workspace_manager.undo_status(ctx.state)}
