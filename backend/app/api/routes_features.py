"""Real website features, asked for in plain English, built as a reviewable change.

Two routers and no model call. `/api/capabilities` is the catalog itself - what Launch Crew has source
for, per surface, with the honest state of each part, so the wizard and the Features panel can only offer
a thing the builder can actually write. The run-scoped routes then work against one project's page:
`/plan` answers "what would this mean?" without recording anything, `/propose` measures the impact and
differs the block on the real files and records a proposal, and `/apply` hands that verified patch to the
workspace pipeline as a `feature build`, which snapshots the whole file set first and puts the patched
page back through the sanitizer, the Chromium checks and the readiness score afterwards.

Nothing here reports a feature as working unless its weakest surface does. A checkout whose payment
provider is unconfigured is returned as `needs-external-setup` with the variables it reads and the steps
that remain - never as "store added". That rule is why this file reads `app/agents/capabilities.py`
instead of asking a model what it thinks a booking system needs.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents import capabilities as caps
from app.api.routes_runs import own_run
from app.api.routes_workspace import BUSY, _ctx, _diff_pair, _fail
from app.core.deps import get_current_user, get_db, get_settings_dep
from app.db.models import RunOut, oid, run_out
from app.orchestrator import runner
from app.services import change_impact, feature_build, feature_plan, workspace_manager
from app.services.workspace_manager import WorkspaceError

router = APIRouter(prefix="/api", tags=["features"])
run_router = APIRouter(prefix="/api/runs/{run_id}/features", tags=["features"])

MAX_REQUEST_CHARS = 500

# The fields a proposal shows the reviewer. The patch text itself is deliberately not among them: one
# entry can carry a whole page block, and a status call that returns six of them would be a download.
_VIEW = ("id", "at", "status", "version", "request", "keys", "named", "added", "introduces",
         "present_before", "replacing", "unchanged", "features", "statuses", "needs", "need_words",
         "overall", "overall_label", "env", "routes", "tables", "setup", "warnings", "summary", "server",
         "files", "page_bytes", "markup_bytes", "authored_names", "impact", "plan", "result",
         "lines_added", "lines_removed")


class PlanIn(BaseModel):
    """The ask, in the user's words and/or as picked capability keys, plus the version being looked at."""
    request: str = Field(default="", max_length=MAX_REQUEST_CHARS)
    keys: list[str] = Field(default_factory=list, max_length=16)
    site: str = Field(default="", max_length=120)
    base_version: int | None = None


class ProposalIn(BaseModel):
    """Which proposal, and the version the reviewer was looking at when they read it."""
    id: str = Field(min_length=1, max_length=12)
    reason: str = Field(default="", max_length=200)
    base_version: int | None = None


def _view(entry: dict) -> dict:
    out = {key: entry.get(key) for key in _VIEW}
    change = (entry.get("changes") or [{}])[0]
    out["patch"] = {"file": change.get("file", "index.html"), "op": change.get("op", "replace"),
                    "note": change.get("note", ""),
                    "find_quote": (change.get("find") or "")[:180],
                    "replace_bytes": len((change.get("replace") or "").encode("utf-8", "ignore"))}
    return out


async def _texts(ctx) -> dict:
    texts = await workspace_manager.load_texts(ctx)
    texts.setdefault("index.html", ctx.state.html)
    return texts


async def _site_name(db, run: dict, body: PlanIn) -> str:
    """What to call the site inside the generated server: the project's own name if it has one."""
    if body.site.strip():
        return body.site.strip()[:120]
    project_id = run.get("project_id")
    if project_id:
        try:
            project = await db.projects.find_one({"_id": oid(project_id)}, projection={"name": 1})
        except Exception:  # noqa: BLE001 - a label is never a reason to fail a plan
            project = None
        if project and (project.get("name") or "").strip():
            return str(project["name"]).strip()[:120]
    return (run.get("idea") or "")[:120]


@router.get("/capabilities")
async def capability_catalog(user=Depends(get_current_user)):
    """Every feature this product can write, with its surfaces and its honest state.

    The wizard's picker and the Features panel both draw from here, which is the point: an option the
    builder has no source for is not offered, so a user can never approve a promise nobody wrote.
    """
    return caps.catalog()


