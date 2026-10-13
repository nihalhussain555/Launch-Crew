"""The IDE's own feed: the projects this user owns, and the newest run of each that can really be opened.

`GET /api/projects` answers "what projects exist" and `GET /api/runs/{id}/workspace` answers "what is in
this build". The selection screen needs both at once - a card that says which run it would open, what
that run contains, and why it cannot be opened if it cannot - and asking the browser to make N+1 requests
to find that out would be slow and would show a half-drawn list. So this router does the join once, on the
server, still filtered by the caller's own user id.

Two things are deliberately not promised here. Project code is not executed (see
`/api/runs/{id}/workspace/exec`), and there is no import path yet (`/api/ide/import` says what it would
take). A card that cannot be opened says so, instead of opening an editor over an empty workspace.

The second router in this file is the assistant the IDE's right-hand panel talks to. It plans a change in
the run's own files and records it as a proposal, and only `/apply` writes - through the same patch
pipeline every other edit uses, so an AI edit gets the checkpoint before it and the sanitizer and Chromium
checks after it, and spends a revision like any other rebuild.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.base import AgentOutputError
from app.agents.ide_assistant import IdeAssistantAgent
from app.api.routes_runs import own_run
from app.api.routes_workspace import BUSY, _ctx, _diff_pair, _fail
from app.core.deps import get_current_user, get_db, get_settings_dep
from app.db.models import RunOut, oid, run_out
from app.orchestrator import runner
from app.services import change_impact, ide_assistant, workspace_manager
from app.services.workspace_manager import WorkspaceError

router = APIRouter(prefix="/api/ide", tags=["ide"])
arouter = APIRouter(prefix="/api/runs/{run_id}/ide", tags=["ide assistant"])

# The workspace a build publishes is always one self-contained page plus the assets split out of it, so
# the "framework" line can be stated from the file set rather than guessed from the brief.
STACK_STATIC = "Static HTML, CSS and JavaScript - no build step"
STACK_WITH_SOURCE = "Static page, with source files that ship beside it"
# A run whose pipeline is mid-write owns its state: the files can be read, and are refused a save until it
# reaches the approval gate again (the same guard the workspace routes enforce).
BUSY = ("queued", "running", "deploying")
RUN_CAP = 500          # runs read per request, newest first: a user with more than this sees the recent set
PROJECT_CAP = 200


def _languages(files: list[dict]) -> list[str]:
    seen = []
    for f in files or []:
        lang = (f.get("language") or "").strip()
        if lang and lang not in seen:
            seen.append(lang)
    return seen


def _run_row(doc: dict) -> dict:
    """One run as the selection screen sees it: enough to choose from, and nothing the editor re-reads anyway."""
    state = doc.get("state") or {}
    files = state.get("files") or []
    authored = state.get("authored_files") or []
    langs = _languages(files)
    readiness = (state.get("readiness") or {}).get("total")
    style = state.get("style") or {}
    status = doc.get("status") or ""
    has_page = bool(files) or bool(state.get("html_key"))
    building = status in BUSY
    if not has_page:
        reason = (f"This run failed: {str(doc.get('error') or 'unknown error')[:160]}" if status == "failed"
                  else "The crew is still building it, so no file has been published to open yet."
                  if building else "No page has been published for this run, so there is nothing to open.")
    elif building:
        reason = "The crew is mid-build: open it to read, saving resumes at the approval gate."
    else:
        reason = ""
    return {
        "run_id": str(doc["_id"]),
        "status": status,
        "idea": doc.get("idea", ""),
        "version": state.get("html_version", 0),
        "files": len(files),
        "authored": len(authored),
        "languages": langs + [l for l in _languages(authored) if l not in langs],
        "framework": STACK_WITH_SOURCE if authored else STACK_STATIC,
        "readiness": readiness,
        "style_label": style.get("label") or style.get("style_key") or "",
        "has_thumbnail": bool((state.get("screenshot_keys") or {}).get("desktop")),
        "deployed": status == "deployed",
        "shared": bool(doc.get("share_token")),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        # Openable means the editor would have something real to show. Writable adds the gate the save
        # path enforces, so a card never promises a save the run would refuse.
        "openable": has_page,
        "writable": has_page and not building,
        "blocked_reason": reason,
    }


@router.get("/projects")
async def ide_projects(db=Depends(get_db), user=Depends(get_current_user)):
    """Every project this user owns, each with the newest run the IDE could open.

    Two queries, not one per project: the runs are grouped here in the same pass that decides which one a
    card would open.
    """
    projects = [p async for p in db.projects.find({"user_id": str(user["_id"])}).sort("created_at", -1).limit(PROJECT_CAP)]
    runs = [doc async for doc in db.runs.find({"user_id": str(user["_id"])})
            .sort("updated_at", -1).limit(RUN_CAP)]
    # `runs` arrives newest-first, so the first run that qualifies is also the newest one that does.
    buckets: dict[str, dict] = {}
    for doc in runs:
        row = _run_row(doc)
        bucket = buckets.setdefault(str(doc.get("project_id") or ""), {"open": None, "count": 0, "latest": row})
        bucket["count"] += 1
        if row["openable"] and bucket["open"] is None:
            bucket["open"] = row

    out = []
    for p in projects:
        bucket = buckets.get(str(p["_id"])) or {"open": None, "count": 0, "latest": None}
        spec = p.get("spec") or {}
        chosen = bucket["open"] or bucket["latest"] or {}
        out.append({
            "project_id": str(p["_id"]),
            "name": p.get("name") or (p.get("idea") or "Untitled")[:60],
            "description": p.get("idea") or "",
            "created_at": p.get("created_at"),
            "business_type": spec.get("business_type") or "",
            "pages": len(spec.get("pages") or []) or None,
            "run_count": bucket["count"],
            "open_run": bucket["open"],
            "latest_run": bucket["latest"],
            # What the card shows and what clicking it does: an openable run, or the reason there isn't one.
            "last_modified": chosen.get("updated_at") or p.get("created_at"),
            "status": chosen.get("status") or "empty",
            "version": chosen.get("version", 0),
            "files": chosen.get("files", 0),
            "languages": chosen.get("languages") or [],
            "framework": chosen.get("framework") or "",
            "readiness": chosen.get("readiness"),
            "style_label": chosen.get("style_label") or "",
            "thumbnail": chosen.get("has_thumbnail", False),
            "can_open": bool(bucket["open"]),
            "can_write": bool(bucket["open"] and bucket["open"]["writable"]),
            "blocked_reason": "" if bucket["open"] else (chosen.get("blocked_reason")
                                                         or "This project has no runs yet. Start one and it will appear here."),
        })
    # Projects with something to edit come first: the list is a picker, not an archive.
    out.sort(key=lambda row: (not row["can_open"], row["name"].lower()))
    return {"projects": out, "limits": {"projects": PROJECT_CAP, "runs": RUN_CAP},
            "counts": {"projects": len(out), "openable": sum(1 for r in out if r["can_open"])}}


@router.get("/import")
async def import_capability(user=Depends(get_current_user)):
    """What this build can and cannot import, in the same terms as the execution report.

    A workspace here is the file set one run published: `index.html` plus the assets split out of it. An
    imported folder would have no page for the preview, the share link or the deploy to read, so accepting
    one is a build step the backend does not have - not a form to wire up and leave broken.
    """
    return {"available": False,
            "supported": [{"kind": "launch-crew project", "how": "Every project you own is already an editable "
                                     "workspace: pick it from this list and open its newest published run."}],
            "unsupported": [
                {"kind": "ZIP upload",
                 "reason": "An archive would have to be turned into a published page before the preview, share "
                           "link and deploy could read it, and no such import path exists in this backend.",
                 "would_need": "A bounded archive reader (path traversal, symlink and size guards), a page "
                               "builder that accepts existing markup, and a sanitizer pass over what it finds."},
                {"kind": "GitHub repository",
                 "reason": "Nothing in this service clones, fetches or authenticates to a git host, so there is "
                           "no repository to point an editor at.",
                 "would_need": "Per-user git credentials held server-side, a checkout area isolated from the API "
                               "process, and the same import pipeline a ZIP would need."},
            ],
            "never_auto_executes": True,
            "note": "Imported code is never run during upload, and this backend runs no project code at all."}


# --------------------------------------------------------------------------- the assistant

MAX_MODEL_REASON = 300


class AskIn(BaseModel):
    """The request, the files the user means, and the version the editor is showing."""
    instruction: str = Field(min_length=3, max_length=500)
    files: list[str] = Field(default_factory=list, max_length=ide_assistant.MAX_FILES_SENT)
    base_version: int | None = None


class ProposalIn(BaseModel):
    """Which proposal, and the version the reviewer was reading when they decided."""
    id: str = Field(min_length=1, max_length=12)
    reason: str = Field(default="", max_length=200)
    base_version: int | None = None


async def _workspace_texts(ctx) -> dict[str, str]:
    texts = await workspace_manager.load_texts(ctx)
    texts.setdefault("index.html", ctx.state.html)
    return texts


@arouter.post("/plan")
async def assistant_plan(run_id: str, body: AskIn, request: Request, db=Depends(get_db),
                         settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """Ask for a change and get the edits it implies - measured, diffed and recorded, with nothing written.

    One model call. Every change the model returns is applied to the stored text first, so a `find` that is
    not really in the file is refused with the pipeline's own message (and the model sees that message on
    its second attempt) rather than offered as a diff. The revision cap is checked here too: a run that
    cannot apply a change should not be charged for proposing one.
    """
    ctx = await _ctx(request, db, run_id, user)
    if ctx.state.revisions >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve this "
                                 f"version or start a new run before asking the assistant for a change.")
    try:
        workspace_manager.check_base(ctx.state, body.base_version)
        texts = await _workspace_texts(ctx)
        picked, clipped = ide_assistant.choose(texts, body.instruction, body.files)
        if not picked:
            raise WorkspaceError("This workspace has no files the assistant can read, so there is nothing "
                                 "to edit. Build the page first.", 409)
        index = workspace_manager.index_texts(texts, version=ctx.state.html_version)
        report = change_impact.analyze(index, body.instruction, version=ctx.state.html_version)
        ctx.state.impact = report
        ask = ide_assistant.prompt(instruction=body.instruction, texts=texts, picked=picked, clipped=clipped,
                                   impact=report.get("block") or "")
        try:
            verified = await IdeAssistantAgent().patch(ctx, user=ask, texts=texts, allowed=picked)
        except AgentOutputError as exc:
            raise WorkspaceError(f"The assistant produced no edit that fits these files: "
                                 f"{str(exc)[:MAX_MODEL_REASON]}", 502) from exc
        before, after, _page = await workspace_manager.prepare_changes(ctx, verified["changes"])
    except WorkspaceError as exc:
        _fail(exc)

    projection = workspace_manager.stats(before, after)
    diffs = {name: _diff_pair(before.get(name, ""), after.get(name, ""), f"before/{name}", f"after/{name}")
             for name in projection["changed"]}
    rows = ide_assistant.affected(verified)
    entry = ide_assistant.record_proposal(ctx, instruction=body.instruction, verified=verified, rows=rows,
                                          report=report, sent=picked, clipped=clipped)
    await db.runs.update_one({"_id": oid(run_id)}, {"$set": {
        "state.ide_edits": ctx.state.ide_edits, "state.impact": ctx.state.impact,
        "updated_at": runner.now()}})
    return {"proposal": entry, "diffs": diffs, "projection": projection, "affected": rows,
            "impact": report, "headline": change_impact.headline(report),
            "sent_files": picked, "clipped_files": clipped,
            "base_version": ctx.state.html_version, "undo": workspace_manager.undo_status(ctx.state),
            "safe_to_apply": not report["counts"]["errors"],
            "applies_through": "the patch pipeline: a checkpoint first, then the sanitizer, the Chromium "
                               "checks and a new page version",
            "limits": {"max_changes": 12, "max_instruction_chars": ide_assistant.MAX_INSTRUCTION_CHARS,
                       "max_files_sent": ide_assistant.MAX_FILES_SENT,
                       "revisions_left": max(settings.max_revisions - ctx.state.revisions, 0)}}


@arouter.get("/proposals")
async def assistant_proposals(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Every change this run's assistant has offered, newest first, with what became of each one."""
    state = (await own_run(db, run_id, user)).get("state", {})
    entries = state.get("ide_edits") or []
    return {"version": state.get("html_version", 0), "proposals": entries[::-1]}


