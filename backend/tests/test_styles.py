"""The style registry's own contract: twelve compositions, the business types that point at them, and
the section arithmetic a brief drives.

`tests/test_variants.py` builds pages from these styles and proves two styles come out with different
shapes. This file stays on the data behind that promise: every slot name in a vocabulary is used exactly
once so no two styles can share a composition and none is dead weight, nothing a style declares can
reach CSS or the wizard as anything but a safe literal, every palette clears the contrast pairs the
Designer schema rejects a run over, and the section helpers add up only what a brief actually named.
"""
import re

import pytest

from app.agents import styles as design_styles
from app.agents.styles import (BUSINESS_TYPES, FEATURE_LAYOUTS, HEROES, MOTIFS, NAVS, OPTIONAL_SECTIONS,
                               REQUIRED_SECTIONS, SECTION_KEYS, TOKEN_DEFAULTS, T)
from app.utils.color import contrast_ratio

# The six pairs `schemas.Design._contrast` validates, so a style is checked against the same rule the
# run is rejected by rather than a looser one invented here.
AA_PAIRS = (("text", "background"), ("text", "surface"), ("muted_text", "background"),
            ("muted_text", "surface"), ("primary_text", "primary"), ("accent", "surface"))

CSS_UNSAFE = (";", "{", "}", "url(", "<", ">", "@", "expression", "javascript:", "/*", "\\")


def px(token: str) -> float:
    """The number a length token starts with, so floors can be compared in px."""
    match = re.match(r"(-?\d+(?:\.\d+)?)px", token)
    assert match, f"expected a px literal, got {token!r}"
    return float(match.group(1))


# ------------------------------------------------------------------ the registry itself

def test_the_registry_holds_twelve_styles_under_twelve_distinct_names():
    assert len(design_styles.STYLES) == 12
    assert design_styles.keys() == tuple(s.key for s in design_styles.STYLES)
    for field in ("key", "label", "blurb", "layout_style"):
        values = [getattr(s, field) for s in design_styles.STYLES]
        assert len(set(values)) == 12, f"two styles share a {field}: {values}"
    for s in design_styles.STYLES:
        assert design_styles.get(s.key) is s
        assert s.label and s.blurb and s.label == s.label.strip()
        assert len(s.blurb) <= 90, f"{s.key}: a blurb the card cannot show"


def test_every_slot_vocabulary_is_used_exactly_once():
    """Twelve styles, twelve names per slot: no style borrows another's composition and no slot is dead."""
    for slot, vocabulary, notes in (("hero", HEROES, design_styles.HERO_NOTES),
                                    ("nav", NAVS, design_styles.NAV_NOTES),
                                    ("features", FEATURE_LAYOUTS, design_styles.FEATURE_NOTES),
                                    ("motif", MOTIFS, design_styles.MOTIF_NOTES)):
        used = [getattr(s, slot) for s in design_styles.STYLES]
        assert len(used) == 12
        assert set(used) == set(vocabulary), f"{slot}: a style names a slot nobody knows"
        assert len(set(used)) == len(used), f"{slot}: two styles share it: {used}"
        assert set(notes) == set(vocabulary), f"{slot}: a slot with no note for the model"
        assert all(str(v).strip() for v in notes.values())


def test_a_styles_slot_notes_explain_all_four_of_its_own_slots():
    for s in design_styles.STYLES:
        text = s.slot_notes()
        for note in (design_styles.HERO_NOTES[s.hero], design_styles.NAV_NOTES[s.nav],
                     design_styles.FEATURE_NOTES[s.features], design_styles.MOTIF_NOTES[s.motif]):
            assert note in text, f"{s.key}: {note!r} missing from its own slot notes"
        assert text.startswith("hero: ") and "navigation: " in text and "motif: " in text


def test_no_two_styles_share_a_palette():
    palettes = {tuple(sorted(s.palette.items())) for s in design_styles.STYLES}
    assert len(palettes) == 12, "two styles are the same palette, which is the one thing this must not be"


# ------------------------------------------------------------------ what reaches CSS

def test_a_token_is_a_literal_the_page_builder_can_paste_into_css():
    for s in design_styles.STYLES:
        assert set(s.tokens) == set(TOKEN_DEFAULTS), f"{s.key}: a token the renderer never reads"
        for name, value in s.tokens.items():
            assert isinstance(value, str) and value.strip(), f"{s.key}.{name}"
            for bad in CSS_UNSAFE:
                assert bad not in value, f"{s.key}.{name} = {value!r} carries {bad!r}"
        assert re.fullmatch(r"\d+px", s.radius), f"{s.key}: radius {s.radius!r} is not a px literal"


def test_type_tokens_never_sink_below_the_readable_floor():
    for s in design_styles.STYLES:
        assert px(s.tokens["base"]) >= 16, f"{s.key}: body text below 16px"
        assert px(s.tokens["small"]) >= 12, f"{s.key}: a size the browser check fails"
        assert px(s.tokens["btn_min"]) >= 40, f"{s.key}: a tap target under 40px"
        assert float(s.tokens["lh"]) >= 1.4, f"{s.key}: line-height too tight to read"


