"""Deliberate file-level edits: validate the path, apply the patch, keep the workspace restorable.

The crew's rebuilds go through `artifacts.publish` (the Engineer writes a whole page). This module is
for the other kind of change - someone names a file and says what to replace - which the pipeline has
never supported. Two invariants make that safe:

1. `index.html` is canonical. `styles.css` / `app.js` are derived from the page's embedded
   `<style>` / `<script>` blocks on every publish, so a patch to one of them is folded back into that
   block here, or the next build would silently undo it.
2. Nothing is overwritten without a snapshot. `capture()` stores the whole file set first, so any
   applied change - a hand-written patch, a chat edit, a crew rebuild or a restore - can be put back
   by workspace version. Those snapshots are the undo/redo timeline: `record_change` marks each one as
   a step back, `step_back`/`step_forward` walk it, and a restore creates a snapshot of its own rather
   than erasing history.

Everything here is deterministic: no LLM, no network, no host filesystem (paths are checked against
the run's recorded file set, never resolved against disk).
"""
from __future__ import annotations

import hashlib
import re
import time

from app.agents.base import looks_like_html
from app.orchestrator import artifacts
from app.services import codebase_index
from app.tools import differ, splitter
from app.tools.audit_util import stamp
from app.tools.sanitizer import sanitize_html

MAX_PATCH_BYTES = 60_000          # one patch's worth of new text
MAX_WORKSPACE_FILE_BYTES = 200_000  # per file: keeps it indexable (see codebase_index)
MAX_NAME_CHARS = 64
MAX_LABEL_CHARS = 80
KEEP_WORKSPACE_VERSIONS = 20      # fallback when the settings field is absent
MAX_UNDO_STEPS = 50               # undo/redo pointers held per run; the snapshots themselves are pruned
ALLOWED_EXTENSIONS = {"html", "htm", "css", "js", "mjs", "md", "py", "json", "txt", "sql"}
OPS = ("replace", "replace_all", "append", "set")

# The kinds of change that get a checkpoint, so history says who moved the workspace and why.
# The last three are the editor's own file operations: they move the file set without touching the page,
# so they earn an undo step but never a rebuild.
CAUSE_KINDS = ("crew rebuild", "file patch", "workspace restore", "version restore", "manual checkpoint",
               "visual edit", "theme edit", "feature build", "file create", "file rename", "file delete",
               "unattributed")

# Files the crew rewrites itself: patching them here would be undone by the next build.
GENERATED_ONLY = {"README.md"}
# The page plus the three files published from it. An authored file (app/services/feature_build.py) may
# not take one of these names, and a patch may not be aimed at one expecting it to be stored back.
DERIVED_NAMES = ("index.html", "styles.css", "app.js", "README.md")
MAX_AUTHORED_PER_BUILD = 12
AUTHORED_NOTE = "Written by a feature build - see FEATURES.md for what it needs to run."
# A name with any of these is not a workspace file, whatever the caller meant.
UNSAFE = re.compile(r"[/\\]|\.\.|^\.|^~|\s")


