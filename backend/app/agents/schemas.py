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


class CopyDoc(BaseModel):
    product_name: str = Field(max_length=40)
    headline: str = Field(max_length=120)
    subheadline: str = Field(max_length=260)
    features: Annotated[list[Feature], _trim(6)] = Field(min_length=3)
    faq: Annotated[list[FAQ], _trim(6)] = Field(min_length=3)
    cta: CTA


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
