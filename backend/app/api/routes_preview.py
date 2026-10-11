"""Preview routes: start, check, refresh and stop a preview of one run's published page.

Owner (JWT)  GET/POST/DELETE /api/runs/{id}/preview
Public (one expiring ticket, rate limited per IP)  GET /api/preview/{token}

The owner routes only read state - no pipeline runs, no tokens are spent, nothing is rebuilt. "Refresh" is
another read of the published file, which is why an applied change shows up without restarting generation.

The public route serves the stored page with `Content-Security-Policy: sandbox allow-scripts`, so even when
the app and the API share one origin in production the previewed document gets an opaque origin of its own:
it cannot read this app's tokens, cookies, environment values or internal APIs. The ticket is a random token
held only as a digest, scoped to one run and one file, expiring on a clock and revocable by its owner. A file
set this environment cannot run is refused at `POST` with the reason, so no half-rendered page is ever
presented as a preview.
"""
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.api.routes_runs import own_run
from app.core.deps import get_current_user, get_db, get_settings_dep
from app.core.rate_limit import SlidingWindowLimiter
from app.orchestrator.runner import now
from app.services import preview

router = APIRouter(tags=["preview"])

# A ticket is one person looking at one page for a few minutes. This limiter is not the protection - the
# 29-character random token is - it only stops someone using the route to probe for live links.
_look_limiter = SlidingWindowLimiter(limit=60, window_s=60)
SANDBOX_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
}
GONE = "This preview link is invalid or has expired."


def _ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for", "").split(",")[0].strip()) or (
        request.client.host if request.client else "?")


def _when(value):
    """Mongo hands back naive UTC while the app clock is aware: normalise before comparing the two."""
    if value is None or getattr(value, "tzinfo", None) is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _page(state: dict) -> dict | None:
    """The canonical file exactly as the workspace published it: where it lives, how big, which version."""
    key = state.get("html_key")
    if not key:
        return None
    entry = next((f for f in state.get("files") or [] if f.get("name") == preview.CANONICAL), None)
    return {"key": key, "name": preview.CANONICAL, "bytes": (entry or {}).get("bytes", 0),
            "version": state.get("html_version", 0)}


def _build(state: dict) -> dict:
    """What the real Chromium pass and the sanitizer said about the page this preview would show."""
    results = state.get("check_results") or []
    summary = state.get("check_summary") or {}
    failed = [{"id": c.get("id", ""), "label": c.get("label", ""), "viewport": c.get("viewport", ""),
               "severity": c.get("severity", "error"), "detail": c.get("detail", "")}
              for c in results if not c.get("passed")]
    return {"checks": summary.get("total", len(results)),
            "errors": summary.get("errors", sum(1 for c in failed if c["severity"] == "error")),
            "warnings": summary.get("warnings", sum(1 for c in failed if c["severity"] == "warning")),
            "failed": failed[:12],
            "readiness": (state.get("readiness") or {}).get("total"),
            "sanitizer_violations": (state.get("sanitizer_violations") or [])[:8]}


async def _live_tickets(db, run_id: str, at) -> list[dict]:
    """Unexpired links for this run. Expired ones are dropped here, so the collection cannot silt up
    even on a deployment whose Mongo TTL index has not been created yet."""
    live, gone = [], []
    for d in [d async for d in db.previews.find({"run_id": run_id})]:
        (live if _when(d.get("exp")) and _when(d["exp"]) > at else gone).append(d["_id"])
    if gone:
        await db.previews.delete_many({"_id": {"$in": gone}})
    return live