def test_the_token_defaults_are_never_mutated_by_a_styles_overrides():
    before = dict(TOKEN_DEFAULTS)
    custom = T(base="19px", pad="10px")
    assert custom["base"] == "19px" and custom["pad"] == "10px"
    assert TOKEN_DEFAULTS == before, "T() wrote through to the shared defaults"
    assert set(custom) == set(before) and custom["h1"] == before["h1"]
    for s in design_styles.STYLES:
        assert s.tokens is not TOKEN_DEFAULTS and s.tokens["base"] in {"17px", "18px"}


def test_every_palette_is_a_real_hex_set_that_clears_aa_on_the_checked_pairs():
    for s in design_styles.STYLES:
        assert set(s.palette) == {"background", "surface", "text", "muted_text", "primary",
                                  "primary_text", "accent"}, s.key
        for name, colour in s.palette.items():
            assert re.fullmatch(r"#[0-9a-fA-F]{6}", colour), f"{s.key}.{name} = {colour!r}"
        for fg, bg in AA_PAIRS:
            ratio = contrast_ratio(s.palette[fg], s.palette[bg])
            assert ratio >= 4.5, f"{s.key}: {fg} on {bg} is {ratio:.2f}:1, under AA"


def test_font_stacks_name_system_faces_and_load_nothing_remotely():
    for s in design_styles.STYLES:
        assert set(s.fonts) == {"heading", "body"}, s.key
        for name, stack in s.fonts.items():
            assert re.search(r"(sans-serif|serif|monospace)$", stack), f"{s.key}.{name} has no generic fallback"
            for bad in ("http", "@import", "<", ";", "url("):
                assert bad not in stack, f"{s.key}.{name} reaches for {bad!r}"


def test_the_rules_a_style_hands_the_model_are_layout_prose_with_no_remote_asset():
    for s in design_styles.STYLES:
        assert len(s.rules) >= 3, f"{s.key}: too few instructions to tell two styles apart"
        assert len(set(s.rules)) == len(s.rules), f"{s.key}: a rule repeated"
        for rule in s.rules:
            assert 20 <= len(rule) <= 400, f"{s.key}: a rule that is not a sentence"
            for bad in ("http", "<img", "<link", "src=", ".jpg", ".png", "unsplash"):
                assert bad not in rule, f"{s.key}: {rule!r} asks for {bad!r}"


def test_styles_differ_in_shape_not_only_in_colour():
    """The registry's own rule: a style is a composition, not a repaint.

    Together with the slot bijection above, this pins that the measurable numbers a page is built with -
    corners, measure, vertical rhythm, display size, type pairing, section order - also differ between
    styles, so no two of the twelve are the same template painted differently.
    """
    assert len({tuple(sorted(s.tokens.items())) for s in design_styles.STYLES}) == 12
    assert len({s.radius for s in design_styles.STYLES}) >= 9
    for field, floor in (("width", 9), ("pad", 8), ("h1", 11), ("gap", 6), ("lh", 4)):
        assert len({s.tokens[field] for s in design_styles.STYLES}) >= floor, field
    assert len({s.fonts["heading"] for s in design_styles.STYLES}) >= 9
    assert len({s.order for s in design_styles.STYLES}) >= 10
    assert len({s.tokens["btn_case"] for s in design_styles.STYLES}) == 2
    assert len({s.tokens["cta_align"] for s in design_styles.STYLES}) == 2


# ------------------------------------------------------------------ sections a brief owns

def test_a_styles_sections_are_real_names_and_its_order_closes_on_the_cta():
    """A style writes its own preferred sequence, so the order is per-style rather than canonical. The
    helpers that hand sections to a brief do normalise, which is what the last line pins here."""
    for s in design_styles.STYLES:
        assert set(s.sections) <= set(OPTIONAL_SECTIONS), s.key
        assert set(s.sections) <= set(s.order), f"{s.key}: a default section its own order drops"
        assert set(REQUIRED_SECTIONS) <= set(s.order), s.key
        assert set(s.order) <= set(SECTION_KEYS), f"{s.key}: a section nobody renders"
        assert len(s.order) == len(set(s.order)), f"{s.key}: a section twice"
        assert s.order[-1] == "cta", f"{s.key}: a page that does not close on the call to action"
        assert design_styles.resolve_sections("other", [], s.key) == tuple(
            x for x in OPTIONAL_SECTIONS if x in s.sections), s.key


def test_with_sections_reorders_and_leaves_the_registry_untouched():
    minimal = design_styles.get("minimal")
    assert minimal.sections == ()
    asked = design_styles.with_sections(minimal, ("contact", "gallery", "pricing", "not-a-section"))
    assert asked.sections == ("pricing", "gallery", "contact")
    assert asked.key == minimal.key and asked.hero == minimal.hero
    assert design_styles.get("minimal").sections == (), "with_sections wrote through to the registry"
    assert design_styles.with_sections(minimal, ()).sections == ()


