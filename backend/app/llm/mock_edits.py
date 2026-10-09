"""Instruction-driven edits for the offline provider (MOCK_LLM=true).

A real model rewrites the JSON or markup it is handed; the mock has no language model, so it
recognises the asks the revise / chat endpoints actually receive - quoted text swaps, tone words,
"warmer colours", "bigger button", "more spacing", an explicit size - and applies them
mechanically. An instruction nothing matches leaves the artefact untouched rather than inventing
a change; set MOCK_LLM=false with Groq keys for real rewrites.

Page edits go into a marked override block at the end of the page's <style>, because every build
is re-composed from copy + design and a rebuild would otherwise drop them. The block is read back
out of CURRENT_HTML, so earlier page edits survive later revisions.
"""
from __future__ import annotations

import json
import re
from colorsys import hls_to_rgb, rgb_to_hls

from app.agents.variants import SYSTEM_BODY
from app.utils.color import contrast_ratio, hex_to_rgb, mix, relative_luminance

AA = 4.5
# Between these two relative luminances neither near-white nor near-black text reaches 4.5:1 against a
# background, so a palette whose pages land inside the band is moved out before its text is chosen.
DARK_MAX, LIGHT_MIN = 0.16, 0.22
_OVERRIDES = re.compile(r"/\*launch-overrides\*/(.*?)/\*end-launch-overrides\*/", re.S)
_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}")
_FIXES = re.compile(r"FIXES \(apply all[;,][^)]*\):\n(.*?)(?=\n(?:CURRENT_JSON|CURRENT_HTML|DESIGN_DIRECTION)[: ]|\Z)",
                    re.S)
_CURRENT_JSON = re.compile(r"CURRENT_JSON: (\{[^\n]*)")
_CURRENT_HTML = re.compile(r"\nCURRENT_HTML:\n(.*)", re.S)
_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_CLAUSE = re.compile(r"[,;]|\band\b|\bwith\b|\balso\b", re.I)
_SAFE_CSS_VALUE = re.compile(r"^[A-Za-z0-9#%(),.\-/' ]{1,140}$")
_SAFE_SELECTOR = re.compile(r"^[A-Za-z0-9 ,.\-:>#*_]{1,80}$")
_SAFE_FONT = re.compile(r"^[A-Za-z0-9 ,'\"\-]+$")
_QUOTED = re.compile(r"\"([^\"]{2,160})\"|'([^']{2,160})'|“([^”]{2,160})”")
_TOPIC = re.compile(r"\b(?:about|for|mention|focus on|should say|regarding)\s+(.{3,80})", re.I)
_OBJECT_RE = re.compile(r"\b(?:add|include|insert|put in|remove|delete|drop|hide|cut)\s+"
                        r"(?:an|a|the|our|some)?\s*(.{3,60}?)(?:[.!?]|$)", re.I)
_SIZE = re.compile(r"(\d{1,4})\s*(px|rem|em|%)")


def _has(low: str, *needles: str) -> bool:
    """Word-prefix match, so "add" finds "add a FAQ" but not "address", and "center" finds "centred"."""
    return any(re.search(rf"\b{re.escape(needle)}", low) for needle in needles)


# ----------------------------------------------------------------- prompt parsing
def fixes_from(blob: str) -> list[str]:
    m = _FIXES.search(blob)
    return [line[2:] for line in m.group(1).splitlines() if line.startswith("- ")][:8] if m else []


def current_json(blob: str) -> dict | None:
    m = _CURRENT_JSON.search(blob)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def current_html(blob: str) -> str:
    m = _CURRENT_HTML.search(blob)
    return m.group(1) if m else ""


# ----------------------------------------------------------------- copywriter
_FRIENDLY = [(" we will ", " we'll "), (" do not ", " don't "), (" you will ", " you'll "), (" cannot ", " can't "),
             (" it is ", " it's "), (" that is ", " that's "), (" we are ", " we're "), (" you are ", " you're "),
             (" there is ", " there's "), (" will not ", " won't "), (" is not ", " isn't ")]
_FORMAL = [(b, a) for a, b in _FRIENDLY]
_PLAIN = [("seamless", "easy"), ("streamlined", "simple"), ("leverage", "use"), ("utilize", "use"),
          ("robust", "solid"), ("intuitive", "easy"), ("comprehensive", "complete"), ("holistic", "whole"),
          ("scalable", "grows with you"), ("paradigm", "model"), ("synergy", "teamwork"), ("optimize", "improve"),
          ("facilitate", "help"), ("endeavor", "try"), ("commence", "start"), ("regarding", "about"),
          ("purchase", "buy"), ("assist", "help"), ("prioritize", "put first")]
