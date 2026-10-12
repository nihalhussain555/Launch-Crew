"""Design tokens: the theme a project is *drawn in*, kept deliberately separate from the style that
lays it out.

`app/agents/styles.py` owns structure - hero composition, navigation, feature layout, motif. This
module owns appearance: colour, typography, spacing rhythm, corner radius, shadow, button and card
treatment. The split is what lets a user re-theme a site without the twelve styles collapsing into one
template with a different background colour: **a theme can never change a layout slot**, and a style
change can never quietly discard the colours the user picked.

Everything here is deterministic and dependency-free, so the whole customizer is testable offline:

* A theme is edited through six colour slots (background, surface, text, primary, secondary, accent).
  Everything else - readable button labels, muted text, hairlines, tinted bands - is *derived* from
  those six by `derive()`, so a user cannot create a palette with an unreadable button label by
  accident, and there are not twelve values to keep consistent by hand.
* `ensure_aa()` then walks the pairs `Design._contrast` rejects the run over and pushes any failing
  colour towards a readable one, recording what it changed. A theme is therefore always valid; the
  notes tell the user which of their choices had to move and why.
* Non-colour tokens are plain CSS strings (units included) validated against `_CSS_VALUE`, because
  they are pasted straight into the page's `:root` block by `app/llm/mock.py`.

A resolved theme is stored as a plain dict (on a saved theme document, on `project.spec["theme"]`, and
inside the run's design direction) so it survives Mongo round-trips and old runs without a migration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from app.agents import styles as design_styles
from app.utils.color import contrast_ratio, hex_to_rgb, mix, relative_luminance

# ----------------------------------------------------------------- colour slots
# The six the user edits. `secondary` and the derived keys are not editable directly: they follow.
COLOR_SLOTS = ("background", "surface", "text", "primary", "secondary", "accent")
# The seven keys `schemas.Palette` (and therefore `Design`) requires.
PALETTE_KEYS = ("background", "surface", "text", "muted_text", "primary", "primary_text", "accent")

HEX = re.compile(r"^#[0-9a-f]{6}$")
# A token value is pasted into CSS, so: lengths, unitless numbers, clamp()/calc(), keywords, font
# stacks. Anything with a brace, semicolon, angle bracket or quote-escape is refused.
_CSS_VALUE = re.compile(r"^[A-Za-z0-9 ,.%#()'\"/-]{0,160}$")
_FORBIDDEN = re.compile(r"</|<script|url\s*\(\s*data:|expression\(|javascript:", re.I)

AA_TEXT = 4.5           # WCAG AA for body text; Design._contrast enforces the same number
_LARGE_TEXT = 3.0

# Pairs the accessibility check cares about: (label, foreground slot, background slot, minimum)
CONTRAST_PAIRS = (("body text on page", "text", "background", AA_TEXT),
                  ("body text on panels", "text", "surface", AA_TEXT),
                  ("secondary text on page", "muted_text", "background", AA_TEXT),
                  ("secondary text on panels", "muted_text", "surface", AA_TEXT),
                  ("button label", "primary_text", "primary", AA_TEXT),
                  ("accent on panels", "accent", "surface", AA_TEXT))


def is_hex(value: str) -> bool:
    return bool(HEX.fullmatch(str(value or "").strip().lower()))


def _ink_for(bg: str) -> str:
    """The label colour that reads best on this fill: white or near-black, by measured contrast."""
    return _best_ink(bg)[0]


def _best_ink(bg: str) -> tuple[str, float]:
    light, dark = "#ffffff", "#0d1117"
    rl, rd = contrast_ratio(light, bg), contrast_ratio(dark, bg)
    return (light, rl) if rl >= rd else (dark, rd)


def _canvas_for(hexc: str, ink: str, minimum: float = AA_TEXT) -> str:
    """Push a background until one specific text colour reads on it, changing it as little as possible.

    Mixing towards the opposite pole of `ink` always succeeds (pure black and pure white are 19:1 apart),
    which is what makes the repair loop terminate instead of stalling on a mid-tone.
    """
    if contrast_ratio(ink, hexc) >= minimum:
        return hexc
    away = "#000000" if ink == "#ffffff" else "#ffffff"
    for step in range(1, 21):
        cand = mix(hexc, away, step / 20)
        if contrast_ratio(ink, cand) >= minimum:
            return cand
    return cand


def _ensure_canvas(hexc: str, minimum: float = AA_TEXT) -> str:
    """Push a background away from the mid-tone until *some* text colour clears AA on it.

    A canvas around 50% grey admits neither white nor black at 4.5:1, so no foreground choice can
    rescue it; the page itself has to become decisively light or decisively dark.
    """
    return _canvas_for(hexc, _best_ink(hexc)[0], minimum)


def _towards(fg: str, bg: str, minimum: float) -> str:
    """Nudge `fg` towards the readable ink for `bg` until it clears `minimum`.

    The pole is measured, not guessed from luminance: a mid-tone background is closer to black's
    contrast ceiling than to white's, and picking the wrong pole here is how a repair loop stalls at
    3:1 and gives up.
    """
    if contrast_ratio(fg, bg) >= minimum:
        return fg
    ink = _best_ink(bg)[0]
    if contrast_ratio(ink, bg) < minimum:
        return fg          # the *background* is unreadable at any text colour; only `_canvas_for` fixes that
    for step in range(1, 21):
        cand = mix(fg, ink, step / 20 * 0.95)
        if contrast_ratio(cand, bg) >= minimum:
            return cand
    return ink


def _towards_all(fg: str, canvases: tuple[str, ...], minimum: float, ink: str) -> str:
    """Move a foreground until it clears `minimum` on every canvas it is read on.

    Body text sits on the page *and* on panels, and the two are usually a shade apart, so a colour
    repaired against one alone can break the other - the ping-pong this avoids.
    """
    if all(contrast_ratio(fg, c) >= minimum for c in canvases):
        return fg
    for step in range(1, 21):
        cand = mix(fg, ink, step / 20 * 0.95)
        if all(contrast_ratio(cand, c) >= minimum for c in canvases):
            return cand
    return ink


def derive(colors: dict) -> dict:
    """The full palette: the six editable slots plus everything computed from them.

    `muted_text` is the text colour pulled towards the page colour, `border`/`band` are hairline and
    panel tints from the same pair, and each button label is the ink that reads on its fill - so a
    user changing one accent never has to reason about five dependent values.
    """
    base = {k: str(colors.get(k) or "").strip().lower() for k in COLOR_SLOTS}
    missing = [k for k, v in base.items() if not is_hex(v)]
    if missing:
        raise ValueError(f"need a six-digit hex colour for: {', '.join(missing)}")
    background, surface, text = base["background"], base["surface"], base["text"]
    # A 38% pull towards the page colour reads as "secondary" but can land under AA on its own - a
    # pale page makes pale grey text. Clamp it against both surfaces so a derived slot can never be
    # the reason a run is rejected, whichever six colours the user picked.
    muted = mix(text, background, 0.38)
    muted = _towards_all(muted, (background, surface), AA_TEXT, _best_ink(background)[0])
    return {
        **base,
        "muted_text": muted,
        "primary_text": _ink_for(base["primary"]),
        "secondary_text": _ink_for(base["secondary"]),
        "accent_text": _ink_for(base["accent"]),
        "border": mix(text, background, 0.16),
        "band": mix(background, surface, 0.55),
    }


def palette_of(derived: dict) -> dict:
    """The seven-key palette the Designer's schema and the direction contract expect."""
    return {k: derived[k] for k in PALETTE_KEYS}


