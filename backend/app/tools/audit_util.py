"""Shared plumbing for the crew's on-demand audits.

Everything here is deterministic: no LLM, no network, no browser. Scanners take the built page
(and, where relevant, the measurements the Critic already took in Chromium) and return findings,
so an audit costs no tokens and gives the same answer twice in a row.

Finding: {id, label, status: pass|warn|fail|info, severity: error|warning|info, detail, fix}
Report:  {kind, label, at, version, findings, errors, warnings, passed, checks, score, fixes, evidence}
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from app.utils.color import contrast_ratio

PASS, WARN, FAIL, INFO = "pass", "warn", "fail", "info"
ERROR, WARNING, INFO_SEVERITY = "error", "warning", "info"

# CSS custom properties in the built page's :root block - the palette the Designer chose.
_ROOT_RE = re.compile(r":root\s*\{(?P<body>[^}]*)\}")
_TOKEN_RE = re.compile(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8}|(?:rgba?|hsla?)\([^)]*\))", re.I)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def finding(id_: str, label: str, status: str, detail: str = "", fix: str = "", *,
            severity: str | None = None) -> dict:
    severity = severity or {FAIL: ERROR, WARN: WARNING, INFO: INFO_SEVERITY, PASS: INFO_SEVERITY}[status]
    return {"id": id_, "label": label, "status": status, "severity": severity,
            "detail": (detail or "")[:500], "fix": (fix or "")[:400]}


def ok(id_: str, label: str, detail: str = "") -> dict:
    return finding(id_, label, PASS, detail)


def counts(findings: list[dict]) -> dict:
    return {"errors": sum(1 for f in findings if f["status"] == FAIL),
            "warnings": sum(1 for f in findings if f["status"] == WARN),
            "passed": sum(1 for f in findings if f["status"] == PASS)}


def score_of(counts_: dict) -> int:
    """100 minus 12 per error and 4 per warning, floored at 0. Info findings never cost anything."""
    return max(0, 100 - 12 * counts_["errors"] - 4 * counts_["warnings"])


def report(kind: str, label: str, findings: list[dict], *, version: int, evidence: dict | None = None,
           agent: str = "engineer") -> dict:
    """`agent` is who can act on the findings. Empty means nobody in the crew can: the fixes stay
    written on each finding for the operator, but they are never routed into a page rebuild."""
    c = counts(findings)
    fixes = [{"finding": f["id"], "agent": agent, "instruction": f["fix"]} for f in findings
             if agent and f["status"] in (FAIL, WARN) and f["fix"]]
    return {"kind": kind, "label": label, "at": stamp(), "version": version, "findings": findings,
            **c, "checks": len(findings), "score": score_of(c), "fixes": fixes,
            "evidence": evidence or {},
            "headline": f"{c['errors']} error(s), {c['warnings']} warning(s) across {len(findings)} check(s)."}


def root_tokens(html: str) -> dict[str, str]:
    """--name -> value for every colour custom property inside the page's :root block(s)."""
    out: dict[str, str] = {}
    for m in _ROOT_RE.finditer(html or ""):
        for name, value in _TOKEN_RE.findall(m["body"]):
            out[f"--{name}"] = value.strip()
    return out


def hex_tokens(html: str) -> dict[str, str]:
    return {k: v for k, v in root_tokens(html).items() if re.fullmatch(r"#[0-9a-fA-F]{6}", v or "")}


AA_PAIRS = (("--text", "--bg", "body text on the page"), ("--text", "--surface", "body text on a card"),
            ("--muted", "--bg", "muted text on the page"), ("--muted", "--surface", "muted text on a card"),
            ("--on-primary", "--primary", "button label on the button"), ("--accent", "--surface", "accent on a card"))


def palette_contrast_failures(tokens: dict[str, str]) -> list[str]:
    """Same pairs the Designer's schema enforces, measured on the page that was actually built."""
    bad = []
    for fg, bg, what in AA_PAIRS:
        if tokens.get(fg) and tokens.get(bg):
            ratio = contrast_ratio(tokens[fg], tokens[bg])
            if ratio < 4.5:
                bad.append(f"{what}: {ratio:.2f}:1")
    return bad