_TONES = (
    (_FRIENDLY, "Finally, ", ("friendlier", "friendly", "warmer", "casual", "approachable", "human",
                              "conversational", "relaxed", "softer")),
    (_FORMAL, "Introducing ", ("formal", "professional", "business-like", "corporate", "serious", "polished")),
)
_FIELDS = (
    ("subheadline", ("subheadline", "subhead", "subtitle", "tagline", "supporting", "second line")),
    ("cta", ("button", "cta", "call to action", "sign-up", "signup")),
    ("headline", ("headline", "heading", "h1", "main title", "title")),
    ("product_name", ("product name", "brand", "app name", "name")),
    ("features", ("feature", "benefit", "card")),
    ("faq", ("faq", "question")),
)
_LIMITS = {"product_name": 40, "headline": 120, "subheadline": 260}


def _clip(value: str, limit: int) -> str:
    return str(value).strip()[:limit].rstrip()


def _field_of(low: str) -> str:
    for name, keys in _FIELDS:
        if _has(low, *keys):
            return name
    return ""


def _quoted(fix: str) -> list[str]:
    return [g for m in _QUOTED.finditer(fix) for g in m.groups() if g]


def _strings(doc: dict):
    """Every text slot of a CopyDoc, so a word-level edit reaches all of the page's copy."""
    for key in ("product_name", "headline", "subheadline"):
        yield doc, key
    yield doc["cta"], "label"
    yield doc["cta"], "supporting_text"
    for item in doc.get("features", []):
        yield item, "title"
        yield item, "description"
    for item in doc.get("faq", []):
        yield item, "question"
        yield item, "answer"


def _replace_every(doc: dict, old: str, new: str) -> bool:
    if not old:
        return False
    pattern, hit = re.compile(re.escape(old), re.I), False
    for holder, key in _strings(doc):
        value = str(holder.get(key) or "")
        if pattern.search(value):
            holder[key] = pattern.sub(lambda m: new, value)
            hit = True
    return hit


def _swap_words(doc: dict, table: list[tuple[str, str]]) -> None:
    for holder, key in _strings(doc):
        value = str(holder.get(key) or "")
        for old, new in table:
            value = re.sub(rf"\b{re.escape(old.strip())}\b", new.strip(), value, flags=re.I)
        holder[key] = value


def _set_field(doc: dict, field: str, value: str) -> None:
    value = str(value).strip()
    if not value:
        return
    if field in _LIMITS:
        doc[field] = _clip(value, _LIMITS[field])
    elif field == "cta":
        doc["cta"]["label"] = _clip(value, 50)
    elif field == "features" and doc.get("features"):
        doc["features"][0]["title"] = _clip(value, 80)
    elif field == "faq" and doc.get("faq"):
        doc["faq"][0]["question"] = _clip(value, 120)


def _shorten(doc: dict) -> None:
    for key, limit in (("headline", 60), ("subheadline", 140)):
        value = str(doc.get(key) or "")
        head = re.split(r"[,:;]| - | — | – ", value, 1)[0].strip()
        doc[key] = _clip(head or value, limit)
    doc["cta"]["label"] = _clip(" ".join(str(doc["cta"].get("label")).split()[:3]), 50)


def _append_item(doc: dict, field: str, topic: str) -> None:
    name = str(doc.get("product_name") or "this product")
    topic = _clip(topic or "", 80)
    if not topic:
        return
    if field == "features" and len(doc.get("features", [])) < 6:
        doc["features"].append({"title": topic,
                                "description": _clip(f"How {name} handles {topic.lower()} - simple to start, "
                                                     f"and we will show you the moment you join.", 300)})
    elif field == "faq" and len(doc.get("faq", [])) < 6:
        question = topic if topic.endswith("?") else topic + "?"
        doc["faq"].append({"question": _clip(question, 120),
                           "answer": "We keep this deliberately simple - join the list and we confirm the "
                                     "details before launch."})


def _drop(doc: dict, field: str, needle: str) -> None:
    items = doc.get(field, [])
    if len(items) <= 3:
        return                                    # CopyDoc needs at least three features and three FAQs
    needle = (needle or "").strip().lower()
    if not needle:
        return
    idx = next((i for i, item in enumerate(items)
                if needle in " ".join(str(v) for v in item.values()).lower()
                or any(word in " ".join(str(v) for v in item.values()).lower() for word in needle.split())), None)
    if idx is not None:
        items.pop(idx)


