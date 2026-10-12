"""The theme system: appearance tokens that any style can be drawn in.

Three invariants drive these tests, because each is the failure mode the design exists to avoid.

1. *No palette can be saved that the crew would reject.* Every resolved theme has to pass
   `Design._contrast`, including the ones a user typed by hand - so `ensure_aa()` is asserted against
   adversarial input, not just the curated families.
2. *A theme never changes a layout slot.* Twelve genuinely distinct styles only stay distinct if
   re-theming cannot touch hero, navigation, feature layout or motif.
3. *What is stored is what is rendered.* `as_stored()` feeds `resolve()` back to itself unchanged, so
   a theme restored next month draws the same page as the one it was saved from.
"""
import json
import random
import re

import pytest

from app.agents import styles as design_styles
from app.agents import theme, variants
from app.agents.schemas import CopyDoc, Design, SiteSpec, brief_line
from app.llm.mock import build_page

LAYOUT_SLOTS = frozenset({"hero", "nav", "features", "motif", "order", "layout_style", "style"})


def design_of(t: dict) -> Design:
    return Design.model_validate({"palette": t["palette"], "fonts": t["fonts"], "layout_style": "minimal"})


def copy_doc() -> dict:
    """The smallest copy set the page builder accepts, for the tests that render a real page."""
    doc = {"product_name": "Nightly", "headline": "Habits for night-shift workers",
           "subheadline": "A calm tracker", "features": [{"title": f"F{i}", "description": f"D{i}"}
                                                         for i in range(1, 4)],
           "faq": [{"question": f"Q{i}?", "answer": f"A{i}"} for i in range(1, 4)],
           "cta": {"label": "Get early access", "supporting_text": "We email you at launch"}}
    return CopyDoc.model_validate(doc).model_dump()


# ------------------------------------------------------------------ colour
@pytest.mark.parametrize("family", [f.key for f in theme.FAMILIES])
@pytest.mark.parametrize("mode", list(theme.MODES))
def test_curated_families_are_accessible(family, mode):
    t = theme.resolve({"family": family, "mode": mode})
    assert design_of(t)
    assert t["notes"] == [], f"{family}/{mode} had to be repaired: {t['notes']}"
    assert all(row["passes"] for row in t["contrast"]), t["contrast"]


def test_poor_contrast_is_flagged_before_it_is_repaired():
    """The UI must be able to show *why* a colour moved, so the raw input has to be measurable."""
    ugly = theme.derive({"background": "#7f7f7f", "surface": "#808080", "text": "#8a8a8a",
                         "primary": "#7f7f7f", "secondary": "#7f7f7f", "accent": "#888888"})
    assert [r for r in theme.contrast_report(ugly) if not r["passes"]]
    repaired, notes = theme.ensure_aa(ugly)
    assert notes and all(r["passes"] for r in theme.contrast_report(repaired))


def test_opposite_pole_canvases_do_not_ping_pong():
    """The regression this walk was rewritten for: a light page with a dark panel.

    One body text colour has to read on both, so the naive per-pair repair alternated between the two
    canvases forever and gave up with three pairs failing.
    """
    t = theme.resolve({"colors": {"background": "#099950", "surface": "#1600a3", "text": "#6f0367",
                                  "primary": "#c8b400", "secondary": "#7f7f7f", "accent": "#8e5cff"}})
    assert design_of(t)
    assert all(r["passes"] for r in t["contrast"]), t["contrast"]
    assert any("opposite light/dark pole" in n for n in t["notes"]), t["notes"]


@pytest.mark.parametrize("seed", list(range(120)))
def test_any_six_colours_resolve_to_a_valid_palette(seed):
    """Half mid-tone (the unreadable zone), half fully random, so both repair paths get exercised."""
    rng = random.Random(seed)
    pick = rng.choice([lambda: "#%06x" % rng.randrange(0x1000000),
                       lambda: "#%06x" % rng.randrange(0x400000, 0xC00000)])
    t = theme.resolve({"colors": {slot: pick() for slot in theme.COLOR_SLOTS}})
    assert design_of(t)
    assert all(r["passes"] for r in t["contrast"]), (seed, t["colors"], t["contrast"])


