"""The style system: twelve genuinely different compositions, built and checked offline.

Two things are asserted over and over here. First that a style owns structure (hero, navigation,
feature layout, motif, tokens) rather than colour, so two styles cannot produce the same page. Second
that the old theme-based directions stored on runs created before this existed still resolve and still
build, because those runs must remain restorable and re-publishable.
"""
import json
import re
from hashlib import sha256

import pytest

from app.agents import styles as design_styles
from app.agents import variants
from app.agents.schemas import CopyDoc, Design, SiteSpec, brief_line
from app.llm.mock import MockProvider, build_page

# Every feature layout the renderer knows, keyed by the styles.py slot name.
FEATURE_CLASS = {"plain-list": "flist", "bento": "fbento", "index-table": "ftab", "tiles": "ftiles",
                 "grid": "fgrid", "checklist": "fcheck", "spotlight": "fspot", "products": "fprod",
                 "articles": "farts", "manifest": "fman", "numbered": "fnum", "duo": "fduo"}


def copy_doc(sections=()) -> dict:
    """A full CopyDoc: the core five fields plus placeholder content for the optional sections."""
    doc = {"product_name": "Nightly", "headline": "Habits for night-shift workers", "subheadline": "A calm tracker",
           "features": [{"title": f"Feature {i}", "description": f"Description {i}"} for i in range(1, 5)],
           "faq": [{"question": f"Question {i}?", "answer": f"Answer {i}"} for i in range(1, 4)],
           "cta": {"label": "Get early access", "supporting_text": "We will email you at launch"}}
    if "testimonials" in sections:
        doc["testimonials"] = [{"quote": f"Sample quote {i}", "attribution": "Sample customer", "sample": True}
                               for i in range(1, 3)]
    if "pricing" in sections:
        doc["pricing"] = [{"name": f"Plan {i}", "price": "Sample price", "blurb": "What you get",
                           "items": ["One thing", "Another"], "featured": i == 2, "sample": True}
                          for i in range(1, 4)]
    if "gallery" in sections:
        doc["gallery"] = [{"title": f"Piece {i}", "caption": "Placeholder panel", "sample": True}
                          for i in range(1, 4)]
    if "team" in sections:
        doc["team"] = [{"role": "Founder", "focus": "Placeholder person", "sample": True},
                       {"role": "Design", "focus": "Placeholder person", "sample": True}]
    if "contact" in sections:
        doc["contact"] = {"email": "", "phone": "", "location": "", "note": "Add your own details.", "sample": True}
    return doc


def payload(d: variants.DesignDirection) -> dict:
    return {"copy": copy_doc(d.sections), "design": {"palette": dict(d.palette), "fonts": dict(d.fonts),
                                                     "layout_style": d.layout_style},
            "direction": variants.as_dict(d)}


def page_for(style_key: str) -> tuple[variants.DesignDirection, str]:
    d = variants.direction_for(f"style-{style_key}", {"style": style_key})
    return d, build_page(payload(d))


def tag_shape(html: str) -> str:
    """The page's skeleton (tags, ids, classes) plus its CSS, with all copy removed.

    Two styles that only differ in colour must still come out as different shapes here.
    """
    css = re.search(r"<style>(.*?)</style>", html, re.S)
    skeleton = re.sub(r">\s*[^<]*<", "><", re.sub(r"<style>.*?</style>", "", html, flags=re.S))
    return sha256(((css.group(1) if css else "") + re.sub(r"\s+", " ", skeleton)).encode("utf-8")).hexdigest()


def structure_only(html: str) -> str:
    """Tags, ids and classes only - the composition, ignoring colour and copy."""
    return " ".join(re.findall(r'<[a-z]+[^>]*>', re.sub(r"<style>.*?</style>", "", html, flags=re.S)))


def section_order(html: str) -> tuple:
    return tuple(re.findall(r'<(?:section|header) id="([\w-]+)"', html))


