"""A safe, bounded index over the files a run's workspace holds.

Deterministic and offline: it reads the text the crew already published (never the host
filesystem, never a path a caller invented), walks it with regexes plus the shared BeautifulSoup
parser, and records the names each file declares and the names each file references. That graph is
what `change_impact` uses to answer "if this changes, what else moves?" without calling a model.

Shapes:
  Symbol: {name, kind, file, where, line}        kind: id|class|field|var|fn|const|type|heading
  Ref:    {from, kind, to, where, line}          kind: css-id|css-class|css-var|dom-id|dom-class|
                                                      anchor|file|url|import|request|mention
  Index:  {at, version, files, symbols, refs, counts, truncated}
`where` separates markup from the blocks embedded in it, because `index.html` is self-contained and
`styles.css` / `app.js` are derived copies of those same blocks.
"""
from __future__ import annotations

import hashlib
import re

from app.tools.audit_util import soup, stamp

MAX_FILE_BYTES = 200_000        # one file's worth of text we are willing to parse
MAX_TOTAL_BYTES = 1_000_000     # whole-workspace budget, so an index can never run away
MAX_FILES = 64                  # files per workspace
MAX_ENTRIES = 4_000             # per list (symbols / refs)

# kind -> which language can declare it
LANGUAGE_BY_EXTENSION = {"html": "html", "htm": "html", "css": "css", "js": "js", "mjs": "js",
                         "md": "md", "markdown": "md", "py": "py", "json": "json", "txt": "text"}

ID_RE = re.compile(r"[A-Za-z_][\w-]*")
CSS_RULE_RE = re.compile(r"(?P<sel>[^{}@;]+)\{(?P<body>[^{}]*)\}", re.S)
CSS_VAR_DEF_RE = re.compile(r"(--[\w-]+)\s*:")
CSS_VAR_USE_RE = re.compile(r"var\(\s*(--[\w-]+)")
CSS_URL_RE = re.compile(r"""url\(\s*['"]?\s*([^)'"]+)['"]?\s*\)""", re.I)
CSS_IMPORT_RE = re.compile(r"""@import[^;]*?['"]([^'"]+)['"]""", re.I)

JS_NAME = r"[A-Za-z_$][A-Za-z0-9_$]*"
JS_DECL_RES = (
    (re.compile(rf"\bfunction\s*\*?\s*({JS_NAME})", re.I), "fn"),
    (re.compile(rf"\bclass\s+({JS_NAME})"), "type"),
    (re.compile(rf"\b(?:const|let|var)\s+({JS_NAME})\s*="), "const"),
)
JS_REF_RES = (
    (re.compile(rf"""getElementById\(\s*['"]([^'"]+)['"]"""), "dom-id"),
    (re.compile(r"""querySelector(?:All)?\(\s*['"`]([^'"`]+)['"`]"""), "dom-query"),
    (re.compile(r"""getElementsByClassName\(\s*['"]([^'"]+)['"]"""), "dom-class-list"),
    (re.compile(r"""classList\.(?:add|remove|toggle|contains|replace)\(([^)]*)\)""", re.I), "dom-class"),
    (re.compile(r"""className\s*=\s*['"]([^'"]*)['"]"""), "dom-class"),
)
JS_IMPORT_RE = re.compile(r"""(?:import\b[^'"]*?from\s*|import\s*\(\s*|require\(\s*)['"]([^'"]+)['"]""")
JS_FETCH_RE = re.compile(r"""(?:fetch|open)\(\s*['"]([^'"]+)['"]""")

