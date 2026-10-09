"""Accessibility audit: structural checks on the built document, plus the Critic's real Chromium
measurements for anything that only shows up when the page is rendered.

Colour contrast, tap-target size and mobile font size are read from the last browser pass instead
of being re-estimated here - two measurements of the same property would only disagree.
"""
from __future__ import annotations

import re

from app.tools import audit_util as au

INTERACTIVE = {"a", "button", "input", "select", "textarea", "summary", "details", "iframe"}
MEASURED = (("contrast", "Text contrast meets WCAG AA (4.5:1)"),
            ("tap_targets", "Tap targets are at least 44x44px"),
            ("font_size", "Body text stays readable on a phone"))

SKIP_LINK = '<a class="skip-link" href="#lc-main">Skip to content</a>'
SKIP_CSS = (":focus-visible{outline:3px solid var(--accent);outline-offset:2px}")


def _focusables(page) -> list:
    out = []
    for el in page.find_all(True):
        name = str(el.name or "")
        tabindex = (el.get("tabindex") or "").strip()
        focusable = name in INTERACTIVE and (name != "a" or el.get("href") is not None)
        if tabindex and tabindex != "-1":
            focusable = True
        if name == "div" and el.get("onclick"):
            focusable = True
        if focusable:
            out.append(el)
    return out


def _css(page) -> str:
    return au.css_text(page)


