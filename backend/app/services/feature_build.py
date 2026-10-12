"""The one page patch and the source files a feature request means, held as a reviewable proposal.

A plan (`app/services/feature_plan.py`) says what a sentence means. This module says what it would write:
one change to `index.html` that puts the panels into the page, and the server, schema, environment
template, browser client and setup notes that ride beside it. Both come out of the catalog, offline, with
no model call - so what the reviewer reads is byte-for-byte what Apply writes.

Four decisions keep it honest:

* **The block is findable again.** A second feature build must not bury a second copy of the panels, so
  the block written before is located by its own opening tag and by `templates.BLOCK_TAIL`, and replaced.
  Comments cannot be the delimiter, because the publisher strips them - which is why the end is an element.
* **Features already on the page stay on it.** The keys the page declares are unioned with the new
  request, so asking for a blog after a contact form does not delete the form. A crew rebuild that draws
  the page from scratch drops the panels, and `status_of` reports that as missing rather than letting
  the history imply they are still live.
* **The patch has one home.** A first block goes in front of `</main>`, or `</body>` when the page has
  no content area, and only when that anchor occurs exactly once. A page with three `</main>` tags gets a
  refusal that says so, not a block dropped in front of the first one.
* **Nothing is written by a proposal.** Recording one appends an entry to `state.feature_edits` and
  touches no file. Apply hands the same verified patch to the workspace pipeline as a `feature build`, so
  it gets the snapshot before it and the sanitizer, Chromium checks and readiness score after it - and if
  the page change is refused, the orchestrator rolls the source files back with it.
"""
from __future__ import annotations

from app.agents import capabilities as caps
from app.services import codebase_index, feature_plan, feature_templates as templates
from app.services import workspace_manager
from app.services.workspace_manager import AUTHORED_NOTE, WorkspaceError
from app.tools.audit_util import stamp

MAX_FEATURE_PROPOSALS = 6        # each entry carries a whole page block, so this list stays bounded
MAX_PATCH_BYTES = workspace_manager.MAX_PATCH_BYTES

# Where a first feature block goes, best home first. Both are only usable when they occur exactly once.
ANCHORS = ("</main>", "</body>")

_NOTES = {
    caps.SHARED_SERVER: "The API every panel on this page calls. Start it with the command in SETUP.md.",
    caps.SHARED_DB: "SQLite access used by every route in server.py.",
    caps.SHARED_SCHEMA: "The tables this build creates on first start. Idempotent.",
    caps.SHARED_ENV: "Variable names only, each commented. No value here is a secret.",
    caps.SHARED_SETUP: "How to install, start and finish the setup only the owner can do.",
    templates.FEATURES_DOC: "What this build contains, per surface, in the catalog's own words.",
    templates.REQUIREMENTS: "Packages server.py needs. Nothing here is a placeholder dependency.",
    templates.FEATURE_CLIENT: "The browser half of the panels, served by server.py at /feature_client.js.",
}


def present_keys(page: str) -> list[str]:
    """The capability keys the page already carries, in the order its block declared them.

    Read out of the opening tag rather than by a fixed attribute position, because the publisher rewrites
    the tag with its attributes in alphabetical order - and a build that could not see what is already on
    the page would stack a second copy of it.
    """
    tag = templates.BLOCK_OPEN_RE.search(page or "")
    if not tag:
        return []
    declared = templates.FEATURE_SET_ATTR.search(tag.group(0))
    if not declared:
        return []
    return [key for key in declared.group(1).split(",") if caps.get(key)]