def contrast_report(derived: dict) -> list[dict]:
    """Every checked pair with its ratio and verdict - what the UI shows as the contrast panel."""
    return [{"pair": label, "foreground": derived[fg], "background": derived[bg],
             "ratio": round(contrast_ratio(derived[fg], derived[bg]), 2), "minimum": need,
             "passes": contrast_ratio(derived[fg], derived[bg]) >= need}
            for label, fg, bg, need in CONTRAST_PAIRS]


def ensure_aa(derived: dict) -> tuple[dict, list[str]]:
    """Repair a palette until `Design._contrast` would accept it, saying what moved.

    The order matters and is the whole point of this function. Text has to read on the page *and* on
    the panels with one colour, so a per-pair nudge can undo the pair it just fixed - the loop used to
    ping-pong between them forever. Instead the canvas pair is made coherent first (both backgrounds on
    the same light/dark pole, one shared text ink), and only then is each editable colour pulled up to
    AA. Every move afterwards is monotone: body text only ever moves towards the pole, which raises its
    contrast on both canvases at once, so the pairs converge in a pass or two rather than oscillating.
    """
    editable = {k: derived[k] for k in COLOR_SLOTS}
    notes: list[str] = []

    def note(text: str) -> None:
        if text not in notes:
            notes.append(text)

    for slot in ("background", "surface"):
        fixed = _ensure_canvas(editable[slot])
        if fixed != editable[slot]:
            note(f"{slot} was a mid-tone no text colour could read on, so it moved from "
                 f"{editable[slot]} to {fixed}")
            editable[slot] = fixed

    # One body text colour must serve both canvases, so they cannot sit on opposite poles. The page
    # wins that argument - it is the larger area - and the panel colour follows it.
    pole = _best_ink(editable["background"])[0]
    surface = _canvas_for(editable["surface"], pole)
    if surface != editable["surface"]:
        note(f"panels sat on the opposite light/dark pole to the page, so surface moved from "
             f"{editable['surface']} to {surface} for one readable body text colour")
        editable["surface"] = surface
    # The page itself must accept the pole it chose, even if its own best ink was the other one.
    background = _canvas_for(editable["background"], pole)
    if background != editable["background"]:
        note(f"background moved from {editable['background']} to {background} to carry the page's "
             f"body text at {AA_TEXT}:1")
        editable["background"] = background

    canvases = (editable["background"], editable["surface"])
    for _ in range(6):
        current = derive(editable)
        failing = [p for p in contrast_report(current) if not p["passes"]]
        if not failing:
            return current, notes
        pair = failing[0]
        label, fg_key, bg_key, need = next(c for c in CONTRAST_PAIRS if c[0] == pair["pair"])
        if fg_key in ("text", "muted_text"):
            # Both body-text pairs share one editable slot; fix it against both canvases at once.
            moved = _towards_all(editable["text"], canvases, need, pole)
            if moved != editable["text"]:
                note(f"{label} was {pair['ratio']}:1 - text moved from {editable['text']} to "
                     f"{moved} to reach {need}:1")
                editable["text"] = moved
                continue
        elif fg_key == "primary_text":
            # The label is derived from the fill, so the fill is the only thing that can move.
            moved = _canvas_for(editable["primary"], current["primary_text"], need)
            if moved != editable["primary"]:
                note(f"{label} was {pair['ratio']}:1 - primary moved from {editable['primary']} to "
                     f"{moved} so its button label reaches {need}:1")
                editable["primary"] = moved
                continue
        else:
            moved = _towards(editable[fg_key], current[bg_key], need)
            if moved != editable[fg_key]:
                note(f"{label} was {pair['ratio']}:1 - {fg_key} moved from {editable[fg_key]} to "
                     f"{moved} to reach {need}:1")
                editable[fg_key] = moved
                continue
        break  # nothing left that can move: report the shortfall instead of spinning

    current = derive(editable)
    still = [p["pair"] for p in contrast_report(current) if not p["passes"]]
    if still:
        note("could not reach AA on " + ", ".join(still)
             + " - the closest readable colours were kept")
    return current, notes


