"""Deliberate file-level edits: validate the path, apply the patch, keep the workspace restorable.

The crew's rebuilds go through `artifacts.publish` (the Engineer writes a whole page). This module is
for the other kind of change - someone names a file and says what to replace - which the pipeline has
never supported. Two invariants make that safe:

1. `index.html` is canonical. `styles.css` / `app.js` are derived from the page's embedded
   `<style>` / `<script>` blocks on every publish, so a patch to one of them is folded back into that
   block here, or the next build would silently undo it.
2. Nothing is overwritten without a snapshot. `capture()` stores the whole file set first, so any
   applied change - or the model-driven rebuilds - can be restored by workspace version.

Everything here is deterministic: no LLM, no network, no host filesystem (paths are checked against
the run's recorded file set, never resolved against disk).
"""
from __future__ import annotations

import hashlib
import re

from app.agents.base import looks_like_html
from app.orchestrator import artifacts
from app.services import codebase_index
from app.tools import differ, splitter
from app.tools.audit_util import stamp
from app.tools.sanitizer import sanitize_html

MAX_PATCH_BYTES = 60_000          # one patch's worth of new text
MAX_WORKSPACE_FILE_BYTES = 200_000  # per file: keeps it indexable (see codebase_index)
MAX_NAME_CHARS = 64
KEEP_WORKSPACE_VERSIONS = 10
ALLOWED_EXTENSIONS = {"html", "htm", "css", "js", "mjs", "md", "py", "json", "txt"}
OPS = ("replace", "replace_all", "append", "set")

# Files the crew rewrites itself: patching them here would be undone by the next build.
GENERATED_ONLY = {"README.md"}
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


def stats(before: dict[str, str], after: dict[str, str]) -> dict:
    """Per-file line movement for an applied change set."""
    rows = []
    for name in sorted(set(before) | set(after)):
        a, b = before.get(name, ""), after.get(name, "")
        if name not in before:
            rows.append({"file": name, "status": "added", "bytes_before": 0, "bytes_after": len(b.encode()),
                         "lines_added": b.count("\n") + 1, "lines_removed": 0})
        elif name not in after:
            rows.append({"file": name, "status": "removed", "bytes_before": len(a.encode()), "bytes_after": 0,
                         "lines_added": 0, "lines_removed": a.count("\n") + 1})
        else:
            d = differ.stats(a, b)
            rows.append({"file": name, "status": "unchanged" if d["same"] else "changed",
                         "bytes_before": len(a.encode()), "bytes_after": len(b.encode()),
                         "lines_added": d["lines_added"], "lines_removed": d["lines_removed"]})
    return {"files": rows,
            "changed": [r["file"] for r in rows if r["status"] == "changed"],
            "lines_added": sum(r["lines_added"] for r in rows),
            "lines_removed": sum(r["lines_removed"] for r in rows)}


async def capture(ctx, *, note: str = "", changed: list[str] | None = None) -> dict:
    """Snapshot every workspace file so this state can be restored later."""
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
              "html_version": s.html_version, "files": entries, "changed": changed or []}
    s.workspace_versions.append(record)

    dropped = s.workspace_versions[:-KEEP_WORKSPACE_VERSIONS]
    if dropped:
        s.workspace_versions = s.workspace_versions[-KEEP_WORKSPACE_VERSIONS:]
        for old in dropped:
            for entry in old["files"]:
                try:
                    await storage.delete(entry["key"])
                except Exception:  # noqa: BLE001 - a stray blob must never fail a change
                    pass
    return record


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def snapshot_of(ctx, w: int) -> dict:
    entry = next((v for v in ctx.state.workspace_versions or [] if v.get("w") == w), None)
    if not entry:
        raise WorkspaceError(f"No workspace snapshot w{w}. Kept: "
                             f"{', '.join(str(v.get('w')) for v in ctx.state.workspace_versions or [])}", 404)
    return entry


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