PY_DEF_RE = re.compile(r"^[ \t]*(?:def|async\s+def)\s+([A-Za-z_]\w*)", re.M)
PY_CLASS_RE = re.compile(r"^[ \t]*class\s+([A-Za-z_]\w*)", re.M)
PY_IMPORT_RE = re.compile(r"^[ \t]*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
MD_FILE_RE = re.compile(r"`([^`\s]+\.(?:html?|css|js|md|py|json))`")

WHERE_MARKUP, WHERE_STYLE, WHERE_SCRIPT, WHERE_SOURCE = "markup", "style", "script", "source"


def language_of(name: str, declared: str = "") -> str:
    """The workspace entry's language, falling back to the extension when the record omits it."""
    if declared:
        return declared
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return LANGUAGE_BY_EXTENSION.get(ext, "text")


def _line_at(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:12]


def _add(bucket: list, item) -> bool:
    """Append unless already present or the bucket is full; tells the caller whether data was lost."""
    if item in bucket:
        return False
    if len(bucket) >= MAX_ENTRIES:
        return True
    bucket.append(item)
    return False


def scan_css(text: str, file: str, where: str, symbols: list, refs: list) -> bool:
    """Selectors, custom properties and asset references inside a stylesheet."""
    truncated = False
    for m in CSS_RULE_RE.finditer(text):
        line = _line_at(text, m.start())
        for part in m["sel"].split(","):
            # A selector is a *reference*: the element it names is declared in the markup, not here.
            for ident in re.findall(r"#([\w-]+)", part):
                truncated |= _add(refs, {"from": file, "kind": "css-id", "to": ident, "where": where,
                                         "line": line})
            for cls in re.findall(r"\.([A-Za-z_][\w-]*)", part):
                truncated |= _add(refs, {"from": file, "kind": "css-class", "to": cls, "where": where,
                                         "line": line})
        for name in CSS_VAR_USE_RE.findall(m["body"]):
            truncated |= _add(refs, {"from": file, "kind": "css-var", "to": name[2:], "where": where,
                                     "line": line})
        for decl in CSS_VAR_DEF_RE.findall(m["body"]):
            truncated |= _add(symbols, {"name": decl[2:], "kind": "var", "file": file, "where": where,
                                        "line": line})
    for m in CSS_URL_RE.finditer(text):
        target = m.group(1).strip()
        if target.startswith("data:"):
            continue
        kind = "url"
        truncated |= _add(refs, {"from": file, "kind": kind, "to": target, "where": where,
                                 "line": _line_at(text, m.start())})
    for m in CSS_IMPORT_RE.finditer(text):
        truncated |= _add(refs, {"from": file, "kind": "file", "to": m.group(1).strip(), "where": where,
                                 "line": _line_at(text, m.start())})
    return truncated


def scan_js(text: str, file: str, where: str, symbols: list, refs: list) -> bool:
    """Declarations and the DOM names a script reaches for."""
    truncated = False
    for regex, kind in JS_DECL_RES:
        for m in regex.finditer(text):
            truncated |= _add(symbols, {"name": m.group(1), "kind": kind, "file": file, "where": where,
                                        "line": _line_at(text, m.start())})
    for regex, kind in JS_REF_RES:
        for m in regex.finditer(text):
            line = _line_at(text, m.start())
            for token in _dom_tokens(m.group(1), kind):
                truncated |= _add(refs, {"from": file, "kind": token[0], "to": token[1], "where": where,
                                         "line": line})
    for m in JS_IMPORT_RE.finditer(text):
        truncated |= _add(refs, {"from": file, "kind": "import", "to": m.group(1), "where": where,
                                 "line": _line_at(text, m.start())})
    for m in JS_FETCH_RE.finditer(text):
        truncated |= _add(refs, {"from": file, "kind": "request", "to": m.group(1), "where": where,
                                 "line": _line_at(text, m.start())})
    return truncated


def _dom_tokens(selector: str, hint: str) -> list[tuple[str, str]]:
    """Turn whatever a DOM call was handed into (ref kind, name) pairs."""
    out: list[tuple[str, str]] = []
    for piece in re.findall(r"""['"]([^'"]+)['"]|([^\s,]+)""", selector or ""):
        token = (piece[0] or piece[1] or "").strip()
        if not token:
            continue
        if hint == "dom-query":
            if token.startswith("#"):
                out.append(("dom-id", token[1:]))
            elif token.startswith("."):
                out.extend(("dom-class", c) for c in ID_RE.findall(token))
            continue
        if hint == "dom-class-list":
            out.extend(("dom-class", c) for c in token.split())
            continue
        if hint == "dom-id":
            out.append(("dom-id", token))
            continue
        out.extend(("dom-class", c) for c in ID_RE.findall(token))
    return out


def scan_html(text: str, file: str, symbols: list, refs: list) -> bool:
    """Markup, plus the style/script blocks it embeds (the page is self-contained)."""
    truncated = False
    page = soup(text)
    for el in page.find_all(True):
        line = el.sourceline or 0
        el_id = (el.get("id") or "").strip()
        if el_id:
            truncated |= _add(symbols, {"name": el_id, "kind": "id", "file": file, "where": WHERE_MARKUP,
                                        "line": line})
        for cls in el.get("class") or []:
            if isinstance(cls, str) and cls.strip():
                truncated |= _add(symbols, {"name": cls.strip(), "kind": "class", "file": file,
                                            "where": WHERE_MARKUP, "line": line})
        for name in filter(None, [f.strip() for f in ([el.get("name")] if isinstance(el.get("name"), str) else [])]):
            if el.name in ("input", "select", "textarea"):
                truncated |= _add(symbols, {"name": name, "kind": "field", "file": file,
                                            "where": WHERE_MARKUP, "line": line})
        if re.fullmatch(r"h[1-6]", el.name or ""):
            heading = " ".join(el.get_text(" ", strip=True).split())[:60]
            if heading:
                truncated |= _add(symbols, {"name": heading, "kind": "heading", "file": file,
                                            "where": WHERE_MARKUP, "line": line})
        href = el.get("href") or el.get("src") or ""
        href = " ".join(href) if isinstance(href, list) else str(href).strip()
        if not href:
            continue
        if href.startswith("#"):
            truncated |= _add(refs, {"from": file, "kind": "anchor", "to": href[1:], "where": WHERE_MARKUP,
                                     "line": line})
        elif re.match(r"^\s*(https?:)?//", href, re.I):
            truncated |= _add(refs, {"from": file, "kind": "request", "to": href, "where": WHERE_MARKUP,
                                     "line": line})
        elif not href.startswith(("data:", "mailto:", "tel:", "javascript:")):
            truncated |= _add(refs, {"from": file, "kind": "file", "to": href, "where": WHERE_MARKUP,
                                     "line": line})

    for st in page.find_all("style"):
        truncated |= scan_css(st.get_text(), file, WHERE_STYLE, symbols, refs)
    for sc in page.find_all("script"):
        if (sc.get("type") or "").lower() in ("application/ld+json", "importmap"):
            continue
        if sc.get("src"):
            continue
        truncated |= scan_js(sc.get_text(), file, WHERE_SCRIPT, symbols, refs)
    return truncated


def scan_md(text: str, file: str, symbols: list, refs: list) -> bool:
    truncated = False
    for m in MD_HEADING_RE.finditer(text):
        truncated |= _add(symbols, {"name": m.group(2).strip()[:60], "kind": "heading", "file": file,
                                    "where": WHERE_SOURCE, "line": _line_at(text, m.start())})
    for m in MD_FILE_RE.finditer(text):
        truncated |= _add(refs, {"from": file, "kind": "mention", "to": m.group(1), "where": WHERE_SOURCE,
                                 "line": _line_at(text, m.start())})
    return truncated


def scan_py(text: str, file: str, symbols: list, refs: list) -> bool:
    truncated = False
    for m in PY_DEF_RE.finditer(text):
        truncated |= _add(symbols, {"name": m.group(1), "kind": "fn", "file": file, "where": WHERE_SOURCE,
                                    "line": _line_at(text, m.start())})
    for m in PY_CLASS_RE.finditer(text):
        truncated |= _add(symbols, {"name": m.group(1), "kind": "type", "file": file, "where": WHERE_SOURCE,
                                    "line": _line_at(text, m.start())})
    for m in PY_IMPORT_RE.finditer(text):
        target = m.group(1) or m.group(2) or ""
        if target:
            truncated |= _add(refs, {"from": file, "kind": "import", "to": target.split(".")[0],
                                     "where": WHERE_SOURCE, "line": _line_at(text, m.start())})
    return truncated


def scan(name: str, text: str, language: str = "") -> dict:
    """One workspace file -> its symbols and references. Oversized text is reported, not parsed."""
    language = language_of(name, language)
    entry = {"name": name, "language": language, "bytes": len(text.encode("utf-8", "ignore")),
             "lines": text.count("\n") + 1, "hash": _digest(text), "indexed": False, "reason": ""}
    symbols: list[dict] = []
    refs: list[dict] = []
    truncated = False
    scanners = {"html": lambda: scan_html(text, name, symbols, refs),
                "css": lambda: scan_css(text, name, WHERE_SOURCE, symbols, refs),
                "js": lambda: scan_js(text, name, WHERE_SOURCE, symbols, refs),
                "md": lambda: scan_md(text, name, symbols, refs),
                "py": lambda: scan_py(text, name, symbols, refs)}
    if entry["bytes"] > MAX_FILE_BYTES:
        entry["reason"] = f"not indexed: {entry['bytes']} bytes over the {MAX_FILE_BYTES} byte cap"
    elif language not in scanners:
        entry["reason"] = f"not indexed: no scanner for .{name.rsplit('.', 1)[-1]}"
    else:
        truncated = scanners[language]()
        entry["indexed"] = True
    entry["symbols"] = len(symbols)
    entry["refs"] = len(refs)
    return {"file": entry, "symbols": symbols, "refs": refs, "truncated": truncated}


def _skipped(name: str, language: str, size: int, reason: str) -> dict:
    return {"name": name, "language": language, "bytes": size, "lines": 0, "hash": "",
            "indexed": False, "symbols": 0, "refs": 0, "reason": f"not indexed: {reason}"}


def build_index(files: list[dict], *, version: int = 0, at: str = "") -> dict:
    """Index a workspace. `files` is [{name, language, text}]; text comes from the run's storage."""
    out = {"at": at or stamp(), "version": version, "files": [], "symbols": [], "refs": [],
           "counts": {}, "truncated": False}
    used = 0
    for position, item in enumerate(files):
        name = item.get("name") or ""
        if not name:
            continue
        language = language_of(name, item.get("language") or "")
        text = item.get("text") or ""
        size = len(text.encode("utf-8", "ignore"))
        if position >= MAX_FILES:
            out["files"].append(_skipped(name, language, size, f"over the {MAX_FILES} file limit"))
            out["truncated"] = True
            continue
        if used + size > MAX_TOTAL_BYTES:
            out["files"].append(_skipped(name, language, size, f"workspace over {MAX_TOTAL_BYTES} bytes"))
            out["truncated"] = True
            continue
        used += size
        part = scan(name, text, language)
        out["files"].append(part["file"])
        out["symbols"].extend(part["symbols"])
        out["refs"].extend(part["refs"])
        out["truncated"] = out["truncated"] or part["truncated"]
    out["counts"] = {
        "files": len(out["files"]),
        "indexed": sum(1 for f in out["files"] if f["indexed"]),
        "symbols": len(out["symbols"]),
        "refs": len(out["refs"]),
        "by_kind": _kind_totals(out["symbols"], out["refs"]),
    }
    return out


def _kind_totals(symbols: list[dict], refs: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for s in symbols:
        totals[f"symbol:{s['kind']}"] = totals.get(f"symbol:{s['kind']}", 0) + 1
    for r in refs:
        totals[f"ref:{r['kind']}"] = totals.get(f"ref:{r['kind']}", 0) + 1
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))


def declarations(index: dict, name: str) -> list[dict]:
    """Every place this symbol name is declared."""
    return [s for s in index["symbols"] if s["name"] == name]


def references(index: dict, name: str, *, in_file: str = "") -> list[dict]:
    """Every reference to this symbol name, optionally limited to one file."""
    return [r for r in index["refs"] if r["to"] == name and (not in_file or r["from"] == in_file)]


def files_of(index: dict) -> list[str]:
    return [f["name"] for f in index["files"]]


def snippet(text: str, line: int, *, width: int = 160) -> str:
    """The source line a symbol or reference sits on, clipped for display."""
    lines = text.splitlines()
    if not 1 <= line <= len(lines):
        return ""
    return lines[line - 1].strip()[:width]
