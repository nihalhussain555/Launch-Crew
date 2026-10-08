"""Per-run design directions, so two ideas never get the same page.

Without this the Engineer has one shape in mind (centred headline, three equal cards,
FAQ, CTA) and every launch comes out looking related. A direction is composed from
independent slots — palette/type theme, hero composition, section order, feature
layout, recurring motif — chosen from the run id, so a run keeps the same identity
across revisions while different runs almost never collide.

Every direction keeps the four sections the checks look for (hero, features, FAQ, CTA);
only their composition and order change.
"""
from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, field

HEROES = ("split", "centered", "band", "rail")
FEATURE_LAYOUTS = ("grid", "numbered", "checklist", "bento")
MOTIFS = ("rules", "glow", "pills", "circles")
SECTIONS = ("features", "faq", "cta")          # always all four; only the order varies

HERO_NOTES = {
    "split": "copy in the left column, a framed visual in the right",
    "centered": "centred stack with the button on its own line",
    "band": "full-width tinted band with an oversized headline",
    "rail": "brand and navigation rail down the left edge, headline beside it",
}
FEATURE_NOTES = {
    "grid": "equal cards in a wrapping grid",
    "numbered": "stacked rows led by large numerals",
    "checklist": "two-column list with tick marks",
    "bento": "one wide panel above a pair of smaller ones",
}
MOTIF_NOTES = {
    "rules": "hairline rules under headings and between rows",
    "glow": "soft shadow and a thin ring around every panel",
    "pills": "pill-shaped headings and badges",
    "circles": "circular dot markers on each card",
}

# Every ordering of the three sections after the hero.
ORDERS = (
    ("features", "faq", "cta"), ("features", "cta", "faq"), ("faq", "features", "cta"),
    ("faq", "cta", "features"), ("cta", "features", "faq"), ("cta", "faq", "features"),
)

SYSTEM_BODY = "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif"


@dataclass(frozen=True)
class Theme:
    """Palette + type for a direction. Colours are WCAG AA checked by the Design schema."""
    key: str
    label: str
    layout_style: str
    radius: str
    palette: dict = field(repr=False)
    fonts: dict = field(repr=False)


THEMES: tuple[Theme, ...] = (
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
_THEME_BY_KEY = {t.key: t for t in THEMES}


@dataclass(frozen=True)
class DesignDirection:
    key: str                 # stable id for this exact composition
    theme_key: str
    label: str               # shown in the run trace
    layout_style: str        # also written into Design.layout_style
    hero: str
    features: str
    motif: str
    order: tuple[str, ...]   # sections after the hero
    radius: str
    hero_note: str
    palette: dict = field(repr=False)
    fonts: dict = field(repr=False)

    def brief(self) -> str:
        """One readable line for the run trace."""
        return (f'{self.label} - hero: {self.hero}; after hero: {", ".join(self.order)}; '
                f'features: {self.features}; motif: {self.motif}; radius {self.radius}')


# ----------------------------------------------------------------- composition
_COMPOSED: dict[tuple, DesignDirection] = {}


def compose(theme: Theme, hero: str, features: str, motif: str, order: tuple[str, ...]) -> DesignDirection:
    """Build (and memoise) a direction from its slots."""
    slot = (theme.key, hero, features, motif, tuple(order))
    if slot not in _COMPOSED:
        _COMPOSED[slot] = DesignDirection(
            key=f"{theme.key}-{hero}-{features}-{motif}-{'-'.join(order)}",
            theme_key=theme.key,
            label=f"{theme.label} {hero} / {features}",
            layout_style=theme.layout_style,
            hero=hero, features=features, motif=motif, order=tuple(order), radius=theme.radius,
            hero_note=f"{HERO_NOTES[hero]}, {FEATURE_NOTES[features]}, {MOTIF_NOTES[motif]}",
            palette=dict(theme.palette), fonts=dict(theme.fonts),
        )
    return _COMPOSED[slot]


def pick_direction(seed: str) -> DesignDirection:
    """Stable direction for a run: the same seed always returns the same direction.

    crc32 rather than Python's `hash`, which is salted per process and would re-skin a run
    after a server restart. Each slot reads its own bit range, so slots vary independently
    instead of moving together.
    """
    h = zlib.crc32(seed.encode("utf-8"))
    return compose(THEMES[h % len(THEMES)], HEROES[(h >> 3) % len(HEROES)],
                   FEATURE_LAYOUTS[(h >> 5) % len(FEATURE_LAYOUTS)], MOTIFS[(h >> 7) % len(MOTIFS)],
                   ORDERS[(h >> 9) % len(ORDERS)])


def fallback() -> DesignDirection:
    """A valid direction for callers with nothing stored (runs created before this existed)."""
    return compose(THEMES[0], HEROES[0], FEATURE_LAYOUTS[1], MOTIFS[0], ORDERS[0])


def from_dict(value: dict | None) -> DesignDirection:
    """Read a direction back out of run state / INPUT_JSON.

    Anything unknown (an old run's document, a field outside the vocabulary) returns the
    fallback, because these values are pasted into CSS by the page builder.
    """
    if not isinstance(value, dict):
        return fallback()
    theme = _THEME_BY_KEY.get(str(value.get("theme_key", "")))
    if theme is None:
        return fallback()
    hero, features, motif, order = value.get("hero"), value.get("features"), value.get("motif"), value.get("order")
    if (hero not in HEROES or features not in FEATURE_LAYOUTS or motif not in MOTIFS
            or not isinstance(order, list) or sorted(order) != sorted(SECTIONS)):
        return fallback()
    return compose(theme, hero, features, motif, tuple(order))


def as_dict(d: DesignDirection) -> dict:
    return {
        "key": d.key, "theme_key": d.theme_key, "label": d.label, "layout_style": d.layout_style,
        "hero": d.hero, "features": d.features, "motif": d.motif, "order": list(d.order),
        "radius": d.radius, "hero_note": d.hero_note, "palette": dict(d.palette), "fonts": dict(d.fonts),
    }


def fallback_dict() -> dict:
    return as_dict(fallback())


def seed_state(seed: str) -> dict:
    """Direction as a plain dict, ready to store on RunState.style."""
    return as_dict(pick_direction(seed))


def prompt_block(d: DesignDirection) -> str:
    """The DESIGN_DIRECTION block agents are given: a machine-readable line plus the rules.

    Kept on its own line so the mock provider can read it back, and appended after any
    FIXES block so a revision always reuses the same identity.
    """
    return (
        "\nDESIGN_DIRECTION: " + json.dumps(as_dict(d), separators=(",", ":")) + "\n"
        f'This run\'s design identity is "{d.label}" ({d.layout_style}): {d.hero_note}. '
        f'Sections after the hero, in this order: {", ".join(d.order)}. Corner radius {d.radius}. '
        "Use the given palette and font stacks as-is - they are already WCAG AA checked. "
        "Do not fall back to a plain centred headline with three equal cards: every other run "
        "uses a different direction, and this page must look like this one."
    )
