"""Design directions: a valid, distinct page composition for every run."""
import json
import re
from hashlib import sha256

import pytest

from app.agents import variants
from app.agents.schemas import Design
from app.llm.mock import MockProvider, build_page

FEATURE_CLASS = {"grid": "fgrid", "numbered": "fnum", "checklist": "fcheck", "bento": "fbento"}


def copy_doc():
    return {"product_name": "Nightly", "headline": "Habits for night-shift workers", "subheadline": "A calm tracker",
            "features": [{"title": f"Feature {i}", "description": f"Description {i}"} for i in range(1, 4)],
            "faq": [{"question": f"Question {i}?", "answer": f"Answer {i}"} for i in range(1, 4)],
            "cta": {"label": "Get early access", "supporting_text": "We will email you at launch"}}


def payload(d: variants.DesignDirection) -> dict:
    return {"copy": copy_doc(), "design": {"palette": dict(d.palette), "fonts": dict(d.fonts),
                                           "layout_style": d.layout_style}, "direction": variants.as_dict(d)}


def tag_shape(html: str) -> str:
    """The page's skeleton (tags, ids, classes) plus its CSS, with all copy removed.

    Two directions that only differ in colour must still come out as different shapes here.
    """
    css = re.search(r"<style>(.*?)</style>", html, re.S)
    skeleton = re.sub(r">\s*[^<]*<", "><", re.sub(r"<style>.*?</style>", "", html, flags=re.S))
    return sha256(((css.group(1) if css else "") + re.sub(r"\s+", " ", skeleton)).encode("utf-8")).hexdigest()


def section_order(html: str) -> tuple:
    return tuple(re.findall(r'<(?:section|header) id="(\w+)"', html))


def sample(n: int = 24) -> list[variants.DesignDirection]:
    return [variants.pick_direction(f"68b1c2d3e4f5a6b7c8d9e0f{n:02d}") for n in range(n)]


def structure_only(html: str) -> str:
    """Tags, ids and classes only - the composition, ignoring colour and copy."""
    return " ".join(re.findall(r'<[a-z]+[^>]*>', re.sub(r"<style>.*?</style>", "", html, flags=re.S)))


# ----------------------------------------------------------------- the slots
def test_every_theme_palette_passes_the_designer_schema():
    for t in variants.THEMES:
        Design.model_validate({"palette": t.palette, "fonts": t.fonts, "layout_style": t.layout_style})


def test_slots_are_independent_and_all_used():
    picked = sample(48)
    assert {d.theme_key for d in picked} == {t.key for t in variants.THEMES}
    assert {d.hero for d in picked} == set(variants.HEROES)
    assert {d.features for d in picked} == set(variants.FEATURE_LAYOUTS)
    assert {d.motif for d in picked} == set(variants.MOTIFS)
    assert {d.order for d in picked} == set(variants.ORDERS)


def test_direction_is_stable_per_seed_and_rarely_repeats():
    assert variants.pick_direction("run-7").key == variants.pick_direction("run-7").key
    picked = sample(24)
    assert len({d.key for d in picked}) >= 20      # 3072 possible compositions, no flood of repeats
    assert len({(d.hero, d.features, d.motif, d.order) for d in picked}) >= 12


def test_theme_slot_combinations_are_all_buildable():
    for theme in variants.THEMES:
        for hero in variants.HEROES:
            for features in variants.FEATURE_LAYOUTS:
                d = variants.compose(theme, hero, features, "glow", variants.ORDERS[0])
                assert d.hero == hero and d.features == features and d.palette == theme.palette


def test_unknown_or_missing_direction_falls_back():
    assert variants.from_dict(None).key == variants.fallback().key
    assert variants.from_dict({"key": "nope"}).key == variants.fallback().key
    bad = variants.as_dict(variants.fallback())
    bad["hero"] = 'x{background:url("//evil"}'
    assert variants.from_dict(bad).key == variants.fallback().key
    bad = variants.as_dict(variants.fallback())
    bad["order"] = ["features", "faq"]             # a section went missing
    assert variants.from_dict(bad).key == variants.fallback().key


def test_direction_survives_a_state_round_trip():
    for d in sample(6):
        restored = variants.from_dict(json.loads(json.dumps(variants.as_dict(d))))
        assert restored.key == d.key and restored.palette == d.palette and restored.order == d.order