class WorkspaceError(Exception):
    """A change this workspace will not apply. `status` is the HTTP code the route should report."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message, self.status = message, status


def validate_name(name: str) -> str:
    """The bare file name of a workspace file - no path, no hidden file, known extension."""
    cleaned = (name or "").strip().strip('"').strip("'").strip("`")
    if not cleaned:
        raise WorkspaceError("A file name is required")
    if len(cleaned) > MAX_NAME_CHARS:
        raise WorkspaceError(f"File name is too long ({len(cleaned)} characters)")
    if UNSAFE.search(cleaned):
        raise WorkspaceError(f"'{cleaned}' is not a workspace file name: no paths, no '..' , no hidden files")
    if "." not in cleaned:
        raise WorkspaceError(f"'{cleaned}' has no extension")
    ext = cleaned.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise WorkspaceError(f"'{cleaned}' has an unsupported extension .{ext}")
    return cleaned


def known_file(state, name: str) -> dict:
    """Only files the current build actually published may be patched."""
    entry = next((f for f in (state.files or []) if f.get("name") == name), None)
    if not entry:
        raise WorkspaceError(f"'{name}' is not in this build's workspace "
                             f"({', '.join(f.get('name', '') for f in state.files or []) or 'no files yet'})", 404)
    if name in GENERATED_ONLY:
        raise WorkspaceError(f"{name} is rewritten by the crew on every build; patch the page instead")
    if any(f.get("name") == name for f in (state.authored_files or [])):
        raise WorkspaceError(f"{name} is feature source a build wrote, not part of the page: this patch "
                             f"would be measured against the file and then dropped, because only the page "
                             f"is published. Ask for the feature again with what should change, and the new "
                             f"version of the file is written whole.")
    return entry


def validate_patch(patch: dict) -> dict:
    """Normalise one change request and reject the shapes that cannot be applied safely."""
    if not isinstance(patch, dict):
        raise WorkspaceError("Each change must be an object")
    name = validate_name(patch.get("file") or "")
    op = (patch.get("op") or "replace").strip().lower()
    if op not in OPS:
        raise WorkspaceError(f"Unknown operation '{op}' for {name}. Use: {', '.join(OPS)}")
    out = {"file": name, "op": op, "find": patch.get("find") or "",
           "replace": patch.get("replace") if patch.get("replace") is not None else "",
           "text": patch.get("text") or "", "note": (patch.get("note") or "")[:200]}
    if op in ("replace", "replace_all") and not out["find"].strip():
        raise WorkspaceError(f"{name}: '{op}' needs the text to find")
    if op in ("append", "set") and not out["text"].strip():
        raise WorkspaceError(f"{name}: '{op}' needs the text to write")
    for key in ("find", "replace", "text"):
        if len(out[key].encode("utf-8", "ignore")) > MAX_PATCH_BYTES:
            raise WorkspaceError(f"{name}: {key} is larger than {MAX_PATCH_BYTES} bytes")
    return out


def validate_changes(changes: list[dict]) -> list[dict]:
    """Validate the whole set at once: duplicated targets would silently drop work."""
    if not changes:
        raise WorkspaceError("No changes given")
    if len(changes) > 12:
        raise WorkspaceError("Too many changes in one request (max 12)")
    seen: set[str] = set()
    out = []
    for raw in changes:
        patch = validate_patch(raw)
        if patch["file"] in seen:
            raise WorkspaceError(f"{patch['file']} appears twice - merge the two changes into one")
        seen.add(patch["file"])
        out.append(patch)
    return out


def occurrences(text: str, needle: str) -> int:
    return text.count(needle)


def apply_op(text: str, patch: dict) -> str:
    """One deterministic edit. Every failure says what it looked for and did not find."""
    op, name = patch["op"], patch["file"]
    if op == "set":
        return patch["text"]
    if op == "append":
        return text.rstrip("\n") + "\n" + patch["text"] + "\n"
    count = occurrences(text, patch["find"])
    if not count:
        raise WorkspaceError(f"{name}: nothing to change - the text to find is not in that file "
                             f"({snippet_of(text, patch['find'])})")
    if op == "replace" and count > 1:
        raise WorkspaceError(f"{name}: '{_quote(patch['find'])}' occurs {count} times. "
                             f"Use replace_all or a longer, unique fragment.")
    return text.replace(patch["find"], patch["replace"])


def _quote(text: str) -> str:
    flat = " ".join((text or "").split())
    return (flat[:48] + "...") if len(flat) > 51 else flat


def snippet_of(text: str, needle: str) -> str:
    """A hint at what the file does contain, so a failed patch is fixable rather than mysterious."""
    head = " ".join((text or "").split())[:160]
    first = needle.strip()[:1]
    hint = ""
    if first:
        near = text.find(first[0] if len(first) == 1 else first)
        if near >= 0:
            hint = " near line " + str(text.count("\n", 0, near) + 1)
    return f"it starts '{head}...'{hint}"


def fold_into_page(html: str, name: str, text: str) -> str:
    """Write a patched derived asset back into the block of the page it came from.

    `splitter.split_page` concatenates every non-empty block into one file, so the round trip is only
    exact while the page holds a single block. More than one is refused rather than guessed at.
    """
    if name == "styles.css":
        regex, body_group, attrs_group, block = splitter.STYLE_RE, 2, None, "style"
    elif name == "app.js":
        # Group 2 of SCRIPT_RE is the tag's attributes; the script body is group 3.
        regex, body_group, attrs_group, block = splitter.SCRIPT_RE, 3, 2, "script"
    else:
        return html
    matches = [m for m in regex.finditer(html) if m.group(body_group).strip()
               and (attrs_group is None or splitter._moved_scripts(m.group(attrs_group)))]
    if not matches:
        raise WorkspaceError(f"{name} is a copy of the page's <{block}> block, but this page has none. "
                             f"Patch index.html instead.")
    if len(matches) > 1:
        raise WorkspaceError(f"index.html holds {len(matches)} <{block}> blocks, which {name} merges into one "
                             f"file. Patch index.html directly so the mapping stays exact.")
    m = matches[0]
    body = "\n" + text.strip("\n") + "\n"
    return html[:m.start(body_group)] + body + html[m.end(body_group):]


async def load_texts(ctx, names: list[str] | None = None) -> dict[str, str]:
    """Current contents of the workspace, keyed by name. Strict: an unreadable file is an error."""
    wanted = [f["name"] for f in ctx.state.files or [] if names is None or f["name"] in names]
    out: dict[str, str] = {}
    for name in wanted:
        try:
            out[name] = await artifacts.file_text(ctx, name)
        except KeyError as exc:
            raise WorkspaceError(str(exc).strip("'"), 404) from exc
        except Exception as exc:  # noqa: BLE001 - a lost blob is a 404, not a 500
            raise WorkspaceError(f"{name} could not be read from storage: {exc}", 404) from exc
    return out


def index_texts(texts: dict[str, str], *, version: int = 0) -> dict:
    """Index file contents that are already loaded, page first so it reads as the root document."""
    files = [{"name": name, "language": codebase_index.language_of(name), "text": text}
             for name, text in texts.items()]
    files.sort(key=lambda f: (f["name"] != "index.html", f["name"]))
    return codebase_index.build_index(files, version=version)


async def index_workspace(ctx, *, version: int | None = None) -> dict:
    """Index the files this run published. Text always comes from the run's own storage."""
    texts = await load_texts(ctx)
    if ctx.state.html and "index.html" not in texts:
        texts["index.html"] = ctx.state.html
    return index_texts(texts, version=version if version is not None else ctx.state.html_version)