def test_partial_input_keeps_the_family_and_fills_the_rest():
    base = theme.resolve({"family": "luxury", "mode": "dark"})
    t = theme.resolve({"family": "luxury", "mode": "dark", "colors": {"accent": "#FFFFFF"}})
    assert t["colors"]["accent"] == "#ffffff"
    for slot in theme.COLOR_SLOTS:
        if slot != "accent":
            assert t["colors"][slot] == base["colors"][slot]


def test_unsafe_colour_values_are_ignored_not_injected():
    t = theme.resolve({"family": "corporate", "colors": {"background": "red; }</style><script>x</script>",
                                                         "text": "#112233"}})
    assert t["colors"]["text"] == "#112233"
    assert all(theme.HEX.fullmatch(v) for v in t["colors"].values()), t["colors"]
    assert all(theme.HEX.fullmatch(v) for v in t["palette"].values())


def test_derive_rejects_a_missing_slot():
    with pytest.raises(ValueError, match="six-digit hex"):
        theme.derive({"background": "#FFFFFF", "surface": "#000000", "text": "#111111",
                      "primary": "#222222", "secondary": "#333333", "accent": "crimson"})


def test_labels_are_derived_from_their_own_fill():
    """Button text is never user-editable, so it can never be the reason a button is unreadable."""
    t = theme.resolve({"colors": {"primary": "#FFFFFF"}})
    assert t["derived"]["primary_text"] in ("#ffffff", "#0d1117")
    assert theme.contrast_ratio(t["derived"]["primary_text"], t["colors"]["primary"]) >= theme.AA_TEXT


# ------------------------------------------------------------------ tokens
def test_a_theme_never_touches_a_layout_slot():
    """Re-theming must not be able to collapse twelve styles into one template."""
    style = design_styles.STYLES[0]
    for value in ({"family": "creative", "density": "compact", "radius": "pill", "card": "glass"},
                  {"family": "minimalist", "mode": "dark", "scale": 1.2}):
        tokens = theme.tokens_for(theme.resolve(value), style)
        assert not set(tokens) & LAYOUT_SLOTS
        assert all(k in theme.THEME_TOKEN_KEYS for k in tokens if k not in style.tokens), tokens.keys()


def test_every_theme_token_is_css_safe():
    for group in theme.PRESETS:
        for preset in theme.PRESETS[group]:
            for key, value in preset.tokens.items():
                assert theme._safe_token(value), f"{group}/{preset.key}.{key}"
                assert key in theme.THEME_TOKEN_KEYS, key
    t = theme.resolve({"family": "futuristic", "card": "glass", "shadow": "hard", "button": "outline"})
    for key, value in t["tokens"].items():
        assert theme._safe_token(value), (key, value)


@pytest.mark.parametrize("bad", ["</style>", "url(data:text/html,<x>)", "expression(alert(1))",
                                 "javascript:alert(1)", "1px; color: red", "var(--x){y}"])
def test_injection_shaped_token_values_are_refused(bad):
    assert not theme._safe_token(bad)


def test_components_follow_the_tokens_rather_than_being_patched_one_by_one():
    """Buttons and cards reference the custom properties the page declares, so one colour change
    restyles every control without a per-element patch."""
    for preset in theme.PRESETS["button"]:
        if preset.key in ("solid", "pill", "sharp"):
            assert preset.tokens["btn_bg"] == "var(--primary)"
            assert preset.tokens["btn_fg"] == "var(--on-primary)"
    for preset in theme.PRESETS["card"]:
        if preset.key in ("filled", "elevated"):
            assert preset.tokens["card_bg"] == "var(--surface)"


def test_density_and_scale_are_relative_to_each_style():
    """Twelve styles at 'Compact' must still be twelve different pages."""
    wide = max(design_styles.STYLES, key=lambda s: theme._px(s.tokens["pad"]))
    lean = min(design_styles.STYLES, key=lambda s: theme._px(s.tokens["pad"]))
    plain, tight = (theme.resolve({"family": "corporate"}),
                    theme.resolve({"family": "corporate", "density": "compact"}))
    assert theme._px(theme.tokens_for(tight, wide)["pad"]) < theme._px(theme.tokens_for(plain, wide)["pad"])
    # Density scales each style's own rhythm instead of setting one padding value for every page.
    assert theme._px(theme.tokens_for(tight, wide)["pad"]) > theme._px(theme.tokens_for(tight, lean)["pad"])
    assert abs(theme._px(theme.tokens_for(tight, wide)["pad"]) / theme._px(wide.tokens["pad"]) - 0.78) < 0.01
    roomy = theme.tokens_for(theme.resolve({"family": "corporate", "density": "roomy"}), wide)
    assert theme._px(roomy["pad"]) > theme._px(theme.tokens_for(plain, wide)["pad"])


