"""The IDE assistant: one plain-English request, answered with named edits the workspace can actually make.

Nothing here writes to a workspace and no key leaves the server. The model is shown the run's own stored
file text and asked for edits in the language `workspace_manager` already speaks (`replace`, `replace_all`,
`append`, `set`); every edit it returns is re-applied to the text we sent before the proposal is recorded,
so a patch that does not match the file is refused with the reason instead of being shown as an option.
Applying a proposal later re-verifies it the same way, through the ordinary patch pipeline: checkpoint
first, sanitizer and Chromium checks after, one revision spent.

This is deliberately not a chat. A proposal either names files that exist and text that is really in them,
or it is a refusal - there is no invented diff and no "done" for a byte nobody wrote.
"""
from __future__ import annotations

from app.services import workspace_manager
from app.tools import differ
from app.tools.audit_util import stamp

MAX_PROPOSALS = 20
MAX_INSTRUCTION_CHARS = 500
MAX_FILES_SENT = 8
MAX_FILE_BYTES_SENT = 30_000      # per file, tail clipped and reported
MAX_TOTAL_BYTES_SENT = 90_000     # across the whole request
MAX_PROPOSED_LINE_MOVEMENT = 600  # a proposal that rewrites the page is a rebuild, not an edit

# The page's own names are rebuilt from `index.html` by the splitter, so a proposal that touches them has
# to go through the patch pipeline like any other edit - which it does. This is the list the panel labels.
PAGE_NAMES = ("index.html", "styles.css", "app.js")


