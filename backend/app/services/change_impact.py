"""What would break if this change were applied - answered before anything edits the workspace.

Two inputs: the workspace index (see `codebase_index`) and the proposed change in plain language.
No model, no network, no filesystem, so the same request against the same build returns the same
report every time and costs nothing to ask. The report names the files a change touches, the sites
that would be left pointing at nothing, and the workspace's own rule - `index.html` is canonical and
`styles.css` / `app.js` are rebuilt from it on every publish - so a multi-file edit is planned
rather than discovered after the fact.

Report:
  {at, version, request, scope, targets, related_files, risks, must, counts, block}
  Target:       {name, kind, files, op, declared, referenced, found}
  RelatedFile:  {file, score, role, symbols, refs, why}
  Risk:         {id, severity: info|warning|error, message, files, symbols}
"""
from __future__ import annotations

import re

from app.tools.audit_util import stamp

CANONICAL = "index.html"
# The derived assets and which embedded block of the page each one is a copy of.
DERIVED = {"styles.css": "style", "app.js": "script"}
EMBEDDED_BLOCK = {block: asset for asset, block in DERIVED.items()}

MAX_TARGETS = 12
MAX_FILES = 10
MAX_RISKS = 20
MAX_WHY = 3
MAX_BLOCK_RISKS = 6
RISK_BLOCK_CHARS = 260
BLOCK_CHARS = 1800

# A reference kind tells us what sort of name it reaches for.
REF_KIND = {"css-id": "id", "dom-id": "id", "anchor": "id", "css-class": "class", "dom-class": "class",
            "css-var": "var", "file": "file", "mention": "file", "url": "asset",
            "import": "module", "request": "endpoint"}

FILE_TOKEN_RE = re.compile(r"[\w./\\-]*[\w-]\.(?:html?|css|js|mjs|md|py|json)\b", re.I)
SELECTOR_RE = re.compile(r"(?<![\w-])([#.][A-Za-z_][\w-]{1,40})")
QUOTED_RE = re.compile(r"""['"`]([^'"`\n]{2,60})['"`]""")
WORD_RE = re.compile(r"[A-Za-z_][\w.-]{1,40}")
PATH_RE = re.compile(r"(?<![\w/])(/[\w./-]{2,60})")
IDENT_LIKE = re.compile(r"[#.]?[A-Za-z_][\w-]{0,40}(?:\.[A-Za-z]{1,5})?")
STOP = {"the", "and", "for", "with", "this", "that", "page", "site", "button", "section", "make",
        "more", "less", "add", "put", "use", "into", "from", "when", "then", "color", "colour",
        "font", "text", "style", "styles", "script", "index", "html", "css", "js", "dark", "light"}
# Words that are both an HTML tag and something the generated page names an element after. Someone
# saying "widen the form" means the visible form, not the `const form` a script happens to declare.
TAG_WORDS = {"a", "abbr", "article", "aside", "audio", "b", "body", "button", "canvas", "card", "caption",
             "code", "col", "data", "details", "dialog", "div", "em", "embed", "fieldset", "figure",
             "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hr", "html", "i",
             "iframe", "img", "input", "label", "legend", "li", "link", "main", "map", "mark", "menu",
             "meta", "nav", "noscript", "object", "ol", "option", "output", "p", "picture", "pre", "progress",
             "q", "rp", "rt", "script", "search", "section", "select", "slot", "small", "source", "span",
             "strong", "style", "sub", "summary", "sup", "svg", "table", "tbody", "td", "template", "textarea",
             "tfoot", "th", "thead", "time", "title", "tr", "track", "ul", "var", "video", "wbr"}

RENAME_RE = re.compile(r"\brename\s+(?:the\s+)?[`'\"#.]?([\w-]{2,40})[`'\"]?\s+(?:to|as|into)\s+[`'\"#.]?([\w-]{2,40})", re.I)
REMOVE_RE = re.compile(r"\b(?:remove|delete|drop|strip|hide)\s+(?:away\s+)?(?:out\s+)?(?:the\s+|an\s+|all\s+)?"
                       r"[`'\"#.]?([\w-]{2,40})", re.I)