def scan(html: str, *, measured: list[dict] | None = None) -> list[dict]:
    page = au.soup(html)
    findings: list[dict] = []

    root = page.find("html")
    lang = (root.get("lang") or "").strip() if root else ""
    findings.append(au.ok("lang", "The document declares its language", f'lang="{lang}"')
                    if lang else
                    au.finding("lang", "The document declares its language", au.FAIL,
                               "<html> has no lang attribute, so screen readers guess the pronunciation.",
                               'Add lang="en" to the <html> element.'))

    if page.title and page.title.get_text(strip=True):
        findings.append(au.ok("doc_title", "The page has a title to announce"))
    else:
        findings.append(au.finding("doc_title", "The page has a title to announce", au.FAIL,
                                   "No <title>; a screen reader announces an untitled tab.",
                                   "Add a <title> naming the product."))

    h1s = page.find_all("h1")
    findings.append(au.ok("one_h1", "One H1 is the start of the reading order", f"{len(h1s)} found")
                    if len(h1s) == 1 else
                    au.finding("one_h1", "One H1 is the start of the reading order", au.FAIL,
                               f"{len(h1s)} <h1> elements; keyboard and screen-reader users navigate by heading.",
                               "Keep exactly one <h1> (the headline) and demote the others to <h2>."))

    seq = au.heading_sequence(page)
    skips = [f"h{seq[i - 1]} then h{seq[i]}" for i in range(1, len(seq)) if seq[i] - seq[i - 1] > 1]
    findings.append(au.ok("heading_order", "Heading levels nest correctly", f"{len(seq)} headings")
                    if not skips else
                    au.finding("heading_order", "Heading levels nest correctly", au.WARN,
                               "Skipped: " + ", ".join(skips[:4]),
                               "Re-level the headings so no level is skipped."))

    if page.find("main"):
        findings.append(au.ok("landmark_main", "A <main> landmark exists"))
    else:
        findings.append(au.finding("landmark_main", "A <main> landmark exists", au.FAIL,
                                   "Content is not inside a <main> element, so there is nothing to skip to.",
                                   'Wrap the page content in <main id="lc-main"> ... </main>.'))

    navs = page.find_all("nav")
    unnamed = [n for n in navs if not (n.get("aria-label") or n.get("aria-labelledby"))]
    findings.append(au.ok("nav_named", "Every navigation landmark is named", f"{len(navs)} nav element(s)")
                    if not navs or not unnamed else
                    au.finding("nav_named", "Every navigation landmark is named", au.WARN,
                               f"{len(unnamed)} <nav> without aria-label; several landmarks are announced as just "
                               "\"navigation\".",
                               'Add aria-label="Main" to the page\'s navigation landmark.'))

    fields = au.form_fields(page)
    unlabelled = [f for f in fields if not au.labelled(f, page)]
    if fields and unlabelled:
        what = ", ".join((f.get("id") or f.get("type") or f.name) + "" for f in unlabelled[:4])
        findings.append(au.finding("labels", "Every form field has a programmatic label", au.FAIL,
                                   f"{len(unlabelled)} of {len(fields)} field(s) rely on placeholder text only: {what}",
                                   "Give each field a real <label for=...> (visually hidden is fine), or aria-label."))
    else:
        findings.append(au.ok("labels", "Every form field has a programmatic label", f"{len(fields)} field(s)"))

    imgs = page.find_all("img")
    no_alt = [i for i in imgs if i.get("alt") is None]
    findings.append(au.ok("img_alt", "Images are alt-labelled or explicitly decorative", f"{len(no_alt)} missing")
                    if not no_alt else
                    au.finding("img_alt", "Images are alt-labelled or explicitly decorative", au.FAIL,
                               f"{len(no_alt)} of {len(imgs)} image(s) have no alt attribute at all.",
                               "Add alt text describing each content image, or alt=\"\" for decoration."))

    ids = [el.get("id") for el in page.find_all(id=True)]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    findings.append(au.ok("unique_ids", "No duplicate element ids", f"{len(ids)} ids")
                    if not dupes else
                    au.finding("unique_ids", "No duplicate element ids", au.FAIL,
                               "Duplicated: " + ", ".join(dupes[:5]),
                               "Give every id a unique value; labels and anchors resolve by id."))

    bad_refs = []
    for el in page.find_all(attrs={"aria-labelledby": True}) + page.find_all(attrs={"aria-describedby": True}):
        attr = el.get("aria-labelledby") or el.get("aria-describedby") or ""
        missing = [r for r in str(attr).split() if r not in set(ids)]
        if missing:
            bad_refs.append(f"{el.name}: " + ", ".join(missing))
    findings.append(au.ok("aria_refs", "aria-labelledby / describedby point at real ids", f"{len(bad_refs)} broken")
                    if not bad_refs else
                    au.finding("aria_refs", "aria-labelledby / describedby point at real ids", au.FAIL,
                               "; ".join(bad_refs[:3]),
                               "Fix or remove the references to missing ids."))

    positive = [el.name for el in page.find_all(attrs={"tabindex": re.compile(r"^[1-9]")})]
    findings.append(au.ok("tabindex", "No positive tabindex", f"{len(positive)} found")
                    if not positive else
                    au.finding("tabindex", "No positive tabindex", au.FAIL,
                               "Elements forced early in the tab order: " + ", ".join(positive[:5]),
                               "Remove positive tabindex values and let source order drive the tab sequence."))

    hidden_focusable = [el.name for el in page.find_all(attrs={"aria-hidden": "true"})
                        if el.name in INTERACTIVE or (el.get("tabindex") or "") != ""]
    findings.append(au.ok("aria_hidden", "Nothing focusable is aria-hidden", f"{len(hidden_focusable)} found")
                    if not hidden_focusable else
                    au.finding("aria_hidden", "Nothing focusable is aria-hidden", au.FAIL,
                               "Focusable but invisible to a screen reader: " + ", ".join(hidden_focusable[:4]),
                               "Either remove these from the tab order or un-hide them."))

    clickables = [el.name for el in page.find_all(True)
                  if el.get("onclick") and el.name not in INTERACTIVE
                  and not (el.get("role") or el.get("tabindex"))]
    findings.append(au.ok("keyboard_click", "Clickable elements are real controls", f"{len(clickables)} found")
                    if not clickables else
                    au.finding("keyboard_click", "Clickable elements are real controls", au.FAIL,
                               "Mouse-only: " + ", ".join(clickables[:4]) + " with onclick but no role or tabindex",
                               "Replace these with <button> elements so they are reachable by keyboard."))

    viewport = page.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
    content = (viewport.get("content") or "") if viewport else ""
    blocked = re.search(r"user-scalable\s*=\s*no|maximum-scale\s*=\s*[12](?:\.\d)?\b", content, re.I)
    findings.append(au.ok("zoom", "People can zoom the page", content[:60])
                    if content and not blocked else
                    au.finding("zoom", "People can zoom the page", au.FAIL,
                               "viewport blocks or caps pinch zoom." if blocked else "No viewport meta tag.",
                               'Add in <head>: <meta name="viewport" content="width=device-width, initial-scale=1">'))

    css = _css(page)
    focus_ring = re.search(r":focus(?:-visible)?\s*(?:,[^{}]*)?\{[^}]*\b(outline|box-shadow)\b", css, re.I)
    findings.append(au.ok("focus_visible", "Keyboard focus is visible", "a :focus style sets outline/box-shadow")
                    if focus_ring else
                    au.finding("focus_visible", "Keyboard focus is visible", au.FAIL,
                               "No :focus style in the CSS, so keyboard users cannot see where they are.",
                               f"Add a visible keyboard focus style: {SKIP_CSS}"))

    animated = bool(re.search(r"@keyframes|animation\s*:|transition\s*:", css, re.I))
    findings.append(au.ok("reduced_motion", "Motion honours prefers-reduced-motion",
                          "no time-based animation to guard")
                    if not animated or "prefers-reduced-motion" in css else
                    au.finding("reduced_motion", "Motion honours prefers-reduced-motion", au.FAIL,
                               "The page animates but has no reduced-motion guard.",
                               "Add a CSS block under @media (prefers-reduced-motion: reduce) that turns animations "
                               "and smooth scrolling off."))

    if page.find(attrs={"role": "status"}) or page.find(attrs={"aria-live": True}):
        findings.append(au.ok("live_region", "Dynamic messages are announced"))
    else:
        scripts = au.inline_scripts(page)
        writes = [s for s in scripts if re.search(r"\.textContent|\.innerText|\.innerHTML", s)]
        findings.append(au.ok("live_region", "Dynamic messages are announced", "the page writes no dynamic text")
                        if not writes else
                        au.finding("live_region", "Dynamic messages are announced", au.WARN,
                                   "Script changes text content, but no role=status / aria-live region exists, so "
                                   "screen readers never announce the result.",
                                   'Add role="status" to the element the script writes into.'))

    first_link = next((a for a in page.find_all("a", href=True)), None)
    has_skip = bool(first_link and re.search(r"skip", first_link.get_text(" ", strip=True), re.I))
    findings.append(au.ok("skip_link", "Keyboard users can skip the navigation", "first link is a skip link")
                    if has_skip or not navs else
                    au.finding("skip_link", "Keyboard users can skip the navigation", au.WARN,
                               "The tab order starts inside the navigation, so keyboard users repeat it on every "
                               "section change.",
                               f"Insert immediately after the opening <body> tag: {SKIP_LINK}"))

    findings.extend(au.measured_findings(measured or [], MEASURED))
    return findings