# ------------------------------------------------------------------ authored feature source
def validate_authored(files: list[dict]) -> list[dict]:
    """Normalise the source a feature build hands over, and refuse what it may not overwrite.

    These files ship as source for the user to run elsewhere; nothing in this backend executes or imports
    them. A name the page owns cannot be taken by one, because the preview, share link and deploy all read
    the page's own files - a clash would be a claim about what is live that the build cannot keep.
    """
    if not files:
        raise WorkspaceError("No files to write")
    if len(files) > MAX_AUTHORED_PER_BUILD:
        raise WorkspaceError(f"Too many files in one build (max {MAX_AUTHORED_PER_BUILD})")
    seen: set[str] = set()
    out: list[dict] = []
    for raw in files:
        if not isinstance(raw, dict):
            raise WorkspaceError("Each authored file must be an object")
        name = validate_name(raw.get("name") or raw.get("file") or "")
        if name in DERIVED_NAMES:
            raise WorkspaceError(f"{name} is rebuilt from the page on every publish; change the page instead")
        if name in seen:
            raise WorkspaceError(f"{name} appears twice; one version of a file can be written")
        text = str(raw.get("text") or "")
        if len(text.encode("utf-8", "ignore")) < 8:
            raise WorkspaceError(f"{name}: refusing to write an empty or stub file")
        if len(text.encode("utf-8", "ignore")) > MAX_WORKSPACE_FILE_BYTES:
            raise WorkspaceError(f"{name} is larger than the {MAX_WORKSPACE_FILE_BYTES} bytes a "
                                 f"workspace file may hold and stay indexable")
        seen.add(name)
        out.append({"name": name, "text": text, "language": codebase_index.language_of(name),
                    "note": (raw.get("note") or AUTHORED_NOTE)[:160],
                    "source": (raw.get("source") or "feature")[:40]})
    return out


async def stage_authored(ctx, files: list[dict]) -> list[dict]:
    """Store the bytes and return workspace entries; nothing is listed until `register_authored`.

    The blobs are written before the page is patched on purpose: if the page change is refused afterwards
    these bytes simply sit unreferenced, which has never failed a build, whereas a file entry pointing at
    bytes that were never written would be a lie in the workspace listing.
    """
    entries = []
    for item in validate_authored(files):
        data = item["text"].encode("utf-8", "ignore")
        key = await ctx.storage.save(ctx.run_id, item["name"], data)
        entries.append({"name": item["name"], "language": item["language"], "key": key, "bytes": len(data),
                        "note": item["note"], "source": item["source"]})
    return entries


def register_authored(state, entries: list[dict]) -> list[str]:
    """Add staged files to the run's authored set, replacing any earlier version of the same name."""
    names = {e["name"] for e in entries}
    state.authored_files = [f for f in (state.authored_files or []) if f.get("name") not in names] + list(entries)
    listed = {f.get("name") for f in (state.files or [])}
    state.files = list(state.files or []) + [dict(e) for e in entries if e.get("name") not in listed]
    return sorted(names)


async def restore_authored(ctx, w: int) -> list[str]:
    """Roll the feature source back exactly as that snapshot held it, including files it did not have yet.

    `publish` recreates the page's own three derived files from `index.html`, so restoring the page is
    enough for them. Server source a feature build wrote is not derivable from the page: without this a
    restore would put the page back and leave those files at whatever version they were written at, so the
    pair would no longer describe one build.
    """
    entry = snapshot_of(ctx, w)
    s = ctx.state
    known = {f["name"]: f for f in (s.authored_files or []) if f.get("name")}
    restored: list[dict] = []
    for recorded in entry["files"]:
        name = recorded.get("name") or ""
        if not name or name in DERIVED_NAMES:
            continue
        try:
            data = await ctx.storage.load(recorded["key"])
        except Exception as exc:  # noqa: BLE001 - a pruned blob is reported, never guessed at
            raise WorkspaceError(f"{name} could not be read from snapshot w{w}: {exc}", 404) from exc
        meta = known.get(name) or {}
        key = await ctx.storage.save(ctx.run_id, name, data)
        restored.append({"name": name, "language": meta.get("language") or codebase_index.language_of(name),
                         "key": key, "bytes": len(data),
                         "note": meta.get("note") or AUTHORED_NOTE,
                         "source": meta.get("source") or f"restored from w{w}"})
    s.authored_files = restored
    return sorted(r["name"] for r in restored)


def stats(before: dict[str, str], after: dict[str, str]) -> dict:
    """Per-file movement between two file sets: added, changed, renamed, removed, unchanged.

    A rename is one row, not a deletion plus an addition: the content is identical, so it moves no
    lines. Detecting it matters because a rebuild that re-names an asset otherwise reads as though
    the crew threw a file away and wrote a new one.
    """
    renames = _detect_renames(before, after)
    moved_from = set(renames.values())
    rows = []
    for name in sorted(set(before) | set(after)):
        a, b = before.get(name, ""), after.get(name, "")
        if name in renames:
            src = renames[name]
            rows.append({"file": name, "status": "renamed", "from": src,
                         "bytes_before": len(before[src].encode()), "bytes_after": len(b.encode()),
                         "lines_added": 0, "lines_removed": 0})
        elif name not in before:
            rows.append({"file": name, "status": "added", "bytes_before": 0, "bytes_after": len(b.encode()),
                         "lines_added": b.count("\n") + 1, "lines_removed": 0})
        elif name not in after:
            if name in moved_from:
                continue
            rows.append({"file": name, "status": "removed", "bytes_before": len(a.encode()), "bytes_after": 0,
                         "lines_added": 0, "lines_removed": a.count("\n") + 1})
        else:
            d = differ.stats(a, b)
            rows.append({"file": name, "status": "unchanged" if d["same"] else "changed",
                         "bytes_before": len(a.encode()), "bytes_after": len(b.encode()),
                         "lines_added": d["lines_added"], "lines_removed": d["lines_removed"]})
    return {"files": rows,
            "changed": [r["file"] for r in rows if r["status"] == "changed"],
            "added": [r["file"] for r in rows if r["status"] == "added"],
            "removed": [r["file"] for r in rows if r["status"] == "removed"],
            "renamed": [{"from": r["from"], "to": r["file"]} for r in rows if r["status"] == "renamed"],
            "lines_added": sum(r["lines_added"] for r in rows),
            "lines_removed": sum(r["lines_removed"] for r in rows)}


