"""The IDE's own feed: the projects this user owns, and the newest run of each that can really be opened.

`GET /api/projects` answers "what projects exist" and `GET /api/runs/{id}/workspace` answers "what is in
this build". The selection screen needs both at once - a card that says which run it would open, what
that run contains, and why it cannot be opened if it cannot - and asking the browser to make N+1 requests
to find that out would be slow and would show a half-drawn list. So this router does the join once, on the
server, still filtered by the caller's own user id.

Two things are deliberately not promised here. Project code is not executed (see
`/api/runs/{id}/workspace/exec`), and there is no import path yet (`/api/ide/import` says what it would
take). A card that cannot be opened says so, instead of opening an editor over an empty workspace.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user, get_db
from app.db.models import oid

router = APIRouter(prefix="/api/ide", tags=["ide"])

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
    projects = await db.projects.find({"user_id": str(user["_id"])}).sort("created_at", -1).to_list(PROJECT_CAP)
    cursor = db.runs.find({"user_id": str(user["_id"])}).sort("updated_at", -1).limit(RUN_CAP)
    by_project: dict[str, list[dict]] = {}
    runs: list[dict] = []
    async for doc in cursor:
        runs.append(doc)
    # `runs` arrives newest-first, so the first openable run seen for a project is also its newest openable one.
    for doc in runs:
        row = _run_row(doc)
        pid = str(doc.get("project_id") or "")
        by_project.setdefault(pid, {"latest": row, "open": None, "count": 0})
        bucket = by_project[pid]
        bucket["count"] += 1
        if row["openable"] and bucket["open"] is None:
            bucket["open"] = row

    out = []
    for p in projects:
        pid = str(p["_id"])
        bucket = by_project.get(pid) or {"latest": None, "open": None, "count": 0}
        spec = p.get("spec") or {}
        chosen = bucket["open"] or bucket["latest"]
        out.append({
            "project_id": pid,
            "name": p.get("name") or (p.get("idea") or "Untitled")[:60],
            "description": p.get("idea") or "",
            "created_at": p.get("created_at"),
            "business_type": spec.get("business_type") or "",
            "pages": len(spec.get("pages") or []) or None,
            "run_count": bucket["count"],
            "open_run": bucket["open"],
            "latest_run": bucket["latest"],
            # What the card shows and what clicking it does: an openable run, or the reason there isn't one.
            "last_modified": (chosen or {}).get("updated_at") or p.get("created_at"),
            "status": (chosen or {}).get("status") or "empty",
            "version": (chosen or {}).get("version", 0),
            "files": (chosen or {}).get("files", 0),
            "languages": (chosen or {}).get("languages") or [],
            "framework": (chosen or {}).get("framework") or STACK_STATIC,
            "readiness": (chosen or {}).get("readiness"),
            "style_label": (chosen or {}).get("style_label") or "",
            "thumbnail": (chosen or {}).get("has_thumbnail", False),
            "can_open": bool(bucket["open"]),
            "blocked_reason": "" if bucket["open"] else ((chosen or {}).get("blocked_reason")
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
