from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response

from app.agents import styles as design_styles
from app.core.deps import get_current_user, get_db, get_settings_dep
from app.core.rate_limit import check_run_quota
from app.db.models import (CompareIn, ProjectCreate, ProjectOut, RunIn, RunOut, oid, project_out, run_out,
                           run_summary)
from app.orchestrator.runner import now, run_pipeline

router = APIRouter(prefix="/api/projects", tags=["projects"])
ACTIVE = ("queued", "running", "deploying")


async def _own_project(db, project_id: str, user) -> dict:
    p = await db.projects.find_one({"_id": oid(project_id), "user_id": str(user["_id"])})
    if not p:
        raise HTTPException(404, "Project not found")
    return p


async def _start_run(app_state, db, request: Request, background: BackgroundTasks, project: dict,
                     spec: dict, settings, user, *, check_quota: bool = True) -> dict:
    """Queue one run for this project under the given brief, and start it in the background."""
    if check_quota:
        await check_run_quota(db, user["_id"], settings.runs_per_hour)       # guardrail: per-user rate limit
    doc = {"project_id": str(project["_id"]), "user_id": str(user["_id"]), "idea": project["idea"],
           "spec": spec, "status": "queued",
           "state": {}, "tokens_used": 0, "steps": 0, "event_seq": 0, "error": None,
           "created_at": now(), "updated_at": now()}
    doc["_id"] = (await db.runs.insert_one(doc)).inserted_id
    background.add_task(run_pipeline, app_state, str(doc["_id"]))
    return doc


@router.get("", response_model=list[ProjectOut])
async def list_projects(db=Depends(get_db), user=Depends(get_current_user)):
    cur = db.projects.find({"user_id": str(user["_id"])}).sort("created_at", -1).limit(100)
    return [project_out(p) async for p in cur]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, db=Depends(get_db), user=Depends(get_current_user)):
    """Create a project from the wizard's answers. `spec` is stored verbatim so every later run,
    template use and regeneration starts from the same brief."""
    idea = body.idea.strip()
    spec = body.spec.model_dump()
    # With an explicit style the section plan is settled now and stored: the sections the brief asked
    # for plus the ones that style carries by default. With no style the list stays exactly as the brief
    # wrote it, so the direction of whichever style the run picks can add its own defaults at build time.
    if spec["style"]:
        planned = set(spec["sections"]) | set(design_styles.resolve_sections(
            spec["business_type"], spec["features"], spec["style"]))
        spec["sections"] = [s for s in design_styles.OPTIONAL_SECTIONS if s in planned]
    spec["pages"] = spec["pages"] or list(design_styles.pages_for(spec["business_type"]))
    doc = {"user_id": str(user["_id"]), "idea": idea, "name": body.name.strip() or idea[:60],
           "spec": spec, "created_at": now()}
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
        for key in [st.get("html_key"),
                    *(f.get("key") for f in st.get("files") or []),
                    *(v.get("key") for v in st.get("versions") or []),
                    *(st.get("screenshot_keys") or {}).values()]:
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
                     settings=Depends(get_settings_dep), user=Depends(get_current_user),
                     body: RunIn | None = None):
    """Start a run for the project's brief. The body is optional: a plain POST still means
    "run the stored brief as-is", exactly as before the wizard existed."""
    project = await _own_project(db, project_id, user)
    spec = (body or RunIn()).merged_with(project.get("spec") or {})
    doc = await _start_run(request.app.state, db, request, background, project, spec, settings, user)
    return run_out(doc)


@router.post("/{project_id}/compare", status_code=202)
async def compare_styles(project_id: str, body: CompareIn, request: Request, background: BackgroundTasks,
                         db=Depends(get_db), settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """Start one run per style on the same brief, so variations can be judged side by side.

    Each of these is an ordinary run: same agents, same Chromium checks, same approval gate. The
    comparison is real generated pages rather than mock-ups, which is also why the batch is bounded
    by the run quota up front instead of starting what it cannot afford.
    """
    project = await _own_project(db, project_id, user)
    unknown = [s for s in body.styles if design_styles.get(s) is None]
    if unknown:
        raise HTTPException(422, f"Unknown style(s): {', '.join(unknown)}")
    await check_run_quota(db, user["_id"], settings.runs_per_hour, needed=len(body.styles))
    spec = dict(project.get("spec") or {})
    started = []
    for style in body.styles:
        doc = await _start_run(request.app.state, db, request, background, project,
                               {**spec, "style": style}, settings, user, check_quota=False)
        started.append({"run_id": str(doc["_id"]), "style": style, "label": design_styles.get(style).label})
    return {"project_id": project_id, "runs": started}