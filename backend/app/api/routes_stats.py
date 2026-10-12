from fastapi import APIRouter, Depends

from app.core.deps import get_current_user, get_db

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats")
async def stats(db=Depends(get_db), user=Depends(get_current_user)):
    uid = str(user["_id"])
    projects = await db.projects.count_documents({"user_id": uid})
    runs = [r async for r in db.runs.find({"user_id": uid}).sort("created_at", -1).limit(500)]
    scores = [r["state"]["readiness"]["total"] for r in runs if ((r.get("state") or {}).get("readiness"))]
    return {
        "projects": projects,
        "runs": len(runs),
        "deployed": sum(1 for r in runs if r["status"] == "deployed"),
        "tokens": sum(r.get("tokens_used", 0) for r in runs),
        "avg_readiness": round(sum(scores) / len(scores)) if scores else None,
        # Feature work, counted out of the run's own record. Deliberately not a claim about liveness:
        # whether a page still carries its panels needs the stored page, so no field here implies it -
        # the workspace's Feature studio reads that from the page and says so.
        "recent_runs": [{
            "id": str(r["_id"]), "project_id": r["project_id"], "idea": r["idea"], "status": r["status"],
            "score": ((r.get("state") or {}).get("readiness") or {}).get("total"),
            "created_at": r["created_at"].isoformat(),
            "feature_asked": len((((r.get("state") or {}).get("spec") or {}).get("feature_keys")) or []),
            "feature_open": sum(1 for e in ((r.get("state") or {}).get("feature_edits") or [])
                                if e.get("status") in ("proposed", "applying")),
            "feature_built": sum(1 for e in ((r.get("state") or {}).get("feature_edits") or [])
                                 if e.get("status") == "applied"),
        } for r in runs[:8]],
    }