def _detect_renames(before: dict[str, str], after: dict[str, str]) -> dict[str, str]:
    """New names whose bytes are identical to a name that disappeared, matched by digest."""
    gone: dict[str, list[str]] = {}
    for name, text in before.items():
        if name not in after and text.strip():
            gone.setdefault(_digest(text.encode("utf-8", "ignore")), []).append(name)
    out: dict[str, str] = {}
    for name in sorted(after):
        if name in before or not after[name].strip():
            continue
        digest = _digest(after[name].encode("utf-8", "ignore"))
        bucket = gone.get(digest)
        if bucket:
            out[name] = bucket.pop(0)
            if not bucket:
                gone.pop(digest)
    return out


def kept_count(ctx) -> int:
    """How many whole-file-set snapshots this deployment holds, from settings or the module default."""
    return max(1, int(getattr(ctx.settings, "workspace_versions_keep", KEEP_WORKSPACE_VERSIONS)
                      or KEEP_WORKSPACE_VERSIONS))


async def capture(ctx, *, note: str = "", changed: list[str] | None = None,
                  cause: dict | None = None, label: str = "") -> dict:
    """Snapshot every workspace file so this state can be restored later.

    `cause` records what the change was and which agent or plan owned it, so a history entry explains
    itself without anyone re-reading the events: `{"kind", "agent", "plan", "version"}`.
    """
    s, storage = ctx.state, ctx.storage
    if not s.files:
        raise WorkspaceError("Nothing to snapshot: this run has no workspace files yet", 409)
    number = (s.workspace_versions[-1]["w"] if s.workspace_versions else 0) + 1
    entries = []
    for f in s.files:
        data = await storage.load(f["key"])
        key = await storage.save(ctx.run_id, f"workspace/w{number}/{f['name']}", data)
        entries.append({"name": f["name"], "key": key, "bytes": len(data), "hash": _digest(data)})
    record = {"w": number, "at": stamp(), "note": note or "Workspace snapshot",
              "label": (label or "").strip()[:MAX_LABEL_CHARS],
              "cause": clean_cause(cause),
              "html_version": s.html_version, "files": entries, "changed": changed or []}
    s.workspace_versions.append(record)

    keep = kept_count(ctx)
    dropped = s.workspace_versions[:-keep]
    if dropped:
        s.workspace_versions = s.workspace_versions[-keep:]
        for old in dropped:
            for entry in old["files"]:
                try:
                    await storage.delete(entry["key"])
                except Exception:  # noqa: BLE001 - a stray blob must never fail a change
                    pass
    return record


def clean_cause(cause: dict | None) -> dict:
    """The attribution a history entry is allowed to carry: a known kind, and names, not prose.

    An unrecognised kind is recorded as `unattributed` rather than rounded onto the nearest real one -
    history that guesses is worse than history that admits it does not know.
    """
    cause = cause or {}
    kind = cause.get("kind") if cause.get("kind") in CAUSE_KINDS else "unattributed"
    out = {"kind": kind, "agent": (cause.get("agent") or "")[:40],
           "plan": (cause.get("plan") or "")[:12], "run_id": (cause.get("run_id") or "")[:40]}
    try:
        out["version"] = int(cause.get("version") or 0)
    except (TypeError, ValueError):
        out["version"] = 0
    return {k: v for k, v in out.items() if v not in ("", 0)}


async def checkpoint(ctx, *, note: str = "", label: str = "") -> dict:
    """A named snapshot the user asked for, taken because they want it kept, not because a change comes.

    Deliberately not an undo step: nothing moved, so the timeline must not claim it did.
    """
    text = (label or "").strip()
    record = await capture(ctx, note=(note or text or "Named checkpoint"), changed=[],
                           cause={"kind": "manual checkpoint", "version": ctx.state.html_version},
                           label=text)
    return record


def label_snapshot(versions: list[dict], w: int, label: str) -> dict:
    """Name a snapshot so a later reader can tell the release candidate from the experiment.

    Takes the list rather than a context: renaming history is a write to one record, and a route that
    does it needs no run context and no model.
    """
    text = (label or "").strip()
    if not text:
        raise WorkspaceError("A snapshot name cannot be empty; use a clear label or leave it unnamed")
    entry = find_snapshot(versions, w)
    entry["label"] = text[:MAX_LABEL_CHARS]
    return entry


# ------------------------------------------------------------------ undo / redo over the snapshot timeline

def _kept(state, stack: list[int]) -> list[int]:
    """Drop pointers to snapshots the keep window has already pruned, so a step never 404s."""
    present = {v.get("w") for v in state.workspace_versions or []}
    return [w for w in stack or [] if w in present]


def _bounded(stack: list[int]) -> list[int]:
    return stack[-MAX_UNDO_STEPS:]


def record_change(state, w: int) -> None:
    """A change landed. Its pre-change snapshot is the way back, and nothing forward is redoable now."""
    state.undo_stack = _bounded(_kept(state, state.undo_stack) + [w])
    state.redo_stack = []