def _name_universe(index: dict) -> tuple[dict[str, list], dict[str, list], dict[str, str]]:
    """(declarations by name, references by name, lowercase name -> real name)."""
    decl: dict[str, list] = {}
    refs: dict[str, list] = {}
    by_lower: dict[str, str] = {}
    for s in index.get("symbols") or []:
        name = s.get("name") or ""
        if not name:
            continue
        decl.setdefault(name, []).append(s)
        by_lower.setdefault(name.lower(), name)
    for r in index.get("refs") or []:
        to = r.get("to") or ""
        if not to:
            continue
        refs.setdefault(to, []).append(r)
        by_lower.setdefault(to.lower(), to)
    for entry in index.get("files") or []:
        name = entry.get("name") or ""
        if name:
            by_lower.setdefault(name.lower(), name)
    return decl, refs, by_lower


def _bare(token: str) -> str:
    """Workspace files are keyed by bare name, so a path in the request still means the same file.
    A route beginning with '/' is a name in its own right and must not be shaved down."""
    token = token.strip().strip("`'\"")
    if token.startswith("/"):
        return token
    token = token.lstrip("#.")        # a selector prefix says which kind it is, it is not part of the name
    return re.split(r"[/\\]", token)[-1]


def _kind_for(name: str, hint: str, decl: dict, refs: dict) -> str:
    if hint:
        return hint
    for s in decl.get(name) or []:
        if s.get("kind"):
            return s["kind"]
    for r in refs.get(name) or []:
        kind = REF_KIND.get(r.get("kind") or "")
        if kind:
            return kind
    return "name"


def find_targets(index: dict, request: str) -> list[dict]:
    """Names from the request that this build actually knows about, with their declaration sites."""
    decl, refs, by_lower = _name_universe(index)
    text = request or ""
    found: dict[str, dict] = {}

    def note(raw: str, hint: str, *, keep_unknown: bool = False) -> None:
        token = _bare(raw)
        if not token or token.lower() in STOP:
            return
        name = by_lower.get(token.lower())
        if name is None:
            # An unfamiliar name is only worth reporting when it looks like an identifier,
            # not when it is a phrase the request happened to quote.
            if not keep_unknown or not IDENT_LIKE.fullmatch(token):
                return
            name = token
        entry = found.setdefault(name, {"name": name, "kind": _kind_for(name, hint, decl, refs),
                                        "op": "modify", "matched": []})
        entry["matched"].append(raw.strip()[:40])

    for m in FILE_TOKEN_RE.finditer(text):
        note(m.group(0), "file", keep_unknown=True)
    for m in SELECTOR_RE.finditer(text):
        note(m.group(1), "id" if m.group(1)[0] == "#" else "class", keep_unknown=True)
    for m in QUOTED_RE.finditer(text):
        raw = m.group(1).strip()
        note(raw, "id" if raw.startswith("#") else "class" if raw.startswith(".") else "",
             keep_unknown=not raw.startswith("#") and not raw.startswith("."))
    for m in RENAME_RE.finditer(text):
        note(m.group(1), "", keep_unknown=True)
    for m in REMOVE_RE.finditer(text):
        note(m.group(1), "", keep_unknown=True)
    for m in PATH_RE.finditer(text):
        note(m.group(1), "")
    for m in WORD_RE.finditer(text):
        if m.group(0).lower() not in TAG_WORDS:
            note(m.group(0), "")

    for m in RENAME_RE.finditer(text):
        known = by_lower.get(_bare(m.group(1)).lower())
        if known:
            found[known]["op"] = "rename"
            found[known]["rename_to"] = m.group(2).strip()
    for m in REMOVE_RE.finditer(text):
        known = by_lower.get(_bare(m.group(1)).lower())
        if known:
            found[known]["op"] = "remove"

    out: list[dict] = []
    workspace = {f.get("name") for f in index.get("files") or [] if f.get("name")}
    for name, entry in found.items():
        declarations = decl.get(name) or []
        references = refs.get(name) or []
        files = sorted({*(s.get("file") for s in declarations), *(r.get("from") for r in references)})
        out.append({**entry,
                    "files": files,
                    "declaration_files": sorted({s["file"] for s in declarations if s.get("file")}),
                    "reference_files": sorted({r["from"] for r in references if r.get("from")}),
                    "found": bool(declarations or references or name in workspace),
                    "declared": [_site(s, "declaration") for s in declarations[:MAX_WHY]],
                    "referenced": [_site(r, "reference") for r in references[:MAX_WHY]],
                    "reference_count": len(references),
                    "declaration_count": len(declarations)})
    out.sort(key=lambda t: (-int(t["found"]), -t["reference_count"], t["name"].lower()))
    return out[:MAX_TARGETS]