def _region(page: str) -> tuple[int, int] | None:
    """Offsets of the feature block already in this page, or None when it carries none.

    A block that starts but never reaches its tail is refused rather than guessed at: writing over an
    unknown span is how a feature build would eat the rest of someone's page.
    """
    start = (page or "").find(templates.BLOCK_HEAD)
    if start < 0:
        return None
    tail = page.find("data-lc-features-end", start)
    if tail < 0:
        raise WorkspaceError(
            "A feature block starts in this page but its end marker is gone, so its span cannot be "
            "measured and nothing was written. Restore an earlier version of the page, or ask the crew "
            "to revise it, then request the features again.", 409)
    end = page.find("</div>", tail)
    if end < 0:
        raise WorkspaceError("The feature block in this page is cut off, so its end cannot be found. "
                             "Restore an earlier version and ask for the features again.", 409)
    return start, end + len("</div>")


def _anchor(page: str) -> str:
    """The single text a first block goes in front of. Refuses when no candidate stands alone."""
    counts = {anchor: workspace_manager.occurrences(page, anchor) for anchor in ANCHORS}
    for anchor in ANCHORS:
        if counts[anchor] == 1:
            return anchor
    raise WorkspaceError(
        "This page has no single place a feature block could go ("
        + ", ".join(f"“{anchor}” found {count} times" for anchor, count in counts.items())
        + "). Ask the crew to revise the page into one content area, then request the feature again.", 409)


def source_files(keys, *, site: str = "", idea: str = "", plan: dict | None = None) -> list[dict]:
    """The files a build writes, as the workspace wants them: name, bytes, language, note, source."""
    files = templates.compose(keys, site=site, idea=idea, plan=plan)
    files.pop(templates.PAGE_SECTIONS, None)          # the page gets this markup; it is not a second file
    return [{"name": name, "text": text, "language": codebase_index.language_of(name),
             "note": _NOTES.get(name, AUTHORED_NOTE)[:160], "source": "feature build"}
            for name, text in sorted(files.items())]


def plan(texts: dict[str, str], *, request: str = "", keys: list[str] | None = None,
         include: list[str] | None = None, site: str = "", idea: str = "") -> dict:
    """The patch, the source and the report for one feature request. Measures everything, writes nothing.

    Union with the page's own block is deliberate: a page that already carries a catalog must keep it,
    because dropping someone's existing feature while reporting a new one is the worst summary a build
    can print.
    """
    page = texts.get("index.html") or ""
    if not page.strip():
        raise WorkspaceError("No page has been built yet, so there is nothing to add a feature to.", 409)

    asked = feature_plan.resolve(request, keys=keys, include=include, site=site, idea=idea)
    here = present_keys(page)
    wanted = list(dict.fromkeys(here + asked["keys"]))
    built = feature_plan.build(wanted, request=request, matched=feature_plan.named(request),
                               site=site, idea=idea,
                               origin=list(dict.fromkeys(asked["origin"] + here)))
    # The block declares its keys in catalog order, so that list - not the order they arrived in - is what
    # `recheck` has to find in the patch on the way back. `introduces` is measured against it too.
    final = list(built["keys"])

    files = templates.compose(final, site=site, idea=idea or request, plan=built["doc"])
    markup = files.pop(templates.PAGE_SECTIONS, "")
    if not markup:
        raise WorkspaceError(
            f"{', '.join(caps.get(key).label for key in final)} write no panel, so there is nothing for "
            f"this page to show. Their routes and tables are real source and will be written as soon as "
            f"the request also names a feature with an interface.", 422)

    span = _region(page)
    if span:
        find, replace, replacing = page[span[0]:span[1]], markup, True
        if workspace_manager.occurrences(page, find) != 1:
            raise WorkspaceError("The feature block already in this page does not occur in one place, so "
                                 "it cannot be replaced safely. Restore a version of the page and ask "
                                 "again.", 409)
    else:
        find = _anchor(page)
        replace = markup + find
        replacing = False
    for text in (find, replace):
        if len(text.encode("utf-8", "ignore")) > MAX_PATCH_BYTES:
            raise WorkspaceError(f"{len(final)} features in one build make a page block larger than the "
                                 f"{MAX_PATCH_BYTES} bytes one workspace patch can carry. Ask for fewer "
                                 f"features at a time.", 422)

    labels = [caps.get(key).label for key in final]
    note = ("Feature build: " + ", ".join(labels[:4])
            + (f" (+{len(labels) - 4} more)" if len(labels) > 4 else ""))[:200]
    authored = source_files(final, site=site, idea=idea or request, plan=built["doc"])
    return {"changes": [{"file": "index.html", "op": "replace", "find": find, "replace": replace,
                         "note": note}],
            "authored": authored, "report": built, "keys": final, "present": here,
            "introduces": [key for key in final if key not in here],
            "replacing": replacing, "anchor": find if not replacing else "",
            "block": find, "markup_bytes": len(markup.encode("utf-8", "ignore")),
            "unchanged": replacing and find == replace,
            "files": built["files"], "summary": feature_plan.summarise(built)}