# ----------------------------------------------------------------- non-colour tokens
@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    blurb: str
    tokens: dict = field(repr=False, default_factory=dict)


def _px(value: str) -> float:
    m = re.match(r"^(-?[\d.]+)px$", str(value).strip())
    return float(m.group(1)) if m else 0.0


def _set_px(value: str, amount: float) -> str:
    return f"{round(_px(value) * amount, 2):g}px" if "px" in str(value) else value


def scale_sizes(tokens: dict, factor: float) -> dict:
    """Multiply every type size in a token map: the font-scale control, applied in Python so the page
    still carries plain px/clamp() values a browser check can measure."""
    out = dict(tokens)
    for key in ("base", "lh", "h1", "h2", "h3", "small", "btn_min"):
        value = str(out.get(key) or "")
        if key == "lh":
            out[key] = f"{round(float(value) * (1 + (factor - 1) * 0.4), 3):g}"
        else:
            out[key] = re.sub(r"(-?[\d.]+)px", lambda m: f"{round(float(m.group(1)) * factor, 1):g}px", value)
    return out


DENSITIES: tuple[Preset, ...] = (
    Preset("compact", "Compact", "Tight rhythm for dense, information-heavy pages.",
           {"space": 0.78}),
    Preset("normal", "Normal", "The rhythm the styles were designed at.", {"space": 1.0}),
    Preset("roomy", "Roomy", "Long pauses between sections; suits a statement page.",
           {"space": 1.28}),
)
WIDTHS: tuple[Preset, ...] = (
    Preset("narrow", "Narrow", "One comfortable reading measure (820px).", {"width": "820px"}),
    Preset("default", "Default", "The style's own content width.", {}),
    Preset("wide", "Wide", "Room for side-by-side panels (1240px).", {"width": "1240px"}),
    Preset("full", "Full bleed", "Almost edge to edge (1440px).", {"width": "1440px"}),
)
RADII: tuple[Preset, ...] = (
    Preset("square", "Square", "0px corners, hard edges.", {"radius": "0px", "art_radius": "0px"}),
    Preset("subtle", "Subtle", "6px corners.", {"radius": "6px", "art_radius": "8px"}),
    Preset("rounded", "Rounded", "14px corners.", {"radius": "14px", "art_radius": "16px"}),
    Preset("soft", "Soft", "22px corners.", {"radius": "22px", "art_radius": "26px"}),
    Preset("pill", "Pill", "Fully rounded controls.", {"radius": "999px", "art_radius": "32px"}),
)
SHADOWS: tuple[Preset, ...] = (
    Preset("none", "None", "No shadows; separation comes from rules and colour.",
           {"shadow": "none", "shadow_strong": "none"}),
    Preset("soft", "Soft", "One low, wide shadow.",
           {"shadow": "0 1px 2px rgba(16,24,40,.06), 0 8px 24px rgba(16,24,40,.08)",
            "shadow_strong": "0 2px 4px rgba(16,24,40,.08), 0 16px 40px rgba(16,24,40,.14)"}),
    Preset("medium", "Medium", "A clearer lift off the page.",
           {"shadow": "0 2px 6px rgba(16,24,40,.10), 0 12px 28px rgba(16,24,40,.12)",
            "shadow_strong": "0 6px 12px rgba(16,24,40,.12), 0 24px 48px rgba(16,24,40,.18)"}),
    Preset("strong", "Strong", "Deep shadow, high separation.",
           {"shadow": "0 8px 16px rgba(12,18,30,.18), 0 24px 48px rgba(12,18,30,.22)",
            "shadow_strong": "0 16px 32px rgba(12,18,30,.24), 0 40px 80px rgba(12,18,30,.30)"}),
    Preset("hard", "Hard offset", "No blur - a printed, brutalist shadow.",
           {"shadow": "4px 4px 0 0 currentColor", "shadow_strong": "8px 8px 0 0 currentColor"}),
)
BUTTONS: tuple[Preset, ...] = (
    Preset("solid", "Solid", "Filled with the primary colour.",
           {"btn_bg": "var(--primary)", "btn_fg": "var(--on-primary)", "btn_border": "0 solid transparent"}),
    Preset("outline", "Outline", "Transparent with a primary border.",
           {"btn_bg": "transparent", "btn_fg": "var(--primary)", "btn_border": "2px solid var(--primary)"}),
    Preset("soft", "Soft", "A tinted fill instead of the full-strength primary.",
           {"btn_bg": "var(--band)", "btn_fg": "var(--text)", "btn_border": "1px solid var(--line)"}),
    Preset("pill", "Pill", "Solid and fully rounded.",
           {"btn_bg": "var(--primary)", "btn_fg": "var(--on-primary)", "btn_border": "0 solid transparent",
            "btn_radius": "999px"}),
    Preset("sharp", "Sharp", "Solid, square, uppercase.",
           {"btn_bg": "var(--primary)", "btn_fg": "var(--on-primary)", "btn_border": "0 solid transparent",
            "btn_radius": "0px", "btn_case": "uppercase"}),
)
CARDS: tuple[Preset, ...] = (
    Preset("filled", "Filled", "A solid surface panel.",
           {"card_bg": "var(--surface)", "card_border": "0 solid transparent", "card_shadow": "var(--shadow)"}),
    Preset("outlined", "Outlined", "A hairline border, no shadow.",
           {"card_bg": "var(--surface)", "card_border": "1px solid var(--line)", "card_shadow": "none"}),
    Preset("elevated", "Elevated", "Filled and lifted with the strong shadow.",
           {"card_bg": "var(--surface)", "card_border": "0 solid transparent", "card_shadow": "var(--shadow-strong)"}),
    Preset("glass", "Glass", "Translucent panel with a blur - for overlays and feature panels only.",
           {"card_bg": "color-mix(in srgb, var(--surface) 68%, transparent)",
            "card_border": "1px solid var(--line)", "card_shadow": "var(--shadow)",
            "card_blur": "blur(10px)"}),
    Preset("flat", "Flat", "No fill, no border: content sits on the page.",
           {"card_bg": "transparent", "card_border": "0 solid transparent", "card_shadow": "none"}),
)
PRESETS: dict[str, tuple[Preset, ...]] = {
    "density": DENSITIES, "width": WIDTHS, "radius": RADII, "shadow": SHADOWS,
    "button": BUTTONS, "card": CARDS,
}
SCALE_MIN, SCALE_MAX = 0.85, 1.25


