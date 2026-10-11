"""Tie one clicked element in the live preview back to the source that declares it.

The preview frame is sandboxed, so this app cannot read its DOM; the page reports the element the user
picked over postMessage. That report describes what is *rendered*, which is not the same thing as what
was written. This module answers "where does this come from?" from the run's own files, and says so
plainly when the answer is not there: a mapping is either found in the published text or the edit is
refused. Nothing here calls a model and no path is invented.

`locate()` works on the same parsed markup the index uses (BeautifulSoup, `sourceline`), so the line it
reports is the line a reader finds in the file. Repeated elements are told apart by the position the
browser reported, and a mismatch between the two counts is treated as a stale selection rather than a
coin flip.
"""
from __future__ import annotations

import re

from app.services import codebase_index, workspace_manager
from app.tools import differ, splitter
from app.tools.audit_util import soup, stamp

MAX_PROPOSALS = 20

MAX_TEXT_CHARS = 160
MAX_ATTR_PAIRS = 12
MAX_ATTR_CHARS = 80
MAX_CLASSES = 16
MAX_CANDIDATES = 6
MAX_PAGE_BYTES = codebase_index.MAX_FILE_BYTES     # above this the page is not indexed, so not mapped
MAX_PAGES = 4
CONTEXT_RADIUS = 5
CONTEXT_CLIP = 220

# A visual edit names a fragment to swap or a rule to add. Writing a whole file from scratch is not a
# visual edit - it is a rebuild, and it belongs to the crew.
VISUAL_OPS = ("replace", "replace_all", "append")
MAX_PATCH_LINES = 60

CSS_REF_KINDS = {"css-id", "css-class"}
DOM_REF_KINDS = {"dom-id", "dom-class"}
SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")


