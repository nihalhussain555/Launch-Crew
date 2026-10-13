"""Saved themes over HTTP: the customizer's controls, the user's library, and what a theme resolves to.

Two rules shape every route here, and they come from the theme model itself (`app/agents/theme.py`):

* **Only the controls are stored.** Colours, pairings, radii, shadows, densities and the scale are what a
  user set; the derived labels, the token map, the palette and the contrast report are recomputed on every
  read. A theme saved before a future AA fix or a new preset therefore draws with that fix, and a stored
  document stays small enough to travel inside a project's brief.
* **Nothing here writes to a project or a run.** This library is reusable settings. Applying a theme to a
  live site is a workspace change with a checkpoint, a review and a restore path of its own, so a saved
  theme can be handed to the wizard (`spec["theme"]`) or to the apply pipeline - but a route here never
  rewrites someone's pages.

Invalid colours are refused rather than quietly dropped, because they are the values that reach CSS.
Every other unknown key is ignored on purpose: the customizer sends the controls it has, and a
half-finished theme is still a valid theme once resolved.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.agents import styles as design_styles
from app.agents import theme as design_theme
from app.agents import variants
from app.core.deps import get_current_user, get_db
from app.db.models import oid
from app.orchestrator.runner import now

router = APIRouter(prefix="/api/themes", tags=["themes"])

LIST_LIMIT = 100


class ThemeIn(BaseModel):
    """A new saved theme: a name and the controls themselves."""
    name: str = Field(default="", max_length=120)
    theme: dict = Field(default_factory=dict)


class ThemePatchIn(BaseModel):
    """Change the controls, the name, or both. Omitted half is left exactly as it was."""
    name: str | None = Field(default=None, max_length=120)
    theme: dict | None = None


class ApplyToBriefIn(BaseModel):
    """The brief the preview should be composed against, so the sample page is the site being themed."""
    style: str = Field(default="", max_length=32)


class SamplePageIn(ApplyToBriefIn):
    """A whole sample page: the controls to draw it with, plus the style to lay it out in.

    `business` is optional and only changes the words the sample page introduces its blocks with (a
    cafe's list is headed Menu, a school's Courses) so the customizer can be checked against the kind
    of site it is being tuned for. An unknown key is ignored rather than rejected: it is cosmetics on
    a throwaway page, and a stale value from a browser must not break the preview.
    """
    theme: dict = Field(default_factory=dict)
    business: str = Field(default="", max_length=24)


def _validate_colors(controls: dict) -> None:
    """Refuse a colour that is not a hex triplet, wherever the customizer put it.

    Checks what the client sent, not what it would become: a patch that names `accent` alone must not
    pass because the stored theme happens to have a valid `colors` block. `resolve()` ignores values it
    cannot use, which is right for a live drag but wrong for something being saved - the user would look
    at a saved theme and see a different colour than the one they typed.
    """
    controls = controls or {}
    flat = {k: v for k, v in controls.items() if k in design_theme.COLOR_SLOTS}
    nested = controls.get("colors") if isinstance(controls.get("colors"), dict) else {}
    unknown = [k for k in nested if k not in design_theme.COLOR_SLOTS]
    picked = {**flat, **nested}
    bad = [k for k, v in picked.items() if not design_theme.is_hex(str(v))]
    if unknown:
        raise HTTPException(422, f"Unknown colour slot(s): {', '.join(sorted(set(unknown)))}")
    if bad:
        raise HTTPException(422, f"Not a #rrggbb colour: {', '.join(sorted(set(bad)))}. "
                                 f"Pick one from the swatch or type a hex value.")


CONTROL_GROUPS = {"family": set(design_theme.FAMILY_BY_KEY), "mode": set(design_theme.MODES),
                  "pairing": set(design_theme.PAIRING_BY_KEY)}
CONTROL_KEYS = {"family", "mode", "label", "colors", "pairing", "scale", "width",
                "radius", "shadow", "button", "card", "density"} | set(design_theme.COLOR_SLOTS)


def _validate_controls(controls: dict) -> None:
    """Refuse a control the registry does not have, instead of storing the value it would quietly become.

    The same rule as colours, one level up: `resolve()` ignores what it cannot use, so `{"radius":
    "sharp"}` - a button preset, not a corner one - settled on the family's own corners and the library
    showed a theme that was never asked for. A saved theme has to say back exactly what it was given.
    """
    controls = controls or {}
    unknown = sorted(set(controls) - CONTROL_KEYS)
    bad = []
    for group, allowed in CONTROL_GROUPS.items():
        value = controls.get(group)
        if value not in (None, "") and value not in allowed:
            bad.append(f"{group} '{value}'")
    for group in ("density", "width", "radius", "shadow", "button", "card"):
        value = controls.get(group)
        if value not in (None, "") and not design_theme.preset_key(group, str(value)):
            bad.append(f"{group} '{value}'")
    scale = controls.get("scale")
    if scale not in (None, ""):
        try:
            num = float(scale)
        except (TypeError, ValueError):
            bad.append(f"scale '{scale}'")
        else:
            if not design_theme.SCALE_MIN <= num <= design_theme.SCALE_MAX:
                bad.append(f"scale {num} (the customizer only goes from {design_theme.SCALE_MIN} to "
                           f"{design_theme.SCALE_MAX})")
    if unknown:
        raise HTTPException(422, f"Unknown control(s): {', '.join(unknown)}. The registry offers "
                                 f"{', '.join(sorted(CONTROL_KEYS))}.")
    if bad:
        raise HTTPException(422, "Not a control this customizer has: " + "; ".join(bad) +
                                 ". Pick from the swatches, chips and slider - a saved theme stores exactly "
                                 "what it shows.")


def _resolve(controls: dict) -> dict:
    _validate_colors(controls or {})
    _validate_controls(controls or {})
    return design_theme.resolve(controls)


def _as_colors(controls: dict) -> dict:
    """Move colour slots given at the top level into the `colors` block.

    `resolve()` accepts a colour in either place, but a patch has to merge the stored block with the
    slots this request named, and that only works if they are in one place. Within a single request the
    nested block still wins for a slot it already names.
    """
    out = {k: v for k, v in (controls or {}).items()}
    flat = {k: out.pop(k) for k in list(out) if k in design_theme.COLOR_SLOTS}
    if flat:
        nested = dict(out.get("colors") or {})
        for key, value in flat.items():
            nested.setdefault(key, value)
        out["colors"] = nested
    return out


async def _own_theme(db, theme_id: str, user) -> dict:
    doc = await db.themes.find_one({"_id": oid(theme_id), "user_id": str(user["_id"])})
    if not doc:
        raise HTTPException(404, "Theme not found")
    return doc


async def _count(db, user) -> int:
    return await db.themes.count_documents({"user_id": str(user["_id"])})


def _card(doc: dict, resolved: dict | None = None) -> dict:
    """One library row: the swatches, the readable summary and what had to be repaired.

    `resolved` is the theme as the *request* settled it, which is what carries the notes about colours
    that had to move. Reading a stored theme back gives none, because what is in the database is already
    the readable set - the notes describe a save, not a permanent property of the theme.
    """
    t = resolved or design_theme.resolve(doc.get("theme") or {})
    return {"id": str(doc["_id"]), "name": doc.get("name", ""), "summary": design_theme.describe(t),
            "family": t["family"], "mode": t["mode"], "label": t["label"],
            "palette": t["palette"], "derived": t["derived"], "contrast": t["contrast"],
            "notes": t["notes"], "controls": doc.get("theme") or {},
            "has_previous": bool(doc.get("previous")),
            "created_at": doc.get("created_at"), "updated_at": doc.get("updated_at")}


def _detail(doc: dict, resolved: dict | None = None) -> dict:
    """A whole theme: the card plus every token and font the page is drawn from."""
    t = resolved or design_theme.resolve(doc.get("theme") or {})
    return {**_card(doc, t), "theme": t, "tokens": t["tokens"], "fonts": t["fonts"],
            "scale": t["scale"], "radius": t["radius"], "width": t["width"],
            "previous": doc.get("previous") or None}


# ------------------------------------------------------------------ the controls
@router.get("/registry")
async def registry(user=Depends(get_current_user)):
    """Everything the customizer needs to draw itself: families, pairings, presets, limits, defaults.

    Served from the same registry `resolve()` reads, so a control the UI offers is a control the
    backend can store, and there is no second list of names for the two to drift apart from.
    """
    return design_theme.registry()


# ------------------------------------------------------------------ the library
@router.get("")
async def list_themes(db=Depends(get_db), user=Depends(get_current_user)):
    cur = db.themes.find({"user_id": str(user["_id"])}).sort("updated_at", -1).limit(LIST_LIMIT)
    rows = [doc async for doc in cur]
    return {"themes": [_card(d) for d in rows], "limits": {"per_user": design_theme.MAX_THEMES_PER_USER}}


@router.post("", status_code=201)
async def create_theme(body: ThemeIn, db=Depends(get_db), user=Depends(get_current_user)):
    """Save the current controls as a reusable theme."""
    if await _count(db, user) >= design_theme.MAX_THEMES_PER_USER:
        raise HTTPException(409, f"You have {design_theme.MAX_THEMES_PER_USER} saved themes, which is the "
                                 f"limit. Delete or duplicate-over one of them to save another.")
    t = _resolve({**body.theme, "label": design_theme.clean_name(body.name)})
    stored = design_theme.as_stored(t)
    doc = {"user_id": str(user["_id"]), "name": stored["label"], "theme": stored, "previous": None,
           "created_at": now(), "updated_at": now()}
    doc["_id"] = (await db.themes.insert_one(doc)).inserted_id
    return _detail(doc, t)


@router.get("/{theme_id}")
async def get_theme(theme_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    return _detail(await _own_theme(db, theme_id, user))


@router.patch("/{theme_id}")
async def update_theme(theme_id: str, body: ThemePatchIn, db=Depends(get_db), user=Depends(get_current_user)):
    """Save new controls, or a new name. What the theme held before is kept for `/restore`.

    A patch replaces only the keys it names: sending `{"radius": "pill"}` changes the corners and leaves
    every colour alone, and a colour named on its own replaces just that slot. The customizer sends the
    whole settled set it is showing, so this is the same result either way - and a partial patch cannot
    quietly reset a swatch the user never touched.
    """
    doc = await _own_theme(db, theme_id, user)
    if body.theme is None and body.name is None:
        raise HTTPException(422, "Nothing to change: send a name, the controls, or both.")
    if body.theme is not None:
        _validate_colors(body.theme)
        _validate_controls(body.theme)
    merged = {**(doc.get("theme") or {}), **_as_colors(body.theme)}
    if "colors" in merged:
        merged["colors"] = {**((doc.get("theme") or {}).get("colors") or {}),
                            **(merged.get("colors") or {})}
    if body.name is not None:
        merged["label"] = design_theme.clean_name(body.name)
    resolved = design_theme.resolve(merged)
    settled = design_theme.as_stored(resolved)
    update = {"theme": settled, "name": settled["label"], "updated_at": now()}
    if body.theme is not None and settled != (doc.get("theme") or {}):
        update["previous"] = doc.get("theme") or None
    await db.themes.update_one({"_id": doc["_id"]}, {"$set": update})
    return _detail(await _own_theme(db, theme_id, user), resolved)


@router.post("/{theme_id}/duplicate", status_code=201)
async def duplicate_theme(theme_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """A copy to experiment on, with the original untouched."""
    doc = await _own_theme(db, theme_id, user)
    if await _count(db, user) >= design_theme.MAX_THEMES_PER_USER:
        raise HTTPException(409, f"You cannot save another theme: {design_theme.MAX_THEMES_PER_USER} is the "
                                 f"limit. Delete one first, then duplicate.")
    # Room left for the word "copy", so a duplicate of a full-length name is still recognisably the copy.
    name = design_theme.clean_name(f"{(doc.get('name') or 'Theme')[:design_theme.THEME_NAME_MAX - 5]} copy")
    copy = {"user_id": str(user["_id"]), "name": name,
            "theme": {**(doc.get("theme") or {}), "label": name},
            "previous": None, "created_at": now(), "updated_at": now()}
    copy["_id"] = (await db.themes.insert_one(copy)).inserted_id
    return _detail(copy)


@router.post("/{theme_id}/reset")
async def reset_theme(theme_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Back to the curated family and mode this theme started from: colours, pairing and every preset
    at the family's own values, with the name kept. The controls it had are stored as `previous`."""
    doc = await _own_theme(db, theme_id, user)
    stored = doc.get("theme") or {}
    fresh = design_theme.as_stored(design_theme.resolve({"family": stored.get("family"),
                                                          "mode": stored.get("mode"),
                                                          "label": stored.get("label")}))
    await db.themes.update_one({"_id": doc["_id"]}, {"$set": {"theme": fresh, "previous": stored,
                                                              "updated_at": now()}})
    return _detail(await _own_theme(db, theme_id, user))


