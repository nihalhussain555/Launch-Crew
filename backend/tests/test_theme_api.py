"""Saved themes over HTTP: the library, its limits, and the point where a theme becomes a project's brief.

The contract these tests hold is the one the customizer depends on:

* the registry the UI draws its controls from is `app.agents.theme.registry()` itself, so a control on
  screen is a control the backend can store;
* only the controls persist - a saved theme carries no palette, tokens or contrast report, because those
  are recomputed on read, which is what lets a later accessibility fix reach an old theme;
* a colour that cannot be stored safely is refused, and a colour that had to move to stay readable says
  so in `notes` rather than being silently replaced;
* save, duplicate, reset and restore-previous are non-destructive: the version a save replaced is kept,
  and a theme already applied to a project survives deleting it from the library;
* and a saved theme handed to the wizard produces a run whose generated page is actually drawn in it.
"""
import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from app.agents import styles as design_styles
from app.agents import theme as design_theme
from app.agents import variants
from app.api import routes_auth
from app.main import app
from app.tools import browser_checks
from tests.conftest import GOOD_CHECKS


@pytest.fixture
def client(monkeypatch):
    """Chromium is not the subject here - the themed run just needs to reach the approval gate."""
    async def fake(html):
        return GOOD_CHECKS, {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    routes_auth._auth_limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    routes_auth._auth_limiter._hits.clear()


@pytest.fixture
def auth(client):
    r = client.post("/api/auth/register", json={"email": "designer@example.com",
                                                "password": "supersecret1", "name": "Designer"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def save(client, headers, controls, name=""):
    r = client.post("/api/themes", json={"name": name, "theme": controls}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ the controls
def test_the_library_needs_a_signed_in_user(client):
    assert client.get("/api/themes").status_code == 401
    assert client.get("/api/themes/registry").status_code == 401
    assert client.post("/api/themes", json={}).status_code == 401


def test_the_registry_serves_exactly_what_resolve_accepts(client, auth):
    body = client.get("/api/themes/registry", headers=auth).json()
    assert body == jsonable_encoder(design_theme.registry())
    assert [f["key"] for f in body["families"]] == [f.key for f in design_theme.FAMILIES]
    assert set(body["presets"]) == set(design_theme.PRESETS)
    assert body["colors"] == list(design_theme.COLOR_SLOTS)
    assert body["modes"] == list(design_theme.MODES)
    # every control the UI can set is a key resolve() reads, so nothing on screen is decorative
    assert {p["key"] for p in body["pairings"]} == {p.key for p in design_theme.PAIRINGS}
    assert body["limits"] == {"name": design_theme.THEME_NAME_MAX,
                              "themes_per_user": design_theme.MAX_THEMES_PER_USER}
    for family in body["families"]:
        for mode in design_theme.MODES:
            assert design_theme.resolve({"family": family["key"], "mode": mode})["notes"] == [], \
                f"{family['key']}/{mode}"


def test_a_saved_theme_stores_only_the_controls(client, auth):
    saved = save(client, auth, {"family": "creative", "mode": "dark", "card": "glass", "scale": 1.2},
                 name="Studio night")
    assert saved["name"] == "Studio night"
    assert set(saved["controls"]) == set(design_theme.as_stored(design_theme.resolve({})))
    for derived in ("palette", "tokens", "derived", "contrast", "notes", "fonts"):
        assert derived not in saved["controls"], derived
    # ... and the response still shows the derived half, computed on read
    assert set(saved["palette"]) == set(design_theme.PALETTE_KEYS)
    assert all(row["passes"] for row in saved["contrast"])
    assert saved["controls"]["card"] == "glass" and saved["theme"]["scale"] == 1.2
    assert saved["tokens"]["card_blur"] == "blur(10px)"
    assert saved["summary"] == design_theme.describe(saved["controls"])


def test_a_theme_is_read_back_as_the_same_page_it_was_saved_from(client, auth):
    """The library's reason for existing: a theme restored next month draws what it drew today."""
    controls = save(client, auth, {"family": "luxury", "mode": "dark", "density": "roomy",
                                   "radius": "pill", "shadow": "strong"})["controls"]
    first = variants.direction_for("idea", {"style": "startup", "theme": controls})
    again = variants.direction_for("idea", {"style": "startup",
                                           "theme": design_theme.as_stored(design_theme.resolve(controls))})
    assert (again.tokens, again.palette, again.fonts, again.theme) == \
           (first.tokens, first.palette, first.fonts, first.theme)


def test_a_colour_that_could_not_stay_readable_says_so(client, auth):
    """The customizer must be able to explain a moved swatch, not just show the result."""
    ugly = {"background": "#7f7f7f", "surface": "#808080", "text": "#8a8a8a", "primary": "#7f7f7f",
            "secondary": "#7f7f7f", "accent": "#888888"}
    saved = save(client, auth, {"family": "minimalist", "colors": ugly}, name="Grey soup")
    assert saved["notes"], "resolve() had to repair these colours and the user has to be told"
    assert all(row["passes"] for row in saved["contrast"])
    assert saved["palette"]["text"] != "#8a8a8a"
    assert saved["controls"]["colors"]["text"] != "#8a8a8a"      # what is stored is what was shown


@pytest.mark.parametrize("bad", [{"colors": {"primary": "sea blue"}},
                                 {"colors": {"primary": "#fc0"}},           # shorthand: not #rrggbb
                                 {"colors": {"tertiary": "#ffc700"}},       # not a slot the model has
                                 {"accent": "rgb(1, 2, 3)"},
                                 {"colors": {"primary": "<script>1</script>"}}])
def test_a_colour_that_cannot_be_stored_is_refused(client, auth, bad):
    assert client.post("/api/themes", json={"theme": bad}, headers=auth).status_code == 422
    saved = save(client, auth, {"family": "corporate"})
    assert client.patch(f"/api/themes/{saved['id']}", json={"theme": bad}, headers=auth).status_code == 422
    # a refused save leaves the theme exactly as it was
    assert client.get(f"/api/themes/{saved['id']}", headers=auth).json()["controls"] == saved["controls"]


def test_a_colour_is_stored_in_one_form_so_a_theme_has_no_aliases(client, auth):
    """`#FFC700` and `#ffc700` are the same colour; the swatch the user saw is the value that is kept."""
    upper = save(client, auth, {"family": "vibrant", "colors": {"primary": "#FFC700"}})
    lower = save(client, auth, {"family": "vibrant", "colors": {"primary": "#ffc700"}})
    assert upper["controls"] == lower["controls"]
    assert design_theme.is_hex(upper["controls"]["colors"]["primary"])


# ------------------------------------------------------------------ limits and isolation
@pytest.mark.parametrize("bad", [{"family": "signal"},                 # the old hard-coded name, not a family
                                 {"mode": "sepia"},
                                 {"pairing": "comic"},
                                 {"radius": "sharp"},                   # a button preset, not a corner one
                                 {"button": "rounded"},                   # a corner key, not a button one
                                 {"raadius": "pill"},                   # a misspelt control is not a control
                                 {"scale": 3},                          # past the slider's own limits
                                 {"scale": "huge"},
                                 {"colours": {"primary": "#ffc700"}}])   # a British spelling is not a slot
def test_a_control_the_registry_does_not_have_is_refused(client, auth, bad):
    """`resolve()` ignores what it cannot use, which is right mid-drag and wrong for something being saved.

    A theme that quietly stored the family's own corners after being asked for `radius: sharp` would show
    the user a library row that does not describe the page it later draws.
    """
    assert client.post("/api/themes", json={"name": "Nope", "theme": bad}, headers=auth).status_code == 422
    saved = save(client, auth, {"family": "corporate"})
    assert client.patch(f"/api/themes/{saved['id']}", json={"theme": bad}, headers=auth).status_code == 422
    # a refused save leaves the theme exactly as it was
    assert client.get(f"/api/themes/{saved['id']}", headers=auth).json()["controls"] == saved["controls"]
    assert client.post("/api/themes/preview-page", json={"theme": bad}, headers=auth).status_code == 422


def test_a_control_the_registry_does_have_is_stored_exactly_as_sent(client, auth):
    """The other half of the same promise: a real key from the right group comes back unchanged."""
    saved = save(client, auth, {"family": "luxury", "radius": "square", "button": "sharp", "scale": 1.18})
    assert saved["controls"]["radius"] == "square" and saved["controls"]["button"] == "sharp"
    assert saved["controls"]["scale"] == 1.18 and saved["theme"]["radius_key"] == "square"


def test_the_library_stops_at_the_documented_limit(client, auth):
    for i in range(design_theme.MAX_THEMES_PER_USER):
        save(client, auth, {"family": "pastel"}, name=f"theme {i}")
    r = client.post("/api/themes", json={"theme": {"family": "pastel"}}, headers=auth)
    assert r.status_code == 409 and str(design_theme.MAX_THEMES_PER_USER) in r.json()["detail"]
    assert len(client.get("/api/themes", headers=auth).json()["themes"]) == design_theme.MAX_THEMES_PER_USER
    # a duplicate is refused too, rather than half-created
    first = client.get("/api/themes", headers=auth).json()["themes"][0]
    assert client.post(f"/api/themes/{first['id']}/duplicate", headers=auth).status_code == 409
    assert len(client.get("/api/themes", headers=auth).json()["themes"]) == design_theme.MAX_THEMES_PER_USER


def test_another_users_themes_are_invisible(client, auth):
    saved = save(client, auth, {"family": "futuristic"}, name="Private")
    other = client.post("/api/auth/register", json={"email": "other@example.com",
                                                   "password": "supersecret1"}).json()
    h = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get("/api/themes", headers=h).json()["themes"] == []
    calls = (client.get(f"/api/themes/{saved['id']}", headers=h),
             client.patch(f"/api/themes/{saved['id']}", json={"name": "mine"}, headers=h),
             client.post(f"/api/themes/{saved['id']}/duplicate", headers=h),
             client.post(f"/api/themes/{saved['id']}/reset", headers=h),
             client.post(f"/api/themes/{saved['id']}/restore", headers=h),
             client.post(f"/api/themes/{saved['id']}/direction", json={}, headers=h),
             client.delete(f"/api/themes/{saved['id']}", headers=h))
    assert [c.status_code for c in calls] == [404] * len(calls)
    assert client.get(f"/api/themes/{saved['id']}", headers=auth).status_code == 200
    assert client.get("/api/themes/none-such", headers=auth).status_code == 404


# ------------------------------------------------------------------ save, duplicate, reset, restore
def test_editing_a_theme_keeps_the_version_it_replaced(client, auth):
    saved = save(client, auth, {"family": "corporate", "radius": "subtle"}, name="Client deck")
    assert saved["has_previous"] is False
    moved = client.patch(f"/api/themes/{saved['id']}",
                         json={"theme": {**saved["controls"], "radius": "pill"}}, headers=auth).json()
    assert moved["controls"]["radius"] == "pill" and moved["has_previous"] is True
    assert moved["previous"]["radius"] == "subtle"


def test_a_rename_is_not_a_theme_change(client, auth):
    saved = save(client, auth, {"family": "corporate"}, name="Old name")
    renamed = client.patch(f"/api/themes/{saved['id']}", json={"name": "New name"}, headers=auth).json()
    plain = lambda t: {k: v for k, v in t.items() if k != "label"}      # the name lives in `label` too
    assert renamed["name"] == "New name" and plain(renamed["controls"]) == plain(saved["controls"])
    assert renamed["controls"]["colors"] == saved["controls"]["colors"]
    assert renamed["has_previous"] is False           # nothing to undo: the appearance never moved
    assert client.patch(f"/api/themes/{saved['id']}", json={}, headers=auth).status_code == 422


def test_a_long_name_is_trimmed_the_way_the_registry_documents_it(client, auth):
    saved = save(client, auth, {"family": "corporate"}, name="x" * 90)
    assert len(saved["name"]) == design_theme.THEME_NAME_MAX
    assert saved["name"] == design_theme.clean_name("x" * 90)


def test_restore_gives_back_the_previous_theme_and_can_itself_be_undone(client, auth):
    saved = save(client, auth, {"family": "creative"}, name="First")
    before = saved["controls"]
    moved = client.patch(f"/api/themes/{saved['id']}", json={"theme": {"family": "luxury",
                                                                       "mode": "dark"}},
                         headers=auth).json()
    back = client.post(f"/api/themes/{saved['id']}/restore", headers=auth).json()
    assert back["controls"] == before and back["previous"] == moved["controls"]
    # restoring twice puts the moved theme back, so the button is an undo rather than a trap
    again = client.post(f"/api/themes/{saved['id']}/restore", headers=auth).json()
    assert again["controls"] == moved["controls"]
    fresh = save(client, auth, {"family": "minimalist"})
    assert client.post(f"/api/themes/{fresh['id']}/restore", headers=auth).status_code == 409


def test_reset_returns_to_the_curated_family_and_keeps_the_name(client, auth):
    saved = save(client, auth, {"family": "pastel", "colors": {"primary": "#0000ff"}, "shadow": "strong",
                                "density": "compact", "scale": 1.2, "card": "glass"}, name="My pastel")
    reset = client.post(f"/api/themes/{saved['id']}/reset", headers=auth).json()
    curated = design_theme.resolve({"family": "pastel", "mode": saved["controls"]["mode"]})
    assert reset["name"] == "My pastel"
    assert reset["controls"]["colors"] == curated["colors"]
    assert reset["controls"]["scale"] == curated["scale"]
    for group, control in (("pairing", "pairing"), ("density", "density"), ("width", "width_key"),
                           ("shadow", "shadow"), ("button", "button"), ("card", "card"),
                           ("radius", "radius_key")):
        assert reset["controls"][group] == curated[control], group
    assert reset["previous"] == saved["controls"] and reset["has_previous"] is True


def test_a_duplicate_can_be_edited_without_touching_the_original(client, auth):
    original = save(client, auth, {"family": "corporate", "shadow": "soft"}, name="Report")
    copy = client.post(f"/api/themes/{original['id']}/duplicate", headers=auth)
    assert copy.status_code == 201, copy.text
    dupe = copy.json()
    assert dupe["name"] == "Report copy" and dupe["controls"]["shadow"] == "soft"
    assert {k: v for k, v in dupe["controls"].items() if k != "label"} == \
           {k: v for k, v in original["controls"].items() if k != "label"}
    assert dupe["id"] != original["id"] and dupe["has_previous"] is False

    changed = client.patch(f"/api/themes/{dupe['id']}", json={"theme": {**dupe["controls"],
                                                                        "mode": "dark"}},
                           headers=auth).json()
    assert changed["controls"]["mode"] == "dark"
    assert client.get(f"/api/themes/{original['id']}", headers=auth).json()["controls"] == original["controls"]


def test_a_duplicate_of_a_full_length_name_still_says_it_is_the_copy(client, auth):
    long_name = "brand" * 16                                    # longer than THEME_NAME_MAX
    original = save(client, auth, {"family": "futuristic"}, name=long_name)
    dupe = client.post(f"/api/themes/{original['id']}/duplicate", headers=auth).json()
    assert dupe["name"].endswith("copy") and len(dupe["name"]) == design_theme.THEME_NAME_MAX
    assert dupe["name"] != original["name"]


def test_deleting_a_theme_leaves_the_projects_built_with_it_alone(client, auth):
    saved = save(client, auth, {"family": "vibrant"}, name="Temporary")
    project = client.post("/api/projects", json={"idea": "A booking desk for a pottery studio",
                                                 "spec": {"business_type": "health",
                                                          "theme": saved["controls"]}},
                          headers=auth).json()
    assert client.delete(f"/api/themes/{saved['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/themes/{saved['id']}", headers=auth).status_code == 404
    assert client.get(f"/api/projects/{project['id']}", headers=auth).json()["spec"]["theme"] == saved["controls"]


def test_the_library_is_ordered_by_the_theme_the_user_touched_last(client, auth):
    first = save(client, auth, {"family": "corporate"}, name="first")
    second = save(client, auth, {"family": "minimalist"}, name="second")
    listed = [t["name"] for t in client.get("/api/themes", headers=auth).json()["themes"]]
    assert listed == ["second", "first"]
    client.patch(f"/api/themes/{first['id']}", json={"theme": {"family": "corporate", "shadow": "strong"}},
                 headers=auth)
    assert [t["id"] for t in client.get("/api/themes", headers=auth).json()["themes"]][0] == first["id"]
    assert second["id"] in [t["id"] for t in client.get("/api/themes", headers=auth).json()["themes"]]


# ------------------------------------------------------------------ what a saved theme would draw
def test_the_direction_route_composes_the_page_this_theme_would_build(client, auth):
    saved = save(client, auth, {"family": "futuristic", "mode": "dark", "scale": 1.15,
                                 "radius": "pill", "card": "glass"})
    r = client.post(f"/api/themes/{saved['id']}/direction", json={"style": "editorial"}, headers=auth)
    assert r.status_code == 200, r.text
    direction = r.json()["direction"]
    style = design_styles.get("editorial")
    assert direction["style_key"] == "editorial"
    # a theme never moves a layout slot: the style's own structure is what comes back
    assert (direction["hero"], direction["nav"], direction["features"], direction["motif"]) == \
           (style.hero, style.nav, style.features, style.motif)
    assert direction["theme"] == saved["controls"]
    assert direction["radius"] == saved["radius"]
    assert direction["tokens"] == design_theme.tokens_for(design_theme.resolve(saved["controls"]), style)
    assert direction["tokens"]["base"] != style.tokens["base"]           # the scale reached the page
    assert design_theme.FAMILY_BY_KEY["futuristic"].label in r.json()["brief"]
    assert "999px" in r.json()["brief"]        # the trace line reads like the theme it describes
    assert client.post(f"/api/themes/{saved['id']}/direction", json={"style": "vaporwave"},
                       headers=auth).status_code == 422


def test_a_theme_with_no_style_chosen_previews_in_a_real_style(client, auth):
    saved = save(client, auth, {"family": "minimalist"})
    direction = client.post(f"/api/themes/{saved['id']}/direction", json={}, headers=auth).json()["direction"]
    assert design_styles.get(direction["style_key"]) is not None
    assert direction["theme"] == saved["controls"]


# ------------------------------------------------------------------ the customizer's live preview page
def preview(client, auth, theme, style="saas"):
    r = client.post("/api/themes/preview-page", json={"theme": theme, "style": style}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_preview_page_is_drawn_from_the_theme_it_describes(client, auth):
    """The panel shows a page, not a promise: every value it claims must be in that page's token block."""
    controls = {"family": "futuristic", "mode": "dark", "radius": "pill", "card": "glass", "scale": 1.15}
    body = preview(client, auth, controls)
    settled = design_theme.resolve(controls)
    assert body["sample_copy"] is True and body["style_key"] == "saas"
    assert body["theme"] == settled and body["tokens"] == settled["tokens"]
    root = body["html"].split(":root{")[1].split("}")[0]
    direction = variants.direction_for("theme-preview", {"style": "saas",
                                                         "theme": design_theme.as_stored(settled)})
    for prop in (f"--bg:{settled['palette']['background']}", f"--primary:{settled['palette']['primary']}",
                 "--radius:999px", "--card-blur:blur(", f"--base:{direction.tokens['base']}"):
        assert prop in root, prop
    assert all(row["passes"] for row in body["contrast"])
    assert body["summary"] == design_theme.describe(settled)


def test_previewing_two_themes_moves_the_tokens_not_the_layout(client, auth):
    """One style drawn two ways: the same page structure, recoloured by its variables alone."""
    light = preview(client, auth, {"family": "corporate", "mode": "light"})
    dark = preview(client, auth, {"family": "luxury", "mode": "dark", "radius": "square",
                                  "pairing": "editorial"})
    assert light["theme"]["palette"] != dark["theme"]["palette"]
    assert light["html"].split("</style>")[1] == dark["html"].split("</style>")[1]
    assert light["html"].split("<style>")[1].split("</style>")[0] != \
           dark["html"].split("<style>")[1].split("</style>")[0]
    # the style owns the layout, so both previews get the same hero the registry describes
    style = design_styles.get("saas")
    for body in (light, dark):
        assert f'class="hero hero-{style.hero}"' in body["html"]


def test_the_preview_page_refuses_what_a_saved_theme_refuses(client, auth):
    assert client.post("/api/themes/preview-page", json={"theme": {}}).status_code == 401
    assert client.post("/api/themes/preview-page", json={"theme": {}, "style": "vaporwave"},
                       headers=auth).status_code == 422
    bad = client.post("/api/themes/preview-page", json={"theme": {"colors": {"primary": "sea blue"}},
                                                        "style": "saas"}, headers=auth)
    assert bad.status_code == 422 and "primary" in bad.json()["detail"]


def test_a_previewed_theme_is_the_theme_a_brief_can_keep(client, auth):
    """What the customizer previews is what the wizard sends, so the preview is not a second renderer."""
    controls = {"family": "pastel", "mode": "dark", "density": "compact", "button": "sharp"}
    body = preview(client, auth, controls, style="startup")
    resolved = design_theme.resolve(controls)
    assert body["theme"]["tokens"] == resolved["tokens"]
    spec = {"business_type": "saas", "style": "startup", "theme": design_theme.as_stored(resolved)}
    planned = client.post("/api/styles/resolve", json=spec, headers=auth).json()
    assert planned["direction"]["theme"] == design_theme.as_stored(resolved)
    assert planned["direction"]["tokens"] == variants.direction_for(
        "x", {**spec, "theme": design_theme.as_stored(resolved)}).tokens


# ------------------------------------------------------------------ a saved theme becomes a real project
def test_a_saved_theme_applied_to_a_new_brief_draws_the_generated_page(client, auth):
    """The end-to-end promise: reuse this theme on a future project and the crew actually honours it."""
    saved = save(client, auth, {"family": "futuristic", "mode": "dark", "shadow": "strong",
                                "button": "outline", "radius": "rounded"}, name="Nightly product")
    controls = saved["controls"]
    r = client.post("/api/projects", json={"idea": "A commission manager for digital artists",
                                           "spec": {"business_type": "agency", "style": "agency",
                                                    "theme": controls}}, headers=auth)
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["spec"]["theme"] == controls

    rid = client.post(f"/api/projects/{project['id']}/runs", headers=auth).json()["id"]
    run = client.get(f"/api/runs/{rid}", headers=auth).json()
    assert run["status"] == "awaiting_approval", run["error"]
    assert run["state"]["style"]["theme"] == controls
    assert run["state"]["style"]["style_key"] == "agency"        # the brief's style, this theme's appearance

    page = client.get(f"/api/runs/{rid}/files/index.html", headers=auth).text
    root = page.split(":root{")[1].split("}")[0]
    settled = design_theme.resolve(controls)
    for prop in (f"--bg:{settled['palette']['background']}",
                 f"--primary:{settled['palette']['primary']}",
                 f"--radius:{saved['radius']}",
                 f"--shadow-strong:{saved['tokens']['shadow_strong']}",
                 "--btn-bg:transparent"):                      # the outline button preset
        assert prop in root, prop
    assert "--card-blur:none" in root                           # this theme asked for no glass


def test_the_wizard_preview_and_the_stored_brief_agree_about_the_theme(client, auth):
    """`/api/styles/resolve` is the review step; a theme it shows must be the theme the project keeps."""
    spec = {"business_type": "saas", "style": "startup", "theme": {"family": "luxury", "mode": "dark",
                                                                   "density": "roomy"}}
    preview = client.post("/api/styles/resolve", json=spec, headers=auth).json()
    assert preview["exact"] is True
    assert preview["direction"]["theme"] == design_theme.as_stored(design_theme.resolve(spec["theme"]))
    created = client.post("/api/projects", json={"idea": "A shift swap app for nurses", "spec": spec},
                          headers=auth).json()
    assert created["spec"]["theme"] == preview["direction"]["theme"]