def test_font_scale_reaches_type_only():
    style = design_styles.STYLES[0]
    base = theme.tokens_for(theme.resolve({}), style)
    big = theme.tokens_for(theme.resolve({"scale": 1.2}), style)
    assert theme._px(big["h3"]) > theme._px(base["h3"])
    assert big["pad"] == base["pad"] and big["width"] == base["width"]
    # line-height moves with the type, but damped so a large scale does not become sparse
    assert float(big["lh"]) > float(base["lh"])


def test_type_never_falls_below_the_sizes_the_browser_check_enforces():
    t = theme.tokens_for(theme.resolve({"scale": 0.1}), design_styles.STYLES[0])
    assert theme._px(t["base"]) >= 16 and theme._px(t["small"]) >= 12


def test_scale_is_clamped_to_the_control_range():
    assert theme._clean_scale(9) == theme.SCALE_MAX
    assert theme._clean_scale(-4) == theme.SCALE_MIN
    assert theme._clean_scale("nonsense") == 1.0


def test_width_and_radius_reach_the_page():
    t = theme.resolve({"family": "corporate", "width": "narrow", "radius": "pill"})
    tokens = theme.tokens_for(t, design_styles.STYLES[0])
    assert (t["width"], tokens["width"]) == ("820px", "820px")
    assert (t["radius"], tokens["radius"]) == ("999px", "999px")
    assert (t["art_radius"], tokens["art_radius"]) == ("32px", "32px")
    default = theme.tokens_for(theme.resolve({"family": "corporate"}), design_styles.STYLES[0])
    assert default["width"] == design_styles.STYLES[0].tokens["width"]  # 'Default' keeps the style's own


def test_unknown_preset_key_keeps_the_family_choice_instead_of_substituting():
    t = theme.resolve({"family": "luxury", "radius": "nonsense", "button": "also-nonsense"})
    assert t["radius_key"] == "square" and t["button"] == "outline"


def test_pairings_are_system_stacks_the_sanitizer_cannot_break():
    """Every `<link>` is removed from a generated page, so a web font would silently downgrade."""
    for p in theme.PAIRINGS:
        for stack in (p.heading, p.body):
            assert "http" not in stack and "@" not in stack
            assert re.fullmatch(r"[A-Za-z0-9 ,'\"\-]+", stack), stack
    t = theme.resolve({"pairing": "editorial"})
    assert t["fonts"]["heading"].startswith("'Palatino")


# ------------------------------------------------------------------ storage
def test_a_stored_theme_resolves_back_to_the_same_page():
    for value in ({}, {"family": "creative", "mode": "dark"}, {"family": "pastel", "scale": 1.15},
                  {"colors": {"background": "#101010", "surface": "#202020", "text": "#EFEFEF",
                              "primary": "#22C55E", "secondary": "#A3A3A3", "accent": "#F59E0B"}}):
        original = theme.resolve(value)
        stored = theme.as_stored(original)
        again = theme.resolve(stored)
        assert again["palette"] == original["palette"]
        assert again["tokens"] == original["tokens"]
        assert (again["radius"], again["width"]) == (original["radius"], original["width"])
        assert again["notes"] == []  # already repaired: restoring must not move anything further


def test_only_the_controls_are_stored_so_later_fixes_reach_old_themes():
    stored = theme.as_stored(theme.resolve({"family": "creative", "card": "glass"}))
    assert set(stored["colors"]) == set(theme.COLOR_SLOTS)
    assert not set(stored) & {"palette", "derived", "tokens", "contrast", "notes", "fonts"}


