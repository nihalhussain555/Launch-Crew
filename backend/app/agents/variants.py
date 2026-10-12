"""Design directions: the style a run was briefed into, resolved into the slots the page is built from.

`app/agents/styles.py` owns the twelve styles (hero, navigation, feature layout, motif, type scale,
spacing, palette, fonts, sections). A direction is that style plus what this particular run asked for:
the optional sections the brief implies, the run's theme (app/agents/theme.py - colour, spacing rhythm,
radius, shadow, button and card treatment) when the brief carries one, any colour preference re-checked
against WCAG AA, and the section order. The Designer and Engineer receive it as one machine-readable
DESIGN_DIRECTION block, and `app/llm/mock.py` renders it into a real page, so the difference between
two styles is markup rather than a colour swap - and it is testable without API keys.

Directions are stored on the run (`RunState.style`) as a plain dict, so a revision reuses the identity
it was built with instead of re-skinning the page. Everything the page is drawn from has to survive
that round trip: `as_dict` writes the resolved token map and `from_dict` re-reads it, so a themed run
that is resumed, revised or re-published is still themed - a direction that fell back to the style's
own spacing would silently re-skin someone's finished page. Runs created before styles existed carry a
legacy `theme_key`; those still resolve, unchanged.
"""
from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass, field

from app.agents import styles as design_styles
from app.agents import theme as theme_mod
from app.utils.color import contrast_ratio, mix

SYSTEM_BODY = design_styles.SYSTEM_BODY
_HEX = re.compile(r"^#[0-9a-f]{6}$")
# A font stack is pasted into CSS, so the same characters `schemas.Fonts` allows and nothing else.
_FONT = re.compile(r"^[A-Za-z0-9 ,'\"\-]{1,120}$")
HEROES = design_styles.HEROES
NAVS = design_styles.NAVS
FEATURE_LAYOUTS = design_styles.FEATURE_LAYOUTS
MOTIFS = design_styles.MOTIFS
SECTIONS = design_styles.SECTION_KEYS
REQUIRED_SECTIONS = design_styles.REQUIRED_SECTIONS
STYLES = design_styles.STYLES
Style = design_styles.Style

# ----------------------------------------------------------------- legacy themes
# The eight palette/type themes used by runs created before the style system existed. They are kept
# only so a stored legacy direction still resolves to the same page; new runs always get a style.
LEGACY_HEROES = ("split", "centered", "band", "rail")
LEGACY_FEATURES = ("grid", "numbered", "checklist", "bento")
LEGACY_MOTIFS = ("rules", "glow", "pills", "circles")
LEGACY_SECTIONS = ("features", "faq", "cta")
LEGACY_ORDERS = (
    ("features", "faq", "cta"), ("features", "cta", "faq"), ("faq", "features", "cta"),
    ("faq", "cta", "features"), ("cta", "features", "faq"), ("cta", "faq", "features"),
)

# The tokens the old builder hardcoded, so a legacy direction rebuilds the page it had before.
LEGACY_TOKENS = {**design_styles.TOKEN_DEFAULTS,
                 "width": "1040px", "pad": "56px", "pad_half": "28px", "hero_pad": "64px",
                 "track": "-.02em", "cta_align": "center"}


@dataclass(frozen=True)
class Theme:
    """Legacy palette + type. Superseded by `styles.Style`, kept for stored directions."""
    key: str
    label: str
    layout_style: str
    radius: str
    palette: dict = field(repr=False)
    fonts: dict = field(repr=False)


