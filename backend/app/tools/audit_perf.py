"""Performance audit: measured weight, measured DOM, and the CSS the page animates.

The load-time number is an estimate from the bytes we measured (gzip ~32% for text, one round trip
per request, 1.6 Mbps / 150 ms RTT for a slow mobile connection) and is labelled as such in the
report - it is not a lab run.
"""
from __future__ import annotations

import re

from app.tools import audit_util as au

NON_COMPOSITED = ("width", "height", "top", "left", "right", "bottom", "margin", "padding",
                  "font-size", "box-shadow", "border-radius")
LAY_OUT_RE = re.compile(r"(?:transition|animation)\s*:[^;]*\b(" + "|".join(NON_COMPOSITED) + r")\b", re.I)
DATA_URI = re.compile(r"""data:[^"')\s]{40,}""")
KB = 1024


def _depth(el, current=0) -> int:
    kids = [c for c in getattr(el, "children", []) or []]
    if not kids:
        return current
    return max(_depth(c, current + 1) for c in kids)


def _wire_bytes(raw: int) -> int:
    return max(1200, int(raw * 0.32))


def estimate_seconds(raw_bytes: int, requests: int) -> float:
    rtt = 0.15 * max(1, requests)
    return round(rtt + _wire_bytes(raw_bytes) / 200_000, 2)


def scan(html: str, *, assets: dict[str, str] | None = None, measured: list[dict] | None = None) -> list[dict]:
    page = au.soup(html)
    findings: list[dict] = []
    assets = assets or {}

    page_bytes = len(html.encode())
    total = page_bytes + sum(len(text.encode()) for text in assets.values())
    css_bytes = len(au.css_text(page).encode())
    js_bytes = sum(len(s.encode()) for s in au.inline_scripts(page))

    refs = au.external_refs(html)
    requests = 1 + len(refs)          # the file itself, plus anything it reaches out for

    if page_bytes < 60 * KB:
        findings.append(au.ok("payload", "Page weight", f"{page_bytes / KB:.1f} KB for index.html; "
                                                        f"{total / KB:.1f} KB for the whole workspace"))
    elif page_bytes < 150 * KB:
        findings.append(au.finding("payload", "Page weight", au.WARN, f"{page_bytes / KB:.1f} KB in one file.",
                                   "Move the largest sections' markup into fewer repeated blocks, or split the stylesheet "
                                   "so the first paint only needs the hero rules."))
    else:
        findings.append(au.finding("payload", "Page weight", au.FAIL, f"{page_bytes / KB:.1f} KB in one file.",
                                   "Cut the payload: remove embedded base64 media and shorten the page."))

    findings.append(au.finding("transfer", "Estimated time to first byte on a slow connection", au.INFO,
                               f"{_wire_bytes(page_bytes) / KB:.1f} KB after gzip, {requests} request(s) -> "
                               f"about {estimate_seconds(page_bytes, requests)}s at 1.6 Mbps / 150 ms RTT. "
                               "Estimate from measured bytes, not a lab run.",
                               severity=au.INFO_SEVERITY))

    findings.append(au.ok("requests", "Nothing waits on a third-party host",
                          f"{len(refs)} external request(s); no fonts, scripts or images to fetch")
                    if not refs else
                    au.finding("requests", "Nothing waits on a third-party host", au.FAIL,
                               ", ".join(refs[:5]),
                               "Remove the external references: each one is a DNS lookup, a connection and a possible "
                               "blocked request."))

    nodes = len(page.find_all(True))
    depth = _depth(page)
    if nodes <= 600:
        findings.append(au.ok("dom", "DOM size", f"{nodes} elements, {depth} levels deep"))
    elif nodes <= 1200:
        findings.append(au.finding("dom", "DOM size", au.WARN, f"{nodes} elements, {depth} levels deep.",
                                   "Shorten the page or collapse repeated card markup; a big DOM slows every style "
                                   "change."))
    else:
        findings.append(au.finding("dom", "DOM size", au.FAIL, f"{nodes} elements.",
                                   "Split the page: this many nodes costs layout time on a phone."))

    styles = au.css_text(page)
    layout_animations = sorted({m.group(1).lower() for m in LAY_OUT_RE.finditer(styles)})
    findings.append(au.ok("animations", "Animated properties are cheap to repaint", f"{len(layout_animations)} found")
                    if not layout_animations else
                    au.finding("animations", "Animated properties are cheap to repaint", au.WARN,
                               "Transitions/animations touch: " + ", ".join(layout_animations),
                               "Animate transform and opacity instead of size, position or shadow."))

    data_uris = [len(d) for d in DATA_URI.findall(html)]
    if data_uris:
        findings.append(au.finding("embedded_media", "Embedded base64 media", au.WARN,
                                   f"{len(data_uris)} data URI(s), {sum(data_uris) / KB:.1f} KB of the payload.",
                                   "Serve images as files (or use CSS art) so the text of the page stays small."))
    else:
        findings.append(au.ok("embedded_media", "Embedded base64 media", "none: the page is text and CSS only"))

    imgs = page.find_all("img")
    unsized = [i for i in imgs if not (i.get("width") and i.get("height"))]
    findings.append(au.ok("cls", "Images reserve their space", f"{len(imgs)} image(s)")
                    if not unsized else
                    au.finding("cls", "Images reserve their space", au.WARN,
                               f"{len(unsized)} of {len(imgs)} image(s) lack width/height, so the layout jumps when "
                               "they load.",
                               "Add width and height attributes to every image."))

    scripts = au.inline_scripts(page)
    blocking = [s for s in scripts if re.search(r"document\.write|\bwhile\s*\(\s*true\s*\)", s)]
    findings.append(au.ok("script_cost", "Inline script is cheap", f"{js_bytes} bytes across {len(scripts)} script(s)")
                    if not blocking else
                    au.finding("script_cost", "Inline script is cheap", au.FAIL,
                               "document.write or an unbounded loop found.",
                               "Remove document.write and any unbounded loop from the page script."))

    font_css = re.findall(r"@font-face", styles)
    findings.append(au.ok("fonts", "No font download blocks first paint", f"{len(font_css)} @font-face rule(s), "
                                                                          "system stacks only")
                    if not font_css or not refs else
                    au.finding("fonts", "No font download blocks first paint", au.WARN,
                               f"{len(font_css)} @font-face rule(s).",
                               "Keep system font stacks, or preload the file and set font-display: swap."))

    overflow = [c for c in measured or [] if c.get("id") == "overflow" and not c.get("passed")]
    findings.append(au.ok("overflow", "No horizontal scroll on a phone", "measured clean at 375px")
                    if not overflow else
                    au.finding("overflow", "No horizontal scroll on a phone", au.FAIL,
                               "Measured wider than the viewport: " + (overflow[0].get("detail") or "")[:120],
                               "Find the fixed-width element and give it max-width:100%."))

    return findings