def recheck(entry: dict, texts: dict[str, str]) -> None:
    """Prove a stored proposal still means this page, and still means these features.

    Two things must hold before Apply runs: the text the patch looks for occurs exactly once here, and
    the text it writes is still the block for the keys the reviewer read. A proposal whose block has been
    rewritten is a different change than the one that was approved, so it is refused and the user is told
    to ask again against the current page.
    """
    page = texts.get("index.html") or ""
    for change in entry.get("changes") or []:
        if change.get("file") != "index.html":
            raise WorkspaceError("A feature build may only edit the page itself.", 422)
        count = workspace_manager.occurrences(page, change.get("find") or "")
        if count != 1:
            raise WorkspaceError(f"Conflict: the place this proposal was read from is no longer here on "
                                 f"its own (found {count} times). Load the page again and ask for the "
                                 f"features once more.", 409)
        want = f'data-lc-feature-set="{",".join(entry.get("keys") or [])}"'
        if want not in (change.get("replace") or ""):
            raise WorkspaceError(f"Conflict: proposal {entry.get('id', '')} no longer writes "
                                 f"{', '.join(entry.get('keys') or [])}. Preview the features again and "
                                 f"re-request the build.", 409)


# --------------------------------------------------------------------------- the proposal, as run history

def _next_id(entries: list[dict]) -> str:
    """The next proposal id. The list is pruned, so its length is not an index: an id a reviewer was told
    must keep meaning one entry, or Apply could build the wrong feature off a right-looking name."""
    used = [int(str(e.get("id", ""))[1:]) for e in entries if str(e.get("id", ""))[1:].isdigit()]
    return f"f{max(used, default=0) + 1}"


def record_proposal(ctx, *, request: str, site: str, idea: str, planned: dict,
                    report: dict | None = None) -> dict:
    """Keep a reviewed feature patch beside the plan it came from. Touches no file and takes no snapshot."""
    s = ctx.state
    built = planned["report"]
    entries = s.feature_edits or []
    entry = {"id": _next_id(entries), "at": stamp(), "status": "proposed", "run_id": ctx.run_id,
             "version": s.html_version, "request": (request or "")[:500],
             "site": (site or "")[:120], "idea": (idea or request or "")[:300],
             "keys": planned["keys"], "named": built["named"], "added": built["added"],
             "introduces": planned["introduces"], "present_before": planned["present"],
             "replacing": planned["replacing"], "unchanged": planned["unchanged"],
             "features": built["features"], "statuses": built["statuses"], "needs": built["needs"],
             "need_words": built["need_words"], "overall": built["overall"],
             "overall_label": built["overall_label"], "env": built["env"], "routes": built["routes"],
             "tables": built["tables"], "setup": built["setup"], "warnings": built["warnings"],
             "summary": planned["summary"], "server": built["server"],
             "files": [{"name": item["name"], "bytes": len(item["text"].encode("utf-8", "ignore")),
                        "note": item["note"]} for item in planned["authored"]],
             # FEATURES.md quotes these three fields; kept so Apply writes the document that was reviewed.
             "doc_plan": built["doc"],
             "page_bytes": built["page_bytes"], "markup_bytes": planned["markup_bytes"],
             "changes": planned["changes"], "authored_names": [item["name"] for item in planned["authored"]],
             "impact": {"scope": (report or {}).get("scope"), "counts": (report or {}).get("counts"),
                        "risks": [(r["severity"], r["message"])
                                   for r in (report or {}).get("risks") or []][:6]},
             "plan": "", "result": {}, "lines_added": 0, "lines_removed": 0}
    s.feature_edits = entries[-(MAX_FEATURE_PROPOSALS - 1):] + [entry]
    return entry


