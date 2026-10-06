"""HTML sanitizer for generated pages.

Policy: one self-contained file. Inline CSS/JS are allowed; anything that loads or sends data
off-page is removed. A restrictive CSP <meta> is injected as defence in depth.
Returns (clean_html, violations) so the UI can show what was stripped.
"""
import re

from bs4 import BeautifulSoup, Comment

CSP = ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
       "font-src data:; form-action 'none'; base-uri 'none'")

# Patterns that make an inline script a network/tracking/exfiltration risk -> script removed.
# NOTE: deliberately case-sensitive. With re.I, "Function(" also matched ordinary `function(` callbacks
# and silently removed every legitimate inline script.
BANNED_JS = re.compile(
    r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|importScripts|eval)\s*\(|"
    r"\bnew\s+Function\s*\(|document\.cookie|\blocalStorage\b|\bsessionStorage\b|window\.open|\bimport\s*\(|"
    r"\.src\s*=\s*['\"]https?:"
)  # case-sensitive on purpose: JS is, and `function(){}` must stay legal
REMOTE = re.compile(r"^\s*(https?:)?//", re.I)
CSS_REMOTE_URL = re.compile(r"url\(\s*['\"]?\s*(https?:)?//[^)]*\)", re.I)
CSS_IMPORT = re.compile(r"@import[^;]*;?", re.I)
REMOVE_TAGS = ["iframe", "object", "embed", "base", "applet", "frame", "frameset", "portal"]


def _clean_css(css: str, violations: list[str]) -> str:
    new = CSS_IMPORT.sub("", css)
    new = CSS_REMOTE_URL.sub("none", new)
    if new != css:
        violations.append("Removed remote CSS (@import / remote url())")
    return new


def sanitize_html(raw: str) -> tuple[str, list[str]]:
    violations: list[str] = []
    soup = BeautifulSoup(raw, "html.parser")

    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()

    for tag in soup.find_all(REMOVE_TAGS):
        violations.append(f"Removed <{tag.name}>")
        tag.decompose()

    for s in soup.find_all("script"):
        if s.get("src"):
            violations.append(f"Removed external script: {s.get('src')[:80]}")
            s.decompose()
        elif BANNED_JS.search(s.string or s.get_text() or ""):
            violations.append("Removed inline script with network/storage access")
            s.decompose()

    for link in soup.find_all("link"):
        violations.append(f"Removed <link rel={link.get('rel')}> (external resources not allowed)")
        link.decompose()

    for m in soup.find_all("meta"):
        if (m.get("http-equiv") or "").lower() in {"refresh", "content-security-policy"}:
            m.decompose()

    for st in soup.find_all("style"):
        if st.string is not None or st.get_text():
            st.string = _clean_css(st.get_text(), violations)

    for img in soup.find_all(["img", "source", "video", "audio", "track", "input"]):
        src = img.get("src")
        if src and (REMOTE.match(src) or src.lower().startswith(("javascript:", "http:", "https:"))):
            violations.append(f"Removed remote <{img.name}> src")
            if img.name == "input":
                del img["src"]
            else:
                img.decompose()
    for img in soup.find_all("img"):
        if img.get("srcset"):
            del img["srcset"]

    for form in soup.find_all("form"):
        action = (form.get("action") or "").strip()
        if action not in ("", "#"):
            violations.append(f"Neutralised form action: {action[:80]}")
        form["action"] = "#"
        form["method"] = "get"
        form["onsubmit"] = "return false"

    for el in soup.find_all(True):
        for attr in list(el.attrs):
            val = el.attrs[attr]
            val = " ".join(val) if isinstance(val, list) else str(val)
            if attr.lower().startswith("on") and attr.lower() != "onsubmit" and BANNED_JS.search(val):
                violations.append(f"Removed risky {attr} handler")
                del el.attrs[attr]
            elif attr.lower() in {"href", "src", "action", "formaction", "xlink:href"} and val.strip().lower().startswith(("javascript:", "data:text/html")):
                violations.append(f"Removed {attr}={val[:30]}")
                del el.attrs[attr]
            elif attr.lower() == "style":
                cleaned = _clean_css(val, violations)
                el.attrs[attr] = cleaned

    head = soup.find("head")
    if head is None:
        html_tag = soup.find("html")
        if html_tag is not None:
            head = soup.new_tag("head")
            html_tag.insert(0, head)
    if head is not None:
        meta = soup.new_tag("meta")
        meta["http-equiv"] = "Content-Security-Policy"
        meta["content"] = CSP
        head.insert(0, meta)

    return str(soup), violations