@run_router.get("")
async def feature_status(run_id: str, request: Request, db=Depends(get_db),
                         settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """What this run has been offered, what it was built with, and what the page actually carries now."""
    run = await own_run(db, run_id, user)
    state = run.get("state", {})
    page = None
    if state.get("html_key"):
        try:
            page = (await request.app.state.storage.load(state["html_key"])).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001 - a lost blob leaves the record readable, not the route broken
            page = None
    entries = state.get("feature_edits") or []
    # spread first: `status_of` reports the proposal ids, and the reviewable views of them are what this
    # route is for, so the views have to win the key
    return {"status": run["status"], "busy": run["status"] in BUSY,
            **feature_build.status_of(state, page),
            "proposals": [_view(e) for e in reversed(entries)],
            "authored_files": [{"name": f.get("name", ""), "bytes": f.get("bytes", 0),
                                "note": f.get("note", "")} for f in state.get("authored_files") or []],
            "limits": {"max_proposals": feature_build.MAX_FEATURE_PROPOSALS,
                       "max_features_per_build": feature_plan.MAX_KEYS,
                       "revisions_left": max(settings.max_revisions - state.get("revisions", 0), 0)}}


@run_router.post("/plan")
async def plan_features(run_id: str, body: PlanIn, request: Request, db=Depends(get_db),
                        user=Depends(get_current_user)):
    """What this sentence means as a build, measured against this page. Records nothing.

    The refusal matters as much as the answer: a request naming no known feature comes back 422 with the
    list that does, and an unknown key is refused rather than swapped for the nearest real one.
    """
    run = await own_run(db, run_id, user)
    site = await _site_name(db, run, body)
    ctx = await _ctx(request, db, run_id, user)
    try:
        workspace_manager.check_base(ctx.state, body.base_version)
        planned = feature_build.plan(await _texts(ctx), request=body.request, keys=body.keys,
                                     site=site, idea=ctx.state.idea)
    except WorkspaceError as exc:
        _fail(exc)
    report = planned["report"]
    return {"request": body.request, "keys": planned["keys"], "named": report["named"],
            "added": report["added"], "introduces": planned["introduces"],
            "present_before": planned["present"], "replacing": planned["replacing"],
            "features": report["features"], "statuses": report["statuses"], "needs": report["needs"],
            "need_words": report["need_words"], "overall": report["overall"],
            "overall_label": report["overall_label"], "files": report["files"],
            "env": report["env"], "routes": report["routes"], "tables": report["tables"],
            "setup": report["setup"], "warnings": report["warnings"],
            "summary": planned["summary"], "page_bytes": planned["markup_bytes"],
            "base_version": ctx.state.html_version}


@run_router.post("/propose")
async def propose_features(run_id: str, body: PlanIn, request: Request, db=Depends(get_db),
                           settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """The patch and the source files, verified against this page and left for review. Writes nothing.

    The diff is computed in memory and thrown away; what is kept is the proposal, so Apply can prove it
    means the same change the reviewer read. The revision cap is checked here too, because a run that
    cannot apply should not fill its history with offers it cannot honour.
    """
    ctx = await _ctx(request, db, run_id, user)
    if ctx.state.revisions >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve "
                                 f"this version or start a new run before asking for another feature.")
    run = await own_run(db, run_id, user)
    site = await _site_name(db, run, body)
    try:
        workspace_manager.check_base(ctx.state, body.base_version)
        texts = await _texts(ctx)
        planned = feature_build.plan(texts, request=body.request, keys=body.keys, site=site,
                                     idea=ctx.state.idea)
        ask = (body.request or planned["summary"])[:MAX_REQUEST_CHARS]
        index = workspace_manager.index_texts(texts, version=ctx.state.html_version)
        report = change_impact.analyze(index, ask, version=ctx.state.html_version)
        ctx.state.impact = report
        before, after, _page = await workspace_manager.prepare_changes(ctx, planned["changes"])
    except WorkspaceError as exc:
        _fail(exc)

    projection = workspace_manager.stats(before, after)
    diffs = {name: _diff_pair(before.get(name, ""), after.get(name, ""), f"before/{name}", f"after/{name}")
             for name in projection["changed"]}
    entry = feature_build.record_proposal(ctx, request=ask, site=site, idea=ctx.state.idea,
                                          planned=planned, report=report)
    entry["lines_added"] = projection["lines_added"]
    entry["lines_removed"] = projection["lines_removed"]
    await db.runs.update_one({"_id": oid(run_id)},
                             {"$set": {"state.feature_edits": ctx.state.feature_edits,
                                       "state.impact": ctx.state.impact, "updated_at": runner.now()}})
    return {"proposal": _view(entry), "features": entry["features"], "warnings": entry["warnings"],
            "env": entry["env"], "summary": entry["summary"], "overall": entry["overall"],
            "overall_label": entry["overall_label"], "files": entry["files"],
            "introduces": entry["introduces"], "replacing": entry["replacing"],
            "unchanged": entry["unchanged"], "diffs": diffs, "projection": projection,
            "impact": report, "headline": change_impact.headline(report),
            "base_version": ctx.state.html_version, "undo": workspace_manager.undo_status(ctx.state),
            "safe_to_apply": not report["counts"]["errors"],
            "limits": {"max_proposals": feature_build.MAX_FEATURE_PROPOSALS,
                       "revisions_left": max(settings.max_revisions - ctx.state.revisions, 0)}}


@run_router.post("/apply", response_model=RunOut, status_code=202)
async def apply_features(run_id: str, body: ProposalIn, request: Request, background: BackgroundTasks,
                         db=Depends(get_db), settings=Depends(get_settings_dep),
                         user=Depends(get_current_user)):
    """Build the feature the user has read. Re-checked here: the page must still be the one proposed.

    The version guard, the block lookup and the feature set named inside the patch all run again, because
    an offer read at v6 over a page now at v7 is a different change than the one that was approved - and
    a page whose block has been rewritten would otherwise be overwritten by bytes nobody reviewed.
    """
    run = await own_run(db, run_id, user)
    if run.get("state", {}).get("revisions", 0) >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve "
                                 f"this version or start a new run.")
    ctx = await _ctx(request, db, run_id, user)
    try:
        entry = feature_build.find_proposal(ctx.state, body.id)
        if entry.get("status") != "proposed":
            raise WorkspaceError(f"Feature proposal {entry['id']} was already {entry.get('status')}. Ask "
                                 f"for a new one to change this page again.", 409)
        workspace_manager.check_base(ctx.state, body.base_version)
        if entry.get("version") != ctx.state.html_version:
            raise WorkspaceError(f"Conflict: proposal {entry['id']} was read at v{entry.get('version')} "
                                 f"but the workspace is at v{ctx.state.html_version}. Preview the feature "
                                 f"again and re-request the build.", 409)
        feature_build.recheck(entry, await _texts(ctx))
        feature_build.authored_for(entry)
    except WorkspaceError as exc:
        _fail(exc)

    feature_build.mark_proposal(entry, "applying")
    await db.runs.update_one({"_id": oid(run_id)},
                             {"$set": {"state.feature_edits": ctx.state.feature_edits,
                                       "updated_at": runner.now()}})
    if not await runner.claim_for_revision(db, run_id, str(user["_id"])):
        feature_build.mark_proposal(entry, "proposed")
        await db.runs.update_one({"_id": oid(run_id)},
                                 {"$set": {"state.feature_edits": ctx.state.feature_edits}})
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(runner.feature_apply_pipeline, request.app.state, run_id, entry["id"])
    return run_out(await own_run(db, run_id, user))


@run_router.post("/reject")
async def reject_features(run_id: str, body: ProposalIn, request: Request, db=Depends(get_db),
                          user=Depends(get_current_user)):
    """Turn a feature proposal down. No file is written; the record says it was rejected."""
    run = await own_run(db, run_id, user)
    if run["status"] in BUSY:
        raise HTTPException(409, f"The crew is {run['status']} on this run right now. Reject the proposal "
                                 f"once it is back at the approval gate.")
    ctx = await _ctx(request, db, run_id, user)
    try:
        entry = feature_build.find_proposal(ctx.state, body.id)
        if entry.get("status") != "proposed":
            raise WorkspaceError(f"Feature proposal {entry['id']} is already {entry.get('status')}.", 409)
        feature_build.mark_proposal(entry, "rejected", reason=body.reason[:200])
    except WorkspaceError as exc:
        _fail(exc)
    await db.runs.update_one({"_id": oid(run_id)},
                             {"$set": {"state.feature_edits": ctx.state.feature_edits,
                                       "updated_at": runner.now()}})
    return {"proposal": _view(entry), "undo": workspace_manager.undo_status(ctx.state)}
