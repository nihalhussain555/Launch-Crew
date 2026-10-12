"""Restyle a built page by editing its tokens, in one reviewable patch.

A theme is a block of custom properties, so the whole site moves with one small edit to the page's
`:root` block: every rule that reads `var(--radius)`, `var(--bg)` or `var(--card-shadow)` follows it.
That is what "apply global design-token changes to compatible components" means here - the patch never
walks the elements, because the elements already point at the variables.

This module finds that block in the run's own published text, writes the values a theme produces, and
says plainly what it could not reach. A page whose CSS hardcodes every colour has no tokens to change,
and inventing a variable that no rule reads would be a change that does nothing while claiming to have
done something; both cases refuse with the reason instead.

Nothing here calls a model, spends a token or writes a byte: `plan()` is pure text work over the files
the caller already loaded. The patch it returns goes through the ordinary workspace pipeline, so a
theme edit gets the same snapshot before it, the same sanitizer and Chromium checks after it, and the
same undo as a hand-written one - it is only labelled differently in history.
"""
from __future__ import annotations

import re

from app.agents import theme as design_theme, variants
from app.llm import mock
from app.services import workspace_manager
from app.services.workspace_manager import WorkspaceError
from app.tools.audit_util import stamp

MAX_THEME_PROPOSALS = 20
MAX_UNREACHED_SHOWN = 12
MAX_NEEDLE_BYTES = 40_000          # the block plus whatever context a unique match needs

# The global `:root` selector and the declarations inside it. A custom property is written with its
# value separately so the value can be swapped without touching the selector, the spacing or any
# comment around it.
_ROOT = re.compile(r":root[^{};]*\{")
_DECL = re.compile(r"(--[a-z][a-z0-9-]*)[ \t]*:[ \t]*([^;{}]+)")

NO_ROOT = ("This page declares no `:root` block, so it has no design tokens to change. A theme edit "
           "would have to rewrite every colour and size on the page separately, which is a rebuild - "
           "ask the crew to revise it in that style instead.")


def variables(direction: variants.DesignDirection) -> dict[str, str]:
    """The custom properties this direction wants, in the names the page builder uses.

    One source of truth for the vocabulary (`mock.PALETTE_VARS`, `mock.token_variables()`), so a patch
    can only ever name a property the builder itself would have written.
    """
    out: dict[str, str] = {}
    for key, var in mock.PALETTE_VARS.items():
        value = str(direction.palette.get(key) or "")
        if mock.is_css(value):
            out[var] = value
    for key, var in mock.token_variables().items():
        value = str(direction.tokens.get(key) or "")
        if mock.is_css(value):
            out[var] = value
    return out


def global_root(text: str) -> tuple[int, int, int] | None:
    """Span of the page's global token block: (selector start, body start, body end).

    Depth is counted between candidates, so the `:root` a responsive override lives in - inside an
    `@media` block, which is how mobile spacing is expressed - is not mistaken for the global one. Only
    the block at depth zero is patched; the override keeps its relative `calc()` values.
    """
    depth = 0
    previous = 0
    for match in _ROOT.finditer(text):
        depth += text.count("{", previous, match.start()) - text.count("}", previous, match.start())
        previous = match.start()
        if depth:
            continue
        close = _matching_brace(text, match.end() - 1)
        if close is None:
            return None
        return match.start(), match.end(), close
    return None


