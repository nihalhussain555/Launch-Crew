"""Pydantic schemas for every structured agent output (validated; one corrective retry on failure).
List fields are trimmed (not rejected) when a model is a little too chatty; minimums are enforced."""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator, model_validator

from app.utils.color import contrast_ratio


def _trim(n: int):
    return BeforeValidator(lambda v: v[:n] if isinstance(v, list) else v)


Hex = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
_SAFE_FONT = re.compile(r"^[A-Za-z0-9 ,'\"\-]+$")


# ---- Researcher
class Competitor(BaseModel):
    name: str
    positioning: str = ""
    weakness: str = ""


class MarketBrief(BaseModel):
    competitors: Annotated[list[Competitor], _trim(5)] = Field(default_factory=list)
    audience_pain_points: Annotated[list[str], _trim(6)] = Field(min_length=1)
    keywords: Annotated[list[str], _trim(10)] = Field(min_length=1)
    opportunity: str
    sources: list[str] = Field(default_factory=list)


# ---- Website brief (what the creation wizard collects)
_PAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")


def _text(spec: dict, key: str) -> str:
    return str(spec.get(key) or "").strip()


def _words(spec: dict, key: str) -> list[str]:
    return [str(v).strip() for v in (spec.get(key) or []) if str(v).strip()]


def brief_line(spec: dict | None) -> str:
    """One prompt line describing a stored brief, or "" when there is nothing to say.

    Run state keeps the spec as a plain dict, and a dict from before the wizard (or with a value a
    validator would reject) must cost a run nothing rather than fail it mid-pipeline, so this reads the
    fields defensively instead of rebuilding `SiteSpec`.
    """
    from app.agents import styles as design_styles
    from app.agents import templates as site_templates

    if not isinstance(spec, dict):
        return ""
    style = design_styles.get(_text(spec, "style").lower())
    business = design_styles.BUSINESS_BY_KEY.get(_text(spec, "business_type").lower())
    template = site_templates.get(_text(spec, "template").lower())
    bits = []
    if template:
        # Names the shape the owner chose, so the copy is written for that trade rather than a generic site.
        bits.append(f"site template: {template.label} ({template.industries_line()})")
    if business:
        # The key travels with the label: the offline builder names its sections after the trade
        # ("Menu" for a café, "Courses" for a school), and it needs the stable id to do that.
        bits.append(f"business type: {business.label} ({business.key})")
    bits.append(f"design style: {style.label} ({style.key})" if style
                else "design style: the crew's choice for this idea")
    for label, limit in (("audience", 160), ("tone", 120)):
        value = _text(spec, label)
        if value:
            bits.append(f"{label}: {value[:limit]}")
    features = _words(spec, "features")
    if features:
        bits.append("requested features: " + ", ".join(features[:10])[:300])
    pages = _words(spec, "pages")
    if pages:
        bits.append("pages: " + ", ".join(pages[:8]))
    sections = [s for s in _words(spec, "sections") if s in design_styles.OPTIONAL_SECTIONS]
    if sections:
        bits.append("sections the brief asked for: " + ", ".join(sections))
    colour = _text(spec, "color")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
        bits.append(f"preferred colour: {colour}")
    theme_value = spec.get("theme")
    if isinstance(theme_value, dict) and theme_value:
        from app.agents import theme as design_theme
        bits.append(f"theme: {design_theme.describe(theme_value)[:200]}")
    return "; ".join(bits)