LEGACY_THEMES: tuple[Theme, ...] = (
    Theme("studio", "Studio", "editorial", "4px",
          {"background": "#F7F4EE", "surface": "#FFFFFF", "text": "#1C1917", "muted_text": "#574F45",
           "primary": "#B45309", "primary_text": "#FFFFFF", "accent": "#7C5C2B"},
          {"heading": "Georgia, 'Times New Roman', serif", "body": SYSTEM_BODY}),
    Theme("midnight", "Midnight glow", "bold", "20px",
          {"background": "#0B1220", "surface": "#151F33", "text": "#EEF4FA", "muted_text": "#93A6BC",
           "primary": "#22D3EE", "primary_text": "#04222B", "accent": "#7DD3C0"},
          {"heading": "'Franklin Gothic Medium', 'Segoe UI', Arial, sans-serif", "body": SYSTEM_BODY}),
    Theme("signal", "Signal", "bold", "12px",
          {"background": "#FFFFFF", "surface": "#EEF2F7", "text": "#0B1220", "muted_text": "#4B5866",
           "primary": "#4338CA", "primary_text": "#FFFFFF", "accent": "#0E7490"},
          {"heading": "'Trebuchet MS', 'Segoe UI', Arial, sans-serif", "body": SYSTEM_BODY}),
    Theme("ledger", "Ledger", "minimal", "8px",
          {"background": "#F2F7F6", "surface": "#FFFFFF", "text": "#10231F", "muted_text": "#4E6A64",
           "primary": "#0F766E", "primary_text": "#FFFFFF", "accent": "#B45309"},
          {"heading": "'Helvetica Neue', Helvetica, Arial, sans-serif", "body": SYSTEM_BODY}),
    Theme("ink", "Ink press", "editorial", "2px",
          {"background": "#14161A", "surface": "#1E2127", "text": "#F5F3EF", "muted_text": "#A8A49B",
           "primary": "#E4B363", "primary_text": "#241A05", "accent": "#86C2BC"},
          {"heading": "'Palatino Linotype', Palatino, Georgia, serif", "body": "Georgia, 'Times New Roman', serif"}),
    Theme("pastel", "Pastel pop", "playful", "26px",
          {"background": "#EAFBF3", "surface": "#FFFFFF", "text": "#10231C", "muted_text": "#42604F",
           "primary": "#115E59", "primary_text": "#FFFFFF", "accent": "#C2410C"},
          {"heading": "Verdana, Geneva, sans-serif", "body": SYSTEM_BODY}),
    Theme("terminal", "Terminal", "minimal", "6px",
          {"background": "#0D1117", "surface": "#161B22", "text": "#E6EDF3", "muted_text": "#8B949E",
           "primary": "#3FB950", "primary_text": "#04180A", "accent": "#58A6FF"},
          {"heading": "'Courier New', Consolas, monospace", "body": "'Courier New', Consolas, monospace"}),
    Theme("sunset", "Sunset", "playful", "18px",
          {"background": "#FFF7F2", "surface": "#FFFFFF", "text": "#2A1206", "muted_text": "#6E4A38",
           "primary": "#C2410C", "primary_text": "#FFFFFF", "accent": "#7C3AED"},
          {"heading": "Impact, 'Arial Black', 'Segoe UI', sans-serif", "body": SYSTEM_BODY}),
)
_THEME_BY_KEY = {t.key: t for t in LEGACY_THEMES}


@dataclass(frozen=True)
class DesignDirection:
    key: str                 # stable id for this exact composition
    style_key: str           # "" for a legacy theme direction
    theme_key: str           # legacy only; "" for style-driven directions
    label: str               # shown in the run trace
    layout_style: str        # also written into Design.layout_style
    hero: str
    nav: str
    features: str
    motif: str
    order: tuple[str, ...]   # every section after the hero, in render order
    radius: str
    tokens: dict = field(repr=False)
    rules: tuple = field(repr=False)
    notes: str = ""
    color_note: str = ""           # what happened to the brief's preferred colour, for the run trace
    palette: dict = field(repr=False, default_factory=dict)
    fonts: dict = field(repr=False, default_factory=dict)
    theme: dict = field(repr=False, default_factory=dict)  # the run's theme, as stored ("" when unthemed)

    @property
    def style(self) -> str:
        return self.style_key or self.theme_key

    @property
    def sections(self) -> tuple[str, ...]:
        return self.order

    def optional_sections(self) -> tuple[str, ...]:
        return tuple(s for s in self.order if s not in REQUIRED_SECTIONS)

    def brief(self) -> str:
        """One readable line for the run trace."""
        extra = ", ".join(self.optional_sections())
        return ((f'{theme_mod.describe(self.theme)} - ' if self.theme else f'{self.label} - ')
                + f'hero: {self.hero}; nav: {self.nav}; features: {self.features}; '
                f'motif: {self.motif}; radius {self.radius}'
                + (f'; extra sections: {extra}' if extra else ''))