def test_every_control_survives_being_saved_and_read_back():
    """A stored theme keeps the *control* the user set, never the value it produced.

    That is what makes a later preset change reach old themes, and it only works if every group round-trips
    as a key: a width saved as `1240px` would not match the `wide` control on read, and the theme would
    silently lose it.
    """
    controls = {"family": "creative", "mode": "dark", "pairing": "editorial", "scale": 1.15,
                "density": "compact", "width": "wide", "radius": "pill", "shadow": "strong",
                "button": "outline", "card": "glass"}
    stored = theme.as_stored(theme.resolve(controls))
    assert {k: stored[k] for k in controls if k != "colors"} == controls
    again = theme.resolve(stored)
    assert theme.as_stored(again) == stored
    assert (again["width"], again["radius"]) == ("1240px", "999px")
    assert theme.tokens_for(again, design_styles.get("startup")) == \
           theme.tokens_for(theme.resolve(controls), design_styles.get("startup"))


def test_a_control_that_is_not_a_key_falls_back_to_the_family_instead_of_guessing():
    """An old or hand-edited document stores a CSS value where a key belongs: the family's own setting
    is used, which is honest, rather than the nearest preset being invented."""
    stored = dict(theme.as_stored(theme.resolve({"family": "corporate", "width": "wide"})))
    stored["width"] = "1240px"
    assert theme.resolve(stored)["width_key"] == theme.FAMILY_BY_KEY["corporate"].width


def test_a_preset_fix_reaches_themes_saved_before_it(monkeypatch):
    """Nothing derived is persisted, so the theme a user saved months ago follows the current presets."""
    stored = theme.as_stored(theme.resolve({"family": "creative", "card": "glass"}))
    assert theme.resolve(stored)["tokens"]["card_blur"] == "blur(10px)"
    monkeypatch.setitem(next(p for p in theme.PRESETS["card"] if p.key == "glass").tokens,
                        "card_blur", "blur(18px)")
    assert theme.resolve(stored)["tokens"]["card_blur"] == "blur(18px)"


def test_names_are_trimmed_to_the_documented_limit():
    assert theme.clean_name("  my   very  long  theme  ") == "my very long theme"
    assert len(theme.clean_name("x" * 200)) == theme.THEME_NAME_MAX


def test_registry_describes_every_control_the_ui_has_to_draw():
    r = theme.registry()
    assert [f["key"] for f in r["families"]] == [f.key for f in theme.FAMILIES]
    assert len(r["families"]) >= 7 and all(set(f["modes"]) == set(theme.MODES) for f in r["families"])
    assert set(r["presets"]) == set(theme.PRESETS)
    assert {p["key"] for p in r["pairings"]} == {p.key for p in theme.PAIRINGS}
    assert r["colors"] == list(theme.COLOR_SLOTS) and r["default"]
    assert r["limits"]["themes_per_user"] == theme.MAX_THEMES_PER_USER
    for family in r["families"]:
        for mode, card in family["modes"].items():
            assert all(row["passes"] for row in card["contrast"]), (family["key"], mode)


def test_describe_reads_like_a_sentence_about_the_appearance():
    line = theme.describe(theme.as_stored(theme.resolve({"family": "luxury", "mode": "dark",
                                                          "density": "roomy", "scale": 1.2})))
    assert "Luxury" in line and "dark" in line and "roomy density" in line and "1.2x" in line
    assert not set(re.findall(r"hero|motif", line))


# ------------------------------------------------------------------ the run's direction
def themed(family="futuristic", **kw) -> variants.DesignDirection:
    return variants.direction_for("a habit tracker", {"theme": {"family": family, **kw}})


def page_of(d: variants.DesignDirection) -> str:
    return build_page({"copy": copy_doc(), "design": {"palette": dict(d.palette), "fonts": dict(d.fonts),
                                                      "layout_style": d.layout_style},
                       "direction": variants.as_dict(d)})


def test_a_themed_direction_survives_the_round_trip_through_run_state():
    """The one requirement the direction store exists to satisfy.

    A run stores its direction as a dict and reads it back on every revision, re-publish and restore.
    If the theme did not survive that, resuming a project would silently re-skin the page its user
    approved.
    """
    d = themed(density="roomy", radius="pill", pairing="editorial")
    again = variants.from_dict(variants.as_dict(d))
    assert again == d
    assert again.tokens == d.tokens and again.radius == d.radius
    assert again.palette == d.palette and again.fonts == d.fonts
    assert again.theme == d.theme and again.key == d.key


