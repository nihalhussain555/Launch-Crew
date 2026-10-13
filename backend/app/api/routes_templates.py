"""The template gallery over HTTP, for the wizard and the templates pages.

Read-only, and the same registry a run is actually built from: a card's layout style, content blocks and
feature requests are the fields `SiteSpec` receives, so what the gallery promises is what the crew
composes. There is deliberately no second list of templates on the frontend for the two to drift apart
from.

`/{key}/preview` is not a picture of a template. It calls the same `app.llm.mock` page builder an offline
run renders with, at the template's own style and composition, so every block the card names is on the
page the user is looking at - filled with the sample copy that builder labels as sample copy. Colours and
spacing come from the template's style; a saved theme is applied by the run itself, through the theme
controls that already exist.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.agents import styles as design_styles
from app.agents import templates as site_templates
from app.agents import variants
from app.agents.schemas import SiteSpec
from app.core.deps import get_current_user
from app.llm import mock

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _built_sections(spec: dict) -> list[str]:
    """The blocks this brief composes to: the template's own list plus whatever the style and business
    type add, in the page's order. Same calculation `POST /api/styles/resolve` makes for a hand-written
    brief, so a card and a typed brief are measured the same way."""
    planned = set(spec["sections"]) | set(design_styles.resolve_sections(
        spec["business_type"], spec["features"], spec["style"]))
    spec["sections"] = [s for s in design_styles.OPTIONAL_SECTIONS if s in planned]
    return list(variants.direction_for(f"template:{spec['template']}", spec).sections)


@router.get("")
async def list_templates(user=Depends(get_current_user)):
    """Every template, in the order the gallery reads, with its honest status badge."""
    return site_templates.catalog()


@router.get("/sections")
async def section_catalogue(user=Depends(get_current_user)):
    """Every content block the page builder can render, and what each one carries.

    The wizard's block picker and the cards' block lists both read this, so a template can only name a
    block that has rendering code behind it.
    """
    return {"always": list(design_styles.REQUIRED_SECTIONS),
            "optional": list(design_styles.OPTIONAL_SECTIONS),
            "cards": design_styles.section_cards()}


@router.get("/{key}")
async def template_detail(key: str, user=Depends(get_current_user)):
    """One template: its blocks, the features it asks for with their real statuses, and the brief a run
    would start from."""
    t = site_templates.get(key)
    if t is None:
        raise HTTPException(404, f"Unknown template '{key}' - choose one of {', '.join(site_templates.keys())}")
    spec = SiteSpec.model_validate(site_templates.spec_for(t)).model_dump()
    built = _built_sections(spec)
    return {"template": site_templates.as_card(t),
            "spec": spec,
            "direction": variants.as_dict(variants.direction_for(f"template:{key}", spec)),
            "sections_built": built}


@router.get("/{key}/preview")
async def template_preview(key: str, user=Depends(get_current_user)):
    """The page this template composes, drawn by the real builder with placeholder copy.

    Not a screenshot: it is the HTML a run of this template builds, in the template's style, with the
    blocks it asks for, before that run's own copy replaces the samples.
    """
    t = site_templates.get(key)
    if t is None:
        raise HTTPException(404, f"Unknown template '{key}' - choose one of {', '.join(site_templates.keys())}")
    spec = site_templates.spec_for(t)
    direction = variants.direction_for(f"template-preview:{key}", spec)
    return {"html": mock.design_sample_page(direction, t.business, t.summary),
            "template": key, "style_key": direction.style_key, "style_label": direction.label,
            "sections": list(direction.sections), "blocks": t.blocks(),
            "sample_copy": True,
            "note": ("Placeholder content in the template's real composition: the blocks, headings and "
                     "fields are what a run builds; the words inside them are samples the first run "
                     "replaces with this business's own copy.")}