def external_refs(html: str) -> list[str]:
    """References the browser could actually fetch: load-bearing attributes plus CSS url()/@import.

    Attribute-based on purpose - a schema.org URL inside JSON-LD or a domain named in the copy is
    text, not a request, and must not be reported as one.
    """
    page = soup(html)
    refs: list[str] = []
    for el in page.find_all(True):
        # An <a href> is a link a person clicks, not something the page loads: counting it as a
        # request would make every outbound link look like a third-party dependency.
        attrs = ("src", "action", "formaction", "data", "poster", "xlink:href", "srcset")
        if el.name not in ("a", "area"):
            attrs += ("href",)
        for attr in attrs:
            value = el.get(attr)
            value = " ".join(value) if isinstance(value, list) else str(value or "")
            if re.match(r"^\s*(https?:)?//", value, re.I):
                refs.append(value.strip())
    for m in re.finditer(r"""url\(\s*['"]?\s*((?:https?:)?//[^)]*)['"]?\s*\)""", html or "", re.I):
        refs.append(m.group(1).strip())
    for m in re.finditer(r"@import[^;]*;", html or "", re.I):
        refs.append(m.group(0)[:80])
    return sorted(set(refs))


def css_text(page_soup: BeautifulSoup) -> str:
    return "\n".join(st.get_text() for st in page_soup.find_all("style"))


def inline_scripts(page_soup: BeautifulSoup) -> list[str]:
    return [s.get_text() for s in page_soup.find_all("script") if (s.get("type") or "").lower() != "application/ld+json"]


def visible_text(page_soup: BeautifulSoup) -> str:
    """Text a visitor actually reads: non-destructive, so the same soup can keep being used."""
    parts = [str(t) for t in page_soup.find_all(string=True)
             if not t.find_parent(["script", "style", "noscript", "template"])]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def anchors(page_soup: BeautifulSoup) -> list[tuple[str, str]]:
    """(href, link text) for every anchor with an href."""
    return [(a["href"].strip(), a.get_text(" ", strip=True)) for a in page_soup.find_all("a", href=True)]


def ids_in(page_soup: BeautifulSoup) -> set[str]:
    return {el.get("id") for el in page_soup.find_all(id=True) if el.get("id")}


def heading_sequence(page_soup: BeautifulSoup) -> list[int]:
    return [int(t.name[1]) for t in page_soup.find_all(re.compile(r"^h[1-6]$"))]


def form_fields(page_soup: BeautifulSoup) -> list:
    return page_soup.find_all(["input", "select", "textarea"])


def labelled(el, page_soup: BeautifulSoup) -> bool:
    """Does this form control have a programmatic name a screen reader would announce?"""
    if el.get("type") in {"hidden", "submit", "button", "reset"}:
        return True
    if (el.get("aria-label") or "").strip():
        return True
    named = (el.get("aria-labelledby") or "").split()
    ids = ids_in(page_soup)
    if named and any(i in ids for i in named):
        return True
    el_id = el.get("id")
    if el_id and page_soup.find("label", attrs={"for": el_id}):
        return True
    if el.find_parent("label") is not None:
        return True
    return bool((el.get("title") or "").strip())


async def workspace_texts(ctx, *, skip: tuple[str, ...] = (), max_bytes: int = 200_000) -> dict[str, str]:
    """Contents of the run's workspace files, for the scanners that look past index.html.
    Best effort: an unreadable blob is skipped rather than failing the audit."""
    from app.orchestrator import artifacts   # local import: artifacts owns storage access

    out: dict[str, str] = {}
    for entry in ctx.state.files or []:
        name = entry.get("name") or ""
        if not name or name in skip:
            continue
        try:
            text = await artifacts.file_text(ctx, name)
        except Exception:  # noqa: BLE001 - a missing blob must not fail an audit
            continue
        if len(text) > max_bytes:
            text = text[:max_bytes]
        out[name] = text
    return out


def measured_check(check_results: list[dict], id_: str) -> dict | None:
    return next((c for c in check_results or [] if c.get("id") == id_), None)


def measured_findings(check_results: list[dict], mapping: tuple[tuple[str, str], ...]) -> list[dict]:
    """Carry the Critic's real Chromium measurements into an audit instead of re-estimating them.

    A check id can be measured at both viewports: the audit reports the worst of them.
    mapping: (check id, audit label)
    """
    out = []
    for id_, label in mapping:
        measured = [c for c in check_results or [] if c.get("id") == id_]
        if not measured:
            continue
        failed = [c for c in measured if not c.get("passed")]
        status = PASS if not failed else (FAIL if any(c.get("severity") == "error" for c in failed) else WARN)
        detail = "; ".join(f"{c.get('viewport', '')}: {(c.get('detail') or '')[:180]}".strip(": ") for c in failed) \
            or "measured in Chromium at 1280px and 375px"
        out.append(finding(id_, f"{label} (measured in a real browser)", status, detail[:500]))
    return out