# ----------------------------------------------------------------- composition
_COMPOSED: dict[tuple, DesignDirection] = {}


def compose(style: Style, order: tuple[str, ...] | None = None,
            palette: dict | None = None, color_note: str = "",
            tokens: dict | None = None, theme_value: dict | None = None,
            fonts: dict | None = None) -> DesignDirection:
    """A direction from a style. `order` may narrow or extend the style's default section sequence.

    An order the caller supplies is taken as complete for the optional sections - it comes back from a
    stored direction, where the brief decided what this run has - so only the three sections every page
    needs are re-added here, never the style's own extras.

    `tokens` is the run's appearance map (from `theme.tokens_for`), applied over the style's own values,
    with `fonts` and `palette` from the same theme; `theme_value` is the theme that produced them, kept
    so the trace and the review step can name it. None of it can change a layout slot, which is why a
    themed run is still recognisably its style.
    """
    seq = _required_only(order if order is not None else _default_order(style))
    overrides = {k: str(v) for k, v in (tokens or {}).items() if k in theme_mod.THEME_TOKEN_KEYS}
    faces = {k: str(v) for k, v in (fonts or {}).items() if _FONT.fullmatch(str(v))}
    slot = (style.key, seq, tuple(sorted((palette or {}).items())), color_note,
            tuple(sorted(overrides.items())), tuple(sorted(faces.items())),
            json.dumps(theme_value or {}, sort_keys=True))
    if slot not in _COMPOSED:
        merged = dict(style.tokens)
        merged.update(overrides)
        _COMPOSED[slot] = DesignDirection(
            key=f"{style.key}-{'-'.join(seq)}" + ("-recoloured" if color_note else "")
                + ("-themed" if overrides and not color_note else ""),
            style_key=style.key, theme_key="",
            label=style.label, layout_style=style.layout_style,
            hero=style.hero, nav=style.nav, features=style.features, motif=style.motif,
            order=seq, radius=overrides.get("radius") or style.radius, tokens=merged,
            rules=style.rules, notes=style.slot_notes(), color_note=color_note,
            palette=dict(palette or style.palette),
            fonts={**style.fonts, **faces} if faces else dict(style.fonts),
            theme=dict(theme_value or {}),
        )
    return _COMPOSED[slot]


def _place(seq: list[str], section: str) -> None:
    """Insert a section where the page's closing FAQ/CTA pair can still follow it."""
    anchor = next((i for i, s in enumerate(seq) if s in ("faq", "cta")), len(seq))
    seq.insert(anchor, section)


def _clean(seq: list[str]) -> tuple[str, ...]:
    """Drop unknown names and repeats, keeping the caller's order."""
    seen: list[str] = []
    for s in seq:
        if s in SECTIONS and s not in seen:
            seen.append(s)
    return tuple(seen)


def _required_only(order: tuple[str, ...]) -> tuple[str, ...]:
    seq = list(order)
    for s in REQUIRED_SECTIONS:
        if s not in seq:
            _place(seq, s)
    return _clean(seq)


def _default_order(style: Style) -> tuple[str, ...]:
    """The style's preferred sequence: every required section once, plus exactly the sections this
    style carries. A section the brief added that the style never ordered goes before the closing
    FAQ/CTA pair, so new content does not land after the page's last call to action."""
    allowed = set(REQUIRED_SECTIONS) | set(style.sections)
    seq = [s for s in style.order if s in allowed]
    for s in list(style.sections):
        if s not in seq:
            _place(seq, s)
    return _required_only(_clean(seq))