def _out(run: dict, page: dict | None, verdict: dict, active: int, settings,
         ticket: dict | None = None) -> dict:
    state = run.get("state") or {}
    return {"run_id": str(run["_id"]), "status": run["status"], "version": state.get("html_version", 0),
            "files": [{"name": f.get("name", ""), "language": f.get("language", ""),
                       "bytes": f.get("bytes", 0)} for f in state.get("files") or []],
            "preview": {"supported": verdict["supported"], "kind": verdict["kind"],
                        "reason": verdict["reason"], "entry": verdict["entry"],
                        "blocked": verdict["blocked"]},
            "page": page, "build": _build(state), "ticket": ticket,
            "tickets": {"active": active, "per_run": settings.preview_tickets_per_run,
                        "ttl_seconds": settings.preview_ttl_seconds},
            "runtime_channel": "postMessage"}


@router.get("/api/runs/{run_id}/preview")
async def preview_status(run_id: str, db=Depends(get_db), settings=Depends(get_settings_dep),
                         user=Depends(get_current_user)):
    """What a preview of this run would show, whether this environment can run it, and how many links are live."""
    run = await own_run(db, run_id, user)
    state = run.get("state") or {}
    verdict = preview.support(state.get("files") or [])
    return _out(run, _page(state), verdict, len(await _live_tickets(db, run_id, now())), settings)


@router.post("/api/runs/{run_id}/preview", status_code=201)
async def preview_start(run_id: str, request: Request, db=Depends(get_db),
                        settings=Depends(get_settings_dep), user=Depends(get_current_user)):
    """Open a preview: hand out one expiring link for the page exactly as it is published right now."""
    run = await own_run(db, run_id, user)
    state = run.get("state") or {}
    verdict = preview.support(state.get("files") or [])
    if not verdict["supported"]:
        raise HTTPException(415, verdict["reason"])
    page = _page(state)
    if not page:
        raise HTTPException(409, "No page has been published for this run yet")
    try:  # prove the blob is readable before handing anyone a link to it
        await request.app.state.storage.load(page["key"])
    except Exception as exc:  # noqa: BLE001 - a lost blob is a refusal, never a link to a broken page
        raise HTTPException(409, f"The published page could not be read from storage: {str(exc)[:160]}") from exc

    at = now()
    live = await _live_tickets(db, run_id, at)
    if len(live) >= settings.preview_tickets_per_run:
        raise HTTPException(429, f"This run already has {len(live)} live preview links. Stop the preview first.")
    token = preview.new_token()
    await db.previews.insert_one({"run_id": run_id, "user_id": str(user["_id"]),
                                  "token_hash": preview.token_hash(token), "html_key": page["key"],
                                  "version": page["version"], "created_at": at,
                                  "exp": at + timedelta(seconds=settings.preview_ttl_seconds)})
    # The plaintext token exists in this response and nowhere else: Mongo holds only its digest.
    return _out(run, page, verdict, len(live) + 1, settings,
                {"token": token, "path": f"/api/preview/{token}",
                 "expires_in": settings.preview_ttl_seconds, "version": page["version"]})


@router.delete("/api/runs/{run_id}/preview")
async def preview_stop(run_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Stop the preview: revoke every link this run has handed out, immediately."""
    run = await own_run(db, run_id, user)
    res = await db.previews.delete_many({"run_id": run_id, "user_id": str(user["_id"])})
    return {"ok": True, "revoked": res.deleted_count}


@router.get("/api/preview/{token}")
async def preview_content(token: str, request: Request, db=Depends(get_db)):
    """The previewed page, sandboxed. No credentials are read, sent or needed here."""
    _look_limiter.check(_ip(request))
    if not preview.valid_token(token):
        raise HTTPException(404, GONE)
    doc = await db.previews.find_one({"token_hash": preview.token_hash(token)})
    exp = _when(doc.get("exp")) if doc else None
    if not doc or exp is None or exp <= now():
        raise HTTPException(404, GONE)
    try:
        data = await request.app.state.storage.load(doc["html_key"])
    except Exception as exc:  # noqa: BLE001 - the page went away; the link is dead, not the server
        raise HTTPException(404, f"That preview is gone: {str(exc)[:120]}") from exc
    return Response(data, media_type="text/html; charset=utf-8", headers=SANDBOX_HEADERS)
