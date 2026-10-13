"""One art-direction record per template: what makes twenty cards produce twenty different pages.

`styles.Style` gives the product twelve compositions. Twenty templates over twelve styles means several
cards render the same page in a different colour, which is the one thing a gallery must not do - so a look
pins the rest of the decision a studio would make per template: the palette family, how large and tight the
display type runs, which hero the copy sits in, how the feature blocks are arranged, the corner radius, and
which ornaments the page carries.

`apply()` returns a `Style` with those overrides folded in, so everything downstream - `compose`, the run
trace, `from_dict`, the theme customizer - keeps working on the same object it always did. A theme the owner
sets still wins on colour: the look is the template's default, not a lock.

`ornaments` names the extra furniture a page of this template draws on top of the composition. A record may
only list a switch `app/llm/mock.py` actually implements, so the field describes the page rather than
wishing for one. `app/agents/art.py` keys the sample photography off the same `key`.

The references this set was drawn from are named in each record's note. They describe a *genre* - cream and
serif for an architecture studio, charcoal and gold for a members' restaurant, near-black and mono for a
developer's portfolio. The markup, palettes, spacing and copy here are this codebase's own; nothing traces
another site's layout pixel for pixel, and no third-party brand mark, logo or photograph appears anywhere -
the pictures are generated for this project and captioned as samples.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.agents import styles as design_styles
from app.agents.styles import (GROTESK, HUMANIST, IMPACT, MONO, MONO_SOFT, SERIF, SERIF_DISPLAY,
                               SYSTEM_BODY, Style, T)

# The seven colours every direction carries. Written out per look rather than inherited, because a
# template's palette is most of what its card promises.
def P(background: str, surface: str, text: str, muted: str, primary: str, on_primary: str,
      accent: str) -> dict:
    return {"background": background, "surface": surface, "text": text, "muted_text": muted,
            "primary": primary, "primary_text": on_primary, "accent": accent}


@dataclass(frozen=True)
class Look:
    key: str                                   # the template key this belongs to
    label: str
    hero: str
    nav: str
    features: str
    motif: str
    radius: str
    palette: dict = field(repr=False)
    tokens: dict = field(repr=False, default_factory=dict)     # merged over the style's own
    fonts: dict = field(repr=False, default_factory=dict)      # heading/body only, system stacks
    ornaments: tuple[str, ...] = ()
    note: str = ""

    def has(self, ornament: str) -> bool:
        return ornament in self.ornaments


# h1 sizes here run past the style defaults on purpose: the demos are type-led, and a display line that
# stops at 52px is the difference between "template" and "form". Every one keeps a clamp() floor so a phone
# never wraps a headline into five lines.
LOOKS: tuple[Look, ...] = (
    Look("corporate-pro", "Corporate Pro", "split", "underline-bar", "checklist", "depth", "6px",
         P("#EDF1F5", "#FFFFFF", "#12293E", "#5A6B7B", "#1B4C6B", "#FFFFFF", "#54788A"),
         T(width="1120px", pad="72px", hero_pad="84px", h1="clamp(34px, 4.4vw, 54px)", track="-.02em",
           lh="1.6", btn_pad="0 26px"),
         {"heading": GROTESK, "body": SYSTEM_BODY}, ("stat-pills",),
         "Navy panel, white surface, one restrained accent: the consulting-firm shape."),

    Look("creative-agency", "Creative Agency", "marquee", "bracket", "spotlight", "ticker", "2px",
         P("#FFFFFF", "#F4F1EC", "#0E0E0E", "#6A6660", "#0E0E0E", "#FFFFFF", "#B94411"),
         T(width="1180px", pad="80px", hero_pad="88px", h1="clamp(44px, 8vw, 96px)", h2="clamp(30px, 5vw, 56px)",
           track="-.045em", lh="1.5", label_track=".14em", gap="14px"),
         {"heading": IMPACT, "body": GROTESK}, (),
         "Oversized black display type, one hot accent, a scrolling strip of service words."),

    Look("luxury-editorial", "Luxury Editorial", "editorial", "wide-labels", "index-table", "hairline-caps",
         "0px",
         P("#F2EFE9", "#FBFAF7", "#17150F", "#6B665C", "#17150F", "#FFFFFF", "#7B6D52"),
         T(width="1240px", pad="96px", hero_pad="104px", h1="clamp(46px, 8.4vw, 104px)", h2="clamp(28px, 4vw, 44px)",
           base="18px", lh="1.7", track="-.02em", gap="26px", label_track=".22em", art_radius="0px"),
         {"heading": SERIF_DISPLAY, "body": SERIF}, (),
         "Cream, hairline rules, a serif display line and a great deal of deliberate whitespace."),

    Look("saas-launchpad", "SaaS Launchpad", "showcase", "top-links", "bento", "glow", "14px",
         P("#0E0B1F", "#191434", "#F1EEFF", "#9C93BF", "#7C3AED", "#FFFFFF", "#C4B5FD"),
         T(width="1120px", pad="76px", hero_pad="88px", h1="clamp(38px, 6vw, 68px)", track="-.03em",
           gap="16px", btn_pad="0 24px", btn_min="48px"),
         {"heading": GROTESK, "body": SYSTEM_BODY}, (),
         "Dark violet, a centred product window, and the conversion furniture a launch page needs."),

    Look("ai-future", "AI Future", "orb", "split-links", "duo", "gridlines", "16px",
         P("#05060F", "#0D1230", "#EAF0FF", "#8A93C9", "#2563EB", "#FFFFFF", "#38BDF8"),
         T(width="1140px", pad="78px", hero_pad="92px", h1="clamp(38px, 6.2vw, 70px)", track="-.03em",
           lh="1.55", gap="18px"),
         {"heading": HUMANIST, "body": SYSTEM_BODY}, (),
         "Near-black blue, faint grid, one cool accent and a glow behind the product panel."),

    Look("developer-portfolio", "Developer Portfolio", "terminal", "index-list", "grid", "gridlines", "4px",
         P("#0A0A0A", "#131313", "#F2F2F2", "#9A9A9A", "#22C55E", "#04150A", "#22C55E"),
         T(width="1000px", pad="70px", hero_pad="80px", h1="clamp(38px, 6.6vw, 72px)", h2="clamp(26px, 3.4vw, 34px)",
           track="-.035em", lh="1.6", label_track=".16em", base="17px"),
         {"heading": GROTESK, "body": MONO_SOFT}, (),
         "Black, a visible grid, monospace furniture and one green accent doing all the signalling."),

    Look("fashion-boutique", "Fashion Boutique", "storefront", "store-bar", "products", "pills", "2px",
         P("#EFE6DA", "#FBF7F1", "#241C14", "#716252", "#1C1917", "#FFFFFF", "#8A6742"),
         T(width="1200px", pad="72px", hero_pad="72px", h1="clamp(38px, 6vw, 66px)", h2="clamp(26px, 3.6vw, 36px)",
           track="-.02em", lh="1.6", label_track=".18em", gap="18px"),
         {"heading": SERIF_DISPLAY, "body": GROTESK}, (),
         "Warm beige, an announcement strip, serif headline with a single italic-feeling accent."),

    Look("tech-store", "Tech Store", "storefront", "store-bar", "products", "rules", "10px",
         P("#F3F6F9", "#FFFFFF", "#0F1B2D", "#55637A", "#1D4ED8", "#FFFFFF", "#475569"),
         T(width="1240px", pad="64px", hero_pad="68px", h1="clamp(34px, 5vw, 58px)", track="-.02em",
           gap="16px"),
         {"heading": SERIF, "body": SYSTEM_BODY}, (),
         "Catalogue-first: a product hero, a strip of assurances, then a grid of priced items."),

    Look("beauty-lifestyle", "Beauty & Lifestyle", "band", "pill-bar", "products", "hairline-caps", "12px",
         P("#E8ECE3", "#FFFFFF", "#28321F", "#616A5C", "#4B5D45", "#FFFFFF", "#667957"),
         T(width="1160px", pad="80px", hero_pad="88px", h1="clamp(34px, 5.2vw, 58px)", base="18px", lh="1.7",
           track="-.02em", gap="20px", label_track=".2em"),
         {"heading": SERIF_DISPLAY, "body": SERIF}, (),
         "Sage and stone, soft edges, an ingredient list that reads like an index."),

    Look("restaurant-cafe", "Restaurant & Café", "split", "wide-labels", "plain-list", "hairline-caps", "2px",
         P("#121212", "#1B1A18", "#F5F1E8", "#A79E8E", "#C9A227", "#241A05", "#C9A227"),
         T(width="1120px", pad="84px", hero_pad="96px", h1="clamp(40px, 6.6vw, 72px)", h2="clamp(28px, 4vw, 40px)",
           base="18px", lh="1.7", track="-.02em", label_track=".22em"),
         {"heading": SERIF_DISPLAY, "body": SERIF}, (),
         "Charcoal and gold, a serif display line, and the menu treated as the page's main event."),

    Look("real-estate-pro", "Real Estate Pro", "split", "top-links", "products", "depth", "12px",
         P("#F6F8FC", "#FFFFFF", "#0F1B2D", "#5A6B82", "#1D5CFF", "#FFFFFF", "#0A79AA"),
         T(width="1280px", pad="60px", hero_pad="68px", h1="clamp(32px, 4.6vw, 52px)", gap="16px",
           label_track=".1em", base="17px"),
         {"heading": GROTESK, "body": SYSTEM_BODY}, (),
         "A listing interface, not a brochure: a grid of property cards with the price leading."),

    Look("healthcare-clinic", "Healthcare & Clinic", "split", "split-links", "tiles", "circles", "16px",
         P("#E9F5F8", "#FFFFFF", "#0E2A33", "#55707A", "#0C7B90", "#FFFFFF", "#247D8C"),
         T(width="1160px", pad="68px", hero_pad="76px", h1="clamp(32px, 4.8vw, 52px)", base="17px", lh="1.65",
           gap="16px"),
         {"heading": HUMANIST, "body": SYSTEM_BODY}, (),
         "Light clinical blue, rounded cards, an appointment path that stays the loudest thing on the page."),

    Look("legal-consulting", "Legal & Consulting", "editorial", "wide-labels", "tiles", "hairline-caps",
         "2px",
         P("#0B1F3A", "#132A4C", "#F1EDE4", "#A9B4C4", "#C9A24B", "#241A05", "#C9A24B"),
         T(width="1140px", pad="84px", hero_pad="96px", h1="clamp(38px, 6vw, 66px)", h2="clamp(26px, 3.8vw, 38px)",
           base="18px", lh="1.7", track="-.015em", label_track=".24em"),
         {"heading": SERIF_DISPLAY, "body": SERIF}, ("stat-pills",),
         "Deep navy, gold small-caps rules, serif headlines and a credentials row."),

    Look("edtech-academy", "EdTech Academy", "split", "top-links", "tiles", "circles", "18px",
         P("#FDF1E7", "#FFFFFF", "#1E2233", "#5D6478", "#3B4CCA", "#FFFFFF", "#9E6506"),
         T(width="1200px", pad="66px", hero_pad="76px", h1="clamp(34px, 5.2vw, 58px)", gap="16px",
           base="17px", lh="1.6"),
         {"heading": HUMANIST, "body": SYSTEM_BODY}, (),
         "Warm paper, a friendly bold headline, course cards with a clear rating and price line."),

    Look("editorial-blog", "Editorial & Blog", "masthead", "masthead-nav", "articles", "frame", "0px",
         P("#FFFFFF", "#F2F2F0", "#0A0A0A", "#575757", "#0A0A0A", "#FFFFFF", "#6B6B6B"),
         T(width="1220px", pad="72px", hero_pad="72px", h1="clamp(40px, 7vw, 84px)", h2="clamp(24px, 3vw, 32px)",
           track="-.03em", lh="1.6", label_track=".2em", gap="20px"),
         {"heading": IMPACT, "body": GROTESK}, (),
         "A magazine masthead and an article grid; typography carries the whole thing."),

    Look("events-conference", "Events & Conference", "poster", "mono-strip", "grid", "outline-thick", "4px",
         P("#0A1230", "#121B40", "#EEF2FF", "#94A3C4", "#2563EB", "#FFFFFF", "#60A5FA"),
         T(width="1180px", pad="72px", hero_pad="88px", h1="clamp(36px, 5.6vw, 62px)", gap="16px",
           label_track=".18em", base="17px"),
         {"heading": GROTESK, "body": SYSTEM_BODY}, ("stat-pills",),
         "A dark stage, an agenda that reads as a schedule, speaker cards and ticket tiers."),

    Look("startup-waitlist", "Startup Waitlist", "centered", "plain-brand", "numbered", "circles", "16px",
         P("#E6E6F8", "#F7F7FD", "#1E1B2E", "#5C5878", "#171625", "#FFFFFF", "#6755EE"),
         T(width="760px", pad="72px", hero_pad="96px", h1="clamp(40px, 6.4vw, 68px)", track="-.035em",
           lh="1.25", base="18px", cta_align="center", gap="14px"),
         {"heading": GROTESK, "body": SYSTEM_BODY}, (),
         "One narrow column, a soft glow behind it, and a single ask: your email."),

    Look("mobile-app-showcase", "Mobile App Showcase", "centered", "pill-bar", "tiles", "glow", "22px",
         P("#F1E9E0", "#FBF6F1", "#16131F", "#696275", "#16131F", "#FFFFFF", "#577506"),
         T(width="1080px", pad="72px", hero_pad="84px", h1="clamp(38px, 6vw, 66px)", track="-.03em",
           lh="1.3", gap="18px", btn_radius="999px"),
         {"heading": GROTESK, "body": SYSTEM_BODY}, ("device-frame",),
         "A warm page inside a coloured frame, pill buttons and a phone drawn in CSS."),

    Look("personal-brand", "Personal Brand", "rail", "rail-left", "plain-list", "rules", "0px",
         P("#F7F4EF", "#FFFFFF", "#111111", "#5A564F", "#111111", "#FFFFFF", "#777167"),
         T(width="1180px", pad="88px", hero_pad="96px", h1="clamp(42px, 7.4vw, 88px)", h2="clamp(26px, 3.4vw, 36px)",
           track="-.04em", lh="1.15", base="18px", gap="24px"),
         {"heading": GROTESK, "body": GROTESK}, (),
         "Off-white, a left rail, very tight very large type and one black-and-white portrait slot."),

    Look("mobile-service-center", "Mobile Service Center", "storefront", "store-bar", "tiles", "pills",
         "10px",
         P("#0F2A47", "#16395F", "#EAF2FA", "#9FB6CC", "#22C55E", "#04180A", "#38BDF8"),
         T(width="1180px", pad="64px", hero_pad="72px", h1="clamp(34px, 5.2vw, 58px)", gap="16px",
           base="17px", lh="1.6"),
         {"heading": GROTESK, "body": SYSTEM_BODY}, (),
         "Navy workshop, green call-to-action, device categories and a price list you can scan."),
)

_BY_KEY = {look.key: look for look in LOOKS}

# The switches `app/llm/mock.py` actually reads. A look may name only these: an ornament the builder
# does not draw would be a promise the page cannot keep, and the field is meant to say what a page carries.
# - stat-pills:    the page's own `stats` figures, repeated as a pill row under the hero's ask
# - device-frame:  the product preview drawn as a phone rather than a browser window
ORNAMENTS = ("stat-pills", "device-frame")

# Every slot name has to exist in the style registry, or the builder would emit a class no CSS owns.
for _look in LOOKS:
    assert _look.hero in design_styles.HEROES, f"{_look.key}: unknown hero {_look.hero}"
    assert _look.nav in design_styles.NAVS, f"{_look.key}: unknown nav {_look.nav}"
    assert _look.features in design_styles.FEATURE_LAYOUTS, f"{_look.key}: unknown features {_look.features}"
    assert _look.motif in design_styles.MOTIFS, f"{_look.key}: unknown motif {_look.motif}"
    assert set(_look.palette) == set(design_styles.STYLES[0].palette), f"{_look.key}: palette keys drifted"
    assert all(o in ORNAMENTS for o in _look.ornaments), f"{_look.key}: unknown ornament"


def get(key: str) -> Look | None:
    return _BY_KEY.get(str(key or ""))


def ornaments(design) -> tuple[str, ...]:
    """The furniture this page carries. A direction that came from a stored run knows its own look."""
    look = _BY_KEY.get(getattr(design, "look", "") or "")
    return look.ornaments if look else ()


def has(design, name: str) -> bool:
    return name in ornaments(design)


def apply(style: Style, key: str) -> tuple[Style, str]:
    """The style as this template draws it, plus the look key the direction has to carry to survive a round trip.

    Only the composition slots, the palette, the type scale and the faces change. The section order the
    brief decided stays exactly as it is, because that is the owner's content, not the template's styling.
    """
    look = _BY_KEY.get(str(key or ""))
    if look is None:
        return style, ""
    tokens = {**style.tokens, **look.tokens}
    fonts = {**style.fonts, **look.fonts}
    styled = replace(style, hero=look.hero, nav=look.nav, features=look.features, motif=look.motif,
                     radius=look.radius, palette=dict(look.palette), tokens=tokens, fonts=fonts,
                     layout_style=f"{style.layout_style} / {look.key}")
    return styled, look.key