def _site(item: dict, kind: str) -> dict:
    return {"file": item.get("file") or item.get("from") or "",
            "where": item.get("where") or "",
            "line": item.get("line") or 0,
            "via": item.get("kind") or kind}


def _role(name: str) -> str:
    if name == CANONICAL:
        return "canonical page"
    if name in DERIVED:
        return f"derived copy of the page's <{DERIVED[name]}> block"
    if name == "README.md":
        return "handoff note"
    if name.startswith("tests/"):
        return "generated test"
    return "workspace file"


def related_files(index: dict, targets: list[dict]) -> list[dict]:
    """Files that a change to these names has to touch, ordered by how much of the change lands there."""
    if not targets:
        return []
    names = {t["name"] for t in targets}
    weights = {"declaration": 5, "reference": 3, "contains": 2}
    scores: dict[str, dict] = {}

    def add(file: str, weight: int, why: str) -> None:
        entry = scores.setdefault(file, {"file": file, "score": 0, "symbols": [], "refs": [], "why": []})
        entry["score"] += weight
        if why not in entry["why"]:
            entry["why"].append(why)

    for t in targets:
        for s in index.get("symbols") or []:
            if s.get("name") == t["name"]:
                add(s["file"], weights["declaration"], f"declares {t['kind']} {t['name']} at line {s['line']}")
        for r in index.get("refs") or []:
            if r.get("to") == t["name"]:
                add(r["from"], weights["reference"],
                    f"{r['kind']} reference to {t['name']} at line {r['line']} ({r['where']})")
    for entry in index.get("files") or []:
        if entry.get("name") in names:
            add(entry["name"], weights["contains"], "named directly in the change")
            for t in targets:
                if t["name"] == entry["name"]:
                    t.setdefault("role", _role(entry["name"]))

    out = []
    for name, entry in scores.items():
        entry["file"] = name
        entry["role"] = _role(name)
        entry["why"] = entry["why"][:MAX_WHY]
        out.append(entry)
    out.sort(key=lambda e: (-e["score"], e["file"]))
    return out[:MAX_FILES]


def _risk(id_: str, severity: str, message: str, files: list[str], symbols: list[str]) -> dict:
    return {"id": id_, "severity": severity, "message": message[:400],
            "files": sorted(set(f for f in files if f))[:8], "symbols": sorted(set(symbols))[:8]}


