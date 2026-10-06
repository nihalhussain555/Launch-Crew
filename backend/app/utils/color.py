"""WCAG colour maths (pure functions, no dependencies)."""
import re

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def relative_luminance(rgb) -> float:
    def chan(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg, bg) -> float:
    """WCAG contrast ratio between two (r,g,b) tuples or hex strings."""
    if isinstance(fg, str):
        fg = hex_to_rgb(fg)
    if isinstance(bg, str):
        bg = hex_to_rgb(bg)
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def is_large_text(font_px: float, bold: bool) -> bool:
    """WCAG 'large text': >=24px, or >=18.66px (14pt) and bold."""
    return font_px >= 24 or (bold and font_px >= 18.66)


def passes_aa(fg, bg, font_px: float = 16, bold: bool = False) -> bool:
    need = 3.0 if is_large_text(font_px, bold) else 4.5
    return contrast_ratio(fg, bg) >= need