def record_step(state, w: int, *, forward: bool) -> None:
    """One undo or redo, recorded as the pointer swap it is.

    The step spends the pointer it used and keeps the state it left as the reverse move, so walking
    back three steps never destroys the ability to walk forward again. `w` is the snapshot of the
    page as it stood immediately before this move, which is exactly what the opposite step restores.
    """
    if forward:  # redo: one pointer off the redo side, one onto the undo side
        state.redo_stack = _kept(state, state.redo_stack)[:-1]
        state.undo_stack = _bounded(_kept(state, state.undo_stack) + [w])
    else:        # undo
        state.undo_stack = _kept(state, state.undo_stack)[:-1]
        state.redo_stack = _bounded(_kept(state, state.redo_stack) + [w])


def next_step(state, side: str) -> int:
    """The snapshot the next undo (or redo) would restore - read without spending it.

    A restore that fails before it captures anything leaves here, so the pointer it read is still
    there and the timeline stays walkable; the swap only happens with the snapshot the move takes.
    """
    stack = _kept(state, state.undo_stack if side == "undo" else state.redo_stack)
    if not stack:
        raise WorkspaceError(
            "Nothing to undo: no checkpoint has been recorded for this workspace yet (checkpoints older "
            "than the kept window are gone)" if side == "undo" else
            "Nothing to redo: the workspace has not been stepped back", 409)
    return stack[-1]


def undo_status(state) -> dict:
    """What the interface needs to say about the timeline without guessing."""
    return _status(_kept(state, state.undo_stack), _kept(state, state.redo_stack))


def status_of(state: dict) -> dict:
    """The same view for a run document's state dict, so a read-only route needs no context."""
    state = state or {}
    present = {v.get("w") for v in state.get("workspace_versions") or []}
    return _status([w for w in state.get("undo_stack") or [] if w in present],
                   [w for w in state.get("redo_stack") or [] if w in present])


def _status(back: list[int], forward: list[int]) -> dict:
    return {"can_undo": bool(back), "can_redo": bool(forward),
            "undo_steps": len(back), "redo_steps": len(forward),
            "next_undo": back[-1] if back else None, "next_redo": forward[-1] if forward else None}


# ------------------------------------------------------------------ conflict detection

def check_base(state, base_version: int | None) -> None:
    """Refuse to write over a newer change: a view built on v3 must not apply at v5 unnoticed.

    The caller sends back the version it read. Anything else means another edit - a second tab, a crew
    run, an undo - moved the workspace in between, so the plan was measured against a page that no
    longer exists.
    """
    if base_version is None or base_version == state.html_version:
        return
    raise WorkspaceError(f"Conflict: this change was planned against v{base_version}, but the workspace is "
                         f"now at v{state.html_version}. Read it again and re-plan before applying, or the "
                         f"newer change is lost.", 409)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def digest(data: bytes) -> str:
    """The public reading of a stored file's identity: the hash the editor sends back on a save."""
    return _digest(data)


def find_snapshot(versions: list[dict], w: int) -> dict:
    """One snapshot record out of a state's list, by its number."""
    entry = next((v for v in versions or [] if v.get("w") == w), None)
    if not entry:
        raise WorkspaceError(f"No workspace snapshot w{w}. Kept: "
                             f"{', '.join(str(v.get('w')) for v in versions or [])}", 404)
    return entry


def snapshot_of(ctx, w: int) -> dict:
    return find_snapshot(ctx.state.workspace_versions, w)


async def snapshot_page(ctx, w: int) -> str:
    """The canonical page as stored in that snapshot."""
    entry = snapshot_of(ctx, w)
    page = next((f for f in entry["files"] if f["name"] == "index.html"), None)
    if not page:
        raise WorkspaceError(f"Snapshot w{w} holds no index.html; nothing to restore", 409)
    try:
        return (await ctx.storage.load(page["key"])).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise WorkspaceError(f"Snapshot w{w} could not be read from storage: {exc}", 404) from exc


def check_sizes(texts: dict[str, str], names=None) -> None:
    """Refuse a file the index would have to skip: an oversized workspace file stops being analysable."""
    for name, text in texts.items():
        if names is not None and name not in names:
            continue
        if len(text.encode("utf-8", "ignore")) > MAX_WORKSPACE_FILE_BYTES:
            raise WorkspaceError(f"{name} would grow past {MAX_WORKSPACE_FILE_BYTES} bytes "
                                 f"and stop being indexable")


async def prepare_changes(ctx, changes: list[dict]) -> tuple[dict[str, str], dict[str, str], str]:
    """Apply every patch in memory and fold asset edits into the page.

    Returns (before, after, page_html). Nothing is written until `commit`, so a rejected patch leaves
    the workspace untouched.
    """
    s = ctx.state
    if not s.html:
        raise WorkspaceError("No page has been built yet", 409)
    validated = validate_changes(changes)
    before = await load_texts(ctx)
    before.setdefault("index.html", s.html)
    after = dict(before)
    page = s.html

    for patch in validated:
        name = patch["file"]
        known_file(s, name)
        if name == "index.html":
            page = apply_op(page, patch)
        else:
            updated = apply_op(after.get(name, ""), patch)
            page = fold_into_page(page, name, updated)  # the page is what gets published
            after[name] = updated
        after["index.html"] = page

    check_sizes(after, {*(p["file"] for p in validated), "index.html"})
    return before, after, page