@arouter.post("/apply", response_model=RunOut, status_code=202)
async def assistant_apply(run_id: str, body: ProposalIn, request: Request, background: BackgroundTasks,
                          db=Depends(get_db), settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """Write a proposal the user has read. Re-measured here: it must still mean the edit that was approved.

    The stored change set is applied to the current text again before anything is claimed, so a file that
    moved since the proposal was made produces a conflict rather than a silent overwrite. The page rebuild
    that follows is the workspace pipeline's own, and it is the run's approval gate that lets it start.
    """
    run = await own_run(db, run_id, user)
    if run.get("state", {}).get("revisions", 0) >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve this "
                                 f"version or start a new run.")
    ctx = await _ctx(request, db, run_id, user)
    try:
        entry = ide_assistant.find_entry(ctx.state, body.id)
        if entry.get("status") != "proposed":
            raise WorkspaceError(f"Proposal {entry['id']} was already {entry.get('status')}. Ask the "
                                 f"assistant again to change this workspace.", 409)
        workspace_manager.check_base(ctx.state, body.base_version)
        if entry.get("version") != ctx.state.html_version:
            raise WorkspaceError(f"Conflict: proposal {entry['id']} was read at v{entry.get('version')} but "
                                 f"the page is now v{ctx.state.html_version}. Ask again to see the change "
                                 f"against what is stored.", 409)
        texts = await _workspace_texts(ctx)
        # Re-measured against the scope the reviewer actually read: a proposal that edits a file which was
        # never sent could not have been reviewed, whatever the stored change set says.
        verified = ide_assistant.verify({"summary": entry.get("summary") or "", "changes": entry["changes"]},
                                        texts, allowed=entry.get("sent_files"))
        await workspace_manager.prepare_changes(ctx, verified["changes"])
    except WorkspaceError as exc:
        _fail(exc)

    ide_assistant.mark_proposal(entry, "applying")
    await db.runs.update_one({"_id": oid(run_id)},
                             {"$set": {"state.ide_edits": ctx.state.ide_edits, "updated_at": runner.now()}})
    if not await runner.claim_for_revision(db, run_id, str(user["_id"])):
        ide_assistant.mark_proposal(entry, "proposed")
        await db.runs.update_one({"_id": oid(run_id)},
                                 {"$set": {"state.ide_edits": ctx.state.ide_edits}})
        raise HTTPException(409, "Run is not awaiting approval - the assistant applies its edit at the "
                                 "review gate, where a page can be rebuilt.")
    background.add_task(runner.ide_apply_pipeline, request.app.state, run_id, verified["changes"],
                        entry["instruction"], entry["id"])
    return run_out(await own_run(db, run_id, user))


@arouter.post("/reject")
async def assistant_reject(run_id: str, body: ProposalIn, request: Request, db=Depends(get_db),
                           user=Depends(get_current_user)):
    """Turn a proposal down. No file is touched; the record says it was rejected, and why if told."""
    run = await own_run(db, run_id, user)
    if run["status"] in BUSY:
        raise HTTPException(409, f"The crew is {run['status']} on this run right now. Reject the proposal "
                                 f"once it is back at the approval gate.")
    ctx = await _ctx(request, db, run_id, user)
    try:
        entry = ide_assistant.find_entry(ctx.state, body.id)
        if entry.get("status") != "proposed":
            raise WorkspaceError(f"Proposal {entry['id']} is already {entry.get('status')}.", 409)
        ide_assistant.mark_proposal(entry, "rejected", reason=body.reason[:200])
    except WorkspaceError as exc:
        _fail(exc)
    await db.runs.update_one({"_id": oid(run_id)},
                             {"$set": {"state.ide_edits": ctx.state.ide_edits, "updated_at": runner.now()}})
    return {"proposal": entry, "undo": workspace_manager.undo_status(ctx.state)}