def authored_for(entry: dict) -> list[dict]:
    """The source files an applied proposal ships, recomposed from the keys it was reviewed for.

    The bytes are regenerated rather than replayed from the record: the record holds names and sizes, and
    a proposal must not apply a stale copy of `server.py` beside a page whose markup came from the current
    catalog. The name set is what the reviewer read, and `recheck` has just proved the page still means
    these keys, so regenerating is both lighter in storage and harder to get wrong.
    """
    files = source_files(entry.get("keys") or [], site=entry.get("site", ""),
                         idea=entry.get("idea", ""), plan=entry.get("doc_plan") or None)
    if {item["name"] for item in files} != set(entry.get("authored_names") or []):
        raise WorkspaceError("Conflict: the feature source this proposal listed is not what the current "
                             "catalog writes for these keys. Preview the features again and re-request "
                             "the build.", 409)
    if not files:
        raise WorkspaceError("This proposal carries no source files, so there is no build to apply.", 409)
    return files


def find_proposal(state, fid: str) -> dict:
    """One recorded feature proposal, or a 404 that names the ones that do exist."""
    entries = (state.feature_edits if hasattr(state, "feature_edits")
               else (state.get("feature_edits") or [])) or []
    entry = next((e for e in entries if e.get("id") == fid), None)
    if not entry:
        raise WorkspaceError(f"No feature proposal '{fid}' in this run (recorded: "
                             f"{', '.join(e.get('id', '') for e in entries) or 'none'})", 404)
    return entry


def mark_proposal(entry: dict, status: str, **extra) -> dict:
    """Say what became of a proposal. History keeps the entry; only its outcome changes."""
    entry["status"] = status
    entry["result"] = {**(entry.get("result") or {}), **extra}
    return entry


def status_of(state, page: str | None = None) -> dict:
    """What a feature panel should show before it offers anything: the version a patch would be measured
    against, the proposal still waiting, the panels the page actually carries - and, when a caller passes
    the page, the features a crew rebuild has quietly dropped."""
    entries = (state.feature_edits if hasattr(state, "feature_edits")
               else (state.get("feature_edits") or [])) or []
    version = (state.html_version if hasattr(state, "html_version")
               else state.get("html_version")) or 0
    open_entry = next((e for e in reversed(entries) if e.get("status") == "proposed"), None)
    applied = [e for e in entries if e.get("status") == "applied"]
    out = {"version": version, "open": bool(open_entry), "open_id": (open_entry or {}).get("id", ""),
           "count": len(entries), "max": MAX_FEATURE_PROPOSALS,
           "proposals": [e.get("id", "") for e in entries],
           "built": [{"id": e.get("id", ""), "at": e.get("at", ""), "keys": e.get("keys") or [],
                      "overall": e.get("overall", "")} for e in applied],
           "server_files": bool(applied and applied[-1].get("authored_names")),
           "env": (applied[-1].get("env") or []) if applied else []}
    if page is not None:
        here = present_keys(page)
        out["panels_present"] = here
        last = applied[-1] if applied else None
        out["panels_missing"] = [key for key in (last or {}).get("keys") or [] if key not in here]
        out["panels_declared"] = bool((last or {}).get("keys")) and not here
    return out