def _matching_brace(text: str, open_at: int) -> int | None:
    """The `}` that closes the `{` at `open_at`, or None if the block never closes."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def used_elsewhere(text: str, var: str) -> bool:
    """Whether some rule outside the token block reads this property - the difference between a token
    that restyles the site and a declaration nothing looks at."""
    return re.search(rf"var\(\s*{re.escape(var)}\s*[,)]", text) is not None


def coverage(texts: dict[str, str], direction: variants.DesignDirection) -> dict:
    """Where each property this theme writes would actually land on this page.

    Three answers, because they mean different things to a reviewer: a property the block already
    declares (the edit changes its value), one the block lacks but a rule reads (the edit adds it, and
    that rule then follows), and one no rule reads (the page hardcodes that part, so a token edit cannot
    reach it). Planning without measuring this is how a restyle quietly becomes a no-op.
    """
    page = texts.get("index.html") or ""
    span = global_root(page)
    wanted = variables(direction)
    body = page[span[1]:span[2]] if span else ""
    rest = (page[:span[1]] + page[span[2]:]) if span else page
    declared = {match.group(1) for match in _DECL.finditer(body)} & set(wanted)
    return {"has_block": span is not None, "wants": wanted, "declared": sorted(declared),
            "reached": sorted(var for var in wanted if var in declared or used_elsewhere(rest, var)),
            "unreached": sorted(set(wanted) - {var for var in wanted
                                               if var in declared or used_elsewhere(rest, var)})}


def _rewrite(body: str, wanted: dict[str, str]) -> tuple[str, list[str], list[str], list[str]]:
    """Swap the value of each token the block already declares, leaving everything else as it was.

    Returns (new body, names whose value changed, names declared here, names already correct). Only the
    value text is replaced, so comments, ordering, spacing and any property the theme does not control
    survive byte for byte.
    """
    pieces: list[str] = []
    last = 0
    changed: list[str] = []
    declared: list[str] = []
    kept: list[str] = []
    for match in _DECL.finditer(body):
        var = match.group(1)
        if var not in wanted:
            continue
        declared.append(var)
        start, end = match.span(2)
        current = body[start:end].strip()
        if current == wanted[var]:
            kept.append(var)
            continue
        changed.append(var)
        pieces.append(body[last:start])
        pieces.append(wanted[var])
        last = end
    pieces.append(body[last:])
    return "".join(pieces), changed, declared, kept


def _unique_needle(text: str, start: int, end: int) -> int:
    """How far left a fragment must reach to name one place in the file.

    Two identical `:root` blocks in one document are a real possibility in hand-edited CSS, and a patch
    that matches twice would be refused by the workspace. Growing the fragment backwards keeps the edit
    unambiguous without rewriting the block twice.
    """
    for left in range(start, max(start - MAX_NEEDLE_BYTES, -1), -512):
        if workspace_manager.occurrences(text, text[left:end]) == 1:
            return left
    raise WorkspaceError("This page contains the same token block more than once, so no single edit can "
                         "tell them apart. Nothing was planned.")


def plan(texts: dict[str, str], direction: variants.DesignDirection) -> dict:
    """The one patch that draws this direction onto the current page, and what it can actually reach.

    A token the block declares gets its value written; a token it does not declare is added only when
    some rule outside the block already reads it, because an unused declaration would be the proof that
    this page cannot be restyled by tokens. When neither case applies to a single token the plan refuses
    with the reason - that is the honest answer, not a patch that changes nothing.
    """
    page = texts.get("index.html") or ""
    span = global_root(page)
    if span is None:
        raise WorkspaceError(NO_ROOT, 409)
    selector_start, body_start, body_end = span
    wanted = variables(direction)
    if not wanted:
        raise WorkspaceError("That theme produces no design tokens, so there is nothing to write.", 422)

    body = page[body_start:body_end]
    new_body, changed, declared, kept = _rewrite(body, wanted)
    rest = page[:body_start] + page[body_end:]
    added = [var for var in wanted if var not in declared and used_elsewhere(rest, var)]
    unreached = [var for var in wanted if var not in declared and var not in added]
    if added:
        head = new_body.rstrip()
        if head and not head.endswith(";"):
            head += ";"
        new_body = head + "".join(f"{var}:{wanted[var]};" for var in added)
    if not changed and not added:
        raise WorkspaceError(f"Nothing on this page is drawn from the tokens that theme changes "
                             f"({len(kept)} of them already hold the values it would write).", 409)

    start = _unique_needle(page, selector_start, body_end + 1)
    block = page[selector_start:body_end + 1]
    new_block = page[selector_start:body_start] + new_body + "}"
    touched = changed + added
    changes = [{"file": "index.html", "op": "replace", "find": page[start:body_end + 1],
                "replace": page[start:selector_start] + new_block,
                "note": (f"Design tokens: {', '.join(touched[:8])}"
                         + (f" (+{len(touched) - 8} more)" if len(touched) > 8 else ""))[:200]}]
    return {"changes": changes, "block": block, "replaced": changed, "added": added, "kept": kept,
            "unreached": unreached[:MAX_UNREACHED_SHOWN], "wants": wanted,
            "declared": len(declared), "reaches": len(touched)}


def recheck(changes: list[dict], texts: dict[str, str]) -> None:
    """Prove a stored patch still means this page before it is applied again.

    A proposal read at v4 must not be applied over a page that has moved on: the block it names either
    still occurs exactly once here or the edit is refused, and the reviewer is told to ask again.
    """
    page = texts.get("index.html") or ""
    for change in changes:
        if change.get("file") != "index.html":
            raise WorkspaceError("A theme patch may only edit the page itself.", 422)
        count = workspace_manager.occurrences(page, change.get("find") or "")
        if count != 1:
            raise WorkspaceError(f"Conflict: the token block this proposal was read from is no longer "
                                 f"here on its own (found {count} times). Load the page again and ask "
                                 f"for the theme once more.", 409)


# --------------------------------------------------------------------------- the proposal, as run history

def record_proposal(ctx, *, request: str, resolved: dict, planned: dict, report: dict | None = None) -> dict:
    """Keep a reviewed theme patch beside the theme it came from.

    Recording is not applying: no file is touched and no snapshot is taken here. The entry exists so
    Apply can prove it means the same patch the reviewer read, and so a later reader can see which theme
    was offered, what it would have reached, and what became of it.
    """
    s = ctx.state
    number = len(s.theme_edits or []) + 1
    entry = {"id": f"t{number}", "at": stamp(), "status": "proposed", "run_id": ctx.run_id,
             "version": s.html_version, "request": (request or "")[:500],
             "theme": design_theme.as_stored(resolved), "summary": design_theme.describe(resolved),
             "palette": dict(resolved.get("palette") or {}),
             "notes": list(resolved.get("notes") or [])[:6],
             "contrast": [{k: pair.get(k) for k in ("pair", "ratio", "passes")}
                          for pair in (resolved.get("contrast") or [])][:8],
             "replaced": planned["replaced"], "added": planned["added"], "kept": planned["kept"],
             "unreached": planned["unreached"], "reaches": planned["reaches"],
             "changes": planned["changes"], "files": ["index.html"],
             "impact": {"scope": (report or {}).get("scope"), "counts": (report or {}).get("counts"),
                        "risks": [(r["severity"], r["message"]) for r in (report or {}).get("risks") or []][:6]},
             "style_key": s.style.get("style_key", ""), "plan": "", "result": {}, "lines_added": 0,
             "lines_removed": 0}
    s.theme_edits = (s.theme_edits or [])[-(MAX_THEME_PROPOSALS - 1):] + [entry]
    return entry


def find_proposal(state, tid: str) -> dict:
    """One recorded theme proposal, or a 404 that names the ones that do exist."""
    entries = state.theme_edits if hasattr(state, "theme_edits") else (state.get("theme_edits") or [])
    entry = next((e for e in entries or [] if e.get("id") == tid), None)
    if not entry:
        raise WorkspaceError(f"No theme proposal '{tid}' in this run (recorded: "
                             f"{', '.join(e.get('id', '') for e in entries or []) or 'none'})", 404)
    return entry


def mark_proposal(entry: dict, status: str, **extra) -> dict:
    """Say what became of a proposal. History keeps the entry; only its outcome changes."""
    entry["status"] = status
    entry["result"] = {**(entry.get("result") or {}), **extra}
    return entry


def status_of(state) -> dict:
    """What a customizer should show before it offers anything: the version a patch would be measured
    against, the theme the run was built with, and the proposal still waiting for a decision."""
    entries = (state.theme_edits if hasattr(state, "theme_edits") else state.get("theme_edits")) or []
    style = (state.style if hasattr(state, "style") else state.get("style")) or {}
    version = (state.html_version if hasattr(state, "html_version") else state.get("html_version")) or 0
    open_entry = next((e for e in reversed(entries) if e.get("status") == "proposed"), None)
    return {"version": version, "open": bool(open_entry), "open_id": (open_entry or {}).get("id", ""),
            "count": len(entries), "max": MAX_THEME_PROPOSALS, "theme": style.get("theme") or {}}