def preset_key(group: str, key: str) -> str:
    """A preset key validated against its group, or "" when unknown (the theme then keeps the style's
    own value rather than substituting something the user did not ask for)."""
    return key if any(p.key == key for p in PRESETS.get(group, ())) else ""


def preset_tokens(group: str, key: str) -> dict:
    return next((dict(p.tokens) for p in PRESETS.get(group, ()) if p.key == key), {})


def preset_cards(group: str) -> list[dict]:
    return [{"key": p.key, "label": p.label, "blurb": p.blurb} for p in PRESETS.get(group, ())]


# ----------------------------------------------------------------- typography
@dataclass(frozen=True)
class Pairing:
    key: str
    label: str
    blurb: str
    heading: str
    body: str


# System font stacks only: the sanitizer removes every <link>, so a web font could not load, and a
# stack that names a font nobody has is a silent downgrade to the browser default.
PAIRINGS: tuple[Pairing, ...] = (
    Pairing("grotesk", "Grotesk / system", "Neutral, modern, safe on every OS.",
            "'Helvetica Neue', Helvetica, Arial, sans-serif", design_styles.SYSTEM_BODY),
    Pairing("humanist", "Humanist / system", "Warmer letterforms, very readable at small sizes.",
            "'Segoe UI', 'Helvetica Neue', Arial, sans-serif", design_styles.SYSTEM_BODY),
    Pairing("editorial", "Serif display / serif body", "Bookish and calm; suits long copy.",
            "'Palatino Linotype', Palatino, Georgia, serif", "Georgia, 'Times New Roman', serif"),
    Pairing("contrast", "Serif display / sans body", "The classic editorial pairing.",
            "Georgia, 'Times New Roman', serif", design_styles.SYSTEM_BODY),
    Pairing("mono", "Monospace / monospace", "Technical, terminal-grade signal.",
            "'Courier New', Consolas, monospace", "'Courier New', Consolas, monospace"),
    Pairing("mono_soft", "Monospace display / sans body", "Code-flavoured headings over readable copy.",
            "Consolas, 'Lucida Console', monospace", design_styles.SYSTEM_BODY),
    Pairing("statement", "Impact display / sans body", "One loud headline face, quiet body.",
            "Impact, 'Arial Black', 'Segoe UI', sans-serif", design_styles.SYSTEM_BODY),
    Pairing("friendly", "Rounded / system", "Soft, approachable product pages.",
            "'Arial Rounded MT Bold', 'Segoe UI', Arial, sans-serif", design_styles.SYSTEM_BODY),
)
PAIRING_BY_KEY = {p.key: p for p in PAIRINGS}


def pairing_cards() -> list[dict]:
    return [{"key": p.key, "label": p.label, "blurb": p.blurb,
             "heading": p.heading, "body": p.body} for p in PAIRINGS]


# ----------------------------------------------------------------- curated palettes
@dataclass(frozen=True)
class Family:
    key: str
    label: str
    blurb: str
    light: dict = field(repr=False)
    dark: dict = field(repr=False)
    pairing: str = "grotesk"
    radius: str = "rounded"
    density: str = "normal"
    width: str = "default"
    shadow: str = "soft"
    button: str = "solid"
    card: str = "filled"
    scale: float = 1.0