def seeded(n: int = 96) -> list[variants.DesignDirection]:
    """Directions for a series of realistic run ids, so seed behaviour is tested on many ids at once."""
    return [variants.pick_direction(f"68b1c2d3e4f5a6b7c8d9e0f{n:02d}") for n in range(n)]


# ----------------------------------------------------------------- the registry
def test_twelve_styles_each_own_a_distinct_composition():
    assert len(design_styles.STYLES) == 12
    for slot in ("hero", "nav", "features", "motif"):
        used = [getattr(s, slot) for s in design_styles.STYLES]
        assert len(set(used)) == 12, f"two styles share a {slot}: {used}"


def test_every_style_palette_and_font_stack_is_valid():
    for s in design_styles.STYLES:
        Design.model_validate({"palette": s.palette, "fonts": s.fonts, "layout_style": s.layout_style})
        assert set(s.tokens) >= {"width", "pad", "base", "h1", "small", "btn_min"}, s.key
        assert s.hero in design_styles.HEROES and s.nav in design_styles.NAVS
        assert s.features in design_styles.FEATURE_LAYOUTS and s.motif in design_styles.MOTIFS


def test_style_orders_cover_the_required_and_their_own_sections():
    for s in design_styles.STYLES:
        assert set(design_styles.REQUIRED_SECTIONS) <= set(s.order), s.key
        assert set(s.sections) <= set(s.order), s.key
        assert set(s.order) <= set(design_styles.SECTION_KEYS), s.key
        assert len(s.order) == len(set(s.order)), f"{s.key}: a section appears twice"


def test_business_types_and_sections_point_at_real_things():
    for b in design_styles.BUSINESS_TYPES:
        assert design_styles.get(b.style) is not None, b.key
        assert set(b.sections) <= set(design_styles.OPTIONAL_SECTIONS), b.key
    for needles in design_styles.SECTION_KEYWORDS.values():
        assert needles


def test_feature_keywords_only_add_sections_that_exist():
    for section, needles in design_styles.SECTION_KEYWORDS.items():
        for needle in needles:
            assert section in design_styles.sections_for("other", [needle]), f"{needle} -> {section}"


# ----------------------------------------------------------------- directions
def test_an_explicit_style_beats_the_seed():
    for s in design_styles.STYLES:
        d = variants.direction_for("any-run-id", {"style": s.key})
        assert d.style_key == s.key and d.hero == s.hero and d.nav == s.nav
        assert d.features == s.features and d.motif == s.motif and d.radius == s.radius
        assert d.tokens == s.tokens and d.rules == s.rules


def test_the_seed_spreads_runs_over_the_whole_registry():
    picked = seeded()
    assert {d.style_key for d in picked} == set(design_styles.keys())
    assert max(sum(1 for d in picked if d.style_key == k) for k in design_styles.keys()) <= 16
    first, second = variants.pick_direction("run-7"), variants.pick_direction("run-7")
    assert first.key == second.key


def test_required_sections_survive_any_brief():
    for spec in ({"business_type": "store", "features": ["pricing table", "team page"]},
                 {"style": "brutalist", "sections": ["contact"]}, {"sections": ["gallery"]}, {}):
        d = variants.direction_for("seed", spec)
        assert set(design_styles.REQUIRED_SECTIONS) <= set(d.sections)
        assert d.hero in design_styles.HEROES and d.features in FEATURE_CLASS


def test_sections_the_brief_adds_are_ordered_before_the_closing_pairs():
    d = variants.direction_for("seed", {"style": "minimal", "sections": ["contact", "team"]})
    order = list(d.sections)
    assert {"contact", "team"} <= set(order)
    assert order.index("team") < order.index("cta") and order.index("contact") < order.index("cta")


def test_a_preferred_colour_is_applied_or_explained_never_silently_dropped():
    dark = variants.direction_for("seed", {"style": "minimal", "color": "#b45309"})
    assert dark.color_note and dark.palette["primary"].lower() == "#b45309"
    hard = variants.direction_for("seed", {"style": "glass", "color": "#ff66cc"})
    assert hard.color_note.startswith("preferred colour")
    assert Design.model_validate({"palette": hard.palette, "fonts": hard.fonts, "layout_style": "glass"})
    none = variants.direction_for("seed", {"style": "saas", "color": "red"})
    assert none.color_note == "" and none.palette == design_styles.get("saas").palette


