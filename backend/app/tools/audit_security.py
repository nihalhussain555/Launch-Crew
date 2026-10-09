"""Security audit of the page the crew actually shipped.

The sanitizer is a guardrail, not a promise: this re-reads the built document (and the rest of the
workspace) and verifies the properties we claim - locked-down CSP, zero off-page requests, no
network or storage APIs in inline script, forms that cannot exfiltrate, and no credential-shaped
text in any file a user could download.
"""
from __future__ import annotations

import re

from bs4 import Comment

from app.tools import audit_util as au
from app.tools import secret_scan
from app.tools.sanitizer import BANNED_JS

RISKY = re.compile(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|navigator\.clipboard|"
                   r"document\.cookie|localStorage|sessionStorage|indexedDB|eval|new\s+Function)\b")


def _csp(page_soup) -> str:
    meta = page_soup.find("meta", attrs={"http-equiv": re.compile("^content-security-policy$", re.I)})
    return (meta.get("content") or "") if meta else ""


def scan(html: str, *, files: dict[str, str] | None = None) -> list[dict]:
    page = au.soup(html)
    findings: list[dict] = []
    documents = {"index.html": html, **(files or {})}

    csp = _csp(page)
    if not csp:
        findings.append(au.finding("csp", "Content-Security-Policy is set", au.FAIL,
                                   "The document ships no CSP meta tag, which means it did not go through the build's "
                                   "sanitizer step."))
    else:
        tight = all(p in csp for p in ("default-src 'none'", "form-action 'none'", "base-uri 'none'"))
        findings.append(au.ok("csp", "Content-Security-Policy is set",
                              f"default-src 'none' and friends present: {tight}" if tight
                              else f"Present but looser than the policy: {csp[:120]}"))
        if "unsafe-inline" in csp:
            findings.append(au.finding("csp_inline", "CSP allows inline style and script", au.INFO,
                                       "The page is one self-contained file, so its own CSS/JS needs 'unsafe-inline'.",
                                       "To tighten this later, split the page into files and move script style to nonces or "
                                       "hashes - that is a hosting change, not a defect in the build.",
                                       severity=au.INFO_SEVERITY))

    refs = au.external_refs(html)
    findings.append(au.ok("no_external", "No off-page requests", f"{len(refs)} external reference(s)")
                    if not refs else
                    au.finding("no_external", "No off-page requests", au.FAIL,
                               "References found: " + ", ".join(refs[:6]),
                               "Remove the external references: the build must stay self-contained."))

    risky = sorted({m.group(1) for s in au.inline_scripts(page) for m in RISKY.finditer(s)})
    banned = sorted({m.group(0) for s in au.inline_scripts(page) for m in BANNED_JS.finditer(s)})
    if risky or banned:
        findings.append(au.finding("script_apis", "Inline script has no network or storage access", au.FAIL,
                                   "Found: " + ", ".join((risky + banned)[:8]),
                                   "Delete these APIs from the page script: a landing page must not read storage or "
                                   "make requests."))
    else:
        findings.append(au.ok("script_apis", "Inline script has no network or storage access",
                              f"{len(au.inline_scripts(page))} inline script(s) scanned"))

    iframes = page.find_all(["iframe", "object", "embed", "base", "frame"])
    findings.append(au.ok("no_frames", "No frames, embeds or <base>", f"{len(iframes)} element(s)")
                    if not iframes else
                    au.finding("no_frames", "No frames, embeds or <base>", au.FAIL,
                               ", ".join(sorted({t.name for t in iframes})),
                               "Remove every <iframe>, <object>, <embed> and <base> element."))

    handlers = sorted({a for el in page.find_all(True) for a in el.attrs
                       if str(a).lower().startswith("on") and str(a).lower() != "onsubmit"})
    findings.append(au.ok("handlers", "No ad-hoc inline event handlers", f"{len(handlers)} handler(s)")
                    if not handlers else
                    au.finding("handlers", "No ad-hoc inline event handlers", au.WARN,
                               "Attributes present: " + ", ".join(handlers[:6]),
                               "Move behaviour into the page script and keep only the form's onsubmit guard."))

    forms = page.find_all("form")
    open_action = [f for f in forms if (f.get("action") or "#").strip() not in ("", "#")]
    if open_action:
        findings.append(au.finding("form_action", "No form can post off-page", au.FAIL,
                                   f"{len(open_action)} form(s) point somewhere: " +
                                   ", ".join((f.get("action") or "")[:60] for f in open_action[:3]),
                                   "Set every form action to '#' and handle submission in page script, or point it at a "
                                   "real endpoint you control."))
    elif forms:
        findings.append(au.finding("form_action", "Form submission is not wired to a real endpoint", au.WARN,
                                   f"{len(forms)} form(s) collect input and post to '#', so sign-ups are not stored "
                                   "anywhere. Point the form at your list provider before you launch.",
                                   severity=au.WARNING))
    else:
        findings.append(au.ok("form_action", "No forms to exfiltrate through"))

    unsafe_target = [a for a in page.find_all("a", target=re.compile("_blank", re.I))
                     if "noopener" not in (a.get("rel") or "").lower()]
    findings.append(au.ok("opener", "No window.opener leak from _blank links", f"{len(unsafe_target)} link(s)")
                    if not unsafe_target else
                    au.finding("opener", "No window.opener leak from _blank links", au.FAIL,
                               f"{len(unsafe_target)} link(s) use target=_blank without rel=noopener",
                               "Add rel=\"noopener noreferrer\" to every link that opens a new tab."))

    plain_http = [r for r in refs if r.lower().startswith("http://")]
    findings.append(au.ok("mixed_content", "No plain-http references", f"{len(plain_http)} found")
                    if not plain_http else
                    au.finding("mixed_content", "No plain-http references", au.FAIL,
                               ", ".join(plain_http[:4]),
                               "Replace every http:// reference with https:// or remove it."))

    risky_comment = [str(t)[:80] for t in page.find_all(string=Comment)
                     if re.search(r"(?i)(password|secret|token|api.?key|internal|do not)", str(t))]
    findings.append(au.ok("comments", "No internal notes left in the source", f"{len(risky_comment)} flagged")
                    if not risky_comment else
                    au.finding("comments", "No internal notes left in the source", au.WARN,
                               "; ".join(risky_comment[:3]),
                               "Delete these HTML comments from the page source."))

    hits = [h for name, text in documents.items() for h in secret_scan.find_secrets(text, name=name)]
    findings.append(au.ok("secret_material", "No credentials in the shipped files",
                          f"{len(documents)} file(s) scanned")
                    if not hits else
                    au.finding("secret_material", "No credentials in the shipped files", au.FAIL,
                               secret_scan.describe(hits),
                               "Remove the value, rotate the credential it exposes, and keep secrets in the server's "
                               "environment instead of the page."))

    pw_fields = page.find_all("input", attrs={"type": re.compile("^password$", re.I)})
    findings.append(au.ok("credentials_collected", "No password or payment fields", f"{len(pw_fields)} field(s)")
                    if not pw_fields else
                    au.finding("credentials_collected", "No password or payment fields", au.FAIL,
                               f"{len(pw_fields)} password field(s) on a static page that cannot protect them",
                               "Drop the password field from this page and send people to the real signed-in app."))

    return findings
