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
        "recent_runs": [{
            "id": str(r["_id"]), "project_id": r["project_id"], "idea": r["idea"], "status": r["status"],
            "score": ((r.get("state") or {}).get("readiness") or {}).get("total"),
            "created_at": r["created_at"].isoformat(),
        } for r in runs[:8]],
    }