def _object(fix: str) -> str:
    """The thing an "add / remove ..." request is about: "add a pricing table" -> "pricing table"."""
    m = _OBJECT_RE.search(fix.strip())
    return _clip(m.group(1) if m else "", 60)


def _swap_order(fix: str) -> tuple[str, str]:
    """'Change A to B' and 'B instead of A': the phrase between the quotes decides which is the old text."""
    matches = list(_QUOTED.finditer(fix))[:2]
    if len(matches) < 2:
        return "", ""
    a, b = matches[0].group(0), matches[1].group(0)
    low = fix.lower()
    pivots = [low.find(p) for p in ("instead of", "rather than", "in place of")]
    pivots = [p for p in pivots if p != -1]
    first_at = low.find(a.lower())
    if pivots and first_at < min(pivots):
        return b.strip("\"'“”"), a.strip("\"'“”")
    return a.strip("\"'“”"), b.strip("\"'“”")


def apply_copy(current: dict, fixes: list[str]) -> dict:
    doc = json.loads(json.dumps(current))         # deep copy: the run's stored document stays untouched
    for fix in fixes:
        _copy_edit(doc, fix)
    return doc


def _copy_edit(doc: dict, fix: str) -> None:
    low = fix.lower()
    field = _field_of(low)
    quotes = _quoted(fix)
    adding = _has(low, "add", "include", "insert", "put in")
    removing = _has(low, "remove", "delete", "drop", "cut", "take out", "hide")

    if len(quotes) >= 2:
        old, new = _swap_order(fix)
        if not _replace_every(doc, old, new) and field:
            _set_field(doc, field, new)      # no named field and nothing to replace: leave the copy alone
        return
    if len(quotes) == 1:
        text = quotes[0]
        if removing and field in ("features", "faq"):
            _drop(doc, field, text)
        elif adding and field in ("features", "faq"):
            _append_item(doc, field, text)
        elif field:
            _set_field(doc, field, text)
        else:
            doc["subheadline"] = _clip(f"{doc.get('subheadline', '')} {text}".strip(), _LIMITS["subheadline"])
        return

    if removing:
        _drop(doc, field if field in ("features", "faq") else "features", _topic(fix) or _object(fix))
        return
    if adding:
        _append_item(doc, field if field in ("features", "faq") else "features", _topic(fix) or _object(fix))
        return
    if _has(low, "shorter", "punchier", "concise", "trim", "too long", "crisp", "more direct"):
        _shorten(doc)
        return
    for table, prefix, needles in _TONES:
        if _has(low, *needles):
            _swap_words(doc, table)
            headline = str(doc.get("headline") or "")
            if not headline.lower().startswith(prefix.lower()):
                doc["headline"] = _clip(prefix + headline, _LIMITS["headline"])
            return
    if _has(low, "simpler", "plain", "english", "jargon", "easier to read", "avoid buzzword"):
        _swap_words(doc, _PLAIN)
        return
    topic = _topic(fix)
    if topic and (field or _has(low, "about", "mention", "focus", "should say")):
        _set_field(doc, field or "subheadline", f"{doc.get('product_name', '')} {topic}".strip())


def _topic(fix: str) -> str:
    m = _TOPIC.search(fix)
    return (m.group(1).strip(" .,;:") if m else "")[:100]


# ----------------------------------------------------------------- designer
_HUES = {"red": 0, "orange": 25, "amber": 40, "yellow": 55, "lime": 90, "green": 120, "emerald": 145,
         "teal": 175, "cyan": 190, "turquoise": 180, "blue": 220, "navy": 230, "indigo": 250, "violet": 270,
         "purple": 280, "magenta": 300, "pink": 330, "brown": 30}
_FONTS = ("Franklin Gothic Medium", "Book Antiquity", "Times New Roman", "Palatino", "Garamond", "Georgia",
          "Trebuchet MS", "Courier New", "Lucida Console", "Arial Black", "Segoe UI", "Helvetica", "Verdana",
          "Tahoma", "Consolas", "Impact", "Arial")


def _hls(value: str):
    return rgb_to_hls(*(c / 255 for c in hex_to_rgb(value)))


