from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.deps import get_current_user, get_db, get_settings_dep
from app.db.models import RunOut, oid, run_out
from app.orchestrator.graph import AUDIT_ORDER, infer_target
from app.orchestrator.runner import (audit_pipeline, claim_for_deploy, claim_for_revision, debug_pipeline,
                                     launch_pipeline, repair_pipeline, restore_pipeline, revise_pipeline)
from app.tools import differ

router = APIRouter(prefix="/api/runs", tags=["runs"])

MEDIA = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".md": "text/markdown; charset=utf-8",
         ".py": "text/x-python; charset=utf-8"}

AuditKind = Literal["security", "seo", "accessibility", "performance", "dependency", "tests"]


class ReviseIn(BaseModel):
    instruction: str = Field(min_length=3, max_length=500)
    target: Literal["page", "copy", "design"] = "page"


class AuditIn(BaseModel):
    """Which audit agents to run; defaults to all six. Unknown names are rejected by the model."""
    agents: list[AuditKind] = Field(default_factory=lambda: list(AUDIT_ORDER))

    def kinds(self) -> list[str]:
        return [k for k in AUDIT_ORDER if k in set(self.agents)]


class ChatIn(BaseModel):
    text: str = Field(min_length=3, max_length=500)


class RestoreIn(BaseModel):
    version: int = Field(ge=1)


async def own_run(db, run_id: str, user) -> dict:
    r = await db.runs.find_one({"_id": oid(run_id), "user_id": str(user["_id"])})
    if not r:
        raise HTTPException(404, "Run not found")
    return r


def _file(state: dict, name: str) -> dict:
    entry = next((f for f in state.get("files") or [] if f.get("name") == name), None)
    if not entry:
        raise HTTPException(404, "That file is not in this run's workspace")
    return entry


def _version(state: dict, version: int) -> dict:
    entry = next((v for v in state.get("versions") or [] if v.get("v") == version), None)
    if not entry:
        raise HTTPException(404, f"No snapshot for v{version}")
    return entry


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    return run_out(await own_run(db, run_id, user))


@router.post("/{run_id}/approve", response_model=RunOut, status_code=202)
async def approve(run_id: str, request: Request, background: BackgroundTasks, db=Depends(get_db), user=Depends(get_current_user)):
    """Human approval gate: nothing is deployed unless the run is 'awaiting_approval' AND the user calls this."""
    await own_run(db, run_id, user)
    if not await claim_for_deploy(db, run_id, str(user["_id"])):
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(launch_pipeline, request.app.state, run_id)
    return run_out(await own_run(db, run_id, user))