def compose_legacy(theme: Theme, hero: str, features: str, motif: str, order: tuple[str, ...]) -> DesignDirection:
    """Rebuild a direction stored before styles existed, with the values it was created with."""
    slot = (f"legacy:{theme.key}", hero, features, motif, tuple(order))
    if slot not in _COMPOSED:
        notes = (f"hero: {design_styles.HERO_NOTES[hero]}; features: {design_styles.FEATURE_NOTES[features]}; "
                 f"motif: {design_styles.MOTIF_NOTES[motif]}")
        _COMPOSED[slot] = DesignDirection(
            key=f"{theme.key}-{hero}-{features}-{motif}-{'-'.join(order)}",
            style_key="", theme_key=theme.key, label=f"{theme.label} {hero} / {features}",
            layout_style=theme.layout_style, hero=hero, nav="top-links", features=features, motif=motif,
            order=tuple(order), radius=theme.radius, tokens=dict(LEGACY_TOKENS), rules=(), notes=notes,
            palette=dict(theme.palette), fonts=dict(theme.fonts),
        )
    return _COMPOSED[slot]


# ----------------------------------------------------------------- the brief
def style_for(seed: str, spec: dict | None) -> Style:
    """The style this run should be built in.

    An explicit choice from the wizard wins. Otherwise the seed picks one, so two different ideas
    rarely land on the same composition - the property the direction system existed for.
    """
    chosen = design_styles.get((spec or {}).get("style"))
    if chosen:
        return chosen
    return STYLES[zlib.crc32(str(seed or "").encode("utf-8")) % len(STYLES)]


def _wanted_sections(style: Style, spec: dict) -> tuple[str, ...]:
    """Optional sections for this run: an explicit list wins, else the brief's business type,
    requested features and the style's own defaults are combined."""
    explicit = (spec or {}).get("sections")
    if isinstance(explicit, list) and explicit:
        return tuple(s for s in design_styles.OPTIONAL_SECTIONS if s in set(explicit))
    wanted = set(design_styles.sections_for((spec or {}).get("business_type", ""),
                                           (spec or {}).get("features", [])))
    return tuple(s for s in design_styles.OPTIONAL_SECTIONS if s in wanted or s in style.sections)


def _recolour(palette: dict, hexc: str) -> tuple[dict, str]:
    """Apply the brief's preferred colour as the primary, or explain why it could not be used.

    The Designer's schema rejects a palette below WCAG AA, so a colour that cannot be made readable
    on this style's surfaces is reported in the run trace instead of quietly being dropped.
    """
    wanted = (hexc or "").strip().lower()
    if not _HEX.fullmatch(wanted):
        return palette, ""
    ink = "#ffffff" if contrast_ratio("#ffffff", wanted) >= contrast_ratio("#0b1220", wanted) else "#0b1220"
    for step in range(21):
        cand = wanted if step == 0 else mix(wanted, ink, step / 20 * 0.55)
        if contrast_ratio(ink, cand) >= 4.5:
            if cand.lower() == wanted:
                return dict(palette, primary=cand, primary_text=ink), f"preferred colour {wanted} applied"
            return (dict(palette, primary=cand, primary_text=ink),
                    f"preferred colour {wanted} adjusted to {cand} to reach AA contrast")
    return palette, f"preferred colour {wanted} could not meet AA contrast, so the style palette was kept"


def theme_input(spec: dict | None) -> dict:
    """The brief's theme, with the brief's preferred colour folded into it.

    One colour path rather than two: a typed preference becomes the theme's primary slot, so the
    theme's own AA walk decides whether it can be honoured and records what it had to move. A colour
    the customizer already set on that slot wins over the older brief preference.
    """
    value = dict((spec or {}).get("theme") or {})
    colour = str((spec or {}).get("color") or "").strip().lower()
    if _HEX.fullmatch(colour):
        colors = dict(value.get("colors") or {})
        colors.setdefault("primary", colour)
        value["colors"] = colors
    return value