FAMILIES: tuple[Family, ...] = (
    Family("minimalist", "Minimalist", "Near-white paper, one graphite accent, nothing else.",
           {"background": "#FAFAF9", "surface": "#FFFFFF", "text": "#1C1917",
            "primary": "#1F2937", "secondary": "#57534E", "accent": "#B45309"},
           {"background": "#111110", "surface": "#1B1B1A", "text": "#F5F4F1",
            "primary": "#E7E5E4", "secondary": "#A8A29E", "accent": "#F59E0B"},
           pairing="grotesk", radius="subtle", density="roomy", shadow="none", button="solid",
           card="outlined", scale=0.98),
    Family("corporate", "Corporate", "Cool paper, dependable blue, clear hierarchy.",
           {"background": "#F5F7FA", "surface": "#FFFFFF", "text": "#111C2E",
            "primary": "#1D4ED8", "secondary": "#0F766E", "accent": "#B45309"},
           {"background": "#0C1524", "surface": "#16223A", "text": "#EAF1FA",
            "primary": "#7CB2FF", "secondary": "#5EEAD4", "accent": "#FBBF24"},
           pairing="humanist", radius="subtle", density="normal", shadow="soft", button="solid",
           card="filled", scale=1.0),
    Family("luxury", "Luxury", "Ink and champagne, serif display, wide spacing.",
           {"background": "#F7F3EA", "surface": "#FFFFFF", "text": "#1A1710",
            "primary": "#8A6A1F", "secondary": "#4B3B12", "accent": "#831843"},
           {"background": "#101014", "surface": "#191920", "text": "#F4F0E6",
            "primary": "#C9A227", "secondary": "#8A7420", "accent": "#D9CBA3"},
           pairing="editorial", radius="square", density="roomy", shadow="none", button="outline",
           card="outlined", scale=0.97),
    Family("creative", "Creative", "Paper white, poster-black buttons, one saturated rose.",
           {"background": "#FFFFFF", "surface": "#F2F1EC", "text": "#111111",
            "primary": "#141414", "secondary": "#7C3AED", "accent": "#C2185B"},
           {"background": "#131018", "surface": "#1E1928", "text": "#F6F2FF",
            "primary": "#F6F2FF", "secondary": "#A78BFA", "accent": "#FB7185"},
           pairing="statement", radius="square", density="roomy", shadow="hard", button="sharp",
           card="flat", scale=1.06),
    Family("futuristic", "Dark futuristic", "Near-black, cyan signal, monospace accents.",
           {"background": "#EEF6FA", "surface": "#FFFFFF", "text": "#0B1B24",
            "primary": "#0E7490", "secondary": "#4338CA", "accent": "#0F766E"},
           {"background": "#070B14", "surface": "#101A2B", "text": "#E8F1FA",
            "primary": "#22D3EE", "secondary": "#7DD3C0", "accent": "#9D7BFF"},
           pairing="mono_soft", radius="subtle", density="normal", shadow="strong", button="solid",
           card="elevated", scale=1.0),
    Family("pastel", "Pastel", "Soft mint and blush, gentle contrast, rounded corners.",
           {"background": "#F4FBF7", "surface": "#FFFFFF", "text": "#132A22",
            "primary": "#0F766E", "secondary": "#DB2777", "accent": "#C2410C"},
           {"background": "#141A1E", "surface": "#1D262B", "text": "#EAF6F1",
            "primary": "#7DD3C0", "secondary": "#F9A8D4", "accent": "#FDBA74"},
           pairing="friendly", radius="soft", density="normal", shadow="soft", button="pill",
           card="filled", scale=1.02),
    Family("vibrant", "Vibrant", "High-energy primaries on white, hard shadows, big type.",
           {"background": "#FFFFFF", "surface": "#FFF4E5", "text": "#14100D",
            "primary": "#E11D48", "secondary": "#4338CA", "accent": "#0F766E"},
           {"background": "#0D0A14", "surface": "#181228", "text": "#FDF7F2",
            "primary": "#FF4D6D", "secondary": "#818CF8", "accent": "#2DD4BF"},
           pairing="humanist", radius="rounded", density="compact", shadow="hard", button="solid",
           card="elevated", scale=1.08),
)
FAMILY_BY_KEY = {f.key: f for f in FAMILIES}
MODES = ("light", "dark")


def family_cards() -> list[dict]:
    """Everything the picker needs to draw one palette family in both modes, already AA-repaired -
    so the swatch a user clicks is the palette they get, not an approximation of it."""
    out = []
    for f in FAMILIES:
        modes = {}
        for mode in MODES:
            theme = resolve({"family": f.key, "mode": mode})
            modes[mode] = {"colors": {k: theme["colors"][k] for k in COLOR_SLOTS},
                           "palette": theme["palette"], "contrast": theme["contrast"]}
        out.append({"key": f.key, "label": f.label, "blurb": f.blurb, "pairing": f.pairing,
                    "radius": f.radius, "density": f.density, "shadow": f.shadow,
                    "button": f.button, "card": f.card, "scale": f.scale, "modes": modes})
    return out


# ----------------------------------------------------------------- resolution
DEFAULT_FAMILY, DEFAULT_MODE = "corporate", "light"

# Tokens a theme is allowed to write. The style-owned layout tokens stay out of this list on purpose:
# `hero`, `nav`, `features` and `motif` are not in it because they are not tokens at all, and the
# section rhythm keys are here because spacing is exactly what the customizer is for.
THEME_TOKEN_KEYS = frozenset(design_styles.TOKEN_DEFAULTS) | {
    "space", "shadow", "shadow_strong", "radius", "card_bg", "card_border", "card_shadow", "card_blur",
    "card_radius", "card_pad", "btn_bg", "btn_fg", "btn_border", "btn_radius", "btn_shadow",
    "secondary", "secondary_text", "border", "band", "focus_ring",
}


def _clean_scale(value) -> float:
    try:
        return max(SCALE_MIN, min(SCALE_MAX, round(float(value), 3)))
    except (TypeError, ValueError):
        return 1.0