def test_prompt_block_carries_a_machine_readable_direction():
    d = variants.fallback()
    match = re.search(r"DESIGN_DIRECTION: (\{.*\})[ \t]*$", variants.prompt_block(d), re.M)
    assert match, "DESIGN_DIRECTION must sit on its own line for the mock provider to read"
    assert variants.from_dict(json.loads(match.group(1))).key == d.key


# ----------------------------------------------------------------- generated pages
def test_each_direction_builds_a_different_page():
    shapes = {tag_shape(build_page(payload(d))) for d in sample(12)}
    assert len(shapes) == 12


def test_pages_differ_in_structure_not_just_colour():
    """Same copy, same builder: the markup itself has to change between directions."""
    structures = {structure_only(build_page(payload(d))) for d in sample(12)}
    assert len(structures) >= 9


def test_page_follows_its_direction_order_and_feature_layout():
    for d in sample(16):
        html = build_page(payload(d))
        assert section_order(html) == ("hero", *d.order), f"{d.key}: {section_order(html)}"
        assert f'class="{FEATURE_CLASS[d.features]}' in html, f"{d.key}: wrong feature layout"
        assert f'hero hero-{d.hero}' in html, f"{d.key}: wrong hero"


def test_every_page_keeps_the_four_sections_and_working_anchors():
    for d in sample(16):
        html = build_page(payload(d))
        ids = re.findall(r'id="([\w-]+)"', html)
        assert {"hero", "features", "faq", "cta"} <= set(ids), d.key
        assert len(ids) == len(set(ids)), f"{d.key}: duplicate ids"
        for target in set(re.findall(r'href="#([\w-]+)"', html)):
            assert target in ids, f"{d.key}: #{target} has no target"
        assert "<style>" in html and 'name="viewport"' in html
        assert "http://" not in html and "https://" not in html, f"{d.key}: page is not self-contained"


def test_palette_and_fonts_from_the_direction_reach_the_css():
    for d in sample(8):
        html = build_page(payload(d))
        assert d.palette["background"].lower() in html.lower()
        assert d.radius in html


def test_a_page_without_a_direction_still_builds():
    """Runs created before directions existed (and the LLM path) must not break."""
    old = {"copy": copy_doc(), "design": {"palette": variants.THEMES[0].palette, "fonts": variants.THEMES[0].fonts,
                                         "layout_style": "minimal"}}
    html = build_page(old)
    assert {"hero", "features", "faq", "cta"} <= set(re.findall(r'id="([\w-]+)"', html))


async def test_mock_agents_reproduce_the_direction_end_to_end():
    """Designer echoes the block's palette, Engineer builds the block's page - no API keys needed."""
    d = variants.pick_direction("68b1c2d3e4f5a6b7c8d9e0ff12")
    messages = [{"role": "user", "content": "IDEA: a habit tracker for night shifts\n" + variants.prompt_block(d)}]
    design = await MockProvider().complete(agent="designer", model="m", messages=messages, json_mode=True,
                                           tools=None, temperature=0.7, max_tokens=700)
    assert json.loads(design.text)["palette"] == d.palette

    blob = "INPUT_JSON: " + json.dumps(payload(d), separators=(",", ":")) + "\n" + variants.prompt_block(d)
    page = await MockProvider().complete(agent="engineer", model="m", messages=[{"role": "user", "content": blob}],
                                         json_mode=False, tools=None, temperature=0.6, max_tokens=6000)
    assert page.text.startswith("```html")
    assert f'hero hero-{d.hero}' in page.text and section_order(page.text) == ("hero", *d.order)


# ----------------------------------------------------------------- real Chromium
@pytest.fixture
async def browser_ok():
    from app.tools.browser_checks import BrowserUnavailable, run_checks
    try:
        await run_checks("<html><body>x</body></html>")
    except (BrowserUnavailable, ImportError):
        pytest.skip("Playwright/Chromium not available")


async def test_sampled_directions_pass_the_browser_checks(browser_ok):
    from app.tools.browser_checks import run_checks, summarize
    for d in sample(12):
        checks, _ = await run_checks(build_page(payload(d)))
        failed = [c for c in checks if not c["passed"]]
        assert summarize(checks)["errors"] == 0, f"{d.key}: {failed}"