@router.post("/{theme_id}/restore")
async def restore_theme(theme_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Put back the controls this theme had before the last save or reset.

    One level deep, and it swaps rather than discards: restoring twice returns the values that were
    replaced by the restore, which is what makes an accidental save safe rather than permanent.
    """
    doc = await _own_theme(db, theme_id, user)
    previous = doc.get("previous")
    if not previous:
        raise HTTPException(409, "This theme has not been changed since it was saved, so there is no "
                                 "previous version to restore.")
    stored = doc.get("theme") or {}
    await db.themes.update_one({"_id": doc["_id"]}, {"$set": {"theme": previous, "previous": stored,
                                                              "updated_at": now()}})
    return _detail(await _own_theme(db, theme_id, user))


@router.delete("/{theme_id}", status_code=204)
async def delete_theme(theme_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    """Forget a saved theme. Projects already built with it keep the controls stored in their own brief."""
    doc = await _own_theme(db, theme_id, user)
    await db.themes.delete_one({"_id": doc["_id"]})
    return Response(status_code=204)


# ------------------------------------------------------------------ what it would draw
@router.post("/{theme_id}/direction")
async def theme_direction(theme_id: str, body: ApplyToBriefIn, db=Depends(get_db),
                          user=Depends(get_current_user)):
    """The design direction this theme produces, without starting a run.

    Same `direction_for` the pipeline calls, so the preview is the real composition: the style's own
    layout slots plus this theme's colours, type and spacing. A style the registry does not have is
    refused instead of silently replaced, because a preview of a different layout is worse than none.
    """
    doc = await _own_theme(db, theme_id, user)
    if body.style and design_styles.get(body.style) is None:
        raise HTTPException(422, f"Unknown design style '{body.style}'")
    direction = variants.direction_for("theme-preview", {"style": body.style,
                                                         "theme": doc.get("theme") or {}})
    return {"direction": variants.as_dict(direction), "brief": direction.brief()}


@router.post("/preview-page")
async def preview_page(body: SamplePageIn, user=Depends(get_current_user)):
    """A whole page drawn by these controls, for the customizer's live preview before anything is saved.

    Not a mock-up of what a theme looks like: the same `mock.build_page` an offline run renders with,
    driven by the same `direction_for` the pipeline calls, so the tokens a user is choosing are the
    tokens that page's `:root` block carries - the same block `POST /api/runs/{id}/theme/propose` would
    later patch on a real project. The copy is the deterministic sample, with every stand-in placeholder
    marked `sample`, and `sample_copy` says so in the response: this previews *appearance*, not content.
    """
    if body.style and design_styles.get(body.style) is None:
        raise HTTPException(422, f"Unknown design style '{body.style}'")
    from app.llm import mock
    resolved = _resolve(body.theme)
    direction = variants.direction_for("theme-preview", {"style": body.style,
                                                         "theme": design_theme.as_stored(resolved)})
    business = body.business if body.business in design_styles.BUSINESS_BY_KEY else ""
    return {"html": mock.design_sample_page(direction, business), "style_key": direction.style_key,
            "style_label": direction.label, "theme": resolved, "tokens": resolved["tokens"],
            "summary": design_theme.describe(resolved), "contrast": resolved["contrast"],
            "notes": resolved["notes"], "brief": direction.brief(), "sample_copy": True}