def resolve(value: dict | None = None) -> dict:
    """Turn user input into a complete, valid, AA-checked theme.

    Accepts a partial dict (what the customizer sends as the user drags a control) and fills the rest
    from the named family. Unknown keys are ignored rather than rejected: the controls send what they
    have, and a half-finished theme is still a theme. Colour and token *values* are validated, though -
    those reach CSS.
    """
    value = value if isinstance(value, dict) else {}
    family = FAMILY_BY_KEY.get(str(value.get("family") or DEFAULT_FAMILY), FAMILY_BY_KEY[DEFAULT_FAMILY])
    mode = str(value.get("mode") or "light").strip().lower()
    mode = mode if mode in MODES else "light"
    seed = dict(family.dark if mode == "dark" else family.light)

    colors = dict(seed)
    wanted_colors = value.get("colors") if isinstance(value.get("colors"), dict) else {}
    for slot in COLOR_SLOTS:
        for candidate in (wanted_colors.get(slot), value.get(slot)):
            picked = str(candidate or "").strip().lower()
            if is_hex(picked):
                colors[slot] = picked
                break
    derived, notes = ensure_aa(derive(colors))

    pairing = PAIRING_BY_KEY.get(str(value.get("pairing") or family.pairing), PAIRING_BY_KEY["grotesk"])
    scale = _clean_scale(value.get("scale", family.scale))
    groups = {g: (preset_key(g, str(value.get(g) or "")) or getattr(family, g)) for g in PRESETS}
    radius_key = groups["radius"]

    tokens: dict[str, str] = {"shadow": "none", "shadow_strong": "none", "card_blur": "none",
                              "card_radius": "", "card_pad": "", "btn_radius": "", "btn_shadow": "none",
                              "space": "1"}
    tokens.update({k: v for k, v in preset_tokens("shadow", groups["shadow"]).items()})
    tokens.update({k: v for k, v in preset_tokens("card", groups["card"]).items()})
    tokens.update({k: v for k, v in preset_tokens("button", groups["button"]).items()})
    tokens.update({k: v for k, v in preset_tokens("width", groups["width"]).items()})
    tokens.update({k: v for k, v in preset_tokens("radius", radius_key).items()})
    density = preset_tokens("density", groups["density"]).get("space", "1")
    tokens["space"] = str(density)

    fonts = {"heading": pairing.heading, "body": pairing.body}
    # `radius`, `art_radius` and `width` are page tokens, so they stay in `tokens`; they are also read out
    # here because the design direction carries the corner radius as its own field, and because a saved
    # theme has to remember the *control* the user set - `radius_key` and `width_key` - not the CSS value
    # that control produced, which is recomputed from the preset tables on every read.
    radius = str(tokens.get("radius") or "12px")
    art_radius = str(tokens.get("art_radius") or radius)
    width = str(tokens.get("width") or "")
    tokens = {k: v for k, v in tokens.items() if v != ""}

    theme = {
        "family": family.key, "mode": mode, "label": str(value.get("label") or family.label).strip()[:60],
        "colors": {k: derived[k] for k in COLOR_SLOTS},
        "derived": {k: derived[k] for k in ("muted_text", "primary_text", "secondary_text",
                                            "accent_text", "border", "band")},
        "palette": palette_of(derived),
        "fonts": fonts, "pairing": pairing.key, "scale": scale,
        # `radius` is the CSS value the page gets; `radius_key` is the control that produced it, which
        # is what a saved theme has to remember.
        "radius_key": radius_key, "radius": radius, "art_radius": art_radius,
        "tokens": tokens, "width": width, "width_key": groups["width"],
        "density": groups["density"], "shadow": groups["shadow"], "button": groups["button"],
        "card": groups["card"], "contrast": contrast_report(derived), "notes": notes,
    }
    return theme


def tokens_for(theme: dict, style: design_styles.Style) -> dict:
    """The style's own token map with this theme applied on top.

    Spacing and type scale are *relative* to the style, not absolute: a theme's density multiplies the
    padding the style was designed with, so "Compact" makes every one of the twelve styles tighter
    without flattening the differences between them.
    """
    base = dict(style.tokens)
    factor = _clean_scale(theme.get("scale", 1.0))
    space = float(theme.get("tokens", {}).get("space") or 1.0)
    base = scale_sizes(base, factor)
    if space != 1.0:
        for key in ("pad", "pad_half", "hero_pad", "gap"):
            base[key] = _set_px(base.get(key, ""), space)
    for key, value in (theme.get("tokens") or {}).items():
        if key in THEME_TOKEN_KEYS and _safe_token(value):
            base[key] = str(value)
    # The colours a theme derives but the seven-key palette cannot carry (a secondary brand colour, the
    # hairline, the tinted band) reach the page through the same token map as everything else.
    for key, source in (("secondary", (theme.get("colors") or {}).get("secondary")),
                        ("secondary_text", (theme.get("derived") or {}).get("secondary_text")),
                        ("border", (theme.get("derived") or {}).get("border"))):
        if _safe_token(source):
            base[key] = str(source)
    base["base"] = _floor_font(base.get("base", ""))
    base["small"] = _floor_font(base.get("small", ""), 12)
    return base


def _floor_font(value: str, minimum: float = 16.0) -> str:
    """Never let a scale go below the size the browser checks enforce (12px anywhere, 16px body)."""
    if not value:
        return value
    return re.sub(r"(-?[\d.]+)px", lambda m: f"{max(float(m.group(1)), minimum):g}px", value)


def _safe_token(value) -> bool:
    v = str(value or "")
    return bool(_CSS_VALUE.match(v)) and not _FORBIDDEN.search(v)


def fonts_for(theme: dict) -> dict:
    return dict(theme.get("fonts") or {})


def palette_for(theme: dict) -> dict:
    return dict(theme.get("palette") or {})


# ----------------------------------------------------------------- stored themes
THEME_NAME_MAX = 48


def clean_name(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:THEME_NAME_MAX]


def as_stored(theme: dict) -> dict:
    """What goes into the database / `spec["theme"]`: the controls a user set, nothing derived.

    Only the six colour slots and the preset keys are stored; the palette, the dependent colours, the
    token map and the contrast report are all recomputed on read. That means a later fix here (a
    stricter AA walk, a new preset, revised spacing) reaches every existing saved theme instead of
    freezing each one at the values it was created with - and a stored theme stays small enough to
    travel inside a run's spec.

    The colours are the ones `resolve()` settled on rather than the raw keystrokes, which is what the
    swatch showed the user; `notes` on the resolved theme still says what had to move and why.
    """
    return {"family": theme.get("family") or DEFAULT_FAMILY, "mode": theme.get("mode") or DEFAULT_MODE,
            "label": clean_name(theme.get("label")), "colors": dict(theme.get("colors") or {}),
            "pairing": theme.get("pairing") or "grotesk", "scale": _clean_scale(theme.get("scale", 1.0)),
            "density": theme.get("density") or "normal", "width": theme.get("width_key") or "",
            "radius": theme.get("radius_key") or "", "shadow": theme.get("shadow") or "none",
            "button": theme.get("button") or "solid", "card": theme.get("card") or "filled"}