def direction_for(seed: str, spec: dict | None = None) -> DesignDirection:
    """The direction for a run: style from the brief (or the seed), sections from the brief.

    A brief that carries a theme gets that theme's palette, fonts and appearance tokens on top of the
    style's composition; without one the style is drawn as designed, with the legacy colour-preference
    path.
    """
    spec = spec or {}
    style = style_for(seed, spec)
    style = design_styles.with_sections(style, _wanted_sections(style, spec))
    if spec.get("theme"):
        resolved = theme_mod.resolve(theme_input(spec))
        colour = str(spec.get("color") or "").strip().lower()
        note = ("; ".join(resolved["notes"])
                or (f"preferred colour {colour} applied through the theme" if _HEX.fullmatch(colour) else ""))
        return compose(style, palette=resolved["palette"], color_note=note,
                       tokens=theme_mod.tokens_for(resolved, style),
                       fonts=resolved["fonts"], theme_value=theme_mod.as_stored(resolved))
    palette, color_note = _recolour(style.palette, spec.get("color", ""))
    return compose(style, palette=palette, color_note=color_note)


def pick_direction(seed: str, spec: dict | None = None) -> DesignDirection:
    """Public name used by the orchestrator; `direction_for` with the same behaviour."""
    return direction_for(seed, spec)


def retheme(direction: DesignDirection, controls: dict | None, color: str = "") -> DesignDirection:
    """This run's design drawn in a different theme: the direction a theme edit writes back to state.

    The style, the section order and the brief stay exactly as they are; only what `direction_for`
    derives from a theme - palette, fonts and the appearance token map - is recomputed, so the direction
    a themed run carries after an edit is the same one it would have had if the brief had named that
    theme from the start. `ValueError` for a direction with no registry style behind it (a legacy run):
    its density and type scale have nothing to be relative to.
    """
    style = design_styles.get(direction.style_key)
    if style is None:
        raise ValueError(f"'{direction.style_key or 'legacy'}' is not a style this crew can build, "
                         f"so its theme cannot be changed in place.")
    resolved = theme_mod.resolve(theme_input({"theme": controls or {}, "color": color}))
    colour = str(color or "").strip().lower()
    note = ("; ".join(resolved["notes"])
            or (f"preferred colour {colour} applied through the theme" if _HEX.fullmatch(colour) else ""))
    return compose(style, order=direction.order, palette=resolved["palette"], color_note=note,
                   tokens=theme_mod.tokens_for(resolved, style), fonts=resolved["fonts"],
                   theme_value=theme_mod.as_stored(resolved))


def fallback() -> DesignDirection:
    """A valid direction for callers with nothing stored (runs created before this existed)."""
    return compose(STYLES[0])


def _token_overrides(value, style: Style) -> dict:
    """The stored appearance tokens that differ from this style's own - a theme's contribution.

    Only the differences are kept, so an unthemed direction round-trips to exactly the direction it was
    written from, and a stored map that a later style revision supersedes does not pin the old numbers.
    """
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, raw in value.items():
        text = str(raw or "").strip()
        if key in theme_mod.THEME_TOKEN_KEYS and theme_mod._safe_token(text) and style.tokens.get(key) != text:
            out[str(key)] = text
    return out


def _stored_fonts(value, style: Style) -> dict:
    if not isinstance(value, dict):
        return {}
    faces = {k: str(value.get(k) or "").strip() for k in ("heading", "body")}
    if not all(_FONT.fullmatch(v or "") for v in faces.values()):
        return {}
    return faces if faces != style.fonts else {}