class SiteSpec(BaseModel):
    """The user's brief, stored on the project and handed to the crew.

    An unknown style or business type is a validation error rather than a substitution: a wizard
    choice that silently became something else is the one outcome no one can see happening. A theme
    is the exception - it is normalised rather than rejected, because a run must still be able to
    start against a theme saved before a palette family changed.
    """
    business_type: str = "other"
    audience: str = Field(default="", max_length=160)
    pages: Annotated[list[str], _trim(8)] = Field(default_factory=list)
    style: str = Field(default="", max_length=32)
    color: str = Field(default="", max_length=9)
    features: Annotated[list[str], _trim(10)] = Field(default_factory=list)
    tone: str = Field(default="", max_length=120)
    sections: Annotated[list[str], _trim(12)] = Field(default_factory=list)
    # The gallery card a brief started from. It carries no behaviour of its own: every field a template
    # knows about (style, sections, features, pages) arrives with the brief, so this is provenance the
    # run can name, not a second source of layout decisions.
    template: str = Field(default="", max_length=40)
    theme: dict = Field(default_factory=dict)
    # The catalog keys the wizard ticked. The page the crew generates is not built from them - a feature
    # is written into an existing page, through the reviewable build in the workspace - so the brief only
    # carries the request forward, and the Features panel offers exactly these when the run is waiting.
    feature_keys: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("theme", mode="before")
    @classmethod
    def _theme(cls, v):
        # Stored as the controls the user set, never as a resolved palette: the run re-resolves it, so
        # a later accessibility or preset fix reaches projects that were themed before it.
        from app.agents import theme as design_theme
        return design_theme.as_stored(design_theme.resolve(v)) if isinstance(v, dict) and v else {}

    @field_validator("business_type", "style", "color", "template", mode="before")
    @classmethod
    def _clean(cls, v):
        return str(v or "").strip().lower()

    @field_validator("template")
    @classmethod
    def _template(cls, v: str) -> str:
        from app.agents import templates as site_templates
        if v and site_templates.get(v) is None:
            raise ValueError(f"unknown template '{v}' - choose one of {', '.join(site_templates.keys())}")
        return v

    @field_validator("business_type")
    @classmethod
    def _business(cls, v: str) -> str:
        from app.agents import styles as design_styles
        if v not in design_styles.BUSINESS_BY_KEY:
            raise ValueError(f"unknown business type '{v}' - choose one of {', '.join(design_styles.BUSINESS_BY_KEY)}")
        return v

    @field_validator("style")
    @classmethod
    def _style(cls, v: str) -> str:
        from app.agents import styles as design_styles
        if v and design_styles.get(v) is None:
            raise ValueError(f"unknown design style '{v}' - choose one of {', '.join(design_styles.keys())}")
        return v

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if v and not re.fullmatch(r"#[0-9a-f]{6}", v):
            raise ValueError("preferred colour must be a six-digit hex value like #4f46e5, or empty")
        return v

    @field_validator("feature_keys", mode="before")
    @classmethod
    def _features(cls, v):
        from app.agents import capabilities as caps
        keys = list(dict.fromkeys(str(k or "").strip().lower() for k in (v or []) if str(k or "").strip()))
        unknown = [k for k in keys if caps.get(k) is None]
        if unknown:
            raise ValueError(f"no feature source for {', '.join(unknown)} - ask for one of "
                             f"{', '.join(caps.keys())}")
        return keys

    @field_validator("pages")
    @classmethod
    def _pages(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for page in v:
            name = str(page or "").strip().lower()
            if name and not _PAGE_NAME.match(name):
                raise ValueError(f"page name '{name}' must be lower-case letters, digits or hyphens")
            if name and name not in out:
                out.append(name)
        return out

    @field_validator("sections")
    @classmethod
    def _sections(cls, v: list[str]) -> list[str]:
        from app.agents import styles as design_styles
        out = [str(s or "").strip().lower() for s in v if s]
        bad = [s for s in out if s not in design_styles.OPTIONAL_SECTIONS]
        if bad:
            raise ValueError(f"{'/'.join(bad)} is not a section the crew can build "
                             f"(choose from {', '.join(design_styles.OPTIONAL_SECTIONS)})")
        return list(dict.fromkeys(out))

    def pages_or_default(self) -> tuple[str, ...]:
        from app.agents import styles as design_styles
        return tuple(self.pages) or design_styles.pages_for(self.business_type)

    def brief_block(self) -> str:
        """The brief as one prompt line, empty fields left out so the model is not told nothing."""
        return brief_line(self.model_dump())


# ---- Strategist
class Persona(BaseModel):
    name: str
    description: str
    goals: list[str] = Field(default_factory=list)
    frustrations: list[str] = Field(default_factory=list)


class Strategy(BaseModel):
    positioning: str
    persona: Persona
    key_messages: Annotated[list[str], _trim(3)] = Field(min_length=3, max_length=3)


# ---- Copywriter
class Feature(BaseModel):
    title: str = Field(max_length=80)
    description: str = Field(max_length=300)


class FAQ(BaseModel):
    question: str
    answer: str


class CTA(BaseModel):
    label: str = Field(max_length=50)
    supporting_text: str = Field(default="", max_length=240)


# ---- Optional sections a brief can ask for.
# Every item carries `sample`: content the crew wrote because the brief did not supply any. The page
# builder prints a visible "sample content" note for a section made up entirely of samples, so a
# generated site can never pass off an invented testimonial as a real customer.
class Testimonial(BaseModel):
    quote: str = Field(max_length=220)
    attribution: str = Field(default="", max_length=60)
    sample: bool = True


class Plan(BaseModel):
    name: str = Field(max_length=40)
    price: str = Field(max_length=40)
    blurb: str = Field(default="", max_length=120)
    items: Annotated[list[str], _trim(5)] = Field(default_factory=list)
    featured: bool = False
    sample: bool = True


class GalleryItem(BaseModel):
    title: str = Field(max_length=60)
    caption: str = Field(default="", max_length=120)
    sample: bool = True


class TeamRole(BaseModel):
    role: str = Field(max_length=60)
    focus: str = Field(default="", max_length=140)
    sample: bool = True


class ContactInfo(BaseModel):
    email: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=60)
    location: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=160)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if v and not re.match(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$", v):
            raise ValueError("contact email must be a plain address, or empty")
        return v


# ---- The content blocks a professional site is made of.
# Each carries `sample` like the sections above: a founded year, an opening-hours row or a client name
# the crew guessed is marked as a guess, and the builder prints that out on the page.
class FactRow(BaseModel):
    label: str = Field(max_length=40)
    value: str = Field(max_length=80)


class AboutDoc(BaseModel):
    intro: str = Field(default="", max_length=400)
    facts: Annotated[list[FactRow], _trim(4)] = Field(default_factory=list)
    credentials: Annotated[list[str], _trim(5)] = Field(default_factory=list)
    sample: bool = True


class Stat(BaseModel):
    value: str = Field(max_length=24)
    label: str = Field(max_length=50)
    sample: bool = True


class SkillGroup(BaseModel):
    group: str = Field(max_length=40)
    items: Annotated[list[str], _trim(6)] = Field(default_factory=list)
    sample: bool = True


class Service(BaseModel):
    name: str = Field(max_length=60)
    description: str = Field(default="", max_length=200)
    detail: str = Field(default="", max_length=48)     # a lead time or a "from" price, never a bare number
    sample: bool = True


class CaseStudy(BaseModel):
    client: str = Field(max_length=60)
    sector: str = Field(default="", max_length=40)
    title: str = Field(max_length=80)
    outcome: str = Field(default="", max_length=220)
    metric: str = Field(default="", max_length=48)
    sample: bool = True


class CatalogItem(BaseModel):
    name: str = Field(max_length=70)
    note: str = Field(default="", max_length=180)
    price: str = Field(default="", max_length=40)
    tag: str = Field(default="", max_length=32)
    specs: Annotated[list[str], _trim(3)] = Field(default_factory=list)
    sample: bool = True


DEVICES = ("window", "phone")


class PreviewDoc(BaseModel):
    title: str = Field(default="", max_length=60)
    caption: str = Field(default="", max_length=200)
    points: Annotated[list[str], _trim(4)] = Field(default_factory=list)
    device: str = Field(default="window", max_length=12)
    sample: bool = True

    @field_validator("device")
    @classmethod
    def _device(cls, v: str) -> str:
        if v not in DEVICES:
            raise ValueError(f"preview device must be one of {', '.join(DEVICES)}")
        return v


class TimelineEntry(BaseModel):
    when: str = Field(max_length=36)
    title: str = Field(max_length=70)
    note: str = Field(default="", max_length=180)
    place: str = Field(default="", max_length=48)
    sample: bool = True


class HoursRow(BaseModel):
    days: str = Field(max_length=32)
    time: str = Field(max_length=40)


class VisitDoc(BaseModel):
    address: str = Field(default="", max_length=160)
    hours: Annotated[list[HoursRow], _trim(6)] = Field(default_factory=list)
    getting_here: str = Field(default="", max_length=180)
    sample: bool = True


BOOKING_KINDS = ("appointment", "reservation", "consultation", "registration", "enquiry")


class BookingDoc(BaseModel):
    """The booking block's copy. Which fields the form asks for follows `kind`, so a table booking
    asks for a party size and a consultation asks for the subject - not one generic form."""
    kind: str = Field(default="appointment", max_length=20)
    title: str = Field(default="", max_length=60)
    intro: str = Field(default="", max_length=200)
    options: Annotated[list[str], _trim(5)] = Field(default_factory=list)
    note: str = Field(default="", max_length=200)
    sample: bool = True

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in BOOKING_KINDS:
            raise ValueError(f"booking kind must be one of {', '.join(BOOKING_KINDS)}")
        return v


class SectionTitle(BaseModel):
    """A section's heading in this site's own words: a café's list is a Menu, a school's is a Course
    catalogue. Only the name of a section the builder knows, so a heading cannot attach itself to a
    block that is not on the page."""
    section: str = Field(max_length=20)
    text: str = Field(max_length=48)

    @field_validator("section")
    @classmethod
    def _section(cls, v: str) -> str:
        from app.agents import styles as design_styles
        if v not in design_styles.SECTION_KEYS:
            raise ValueError(f"'{v}' is not a section this page can carry")
        return v


class CopyDoc(BaseModel):
    product_name: str = Field(max_length=40)
    headline: str = Field(max_length=120)
    subheadline: str = Field(max_length=260)
    features: Annotated[list[Feature], _trim(6)] = Field(min_length=3)
    faq: Annotated[list[FAQ], _trim(6)] = Field(min_length=3)
    cta: CTA
    titles: Annotated[list[SectionTitle], _trim(12)] = Field(default_factory=list)
    about: AboutDoc = AboutDoc()
    stats: Annotated[list[Stat], _trim(4)] = Field(default_factory=list)
    skills: Annotated[list[SkillGroup], _trim(4)] = Field(default_factory=list)
    services: Annotated[list[Service], _trim(6)] = Field(default_factory=list)
    work: Annotated[list[CaseStudy], _trim(4)] = Field(default_factory=list)
    catalog: Annotated[list[CatalogItem], _trim(8)] = Field(default_factory=list)
    preview: PreviewDoc = PreviewDoc()
    timeline: Annotated[list[TimelineEntry], _trim(6)] = Field(default_factory=list)
    testimonials: Annotated[list[Testimonial], _trim(3)] = Field(default_factory=list)
    pricing: Annotated[list[Plan], _trim(3)] = Field(default_factory=list)
    gallery: Annotated[list[GalleryItem], _trim(6)] = Field(default_factory=list)
    team: Annotated[list[TeamRole], _trim(4)] = Field(default_factory=list)
    visit: VisitDoc = VisitDoc()
    booking: BookingDoc = BookingDoc()
    contact: ContactInfo = ContactInfo()


# ---- Designer
class Palette(BaseModel):
    background: Hex
    surface: Hex
    text: Hex
    muted_text: Hex
    primary: Hex
    primary_text: Hex
    accent: Hex


class Fonts(BaseModel):
    heading: str
    body: str

    @field_validator("heading", "body")
    @classmethod
    def _safe(cls, v: str) -> str:
        # Font stacks are pasted into CSS: allow only plain family names so nothing can be injected.
        if not _SAFE_FONT.match(v):
            raise ValueError("font stack may only contain letters, digits, spaces, commas, quotes and hyphens (system fonts only)")
        return v


class Design(BaseModel):
    palette: Palette
    fonts: Fonts
    layout_style: str = Field(default="minimal", max_length=40)

    @model_validator(mode="after")
    def _contrast(self):
        p = self.palette
        pairs = [("text/background", p.text, p.background), ("text/surface", p.text, p.surface),
                 ("muted_text/background", p.muted_text, p.background), ("muted_text/surface", p.muted_text, p.surface),
                 ("primary_text/primary", p.primary_text, p.primary), ("accent/surface", p.accent, p.surface)]
        bad = [f"{n} = {contrast_ratio(a, b):.1f}:1" for n, a, b in pairs if contrast_ratio(a, b) < 4.5]
        if bad:
            raise ValueError("Palette fails WCAG AA (needs >= 4.5:1): " + "; ".join(bad))
        return self


# ---- Critic
class CriticFix(BaseModel):
    agent: Literal["copywriter", "designer", "engineer"] = "engineer"
    priority: int = Field(default=2, ge=1, le=3)  # 1 = most important
    instruction: str = Field(max_length=500)

    @field_validator("priority", mode="before")
    @classmethod
    def _prio(cls, v):
        if isinstance(v, str):
            return {"high": 1, "medium": 2, "low": 3}.get(v.strip().lower(), int(v) if v.strip().isdigit() else 2)
        return v

    @field_validator("agent", mode="before")
    @classmethod
    def _agent(cls, v):
        return str(v).strip().lower() if v else "engineer"


class CriticFeedback(BaseModel):
    summary: str = ""
    fixes: Annotated[list[CriticFix], _trim(8)] = Field(default_factory=list)


# ---- Launcher
class SocialPost(BaseModel):
    platform: str
    text: str = Field(max_length=600)


class LaunchEmail(BaseModel):
    subject: str
    body: str


class LaunchKit(BaseModel):
    social_posts: Annotated[list[SocialPost], _trim(3)] = Field(min_length=3, max_length=3)
    email: LaunchEmail



# ---- Audience panel (synthetic user testing)
def _score(v):
    try:
        return max(1, min(10, round(float(v))))
    except (TypeError, ValueError):
        return v


class PanelReaction(BaseModel):
    persona: str
    score: Annotated[int, BeforeValidator(_score)]
    first_impression: str = ""
    top_objection: str = ""
    would_sign_up: bool = False


class PanelReport(BaseModel):
    reactions: Annotated[list[PanelReaction], _trim(4)] = Field(min_length=3)
    summary: str = ""
    suggested_fix: str = ""
    suggested_target: Literal["page", "copy", "design"] = "copy"

    @field_validator("suggested_target", mode="before")
    @classmethod
    def _target(cls, v):
        v = str(v or "").strip().lower()
        return v if v in {"page", "copy", "design"} else "copy"


# ---- Visual editor (one element selected in the live preview)
class VisualPatch(BaseModel):
    """One minimal edit aimed at the file that declares the selected element.

    `set` is deliberately absent: a click on one element is not a licence to rewrite a document.
    """
    file: Annotated[str, Field(min_length=1, max_length=64)]
    op: str = "replace"
    find: Annotated[str, Field(max_length=8000)] = ""
    replace: Annotated[str, Field(max_length=8000)] = ""
    note: Annotated[str, Field(max_length=200)] = ""

    @field_validator("op", mode="before")
    @classmethod
    def _op(cls, v):
        op = str(v or "replace").strip().lower()
        if op not in {"replace", "replace_all", "append"}:
            raise ValueError(f"'{op}' is not a visual edit - choose replace, replace_all or append")
        return op

    @model_validator(mode="after")
    def _has_something_to_match(self):
        if self.op in ("replace", "replace_all") and not self.find.strip():
            raise ValueError("a visual patch needs `find`: the exact text in that file to change")
        if self.op == "append" and not self.replace.strip():
            raise ValueError("an append needs the text to add in `replace`")
        return self


# ---- IDE assistant (one plain-English request over the workspace's own files)
class IdePatchChange(BaseModel):
    """One file's edit, in the language the workspace routes already accept.

    `workspace_manager.validate_patch` stays the authority on what an edit means; this only bounds the
    shape, so a model cannot hand back a megabyte of text or an operation no pipeline knows. The op list
    and the 12-change cap mirror `workspace_manager.OPS` and `validate_changes`.
    """
    file: Annotated[str, Field(min_length=1, max_length=64)]
    op: str = "replace"
    find: Annotated[str, Field(max_length=12000)] = ""
    replace: Annotated[str, Field(max_length=12000)] = ""
    text: Annotated[str, Field(max_length=60000)] = ""
    note: Annotated[str, Field(max_length=200)] = ""

    @field_validator("op", mode="before")
    @classmethod
    def _op(cls, v):
        op = str(v or "replace").strip().lower()
        if op not in {"replace", "replace_all", "append", "set"}:
            raise ValueError(f"'{op}' is not an edit this workspace accepts - choose replace, "
                             f"replace_all, append or set")
        return op

    @model_validator(mode="after")
    def _has_something_to_write(self):
        if self.op in ("replace", "replace_all") and not self.find.strip():
            raise ValueError("a patch needs `find`: text that is really in that file")
        if self.op in ("append", "set") and not (self.text or self.replace).strip():
            raise ValueError(f"'{self.op}' needs the text to write")
        return self


class IdePatchSet(BaseModel):
    """What the assistant says it would do, and the at-most-a-handful of edits it means by that."""
    summary: Annotated[str, Field(max_length=400)] = ""
    changes: Annotated[list[IdePatchChange], _trim(12)] = Field(min_length=1)