def _clip(value: str, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _whole(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def describe(raw: dict) -> dict:
    """Bind what the frame sent to the sizes this service is willing to reason about.

    Accepts the wire shape (attribute pairs, in document order) and the stored one (a mapping), so a
    proposal read back from run state describes exactly the element it was made for. Clipping is
    idempotent - describing a described element changes nothing.
    """
    raw = raw if isinstance(raw, dict) else {}
    tag = SAFE_NAME.sub("", str(raw.get("tag") or ""))[:24].lower()
    el_id = str(raw.get("id") or "").strip()[:64]
    classes: list[str] = []
    for item in (raw.get("classes") or [])[:MAX_CLASSES]:
        name = str(item).strip()[:64]
        if name and name not in classes:
            classes.append(name)
    attrs: dict[str, str] = {}
    raw_attrs = raw.get("attrs")
    pairs = list(raw_attrs.items()) if isinstance(raw_attrs, dict) else (raw_attrs or [])
    for pair in pairs[:MAX_ATTR_PAIRS]:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            key = str(pair[0]).strip().lower()[:32]
            if key and key not in ("id", "class") and not key.startswith("data-lc"):
                attrs.setdefault(key, _clip(pair[1], MAX_ATTR_CHARS))
    return {"tag": tag, "id": el_id, "classes": classes, "text": _clip(raw.get("text"), MAX_TEXT_CHARS),
            "attrs": attrs, "index": _whole(raw.get("index")), "matches": _whole(raw.get("matches")),
            "path": _clip(raw.get("path"), 200)}


def _miss(reason: str, message: str, **extra) -> dict:
    return {"found": False, "reason": reason, "message": message, **extra}


def _attr_pairs(node) -> list[list[str]]:
    out = []
    for key, value in (node.attrs or {}).items():
        if isinstance(value, list):
            value = " ".join(str(v) for v in value)
        out.append([str(key), _clip(value, MAX_ATTR_CHARS)])
    return out[:MAX_ATTR_PAIRS]


def _matches(node, el: dict) -> bool:
    """The predicate the frame used, applied to the source node instead.

    An id is unique by definition, so it decides on its own. Otherwise the element is told apart by the
    classes it carries and the attribute names written on it - never by its visible text, because the
    same words can appear twice on a page and the position the frame reports is what separates them.
    """
    if el["tag"] and node.name != el["tag"]:
        return False
    if el["id"]:
        return str(node.get("id") or "").strip() == el["id"]
    node_classes = sorted(str(c) for c in (node.get("class") or []) if isinstance(c, str))
    if node_classes != sorted(el["classes"]):
        return False
    return _keys(node.attrs) == _keys(el["attrs"])


def _keys(attrs) -> set[str]:
    """Attribute names written on a node, minus the two that identify it separately."""
    return {str(key) for key in (attrs or {}) if str(key) not in ("id", "class")}


def _via(el: dict) -> tuple[str, str]:
    """How this element was identified, and what that identification is worth."""
    if el["id"]:
        return "id", "exact"
    if el["classes"]:
        return "classes", "exact"
    return "tag", "probable"


def _candidate(name: str, node) -> dict:
    return {"file": name, "line": node.sourceline or 0, "tag": node.name,
            "id": str(node.get("id") or "").strip(),
            "classes": [str(c) for c in (node.get("class") or []) if isinstance(c, str)][:MAX_CLASSES],
            "attrs": _attr_pairs(node)}


def _pages(texts: dict[str, str]) -> list[tuple[str, str]]:
    out = []
    for name in sorted(texts):
        if codebase_index.language_of(name) != "html":
            continue
        text = texts[name]
        if len(text.encode("utf-8", "ignore")) > MAX_PAGE_BYTES:
            continue
        out.append((name, text))
    return out[:MAX_PAGES]


def locate(texts: dict[str, str], el: dict, index: dict | None = None) -> dict:
    """Where this rendered element is written, what styles it, and what script reaches for it."""
    index = index or workspace_manager.index_texts(texts)
    pages = _pages(texts)
    if not pages:
        return _miss("no-page", "This workspace holds no readable HTML page, so nothing on screen can be "
                                "tied back to source.")
    if not el["tag"]:
        return _miss("no-tag", "The preview reported an element with no tag name, so there is nothing to "
                               "search for. Select a node in the page and try again.")

    found: list[tuple[str, object]] = []
    same_tag = 0
    for name, text in pages:
        page = soup(text)
        for node in page.find_all(el["tag"]):
            same_tag += 1
            if _matches(node, el):
                found.append((name, node))

    if not found:
        return _miss("not-found",
                     f"No <{el['tag']}> in this page carries the id, classes and text the preview reported"
                     + (f" ({same_tag} <{el['tag']}> element(s) do exist)" if same_tag else " and the page holds none of that tag")
                     + ". The frame is probably showing a different version than the files: refresh the "
                       "preview and select again.",
                     tag=el["tag"], same_tag=same_tag)

    if el["matches"] is not None and el["matches"] != len(found):
        return _miss("stale", f"The preview reports {el['matches']} element(s) matching this selection but "
                              f"the published page holds {len(found)}. The page changed after this frame was "
                              f"rendered - refresh the preview and select again.",
                     counted=len(found))

    if len(found) == 1:
        picked, node = found[0]
        via, confidence = _via(el)
    else:
        position = el["index"]
        if position is None or position >= len(found):
            return _miss("ambiguous", f"{len(found)} <{el['tag']}> elements match this selection and the "
                                      f"preview sent no position, so there is no honest way to choose one. "
                                      f"Click an element with its own id or class, or edit the file directly.",
                         candidates=[_candidate(name, node) for name, node in found[:MAX_CANDIDATES]],
                         counted=len(found))
        picked, node = found[position]
        via, _exact = _via(el)
        confidence = "positional"

    text = texts[picked]
    line = node.sourceline or 0
    styling, scripting = _pointing_at(index, el, texts)
    return {"found": True, "via": via, "confidence": confidence, "element": el,
            "source": {"file": picked, "line": line, "tag": node.name, "attrs": _attr_pairs(node),
                       "classes": [str(c) for c in (node.get("class") or []) if isinstance(c, str)][:MAX_CLASSES],
                       "id": str(node.get("id") or "").strip(),
                       "text": _clip(node.get_text(" ", strip=True), MAX_TEXT_CHARS),
                       "snippet": codebase_index.snippet(text, line)},
            "styling": styling, "scripting": scripting,
            "candidates": [_candidate(name, n) for name, n in found[:MAX_CANDIDATES]],
            "context": context(text, line)}


def _basis(texts: dict[str, str], ref: dict) -> tuple[str, str, int]:
    """The text and line number a reference should be quoted against.

    Inside an `index.html` the scanner numbers lines within the embedded block, because that is the
    string it parsed. The workspace's `styles.css` / `app.js` are that same text with the block's leading
    newline removed (see `splitter.split_page`), so a page with one block of the kind can be quoted
    against the real file - and a reader who opens it finds the line. Two blocks, or a file that no
    longer matches its block, is not that clean, so the block is named as the basis instead of a file
    whose numbering the line cannot be proven against.
    """
    name, where, line = ref["from"], ref.get("where") or "", ref["line"]
    if where not in ("style", "script") or codebase_index.language_of(name) != "html":
        return texts.get(name, ""), name, line
    html = texts.get(name, "")
    tag = "style" if where == "style" else "script"
    blocks = [b.get_text() for b in soup(html).find_all(tag) if b.get_text().strip()]
    wanted = "styles.css" if where == "style" else "app.js"
    derived = {a.name: a.text for a in splitter.split_page(html)[1]}
    if len(blocks) == 1:
        block = blocks[0]
        target, label = (texts[wanted], wanted) if wanted in texts else (derived.get(wanted, ""),
                                                                        f"{name} <{where}> block")
        if target and block.strip() == target.strip():
            return target, label, line - (len(block) - len(block.lstrip("\n")))
    return "\n\n".join(blocks), f"{name} <{where}> block", line


def _pointing_at(index: dict, el: dict, texts: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Rules and scripts that name this element, deduplicated and read back from the file they live in."""
    names = ([el["id"]] if el["id"] else []) + list(el["classes"])
    styling: list[dict] = []
    scripting: list[dict] = []
    seen: set[tuple] = set()
    for ref in index["refs"]:
        if ref["to"] not in names:
            continue
        bucket = styling if ref["kind"] in CSS_REF_KINDS else (scripting if ref["kind"] in DOM_REF_KINDS else None)
        if bucket is None:
            continue
        basis_text, basis_label, basis_line = _basis(texts, ref)
        key = (basis_label, basis_line, ref["kind"].split("-")[0])
        if key in seen or len(bucket) >= MAX_CANDIDATES * 2:
            continue
        seen.add(key)
        bucket.append({"kind": ref["kind"], "name": ref["to"], "file": ref["from"], "where": ref.get("where", ""),
                       "basis": basis_label, "line": basis_line,
                       "snippet": codebase_index.snippet(basis_text, basis_line)})
    return styling, scripting


def context(text: str, line: int, radius: int = CONTEXT_RADIUS) -> list[dict]:
    """Numbered lines around a declaration - the smallest honest window a model can patch from."""
    rows = text.splitlines()
    if not rows or line < 1:
        return []
    start, stop = max(1, line - radius), min(len(rows), line + radius)
    return [{"n": n, "text": rows[n - 1].strip()[:CONTEXT_CLIP]} for n in range(start, stop + 1)]


def tokens(el: dict) -> list[str]:
    """The strings that tie a fragment to this element: its id, its classes, its tag."""
    out: list[str] = []
    if el["id"]:
        out += [el["id"], f'"{el["id"]}"', f"#{el['id']}"]
    for cls in el["classes"]:
        out += [cls, f".{cls}"]
    if el["tag"] and not el["id"] and not el["classes"]:
        out += [f"<{el['tag']}", f"</{el['tag']}"]
    return out


def names_files(changes: list[dict], located: dict) -> list[str]:
    """Every file this proposal has to touch, so the review screen can say so before anything is applied."""
    files = {c["file"] for c in changes}
    source = (located.get("source") or {}).get("file")
    return sorted(files | ({source} if source else set()))


class PatchError(workspace_manager.WorkspaceError):
    """A model's patch that this workspace will not accept, with the reason the model needs back."""


def verify(raw: dict, texts: dict[str, str], located: dict) -> dict:
    """Prove one patch is real, small and about the selected element - then show what it would do."""
    raw = dict(raw or {})
    if (raw.get("op") or "").strip().lower() == "append":
        # The editor's schema keeps one text field; `append` in the patch language calls it `text`.
        raw.setdefault("text", raw.get("replace") or "")
    patch = workspace_manager.validate_patch(raw)
    if patch["op"] not in VISUAL_OPS:
        raise PatchError(f"op '{patch['op']}' is not a visual edit. Choose a fragment to replace "
                         f"({', '.join(VISUAL_OPS)}) - never rewrite the whole file.")
    name = patch["file"]
    if name not in texts:
        raise PatchError(f"{name} is not a file this workspace holds, so nothing can be patched there. "
                         f"The selected element lives in {(located.get('source') or {}).get('file', 'index.html')}.")
    text = texts[name]
    after = workspace_manager.apply_op(text, patch)      # reuses its exact "not found" / "not unique" errors
    moved = differ.stats(text, after)
    if moved["same"]:
        raise PatchError(f"{name}: the replacement is identical to the text it replaces, so this patch would "
                         f"change nothing. Describe what should look different.")
    if moved["lines_added"] + moved["lines_removed"] > MAX_PATCH_LINES:
        raise PatchError(f"{name}: this patch moves {moved['lines_added'] + moved['lines_removed']} lines, "
                         f"over the {MAX_PATCH_LINES} a visual edit may reach. Narrow it to the selected "
                         f"element or the rule that styles it.")

    hits = [token for token in tokens(located["element"]) if token and token in (patch["find"] + patch["replace"] + patch["text"])]
    region = _region(text, patch)
    return {"patch": patch, "changes": [patch], "files": [name], "lines_added": moved["lines_added"],
            "lines_removed": moved["lines_removed"], "targeted": bool(hits),
            "matched": hits[:6], "region": region, "before": text, "after": after,
            "warning": "" if hits else f"The patch does not name the selected element"
                                       f"{f' ({region})' if region else ''}; it changes something else in "
                                       f"{name}. Review the diff before applying."}


def _region(text: str, patch: dict) -> str:
    """Where in the file this patch lands, as line numbers a reader can open."""
    if patch["op"] == "append":
        return f"end of file (line {text.count(chr(10)) + 1})"
    needle, at, lines = patch["find"], 0, set()
    while True:
        at = text.find(needle, at)
        if at < 0:
            break
        lines.add(text.count("\n", 0, at) + 1)
        at += len(needle)
    if not lines:
        return ""
    first, last = min(lines), max(lines)
    return f"line {first}" if first == last else f"lines {first}-{last}"


def prompt(*, el: dict, located: dict, texts: dict[str, str], instruction: str, impact: str = "") -> str:
    """The one message that gets sent: the request, the element, its source, and the rules that own it."""
    source = located["source"]
    lines = [f"REQUEST: {instruction.strip()[:500]}",
             f"SELECTED ELEMENT: <{el['tag'] or '?'}>"
             + (f" id=\"{el['id']}\"" if el["id"] else "")
             + (f" class=\"{' '.join(el['classes'])}\"" if el["classes"] else "")
             + (f" text=\"{el['text']}\"" if el["text"] else ""),
             f"DECLARED IN: {source['file']} line {source['line']} "
             f"({located['via']}, {located['confidence']} match)",
             f"SOURCE LINE: {source['snippet']}",
             f"CONTEXT ({source['file']}):\n" + "\n".join(f"{row['n']:>4} | {row['text']}" for row in located["context"])]
    for label, key in (("STYLES THAT NAME IT", "styling"), ("SCRIPTS THAT NAME IT", "scripting")):
        rows = located.get(key) or []
        if rows:
            lines.append(label + ":\n" + "\n".join(f"  {r['basis']}:{r['line']} {r['snippet'][:120]}" for r in rows[:8]))
    other = sorted(name for name in texts if name != source["file"])
    if other:
        lines.append(f"OTHER FILES IN THIS WORKSPACE: {', '.join(other)}")
    if impact:
        lines.append(impact.strip()[:1500])
    lines.append("Change only this element or the rules that name it. Copy `find` verbatim from the source "
                 "shown, exactly as printed between the line marker and the end of that fragment, so it "
                 "matches once. Do not touch other elements, do not rewrite the file, do not invent a path.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- the proposal, as run history

def record_proposal(ctx, *, instruction: str, element: dict, located: dict, verified: dict,
                    report: dict | None = None) -> dict:
    """Keep a reviewed proposal beside the selection it came from.

    A proposal is not yet a change: no file is touched and no snapshot is taken here. It is recorded so
    that Apply can prove it means the same patch the user read, and so a later reader can see what was
    asked for, what was found, and what became of it.
    """
    s = ctx.state
    number = len(s.visual_edits or []) + 1
    entry = {"id": f"e{number}", "at": stamp(), "status": "proposed", "run_id": ctx.run_id,
             "version": s.html_version, "instruction": (instruction or "")[:500],
             "element": element, "via": located["via"], "confidence": located["confidence"],
             "source": located["source"],
             "styling": (located.get("styling") or [])[:6], "scripting": (located.get("scripting") or [])[:6],
             "patch": verified["patch"], "targeted": verified["targeted"], "region": verified["region"],
             "warning": verified["warning"], "files": verified["files"],
             "lines_added": verified["lines_added"], "lines_removed": verified["lines_removed"],
             "impact": {"scope": (report or {}).get("scope"), "counts": (report or {}).get("counts"),
                        "risks": [(r["severity"], r["message"]) for r in (report or {}).get("risks") or []][:6]},
             "plan": "", "result": {}}
    s.visual_edits = (s.visual_edits or [])[-(MAX_PROPOSALS - 1):] + [entry]
    return entry


def find_proposal(state, pid: str) -> dict:
    """One recorded proposal, or a 404 that names the ones that do exist."""
    entries = state.visual_edits if hasattr(state, "visual_edits") else (state.get("visual_edits") or [])
    entry = next((e for e in entries or [] if e.get("id") == pid), None)
    if not entry:
        raise workspace_manager.WorkspaceError(
            f"No proposal '{pid}' in this run"
            f" (recorded: {', '.join(e.get('id', '') for e in entries or []) or 'none'})", 404)
    return entry


def mark_proposal(entry: dict, status: str, **extra) -> dict:
    """Say what became of a proposal. History keeps the entry; only its outcome changes."""
    entry["status"] = status
    entry["result"] = {**(entry.get("result") or {}), **extra}
    return entry
