"""The design registry over HTTP, for the creation wizard.

Everything here is read-only, and it is the same registry the run composes its direction from, so a
style the wizard offers is the style the page is built in. There is deliberately no second list of
names or colours on the frontend for the two to drift apart from.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.agents import styles as design_styles
from app.agents import variants
from app.agents.schemas import SiteSpec
from app.core.deps import get_current_user

router = APIRouter(prefix="/api/styles", tags=["styles"])

# An explicit style fixes the whole direction, so a preview needs no run id to hang off.
PREVIEW_SEED = "wizard-preview"


@router.get("")
async def list_styles(user=Depends(get_current_user)):
    """Every style and business type the wizard can offer, with the slot vocabulary behind them."""
    return {
        "styles": design_styles.cards(),
        "business_types": design_styles.business_cards(),
        "sections": {"always": list(design_styles.REQUIRED_SECTIONS),
                     "optional": list(design_styles.OPTIONAL_SECTIONS)},
        "vocabulary": {"heroes": list(design_styles.HEROES), "navs": list(design_styles.NAVS),
                       "features": list(design_styles.FEATURE_LAYOUTS), "motifs": list(design_styles.MOTIFS),
                       "hero_notes": design_styles.HERO_NOTES, "nav_notes": design_styles.NAV_NOTES,
                       "feature_notes": design_styles.FEATURE_NOTES, "motif_notes": design_styles.MOTIF_NOTES},
    }


@router.get("/{key}")
async def style_detail(key: str, user=Depends(get_current_user)):
    """One style, plus the direction it composes to with nothing else in the brief."""
    style = design_styles.get(key)
    if style is None:
        raise HTTPException(404, f"Unknown design style '{key}'")
    return {"style": design_styles.as_card(style),
            "direction": variants.as_dict(variants.direction_for(PREVIEW_SEED, {"style": key})),
            "business_types": [b["key"] for b in design_styles.business_cards() if b["style"] == key]}


@router.post("/resolve")
async def resolve_brief(spec: SiteSpec, user=Depends(get_current_user)):
    """What this brief will be built with, before a run starts.

    With a style chosen the answer is exact: the same `direction_for` the pipeline calls produces the
    section order and the recoloured palette. Without one the style comes from the run id at build
    time, so the response says which style suits this business type and which sections the brief adds,
    and marks the preview not exact rather than guessing a layout.
    """
    stored = spec.model_dump()
    business = design_styles.BUSINESS_BY_KEY[stored["business_type"]]
    exact = bool(stored["style"])
    if exact:
        planned = set(stored["sections"]) | set(design_styles.resolve_sections(
            stored["business_type"], stored["features"], stored["style"]))
        stored["sections"] = [s for s in design_styles.OPTIONAL_SECTIONS if s in planned]
    direction = variants.direction_for(PREVIEW_SEED, stored) if exact else None
    included = (list(direction.sections) if direction
                else list(design_styles.sections_for(stored["business_type"], stored["features"])))
    recommended = design_styles.get(business.style)
    return {
        "spec": stored,                       # what POST /api/projects would store for this brief
        "exact": exact,
        "style": design_styles.as_card(design_styles.get(stored["style"]) or recommended),
        "direction": variants.as_dict(direction) if exact else None,
        "pages": list(spec.pages_or_default()),
        "sections": [s for s in included if s not in design_styles.REQUIRED_SECTIONS],
        "note": ("This brief fixes the layout: the direction below is what the run will build."
                 if exact else
                 f"No style chosen, so the run picks one from its id; {recommended.label} suits a "
                 f"{business.label.lower()}, and its own sections are added on top of these."),
    }