# ------------------------------------------------------- whole-site requests, in plain English
"""Words about the *look of the whole site*, mapped onto the controls the customizer already has.

Deterministic on purpose. "Make the entire site look more premium" has one honest answer - the Luxury
family and the spacing that comes with it - and a sentence nothing matches must be refused with the
vocabulary to try, rather than answered with a theme picked at random. Every value in this table is a
registry key, so `resolve()` can never be handed an invention, and the words the UI advertises come from
the same list the matcher reads.
"""
REQUEST_RULES: tuple[tuple[tuple[str, ...], dict, str], ...] = (
    (("premium", "luxury", "luxurious", "expensive", "elegant", "sophisticated", "upscale", "classy",
      "high end", "high-end", "refined"),
     {"family": "luxury"}, "the curated Luxury palette: ink and champagne, serif display, wide spacing"),
    (("minimalist", "minimal", "clean", "simple", "understated", "spare", "quiet"),
     {"family": "minimalist"}, "the Minimalist family: near-white paper, one graphite accent, no shadows"),
    (("corporate", "professional", "business", "enterprise", "trustworthy", "banking", "consultancy"),
     {"family": "corporate"}, "the Corporate family: cool paper, dependable blue, clear hierarchy"),
    (("futuristic", "sci fi", "cyber", "neon", "space age", "technical", "developer tool"),
     {"family": "futuristic"}, "the Dark futuristic family: near-black with a cyan signal"),
    (("pastel", "soft colours", "gentle", "sweet", "friendly colours"),
     {"family": "pastel"}, "the Pastel family: mint and blush with rounded corners"),
    (("vibrant", "colourful", "colorful", "energetic", "loud", "playful", "fun", "poster"),
     {"family": "vibrant"}, "the Vibrant family: high-energy primaries, hard shadows, big type"),
    (("creative", "artistic", "design studio", "bold statement"),
     {"family": "creative"}, "the Creative family: paper white, poster-black buttons, one saturated rose"),
    (("dark", "night", "midnight", "moody", "black"), {"mode": "dark"}, "the dark palette of this family"),
    (("light", "bright", "airy", "white"), {"mode": "light"}, "the light palette of this family"),
    (("serif", "editorial", "magazine", "bookish"), {"pairing": "editorial"},
     "a serif display over a serif body"),
    (("monospace", "terminal", "code like"), {"pairing": "mono"}, "monospace headings and body"),
    (("rounded", "soft corners", "friendly corners"), {"radius": "soft"}, "22px corners across the page"),
    (("square", "sharp", "hard edges", "angular", "brutalist"), {"radius": "square"}, "0px corners"),
    (("pill", "pill buttons", "pill shaped"), {"radius": "pill"}, "fully rounded controls"),
    (("no shadow", "flat", "shadowless", "without shadows"), {"shadow": "none"},
     "no shadows; separation comes from rules and colour"),
    (("soft shadow", "subtle shadow"), {"shadow": "soft"}, "one low, wide shadow"),
    (("deep shadow", "strong shadow", "elevated", "lifted", "dramatic"), {"shadow": "strong"},
     "deep shadow, high separation"),
    (("outline buttons", "ghost buttons", "bordered buttons"), {"button": "outline"},
     "transparent buttons with a primary border"),
    (("solid buttons",), {"button": "solid"}, "buttons filled with the primary colour"),
    (("sharp buttons", "uppercase buttons"), {"button": "sharp"}, "solid, square, uppercase buttons"),
    (("outlined cards", "hairline", "bordered cards"), {"card": "outlined"}, "a hairline border, no shadow"),
    (("borderless cards", "no cards"), {"card": "flat"}, "no fill and no border"),
    (("compact", "dense", "tight", "information heavy"), {"density": "compact"},
     "a tighter rhythm for dense pages"),
    (("spacious", "roomy", "generous", "breathing room", "lots of space"), {"density": "roomy"},
     "long pauses between sections"),
    (("wide", "full width", "edge to edge", "full bleed"), {"width": "wide"},
     "a 1240px content width for side-by-side panels"),
    (("narrow", "reading width", "single column"), {"width": "narrow"}, "an 820px reading measure"),
    (("bigger text", "larger text", "big type", "large type", "larger font"), {"scale": 1.12},
     "type sizes raised by 12%"),
    (("smaller text", "smaller font", "quiet type"), {"scale": 0.92}, "type sizes lowered by 8%"),
)

# Words that are a design request but not one a token edit may answer. Saying so is the honest part:
# silently ignoring them would let a user believe the site now has frosted panels.
REQUEST_DECLINED: tuple[tuple[tuple[str, ...], str], ...] = (
    (("glass", "glassmorphism", "frosted", "blurred"),
     "A glass card style puts the effect on every panel on the page. Glass is reserved for the navbar, hero "
     "overlays and important floating elements, so it is set per component - not from a whole-site request."),
    (("gradient", "gradients"),
     "Backgrounds and bands come from the family palette; a gradient is a per-section treatment, not a token."),
)

_HEX_WORD = re.compile(r"#[0-9a-fA-F]{6}")

# A few of the words the matcher knows, for the message shown when a sentence uses none of them. The full
# list stays in REQUEST_RULES; this is the part a refusal can name without turning one line into a manual.
REQUEST_WORD_HINTS = ("premium", "minimalist", "corporate", "luxury", "dark", "light", "bold", "pastel",
                      "rounded", "square", "pill", "flat", "deep shadow", "compact", "spacious", "wide",
                      "narrow", "serif", "monospace", "bigger text")


def _word_pattern(phrase: str) -> re.Pattern:
    """One phrase as a whole-word matcher, so `art` cannot match inside `card` and `wide` cannot match `square`."""
    body = r"[\s\-]+".join(re.escape(part) for part in phrase.split())
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


_REQUEST_INDEX = [(_word_pattern(p), p, controls, why) for phrases, controls, why in REQUEST_RULES
                  for p in phrases]