def risks(index: dict, targets: list[dict], related: list[dict]) -> list[dict]:
    """Breakage a change to these names would cause, each with the files and names involved."""
    out: list[dict] = []
    workspace = {f.get("name") for f in index.get("files") or [] if f.get("name")}

    for t in targets:
        name, kind = t["name"], t["kind"]
        if not t["found"]:
            if kind == "file":
                out.append(_risk("unknown-file", "warning",
                                 f"'{name}' is named in the change but no such file is in this build. "
                                 f"A publish only writes {', '.join(sorted(workspace)) or 'nothing'}.",
                                 [name], [name]))
            else:
                out.append(_risk("unknown-name", "warning",
                                 f"'{name}' matches nothing in the current index - the change is naming a "
                                 f"new symbol, so nothing else references it yet.", [], [name]))
            continue

        if t["op"] in ("rename", "remove") and t["reference_count"]:
            to = t.get("rename_to")
            verb = "Renaming" if to else "Removing"
            out.append(_risk("orphaned-reference", "error",
                             f"{verb} {kind} '{name}'{f' to {to}' if to else ''} leaves "
                             f"{t['reference_count']} reference(s) pointing at nothing: "
                             + "; ".join(f"{r['file']}:{r['line']} ({r['via']}, {r['where']})" for r in t["referenced"])
                             + ". Update them in the same change.",
                             t["reference_files"], [name]))

        if not t["declared"] and t["referenced"]:
            out.append(_risk("dangling-reference", "warning",
                             f"'{name}' is referenced but declared nowhere in the workspace, so it is "
                             f"already broken before this change: "
                             + "; ".join(f"{r['file']}:{r['line']}" for r in t["referenced"]) + ".",
                             t["reference_files"], [name]))

        if len(t["declaration_files"]) > 1:
            out.append(_risk("duplicate-declaration", "warning",
                             f"'{name}' is declared in {len(t['declaration_files'])} files "
                             f"({', '.join(t['declaration_files'])}). A patch that names only one of them "
                             f"leaves the other behind.",
                             t["declaration_files"], [name]))
        paired = _paired_sites(index, name)
        if paired:
            assets = sorted(paired.values())
            out.append(_risk("paired-copy", "error",
                             f"'{name}' appears in the page's {', '.join(sorted('<' + b + '>' for b in paired))} "
                             f"and in {', '.join(assets)}, which is rebuilt from that block on every publish. "
                             f"Change both in the same edit or {', '.join(assets)} reverts.",
                             [CANONICAL, *assets], [name]))

        if t["reference_count"] >= 4:
            out.append(_risk("wide-blast-radius", "warning",
                             f"'{name}' is used at {t['reference_count']} sites across "
                             f"{', '.join(t['files'])}. Expect the change to ripple.",
                             t["files"], [name]))

        if kind == "id" and any(r["via"] == "anchor" for r in t["referenced"]):
            out.append(_risk("anchor-target", "error",
                             f"'{name}' is an in-page jump target (skip link or nav anchor). Changing it "
                             f"breaks keyboard navigation unless the href changes too.",
                             [r["file"] for r in t["referenced"] if r["via"] == "anchor"], [name]))

        if kind in ("endpoint", "module", "asset") and not t["declared"]:
            out.append(_risk("outside-workspace", "info",
                             f"'{name}' is reached as a {kind}; it is not part of this workspace, so the "
                             f"crew can change the call site but not the thing being called.",
                             t["files"], [name]))

    touched = {f["file"] for f in related_files(index, targets)}
    if touched & set(DERIVED):
        out.append(_risk("canonical-source", "error",
                         f"This change touches derived asset(s) "
                         f"{', '.join(sorted(touched & set(DERIVED)))}. The preview, share link, deploy and "
                         f"browser checks all read {CANONICAL}: the same edit must land in the page's "
                         f"embedded block or it will not be visible.",
                         sorted(touched & set(DERIVED)) + [CANONICAL], []))

    readme_refs = {r["from"] for r in index.get("refs") or [] if r.get("kind") == "mention"}
    if readme_refs & touched:
        out.append(_risk("handoff-note", "info",
                         "README.md names the file(s) being changed; the handoff note should say the same thing.",
                         sorted(readme_refs), []))

    if not targets:
        out.append(_risk("no-named-target", "info",
                         "The change names no file or symbol this build knows about, so the whole page is "
                         "in scope. Keep the edit bounded and re-check every block.", [], []))

    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda r: (order.get(r["severity"], 3), r["id"]))
    deduped: list[dict] = []
    seen: set[tuple] = set()
    for r in out:
        key = (r["id"], tuple(r["symbols"]), tuple(r["files"]))
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped[:MAX_RISKS]


def _paired_sites(index: dict, name: str) -> dict:
    """{embedded block: derived asset} for a name that lives in both places.

    Scans the whole index rather than a target's display list, which is capped.
    """
    sites = [(s.get("file"), s.get("where")) for s in index.get("symbols") or [] if s.get("name") == name]
    sites += [(r.get("from"), r.get("where")) for r in index.get("refs") or [] if r.get("to") == name]
    blocks = {where for _, where in sites if where in EMBEDDED_BLOCK}
    assets = {file for file, _ in sites if file in DERIVED}
    return {b: EMBEDDED_BLOCK[b] for b in blocks if EMBEDDED_BLOCK[b] in assets}


def scope_of(index: dict, targets: list[dict], related: list[dict]) -> str:
    """How far the change reaches - the Engineer is told to stay inside it."""
    if not targets:
        return "workspace-wide"
    files = {f["file"] for f in related}
    if len(files) > 1:
        return "multi-file"
    if any(t["op"] != "modify" and t["reference_count"] for t in targets):
        return "multi-file"
    return "single-file"


MUST = (
    f"{CANONICAL} is the source of truth: preview, share, deploy and browser checks all read it.",
    "styles.css and app.js are derived from the page's embedded <style>/<script> blocks on every "
    "publish - a patch to one of them must be applied to the block too, in the same change.",
    "Change only the files and names the impact report lists. Anything else is out of scope.",
    "After the edit, the crew re-runs the sanitizer and the Chromium checks against the rebuilt page.",
)