def _hex(h: float, l: float, s: float) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in hls_to_rgb(h % 1.0, min(1.0, max(0.0, l)),
                                                                    min(1.0, max(0.0, s))))


def _turn(value: str, target_deg: float, amount: float = 0.65) -> str:
    h, l, s = _hls(value)
    delta = ((target_deg / 360.0 - h + 0.5) % 1.0) - 0.5
    return _hex(h + delta * amount, l, s)


def _shift(value: str, dl: float = 0.0, ds: float = 0.0) -> str:
    h, l, s = _hls(value)
    return _hex(h, l + dl, s + ds)


def _luminance(value: str) -> float:
    return relative_luminance(hex_to_rgb(value))


def _to_side(value: str, dark: bool) -> str:
    """Blend `value` towards black or white until its luminance leaves the band where AA is unreachable."""
    target, limit = ("#000000", DARK_MAX) if dark else ("#ffffff", LIGHT_MIN)
    for step in range(21):
        cand = value if step == 0 else mix(value, target, step / 20)
        lum = _luminance(cand)
        if (dark and lum <= limit) or (not dark and lum >= limit):
            return cand
    return mix(value, target, 1.0)


def _settle_sides(pal: dict) -> None:
    """Background and surface must sit on the same side of that band, or no single text colour passes both."""
    dark = _luminance(pal["background"]) < (DARK_MAX + LIGHT_MIN) / 2
    for key in ("background", "surface"):
        pal[key] = _to_side(pal[key], dark)


def _readable(fg: str, backgrounds: list[str]) -> str:
    """Nearest tint or shade of `fg` that clears AA against every background, or "" if none exists."""
    if all(contrast_ratio(fg, b) >= AA for b in backgrounds):
        return fg
    anchors = ("#0b1220", "#f4f8fc") if max(_luminance(b) for b in backgrounds) > 0.3 else ("#f4f8fc", "#0b1220")
    for anchor in anchors:
        for step in range(1, 21):
            cand = mix(fg, anchor, step / 20)
            if all(contrast_ratio(cand, b) >= AA for b in backgrounds):
                return cand
    return ""


# The pairs Design._contrast checks; a palette outside them is rejected and fails the run.
_PAIRS = (("text", ("background", "surface")), ("muted_text", ("background", "surface")),
          ("accent", ("surface",)), ("primary_text", ("primary",)))


def _recompute(pal: dict) -> None:
    """Repair an edited palette before it is returned: Design._contrast rejects anything below AA."""
    _settle_sides(pal)
    for key, bgs in _PAIRS:
        if key != "primary_text":
            pal[key] = _readable(pal[key], [pal[b] for b in bgs]) or pal[key]
    white, ink = "#ffffff", "#0b1220"
    anchor = white if contrast_ratio(white, pal["primary"]) >= contrast_ratio(ink, pal["primary"]) else ink
    pal["primary"] = _readable(pal["primary"], [anchor]) or pal["primary"]
    pal["primary_text"] = white if contrast_ratio(white, pal["primary"]) >= contrast_ratio(ink, pal["primary"]) else ink


def _colour_slot(low: str) -> str:
    if _has(low, "background", "page colour", "page color", "canvas"):
        return "background"
    if _has(low, "card", "surface", "panel"):
        return "surface"
    if _has(low, "muted", "secondary text", "caption"):
        return "muted_text"
    if _has(low, "accent", "highlight"):
        return "accent"
    if _has(low, "text colour", "text color", "font colour", "font color", "foreground", "writing"):
        return "text"
    return "primary"


def _font_stack(low: str) -> str:
    for family in _FONTS:
        if family.lower() in low:
            stack = f"'{family}', {SYSTEM_BODY}"
            return stack if _SAFE_FONT.match(stack) else ""
    if _has(low, "serif"):
        return "Georgia, 'Times New Roman', serif"
    if _has(low, "mono"):
        return "'Courier New', Consolas, monospace"
    if _has(low, "sans"):
        return SYSTEM_BODY
    return ""


def apply_design(current: dict, fixes: list[str]) -> dict:
    pal = dict(current.get("palette") or {})
    fonts = dict(current.get("fonts") or {})
    if not pal:
        return dict(current)
    for fix in fixes:
        _design_edit(pal, fonts, fix)
    _recompute(pal)
    out = {**current, "palette": pal, "fonts": fonts or current.get("fonts") or {}}
    return out