def plan_summary(changes: list[dict], report: dict | None = None) -> dict:
    """What a change set says it will do - stored next to the impact it was measured against."""
    return {"changes": [{"file": c["file"], "op": c["op"],
                         "find": _quote(c["find"]), "note": c["note"]} for c in changes],
            "files": sorted({c["file"] for c in changes}),
            "impact_version": (report or {}).get("version"),
            "scope": (report or {}).get("scope", "unknown"),
            "risk_errors": (report or {}).get("counts", {}).get("errors", 0),
            "risk_warnings": (report or {}).get("counts", {}).get("warnings", 0)}


async def commit(ctx, *, before: dict[str, str], page: str, note: str = "") -> dict:
    """Sanitize, publish and measure the patched workspace. Nothing is written before the guard passes.

    The page goes through the same sanitizer a fresh build does, so a hand-written patch cannot slip
    past the policy; the published file set is then measured against `before` for the change stats.
    """
    s = ctx.state
    clean, violations = sanitize_html(page)
    if not looks_like_html(clean):
        raise WorkspaceError("The patched page is no longer a complete document; nothing was written.", 409)
    s.html = clean
    s.sanitizer_violations = violations
    s.html_version += 1
    s.note = note
    files = await artifacts.publish(ctx)
    s.html_key = next(f["key"] for f in files if f["name"] == "index.html")

    after = await load_texts(ctx)
    after["index.html"] = clean
    report = stats(before, after)
    report.update({"version": s.html_version, "sanitizer_removed": len(violations),
                   "workspace_files": [{"name": f["name"], "bytes": f["bytes"]} for f in files]})
    return report


def record_plan(ctx, *, request: str, changes: list[dict], report: dict | None,
                status: str = "proposed", result: dict | None = None) -> dict:
    """Keep the plan beside the impact it was built from - the audit trail for a file-level edit."""
    s = ctx.state
    number = len(s.change_plans or []) + 1
    entry = {"id": f"p{number}", "at": stamp(), "request": (request or "")[:500], "status": status,
             "version": s.html_version, "summary": plan_summary(changes, report),
             "impact": {"scope": (report or {}).get("scope"), "counts": (report or {}).get("counts"),
                        "targets": [t["name"] for t in (report or {}).get("targets") or []],
                        "risks": [(r["severity"], r["message"]) for r in (report or {}).get("risks") or []][:8]},
             "result": result or {}}
    s.change_plans = (s.change_plans or [])[-19:] + [entry]
    return entry


def summarise_index(index: dict) -> dict:
    """The part of an index worth keeping in run state: counts and names, not every symbol."""
    return {"at": index.get("at", ""), "version": index.get("version", 0),
            "counts": index.get("counts", {}), "truncated": index.get("truncated", False),
            "files": [{"name": f["name"], "language": f.get("language", ""), "bytes": f.get("bytes", 0),
                       "indexed": f.get("indexed", False), "symbols": f.get("symbols", 0),
                       "refs": f.get("refs", 0), "reason": f.get("reason", "")}
                      for f in index.get("files") or []],
            "names": sorted({s["name"] for s in index.get("symbols") or []})[:200]}


# ------------------------------------------------------------------ the editor's own file operations
#
# A workspace is a flat set of bare names, and that is a property of the build rather than a shortcut:
# `index.html` is the document the preview, share link and deploy read, and `styles.css` / `app.js` /
# `README.md` are rebuilt from it. A name with a directory in it would describe a file the single-file
# deploy cannot ship, so these operations keep `validate_name` exactly as the patch path enforces it.
#
# Nothing here runs anything. An authored file is stored, listed, snapshotted and served back; the backend
# never imports or executes it (see `stage_authored`). Saving one moves the file set and earns an undo
# step, and deliberately does not rebuild the page: the page was not touched, so a publish would be a
# claim about a change that did not happen.

KIND_PAGE = "page"
KIND_DERIVED = "derived"
KIND_GENERATED = "generated"
KIND_SOURCE = "source"

# How a file of each kind is written, so the editor asks for the right operation instead of guessing:
# "apply" is a patch through the publish path (snapshot, sanitizer, Chromium re-check), "save" writes the
# bytes as they stand, and None means the file cannot be written at all.
SAVE_VIA = {KIND_PAGE: "apply", KIND_DERIVED: "apply", KIND_SOURCE: "save", KIND_GENERATED: None}
KIND_WHY = {
    KIND_PAGE: "The canonical document: a save here is snapshotted, sanitized, republished and re-checked.",
    KIND_DERIVED: "Rebuilt from the page's own <style> / <script> block, so a save is folded back into "
                  "index.html and travels with the deploy.",
    KIND_GENERATED: "Written by the crew on every build, so an edit here would be undone by the next "
                    "publish. Change the page or the brief instead.",
    KIND_SOURCE: "Source that ships beside the page: stored exactly as written, never executed here, and "
                 "kept through a rebuild.",
}

SEARCH_MAX_QUERY = 200
SEARCH_MAX_MATCHES = 200
SEARCH_MAX_LINE_CHARS = 240
# A caller-supplied regular expression can cost more than the text it scans, so a search stops on the
# clock as well as on the match count and says that it stopped.
SEARCH_TIME_S = 2.0


def file_kind(name: str) -> str:
    """Which of the four roles a workspace file plays, from its name alone."""
    if name == "index.html":
        return KIND_PAGE
    if name in ("styles.css", "app.js"):
        return KIND_DERIVED
    return KIND_SOURCE


def _owned_names(state) -> list[dict]:
    """The authored entries of a state, whether it is a RunState or the run document's stored dict."""
    if isinstance(state, dict):
        return state.get("authored_files") or []
    return state.authored_files or []


def _listed_files(state) -> list[dict]:
    if isinstance(state, dict):
        return state.get("files") or []
    return state.files or []