def _clip(value: str, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _bytes(text: str) -> int:
    return len(str(text or "").encode("utf-8", "ignore"))


def choose(texts: dict[str, str], instruction: str, files: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Which files this request is sent with, and which of them arrive only in part.

    An explicit list is taken literally - the editor knows what the user is looking at, and sending the rest
    of the workspace as "context" is how an assistant ends up editing a file nobody asked about. Otherwise
    the file names the instruction mentions come first, then the page itself, then its assets, then the rest
    by size. The tail is dropped rather than spread thin, because a model patching a file it cannot read
    produces a refusal, not a fix.
    """
    names = list(texts)
    explicit = [f for f in (files or []) if f in names]
    if explicit:
        ranked = explicit
    else:
        lower = (instruction or "").lower()
        wanted = [n for n in names if n.lower() in lower]
        rest = sorted(names, key=lambda k: (k != "index.html", k not in PAGE_NAMES, _bytes(texts[k])))
        ranked = list(dict.fromkeys([*wanted, *rest]))
    picked, budget = [], MAX_TOTAL_BYTES_SENT
    for name in ranked:
        if len(picked) >= MAX_FILES_SENT or budget <= 0:
            continue
        picked.append(name)
        budget -= _bytes(texts[name])
    clipped = [n for n in picked if _bytes(texts[n]) > MAX_FILE_BYTES_SENT]
    return picked, clipped


def prompt(*, instruction: str, texts: dict[str, str], picked: list[str], clipped: list[str],
           impact: str = "", editable_note: str = "") -> str:
    """The one message the assistant gets: the request, the files verbatim, and the rules it must respect."""
    lines = [f"REQUEST: {(instruction or '').strip()[:MAX_INSTRUCTION_CHARS]}", "",
             "EDIT THESE FILES (exact stored contents, not a summary):"]
    for name in picked:
        body = texts.get(name) or ""
        marker = ""
        if _bytes(body) > MAX_FILE_BYTES_SENT:
            body = body[:MAX_FILE_BYTES_SENT]
            marker = "\n… file clipped here; the rest was not sent"
        lines.append(f"--- {name} ---")
        lines.append(body + marker)
        lines.append(f"--- end {name} ---")
    if clipped:
        lines.append(f"PARTIALLY SENT: {', '.join(clipped)} - do not patch a region that was not sent.")
    lines.append(f"FILES YOU MAY NAME IN `file`: {', '.join(picked)}")
    if editable_note:
        lines.append(editable_note)
    if impact:
        lines.append(impact.strip()[:1500])
    lines.append(
        "Answer with JSON: {\"summary\": str, \"changes\": [{\"file\": str, \"op\": "
        "\"replace\"|\"replace_all\"|\"append\"|\"set\", \"find\": str, \"replace\": str, \"text\": str, "
        "\"note\": str}]}. One change per file, at most 12 files. For replace/replace_all copy `find` "
        "verbatim from the text above, including whitespace, so it matches exactly once (or use "
        "replace_all). For append and `set` put the new content in `text`. Change only what the request "
        "asks for; do not rewrite a whole file when a fragment will do; do not invent a file name, a path "
        "or a dependency that is not in the list above.")
    return "\n".join(lines)


class PatchError(workspace_manager.WorkspaceError):
    """A model's edit set this workspace will not accept, with the reason the model needs back."""


def verify(raw: dict, texts: dict[str, str], *, allowed: list[str] | None = None) -> dict:
    """Prove every proposed edit against the stored text, then show what the whole set would do.

    `workspace_manager.apply_op` is the same function the pipeline uses, so a `find` that does not match
    here will not match there either - and the caller gets its exact message, which is also the corrective
    prompt the agent gets for its second attempt.

    `allowed` is the set of files that were actually sent for this request. The prompt names it, and a
    reviewer who ticked one file should not get a proposal that edits another: the workspace holds dozens
    of names and a model can produce a plausible patch for any of them, so the scope is enforced here
    rather than left to good manners. Apply re-verifies with the same list the proposal was recorded with.
    """
    raw = dict(raw or {})
    scope = {str(n) for n in (allowed or []) if n}
    changes = []
    for entry in raw.get("changes") or []:
        if isinstance(entry, dict) and entry.get("op") in ("append", "set") and not (entry.get("text") or "").strip():
            entry = {**entry, "text": entry.get("replace") or ""}   # one field for the new content
        changes.append(entry)
    try:
        patches = workspace_manager.validate_changes(changes)
    except workspace_manager.WorkspaceError as exc:
        raise PatchError(exc.message) from exc

    before, after, moved = {}, {}, 0
    for patch in patches:
        name = patch["file"]
        if name not in texts:
            raise PatchError(f"{name} is not a file this workspace holds, so nothing can be patched there. "
                             f"Choose from: {', '.join(sorted(texts))}.")
        if scope and name not in scope:
            raise PatchError(f"{name} was not sent for this request, so its contents are not known here and "
                             f"it cannot be edited. Ask again naming it, or choose from: "
                             f"{', '.join(sorted(scope))}.")
        source = texts[name]
        try:
            result = workspace_manager.apply_op(source, patch)
        except workspace_manager.WorkspaceError as exc:
            raise PatchError(exc.message) from exc      # already names the file and what it looked for
        if result == source:
            raise PatchError(f"{name}: this change would write exactly what is already there, so it does "
                             f"nothing. Say what should read or look different.")
        stats = differ.stats(source, result)
        moved += stats["lines_added"] + stats["lines_removed"]
        before[name], after[name] = source, result
    if moved > MAX_PROPOSED_LINE_MOVEMENT:
        raise PatchError(f"This proposal moves {moved} lines, over the {MAX_PROPOSED_LINE_MOVEMENT} one "
                         f"assistant edit may reach. Narrow it to the parts the request names.")
    lines = {name: differ.stats(before[name], after[name]) for name in before}
    return {"summary": _clip(raw.get("summary"), 400), "changes": patches,
            "files": sorted(before), "lines_added": sum(v["lines_added"] for v in lines.values()),
            "lines_removed": sum(v["lines_removed"] for v in lines.values()),
            "before": before, "after": after, "per_file": lines}


def affected(verified: dict) -> list[dict]:
    """One row per file a proposal would touch, in the same words the editor uses for that file.

    The kind and the `why` come from `workspace_manager`, so a review screen cannot describe
    `styles.css` as a plain source file and hide the fact that applying this rebuilds the page.
    """
    out = []
    for change in verified["changes"]:
        name = change["file"]
        stats = verified["per_file"].get(name) or {}
        kind = workspace_manager.file_kind(name)
        out.append({"file": name, "op": change["op"], "kind": kind, "save_via": workspace_manager.SAVE_VIA[kind],
                    "why": workspace_manager.KIND_WHY[kind], "note": change.get("note") or "",
                    "lines_added": stats.get("lines_added", 0), "lines_removed": stats.get("lines_removed", 0)})
    return out


# --------------------------------------------------------------------------- the proposal, as run history

def record_proposal(ctx, *, instruction: str, verified: dict, rows: list[dict], report: dict | None,
                    sent: list[str], clipped: list[str]) -> dict:
    """Keep a reviewed proposal so Apply can prove it still means the edit the user read.

    Recording writes nothing: no file is touched and no snapshot is taken here. The entry carries the
    change set itself, because re-verifying a stored patch against the current text is what turns "the
    workspace moved underneath you" into a refusal instead of a silent overwrite.
    """
    s = ctx.state
    number = len(s.ide_edits or []) + 1
    entry = {"id": f"i{number}", "at": stamp(), "status": "proposed", "run_id": ctx.run_id,
             "version": s.html_version, "instruction": (instruction or "")[:MAX_INSTRUCTION_CHARS],
             "summary": verified["summary"], "changes": verified["changes"], "affected": rows,
             "files": verified["files"], "sent_files": sent, "clipped_files": clipped,
             "lines_added": verified["lines_added"], "lines_removed": verified["lines_removed"],
             "impact": {"scope": (report or {}).get("scope"), "counts": (report or {}).get("counts"),
                        "risks": [(r["severity"], r["message"]) for r in (report or {}).get("risks") or []][:6]},
             "plan": "", "result": {}}
    s.ide_edits = (s.ide_edits or [])[-(MAX_PROPOSALS - 1):] + [entry]
    return entry


def find_entry(state, pid: str) -> dict:
    """One recorded proposal, from a state object or the plain dict a route read out of Mongo."""
    entries = state.ide_edits if hasattr(state, "ide_edits") else (state.get("ide_edits") or [])
    entry = next((e for e in entries or [] if e.get("id") == pid), None)
    if not entry:
        raise workspace_manager.WorkspaceError(
            f"No assistant proposal '{pid}' in this run"
            f" (recorded: {', '.join(e.get('id', '') for e in entries or []) or 'none'})", 404)
    return entry


def mark_proposal(entry: dict, status: str, **extra) -> dict:
    """Say what became of a proposal. The record stays in run history; only its outcome changes."""
    entry["status"] = status
    entry["result"] = {**(entry.get("result") or {}), **extra}
    return entry