def _slot_for(fix: str, needle: str) -> str:
    """Which colour the clause mentioning this colour names: "dark page with a green button" -> button."""
    for part in _CLAUSE.split(fix):
        if needle.lower() in part.lower():
            return _colour_slot(part.lower())
    return _colour_slot(fix.lower())


def _design_edit(pal: dict, fonts: dict, fix: str) -> None:
    low = fix.lower()
    hexes = _HEX.findall(fix)
    if hexes:
        pal[_slot_for(fix, hexes[0])] = hexes[0]
        for extra, other in zip(hexes[1:], ("accent", "surface", "text")):
            pal[other] = extra
    else:
        for name, hue in _HUES.items():
            if re.search(rf"\b{name}\b", low):
                slot = _slot_for(fix, name)
                pal[slot] = _turn(pal.get(slot) or pal["primary"], hue)
                if slot == "primary":
                    pal["accent"] = _turn(pal.get("accent") or pal["primary"], (hue + 40) % 360, 0.8)
                break
    if _has(low, "warm", "warmer", "sunset", "cosy", "cozy"):
        for key in ("primary", "accent"):
            pal[key] = _turn(pal[key], 30 if key == "primary" else 45)
    elif _has(low, "cool", "cooler", "colder", "icy"):
        for key in ("primary", "accent"):
            pal[key] = _turn(pal[key], 215 if key == "primary" else 190)
    if _has(low, "bright", "vivid", "punchy", "stronger colour", "stronger color"):
        for key in ("primary", "accent"):
            pal[key] = _shift(pal[key], ds=0.2)
    elif _has(low, "muted", "subtle", "pastel", "softer colour", "softer color", "desaturate", "calmer"):
        for key in ("primary", "accent"):
            pal[key] = _shift(pal[key], ds=-0.2)
    if _has(low, "darker", "dark mode", "dark theme", "make it dark", "deep") or (
            re.search(r"\bdark\b", low) and _has(low, "background", "page", "theme", "mode")):
        # A page that only just leaves the AA-dead band reads as grey, not dark: go most of the way to ink.
        pal["background"] = mix(pal["background"], "#0b1220", 0.86)
        pal["surface"] = mix(pal["surface"], "#0b1220", 0.78)
    elif _has(low, "lighter", "make it light", "light mode", "brighter background", "whiter") or (
            re.search(r"\blight\b", low) and _has(low, "background", "page", "theme", "mode")):
        pal["background"] = mix(pal["background"], "#f7fafc", 0.92)
        pal["surface"] = mix(pal["surface"], "#f7fafc", 0.84)
    stack = _font_stack(low)
    if stack:
        for key, keys in (("heading", ("heading", "headline", "title", "h1")), ("body", ("body", "paragraph", "text"))):
            if _has(low, *keys):
                fonts[key] = stack
        if not (_has(low, "heading", "headline", "title", "h1", "body", "paragraph", "text")):
            fonts["heading"] = fonts["body"] = stack


# ----------------------------------------------------------------- engineer
def apply_page(page: str, current_html: str, fixes: list[str]) -> str:
    rules = _read_overrides(current_html)
    page = _carry_over(page, current_html)
    guard = _MEDIA_GUARD.search(current_html or "")
    guard_text = guard.group(0) if guard else ""
    for fix in fixes:
        page = _patch_markup(page, fix)
        for source in (_page_rules(fix), _literal_rules(fix)):
            for key, value in source.items():
                rules[key] = value
        if _reduced_motion.search(fix):
            guard_text = _GUARD_TEXT
    if 'class="skip-link"' in page:
        for key, value in _SKIP_RULES.items():
            rules.setdefault(key, value)
    css = _render(rules) + guard_text
    if not css:
        return page
    i = page.rfind("</style>")
    return page if i == -1 else f"{page[:i]}/*launch-overrides*/{css}/*end-launch-overrides*/{page[i:]}"


# ------------------------------------------------------------------ markup patches
# An audit spells out the exact tag or element it wants ("Add in <head>: <meta ...>"), so the mock
# can insert that literal markup. A real model would rewrite the document; this only ever adds the
# allowlisted elements below, never a script the instruction named in passing.
_HEAD_ADD = re.compile(r"add in <head>\s*:?\s*(.*)", re.I | re.S)
_AFTER_BODY = re.compile(r"insert (?:immediately )?after the opening <body> tag\s*:?\s*(.*)", re.I | re.S)
_HEAD_TAG = re.compile(r"""<meta\b[^<>]*>|<title\b[^<>]*>[^<>]*</title>|"""
                       r"""<script\b[^<>]*application/ld\+json[^<>]*>[^<>]*</script>""", re.I)