def test_direction_survives_a_state_round_trip():
    for s in design_styles.STYLES:
        d = variants.direction_for("rt", {"style": s.key, "sections": ["pricing"], "color": "#0e7490"})
        restored = variants.from_dict(json.loads(json.dumps(variants.as_dict(d))))
        assert restored.key == d.key and restored.palette == d.palette and restored.order == d.order
        assert restored.tokens == d.tokens and restored.nav == d.nav and restored.color_note == d.color_note


def test_a_tampered_direction_rebuilds_from_the_style():
    bad = variants.as_dict(variants.direction_for("x", {"style": "luxury"}))
    bad["hero"] = 'x{background:url("//evil"}'
    bad["features"] = 'y{color:red}'
    d = variants.from_dict(bad)
    assert d.style_key == "luxury" and d.hero == "editorial" and d.features == "index-table"
    assert "evil" not in str(variants.as_dict(d))


def test_unknown_or_missing_direction_falls_back():
    assert variants.from_dict(None).key == variants.fallback().key
    assert variants.from_dict({"key": "nope"}).key == variants.fallback().key
    bad = variants.as_dict(variants.fallback())
    del bad["order"][1]                                   # a required section went missing
    assert variants.from_dict(bad).key == variants.fallback().key


def test_legacy_theme_directions_still_resolve_exactly():
    theme = variants.LEGACY_THEMES[3]
    d = variants.compose_legacy(theme, "band", "checklist", "glow", ("features", "faq", "cta"))
    restored = variants.from_dict(variants.as_dict(d))
    assert restored.theme_key == theme.key and restored.style_key == ""
    assert restored.nav == "top-links" and restored.tokens == variants.LEGACY_TOKENS
    assert restored.palette == theme.palette and restored.order == ("features", "faq", "cta")


def test_prompt_block_carries_a_machine_readable_direction():
    d = variants.fallback()
    match = re.search(r"DESIGN_DIRECTION: (\{.*\})[ \t]*$", variants.prompt_block(d), re.M)
    assert match, "DESIGN_DIRECTION must sit on its own line for the mock provider to read"
    assert variants.from_dict(json.loads(match.group(1))).key == d.key
    assert d.label in variants.prompt_block(d)


# ----------------------------------------------------------------- the brief
def test_the_spec_describes_itself_without_inventing_answers():
    spec = SiteSpec(business_type="store", style="store", audience="cyclists", color="#0f766e",
                    features=["gallery", "pricing"], pages=["home", "catalogue"], tone="warm")
    line = spec.brief_block()
    for needle in ("Online store", "E-commerce storefront", "cyclists", "#0f766e", "gallery", "home"):
        assert needle in line, f"{needle} missing from: {line}"
    assert "audience: " in line and "pages: " in line


def test_an_unusable_spec_is_rejected_rather_than_silently_fixed():
    for bad in ({"style": "neon"}, {"business_type": "restaurant-unknown"}, {"color": "red"},
                {"pages": ["Not A Slug"]}, {"sections": ["newsletter"]}):
        with pytest.raises(ValueError):
            SiteSpec(**bad)


def test_brief_line_tolerates_a_state_from_before_the_wizard():
    assert "crew's choice" in brief_line({})
    assert brief_line(None) == ""
    assert brief_line({"style": "brutalist", "business_type": "nonsense"}) == (
        "design style: Brutalist & bold (brutalist)")
    assert "sections the brief asked for: pricing" in brief_line({"sections": ["pricing", "newsletter"]})


# ----------------------------------------------------------------- generated pages
def test_all_twelve_styles_build_twelve_different_pages():
    shapes = {tag_shape(page_for(s.key)[1]) for s in design_styles.STYLES}
    assert len(shapes) == 12


