from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response

from app.core.deps import get_current_user, get_db, get_settings_dep
from app.core.rate_limit import check_run_quota
from app.db.models import ProjectCreate, ProjectOut, RunOut, oid, project_out, run_out, run_summary
from app.orchestrator.runner import now, run_pipeline

router = APIRouter(prefix="/api/projects", tags=["projects"])
ACTIVE = ("queued", "running", "deploying")


async def _own_project(db, project_id: str, user) -> dict:
    p = await db.projects.find_one({"_id": oid(project_id), "user_id": str(user["_id"])})
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@router.get("", response_model=list[ProjectOut])
async def list_projects(db=Depends(get_db), user=Depends(get_current_user)):
    cur = db.projects.find({"user_id": str(user["_id"])}).sort("created_at", -1).limit(100)
    return [project_out(p) async for p in cur]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, db=Depends(get_db), user=Depends(get_current_user)):
    idea = body.idea.strip()
    doc = {"user_id": str(user["_id"]), "idea": idea, "name": body.name.strip() or idea[:60], "created_at": now()}
    doc["_id"] = (await db.projects.insert_one(doc)).inserted_id
    return project_out(doc)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    p = await _own_project(db, project_id, user)
    runs = [run_summary(r) async for r in db.runs.find({"project_id": project_id}).sort("created_at", -1).limit(30)]
    return project_out(p, runs)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    """Delete a project with all its runs, events, feedback and stored files."""
    await _own_project(db, project_id, user)
    runs = [r async for r in db.runs.find({"project_id": project_id})]
    if any(r["status"] in ACTIVE for r in runs):
        raise HTTPException(409, "A run is still in progress. Wait for it to finish, then delete.")
    storage = request.app.state.storage
    for r in runs:
        rid, st = str(r["_id"]), r.get("state") or {}
        for key in [st.get("html_key"), *(st.get("screenshot_keys") or {}).values()]:
            if key:
                try:
                    await storage.delete(key)
                except Exception:  # noqa: BLE001 - best effort; never block deletion on storage
                    pass
        await db.run_events.delete_many({"run_id": rid})
        await db.feedback.delete_many({"run_id": rid})
    await db.runs.delete_many({"project_id": project_id})
    await db.projects.delete_one({"_id": oid(project_id)})
    return Response(status_code=204)


@router.post("/{project_id}/runs", response_model=RunOut, status_code=202)
async def create_run(project_id: str, request: Request, background: BackgroundTasks, db=Depends(get_db),
                     settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    project = await _own_project(db, project_id, user)
    await check_run_quota(db, user["_id"], settings.runs_per_hour)           # guardrail: per-user rate limit
    doc = {"project_id": project_id, "user_id": str(user["_id"]), "idea": project["idea"], "status": "queued",
           "state": {}, "tokens_used": 0, "steps": 0, "event_seq": 0, "error": None, "created_at": now(), "updated_at": now()}
    doc["_id"] = (await db.runs.insert_one(doc)).inserted_id
    background.add_task(run_pipeline, request.app.state, str(doc["_id"]))
    return run_out(doc)