def describe_file(state, entry: dict) -> dict:
    """One file as the editor needs to see it: what it is, whether it can be written, and how."""
    name = entry.get("name") or ""
    kind = file_kind(name)
    if kind == KIND_SOURCE and not any(f.get("name") == name for f in _owned_names(state)):
        # Listed but not authored and not one of the four names above: it came out of a build, so the
        # build owns it. Saying so is better than offering a save the next publish would quietly drop.
        kind = KIND_GENERATED
    return {"name": name, "language": entry.get("language") or codebase_index.language_of(name),
            "bytes": entry.get("bytes", 0), "note": entry.get("note") or "", "kind": kind,
            "save_via": SAVE_VIA[kind], "editable": SAVE_VIA[kind] is not None, "why": KIND_WHY[kind]}


def describe_workspace(state) -> list[dict]:
    """The file set in the order it was published: the page, its assets, then the source beside them.

    `publish` already writes `files` in that order, so the editor shows what the build means without a
    second sort - and a workspace that gained an authored file keeps the listing its page view has
    always had instead of getting an alphabetical one.
    """
    return [describe_file(state, f) for f in _listed_files(state)]


def authored_entry(state, name: str) -> dict:
    """The recorded entry for a file only the editor owns, with the refusal that says who owns the rest."""
    entry = next((f for f in _owned_names(state) if f.get("name") == name), None)
    if not entry:
        raise WorkspaceError(
            f"{name} is not editor or feature source. index.html, styles.css, app.js and README.md are "
            f"published from the page, so write them through the change set (op 'set') and the patch is "
            f"folded back, sanitized and re-checked like any other edit.", 409)
    return entry


def encode_text(text: str, name: str) -> bytes:
    """Strict UTF-8 with the failure named: a file that cannot be stored whole must not be stored partly."""
    try:
        data = (text or "").encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WorkspaceError(f"{name} cannot be stored: it contains a character that is not valid UTF-8 "
                             f"({exc.reason}). Replace it and save again.") from exc
    if len(data) > MAX_WORKSPACE_FILE_BYTES:
        raise WorkspaceError(f"{name} is {len(data)} bytes, over the {MAX_WORKSPACE_FILE_BYTES} a "
                             f"workspace file may hold and stay indexable")
    return data


async def _step(ctx, *, changed: list[str], note: str, kind: str) -> dict:
    """Snapshot the file set as it stands, then mark that snapshot as the step back."""
    snap = await capture(ctx, note=note, changed=changed,
                         cause={"kind": kind, "agent": "user", "run_id": ctx.run_id,
                                "version": ctx.state.html_version})
    record_change(ctx.state, snap["w"])
    return snap


async def create_file(ctx, name: str, text: str, *, note: str = "") -> dict:
    """Write a new source file beside the page, with the state before it as the undo step."""
    s = ctx.state
    cleaned = validate_name(name)
    if file_kind(cleaned) != KIND_SOURCE or cleaned in DERIVED_NAMES:
        # One of the page's own four names: "pick another name" would be the wrong advice to give, so this
        # asks the ownership question first and gets the answer that names the patch path.
        authored_entry(s, cleaned)
    if any(f.get("name") == cleaned for f in (s.files or [])):
        raise WorkspaceError(f"{cleaned} already exists in this workspace. Open it and save over it, or "
                             f"give the new file another name.", 409)
    staged = await stage_authored(ctx, [{"name": cleaned, "text": text,
                                         "note": note or "Written in the editor.", "source": "editor"}])
    snap = await _step(ctx, changed=[cleaned], note=f"Before creating {cleaned}", kind="file create")
    register_authored(s, staged)
    return {"file": staged[0], "snapshot": snap["w"], "undo": undo_status(s),
            "files": describe_workspace(s)}


async def save_file(ctx, name: str, text: str, *, base_hash: str = "", note: str = "") -> dict:
    """Store a source file exactly as the editor holds it.

    `base_hash` is the digest the editor read. Sending it back means a save that races another writer -
    a second tab, a feature build, an undo - is refused instead of landing on bytes nobody looked at.
    """
    s = ctx.state
    cleaned = validate_name(name)
    entry = authored_entry(s, cleaned)
    data = encode_text(text, cleaned)
    if not data.strip():
        raise WorkspaceError(f"{cleaned}: refusing to save an empty file. Delete it instead, or keep its "
                             f"contents.")
    try:
        current = await ctx.storage.load(entry["key"])
    except Exception as exc:  # noqa: BLE001 - a lost blob is a 404, never a silent rewrite
        raise WorkspaceError(f"{cleaned} could not be read from storage before saving over it: {exc}", 404)
    if base_hash and base_hash != _digest(current):
        raise WorkspaceError(f"Conflict: {cleaned} changed since this file was opened "
                             f"(read {base_hash[:8]}, now {_digest(current)[:8]}). Reload it before saving, "
                             f"or the newer bytes are lost.", 409)
    snap = await _step(ctx, changed=[cleaned], note=f"Before saving {cleaned}", kind="file patch")
    key = await ctx.storage.save(ctx.run_id, cleaned, data)
    update = {"key": key, "bytes": len(data)}
    if note:
        update["note"] = note[:160]
    for row in (s.authored_files or []):
        if row.get("name") == cleaned:
            row.update(update)
    for row in (s.files or []):
        if row.get("name") == cleaned:
            row.update(update)
    return {"file": describe_file(s, entry), "bytes": len(data), "hash": _digest(data),
            "snapshot": snap["w"], "undo": undo_status(s), "files": describe_workspace(s)}


