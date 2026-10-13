"""The twelve design styles a project can be built in, and the layout decisions each one owns.

A style is not a colour scheme. Each one fixes the hero composition, the navigation structure, the
feature layout, the recurring motif, the type scale, the spacing rhythm, the corner radius and the
extra sections it wants by default, so two styles produce different markup rather than the same
page painted differently. `app/agents/variants.py` turns a style plus a run's brief into the design
direction the Designer and Engineer actually work from, and `app/llm/mock.py` renders those slots
into a real page offline - which is what makes the difference between styles testable without API
keys.

Colours and font stacks are written so every pair the Designer's schema checks (text, muted text,
button label, accent against their backgrounds) clears WCAG AA, because that schema rejects the run
otherwise. Nothing here reaches CSS without passing through `variants.from_dict`, which only accepts
keys declared in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Sequence

SYSTEM_BODY = "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif"
SANS_BOLD = "'Trebuchet MS', 'Segoe UI', Arial, sans-serif"
GROTESK = "'Helvetica Neue', Helvetica, Arial, sans-serif"
HUMANIST = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
MONO = "'Courier New', Consolas, monospace"
MONO_SOFT = "Consolas, 'Lucida Console', monospace"
SERIF = "Georgia, 'Times New Roman', serif"
SERIF_DISPLAY = "'Palatino Linotype', Palatino, Georgia, serif"
IMPACT = "Impact, 'Arial Black', 'Segoe UI', sans-serif"

# ---------------------------------------------------------------- slot vocabularies
HEROES = ("rail", "showcase", "editorial", "band", "terminal", "split", "marquee", "storefront",
          "masthead", "poster", "centered", "orb")
NAVS = ("rail-left", "top-links", "wide-labels", "pill-bar", "index-list", "underline-bar", "bracket",
        "store-bar", "masthead-nav", "mono-strip", "plain-brand", "split-links")
FEATURE_LAYOUTS = ("plain-list", "bento", "index-table", "tiles", "grid", "checklist", "spotlight",
                   "products", "articles", "manifest", "numbered", "duo")
MOTIFS = ("rules", "glow", "hairline-caps", "blur", "gridlines", "depth", "ticker", "pills", "frame",
          "outline-thick", "circles", "orbfield")

# The hero is always first; these are the sections every page has, and what the Chromium checks look for.
REQUIRED_SECTIONS = ("features", "faq", "cta")
# Optional sections a brief can ask for. Order here is the order they may appear in, and it decides how
# a mixed list normalises, so the pairs that pre-dated these additions keep their relative order.
OPTIONAL_SECTIONS = ("about", "stats", "skills", "services", "work", "catalog", "preview", "timeline",
                     "testimonials", "pricing", "gallery", "team", "visit", "booking", "contact")
SECTION_KEYS = REQUIRED_SECTIONS + OPTIONAL_SECTIONS

# What a section carries, in the words the gallery and the wizard show. The page builder renders each of
# these as its own markup, so this is a description of real content, not a label for one generic block.
SECTION_INFO = {
    "about": ("About", "an intro paragraph, the facts a buyer checks, and the credentials behind them"),
    "stats": ("By the numbers", "large figures with a label each, for track record and scale"),
    "skills": ("Skills", "grouped capability lists - what the work actually uses"),
    "services": ("Services", "each service with what it covers and its lead time or price-from line"),
    "work": ("Selected work", "case rows: the client, the brief, the outcome and one measure"),
    "catalog": ("Catalogue", "items with a note, a price or spec line and a category tag - products, "
                             "menu items, courses, listings, articles"),
    "preview": ("Product preview", "a CSS-drawn window or phone frame with captioned pointers at it"),
    "timeline": ("Schedule", "dated rows - an agenda, a learning path, a career history, announcements"),
    "testimonials": ("Testimonials", "quotes with attributions, each marked when the crew wrote it"),
    "pricing": ("Plans", "a tier row with prices, what is included and one emphasised plan"),
    "gallery": ("Gallery", "captioned panels drawn in CSS, for work samples and product views"),
    "team": ("People", "the roles on the page - founders, practitioners, instructors, speakers"),
    "visit": ("Find us", "the address, the opening hours as rows, and how to get there"),
    "booking": ("Book", "a validated form for a reservation, appointment, consultation or place"),
    "contact": ("Contact", "the email, phone and location the brief supplied, and nothing invented"),
    "features": ("Features", "what the product does, laid out the way the style lays features out"),
    "faq": ("FAQ", "the questions a first-time visitor asks, as expandable rows"),
    "cta": ("Call to action", "the closing pitch with the email capture form"),
}

HERO_NOTES = {
    "rail": "brand and vertical navigation rail down the left edge of the hero, headline block beside it",
    "showcase": "headline and subline above a framed product window (CSS-drawn browser chrome, no images)",
    "editorial": "two columns: a narrow label column with the section index, a wide display headline beside it",
    "band": "full-bleed tinted band, oversized headline left-aligned inside it, one thin accent rule",
    "terminal": "monospace prompt line above a block headline, hairline grid beneath",
    "split": "copy in the left column, a framed abstract visual in the right",
    "marquee": "one oversized headline running past a horizontal strip of topic chips",
    "storefront": "promo bar across the top of the hero, then category tiles beside the headline",
    "masthead": "publication masthead: brand name centred over a double rule, issue line under it",
    "poster": "giant uppercase headline in a thick bordered panel, links as a hard strip below",
    "centered": "centred badge, headline, subline and two buttons on one axis",
    "orb": "headline offset to one side over layered CSS gradient shapes (no text over a gradient)",
}

NAV_NOTES = {
    "rail-left": "vertical link list inside the hero rail, brand at its head",
    "top-links": "brand left, links right on one bar",
    "wide-labels": "brand centred, links as widely letter-spaced uppercase labels beneath",
    "pill-bar": "links wrapped in a single bordered pill container",
    "index-list": "numbered links (01, 02, 03) in a monospace strip",
    "underline-bar": "full-width bar with a bottom border, links right-aligned and underlined",
    "bracket": "brand in square brackets, links separated by vertical bars",
    "store-bar": "brand, category links, plus a highlighted account chip at the far right",
    "masthead-nav": "brand as the masthead itself, links in a row under a rule",
    "mono-strip": "monospace uppercase links separated by double slashes",
    "plain-brand": "brand only in the bar; links sit under the headline as a quiet row",
    "split-links": "two link groups divided by a vertical rule",
}

FEATURE_NOTES = {
    "plain-list": "title and description as wide-spaced rows with hairline separators, no boxes",
    "bento": "one wide panel above a pair of smaller ones",
    "index-table": "two-column definition rows: term on the left, description on the right",
    "tiles": "square tiles in an even grid, each with a short label",
    "grid": "equal cards in a wrapping grid",
    "checklist": "two-column list with tick marks",
    "spotlight": "first feature full-width and large, the rest stacked as rows beside a rule",
    "products": "cards with a label row, title, description and a price-style chip",
    "articles": "list rows with a kicker, a title and an excerpt, aligned to a text baseline grid",
    "manifest": "uppercase numbered list with large numerals and thick rules between rows",
    "numbered": "stacked rows led by large numerals",
    "duo": "one tall panel beside a column of shorter stacked panels",
}

MOTIF_NOTES = {
    "rules": "hairline rules under headings and between rows",
    "glow": "soft shadow and a thin ring around every panel",
    "hairline-caps": "uppercase letter-spaced labels and one thin rule, no boxes",
    "blur": "translucent panels with a background blur over a tinted field",
    "gridlines": "faint background grid lines behind section headings",
    "depth": "layered shadows and a slight lift on panels",
    "ticker": "bordered strips of chips used as dividers between sections",
    "pills": "pill-shaped headings and badges",
    "frame": "double border / inset frame around panels",
    "outline-thick": "thick solid outlines with hard offset shadows, square corners",
    "circles": "circular dot markers on each card",
    "orbfield": "radial gradient shapes as background decoration, never behind text",
}

# Every token is pasted straight into CSS, so they are strings with units and nothing else.
TOKEN_DEFAULTS = {
    "width": "1040px",      # .wrap max-width
    "pad": "60px",          # section padding top/bottom
    "pad_half": "30px",
    "hero_pad": "64px",
    "gap": "18px",          # grid gaps
    "base": "17px",         # body size (never below 16px)
    "lh": "1.65",
    "h1": "clamp(32px, 5vw, 52px)",
    "h2": "clamp(25px, 3.6vw, 34px)",
    "h3": "20px",
    "small": "13px",        # never below the 12px the browser check allows
    "track": "-.01em",
    "h1_case": "none",
    "h2_case": "none",
    "label_case": "uppercase",
    "label_track": ".14em",
    "btn_case": "none",
    "btn_pad": "0 26px",
    "btn_min": "48px",
    "rule": "1px",
    "cta_align": "flex-start",
    "art_radius": "12px",
}


def T(**overrides: str) -> dict:
    """A style's spacing/type tokens: the defaults with this style's values applied."""
    return {**TOKEN_DEFAULTS, **overrides}


@dataclass(frozen=True)
class Style:
    key: str
    label: str
    blurb: str                                     # one line, shown on the wizard card
    layout_style: str                              # echoed into Design.layout_style
    hero: str
    nav: str
    features: str
    motif: str
    radius: str
    tokens: dict = field(repr=False)
    palette: dict = field(repr=False)
    fonts: dict = field(repr=False)
    sections: tuple = ()                           # optional sections this style asks for by default
    order: tuple = ()                              # preferred sequence of all non-hero sections
    rules: tuple = ()                              # design instructions handed to the model

    def slot_notes(self) -> str:
        return (f"hero: {HERO_NOTES[self.hero]}; navigation: {NAV_NOTES[self.nav]}; "
                f"features: {FEATURE_NOTES[self.features]}; motif: {MOTIF_NOTES[self.motif]}")


_P = dict  # readability: palettes are written as keyword dicts

STYLES: tuple[Style, ...] = (
    Style("minimal", "Minimalist & clean", "Wide margins, one accent, typography doing all the work.",
          "minimal", "rail", "rail-left", "plain-list", "rules", "2px",
          T(width="820px", pad="88px", pad_half="44px", hero_pad="96px", gap="0px", base="17px", lh="1.7",
            h1="clamp(28px, 4vw, 40px)", h2="clamp(21px, 3vw, 26px)", h3="18px", track="0em",
            label_track=".18em", btn_pad="0 22px", cta_align="flex-start"),
          _P(background="#FAFAF9", surface="#FFFFFF", text="#1C1917", muted_text="#58544F",
             primary="#1F2937", primary_text="#FFFFFF", accent="#B45309"),
          {"heading": GROTESK, "body": SYSTEM_BODY},
          (), ("features", "faq", "cta"),
          ("Keep one accent colour only; everything else is text weight and whitespace.",
           "No card boxes around features: wide rows separated by a single hairline.",
           "Narrow measure (max 820px), generous vertical rhythm, no decorative shapes.")),

    Style("saas", "Modern SaaS", "Product window up top, bento proof panels, clear plan ladder.",
          "saas", "showcase", "top-links", "bento", "glow", "14px",
          T(width="1120px", pad="68px", pad_half="34px", hero_pad="60px", gap="18px", base="17px",
            h1="clamp(34px, 5.6vw, 56px)", h2="clamp(26px, 3.8vw, 36px)", label_track=".1em",
            btn_pad="0 28px", art_radius="14px"),
          _P(background="#F7F9FE", surface="#FFFFFF", text="#0F172A", muted_text="#4B5A6E",
             primary="#4338CA", primary_text="#FFFFFF", accent="#0E7490"),
          {"heading": SANS_BOLD, "body": SYSTEM_BODY},
          ("testimonials", "pricing"), ("testimonials", "features", "pricing", "faq", "cta"),
          ("Hero shows the product as a CSS-drawn window (frame, title dots, rows of content) - no screenshots, no remote images.",
           "Bento features: first card spans the full width, the remaining cards pair up beside it.",
           "Show the plan ladder as a row of cards with one emphasised tier.")),

    Style("luxury", "Luxury & premium", "Ink and champagne, serif display, index-table detail.",
          "luxury", "editorial", "wide-labels", "index-table", "hairline-caps", "0px",
          T(width="960px", pad="96px", pad_half="48px", hero_pad="110px", gap="28px", base="18px", lh="1.7",
            h1="clamp(30px, 4.4vw, 46px)", h2="clamp(20px, 2.6vw, 26px)", h3="19px", track=".02em",
            label_track=".3em", small="12px", btn_case="uppercase", btn_pad="0 32px", cta_align="flex-start"),
          _P(background="#101014", surface="#191920", text="#F4F0E6", muted_text="#A79F90",
             primary="#C9A227", primary_text="#1A1400", accent="#D9CBA3"),
          {"heading": SERIF_DISPLAY, "body": SERIF},
          ("gallery", "testimonials"), ("features", "gallery", "testimonials", "faq", "cta"),
          ("Uppercase letter-spaced micro-labels (0.3em) introduce every section; never a bold box.",
           "Features as two-column definition rows: label left, description right, hairline between.",
           "Square corners, thin rules, one gold accent. Ample empty space beats ornament.")),

    Style("glass", "Glassmorphism", "Frosted panels floating on a tinted field.",
          "glass", "band", "pill-bar", "tiles", "blur", "20px",
          T(width="1080px", pad="72px", pad_half="36px", hero_pad="80px", gap="20px", base="17px",
            h1="clamp(32px, 5.2vw, 50px)", label_track=".12em", btn_pad="0 26px", art_radius="20px"),
          _P(background="#E4EDF8", surface="#FFFFFF", text="#0E1A2B", muted_text="#465A72",
             primary="#1D4ED8", primary_text="#FFFFFF", accent="#0F766E"),
          {"heading": HUMANIST, "body": SYSTEM_BODY},
          ("pricing", "testimonials"), ("features", "pricing", "testimonials", "faq", "cta"),
          ("Panels use translucent surfaces (rgba whites over the tinted band) with backdrop-filter blur; "
           "body text still sits on an opaque panel so contrast is measurable.",
           "Features as square tiles in an even grid, each with a short uppercase label.",
           "Keep the glass treatment to the hero band and section panels - not the whole page.")),

    Style("dark", "Dark futuristic", "Monospace signal, faint grid, terminal-grade contrast.",
          "dark", "terminal", "index-list", "grid", "gridlines", "6px",
          T(width="1000px", pad="64px", pad_half="32px", hero_pad="72px", gap="16px", base="17px",
            h1="clamp(30px, 4.8vw, 48px)", label_track=".22em", btn_case="uppercase", btn_pad="0 24px",
            art_radius="6px"),
          _P(background="#070B14", surface="#101A2B", text="#E8F1FA", muted_text="#93A6BC",
             primary="#22D3EE", primary_text="#04222B", accent="#7DD3C0"),
          {"heading": MONO_SOFT, "body": SYSTEM_BODY},
          ("pricing",), ("features", "pricing", "faq", "cta"),
          ("Monospace labels and uppercase button text; a single cyan accent on near-black.",
           "Hero opens with a prompt-style line (e.g. '> deploy in one pass') above the headline.",
           "Faint grid lines behind section headings only, never under body copy.")),

    Style("corporate", "Corporate & professional", "Trustworthy split hero, tick-marked proof, contact path.",
          "corporate", "split", "underline-bar", "checklist", "depth", "8px",
          T(width="1100px", pad="56px", pad_half="28px", hero_pad="56px", gap="16px", base="17px",
            h1="clamp(30px, 4.4vw, 44px)", h2="clamp(24px, 3.2vw, 32px)", label_track=".1em", btn_pad="0 24px"),
          _P(background="#F5F7FA", surface="#FFFFFF", text="#111C2E", muted_text="#4E5A6B",
             primary="#1D4ED8", primary_text="#FFFFFF", accent="#0F766E"),
          {"heading": HUMANIST, "body": SYSTEM_BODY},
          ("testimonials", "contact"), ("features", "testimonials", "contact", "faq", "cta"),
          ("Restrained: two type sizes per level, no decorative shapes beyond a soft shadow.",
           "Features as a two-column checklist with tick marks; contact section carries the enquiry path.",
           "Testimonials must be labelled as sample quotes unless the brief supplies real ones.")),

    Style("agency", "Creative agency", "Oversized statement type, spotlight work, chip ticker.",
          "agency", "marquee", "bracket", "spotlight", "ticker", "2px",
          T(width="1160px", pad="80px", pad_half="40px", hero_pad="88px", gap="22px", base="18px",
            h1="clamp(38px, 7vw, 68px)", h2="clamp(24px, 3.4vw, 32px)", track="-.03em",
            h1_case="uppercase", label_track=".2em", btn_case="uppercase", btn_pad="0 30px"),
          _P(background="#FFFFFF", surface="#F2F1EC", text="#111111", muted_text="#54545A",
             primary="#141414", primary_text="#FFFFFF", accent="#7C3AED"),
          {"heading": IMPACT, "body": SYSTEM_BODY},
          ("gallery", "team"), ("features", "gallery", "team", "faq", "cta"),
          ("One huge uppercase display headline; body copy stays normal case and quiet by comparison.",
           "First feature is a full-width spotlight block, the rest are stacked rows against a rule.",
           "Use a bordered strip of capability chips as the divider between sections.")),

    Style("store", "E-commerce storefront", "Promo bar, category tiles, product-style cards.",
          "store", "storefront", "store-bar", "products", "pills", "10px",
          T(width="1160px", pad="52px", pad_half="26px", hero_pad="48px", gap="16px", base="17px",
            h1="clamp(30px, 4.6vw, 46px)", h2="clamp(23px, 3.2vw, 30px)", label_track=".12em",
            btn_pad="0 22px", art_radius="10px"),
          _P(background="#FFFDF8", surface="#FFFFFF", text="#1F1B16", muted_text="#6B5F52",
             primary="#8A3B12", primary_text="#FFFFFF", accent="#0F766E"),
          {"heading": HUMANIST, "body": SYSTEM_BODY},
          ("gallery", "contact"), ("features", "gallery", "faq", "contact", "cta"),
          ("Hero starts with a promo strip, then headline beside a small grid of category tiles.",
           "Features are product-style cards: label row, title, description and a price/availability chip.",
           "Gallery shows category panels drawn in CSS; no stock imagery or remote files.")),

    Style("editorial", "Editorial & portfolio", "Masthead, baseline-aligned article rows, framed panels.",
          "editorial", "masthead", "masthead-nav", "articles", "frame", "0px",
          T(width="880px", pad="64px", pad_half="32px", hero_pad="56px", gap="0px", base="18px", lh="1.75",
            h1="clamp(34px, 5.4vw, 54px)", h2="clamp(22px, 3vw, 28px)", h3="19px", track="-.01em",
            label_track=".16em", btn_pad="0 20px"),
          _P(background="#FDFCF8", surface="#F4F1E8", text="#1A1A18", muted_text="#5C584E",
             primary="#7C2D12", primary_text="#FFFFFF", accent="#14532D"),
          {"heading": SERIF_DISPLAY, "body": SERIF},
          ("gallery",), ("features", "gallery", "faq", "cta"),
          ("Masthead layout: brand name as the title of a publication, rule beneath, section links under that.",
           "Features read as an article index - kicker, headline, one-line excerpt, hairline separator.",
           "Panels carry a double border (outer rule plus inset offset), no shadows.")),

    Style("brutalist", "Brutalist & bold", "Thick outlines, hard shadows, poster headline.",
          "brutalist", "poster", "mono-strip", "manifest", "outline-thick", "0px",
          T(width="980px", pad="64px", pad_half="32px", hero_pad="56px", gap="0px", base="17px", lh="1.6",
            h1="clamp(40px, 8vw, 76px)", h2="clamp(26px, 4vw, 34px)", h3="20px", track="-.02em",
            h1_case="uppercase", h2_case="uppercase", label_track=".2em", btn_case="uppercase",
            btn_pad="0 26px", btn_min="52px", rule="3px"),
          _P(background="#FFFFFF", surface="#F4F4EF", text="#0A0A0A", muted_text="#4A4A4A",
             primary="#0A0A0A", primary_text="#FFFFFF", accent="#8A0000"),
          {"heading": "'Arial Black', 'Helvetica Neue', Arial, sans-serif", "body": MONO},
          ("pricing",), ("features", "pricing", "faq", "cta"),
          ("Square corners everywhere, 3px solid borders, and a hard offset box-shadow (no blur).",
           "Features as an uppercase numbered manifest with thick rules between rows.",
           "High contrast only: black on white/off-white. Uppercase headings, monospace body.")),

    Style("startup", "Startup landing", "Badge, centred pitch, dual CTA, tiered plans.",
          "startup", "centered", "plain-brand", "numbered", "circles", "16px",
          T(width="1000px", pad="72px", pad_half="36px", hero_pad="84px", gap="20px", base="17px",
            h1="clamp(36px, 6vw, 58px)", h2="clamp(25px, 3.6vw, 34px)", track="-.02em",
            label_track=".12em", btn_pad="0 30px", cta_align="center", art_radius="16px"),
          _P(background="#FFFFFF", surface="#F4F7FB", text="#0B1220", muted_text="#5A6A7E",
             primary="#4F46E5", primary_text="#FFFFFF", accent="#0E7490"),
          {"heading": "Verdana, Geneva, sans-serif", "body": SYSTEM_BODY},
          ("testimonials", "pricing"), ("testimonials", "features", "pricing", "faq", "cta"),
          ("Centred hero: a small pill badge above the headline, then two buttons side by side (primary + ghost).",
           "Features as stacked rows led by large numerals - the story of how it works.",
           "Every heading centred, section content constrained to one column for a focused pitch.")),

    Style("gradient", "Gradient & 3D-inspired", "Layered light shapes, dimensional panels, duo layout.",
          "gradient", "orb", "split-links", "duo", "orbfield", "24px",
          T(width="1080px", pad="72px", pad_half="36px", hero_pad="88px", gap="22px", base="17px",
            h1="clamp(34px, 5.4vw, 54px)", h2="clamp(25px, 3.4vw, 34px)", track="-.02em",
            label_track=".14em", btn_pad="0 28px", art_radius="28px"),
          _P(background="#0B0714", surface="#171029", text="#F3EEFF", muted_text="#A9A0C0",
             primary="#8B5CF6", primary_text="#120A20", accent="#22D3EE"),
          {"heading": "'Arial Rounded MT Bold', 'Segoe UI', Arial, sans-serif", "body": SYSTEM_BODY},
          ("gallery", "pricing"), ("features", "gallery", "pricing", "faq", "cta"),
          ("Radial-gradient light shapes behind the hero only; all copy stays on a solid panel so contrast is real.",
           "Features as a duo grid: one tall panel beside a column of shorter stacked panels.",
           "Large radii (24px+) and layered shadows give depth; keep text off gradients.")),
)

STYLE_BY_KEY: dict[str, Style] = {s.key: s for s in STYLES}


def get(key: str) -> Style | None:
    """The style with this key, or None. Callers decide what to do about an unknown key -
    nothing here silently substitutes a different style."""
    return STYLE_BY_KEY.get(str(key or ""))


def keys() -> tuple[str, ...]:
    return tuple(s.key for s in STYLES)


# ---------------------------------------------------------------- business types
@dataclass(frozen=True)
class Business:
    key: str
    label: str
    style: str                                  # the style this kind of site usually suits best
    sections: tuple                             # optional sections the type implies
    pages: tuple                                # pages a site of this kind would sensibly have


BUSINESS_TYPES: tuple[Business, ...] = (
    Business("corporate", "Business & consulting", "corporate",
             ("about", "stats", "services", "work", "team", "contact"),
             ("home", "about", "services", "work", "contact")),
    Business("saas", "SaaS / software", "saas", ("testimonials", "pricing"),
             ("home", "pricing", "features", "contact")),
    Business("ai", "AI product", "dark", ("testimonials", "pricing"),
             ("home", "pricing", "docs", "contact")),
    Business("agency", "Agency / studio", "agency", ("gallery", "team"),
             ("home", "work", "about", "contact")),
    Business("freelance", "Freelancer / consultant", "minimal", ("pricing", "contact"),
             ("home", "work", "contact")),
    Business("portfolio", "Portfolio / personal work", "editorial", ("gallery",),
             ("home", "work", "about", "contact")),
    Business("store", "Online store", "store", ("gallery", "contact"),
             ("home", "catalogue", "product", "contact")),
    Business("restaurant", "Restaurant / cafe", "store", ("gallery", "contact"),
             ("home", "menu", "visit", "contact")),
    Business("education", "Course / education", "startup", ("pricing", "testimonials"),
             ("home", "curriculum", "pricing", "contact")),
    Business("health", "Clinic / healthcare", "corporate", ("team", "contact"),
             ("home", "services", "team", "contact")),
    Business("legal", "Law firm / advisory", "editorial",
             ("about", "stats", "services", "team", "work", "booking"),
             ("home", "services", "team", "about", "contact")),
    Business("realestate", "Real estate", "luxury", ("gallery", "contact"),
             ("home", "listings", "agents", "contact")),
    Business("event", "Event / community", "gradient", ("gallery", "contact"),
             ("home", "schedule", "speakers", "contact")),
    Business("local", "Local service business", "corporate", ("testimonials", "contact"),
             ("home", "services", "contact")),
    Business("media", "Blog / publication", "editorial", ("gallery",),
             ("home", "archive", "about", "contact")),
    Business("other", "Something else", "minimal", (), ("home", "contact")),
)

BUSINESS_BY_KEY: dict[str, Business] = {b.key: b for b in BUSINESS_TYPES}

# A feature named in the brief maps to the section that can carry it. Kept deliberately narrow:
# anything not listed adds no section, so a stray word cannot silently restructure the site.
SECTION_KEYWORDS: dict[str, tuple] = {
    "testimonials": ("testimonial", "review", "social proof", "client quote", "case study"),
    "pricing": ("pricing", "price", "plan", "tier", "subscription", "package"),
    "gallery": ("gallery", "portfolio", "screenshot", "photo", "imagery", "showcase", "work samples"),
    "team": ("team", "staff", "founders", "people", "about us", "consultants"),
    "contact": ("contact", "enquiry", "inquiry", "address", "phone", "map", "email us"),
    "about": ("about", "company profile", "our story", "history", "mission", "who we are", "biography"),
    "services": ("service", "services", "practice area", "what we do", "offer", "treatment", "repair"),
    "work": ("case study", "client project", "selected work", "track record", "portfolio of work"),
    "catalog": ("catalog", "catalogue", "products", "menu", "courses", "listings", "properties",
                "collection", "shop", "store"),
    "visit": ("opening hours", "shop hours", "find us", "location", "where we are", "get here", "address of"),
    "booking": ("book", "booking", "reserve", "reservation", "appointment", "schedule a", "register",
                "sign up for a slot", "consultation"),
    "stats": ("achievements", "awards", "years in business", "clients served", "by the numbers"),
    "timeline": ("agenda", "schedule", "curriculum", "learning path", "experience", "roadmap",
                 "what happens when", "announcements"),
    "skills": ("skills", "tech stack", "stack", "capabilities", "expertise", "specialisms"),
    "preview": ("demo", "product tour", "app preview", "product preview", "interactive preview",
                "screenshots of the app"),
}


def sections_for(business_key: str, requested: list[str] | tuple[str, ...] = ()) -> tuple[str, ...]:
    """Optional sections implied by the business type plus the features the brief asks for."""
    business = BUSINESS_BY_KEY.get(str(business_key or ""))
    wanted = set(business.sections if business else ())
    blob = " ".join(str(r or "").lower() for r in requested)
    for section, needles in SECTION_KEYWORDS.items():
        if any(needle in blob for needle in needles):
            wanted.add(section)
    return tuple(s for s in OPTIONAL_SECTIONS if s in wanted)


def pages_for(business_key: str) -> tuple[str, ...]:
    business = BUSINESS_BY_KEY.get(str(business_key or ""))
    return business.pages if business else ("home", "contact")


def resolve_sections(business_key: str, requested: Sequence[str] = (), style_key: str = "") -> tuple[str, ...]:
    """The optional sections a brief adds up to: what the business type and the named features imply,
    plus what the chosen style carries by default. With no style chosen the caller leaves the style's
    defaults to whoever picks it, so `style_key` is empty there."""
    wanted = set(sections_for(business_key, requested))
    style = STYLE_BY_KEY.get(str(style_key or ""))
    if style:
        wanted |= set(style.sections)
    return tuple(s for s in OPTIONAL_SECTIONS if s in wanted)


# ---------------------------------------------------------------- card data for the UI
def as_card(style: Style) -> dict:
    """Everything the wizard needs to draw one selectable style card, including a thumbnail that is
    generated from the same slots the page builder uses - not a static picture of a page."""
    return {
        "key": style.key, "label": style.label, "blurb": style.blurb,
        "layout_style": style.layout_style, "hero": style.hero, "nav": style.nav,
        "features": style.features, "motif": style.motif, "radius": style.radius,
        "sections": list(REQUIRED_SECTIONS), "default_sections": list(style.sections),
        "palette": dict(style.palette), "fonts": dict(style.fonts), "tokens": dict(style.tokens),
    }


def cards() -> list[dict]:
    return [as_card(s) for s in STYLES]


def business_cards() -> list[dict]:
    return [{"key": b.key, "label": b.label, "style": b.style, "sections": list(b.sections),
             "pages": list(b.pages)} for b in BUSINESS_TYPES]


def section_cards() -> list[dict]:
    """Every section the builder can render, with the words the gallery and the wizard put on it.

    One list for both: a section a card describes is a section the page builder has code for, which is
    what keeps a template's content list from naming blocks that no run can produce.
    """
    return [{"key": key, "label": SECTION_INFO[key][0], "carries": SECTION_INFO[key][1],
             "always": key in REQUIRED_SECTIONS} for key in SECTION_KEYS]


def with_sections(style: Style, sections: tuple[str, ...]) -> Style:
    """A style reused with a different section set (what the brief asks for wins over the default)."""
    return replace(style, sections=tuple(s for s in OPTIONAL_SECTIONS if s in set(sections)))