def test_theming_cannot_move_a_layout_slot():
    for s in design_styles.STYLES:
        plain = variants.direction_for("idea", {"style": s.key})
        themed_run = variants.direction_for("idea", {"style": s.key, "theme": {
            "family": "pastel", "density": "compact", "radius": "square"}})
        for slot in ("hero", "nav", "features", "motif", "order", "layout_style", "style_key"):
            assert getattr(themed_run, slot) == getattr(plain, slot), (s.key, slot)
        assert themed_run.tokens["pad"] != plain.tokens["pad"]      # appearance did move
        assert themed_run.tokens["h1"] != plain.tokens["h1"] or themed_run.radius != plain.radius


def test_the_theme_reaches_the_rendered_page():
    """A token that round-trips but is never read would pass every test above and do nothing."""
    bright, quiet = themed(family="vibrant"), themed(family="minimalist")
    html_bright, html_quiet = page_of(bright), page_of(quiet)
    assert f"--bg:{bright.palette['background']}" in html_bright
    assert f"--bg:{quiet.palette['background']}" in html_quiet
    assert html_bright != html_quiet
    assert bright.fonts["heading"] in html_bright and quiet.fonts["heading"] not in html_bright


def test_a_direction_stored_before_themes_still_resolves_unchanged():
    stored = variants.as_dict(variants.direction_for("idea", {"style": "brutalist"}))
    stored.pop("theme")
    stored["tokens"] = dict(design_styles.get("brutalist").tokens)
    d = variants.from_dict(stored)
    assert d.tokens == design_styles.get("brutalist").tokens
    assert d.radius == design_styles.get("brutalist").radius and d.theme == {}


def test_tampered_stored_tokens_are_dropped_not_pasted_into_css():
    d = themed()
    style = design_styles.get(d.style_key)
    stored = variants.as_dict(d)
    stored["tokens"]["pad"] = "60px; } * { color: red"
    stored["tokens"]["shadow"] = "</style><script>alert(1)</script>"
    stored["fonts"]["heading"] = "Georgia, url(evil)"
    back = variants.from_dict(stored)
    assert back.tokens["pad"] == style.tokens["pad"]           # the style's own value, not the payload
    assert "shadow" not in back.tokens                          # refused outright
    assert back.fonts["heading"] == style.fonts["heading"]
    assert all(theme._safe_token(v) for v in back.tokens.values())


def test_a_themed_direction_renders_in_the_themes_own_type():
    d = themed(family="vibrant", pairing="editorial")
    assert d.fonts["heading"] != design_styles.get(d.style_key).fonts["heading"]
    assert d.fonts["heading"] in page_of(d)


def test_a_legacy_direction_is_unaffected_by_the_theme_plumbing():
    stored = {"theme_key": "terminal", "hero": "split", "features": "grid", "motif": "glow",
              "order": ["features", "faq", "cta"]}
    d = variants.from_dict(stored)
    assert d.tokens == variants.LEGACY_TOKENS and not d.theme
    assert variants.from_dict(variants.as_dict(d)) == d


def test_the_briefs_preferred_colour_is_resolved_through_the_theme():
    d = variants.direction_for("idea", {"style": "minimal", "color": "#7f7f7f",
                                        "theme": {"family": "corporate"}})
    assert theme.contrast_ratio(d.palette["primary_text"], d.palette["primary"]) >= theme.AA_TEXT
    assert d.color_note  # what moved, and why, is recorded rather than silently applied


def test_the_trace_and_the_prompt_describe_the_theme_rather_than_only_the_style():
    d = themed(family="luxury", mode="dark")
    assert "Luxury" in d.brief() and "dark" in d.brief()
    block = variants.prompt_block(d)
    assert "This run is themed" in block and "custom properties" in block
    payload = json.loads(re.search(r"DESIGN_DIRECTION: (\{.*\})", block).group(1))
    assert variants.from_dict(payload) == d


