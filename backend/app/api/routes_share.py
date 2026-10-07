"""Shareable preview links + stakeholder feedback.

Owner (JWT):  POST/DELETE /api/runs/{id}/share · GET /api/runs/{id}/feedback · POST /api/runs/{id}/feedback/apply
Public (token only, rate-limited):  GET /api/public/{token} · GET /api/public/{token}/html · POST /api/public/{token}/feedback

The public HTML is returned as text/plain and rendered by the client inside a sandboxed iframe (srcDoc),
so generated pages never execute on the API origin.
"""
import secrets
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.routes_runs import own_run
from app.core.deps import get_current_user, get_db, get_settings_dep
from app.core.rate_limit import SlidingWindowLimiter
from app.db.models import RunOut, oid, run_out
from app.orchestrator.runner import claim_for_revision, now, revise_pipeline

router = APIRouter(tags=["share"])
_fb_limiter = SlidingWindowLimiter(limit=6, window_s=600)   # per IP: 6 feedback posts / 10 min
MAX_FEEDBACK_PER_RUN = 100


class FeedbackIn(BaseModel):
    name: str = Field(default="", max_length=60)
    message: str = Field(min_length=3, max_length=600)
    rating: int | None = Field(default=None, ge=1, le=5)


class ApplyIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=20)
    target: Literal["page", "copy", "design"] = "page"


def _ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for", "").split(",")[0].strip()) or (request.client.host if request.client else "?")


def _fb_out(d: dict) -> dict:
    return {"id": str(d["_id"]), "name": d.get("name", ""), "message": d["message"], "rating": d.get("rating"),
            "applied": bool(d.get("applied")), "created_at": d["created_at"].isoformat()}


async def _shared_run(db, token: str) -> dict:
    run = await db.runs.find_one({"share_token": token}) if token else None
    if not run or not (run.get("state") or {}).get("html_key"):
        raise HTTPException(404, "This preview link is invalid or has been revoked")
    return run


# ------------------------------------------------------------------ owner
@router.post("/api/runs/{run_id}/share")
async def create_share(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    run = await own_run(db, run_id, user)
    if not (run.get("state") or {}).get("html_key"):
        raise HTTPException(409, "Nothing to share yet - the page has not been generated")
    token = run.get("share_token") or secrets.token_urlsafe(16)
    await db.runs.update_one({"_id": run["_id"]}, {"$set": {"share_token": token}})
    return {"token": token, "path": f"/p/{token}"}


@router.delete("/api/runs/{run_id}/share", status_code=204)
async def revoke_share(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    run = await own_run(db, run_id, user)
    await db.runs.update_one({"_id": run["_id"]}, {"$unset": {"share_token": ""}})
    return Response(status_code=204)


@router.get("/api/runs/{run_id}/feedback")
async def list_feedback(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    await own_run(db, run_id, user)
    return [_fb_out(d) async for d in db.feedback.find({"run_id": run_id}).sort("created_at", -1).limit(200)]


@router.post("/api/runs/{run_id}/feedback/apply", response_model=RunOut, status_code=202)
async def apply_feedback(run_id: str, body: ApplyIn, request: Request, background: BackgroundTasks, db=Depends(get_db),
                         settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """Turn pending stakeholder feedback into an AI revision (same guarded path as /revise)."""
    run = await own_run(db, run_id, user)
    query: dict = {"run_id": run_id, "applied": False}
    if body.ids:
        query["_id"] = {"$in": [oid(i) for i in body.ids]}
    items = [d async for d in db.feedback.find(query).sort("created_at", 1).limit(8)]
    if not items:
        raise HTTPException(404, "No pending feedback to apply")
    if (run.get("state") or {}).get("revisions", 0) >= settings.max_revisions:
        raise HTTPException(429, f"Revision limit reached ({settings.max_revisions} per run). Approve this version or start a new run.")
    if not await claim_for_revision(db, run_id, str(user["_id"])):
        raise HTTPException(409, "Run is not awaiting approval")
    instruction = "Address this stakeholder feedback: " + " | ".join(f'"{d["message"][:110]}"' for d in items)
    await db.feedback.update_many({"_id": {"$in": [d["_id"] for d in items]}}, {"$set": {"applied": True}})
    background.add_task(revise_pipeline, request.app.state, run_id, instruction[:490], body.target)
    return run_out(await own_run(db, run_id, user))


# ------------------------------------------------------------------ public
@router.get("/api/public/{token}")
async def public_info(token: str, db=Depends(get_db)):
    run = await _shared_run(db, token)
    st = run.get("state") or {}
    content = st.get("content") or {}
    return {"product_name": content.get("product_name") or "Landing page preview", "headline": content.get("headline", ""),
            "html_version": st.get("html_version", 1), "updated_at": (run.get("updated_at") or run["created_at"]).isoformat()}


@router.get("/api/public/{token}/html")
async def public_html(token: str, request: Request, db=Depends(get_db)):
    run = await _shared_run(db, token)
    data = await request.app.state.storage.load(run["state"]["html_key"])
    return Response(data, media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@router.post("/api/public/{token}/feedback", status_code=201)
async def public_feedback(token: str, body: FeedbackIn, request: Request, db=Depends(get_db)):
    _fb_limiter.check(_ip(request))
    run = await _shared_run(db, token)
    run_id = str(run["_id"])
    if await db.feedback.count_documents({"run_id": run_id}) >= MAX_FEEDBACK_PER_RUN:
        raise HTTPException(429, "This page has reached its feedback limit")
    await db.feedback.insert_one({"run_id": run_id, "name": body.name.strip(), "message": body.message.strip(),
                                  "rating": body.rating, "applied": False, "created_at": now()})
    return {"ok": True}