_ANCHOR_TAG = re.compile(r"<a\b[^<>]*>[^<>]*</a>", re.I)
_UNSAFE_TAG = re.compile(r"javascript\s*:|\son[a-z]+\s*=", re.I)
_MEDIA_GUARD = re.compile(r"@media\s*\(prefers-reduced-motion[^{}]*\{(?:[^{}]|\{[^{}]*\})*\}", re.I | re.S)
_reduced_motion = re.compile(r"prefers-reduced-motion", re.I)
_CSS_BLOCK = re.compile(r"([^\s{};]+)\{([^{}]*)\}")
_GUARD_TEXT = "@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important;" \
              "scroll-behavior:auto!important}}"
_SKIP_RULES = {(".skip-link", "position"): "absolute", (".skip-link", "left"): "-9999px",
               (".skip-link", "top"): "0", (".skip-link", "z-index"): "99",
               (".skip-link:focus", "left"): "12px", (".skip-link:focus", "top"): "12px",
               (".skip-link:focus", "background"): "var(--primary)",
               (".skip-link:focus", "color"): "var(--on-primary)",
               (".skip-link:focus", "padding"): "12px 18px", (".skip-link:focus", "min-height"): "44px",
               (".skip-link:focus", "border-radius"): "8px"}


def _attr(tag: str, name: str) -> str:
    m = re.search(rf'{name}\s*=\s*"([^"]*)"', tag, re.I) or re.search(rf"{name}\s*=\s*'([^']*)'", tag, re.I)
    return m.group(1) if m else ""


def _patch_markup(page: str, fix: str) -> str:
    for patch in (_add_head_tags, _add_main, _add_skip_link, _demote_extra_h1):
        page = patch(page, fix)
    return page


def _add_head_tags(page: str, fix: str) -> str:
    m = _HEAD_ADD.search(fix)
    if not m:
        return page
    add = "".join(t for t in (_void_open(x) for x in _HEAD_TAG.findall(m.group(1)))
                  if not _UNSAFE_TAG.search(t) and not _owned_by_sanitizer(t) and not _already_in(page, t))
    if not add:
        return page
    i = page.rfind("</head>")
    return page if i == -1 else f"{page[:i]}{add}{page[i:]}"


def _attrs_of(tag: str) -> dict:
    out = {k.lower(): v for k, v in re.findall(r'([a-zA-Z0-9_:.-]+)\s*=\s*"([^"]*)"', tag)}
    out.update({k.lower(): v for k, v in re.findall(r"([a-zA-Z0-9_:.-]+)\s*=\s*'([^']*)'", tag)})
    return out


def _already_in(page: str, tag: str) -> bool:
    """Does the page already carry this tag? Meta tags match on their key, JSON-LD on its type.

    Compared by attribute rather than text because a sanitised page is re-serialised: the same tag
    comes back as `<meta charset="utf-8"/>` with sorted attributes, and must not be added twice.
    """
    low = tag.lower()
    if low.startswith("<meta"):
        attrs = _attrs_of(tag)
        key = attrs.get("name") or attrs.get("property") or attrs.get("http-equiv")
        if not key:                                       # charset-style tag: nothing to key on
            return any(_attrs_of(other) == attrs for other in _HEAD_TAG.findall(page) if other.lower().startswith("<meta"))
        return bool(re.search(
            rf'<meta[^<>]+(?:name|property|http-equiv)\s*=\s*["\']?{re.escape(key)}', page, re.I))
    if low.startswith("<title"):
        return bool(re.search(r"<title", page, re.I))
    if low.startswith("<script"):
        return bool(re.search(r"<script[^<>]+application/ld\+json", page, re.I))
    return True


def _carry_over(page: str, previous: str) -> str:
    """Re-apply markup an earlier audit fix inserted, which this fresh rebuild has dropped.

    Every build is re-composed from copy + design, so inserted elements only survive if they are
    carried over - the same deal the CSS override block already makes for style edits.
    """
    if not previous:
        return page
    head = "".join(t for t in (_void_open(x) for x in _HEAD_TAG.findall(previous))
                   if not _UNSAFE_TAG.search(t) and not _owned_by_sanitizer(t) and not _already_in(page, t))
    if head:
        i = page.rfind("</head>")
        page = f"{page[:i]}{head}{page[i:]}" if i != -1 else page
    link = next((t for t in _ANCHOR_TAG.findall(previous)
                 if "skip-link" in t and not _UNSAFE_TAG.search(t) and _attr(t, "href").startswith("#")), "")
    return _insert_link(page, link) if link and "skip-link" not in page else page