_DECLINED_INDEX = [(_word_pattern(p), p, reason) for phrases, reason in REQUEST_DECLINED for p in phrases]

for _phrases, _controls, _why in REQUEST_RULES:
    for _key, _value in _controls.items():
        if _key == "family" and _value not in FAMILY_BY_KEY:
            raise RuntimeError(f"request rule names unknown family '{_value}'")
        if _key == "mode" and _value not in MODES:
            raise RuntimeError(f"request rule names unknown mode '{_value}'")
        if _key == "pairing" and _value not in PAIRING_BY_KEY:
            raise RuntimeError(f"request rule names unknown pairing '{_value}'")
        if _key in PRESETS and not preset_key(_key, _value):
            raise RuntimeError(f"request rule names unknown {_key} preset '{_value}'")
        if _key == "scale" and not SCALE_MIN <= float(_value) <= SCALE_MAX:
            raise RuntimeError(f"request rule names out-of-range scale {_value}")


def control_value_label(control: str, value) -> str:
    """The name the customizer shows for a control value, so a mapping row reads in the user's words."""
    if control == "family":
        return FAMILY_BY_KEY[value].label if value in FAMILY_BY_KEY else str(value)
    if control == "pairing":
        return PAIRING_BY_KEY[value].label if value in PAIRING_BY_KEY else str(value)
    if control in PRESETS:
        return next((p.label for p in PRESETS[control] if p.key == value), str(value))
    if control == "scale":
        return f"{_clean_scale(value):g}x type"
    return str(value)


def request_to_controls(text: str) -> dict:
    """Match a whole-site appearance request onto theme controls, and report exactly which words did it.

    The controls returned are a delta - only the keys the sentence named - so a caller can start from the
    theme the page already has and change just those. When two phrases name the same control the table's own
    precedence decides which one wins, and the losing phrase is reported under `conflicts` rather than
    quietly dropped.
    """
    text = str(text or "").lower()
    chosen: dict[str, dict] = {}
    conflicts: list[dict] = []
    for index, (pattern, phrase, controls, why) in enumerate(_REQUEST_INDEX):
        if not pattern.search(text):
            continue
        for key, value in controls.items():
            previous = chosen.get(key)
            if previous and previous["index"] < index:
                conflicts.append({"phrase": previous["phrase"], "control": key, "value": previous["value"],
                                  "instead": value, "instead_phrase": phrase})
            chosen[key] = {"phrase": phrase, "value": value, "why": why, "index": index}
    declined = [{"phrase": phrase, "reason": reason} for pattern, phrase, reason in _DECLINED_INDEX
                if pattern.search(text)]
    if _HEX_WORD.search(text):
        declined.append({"phrase": "#rrggbb",
                         "reason": "One colour in a sentence does not say which of the six slots it belongs "
                                   "to; set it with the swatches and save the theme."})
    ranked = sorted(chosen.items(), key=lambda kv: kv[1]["index"])
    controls = {key: entry["value"] for key, entry in ranked}
    resets: list[str] = []
    if "family" in controls:
        # A named family is a request for *that palette*, so the six colour slots are dropped rather than
        # carried over from the theme being left - the same rule the customizer's family cards follow.
        controls["colors"] = {}
        resets.append("colors")
    return {
        "controls": controls,
        "mapping": [{"phrase": entry["phrase"], "control": key, "value": entry["value"], "why": entry["why"],
                     "label": control_value_label(key, entry["value"])} for key, entry in ranked],
        "resets": resets,
        "conflicts": conflicts, "declined": declined, "matched": bool(chosen),
    }


def request_vocabulary() -> dict:
    """The words the matcher knows, in the order it reads them, for the UI to advertise."""
    return {"phrases": [{"phrase": p, "control": k, "value": v, "label": control_value_label(k, v)}
                        for (_pattern, p, controls, _why) in _REQUEST_INDEX for k, v in controls.items()],
            "declined": [{"phrase": p, "reason": r} for (_pattern, p, r) in _DECLINED_INDEX]}


def registry() -> dict:
    """The customizer's data source: everything the UI needs to draw its controls, in one call."""
    return {"families": family_cards(), "pairings": pairing_cards(),
            "presets": {g: preset_cards(g) for g in PRESETS},
            "colors": list(COLOR_SLOTS), "modes": list(MODES),
            "scale": {"min": SCALE_MIN, "max": SCALE_MAX, "step": 0.01},
            "default": as_stored(resolve({})),
            "requests": request_vocabulary(),
            "limits": {"name": THEME_NAME_MAX, "themes_per_user": MAX_THEMES_PER_USER}}


MAX_THEMES_PER_USER = 24


def describe(theme: dict) -> str:
    """One readable line for the run trace and the review step."""
    family = FAMILY_BY_KEY.get(theme.get("family"))
    pairing = PAIRING_BY_KEY.get(theme.get("pairing"))
    bits = [f"{theme.get('label') or (family.label if family else 'custom')}",
            f"{theme.get('mode', 'light')} {family.label if family else 'custom'} palette",
            f"{pairing.label if pairing else theme.get('pairing')}"]
    for group, word in (("density", "density"), ("radius", "corners"), ("shadow", "shadow"),
                        ("button", "buttons"), ("card", "cards")):
        # A resolved theme keeps the CSS value under the group name and the control under `*_key`; a
        # stored one only has the control. Either way the sentence should name what the user picked.
        chosen = str(theme.get(f"{group}_key") or theme.get(group) or "")
        preset = next((p for p in PRESETS.get(group, ()) if p.key == chosen), None)
        if preset:
            bits.append(f"{preset.label.lower()} {word}")
    scale = _clean_scale(theme.get("scale", 1.0))
    if abs(scale - 1.0) >= 0.02:
        bits.append(f"type scale {scale:g}x")
    return "; ".join(bits)
