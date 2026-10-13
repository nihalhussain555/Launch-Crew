"""The template gallery: the registry, the pages it composes, and the API in front of both.

A gallery is the easiest place in this product to overstate things, so these tests check the two claims
it makes:

* every content block a card names is a block the page builder has rendering code for, and it appears in
  the page that card previews - not as a relabelled copy of another block, but as its own markup;
* every feature a card names carries the feature catalog's own status, so a cart, an inbox or a calendar
  is shown as something the owner still has to connect.

Then the brief a card turns into has to survive: `SiteSpec` accepts it, the project stores it, the run
builds it, and the page that reaches the approval gate still carries those blocks.

And because a card now shows a designed page rather than a wireframe, the two ways this gallery could
overstate itself are checked directly: every picture is inlined, sized, labelled as a sample and small
enough for the workspace, and every per-template art direction changes the page's composition - not just
its colours.
"""
import re

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents import art
from app.agents import capabilities as caps
from app.agents import looks
from app.agents import styles as design_styles
from app.agents import templates as site_templates
from app.agents import variants
from app.agents.schemas import Design, SiteSpec
from app.api import routes_auth
from app.llm import mock
from app.main import app
from app.services import workspace_manager
from app.tools import audit_perf, audit_util
from app.tools import browser_checks
from app.tools.sanitizer import sanitize_html
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
    r = client.post("/api/auth/register", json={"email": "gallery@example.com",
                                                "password": "supersecret1", "name": "Gallery"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def page_for(t: site_templates.Template) -> str:
    """The page this template composes, drawn by the same builder an offline run renders with."""
    direction = variants.direction_for(f"template:{t.key}", site_templates.spec_for(t))
    return mock.design_sample_page(direction, t.business, t.summary)


# ------------------------------------------------------------------ the registry itself

def test_twenty_templates_in_six_categories_every_card_being_in_one():
    assert len(site_templates.TEMPLATE_LIST) == 20
    assert len(set(site_templates.keys())) == 20
    assert list(site_templates.keys()) == [t.key for t in site_templates.TEMPLATE_LIST]
    assert [t.label for t in site_templates.TEMPLATE_LIST] == [   # the names the brief asked for
        "Corporate Pro", "Creative Agency", "Luxury Editorial", "SaaS Launchpad", "AI Future",
        "Developer Portfolio", "Fashion Boutique", "Tech Store", "Beauty & Lifestyle",
        "Restaurant & Café", "Real Estate Pro", "Healthcare & Clinic", "Legal & Consulting",
        "EdTech Academy", "Editorial & Blog", "Events & Conference", "Startup Waitlist",
        "Mobile App Showcase", "Personal Brand", "Mobile Service Center"]
    for t in site_templates.TEMPLATE_LIST:
        assert t.category in site_templates.CATEGORIES, t.key
    assert {t.category for t in site_templates.TEMPLATE_LIST} == set(site_templates.CATEGORIES)
    # every category has something in it: a heading with no cards under it is a broken gallery
    assert all(site_templates.in_category(c) for c in site_templates.CATEGORIES)


def test_a_card_only_names_things_the_other_registries_actually_have():
    styles = {s.key for s in design_styles.STYLES}
    for t in site_templates.TEMPLATE_LIST:
        assert t.style in styles, f"{t.key}: no such design style"
        assert t.business in design_styles.BUSINESS_BY_KEY, f"{t.key}: no such site type"
        assert set(t.sections) <= set(design_styles.OPTIONAL_SECTIONS), f"{t.key}: unknown block"
        assert t.sections == tuple(s for s in design_styles.OPTIONAL_SECTIONS if s in t.sections), \
            f"{t.key}: blocks out of page order"
        for key in t.features:
            assert caps.get(key) is not None, f"{t.key}: {key} is not in the feature catalog"
        assert t.ideas and t.audience and t.tone and t.pages, f"{t.key}: an empty brief"


def test_every_card_says_what_the_owner_still_has_to_supply():
    """A template that shows prices, listings or credentials must say whose they are."""
    for t in site_templates.TEMPLATE_LIST:
        assert t.notes, f"{t.key}: no honest note about what is still missing"
        assert all(len(n) > 30 for n in t.notes), f"{t.key}: a note too short to mean anything"


def test_the_blocks_a_card_lists_are_the_ones_the_builder_documents():
    for t in site_templates.TEMPLATE_LIST:
        blocks = t.blocks()
        assert [b["key"] for b in blocks][:3] == list(design_styles.REQUIRED_SECTIONS)
        assert [b["key"] for b in blocks][3:] == list(t.sections)
        for b in blocks:
            assert b["carries"], f"{t.key}/{b['key']}: a block with no description"


def test_section_cards_cover_the_whole_vocabulary():
    cards = design_styles.section_cards()
    assert [c["key"] for c in cards] == list(design_styles.SECTION_KEYS)
    assert {c["key"] for c in cards if c["always"]} == set(design_styles.REQUIRED_SECTIONS)
    assert all(c["label"] and c["carries"] for c in cards)


# ------------------------------------------------------------------ what the pages are made of

@pytest.mark.parametrize("key", site_templates.keys())
def test_every_block_a_card_promises_is_on_the_page_it_previews(key):
    t = site_templates.get(key)
    html = page_for(t)
    clean, violations = sanitize_html(html)
    assert not violations, f"{key}: the builder's own page gets stripped: {violations}"
    for section in t.sections:
        assert f'id="{section}"' in html, f"{key}: advertises {section}, page has no {section}"
    for core in design_styles.REQUIRED_SECTIONS:
        assert f'id="{core}"' in html, f"{key}: a page without its {core}"


@pytest.mark.parametrize("key", site_templates.keys())
def test_a_page_never_presents_invented_facts_as_this_businesss_own(key):
    """Placeholder content has to be labelled where it stands, on every template."""
    t = site_templates.get(key)
    html = page_for(t)
    copy = mock._sample_copy("This page", "you", t.summary, list(t.sections), t.business)
    labelled = any((isinstance(v, dict) and v.get("sample")) or
                   (isinstance(v, list) and any(x.get("sample") for x in v if isinstance(x, dict)))
                   for v in copy.values())
    assert labelled == ("Sample content" in html), f"{key}: sample content on the page without saying so"


def test_twenty_cards_do_not_make_twenty_copies_of_one_page():
    built = {t.key: page_for(t) for t in site_templates.TEMPLATE_LIST}
    assert len(set(built.values())) == 20, "two templates build the same page"
    # and the difference is structure, not a recolour: the section sets differ between categories
    for a, b in [("restaurant-cafe", "developer-portfolio"), ("tech-store", "legal-consulting"),
                 ("edtech-academy", "beauty-lifestyle"), ("events-conference", "corporate-pro")]:
        assert set(site_templates.get(a).sections) != set(site_templates.get(b).sections)


def test_each_block_is_drawn_as_itself_not_as_a_relabelled_list():
    """A menu is not a testimonial in another colour: each block has its own element shape."""
    everything = variants.direction_for("test:every-block", site_templates.spec_for(
        site_templates.get("corporate-pro")))
    sections = mock._extra_sections(everything, mock._sample_copy(
        "The Test Page", "you", "a page that proves the builder",
        list(design_styles.OPTIONAL_SECTIONS), "restaurant"))
    assert set(sections) == set(design_styles.OPTIONAL_SECTIONS)
    for marker in ("dl class=\"facts\"", "ul class=\"figures\"", "ul class=\"svc\"",
                   "article class=\"case\"", "class=\"ware\"", "class=\"demo\"", "ol class=\"tl\"",
                   "class=\"hours\"", "id=\"book\""):
        assert any(marker in v for v in sections.values()), marker


def test_business_voice_names_the_blocks_the_way_the_trade_does():
    menu = page_for(site_templates.get("restaurant-cafe"))
    assert "<h2>Menu</h2>" in menu and "Book a table" in menu and "Opening hours" in menu
    courses = page_for(site_templates.get("edtech-academy"))
    assert "<h2>Courses</h2>" in courses and "Instructors" in courses
    clinic = page_for(site_templates.get("healthcare-clinic"))
    assert "<h2>Treatments</h2>" in clinic and "Practitioners" in clinic


def test_the_booking_block_says_where_a_request_actually_goes():
    """These pages have no server, so a booking form must admit it stores nothing."""
    for key in ("restaurant-cafe", "healthcare-clinic", "legal-consulting", "events-conference"):
        html = page_for(site_templates.get(key))
        assert 'id="book"' in html, key
        assert "This page stores nothing" in html, f"{key}: a booking form that implies otherwise"


# ------------------------------------------------------------------ the pictures on the page

IMG = re.compile(r"<img\b[^>]*>")
ATTR = re.compile(r'(\w[\w-]*)="([^"]*)"')


def images_in(html: str) -> list[dict]:
    """Every `<img>` on a page, as its attribute dict, so a test can read the tags rather than grep them."""
    return [dict(ATTR.findall(tag)) for tag in IMG.findall(html)]


def page_shape(html: str) -> str:
    """The page with its colours and its pictures removed: what is left is the structure it was drawn in,
    which is the only fair thing to compare two templates that share a design style on."""
    html = re.sub(r":root\{[^}]*\}", "", html)
    return re.sub(r"data:image/[^\"']+", "", html)


@pytest.mark.parametrize("key", site_templates.keys())
def test_every_picture_is_inlined_and_carries_its_own_size_and_alt(key):
    """The page is one file with a `data:`-only CSP, so a picture that lives somewhere else is a broken
    picture - and an unsized, unlabelled one is a layout jump and a screen reader saying nothing."""
    imgs = images_in(page_for(site_templates.get(key)))
    assert imgs, f"{key}: a template page with no picture at all"
    for tag in imgs:
        assert tag["src"].startswith("data:image/"), f"{key}: {tag['src'][:40]} is not inlined"
        assert int(tag["width"]) > 0 and int(tag["height"]) > 0, f"{key}: an unsized picture"
        assert tag["alt"].strip(), f"{key}: a picture with nothing to say about itself"
        assert tag["loading"] in ("lazy", "eager"), f"{key}: a picture that loads whenever the browser feels like it"


@pytest.mark.parametrize("key", site_templates.keys())
def test_a_page_never_reaches_outside_itself_for_a_picture(key):
    """Nothing on the page may ask a server for anything: not an img, not a stylesheet, not a font. The
    CSP would refuse it and the sanitizer would delete it, so a remote reference is a broken picture."""
    html = page_for(site_templates.get(key))
    for shape in ('src="http', "src='http", "srcset=", 'url(http', 'url("//', "<link", "@import"):
        assert shape not in html, f"{key}: {shape} on a page that has to stand alone"


@pytest.mark.parametrize("key", site_templates.keys())
def test_a_picture_on_the_page_is_announced_as_a_sample(key):
    """These are our photographs, not the business's. A visitor - and the owner reading their own page -
    has to be able to tell which is which."""
    html = page_for(site_templates.get(key))
    assert "Sample photography" in html or "words and pictures" in html, \
        f"{key}: pictures on the page with no note saying they are placeholders"


def test_a_brief_that_chose_no_template_gets_the_page_it_always_had():
    """The art layer is additive: no look means no photography, and the CSS drawings stay."""
    plain = variants.direction_for("a hand-written brief",
                                   {"business_type": "saas", "idea": "a launch page"})
    assert plain.look == ""
    html = mock.design_sample_page(plain, "saas", "a launch page")
    assert not IMG.search(html), "a brief that named no template was given photography it never asked for"
    assert "Sample photography" not in html


def test_a_template_that_runs_out_of_picture_budget_shows_a_plate_not_a_hole():
    """`_plate` is what every card slot goes through, so the fallback is on the shipped path, not a theory."""
    tiles = art.art_for("tech-store")["tiles"]
    assert tiles, "tech-store ships no tiles to spend"
    with_tiles = mock._plate(mock._Tiles(tiles[:1], 1), "a device")
    empty = mock._plate(mock._Tiles([], 0), "a device")
    assert with_tiles.startswith("<img"), with_tiles[:60]
    assert empty == '<div class="ph" role="img" aria-label="a device illustration"></div>', empty


@pytest.mark.parametrize("key", site_templates.keys())
def test_the_photography_on_a_page_is_bounded_before_it_is_inlined(key):
    """Six pictures maximum, whatever the copy asks for: a page of stock imagery is a page nobody loads."""
    shots = art.art_for(key)
    assert shots["shots"] <= art.MAX_SHOTS
    assert len(shots["tiles"]) <= art.MAX_TILES
    assert shots["bytes"] <= art.BUDGET_B, f"{key}: {shots['bytes']} bytes of picture over budget"
    if shots["hero"]:
        assert shots["hero"]["bytes"] <= art.HERO_MAX_B, f"{key}: hero of {shots['hero']['bytes']} bytes"
    for tile in shots["tiles"]:
        assert tile["bytes"] <= art.TILE_MAX_B, f"{key}: a {tile['bytes']} byte card picture"


@pytest.mark.parametrize("key", site_templates.keys())
def test_the_pictures_are_the_weight_and_the_page_still_passes_its_own_audit(key):
    """The performance gate measures markup and CSS, because that is what this builder can shorten. The
    pictures have to stay inside the line a single workspace file is allowed, or the run cannot save them."""
    html = page_for(site_templates.get(key))
    total = len(html.encode())
    media = sum(len(t["src"]) for t in images_in(html)) * 3 // 4
    findings = {f["id"]: f for f in audit_perf.scan(html)}
    assert findings["payload"]["status"] == audit_util.PASS, f"{key}: {findings['payload']['detail']}"
    assert findings["embedded_media"]["status"] == audit_util.PASS, f"{key}: {findings['embedded_media']['detail']}"
    assert total < workspace_manager.MAX_WORKSPACE_FILE_BYTES, f"{key}: a {total}-byte page the workspace refuses"
    assert total - media < 60 * 1024, f"{key}: {total - media} bytes of markup and CSS, {media} of picture"


# ------------------------------------------------------------------ art direction per template

def test_twenty_looks_for_twenty_cards_and_each_one_takes_its_styles_colours_and_scale():
    """The brief's rule: not the same page in another colour. Every look owns a palette, a display scale
    and a set of faces its style default has neither of; where a template keeps its style's composition it
    is because that style was drawn for this trade, which is what the group test below then checks."""
    assert len(looks.LOOKS) == len(site_templates.TEMPLATE_LIST) == 20
    assert [x.key for x in looks.LOOKS] == list(site_templates.keys())
    for t in site_templates.TEMPLATE_LIST:
        base = design_styles.get(t.style)
        look = looks.get(t.key)
        styled, applied = looks.apply(base, t.key)
        assert applied == t.key and look is not None, t.key
        assert styled.palette == look.palette and styled.palette != base.palette, f"{t.key}: no palette of its own"
        assert styled.tokens["h1"] == look.tokens["h1"] and styled.tokens["h1"] != base.tokens["h1"], \
            f"{t.key}: the display line is still the style's"
        assert styled.fonts == look.fonts, f"{t.key}: the faces the look names never reach the page"
        # a look styles the page; it never rewrites the brief the owner filled in
        assert styled.sections == base.sections


def test_every_look_palette_clears_the_contrast_rule_the_designer_enforces():
    """`Design` refuses a palette that misses WCAG AA, so a card whose colours are a point short is a card
    whose run dies at the designer step. The gallery cannot promise a page its own schema rejects."""
    fonts = design_styles.STYLES[0].fonts
    for look in looks.LOOKS:
        Design.model_validate({"palette": dict(look.palette), "fonts": fonts, "layout_style": look.key})


def test_two_cards_on_one_style_compose_two_different_pages():
    """Six of the twelve design styles carry two or three templates each. Inside a group no two cards may
    draw the same composition, and the two pages must still differ once the colours and the photography
    are taken out of them - which is the difference between a template and a repaint."""
    groups = {}
    for t in site_templates.TEMPLATE_LIST:
        groups.setdefault(t.style, []).append(t.key)
    shared = {style: keys for style, keys in groups.items() if len(keys) > 1}
    assert len(shared) == 6 and sum(len(keys) for keys in shared.values()) == 14, shared
    for style, keys in shared.items():
        base = design_styles.get(style)
        drawn = {}
        for key in keys:
            styled, _ = looks.apply(base, key)
            drawn[key] = (styled.hero, styled.nav, styled.features, styled.motif, styled.radius)
        assert len(set(drawn.values())) == len(keys), f"{style}: {drawn} - two cards drawing one page"
        pages = {key: page_shape(page_for(site_templates.get(key))) for key in keys}
        assert len(set(pages.values())) == len(keys), f"{style}: the same structure in two colourways"


def test_an_unknown_look_is_no_look_rather_than_a_substitute():
    base = design_styles.get(site_templates.get("tech-store").style)
    styled, applied = looks.apply(base, "no-such-template")
    assert applied == "" and styled == base


@pytest.mark.parametrize("key", site_templates.keys())
def test_a_saved_run_still_draws_the_page_it_drew_before(key):
    """The look travels through the run state, so resuming a project does not restyle it."""
    t = site_templates.get(key)
    direction = variants.direction_for(f"template:{t.key}", site_templates.spec_for(t))
    stored = variants.as_dict(direction)
    assert stored["look"] == t.key
    again = variants.from_dict(stored)
    assert again.look == direction.look and again.hero == direction.hero
    assert mock.design_sample_page(again, t.business, t.summary) == \
        mock.design_sample_page(direction, t.business, t.summary)


def test_a_look_only_promises_furniture_the_builder_actually_draws():
    """`ornaments` describes the page, so the two have to agree in both directions: a name the builder
    ignores would be a field that lies, and a row the builder draws unprompted is a claim nobody made."""
    built = {t.key: page_for(t) for t in site_templates.TEMPLATE_LIST}
    for look in looks.LOOKS:
        assert set(look.ornaments) <= set(looks.ORNAMENTS), f"{look.key}: {look.ornaments}"
        html = built[look.key]
        assert ("stat-pills" in look.ornaments) == ('class="pills"' in html), \
            f"{look.key}: pill row and pill claim disagree"
        assert ("device-frame" in look.ornaments) == ('class="frame phone' in html), \
            f"{look.key}: phone frame and device claim disagree"


# ------------------------------------------------------------------ honest feature claims

def test_a_feature_the_owner_must_connect_is_never_shown_as_done():
    for t in site_templates.TEMPLATE_LIST:
        for row in t.feature_rows():
            cap = caps.get(row["key"])
            assert row["status"] == cap.status, f"{t.key}/{row['key']}: status invented by the card"
            assert row["status_label"] == caps.STATE_LABEL[cap.status]
            assert row["setup"] == list(cap.setup) and row["limits"] == cap.limits
        assert t.weakest() == max((r["status"] for r in t.feature_rows()),
                                  key=["generated", "scaffold", "needs-external-setup"].index,
                                  default="generated")


def test_a_provider_backed_template_says_so_on_its_card():
    for key in ("fashion-boutique", "tech-store", "beauty-lifestyle"):
        card = site_templates.as_card(site_templates.get(key))
        assert card["status"] == "needs-external-setup", f"{key}: a shop presented as finished"
        assert any(f["key"] == "catalog" and "payment" in f["limits"].lower() or
                   f["key"] == "pricing" for f in card["features"])
    # and the badge is the catalog's own worst status for that card's requests, never the card's invention
    for key in ("developer-portfolio", "mobile-app-showcase", "corporate-pro"):
        t = site_templates.get(key)
        card = site_templates.as_card(t)
        assert card["status"] == t.weakest() == max(
            (r["status"] for r in t.feature_rows()),
            key=["generated", "scaffold", "needs-external-setup"].index)
        # a card that needs the owner's keys says what is missing in words, not only in a badge
        if card["status"] == "needs-external-setup":
            assert card["notes"], f"{key}: a warning badge with nothing to back it up"


# ------------------------------------------------------------------ the brief a card turns into

def test_a_template_makes_a_spec_the_wizard_and_the_pipeline_already_accept():
    for t in site_templates.TEMPLATE_LIST:
        spec = SiteSpec.model_validate(site_templates.spec_for(t))
        assert spec.template == t.key and spec.style == t.style and spec.business_type == t.business
        assert set(t.sections) <= set(spec.sections)
        assert spec.feature_keys == list(t.features)
        # the idea is a project field, not a spec field: the wizard takes it from the same dict
        assert site_templates.spec_for(t)["idea"] == t.ideas[0]
    with pytest.raises(ValidationError):
        SiteSpec(template="not-a-template")


def test_a_brief_can_still_ask_for_more_blocks_than_a_card_ships_with():
    """The block cap moved from 5 to 12 so a template's own composition fits; a hand-written brief that
    picks twelve still validates, and a thirteenth is trimmed rather than rejected."""
    spec = SiteSpec(sections=list(design_styles.OPTIONAL_SECTIONS))
    assert len(spec.sections) == 12
    assert spec.sections == list(design_styles.OPTIONAL_SECTIONS[:12]), "the trim keeps the page's order"


def test_get_returns_nothing_for_an_unknown_card_rather_than_a_substitute():
    assert site_templates.get("") is None and site_templates.get("nonsense") is None


# ------------------------------------------------------------------ the gallery over HTTP

def test_the_gallery_needs_a_signed_in_user(client):
    assert client.get("/api/templates").status_code == 401
    assert client.get("/api/templates/tech-store").status_code == 401
    assert client.get("/api/templates/tech-store/preview").status_code == 401
    assert client.get("/api/templates/sections").status_code == 401


def test_the_gallery_serves_the_registry_the_builder_uses(client, auth):
    body = client.get("/api/templates", headers=auth).json()
    assert body["counts"] == {"templates": 20, "categories": 6}
    assert [t["key"] for t in body["templates"]] == list(site_templates.keys())
    assert body["categories"] == list(site_templates.CATEGORIES)
    card = body["templates"][0]
    assert {"blocks", "features", "notes", "status", "status_label", "ideas", "spec"} - {"spec"} <= set(card)
    assert all(f["status_label"] for f in card["features"])


def test_the_section_catalogue_matches_the_builders_vocabulary(client, auth):
    body = client.get("/api/templates/sections", headers=auth).json()
    assert body["cards"] == design_styles.section_cards()
    assert body["optional"] == list(design_styles.OPTIONAL_SECTIONS)


def test_the_gallery_payload_carries_every_field_the_cards_read(client, auth):
    """The gallery, the detail page and the wizard prefill are drawn from these payloads alone: a renamed
    or dropped field is a blank space in the UI, not a message the user can act on."""
    card = client.get("/api/templates", headers=auth).json()["templates"][0]
    assert {"key", "label", "category", "industries", "summary", "style_label", "style_blurb",
            "business_label", "blocks", "features", "notes", "status", "status_label", "idea",
            "audience", "tone", "pages", "asks"} <= set(card)
    assert all({"key", "label", "carries"} <= set(b) for b in card["blocks"])
    assert all({"key", "label", "status", "status_label", "needs", "setup", "env", "limits"} <= set(f)
               for f in card["features"])
    assert all(isinstance(n, str) and n for n in card["notes"])

    d = client.get("/api/templates/restaurant-cafe", headers=auth).json()
    # the wizard prefills exactly these spec fields, and takes the idea from the card: SiteSpec has none
    assert {"business_type", "audience", "pages", "style", "color", "features", "tone", "sections",
            "feature_keys", "template"} <= set(d["spec"])
    assert "idea" not in d["spec"] and d["template"]["idea"]
    assert {"html", "note", "sections", "blocks", "style_label", "sample_copy"} <= set(
        client.get("/api/templates/restaurant-cafe/preview", headers=auth).json())


def test_no_card_ships_more_blocks_than_the_wizard_allows():
    """NewProject's picker caps at SiteSpec's twelve; a longer composition would prefill a trimmed brief."""
    for t in site_templates.TEMPLATES:
        assert len(t.sections) <= 12, t.key


def test_a_detail_answer_is_the_brief_a_project_would_store(client, auth):
    d = client.get("/api/templates/legal-consulting", headers=auth).json()
    assert d["template"]["label"] == "Legal & Consulting"
    assert d["spec"]["template"] == "legal-consulting" and d["spec"]["style"] == "editorial"
    assert set(d["template"]["sections"]) <= set(d["sections_built"])
    assert d["direction"]["style_key"] == "editorial"
    assert "booking" in d["direction"]["order"]


def test_a_preview_is_the_real_page_not_a_picture_of_one(client, auth):
    p = client.get("/api/templates/restaurant-cafe/preview", headers=auth).json()
    assert p["sample_copy"] is True and p["style_key"] == "store"
    assert p["html"].startswith("<!DOCTYPE html>")
    for section in p["sections"]:
        assert f'id="{section}"' in p["html"], section
    assert "Menu" in p["html"] and "This page stores nothing" in p["html"]
    # the copy is labelled as sample wherever it stands in
    assert "Sample content" in p["html"]


def test_an_unknown_template_is_a_404_naming_the_real_ones(client, auth):
    for path in ("/api/templates/sports-club", "/api/templates/sports-club/preview"):
        r = client.get(path, headers=auth)
        assert r.status_code == 404 and "corporate-pro" in r.json()["detail"]


def test_a_card_starts_a_project_that_reaches_the_gate_with_its_blocks(client, auth):
    """End to end: the gallery's composition is the one the run builds and stops for review on."""
    d = client.get("/api/templates/edtech-academy", headers=auth).json()
    t = d["template"]
    created = client.post("/api/projects", json={"idea": t["idea"], "spec": d["spec"]}, headers=auth)
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["spec"]["template"] == "edtech-academy"
    assert set(t["sections"]) <= set(project["spec"]["sections"])

    rid = client.post(f"/api/projects/{project['id']}/runs", headers=auth).json()["id"]
    run = client.get(f"/api/runs/{rid}", headers=auth).json()
    assert run["status"] == "awaiting_approval", run["error"]
    assert run["state"]["spec"]["template"] == "edtech-academy"
    assert set(t["sections"]) <= set(run["state"]["spec"]["sections"])

    html = client.get(f"/api/runs/{rid}/html", headers=auth).text
    for section in t["sections"]:
        assert f'id="{section}"' in html, f"the built page is missing the {section} the card advertised"
    assert "Courses" in html