def test_pages_differ_in_structure_not_just_colour():
    """Same copy, same builder: the markup itself has to change between styles."""
    structures = {structure_only(page_for(s.key)[1]) for s in design_styles.STYLES}
    assert len(structures) == 12


def test_page_follows_its_direction_order_and_layout_slots():
    for s in design_styles.STYLES:
        d, html = page_for(s.key)
        assert section_order(html) == ("hero", *d.sections), f"{s.key}: {section_order(html)}"
        assert f'class="{FEATURE_CLASS[d.features]}' in html, f"{s.key}: wrong feature layout"
        assert f'hero hero-{d.hero}' in html, f"{s.key}: wrong hero"
        assert d.tokens["width"] in html and d.tokens["pad"] in html, f"{s.key}: tokens not applied"
        assert d.palette["background"].lower() in html.lower() and d.fonts["heading"] in html


def test_every_page_keeps_the_four_sections_and_working_anchors():
    for s in design_styles.STYLES:
        d, html = page_for(s.key)
        ids = re.findall(r'id="([\w-]+)"', html)
        assert {"hero", "features", "faq", "cta"} <= set(ids), d.key
        assert len(ids) == len(set(ids)), f"{d.key}: duplicate ids"
        for target in set(re.findall(r'href="#([\w-]+)"', html)):
            assert target in ids, f"{d.key}: #{target} has no target"
        assert html.count("<h1") == 1, f"{d.key}: exactly one h1"
        assert "<style>" in html and 'name="viewport"' in html
        assert "http://" not in html and "https://" not in html, f"{d.key}: page is not self-contained"


def test_sample_content_is_labelled_rather_than_presented_as_real():
    d, html = page_for("saas")
    assert 'id="testimonials"' in html and 'id="pricing"' in html
    assert html.count('class="sample"') >= 2, "placeholder quotes and prices must say so"
    real = dict(copy_doc(d.sections))
    real["testimonials"] = [{"quote": "A real customer quote", "attribution": "Real name", "sample": False}]
    labelled = build_page({"copy": real, "design": {"palette": d.palette, "fonts": d.fonts,
                                                    "layout_style": d.layout_style}, "direction": variants.as_dict(d)})
    assert "A real customer quote" in labelled
    assert labelled.count('class="sample"') < html.count('class="sample"')


def test_a_page_without_a_direction_still_builds():
    """Runs created before directions existed (and the LLM path) must not break."""
    theme = variants.LEGACY_THEMES[0]
    old = {"copy": copy_doc(), "design": {"palette": theme.palette, "fonts": theme.fonts,
                                          "layout_style": theme.layout_style}}
    html = build_page(old)
    assert {"hero", "features", "faq", "cta"} <= set(re.findall(r'id="([\w-]+)"', html))
    assert "hero-rail" in html                                  # the fallback style's composition
    assert theme.palette["background"].lower() in html.lower()  # but its own colours


def test_a_stored_legacy_direction_rebuilds_the_page_it_was_made_with():
    theme = variants.LEGACY_THEMES[2]
    d = variants.compose_legacy(theme, "band", "checklist", "glow", ("faq", "features", "cta"))
    html = build_page(payload(d))
    assert "hero-band" in html and 'class="fcheck"' in html
    assert section_order(html) == ("hero", "faq", "features", "cta")
    assert theme.fonts["heading"] in html


async def test_mock_agents_reproduce_the_direction_end_to_end():
    """Designer echoes the block's palette, Engineer builds the block's page - no API keys needed."""
    d = variants.direction_for("68b1c2d3e4f5a6b7c8d9e0ff12", {"style": "gradient"})
    messages = [{"role": "user", "content": "IDEA: a habit tracker for night shifts\n" + variants.prompt_block(d)}]
    design = await MockProvider().complete(agent="designer", model="m", messages=messages, json_mode=True,
                                           tools=None, temperature=0.7, max_tokens=700)
    assert json.loads(design.text)["palette"] == d.palette

    blob = "INPUT_JSON: " + json.dumps(payload(d), separators=(",", ":")) + "\n" + variants.prompt_block(d)
    page = await MockProvider().complete(agent="engineer", model="m", messages=[{"role": "user", "content": blob}],
                                         json_mode=False, tools=None, temperature=0.6, max_tokens=6000)
    assert page.text.startswith("```html")
    assert f'hero hero-{d.hero}' in page.text and section_order(page.text) == ("hero", *d.order)