@router.post("/{run_id}/revise", response_model=RunOut, status_code=202)
async def revise(run_id: str, body: ReviseIn, request: Request, background: BackgroundTasks, db=Depends(get_db),
                 settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """Ask the crew to change the page/copy/design before approving. Capped by MAX_REVISIONS per run."""
    run = await own_run(db, run_id, user)
    if run.get("state", {}).get("revisions", 0) >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve this version or start a new run.")
    if not await claim_for_revision(db, run_id, str(user["_id"])):
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(revise_pipeline, request.app.state, run_id, body.instruction.strip(), body.target)
    return run_out(await own_run(db, run_id, user))


@router.get("/{run_id}/html")
async def get_html(run_id: str, request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    run = await own_run(db, run_id, user)
    key = run.get("state", {}).get("html_key")
    if not key:
        raise HTTPException(404, "No page generated yet")
    data = await request.app.state.storage.load(key)
    return Response(data, media_type="text/plain; charset=utf-8")  # text/plain: client renders it in a sandboxed iframe


@router.get("/{run_id}/screenshots/{viewport}")
async def get_screenshot(run_id: str, viewport: str, request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    run = await own_run(db, run_id, user)
    key = run.get("state", {}).get("screenshot_keys", {}).get(viewport)
    if not key:
        raise HTTPException(404, "Screenshot not available")
    return Response(await request.app.state.storage.load(key), media_type="image/jpeg")


# --------------------------------------------------------------------------- workspace: files

@router.get("/{run_id}/files")
async def list_files(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """The run's generated file set (metadata only; content comes from /files/{name})."""
    state = (await own_run(db, run_id, user)).get("state", {})
    return {"version": state.get("html_version", 0),
            "files": [{"name": f["name"], "language": f["language"], "bytes": f["bytes"], "note": f["note"]}
                      for f in state.get("files") or []]}


@router.get("/{run_id}/files.zip")
async def download_zip(run_id: str, request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    """Every workspace file in one download, built on demand from stored artifacts."""
    import io
    import zipfile

    run = await own_run(db, run_id, user)
    state = run.get("state", {})
    files = state.get("files") or []
    if not files:
        raise HTTPException(404, "No files generated yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.writestr(f["name"], await request.app.state.storage.load(f["key"]))
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in run["idea"][:40]).strip("-").lower() or "page"
    name = f"{slug}-v{state.get('html_version', 1)}.zip"
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"content-disposition": f'attachment; filename="{name}"'})


@router.get("/{run_id}/files/{name}")
async def get_file(run_id: str, name: str, request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    """One workspace file, by exact name from the recorded set (never a path lookup)."""
    state = (await own_run(db, run_id, user)).get("state", {})
    entry = _file(state, name)
    data = await request.app.state.storage.load(entry["key"])
    media = MEDIA.get("." + name.rsplit(".", 1)[-1].lower(), "text/plain; charset=utf-8")
    return Response(data, media_type=media)


# --------------------------------------------------------------------------- workspace: versions

@router.get("/{run_id}/versions")
async def list_versions(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    state = (await own_run(db, run_id, user)).get("state", {})
    current = state.get("html_version", 0)
    versions = [{**{k: v[k] for k in ("v", "at", "note", "bytes", "errors", "warnings", "readiness")},
                 "current": v["v"] == current,
                 "files": v.get("files", [])} for v in state.get("versions") or []]
    return {"current": current, "revisions": state.get("revisions", 0), "versions": versions[::-1]}


@router.get("/{run_id}/versions/{version}/html")
async def get_version_html(run_id: str, version: int, request: Request, db=Depends(get_db),
                           user=Depends(get_current_user)):
    state = (await own_run(db, run_id, user)).get("state", {})
    entry = _version(state, version)
    return Response(await request.app.state.storage.load(entry["key"]), media_type="text/plain; charset=utf-8")


@router.get("/{run_id}/diff")
async def get_diff(run_id: str, request: Request, frm: int = Query(alias="from"), to: int = Query(),
                   db=Depends(get_db), user=Depends(get_current_user)):
    """Git-style unified diff between two saved versions of this run's page."""
    state = (await own_run(db, run_id, user)).get("state", {})
    old, new = _version(state, frm), _version(state, to)
    a = (await request.app.state.storage.load(old["key"])).decode("utf-8")
    b = (await request.app.state.storage.load(new["key"])).decode("utf-8")
    d = differ.diff(a, b, f"v{frm}", f"v{to}")
    return {"from": {"v": frm, "note": old.get("note"), "at": old.get("at")},
            "to": {"v": to, "note": new.get("note"), "at": new.get("at")},
            **d, **differ.stats(a, b)}


# --------------------------------------------------------------------------- workspace: AI actions

@router.post("/{run_id}/chat", response_model=RunOut, status_code=202)
async def chat(run_id: str, body: ChatIn, request: Request, background: BackgroundTasks, db=Depends(get_db),
               settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """Conversational editing: say what to change in plain words; the crew routes it to the right agent."""
    run = await own_run(db, run_id, user)
    if run.get("state", {}).get("revisions", 0) >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve this version or start a new run.")
    target = infer_target(body.text)
    if not await claim_for_revision(db, run_id, str(user["_id"])):
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(revise_pipeline, request.app.state, run_id, body.text.strip(), target)
    return run_out(await own_run(db, run_id, user))


@router.post("/{run_id}/debug", response_model=RunOut, status_code=202)
async def debug(run_id: str, request: Request, background: BackgroundTasks, db=Depends(get_db),
                user=Depends(get_current_user)):
    """Autonomous debugging: re-run the browser checks and let the crew repair what they find."""
    await own_run(db, run_id, user)
    if not await claim_for_revision(db, run_id, str(user["_id"])):
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(debug_pipeline, request.app.state, run_id)
    return run_out(await own_run(db, run_id, user))


@router.post("/{run_id}/restore", response_model=RunOut, status_code=202)
async def restore(run_id: str, body: RestoreIn, request: Request, background: BackgroundTasks, db=Depends(get_db),
                  user=Depends(get_current_user)):
    """Roll the page back to a saved version. Costs no tokens; checks and score are recomputed."""
    run = await own_run(db, run_id, user)
    _version(run.get("state", {}), body.version)
    if body.version == run.get("state", {}).get("html_version"):
        raise HTTPException(409, f"v{body.version} is already the current version")
    if not await claim_for_revision(db, run_id, str(user["_id"])):
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(restore_pipeline, request.app.state, run_id, body.version)
    return run_out(await own_run(db, run_id, user))


@router.post("/{run_id}/audit", response_model=RunOut, status_code=202)
async def audit(run_id: str, body: AuditIn, request: Request, background: BackgroundTasks, db=Depends(get_db),
                user=Depends(get_current_user)):
    """Run the audit crew against the live page. Deterministic, no LLM, so it costs no tokens."""
    await own_run(db, run_id, user)
    if not body.kinds():
        raise HTTPException(422, "Pick at least one audit")
    if not await claim_for_revision(db, run_id, str(user["_id"])):
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(audit_pipeline, request.app.state, run_id, body.kinds())
    return run_out(await own_run(db, run_id, user))


@router.post("/{run_id}/audit/repair", response_model=RunOut, status_code=202)
async def audit_repair(run_id: str, body: AuditIn, request: Request, background: BackgroundTasks,
                       db=Depends(get_db), settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """Apply the current audits' fix instructions, rebuild the page, then re-run those same audits."""
    run = await own_run(db, run_id, user)
    state = run.get("state", {})
    if state.get("revisions", 0) >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve this version or start a new run.")
    current = state.get("html_version", 0)
    open_findings = [k for k in body.kinds()
                     if (state.get("audits", {}).get(k) or {}).get("version") == current
                     and (state.get("audits", {}).get(k) or {}).get("fixes")]
    if not open_findings:
        raise HTTPException(409, "No current audit findings to repair - run the audits first.")
    if not await claim_for_revision(db, run_id, str(user["_id"])):
        raise HTTPException(409, "Run is not awaiting approval")
    background.add_task(repair_pipeline, request.app.state, run_id, open_findings)
    return run_out(await own_run(db, run_id, user))


@router.get("/{run_id}/tests")
async def get_tests(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """The generated suite's result: pass/fail counts and every case, from the run that executed it."""
    tests = (await own_run(db, run_id, user)).get("state", {}).get("tests")
    if not tests:
        raise HTTPException(404, "No generated test suite yet - run the tester audit first")
    return {k: v for k, v in tests.items() if k != "file"}


@router.get("/{run_id}/tests/file")
async def get_tests_file(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """The generated regression suite as a downloadable Python file."""
    tests = (await own_run(db, run_id, user)).get("state", {}).get("tests") or {}
    entry = tests.get("file") or {}
    if not entry.get("text"):
        raise HTTPException(404, "No generated test suite yet - run the tester audit first")
    return Response(entry["text"], media_type=MEDIA[".py"],
                    headers={"content-disposition": 'attachment; filename="test_page.py"'})