def block_for_prompt(report: dict, *, limit: int = BLOCK_CHARS) -> str:
    """The compact text an agent gets: the plan, then the risks, then the rules.

    Risk lines are dropped from the end until the block fits - the plan and the workspace rules are
    never sacrificed, because those are the lines an agent must obey.
    """
    header = [f"IMPACT REPORT for v{report.get('version', '?')} "
              f"({report.get('scope', 'unknown')} change) - measured from the workspace index, no model used."]
    targets = report.get("targets") or []
    if targets:
        header.append("Named by the request: " + ", ".join(
            f"{t['kind']} {t['name']}"
            + (f" [{t['op']}" + (f" -> {t.get('rename_to') or ''}]" if t["op"] == "rename" else "]")
               if t["op"] != "modify" else "")
            + (f" ({len(t['files'])} file(s))" if len(t["files"]) > 1 else "")
            for t in targets[:6]))
    else:
        header.append("Named by the request: nothing this build declares - treat the page as one scope.")
    related = report.get("related_files") or []
    if related:
        header.append("Files in scope: " + " | ".join(
            f"{f['file']} ({f['role']}; {f['why'][0] if f['why'] else 'named'})" for f in related[:6]))

    risks = [f"RISK {r['severity'].upper()}: {r['message'][:RISK_BLOCK_CHARS]}"
             for r in (report.get("risks") or [])[:MAX_BLOCK_RISKS]]
    risks = risks or ["RISK: none found - the named symbols are referenced only where they are declared."]
    rules = "RULES: " + " ".join(MUST[:3])

    kept = list(risks)
    for take in range(len(kept), 0, -1):
        lines = kept[:take]
        if take < len(kept):
            lines = lines + [f"({len(kept) - take} further risk(s) in the report)"]
        text = "\n".join([*header, *lines, rules])
        if len(text) <= limit:
            return text
    text = "\n".join([*header, rules])
    if len(text) <= limit:
        return text
    trimmed = text[:limit]
    cut = trimmed.rfind("\n")
    return (trimmed[:cut] if cut > 0 else trimmed) + "\n(truncated)"


def analyze(index: dict, request: str, *, version: int | None = None) -> dict:
    """Full impact report for `request` against an index built from the current build."""
    index = index or {}
    targets = find_targets(index, request)
    related = related_files(index, targets)
    found = risks(index, targets, related)
    if version is not None and index.get("version") not in (None, version):
        found = [_risk("stale-index", "warning",
                       f"Impact was measured against v{index.get('version')} but the workspace is at "
                       f"v{version}; re-index before trusting this plan.", [], [])] + found
    report = {"at": stamp(), "version": index.get("version", version or 0), "request": (request or "")[:500],
              "scope": scope_of(index, targets, related), "targets": targets, "related_files": related,
              "risks": found,
              "counts": {"targets": len(targets), "files": len(related),
                         "errors": sum(1 for r in found if r["severity"] == "error"),
                         "warnings": sum(1 for r in found if r["severity"] == "warning")},
              "indexed_files": [f.get("name") for f in index.get("files") or []]}
    report["block"] = block_for_prompt(report)
    report["must"] = list(MUST)
    return report


def empty(request: str, *, version: int = 0, reason: str = "") -> dict:
    """A report for a workspace that has no files to index yet."""
    report = {"at": stamp(), "version": version, "request": (request or "")[:500], "scope": "single-file",
              "targets": [], "related_files": [],
              "risks": [_risk("no-index", "info", reason or "Nothing to analyse yet.", [], [])],
              "counts": {"targets": 0, "files": 0, "errors": 0, "warnings": 0}, "indexed_files": []}
    report["block"] = block_for_prompt(report)
    report["must"] = list(MUST)
    return report


def headline(report: dict) -> str:
    c = report.get("counts", {})
    bits = [f"{c.get('targets', 0)} name(s)", f"{c.get('files', 0)} file(s) in scope",
            f"{c.get('errors', 0)} error(s)", f"{c.get('warnings', 0)} warning(s)"]
    return f"{report.get('scope', 'unknown')} change: " + ", ".join(bits) + "."