def test_a_brief_theme_is_validated_and_readable_by_the_agents():
    spec = SiteSpec.model_validate({"business_type": "saas", "style": "dark",
                                    "theme": {"family": "pastel", "mode": "dark", "radius": "pill"}})
    assert spec.theme["family"] == "pastel" and spec.theme["radius"] == "pill"
    line = brief_line(spec.model_dump())
    assert "theme:" in line and "Pastel" in line
    assert variants.direction_for("idea", spec.model_dump()).theme == spec.theme
    empty = SiteSpec.model_validate({"business_type": "saas"})
    assert empty.theme == {} and "theme:" not in brief_line(empty.model_dump())


# ------------------------------------------------------------------ the rendered page
def root_of(html: str) -> dict:
    block = re.search(r":root\{(.*?)\}", html, re.S).group(1)
    return dict(re.findall(r"(--[a-z0-9-]+):([^;]*);", block))


def test_the_page_declares_its_tokens_once_rather_than_repeating_them():
    """Every component reads the same variables, so a global change is a change to this one block."""
    d = themed(family="vibrant", shadow="medium", card="elevated", button="pill")
    root = root_of(page_of(d))
    for prop in ("--bg", "--surface", "--text", "--primary", "--accent", "--secondary", "--on-secondary",
                 "--radius", "--pad", "--base", "--h1", "--wrap", "--gap", "--shadow", "--shadow-strong",
                 "--btn-bg", "--btn-radius", "--card-bg", "--card-shadow", "--card-blur", "--border",
                 "--focus", "--band", "--line"):
        assert prop in root, (prop, sorted(root))
    css = re.search(r"<style>(.*?)</style>", page_of(d), re.S).group(1)
    for selector in (".btn{", ".card{", "section{", "body{", "details{", ".plans .plan{"):
        assert selector in css
    assert css.count("var(--card-bg)") >= 3 and css.count("var(--btn-bg)") >= 1


def test_no_template_placeholder_survives_into_a_built_page():
    for s in design_styles.STYLES:
        for spec in ({"style": s.key}, {"style": s.key, "theme": {"family": "minimalist", "card": "glass"}}):
            html = page_of(variants.direction_for("idea", spec))
            assert not re.search(r"__[a-z]+__", html), s.key


def test_an_unthemed_page_is_drawn_with_the_values_it_always_used():
    """Existing projects must not change appearance because a customizer was added."""
    root = root_of(page_of(variants.direction_for("idea", {"style": "minimal"})))
    assert root["--btn-bg"] == "var(--primary)" and root["--card-bg"] == "var(--surface)"
    assert root["--card-shadow"] == "none" and root["--card-blur"] == "none"
    assert root["--card-pad"] == "22px" and root["--shadow"] == "none"
    assert root["--radius"] == design_styles.get("minimal").radius
    assert root["--pad"] == design_styles.get("minimal").tokens["pad"]


def test_a_theme_choice_changes_the_variable_not_the_component_css():
    plain, glass = page_of(themed(family="corporate")), page_of(themed(family="corporate", card="glass"))
    strip = lambda h: re.sub(r":root\{.*?\}", "", re.search(r"<style>(.*?)</style>", h, re.S).group(1))
    assert strip(plain) == strip(glass)          # same rules, different tokens
    assert root_of(glass)["--card-blur"] == "blur(10px)"
    assert root_of(plain)["--card-blur"] == "none"
    assert root_of(glass)["--card-bg"].startswith("color-mix(")


def test_the_theme_border_colour_replaces_the_hairline_every_rule_reads():
    """`--line` is what ~30 component rules use for hairlines, so that is the variable a theme must
    write. A border token that only set a variable of its own would change nothing on the page."""
    plain = root_of(page_of(variants.direction_for("idea", {"style": "minimal"})))
    d = themed(family="corporate")
    assert plain["--border"] == "var(--line)"                      # alias, unthemed pages unchanged
    assert root_of(page_of(d))["--line"] == d.tokens["border"] != plain["--line"]
    assert root_of(page_of(d))["--border"] == "var(--line)"        # still an alias, not a second source


def test_the_theme_tone_reaches_the_page_across_every_breakpoint_declaration():
    d = themed(family="creative", density="compact", scale=1.15, width="wide", radius="square")
    root = root_of(page_of(d))
    style = design_styles.get(d.style_key)
    assert root["--radius"] == "0px" and root["--wrap"] == "1240px"
    assert theme._px(root["--pad"]) < theme._px(style.tokens["pad"])
    assert theme._px(root["--h3"]) > theme._px(style.tokens["h3"])
    html = page_of(d)
    assert "@media (max-width:719px)" in html and "@media (prefers-reduced-motion:reduce)" in html
    assert "backdrop-filter:var(--card-blur)" in html