_VOID_SELF_CLOSE = re.compile(r"\s*/>\s*$")


def _void_open(tag: str) -> str:
    """`<meta ... />` -> `<meta ...>`.

    html.parser treats a self-closed void tag as a container and nests whatever follows it inside it,
    which is how a carried-over tag can end up owning the rest of the head.
    """
    return _VOID_SELF_CLOSE.sub(">", tag) if tag.lower().startswith("<meta") else tag


def _owned_by_sanitizer(tag: str) -> bool:
    """Metas the sanitizer adds or strips itself: carrying them over would only cause collisions."""
    return tag.lower().startswith("<meta") and _attr(tag, "http-equiv").lower() in {"content-security-policy", "refresh"}


def _add_skip_link(page: str, fix: str) -> str:
    m = _AFTER_BODY.search(fix)
    if not m or "skip-link" in page:
        return page
    link = next((t for t in _ANCHOR_TAG.findall(m.group(1))
                 if not _UNSAFE_TAG.search(t) and _attr(t, "href").startswith("#")), "")
    return _insert_link(page, link) if link else page


def _insert_link(page: str, link: str) -> str:
    """Put the skip link first in the tab order, and make sure its target really exists."""
    target = _attr(link, "href")[1:]
    if not re.search(rf'id\s*=\s*["\']?{re.escape(target)}\b', page):
        main = re.search(r"<main\b([^<>]*)>", page, re.I)
        # A link to nothing would trade an a11y warning for a broken-anchor error, so require a target.
        if not main or re.search(r"\bid\s*=", main.group(1), re.I):
            return page
        page = page[:main.start()] + f'<main id="{target}"{main.group(1)}>' + page[main.end():]
    body = re.search(r"<body\b[^<>]*>", page, re.I)
    return page if not body else page[:body.end()] + link + page[body.end():]


def _add_main(page: str, fix: str) -> str:
    if not re.search(r"wrap the page content in <main", fix, re.I) or re.search(r"<main\b", page, re.I):
        return page
    start, end = re.search(r"<section\b", page, re.I), page.rfind("</section>")
    if not start or end == -1:
        return page
    return f"{page[:start.start()]}<main id=\"lc-main\">{page[start.start():end + 10]}</main>{page[end + 10:]}"


def _demote_extra_h1(page: str, fix: str) -> str:
    if not re.search(r"exactly one <h1", fix, re.I):
        return page
    seen = []

    def _swap(m):
        seen.append(1)
        return m.group(0) if len(seen) == 1 else m.group(0).replace("h1", "h2")

    return re.sub(r"<h1\b[^<>]*>[^<>]*</h1>", _swap, page)


def _literal_rules(fix: str) -> dict:
    """CSS the audit wrote out literally, e.g. ":focus-visible{outline:...}". Selector is the token
    right before the brace, so the prose that introduces it is ignored."""
    out: dict[tuple[str, str], str] = {}
    for selector, body in _CSS_BLOCK.findall(fix):
        selector = selector.strip()
        if not _SAFE_SELECTOR.match(selector):
            continue
        for declaration in body.split(";"):
            prop, _, value = declaration.partition(":")
            prop, value = prop.strip(), value.strip()
            if prop and value and _SAFE_CSS_VALUE.match(value):
                out[(selector, prop)] = value
    return out


def _read_overrides(html: str) -> dict:
    m = _OVERRIDES.search(html)
    out: dict[tuple[str, str], str] = {}
    if not m:
        return out
    for selector, body in _BLOCK.findall(m.group(1)):
        selector = selector.strip()
        if not _SAFE_SELECTOR.match(selector):
            continue
        for declaration in body.split(";"):
            prop, _, value = declaration.partition(":")
            prop, value = prop.strip(), value.strip()
            if prop and value and _SAFE_CSS_VALUE.match(value):
                out[(selector, prop)] = value
    return out


def _render(rules: dict) -> str:
    by_selector: dict[str, list[str]] = {}
    for (selector, prop), value in rules.items():
        by_selector.setdefault(selector, []).append(f"{prop}:{value}")
    return "".join(f"{selector}{{{';'.join(declarations)}}}" for selector, declarations in by_selector.items())


