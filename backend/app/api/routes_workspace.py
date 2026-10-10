"""Workspace intelligence for one run's generated files: index, impact, bounded patches, snapshots.

No route in this file calls a model, so none of them spend tokens. Reading is free. The two routes
that write reuse the same gates the AI edits use (revision cap + the `awaiting_approval` claim) and
run in the background through the pipeline, so a patched page goes back through the sanitizer, the
Chromium checks and the readiness score exactly like a build the crew made.

Everything is measured from `app/services/codebase_index.py`: a change is planned against the current
index, the whole file set is snapshotted before anything is overwritten, and `index.html` stays the
canonical document that the derived `styles.css` / `app.js` are folded back into.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.routes_runs import MEDIA, own_run
from app.core.deps import get_current_user, get_db, get_settings_dep
from app.db.models import RunOut, change_plan_out, oid, run_out, workspace_version_out
from app.orchestrator import runner
from app.services import change_impact, workspace_manager
from app.services.workspace_manager import WorkspaceError
from app.tools import differ

router = APIRouter(prefix="/api/runs/{run_id}/workspace", tags=["workspace"])

MAX_DIFF_ROWS = 60


class ChangeIn(BaseModel):
    """One named edit. `find`/`replace` for replace ops, `text` for append/set, `note` for the plan."""
    file: str = Field(min_length=1, max_length=64)
    op: str = "replace"
    find: str = ""
    replace: str = ""
    text: str = ""
    note: str = ""


class ApplyIn(BaseModel):
    changes: list[ChangeIn] = Field(min_length=1, max_length=12)
    request: str = Field(default="", max_length=500)


class RestoreIn(BaseModel):
    w: int = Field(ge=1)


def _fail(exc: WorkspaceError):
    """The service layer's error becomes the HTTP answer the caller already knows how to show."""
    raise HTTPException(exc.status, exc.message)


async def _read(request: Request, key: str) -> str:
    try:
        return (await request.app.state.storage.load(key)).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - a lost blob is a 404, never a 500
        _fail(WorkspaceError(f"That file could not be read from storage: {exc}", 404))


async def _ctx(request: Request, db, run_id: str, user):
    """Own the run, then rebuild its context the way a follow-up pipeline would."""
    await own_run(db, run_id, user)
    try:
        ctx = await runner.ctx_for(request.app.state, run_id)
    except Exception as exc:  # noqa: BLE001 - a run with nothing readable in it has no workspace
        raise HTTPException(409, f"This run's workspace could not be read: {str(exc)[:200]}") from exc
    if not ctx.state.files:
        raise HTTPException(409, "No files have been published for this run yet")
    return ctx


async def _index_of(ctx) -> dict:
    try:
        return await workspace_manager.index_workspace(ctx)
    except WorkspaceError as exc:
        _fail(exc)


def _snapshot(state: dict, w: int) -> dict:
    entry = next((v for v in state.get("workspace_versions") or [] if v.get("w") == w), None)
    if not entry:
        raise HTTPException(404, f"No workspace snapshot w{w} for this run")
    return entry


def _plans(state: dict) -> list[dict]:
    out = []
    for entry in state.get("change_plans") or []:
        try:
            out.append(change_plan_out(entry).model_dump())
        except Exception:  # noqa: BLE001 - one unreadable record must not blank the view
            out.append({"id": entry.get("id", ""), "status": "unreadable"})
    return out


# --------------------------------------------------------------------------- reading the workspace