def test_a_bad_token_cannot_bypass_the_variable_block():
    d = themed()
    stored = variants.as_dict(d)
    stored["tokens"]["pad"] = "20px; } body{display:none"
    root = root_of(page_of(variants.from_dict(stored)))
    assert root["--pad"] == d.tokens["pad"] and "display:none" not in page_of(variants.from_dict(stored))


# ------------------------------------------------------- whole-site requests, in plain English

def test_every_word_the_matcher_knows_names_a_control_the_registry_has():
    """The table is data, so it is checked against the registry rather than trusted.

    A renamed preset would otherwise make "make it premium" answer with a control `resolve()` ignores -
    the one failure mode this whole feature exists to avoid.
    """
    for phrases, controls, why in theme.REQUEST_RULES:
        assert phrases and why
        for key, value in controls.items():
            assert key in {"family", "mode", "pairing", "scale", "density", "width", "radius", "shadow",
                           "button", "card"}
            if key == "family":
                assert value in theme.FAMILY_BY_KEY
            elif key == "mode":
                assert value in theme.MODES
            elif key == "pairing":
                assert value in theme.PAIRING_BY_KEY
            elif key == "scale":
                assert theme.SCALE_MIN <= value <= theme.SCALE_MAX
            else:
                assert theme.preset_key(key, value) == value
            assert theme.control_value_label(key, value) not in ("", str(value)) or key == "mode"


def test_the_briefs_own_sentence_maps_onto_the_luxury_family_and_says_so():
    ask = theme.request_to_controls("make the entire site look more premium")
    assert ask["matched"] is True
    assert ask["controls"] == {"family": "luxury", "colors": {}}
    assert ask["resets"] == ["colors"], "a family word asks for that palette, not a blend of two"
    row = ask["mapping"][0]
    assert row == {"phrase": "premium", "control": "family", "value": "luxury",
                   "label": "Luxury", "why": row["why"]}


def test_a_request_about_one_control_changes_only_that_control():
    ask = theme.request_to_controls("softer, rounded corners")
    assert ask["controls"] == {"radius": "soft"}
    assert [m["control"] for m in ask["mapping"]] == ["radius"]
    assert ask["resets"] == []


def test_two_family_words_produce_one_theme_and_report_the_losing_phrase():
    ask = theme.request_to_controls("make it look luxury but also minimalist")
    assert ask["controls"]["family"] == "minimalist"          # the table's own precedence, not the sentence
    assert ask["conflicts"] == [{"phrase": "luxury", "control": "family", "value": "luxury",
                                 "instead": "minimalist", "instead_phrase": "minimalist"}]


@pytest.mark.parametrize("text, word", [("use glass panels everywhere", "glass"),
                                        ("frosted hero", "frosted"),
                                        ("add gradients", "gradients"),
                                        ("make it #ffc700", "#rrggbb")])
def test_a_request_that_a_token_edit_cannot_answer_is_declined_with_its_reason(text, word):
    ask = theme.request_to_controls(text)
    declined = {d["phrase"] for d in ask["declined"]}
    assert word in declined
    if word in ("glass", "frosted", "gradients"):
        assert ask["matched"] is False                       # declined, and no substitute theme invented


def test_a_sentence_about_behaviour_matches_no_appearance_control_at_all():
    ask = theme.request_to_controls("add a login page, a shopping cart and an admin dashboard")
    assert ask == {"controls": {}, "mapping": [], "resets": [], "conflicts": [], "declined": [],
                   "matched": False}


def test_every_matched_request_is_a_theme_the_customizer_would_store_back_identically():
    """No word may resolve into something it did not ask for: the delta survives `resolve()` intact."""
    for phrases, controls, _why in theme.REQUEST_RULES:
        ask = theme.request_to_controls(" ".join(phrases[:1]))
        assert ask["matched"], phrases
        settled = theme.as_stored(theme.resolve(ask["controls"]))
        for key, value in controls.items():
            stored = settled["width" if key == "width" else key]
            assert stored == ({} if key == "colors" else value), (phrases, key, stored)
