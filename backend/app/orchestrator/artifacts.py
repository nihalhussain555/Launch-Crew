"""Publishing a build into the project workspace: file set + restorable version snapshots.

Called by the Engineer after every page build and by the restore flow. The canonical
self-contained `index.html` stays the single source of truth for preview, share, deploy and the
browser checks - everything here is derived from it, so nothing downstream has to change.
"""
from datetime import datetime, timezone

from app.tools import splitter

KEEP_VERSIONS = 30                      # oldest snapshots are dropped (and their blobs) beyond this
PAGE_NOTE = "Self-contained build: the preview, share link and deploy all use this file."


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def publish(ctx, note: str = "") -> list[dict]:
    """Store the file set and a version snapshot for the page currently in state."""
    s, storage = ctx.state, ctx.storage
    if not s.html:
        return s.files

    _, assets = splitter.split_page(s.html)      # only the extracted assets ship; index.html stays self-contained
    doc_note = note or s.note or "Rebuilt by the crew"
    readme = splitter.readme(s.idea, assets, s.html_version, (s.readiness or {}).get("total"))

    files = [{"name": "index.html", "language": "html", "bytes": len(s.html.encode()),
              "note": PAGE_NOTE, "key": await storage.save(ctx.run_id, "index.html", s.html.encode("utf-8"))}]
    for a in assets:
        files.append({"name": a.name, "language": a.language, "bytes": len(a.text.encode()),
                      "note": a.note, "key": await storage.save(ctx.run_id, a.name, a.text.encode("utf-8"))})
    files.append({"name": readme.name, "language": readme.language, "bytes": len(readme.text.encode()),
                  "note": readme.note, "key": await storage.save(ctx.run_id, readme.name, readme.text.encode("utf-8"))})
    s.files = files

    key = await storage.save(ctx.run_id, f"history/v{s.html_version}.html", s.html.encode("utf-8"))
    s.versions.append({"v": s.html_version, "key": key, "bytes": len(s.html.encode()), "at": stamp(),
                       "note": doc_note, "errors": s.check_summary.get("errors", 0),
                       "warnings": s.check_summary.get("warnings", 0),
                       "readiness": (s.readiness or {}).get("total"),
                       "files": [f["name"] for f in files]})

    dropped = s.versions[:-KEEP_VERSIONS]
    if dropped:
        s.versions = s.versions[-KEEP_VERSIONS:]
        for old in dropped:
            try:
                await storage.delete(old["key"])
            except Exception:  # noqa: BLE001 - a stray blob must never fail a build
                pass
    s.note = ""
    return files


async def annotate(ctx) -> None:
    """Attach the final check/readiness numbers to the snapshot just published."""
    s = ctx.state
    if not s.versions:
        return
    last = s.versions[-1]
    if last.get("v") == s.html_version:
        last["errors"] = s.check_summary.get("errors", 0)
        last["warnings"] = s.check_summary.get("warnings", 0)
        last["readiness"] = (s.readiness or {}).get("total")


def current(ctx) -> dict | None:
    return next((v for v in reversed(ctx.state.versions) if v["v"] == ctx.state.html_version), None)


async def load(ctx, version: int) -> str:
    """The page exactly as it was saved at that version."""
    entry = next((v for v in ctx.state.versions if v["v"] == version), None)
    if not entry:
        raise KeyError(f"No snapshot for version v{version}")
    return (await ctx.storage.load(entry["key"])).decode("utf-8")


async def file_text(ctx, name: str) -> str:
    entry = next((f for f in ctx.state.files if f["name"] == name), None)
    if not entry:
        raise KeyError(f"No such file: {name}")
    return (await ctx.storage.load(entry["key"])).decode("utf-8")