async def rename_file(ctx, old: str, new: str) -> dict:
    """Move a source file to a new name and keep its bytes, so the undo returns the old name."""
    s = ctx.state
    src, dst = validate_name(old), validate_name(new)
    if src == dst:
        raise WorkspaceError("The new name is the one it already has")
    entry = authored_entry(s, src)
    if any(f.get("name") == dst for f in (s.files or [])):
        raise WorkspaceError(f"{dst} already exists in this workspace; one file can hold that name", 409)
    try:
        data = await ctx.storage.load(entry["key"])
    except Exception as exc:  # noqa: BLE001
        raise WorkspaceError(f"{src} could not be read from storage: {exc}", 404) from exc
    snap = await _step(ctx, changed=[src, dst], note=f"Before renaming {src}", kind="file rename")
    key = await ctx.storage.save(ctx.run_id, dst, data)
    moved = {**entry, "name": dst, "key": key, "bytes": len(data),
             "language": codebase_index.language_of(dst),
             "note": (entry.get("note") or "")[:160], "source": entry.get("source") or "editor"}
    s.authored_files = [moved if f.get("name") == src else f for f in (s.authored_files or [])]
    s.files = [moved if f.get("name") == src else f for f in (s.files or [])]
    try:  # the snapshot already holds the old bytes under its own key, so this is cleanup, not safety
        await ctx.storage.delete(entry["key"])
    except Exception:  # noqa: BLE001 - a stray blob must never fail a rename
        pass
    return {"from": src, "to": dst, "snapshot": snap["w"], "undo": undo_status(s),
            "files": describe_workspace(s)}


async def delete_file(ctx, name: str) -> dict:
    """Take a source file out of the workspace. The page is untouched, so nothing is rebuilt.

    Only editor-owned files may be deleted: `index.html` and the assets built from it are what the
    preview, share link and deploy read, and removing one of those is a change to the page, not the file
    set - it belongs on the patch path where the sanitizer and the checks can see it.
    """
    s = ctx.state
    cleaned = validate_name(name)
    entry = authored_entry(s, cleaned)
    snap = await _step(ctx, changed=[cleaned], note=f"Before deleting {cleaned}", kind="file delete")
    s.authored_files = [f for f in (s.authored_files or []) if f.get("name") != cleaned]
    s.files = [f for f in (s.files or []) if f.get("name") != cleaned]
    try:
        await ctx.storage.delete(entry["key"])
    except Exception:  # noqa: BLE001 - the listing is the promise; the blob is best-effort cleanup
        pass
    return {"deleted": cleaned, "snapshot": snap["w"], "undo": undo_status(s),
            "files": describe_workspace(s)}


# ------------------------------------------------------------------ searching the workspace
def _clip_line(line: str) -> str:
    flat = line.strip()
    return (flat[:SEARCH_MAX_LINE_CHARS] + "...") if len(flat) > SEARCH_MAX_LINE_CHARS else flat


def search(texts: dict[str, str], query: str, *, name: str | None = None, regex: bool = False,
           case_sensitive: bool = False) -> dict:
    """Find a phrase or a pattern in the files as they are stored now: no model, no writes, no guessing.

    The scan is bounded on matches, on wall-clock and on file size, and every bound it hits is reported.
    A search that says "stopped at 200 matches" is useful; one that quietly returns a tenth of the answer
    is how a reviewer concludes a file is clean when it is not.
    """
    q = (query or "")[:SEARCH_MAX_QUERY]
    if not q.strip():
        raise WorkspaceError("Type something to search for")
    try:
        pattern = re.compile(q if regex else re.escape(q), 0 if case_sensitive else re.IGNORECASE)
    except re.error as exc:
        raise WorkspaceError(f"That regular expression does not compile: {exc}") from exc

    started, matches, files, skipped, truncated, reason = time.monotonic(), [], [], [], False, ""
    scanned = 0
    ordered = sorted(texts, key=lambda n: (n != "index.html", n))
    for fname in ordered:
        if name and fname != name:
            continue
        scanned += 1
        text = texts[fname]
        if len(text.encode("utf-8", "ignore")) > MAX_WORKSPACE_FILE_BYTES:
            skipped.append({"file": fname, "reason": f"over the {MAX_WORKSPACE_FILE_BYTES} byte cap"})
            continue
        hits = 0
        for line_no, line in enumerate(text.splitlines(), start=1):
            for found in pattern.finditer(line):
                matches.append({"file": fname, "line": line_no, "column": found.start() + 1,
                                "length": max(1, found.end() - found.start()), "text": _clip_line(line)})
                hits += 1
                if len(matches) >= SEARCH_MAX_MATCHES:
                    truncated, reason = True, f"{SEARCH_MAX_MATCHES} matches"
                    break
            if truncated:
                break
        if hits:
            files.append({"file": fname, "matches": hits})
        if truncated:
            break
        if time.monotonic() - started > SEARCH_TIME_S:
            truncated, reason = True, f"stopped after {SEARCH_TIME_S}s to keep the request bounded"
            break
    return {"query": q, "regex": regex, "case_sensitive": case_sensitive, "scope": name or "all files",
            "matches": matches, "files": files, "counts": {"matches": len(matches),
                                                           "files": len(files), "scanned": scanned},
            "skipped": skipped, "truncated": truncated, "reason": reason,
            "limits": {"max_query": SEARCH_MAX_QUERY, "max_matches": SEARCH_MAX_MATCHES,
                       "max_line_chars": SEARCH_MAX_LINE_CHARS, "time_s": SEARCH_TIME_S}}