def _size(low: str) -> str:
    m = _SIZE.search(low)
    if not m:
        return ""
    value, unit = int(m.group(1)), m.group(2)
    if unit == "px" and not 8 <= value <= 220:
        return ""
    return f"{value}{unit}"


def _page_rules(fix: str) -> dict:
    low = fix.lower()
    out: dict[tuple[str, str], str] = {}
    size = _size(low)
    button = _has(low, "button", "cta", "sign up", "signup", "submit")
    heading = _has(low, "headline", "heading", "title", "h1", "h2")
    spacing = _has(low, "spacing", "padding", "breathing room", "airy", "more space", "looser", "roomier")
    tight = _has(low, "tighter", "less space", "compact", "denser", "closer together")

    if button and _has(low, "bigger", "larger", "big", "increase", "prominent", "chunky", "thicker", "grow"):
        out.update({(".btn", "min-height"): "60px", (".btn", "padding"): "0 38px", (".btn", "font-size"): "19px"})
    elif button and _has(low, "smaller", "small", "reduce", "thinner", "shrink"):
        out.update({(".btn", "min-height"): "42px", (".btn", "padding"): "0 18px", (".btn", "font-size"): "15px"})
    if button and size:
        out[(".btn", "min-height")] = size

    if heading and _has(low, "bigger", "larger", "big", "prominent", "increase"):
        out[("h1", "font-size")] = "clamp(38px, 7vw, 66px)"
    elif heading and _has(low, "smaller", "small", "thinner", "reduce"):
        out[("h1", "font-size")] = "clamp(28px, 5vw, 44px)"
    if heading and size:
        out[("h1", "font-size")] = size
    if size and not (button or heading) and _has(low, "body", "paragraph", "text", "readable"):
        out[("body", "font-size")] = size

    if spacing:
        out[("section", "padding")] = "84px 0"
    elif tight:
        out[("section", "padding")] = "34px 0"
    if _has(low, "rounded", "rounder", "soft corners", "curved", "pill", "more radius"):
        out[(":root", "--radius")] = "22px"
    elif _has(low, "sharp", "square corner", "flat corner", "less rounded", "no radius", "straight corner"):
        out[(":root", "--radius")] = "2px"
    if _has(low, "wider", "full width", "spread out", "more width"):
        out[(".wrap", "max-width")] = "1280px"
    elif _has(low, "narrow", "narrower", "content width", "tighter width"):
        out[(".wrap", "max-width")] = "880px"
    if _has(low, "centre", "center", "centred", "middle", "symmetric"):
        out.update({("#hero", "text-align"): "center", (".hero-grid", "grid-template-columns"): "1fr",
                    (".hero-art", "display"): "none", (".signup", "justify-content"): "center"})
    elif _has(low, "left align", "left-align", "flush left", "not centered", "not centre"):
        out.update({("#hero", "text-align"): "left", (".signup", "justify-content"): "flex-start"})
    if _has(low, "uppercase", "all caps", "capitalise", "capitalize"):
        out[("h2", "text-transform")] = "uppercase"
    if _has(low, "gradient"):
        out[(".btn", "background")] = "linear-gradient(135deg,#06B6D4,#6366F1)"
    if _has(low, "shadow", "depth", "elevat"):
        out[(".card", "box-shadow")] = "0 14px 34px rgba(0,0,0,.14)"
    elif _has(low, "no shadow", "flat card", "remove shadow", "drop shadow"):
        out[(".card", "box-shadow")] = "none"
    if _has(low, "hide the visual", "hide the image", "remove the image", "no illustration", "hide the graphic",
           "remove the graphic"):
        out[(".hero-art", "display")] = "none"
    if _has(low, "one column", "single column", "stack the feature", "full width card"):
        out[(".fgrid", "grid-template-columns")] = "minmax(0,1fr)"
    elif _has(low, "two column", "2 column", "side by side"):
        out[(".fgrid", "grid-template-columns")] = "repeat(2,minmax(0,1fr))"
    stack = _font_stack(low)
    if stack:
        if _has(low, "heading", "headline", "title", "h1", "h2"):
            out[("h1,h2,h3", "font-family")] = stack
        elif _has(low, "body", "paragraph", "text"):
            out[("body,.signup,input", "font-family")] = stack
        else:
            out[("h1,h2,h3,body,.btn,nav .brand", "font-family")] = stack
    if _has(low, "underline"):
        out[("a", "text-decoration")] = "underline"
    return out