async def test_the_copywriter_is_told_which_sections_to_write():
    """The mock fills the direction's optional sections; nothing else appears on the page."""
    d = variants.direction_for("seed", {"style": "corporate"})
    blob = "IDEA: a tool for nurses\nSECTIONS: " + ",".join(d.sections)
    out = json.loads((await MockProvider().complete(agent="copywriter", model="m",
                                                    messages=[{"role": "user", "content": blob}], json_mode=True,
                                                    tools=None, temperature=0.7, max_tokens=1800)).text)
    doc = CopyDoc.model_validate(out)
    assert doc.testimonials and doc.contact                       # corporate asks for both
    plain = json.loads((await MockProvider().complete(
        agent="copywriter", model="m",
        messages=[{"role": "user", "content": "IDEA: a tool for nurses\nSECTIONS: features,faq,cta"}],
        json_mode=True, tools=None, temperature=0.7, max_tokens=1800)).text)
    assert not CopyDoc.model_validate(plain).testimonials


async def test_a_feature_column_edit_reaches_every_style_layout():
    """A "make the features one column" edit reaches whichever of the twelve layouts the run uses."""
    for s in design_styles.STYLES:
        d, html = page_for(s.key)
        blob = ("INPUT_JSON: " + json.dumps(payload(d), separators=(",", ":")) + "\n"
                "FIXES (apply all, keep everything else unchanged):\n- Make the features one column\n"
                "CURRENT_HTML:\n" + html + "\n" + variants.prompt_block(d))
        page = await MockProvider().complete(agent="engineer", model="m",
                                             messages=[{"role": "user", "content": blob}], json_mode=False,
                                             tools=None, temperature=0.6, max_tokens=6000)
        block = re.search(r"/\*launch-overrides\*/(.*?)/\*end-launch-overrides\*/", page.text, re.S)
        assert block and "grid-template-columns:minmax(0,1fr)" in block.group(1), s.key


# ----------------------------------------------------------------- real Chromium
@pytest.fixture
async def browser_ok():
    from app.tools.browser_checks import BrowserUnavailable, run_checks
    try:
        await run_checks("<html><body>x</body></html>")
    except (BrowserUnavailable, ImportError):
        pytest.skip("Playwright/Chromium not available")


async def test_every_style_passes_the_browser_checks(browser_ok):
    """Twelve compositions, both viewports: no contrast, overflow or anchor errors."""
    from app.tools.browser_checks import run_checks, summarize
    for s in design_styles.STYLES:
        d, html = page_for(s.key)
        checks, _ = await run_checks(html)
        failed = [c for c in checks if not c["passed"]]
        assert summarize(checks)["errors"] == 0, f"{d.key}: {failed}"


async def test_seeded_directions_and_legacy_pages_pass_the_browser_checks(browser_ok):
    from app.tools.browser_checks import run_checks, summarize
    pages = [build_page(payload(d)) for d in seeded(6)]
    pages.append(build_page({"copy": copy_doc(), "design": {"palette": variants.LEGACY_THEMES[2].palette,
                                                             "fonts": variants.LEGACY_THEMES[2].fonts,
                                                             "layout_style": "ledger"},
                             "direction": variants.as_dict(variants.compose_legacy(
                                 variants.LEGACY_THEMES[2], "centered", "grid", "pills",
                                 ("features", "faq", "cta")))}))
    for html in pages:
        checks, _ = await run_checks(html)
        assert summarize(checks)["errors"] == 0, [c for c in checks if not c["passed"]]