def from_dict(value: dict | None) -> DesignDirection:
    """Read a direction back out of run state / INPUT_JSON.

    Only values declared in `styles` are accepted, because these strings are pasted into CSS by the
    page builder. The palette, fonts and appearance tokens come back with it: a themed run that is
    resumed, revised or re-published has to render the page its user approved, not the style's default
    skin. A stored legacy direction resolves through its theme; anything unrecognisable resolves to the
    fallback rather than crashing a run that is already mid-flight.
    """
    if not isinstance(value, dict):
        return fallback()
    if value.get("theme_key") and not value.get("style_key"):
        theme = _THEME_BY_KEY.get(str(value.get("theme_key", "")))
        if theme is None:
            return fallback()
        hero, features, motif, order = (value.get("hero"), value.get("features"),
                                        value.get("motif"), value.get("order"))
        if (hero not in LEGACY_HEROES or features not in LEGACY_FEATURES or motif not in LEGACY_MOTIFS
                or not isinstance(order, list) or sorted(order) != sorted(LEGACY_SECTIONS)):
            return fallback()
        return compose_legacy(theme, hero, features, motif, tuple(order))
    style = design_styles.get(str(value.get("style_key", "")))
    if style is None:
        return fallback()
    order = value.get("order")
    if (not isinstance(order, list) or not set(REQUIRED_SECTIONS) <= set(order)
            or not set(order) <= set(SECTIONS) or len(order) != len(set(order))):
        order = None
    palette = value.get("palette")
    if not (isinstance(palette, dict) and set(palette) == set(style.palette)
            and all(_HEX.fullmatch(str(v).lower()) for v in palette.values())):
        palette = None
    stored = value.get("theme")
    return compose(style, tuple(order) if order else None, palette=palette,
                   color_note=str(value.get("color_note", ""))[:400] if palette else "",
                   tokens=_token_overrides(value.get("tokens"), style), fonts=_stored_fonts(value.get("fonts"), style),
                   theme_value=stored if isinstance(stored, dict) else {})


def as_dict(d: DesignDirection) -> dict:
    out = {
        "key": d.key, "style_key": d.style_key, "theme_key": d.theme_key, "label": d.label,
        "layout_style": d.layout_style, "hero": d.hero, "nav": d.nav, "features": d.features,
        "motif": d.motif, "order": list(d.order), "radius": d.radius, "tokens": dict(d.tokens),
        "rules": list(d.rules), "notes": d.notes, "color_note": d.color_note,
        "palette": dict(d.palette), "fonts": dict(d.fonts), "theme": dict(d.theme),
    }
    return out


def fallback_dict() -> dict:
    return as_dict(fallback())


def seed_state(seed: str, spec: dict | None = None) -> dict:
    """Direction as a plain dict, ready to store on RunState.style."""
    return as_dict(direction_for(seed, spec))


def prompt_block(d: DesignDirection) -> str:
    """The DESIGN_DIRECTION block agents are given: a machine-readable line plus the rules.

    Kept on its own line so the mock provider can read it back, and appended after any
    FIXES block so a revision always reuses the same identity.
    """
    rules = " ".join(f"{r}." for r in d.rules)
    themed = (f"This run is themed - {theme_mod.describe(d.theme)}. Apply that theme globally: use the "
              f"declared custom properties for colour, spacing and type instead of hardcoding a value "
              f"on one element. " if d.theme else "")
    return (
        "\nDESIGN_DIRECTION: " + json.dumps(as_dict(d), separators=(",", ":")) + "\n"
        f'This run is built in the "{d.label}" style ({d.layout_style}). {d.notes}. '
        f'Sections after the hero, in this order: {", ".join(d.order)}. '
        f"Typography and spacing are fixed by the style: body {d.tokens['base']}, headings "
        f"{d.tokens['h1']} / {d.tokens['h2']}, letter-spacing {d.tokens['track']}, section padding "
        f"{d.tokens['pad']}, content width {d.tokens['width']}, corner radius {d.radius}. "
        f"{themed}"
        f"{rules} "
        "Use the given palette and font stacks as-is - they are already WCAG AA checked. "
        "Do not fall back to a plain centred headline with three equal cards unless this style says "
        "exactly that; every other run is built in a different style."
    )