@router.get("")
async def get_workspace(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Everything the workspace view needs in one call: files, snapshots, plans, last outcome."""
    run = await own_run(db, run_id, user)
    state = run.get("state", {})
    return {"version": state.get("html_version", 0), "revisions": state.get("revisions", 0),
            "status": run["status"],
            "files": [{"name": f["name"], "language": f["language"], "bytes": f["bytes"], "note": f["note"]}
                      for f in state.get("files") or []],
            "snapshots": [workspace_version_out(v).model_dump() for v in state.get("workspace_versions") or []],
            "latest_snapshot": max((v.get("w", 0) for v in state.get("workspace_versions") or []), default=0),
            "plans": _plans(state)[::-1],
            "impact": state.get("impact"), "changed_files": state.get("changed_files"),
            "validation": state.get("validation"),
            "limits": {"ops": list(workspace_manager.OPS), "max_changes": 12,
                       "max_patch_bytes": workspace_manager.MAX_PATCH_BYTES,
                       "keep_snapshots": workspace_manager.KEEP_WORKSPACE_VERSIONS}}


@router.get("/index")
async def get_index(run_id: str, request: Request, full: bool = Query(False),
                    db=Depends(get_db), user=Depends(get_current_user)):
    """The file/symbol/reference index of this build. Summary by default; `?full=true` for the entries."""
    ctx = await _ctx(request, db, run_id, user)
    index = await _index_of(ctx)
    out = workspace_manager.summarise_index(index)
    if full:
        out.update({"symbols": index["symbols"], "refs": index["refs"], "entries": index["files"]})
    return out


@router.get("/impact")
async def get_impact(run_id: str, request: Request, text: str = Query(min_length=3, max_length=500),
                     db=Depends(get_db), user=Depends(get_current_user)):
    """What a proposed change would touch and what it would break. Read-only: nothing is recorded."""
    ctx = await _ctx(request, db, run_id, user)
    report = change_impact.analyze(await _index_of(ctx), text, version=ctx.state.html_version)
    return {**report, "headline": change_impact.headline(report)}


# --------------------------------------------------------------------------- planning a change

@router.post("/plan")
async def plan(body: ApplyIn, run_id: str, request: Request, db=Depends(get_db),
               user=Depends(get_current_user)):
    """Measure a change set and prove every patch matches something - without writing a byte."""
    ctx = await _ctx(request, db, run_id, user)
    try:
        changes = workspace_manager.validate_changes([c.model_dump() for c in body.changes])
        ask = (body.request or "").strip() or " ".join(f"{c['file']} {c['op']}" for c in changes)
        report = change_impact.analyze(await workspace_manager.index_workspace(ctx), ask,
                                       version=ctx.state.html_version)
        ctx.state.impact = report
        before, after, _ = await workspace_manager.prepare_changes(ctx, changes)
    except WorkspaceError as exc:
        _fail(exc)

    projection = workspace_manager.stats(before, after)
    diffs = {}
    for row in projection["files"]:
        if row["status"] != "changed":
            continue
        name = row["file"]
        d = differ.diff(before.get(name, ""), after.get(name, ""), f"before/{name}", f"after/{name}")
        diffs[name] = {"added": d["added"], "removed": d["removed"], "rows": d["rows"][:MAX_DIFF_ROWS]}

    entry = workspace_manager.record_plan(
        ctx, request=ask, changes=changes, report=report, status="proposed",
        result={"files": projection["changed"], "lines_added": projection["lines_added"],
                "lines_removed": projection["lines_removed"]})
    await db.runs.update_one({"_id": oid(run_id)}, {"$set": {
        "state.change_plans": ctx.state.change_plans, "state.impact": ctx.state.impact,
        "updated_at": runner.now()}})
    return {"plan": change_plan_out(entry).model_dump(), "headline": change_impact.headline(report),
            "impact": report, "projection": projection, "diffs": diffs,
            "safe_to_apply": not report["counts"]["errors"]}


# --------------------------------------------------------------------------- applying a change

@router.post("/apply", response_model=RunOut, status_code=202)
async def apply(run_id: str, body: ApplyIn, request: Request, background: BackgroundTasks,
                db=Depends(get_db), settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """Patch the named files, then re-check the rebuilt page. Costs no tokens; capped like any edit."""
    run = await own_run(db, run_id, user)
    if run.get("state", {}).get("revisions", 0) >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). "
                                 f"Approve this version or start a new run.")
    ctx = await _ctx(request, db, run_id, user)
    try:  # validate and dry-run the whole set first, so a bad patch never flips the run out of the gate
        changes = workspace_manager.validate_changes([c.model_dump() for c in body.changes])
        await workspace_manager.prepare_changes(ctx, changes)
    except WorkspaceError as exc:
        _fail(exc)
    if not await runner.claim_for_revision(db, run_id, str(user["_id"])):
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(runner.workspace_apply_pipeline, request.app.state, run_id, changes,
                        (body.request or "").strip())
    return run_out(await own_run(db, run_id, user))


# --------------------------------------------------------------------------- snapshots

@router.get("/versions")
async def versions(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Workspace snapshots, newest first: the whole file set as it stood before each change."""
    state = (await own_run(db, run_id, user)).get("state", {})
    snapshots = [workspace_version_out(v).model_dump() for v in state.get("workspace_versions") or []]
    return {"current_version": state.get("html_version", 0),
            "kept": workspace_manager.KEEP_WORKSPACE_VERSIONS,
            "latest": max((s["w"] for s in snapshots), default=0),
            "snapshots": snapshots[::-1]}


@router.get("/versions/{w}")
async def version_detail(run_id: str, w: int, db=Depends(get_db), user=Depends(get_current_user)):
    """One snapshot: its files, sizes and digests, plus the live workspace's diff against it."""
    run = await own_run(db, run_id, user)
    state = run.get("state", {})
    entry = _snapshot(state, w)
    live = {f["name"]: f for f in state.get("files") or []}
    files = []
    for f in entry.get("files") or []:
        now_bytes = (live.get(f["name"]) or {}).get("bytes")
        files.append({"name": f["name"], "bytes": f.get("bytes", 0), "hash": f.get("hash", ""),
                      "differs_from_live": now_bytes is None or now_bytes != f.get("bytes")})
    return {"w": w, "at": entry.get("at", ""), "note": entry.get("note", ""),
            "html_version": entry.get("html_version", 0), "changed": entry.get("changed") or [],
            "files": files}


@router.get("/versions/{w}/files/{name}")
async def version_file(run_id: str, w: int, name: str, request: Request, db=Depends(get_db),
                       user=Depends(get_current_user)):
    """A file exactly as it was captured in that snapshot."""
    state = (await own_run(db, run_id, user)).get("state", {})
    try:
        cleaned = workspace_manager.validate_name(name)
    except WorkspaceError as exc:
        _fail(exc)
    entry = next((f for f in _snapshot(state, w).get("files") or [] if f["name"] == cleaned), None)
    if not entry:
        raise HTTPException(404, f"w{w} holds no {cleaned}")
    data = await _read(request, entry["key"])
    media = MEDIA.get("." + cleaned.rsplit(".", 1)[-1].lower(), "text/plain; charset=utf-8")
    return Response(data.encode("utf-8"), media_type=media)


@router.get("/diff")
async def diff(run_id: str, request: Request, w: int = Query(ge=1), to: int | None = Query(None, ge=1),
               db=Depends(get_db), user=Depends(get_current_user)):
    """Per-file diff between two snapshots, or between one snapshot and the live workspace."""
    state = (await own_run(db, run_id, user)).get("state", {})
    old_entry = _snapshot(state, w)
    old = {f["name"]: f for f in old_entry.get("files") or []}
    if to is None:
        ctx = await _ctx(request, db, run_id, user)
        try:
            new_texts = await workspace_manager.load_texts(ctx)
        except WorkspaceError as exc:
            _fail(exc)
        new_label = f"live v{state.get('html_version', 0)}"
    else:
        new_texts = {f["name"]: await _read(request, f["key"]) for f in _snapshot(state, to).get("files") or []}
        new_label = f"w{to}"

    files, added, removed = [], 0, 0
    for name in sorted(set(old) | set(new_texts)):
        a = await _read(request, old[name]["key"]) if name in old else ""
        d = differ.diff(a, new_texts.get(name, ""), f"w{w}/{name}", f"{new_label}/{name}")
        added += d["added"]
        removed += d["removed"]
        files.append({"file": name, "changed": d["changed"], "added": d["added"], "removed": d["removed"],
                      "rows": d["rows"][:MAX_DIFF_ROWS], "truncated": len(d["rows"]) > MAX_DIFF_ROWS})
    return {"from": {"w": w, "note": old_entry.get("note", ""), "html_version": old_entry.get("html_version", 0)},
            "to": new_label, "files": files, "added": added, "removed": removed,
            "changed": [f["file"] for f in files if f["changed"]]}


@router.post("/restore", response_model=RunOut, status_code=202)
async def restore(run_id: str, body: RestoreIn, request: Request, background: BackgroundTasks,
                  db=Depends(get_db), user=Depends(get_current_user)):
    """Put the whole file set back the way a snapshot held it. Costs no tokens, no revision."""
    state = (await own_run(db, run_id, user)).get("state", {})
    _snapshot(state, body.w)
    if not await runner.claim_for_revision(db, run_id, str(user["_id"])):
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(runner.workspace_restore_pipeline, request.app.state, run_id, body.w)
    return run_out(await own_run(db, run_id, user))
