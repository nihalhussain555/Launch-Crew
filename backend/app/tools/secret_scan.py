"""Detect credential-shaped strings so they can be reported, never echoed.

Used by the Security audit (is a secret sitting in a generated file?) and by the environment
manager. Findings carry the pattern name and the line number only: no value, no prefix, no length
bucket, because a report that quotes a secret has itself leaked it.
"""
from __future__ import annotations

import re

PATTERNS: tuple[tuple[str, str, re.Pattern], ...] = (
    ("private_key", "PEM private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", "AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("groq_api_key", "Groq API key (gsk_...)", re.compile(r"\bgsk_[A-Za-z0-9_\-]{20,}")),
    ("openai_style_key", "sk- style API key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("netlify_token", "Netlify access token", re.compile(r"\bnfp_[A-Za-z0-9]{20,}")),
    ("github_token", "GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack_token", "Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", "Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("bearer_jwt", "JSON web token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}")),
    ("assignment", "secret-looking assignment",
     re.compile(r"""(?ix)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key)\b\s*[:=]\s*["']?([A-Za-z0-9+/_.=\-]{12,})""")),
)

# Values that are obviously placeholders: reporting them would be noise, not a finding.
_PLACEHOLDER = re.compile(
    r"""(?i)^(change-?me.*|your[-_].*|<.*>|\$\{.*\}|\{\{.*\}\}|x{6,}|\*{4,}|example.*|todo.*|none|null|placeholder)$"""
)


def find_secrets(text: str, *, name: str = "") -> list[dict]:
    """[{"id","label","file","line"}] - line numbers are 1-based, the value is never returned."""
    hits: list[dict] = []
    if not text:
        return hits
    for pattern_id, label, rx in PATTERNS:
        for m in rx.finditer(text):
            value = m.group(1) if m.lastindex else m.group(0)
            if _PLACEHOLDER.match(value or ""):
                continue
            hits.append({"id": pattern_id, "label": label, "file": name or "page",
                         "line": text.count("\n", 0, m.start()) + 1})
    return hits


def describe(hits: list[dict]) -> str:
    """A safe summary for a finding's detail line."""
    return "; ".join(sorted({f"{h['label']} in {h['file']} line {h['line']}" for h in hits})[:6])
