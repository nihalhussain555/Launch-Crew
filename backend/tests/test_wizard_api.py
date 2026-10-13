"""The creation wizard's contract over HTTP.

Three things have to hold for the brief on screen to be the brief the page is built from:
`/api/styles` serves the same registry the orchestrator composes its direction from, `/api/styles/resolve`
answers with what `POST /api/projects` will actually store, and the stored spec reaches the run and picks
the style. An unknown choice must be a validation error rather than a silent substitution, because a wizard
answer that quietly became something else is the one failure no one can see in the finished page.
"""
import pytest
from fastapi.testclient import TestClient

from app.agents import styles as design_styles
from app.api import routes_auth
from app.main import app
from app.tools import browser_checks
from tests.conftest import GOOD_CHECKS


@pytest.fixture
def client(monkeypatch):
    """Chromium is not the subject here - the run just needs to reach the approval gate."""
    async def fake(html):
        return GOOD_CHECKS, {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    routes_auth._auth_limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    routes_auth._auth_limiter._hits.clear()


@pytest.fixture
def auth(client):
    """A fresh user per test: the run quota is per user per hour, and these tests start real runs."""
    r = client.post("/api/auth/register", json={"email": "wizard@example.com",
                                                "password": "supersecret1", "name": "Wizard"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def project(client, headers, spec, idea="A commission manager for digital artists"):
    r = client.post("/api/projects", json={"idea": idea, "spec": spec}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ the registry the wizard reads

def test_the_registry_needs_a_signed_in_user(client):
    assert client.get("/api/styles").status_code == 401
    assert client.get("/api/styles/saas").status_code == 401
    assert client.post("/api/styles/resolve", json={}).status_code == 401


def test_the_registry_serves_the_styles_the_pipeline_can_build(client, auth):
    body = client.get("/api/styles", headers=auth).json()
    assert [s["key"] for s in body["styles"]] == list(design_styles.keys())
    assert [b["key"] for b in body["business_types"]] == list(design_styles.BUSINESS_BY_KEY)
    assert body["sections"] == {"always": list(design_styles.REQUIRED_SECTIONS),
                                "optional": list(design_styles.OPTIONAL_SECTIONS),
                                "cards": design_styles.section_cards()}
    # the picker reads the cards, so a card has to exist for every name in the vocabulary and only those
    assert [c["key"] for c in body["sections"]["cards"]] == list(design_styles.SECTION_KEYS)

    vocab = body["vocabulary"]
    assert vocab["heroes"] == list(design_styles.HEROES)
    assert vocab["navs"] == list(design_styles.NAVS)
    assert vocab["features"] == list(design_styles.FEATURE_LAYOUTS)
    assert vocab["motifs"] == list(design_styles.MOTIFS)
    # every slot value the wizard shows an explanation for, and nothing it cannot build
    assert set(vocab["hero_notes"]) == set(design_styles.HEROES)
    assert set(vocab["nav_notes"]) == set(design_styles.NAVS)
    assert set(vocab["feature_notes"]) == set(design_styles.FEATURE_LAYOUTS)
    assert set(vocab["motif_notes"]) == set(design_styles.MOTIFS)


def test_each_style_card_describes_a_distinct_layout(client, auth):
    cards = client.get("/api/styles", headers=auth).json()["styles"]
    for field in ("hero", "nav", "features", "motif"):
        assert len({c[field] for c in cards}) == len(cards), field
    for c in cards:
        assert set(c["palette"]) == set(design_styles.STYLE_BY_KEY[c["key"]].palette)
        assert set(c["sections"]) == set(design_styles.REQUIRED_SECTIONS)
        assert set(c["default_sections"]) <= set(design_styles.OPTIONAL_SECTIONS)
        assert c["radius"] and c["tokens"]["base"] and c["fonts"]["heading"]
    # twelve styles that only differ by colour would fail this; the slots are what make them different
    assert len({(c["hero"], c["nav"], c["features"], c["motif"], c["radius"]) for c in cards}) == len(cards)


def test_business_types_point_at_real_styles_and_sections(client, auth):
    for b in client.get("/api/styles", headers=auth).json()["business_types"]:
        assert design_styles.get(b["style"]) is not None, b["key"]
        assert set(b["sections"]) <= set(design_styles.OPTIONAL_SECTIONS), b["key"]
        assert b["pages"] and b["pages"][0] == "home", b["key"]


def test_a_style_detail_composes_the_direction_it_will_build(client, auth):
    body = client.get("/api/styles/brutalist", headers=auth).json()
    assert body["style"]["key"] == "brutalist"
    assert body["direction"]["style_key"] == "brutalist"
    assert set(design_styles.REQUIRED_SECTIONS) <= set(body["direction"]["order"])
    assert set(body["business_types"]) <= set(design_styles.BUSINESS_BY_KEY)
    assert client.get("/api/styles/vaporwave", headers=auth).status_code == 404


# ------------------------------------------------------------------ the resolve preview is the stored brief

def test_a_chosen_style_makes_the_preview_exact(client, auth):
    spec = {"business_type": "saas", "style": "luxury", "features": ["monthly plans"], "audience": "ops leads"}
    r = client.post("/api/styles/resolve", json=spec, headers=auth).json()
    assert r["exact"] is True
    assert r["style"]["key"] == "luxury"
    assert r["direction"]["style_key"] == "luxury"
    assert r["pages"] == list(design_styles.pages_for("saas"))
    # business saas implies testimonials+pricing, the keyword "plans" implies pricing, luxury carries gallery
    assert r["spec"]["sections"] == ["testimonials", "pricing", "gallery"]
    assert set(r["sections"]) == {"testimonials", "pricing", "gallery"}
    assert {"features", "faq", "cta"} <= set(r["direction"]["order"])
    assert "pricing" in r["direction"]["order"]


def test_no_style_leaves_the_layout_to_the_run(client, auth):
    r = client.post("/api/styles/resolve", json={"business_type": "health"}, headers=auth).json()
    assert r["exact"] is False
    assert r["direction"] is None                      # nothing to compose until a style exists
    assert r["spec"]["sections"] == []                 # the brief's own list, untouched
    assert r["style"]["key"] == design_styles.BUSINESS_BY_KEY["health"].style
    assert set(r["sections"]) == {"team", "contact"}   # what the site type implies, shown as advice
    assert "No style chosen" in r["note"] and r["style"]["label"] in r["note"]


def test_a_colour_preference_is_reported_whatever_contrast_it_needed(client, auth):
    readable = client.post("/api/styles/resolve",
                           json={"business_type": "saas", "style": "startup", "color": "#4f46e5"},
                           headers=auth).json()
    assert "preferred colour #4f46e5" in readable["direction"]["color_note"]
    assert readable["direction"]["palette"]["primary"]

    # a light colour on a light style cannot stay as it is: the note says what happened, in the run trace
    awkward = client.post("/api/styles/resolve",
                          json={"business_type": "saas", "style": "minimal", "color": "#ffffff"},
                          headers=auth).json()
    assert awkward["direction"]["color_note"] != ""
    assert "preferred colour" in awkward["direction"]["color_note"]


def test_the_preview_stores_exactly_what_the_project_gets(client, auth):
    """The wizard's review step and POST /api/projects must agree, or the review is a preview of a lie."""
    spec = {"business_type": "education", "style": "store", "features": ["book a lesson"], "sections": ["team"]}
    resolved = client.post("/api/styles/resolve", json=spec, headers=auth).json()
    created = project(client, auth, spec, idea="A music practice coach for beginners")
    assert created["spec"]["sections"] == resolved["spec"]["sections"]
    assert created["spec"]["pages"] == resolved["pages"]
    assert created["spec"]["style"] == resolved["spec"]["style"]
    # brief (team) + what an education site implies (testimonials, pricing) + the asking for a lesson
    # (booking, its own block now) + the store style's own (gallery, contact)
    assert created["spec"]["sections"] == ["testimonials", "pricing", "gallery", "team", "booking", "contact"]


@pytest.mark.parametrize("bad", [
    {"business_type": "crypto"},          # not a site type the registry has
    {"style": "vaporwave"},               # not a style the builder can compose
    {"color": "sea blue"},                # not a hex value
    {"sections": ["reviews"]},            # not a section the crew can build
    {"pages": ["Pricing Page"]},          # not a page slug
])
def test_an_unknown_choice_is_refused_rather_than_swapped(client, auth, bad):
    r = client.post("/api/styles/resolve", json={"business_type": "saas", "style": "saas", **bad},
                    headers=auth)
    assert r.status_code == 422, bad
    assert client.post("/api/projects", json={"idea": "A habit tracker", "spec": bad},
                       headers=auth).status_code == 422, bad


# ------------------------------------------------------------------ the brief reaches the run

def test_a_plain_idea_still_creates_a_project(client, auth):
    """Nothing the wizard added may change what a one-field create did before it existed."""
    p = client.post("/api/projects", json={"idea": "A habit tracker for night-shift workers"},
                    headers=auth).json()
    assert p["spec"] == {"business_type": "other", "audience": "", "pages": ["home", "contact"],
                         "style": "", "color": "", "features": [], "tone": "", "sections": [],
                         "theme": {}, "feature_keys": [], "template": ""}
    assert p["name"] == "A habit tracker for night-shift workers"


def test_a_brief_with_no_style_keeps_the_sections_it_asked_for(client, auth):
    """The crew picks the style at build time, which is no reason to discard the user's own list."""
    p = project(client, auth, {"business_type": "other", "sections": ["contact", "pricing"]})
    assert p["spec"]["style"] == "" and p["spec"]["sections"] == ["contact", "pricing"]
    assert p["spec"]["pages"] == list(design_styles.pages_for("other"))


def test_a_styled_brief_stores_the_whole_section_plan(client, auth):
    p = project(client, auth, {"business_type": "agency", "style": "agency", "features": ["team page"],
                               "sections": ["contact"], "audience": "artists", "tone": "warm",
                               "color": "#7C3AED"})
    # the brief's own contact, plus what an agency site and the agency style both carry
    assert p["spec"]["sections"] == ["gallery", "team", "contact"]
    assert p["spec"]["color"] == "#7c3aed"
    assert p["spec"]["audience"] == "artists"


def test_the_features_a_brief_ticks_are_stored_and_reach_the_run(client, auth):
    """The wizard may only tick what the builder has source for, and the list must survive to the run.

    A brief's feature keys are a request, not a build: the page the crew generates is drawn from the same
    brief it always was, and these keys are what the workspace's Features panel offers when that page is
    waiting for approval.
    """
    p = project(client, auth, {"business_type": "store", "feature_keys": ["contact", "blog", "contact"]})
    assert p["spec"]["feature_keys"] == ["contact", "blog"], "the pick is kept, in order, without duplicates"
    rid = client.post(f"/api/projects/{p['id']}/runs", headers=auth).json()["id"]
    run = client.get(f"/api/runs/{rid}", headers=auth).json()
    assert run["spec"]["feature_keys"] == ["contact", "blog"]
    assert run["state"]["spec"]["feature_keys"] == ["contact", "blog"]
    # the page itself is unchanged by a tick: nothing was generated for a feature nobody built
    assert "<section class=\"lc-features\"" not in client.get(f"/api/runs/{rid}/html", headers=auth).text


def test_a_brief_cannot_ask_for_a_feature_the_builder_has_no_source_for(client, auth):
    bad = {"business_type": "saas", "feature_keys": ["payments"]}
    r = client.post("/api/projects", json={"idea": "A invoicing tool", "spec": bad}, headers=auth)
    assert r.status_code == 422, r.text
    assert "payments" in r.text and "no feature source" in r.text
    assert client.post("/api/styles/resolve", json=bad, headers=auth).status_code == 422


def test_a_run_is_built_in_the_style_the_brief_named(client, auth):
    p = project(client, auth, {"business_type": "education", "style": "brutalist", "sections": ["pricing"]})
    rid = client.post(f"/api/projects/{p['id']}/runs", headers=auth).json()["id"]
    run = client.get(f"/api/runs/{rid}", headers=auth).json()
    assert run["status"] == "awaiting_approval", run["error"]
    assert run["spec"]["style"] == "brutalist"
    style = run["state"]["style"]
    assert style["style_key"] == "brutalist"
    assert (style["hero"], style["features"], style["motif"]) == ("poster", "manifest", "outline-thick")
    assert "pricing" in style["order"]
    assert run["state"]["design"]["layout_style"] == "brutalist"
    # the project list reports it the same way the comparison page reads it
    listed = client.get(f"/api/projects/{p['id']}", headers=auth).json()["runs"][0]
    assert listed["style_key"] == "brutalist" and listed["style_label"] == "Brutalist & bold"


def test_a_run_with_no_style_choice_gets_a_real_style_anyway(client, auth):
    rid = client.post(f"/api/projects/{project(client, auth, {})['id']}/runs", headers=auth).json()["id"]
    key = client.get(f"/api/runs/{rid}", headers=auth).json()["state"]["style"]["style_key"]
    assert key in design_styles.keys()


def test_one_run_can_differ_from_the_project_it_came_from(client, auth):
    p = project(client, auth, {"business_type": "saas", "style": "saas"})
    rid = client.post(f"/api/projects/{p['id']}/runs", headers=auth, json={"style": "glass"}).json()["id"]
    run = client.get(f"/api/runs/{rid}", headers=auth).json()
    assert run["spec"]["style"] == "glass" and run["state"]["style"]["style_key"] == "glass"
    assert run["spec"]["business_type"] == "saas"           # the rest of the brief still applies
    assert client.get(f"/api/projects/{p['id']}", headers=auth).json()["spec"]["style"] == "saas"


def test_compare_builds_one_page_per_style_on_the_same_brief(client, auth):
    p = project(client, auth, {"business_type": "store", "sections": ["contact"]})
    res = client.post(f"/api/projects/{p['id']}/compare", headers=auth,
                      json={"styles": ["minimal", "gradient"]})
    assert res.status_code == 202, res.text
    started = res.json()["runs"]
    assert [s["style"] for s in started] == ["minimal", "gradient"]
    assert [s["label"] for s in started] == ["Minimalist & clean", "Gradient & 3D-inspired"]

    listed = client.get(f"/api/projects/{p['id']}", headers=auth).json()["runs"]
    assert sorted(r["style_key"] for r in listed) == ["gradient", "minimal"]
    assert all(r["status"] == "awaiting_approval" for r in listed)
    assert len({r["id"] for r in listed}) == 2
    # each variation keeps the brief and differs only in the style it was told to build in
    html = {r["style_key"]: client.get(f"/api/runs/{r['id']}/files/index.html", headers=auth).text
            for r in listed}
    assert html["minimal"] != html["gradient"]


def test_compare_refuses_a_batch_it_cannot_build(client, auth):
    p = project(client, auth, {"business_type": "saas"})
    before = client.get(f"/api/projects/{p['id']}", headers=auth).json()["runs"]
    for body in ({"styles": []}, {"styles": ["saas"] * 5}, {"styles": ["vaporwave"]}):
        assert client.post(f"/api/projects/{p['id']}/compare", headers=auth, json=body).status_code == 422
    # an unknown style is caught before anything is queued, so a refused batch leaves no half-started runs
    assert client.get(f"/api/projects/{p['id']}", headers=auth).json()["runs"] == before


def test_another_users_brief_is_not_readable_or_runnable(client, auth):
    p = project(client, auth, {"business_type": "saas", "style": "saas"})
    other = client.post("/api/auth/register", json={"email": "other@example.com",
                                                   "password": "supersecret1"}).json()
    h = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"/api/projects/{p['id']}", headers=h).status_code == 404
    assert client.post(f"/api/projects/{p['id']}/runs", headers=h).status_code == 404
    assert client.post(f"/api/projects/{p['id']}/compare", headers=h, json={"styles": ["saas"]}).status_code == 404