# ------------------------------------------------------------------ business types

def test_business_types_are_unique_and_point_at_a_real_style():
    assert len(BUSINESS_TYPES) >= 12
    for b in BUSINESS_TYPES:
        assert design_styles.get(b.style) is not None, f"{b.key}: suggests a style nobody has"
        assert set(b.sections) <= set(OPTIONAL_SECTIONS), b.key
        assert len(set(b.pages)) == len(b.pages) >= 1 and b.pages[0] == "home", b.key
        assert "contact" in b.pages, f"{b.key}: a site type with no way to get in touch"
    assert len({b.key for b in BUSINESS_TYPES}) == len(BUSINESS_TYPES)
    assert len({b.label for b in BUSINESS_TYPES}) == len(BUSINESS_TYPES)
    assert len({b.style for b in BUSINESS_TYPES}) >= 8, "twelve kinds of site, one look"


def test_an_unknown_business_type_gets_the_smallest_honest_set():
    assert design_styles.pages_for("not-a-business") == ("home", "contact")
    assert design_styles.pages_for("") == ("home", "contact")
    assert design_styles.sections_for("not-a-business") == ()
    for b in BUSINESS_TYPES:
        assert design_styles.pages_for(b.key) == b.pages
        assert set(design_styles.sections_for(b.key)) == set(b.sections)
        assert design_styles.sections_for(b.key) == tuple(x for x in OPTIONAL_SECTIONS if x in b.sections)


@pytest.mark.parametrize("needle,section", [
    ("a case study", "testimonials"), ("a subscription tier", "pricing"), ("screenshot gallery", "gallery"),
    ("our founders", "team"), ("book an appointment", "booking"), ("phone and address", "contact"),
])
def test_a_named_feature_adds_the_section_that_can_carry_it(needle, section):
    assert section in design_styles.sections_for("other", [needle])


def test_a_stray_word_invents_no_section_and_a_blank_entry_is_not_a_crash():
    assert design_styles.sections_for("other", ["a calm page for showing hours"]) == ()
    assert design_styles.sections_for("other", ["", None, "  "]) == ()
    assert design_styles.sections_for("", ["pricing"]) == ("pricing",)


def test_sections_are_unioned_in_the_canonical_order_never_the_input_order():
    assert design_styles.sections_for("store", ["team", "pricing"]) == ("pricing", "gallery", "team", "contact")
    assert design_styles.sections_for("store", ["pricing", "team"]) == ("pricing", "gallery", "team", "contact")


def test_resolve_sections_adds_the_styles_defaults_and_nobody_elses():
    assert design_styles.resolve_sections("other", [], "") == ()
    assert design_styles.resolve_sections("other", [], "saas") == ("testimonials", "pricing")
    assert design_styles.resolve_sections("other", [], "not-a-style") == ()
    assert design_styles.resolve_sections("saas", ["booking"], "minimal") == ("testimonials", "pricing", "booking")
    for s in design_styles.STYLES:
        assert set(s.sections) <= set(design_styles.resolve_sections("other", [], s.key)), s.key


# ------------------------------------------------------------------ the wizard's card data

def test_a_card_names_everything_the_wizard_draws():
    cards = design_styles.cards()
    assert len(cards) == 12 and [c["key"] for c in cards] == list(design_styles.keys())
    wanted = {"key", "label", "blurb", "layout_style", "hero", "nav", "features", "motif", "radius",
              "sections", "default_sections", "palette", "fonts", "tokens"}
    for card, style in zip(cards, design_styles.STYLES):
        assert set(card) == wanted, card["key"]
        assert card["sections"] == list(REQUIRED_SECTIONS)
        assert card["default_sections"] == list(style.sections)
        assert card["palette"] == style.palette and card["fonts"] == style.fonts
        assert card["tokens"] == style.tokens and card["radius"] == style.radius


def test_a_card_is_a_copy_the_ui_can_mutate_without_touching_the_registry():
    first = design_styles.STYLES[0]
    card = design_styles.as_card(first)
    card["palette"]["background"] = "#00ff00"
    card["tokens"]["base"] = "99px"
    card["fonts"]["heading"] = "Evil Font, url(evil)"
    assert first.palette["background"] != "#00ff00"
    assert first.tokens["base"] != "99px"
    assert first.fonts["heading"] != "Evil Font, url(evil)"
    assert design_styles.as_card(first)["palette"] == first.palette


def test_business_cards_describe_the_type_and_its_default_style():
    cards = design_styles.business_cards()
    assert len(cards) == len(BUSINESS_TYPES)
    for card, business in zip(cards, BUSINESS_TYPES):
        assert card == {"key": business.key, "label": business.label, "style": business.style,
                        "sections": list(business.sections), "pages": list(business.pages)}
