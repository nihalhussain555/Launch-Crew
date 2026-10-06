from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.deps import get_current_user, get_db, get_settings_dep
from app.db.models import RunOut, oid, run_out
from app.orchestrator.runner import claim_for_deploy, claim_for_revision, launch_pipeline, revise_pipeline

router = APIRouter(prefix="/api/runs", tags=["runs"])


class ReviseIn(BaseModel):
    instruction: str = Field(min_length=3, max_length=500)
    target: Literal["page", "copy", "design"] = "page"


async def own_run(db, run_id: str, user) -> dict:
    r = await db.runs.find_one({"_id": oid(run_id), "user_id": str(user["_id"])})
    if not r:
        raise HTTPException(404, "Run not found")
    return r


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