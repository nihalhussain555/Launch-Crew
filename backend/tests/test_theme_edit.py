"""Theme editing on a built page: the token patch, its limits, and the proposal lifecycle over HTTP.

The claim under test is the one the brief makes: a theme is applied *globally* to compatible components,
not by patching every element. That only holds if the edit is a value change inside the page's `:root`
block, so these tests compare the rest of the document byte for byte and refuse any flow that would have
to touch it. The other half is honesty about reach - a page that does not read the tokens gets a refusal,
not a patch that changes nothing while reporting success.

The lifecycle tests are the workspace ones again (propose, review, apply, conflict, reject) with a theme's
shape: no model call, one file, and history that says a theme edit did it.
"""
import re

import pytest
from fastapi.testclient import TestClient

from app.agents import styles as design_styles
from app.agents import theme as design_theme
from app.agents import variants
from app.agents.schemas import CopyDoc
from app.api import routes_auth
from app.llm.mock import build_page
from app.main import app
from app.services import theme_edit, workspace_manager
from app.services.workspace_manager import WorkspaceError
from app.tools import browser_checks
from tests.conftest import GOOD_CHECKS

CONTROLS = {"family": "futuristic", "mode": "dark", "card": "glass", "radius": "pill", "density": "compact"}

COPY = CopyDoc.model_validate({
    "product_name": "Nightly", "headline": "Habits for night-shift workers", "subheadline": "A calm tracker",
    "features": [{"title": f"F{i}", "description": f"D{i}"} for i in range(1, 4)],
    "faq": [{"question": f"Q{i}?", "answer": f"A{i}"} for i in range(1, 4)],
    "cta": {"label": "Get early access", "supporting_text": "We email you at launch"}}).model_dump()


def drawn(style_key="startup", **spec_kw) -> str:
    """The page the crew would publish for a run built in this style."""
    spec = {"style": style_key, **spec_kw}
    direction = variants.direction_for("a habit tracker for night-shift workers", spec)
    return build_page({"copy": COPY, "direction": variants.as_dict(direction),
                       "design": {"palette": dict(direction.palette), "fonts": dict(direction.fonts),
                                  "layout_style": direction.layout_style}})


def block(text: str) -> dict:
    """The custom properties of the page's global token block, as a name -> value map."""
    span = theme_edit.global_root(text)
    assert span is not None, "no :root block"
    return {name: value.strip() for name, value in
            re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;{}]+)", text[span[1]:span[2]])}


def rest_of(page: str) -> str:
    """Everything the token block does not cover: the selectors, the rules, the markup."""
    span = theme_edit.global_root(page)
    return page[:span[1]] + page[span[2]:]


def patched(page: str, controls: dict) -> str:
    direction = variants.retheme(variants.direction_for("a habit tracker", {"style": "startup"}),
                                 design_theme.as_stored(design_theme.resolve(controls)))
    plan = theme_edit.plan({"index.html": page}, direction)
    return workspace_manager.apply_op(page, plan["changes"][0])


# ------------------------------------------------------------------ the patch itself

def test_the_token_block_found_is_the_global_one_not_a_responsive_override():
    """`:root` appears twice in a built page - the block and the mobile override inside `@media`."""
    page = drawn()
    span = theme_edit.global_root(page)
    assert page[span[0]:span[0] + 5] == ":root"
    assert "--bg" in page[span[1]:span[2]]
    assert "@media" not in page[:span[0]]                     # depth zero, so not nested in a rule
    assert page.count(":root{") > 1                           # and the override is still down the page


def test_a_theme_edit_changes_values_and_leaves_the_rest_of_the_document_alone():
    page = drawn()
    after = patched(page, CONTROLS)
    before_vars, after_vars = block(page), block(after)
    changed = {name for name in after_vars if before_vars.get(name) != after_vars.get(name)}
    assert changed >= {"--bg", "--primary", "--radius", "--card-blur", "--line"}
    assert after_vars["--radius"] == "999px" and after_vars["--card-blur"].startswith("blur(")
    # the proof that this is a token edit: the rules and markup are identical, character for character
    assert rest_of(after) == rest_of(page)
    assert after.count("var(--") == page.count("var(--")


def test_the_responsive_override_is_left_relative():
    """Mobile padding is a `calc()` of the same tokens, so a density change reaches it without an edit."""
    page = drawn()
    after = patched(page, {**CONTROLS, "density": "roomy"})
    mobile = re.search(r"@media[^{]*\{(?P<body>[^:]*:root\{[^}]*\})", after).group("body")
    assert "calc(var(--pad-half)" in mobile


def test_a_page_that_declares_no_tokens_is_refused_rather_than_rewritten():
    stripped = drawn().replace(":root{", "#not-tokens{", 1)
    with pytest.raises(WorkspaceError) as exc:
        theme_edit.plan({"index.html": stripped}, variants.direction_for("a habit tracker", {"style": "startup"}))
    assert "no `:root` block" in exc.value.message
    assert exc.value.status == 409


def test_replanning_a_theme_that_is_already_drawn_says_so():
    """A second apply of the same theme must not be able to report a change it did not make."""
    page = patched(drawn(), CONTROLS)
    with pytest.raises(WorkspaceError) as exc:
        theme_edit.plan({"index.html": page},
                        variants.retheme(variants.direction_for("a habit tracker", {"style": "startup"}),
                                         design_theme.as_stored(design_theme.resolve(CONTROLS))))
    assert "already hold" in exc.value.message


def test_coverage_tells_apart_declared_and_addable_and_unreachable():
    """A token the block declares, one only a rule reads, and one nothing reads - three different answers."""
    page = drawn().replace("--gap:20px;", "", 1).replace("gap:var(--gap)", "gap:14px")
    page = page.replace("border-radius:var(--radius)", "border-radius:9px", 1)
    direction = variants.direction_for("a habit tracker", {"style": "startup", "theme": CONTROLS})
    measured = theme_edit.coverage({"index.html": page}, direction)
    assert "--bg" in measured["declared"]
    assert "--gap" not in measured["declared"] and "--gap" in measured["reached"]
    assert "--radius" in measured["reached"]                  # declared, even though one rule ignores it


# ------------------------------------------------------------------ retheme keeps the design

def test_retheming_a_run_redraws_it_without_moving_its_layout():
    before = variants.direction_for("a habit tracker", {"style": "brutalist"})
    after = variants.retheme(before, design_theme.as_stored(design_theme.resolve(CONTROLS)))
    for slot in ("style_key", "layout_style", "hero", "nav", "features", "motif", "order"):
        assert getattr(after, slot) == getattr(before, slot), slot
    assert after.palette != before.palette and after.tokens["radius"] == "999px"
    assert after.theme == design_theme.as_stored(design_theme.resolve(CONTROLS))


def test_a_direction_with_no_registry_style_cannot_be_re_themed_in_place():
    """A legacy run has no style for density to be relative to; inventing one would be a substitution."""
    legacy = variants.compose_legacy(variants.LEGACY_THEMES[0], "band", "checklist", "glow",
                                     ("features", "faq", "cta"))
    with pytest.raises(ValueError):
        variants.retheme(legacy, design_theme.as_stored(design_theme.resolve(CONTROLS)))


# ------------------------------------------------------------------ over HTTP

@pytest.fixture
def client(monkeypatch):
    async def fake(html):
        return GOOD_CHECKS, {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    routes_auth._auth_limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    routes_auth._auth_limiter._hits.clear()


@pytest.fixture
def built(client):
    """One run at the approval gate, which is where a theme edit is allowed to happen."""
    r = client.post("/api/auth/register", json={"email": "premium@example.com",
                                                "password": "supersecret1", "name": "Premium"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A commission manager for digital artists",
                                             "spec": {"style": "startup"}}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    return client, h, f"/api/runs/{rid}/theme", rid


def state(client, h, rid):
    return client.get(f"/api/runs/{rid}", headers=h).json()["state"]


def page_of(client, h, rid):
    return client.get(f"/api/runs/{rid}/html", headers=h).text


# ------------------------------------------------------------------ reading and previewing

def test_the_theme_routes_need_a_signed_in_user(client):
    assert client.get("/api/runs/000000000000000000000000/theme").status_code == 401
    for path in ("/preview", "/propose", "/apply", "/reject"):
        url = f"/api/runs/000000000000000000000000/theme{path}"
        assert client.post(url, json={}).status_code == 401, path
    # /from-request needs a body, so it is asked properly: the answer is still "sign in", not "422"
    asked = client.post("/api/runs/000000000000000000000000/theme/from-request",
                        json={"request": "make it premium"})
    assert asked.status_code == 401, asked.text


def test_the_view_reports_the_runs_theme_and_its_proposals(built):
    client, h, ts, rid = built
    body = client.get(ts, headers=h).json()
    assert body["status"] == "awaiting_approval" and body["version"] == 1
    assert body["proposals"] == [] and body["open"] is False and body["theme"] == {}
    assert body["limits"]["revisions_left"] > 0


def test_a_preview_names_the_properties_it_would_move_and_records_nothing(built):
    client, h, ts, rid = built
    out = client.post(f"{ts}/preview", json={"theme": CONTROLS}, headers=h)
    assert out.status_code == 200, out.text
    data = out.json()
    assert data["has_token_block"] is True and data["theme"]["radius"] == "999px"
    assert "--bg" in data["declared"] and data["unreached"] == []
    assert all(row["passes"] for row in data["contrast"])
    assert client.get(ts, headers=h).json()["proposals"] == []      # previewing is not proposing


# ------------------------------------------------------------------ asking in plain English

def test_premium_in_words_becomes_the_controls_that_mean_it(built):
    """The brief's own sentence, asked over HTTP: words -> controls -> what they would reach here."""
    client, h, ts, rid = built
    out = client.post(f"{ts}/from-request", json={"request": "make the entire site look more premium"},
                      headers=h)
    assert out.status_code == 200, out.text
    data = out.json()
    assert [m["control"] for m in data["matched"]] == ["family"]
    assert data["matched"][0]["value"] == "luxury" and data["matched"][0]["label"] == "Luxury"
    assert data["controls"]["family"] == "luxury"
    assert data["resets"] == ["colors"], "asking for a family asks for that palette, not a blend of two"
    assert data["theme"]["palette"] == design_theme.resolve({"family": "luxury"})["palette"]
    assert data["has_token_block"] is True and data["reached"] and all(r["passes"] for r in data["contrast"])
    # reading a sentence is not writing one: no proposal, no page change
    assert client.get(ts, headers=h).json()["proposals"] == []
    assert block(page_of(client, h, rid))["--bg"] != data["theme"]["palette"]["background"]


def test_a_request_about_corners_lands_on_the_theme_the_project_was_briefed_with(client):
    """A delta, not a reset: "square corners" must keep the colours this run was briefed with."""
    r = client.post("/api/auth/register", json={"email": "words@example.com", "password": "supersecret1",
                                                "name": "Words"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A shift swap board for nurses", "spec": {
        "style": "startup", "theme": {"family": "pastel", "mode": "dark"}}}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    ts = f"/api/runs/{rid}/theme"
    asked = client.post(f"{ts}/from-request", json={"request": "square corners, more spacious"}, headers=h)
    assert asked.status_code == 200, asked.text
    data = asked.json()
    assert {m["control"] for m in data["matched"]} == {"radius", "density"}
    assert data["controls"]["radius"] == "square" and data["controls"]["density"] == "roomy"
    assert data["controls"]["family"] == "pastel" and data["controls"]["mode"] == "dark", "the brief's palette survives"
    assert data["theme"]["radius"] == "0px"
    assert data["theme"]["palette"]["background"] == design_theme.resolve(
        {"family": "pastel", "mode": "dark"})["palette"]["background"]


def test_a_sentence_about_something_other_than_appearance_is_refused_with_the_words_that_work(built):
    """No invented theme to please the user: an ask the vocabulary does not know gets a refusal and a hint."""
    client, h, ts, rid = built
    out = client.post(f"{ts}/from-request", json={"request": "add a login page and a shopping cart"},
                      headers=h)
    assert out.status_code == 422, out.text
    detail = out.json()["detail"]
    assert "add a login page" in detail                     # it quotes the ask back rather than guessing
    assert "premium" in detail and "rounded" in detail       # and names words that would have worked
    assert client.get(ts, headers=h).json()["proposals"] == []


def test_a_glass_request_says_why_it_was_not_granted(built):
    """Glass is a per-component treatment here; a whole-site glass ask would put it on every panel."""
    client, h, ts, rid = built
    out = client.post(f"{ts}/from-request", json={"request": "use glass panels across the site"}, headers=h)
    assert out.status_code == 422, out.text
    assert "navbar" in out.json()["detail"]


def test_the_controls_a_request_returns_are_the_ones_a_proposal_can_plan(built):
    """The handoff the visual editor needs: words -> controls -> the existing reviewable patch flow."""
    client, h, ts, rid = built
    controls = client.post(f"{ts}/from-request",
                           json={"request": "make it premium and dark"}, headers=h).json()["controls"]
    planned = client.post(f"{ts}/propose", json={"theme": controls, "request": "premium + dark"}, headers=h)
    assert planned.status_code == 200, planned.text
    theme = planned.json()["theme"]
    assert theme["family"] == "luxury" and theme["mode"] == "dark"
    assert planned.json()["reaches"] > 0 and planned.json()["proposal"]["theme"]["radius"] == theme["radius_key"]


def test_a_request_measured_against_a_page_that_moved_is_refused(built):
    client, h, ts, rid = built
    stale = client.post(f"{ts}/from-request", json={"request": "premium", "base_version": 9}, headers=h)
    assert stale.status_code == 409, stale.text
    assert "Conflict" in stale.json()["detail"]
    # /preview reads the page too, so it answers the same way rather than reporting a stale measurement
    old = client.post(f"{ts}/preview", json={"theme": CONTROLS, "base_version": 9}, headers=h)
    assert old.status_code == 409, old.text


# ------------------------------------------------------------------ proposing

def test_a_proposal_shows_the_patch_and_the_diff_before_anything_is_written(built):
    client, h, ts, rid = built
    before = page_of(client, h, rid)
    out = client.post(f"{ts}/propose", json={"theme": CONTROLS, "request": "make it dark and premium"},
                      headers=h)
    assert out.status_code == 200, out.text
    data = out.json()
    assert data["proposal"]["id"] == "t1" and data["proposal"]["status"] == "proposed"
    assert data["patch"]["file"] == "index.html" and data["patch"]["op"] == "replace"
    assert data["proposal"]["request"] == "make it dark and premium"
    assert data["replaced"] and data["added"] == [] and data["reaches"] == len(data["replaced"])
    assert data["projection"]["changed"] == ["index.html"]
    assert data["base_version"] == 1 and data["safe_to_apply"] is True
    assert data["diffs"]["index.html"]["rows"], "the reviewer gets a diff, not a promise"
    # and the run is exactly where it was
    assert page_of(client, h, rid) == before
    assert state(client, h, rid)["html_version"] == 1
    assert state(client, h, rid)["workspace_versions"] == []


def test_a_proposal_is_recorded_with_the_theme_and_what_it_reaches(built):
    client, h, ts, rid = built
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    entry = client.get(ts, headers=h).json()["proposals"][0]
    assert entry["theme"] == design_theme.as_stored(design_theme.resolve(CONTROLS))
    assert entry["summary"] == design_theme.describe(design_theme.resolve(CONTROLS))
    assert entry["files"] == ["index.html"] and entry["version"] == 1
    assert entry["palette"]["background"] == entry["theme"]["colors"]["background"]
    assert entry["plan"] == "" and entry["result"] == {}
    # a history row has to name the pair it measured, or the panel can only show a bare ratio
    assert [r["pair"] for r in entry["contrast"]] == [r["pair"] for r in
                                                      design_theme.resolve(CONTROLS)["contrast"]][:8]


def test_an_unusable_colour_is_refused_and_records_nothing(built):
    client, h, ts, rid = built
    bad = client.post(f"{ts}/propose", json={"theme": {"colors": {"primary": "sea blue"}}}, headers=h)
    assert bad.status_code == 422, bad.text
    assert client.get(ts, headers=h).json()["proposals"] == []
    assert state(client, h, rid)["html_version"] == 1


def test_a_control_the_customizer_does_not_offer_is_refused_before_planning(built):
    """The same refusal one level up: an unknown preset key would plan a patch for corners nobody chose."""
    client, h, ts, rid = built
    for bad in ({"radius": "sharp"}, {"family": "signal"}, {"scale": 4}):
        refused = client.post(f"{ts}/propose", json={"theme": bad}, headers=h)
        assert refused.status_code == 422, (bad, refused.text)
        assert client.post(f"{ts}/preview", json={"theme": bad}, headers=h).status_code == 422
    assert client.get(ts, headers=h).json()["proposals"] == []
    assert state(client, h, rid)["html_version"] == 1


def test_a_page_without_tokens_cannot_be_theme_edited(built):
    """Remove the block through the ordinary workspace route, then ask for a theme: the answer is no."""
    client, h, ts, rid = built
    page = page_of(client, h, rid)
    span = theme_edit.global_root(page)
    applied = client.post(f"/api/runs/{rid}/workspace/apply", headers=h, json={"changes": [
        {"file": "index.html", "op": "replace", "find": page[span[0]:span[2] + 1], "replace": ""}],
        "request": "hardcode everything"})
    assert applied.status_code == 202, applied.text
    assert theme_edit.global_root(page_of(client, h, rid)) is None   # the block really is gone
    refused = client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    assert refused.status_code == 409, refused.text
    assert "rebuild" in refused.json()["detail"]


# ------------------------------------------------------------------ applying

def test_applying_a_theme_edits_the_tokens_and_is_attributed_to_the_theme(built):
    client, h, ts, rid = built
    before = page_of(client, h, rid)
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    started = client.post(f"{ts}/apply", json={"id": "t1", "base_version": 1}, headers=h)
    assert started.status_code == 202, started.text

    s = state(client, h, rid)
    after = page_of(client, h, rid)
    assert s["html_version"] == 2 and s["revisions"] == 1
    assert block(after)["--radius"] == "999px" and block(after)["--card-blur"].startswith("blur(")
    assert block(after)["--bg"] != block(before)["--bg"]
    # global, by tokens: the rules that read them were not touched
    assert rest_of(after) == rest_of(before)

    entry = client.get(ts, headers=h).json()["proposals"][0]
    assert entry["status"] == "applied" and entry["plan"] == "p1"
    assert entry["result"]["version"] == 2
    snapshot = s["workspace_versions"][-1]
    assert snapshot["cause"]["kind"] == "theme edit" and snapshot["cause"]["plan"] == entry["plan"]
    # publishing re-splits the page, so the derived assets move too - but only from the new tokens
    assert s["changed_files"]["changed"] == ["README.md", "index.html", "styles.css"]


def test_the_derived_stylesheet_follows_the_token_block(built):
    """`styles.css` is re-split from the page on publish: a token edit cannot leave it behind."""
    client, h, ts, rid = built
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    client.post(f"{ts}/apply", json={"id": "t1", "base_version": 1}, headers=h)
    css = client.get(f"/api/runs/{rid}/files/styles.css", headers=h).text
    assert "--radius:999px" in css and "--card-blur:blur(" in css


def test_an_applied_theme_is_the_runs_theme_for_every_later_build(built):
    """The page and the brief are two halves of one promise: a rebuild must not draw the old skin back."""
    client, h, ts, rid = built
    before = state(client, h, rid)["style"]
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    client.post(f"{ts}/apply", json={"id": "t1", "base_version": 1}, headers=h)
    s = state(client, h, rid)
    assert s["spec"]["theme"] == design_theme.as_stored(design_theme.resolve(CONTROLS))
    assert s["style"]["theme"] == s["spec"]["theme"]
    rebuilt = variants.from_dict(s["style"])
    assert (rebuilt.hero, rebuilt.nav, rebuilt.features, rebuilt.motif, list(rebuilt.order)) == \
           (before["hero"], before["nav"], before["features"], before["motif"], list(before["order"]))
    assert rebuilt.tokens["radius"] == "999px"


def test_a_theme_edit_keeps_the_layout_slots_it_was_given(built):
    client, h, ts, rid = built
    style = state(client, h, rid)["style"]
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    client.post(f"{ts}/apply", json={"id": "t1", "base_version": 1}, headers=h)
    after = state(client, h, rid)["style"]
    for key in ("style_key", "hero", "nav", "features", "motif", "order", "layout_style"):
        assert after[key] == style[key], key


def test_the_same_theme_proposal_cannot_be_applied_twice(built):
    client, h, ts, rid = built
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    client.post(f"{ts}/apply", json={"id": "t1", "base_version": 1}, headers=h)
    again = client.post(f"{ts}/apply", json={"id": "t1"}, headers=h)
    assert again.status_code == 409, again.text
    assert "already applied" in again.json()["detail"]


def test_a_proposal_read_at_an_older_version_is_refused_as_a_conflict(built):
    client, h, ts, rid = built
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    moved = client.post(f"/api/runs/{rid}/workspace/apply", headers=h, json={"changes": [
        {"file": "index.html", "op": "replace", "find": "<title>", "replace": "<title>x</title><!--"}],
        "request": "someone else edited the page"})
    assert moved.status_code == 202, moved.text
    clash = client.post(f"{ts}/apply", json={"id": "t1", "base_version": 1}, headers=h)
    assert clash.status_code == 409, clash.text
    assert "Conflict" in clash.json()["detail"]


def test_a_token_block_rewritten_elsewhere_stops_the_apply(built):
    """Same version number, different bytes: the stored patch has to still name one place to apply."""
    client, h, ts, rid = built
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    page = page_of(client, h, rid)
    span = theme_edit.global_root(page)
    client.post(f"/api/runs/{rid}/workspace/apply", headers=h, json={"changes": [
        {"file": "index.html", "op": "replace", "find": page[span[0]:span[2]],
         "replace": page[span[0]:span[1]] + "--bg:#123456;"}], "request": "rewrite the block by hand"})
    refused = client.post(f"{ts}/apply", json={"id": "t1", "base_version": 2}, headers=h)
    assert refused.status_code == 409, refused.text
    assert block(page_of(client, h, rid))["--bg"] == "#123456"
    assert client.get(ts, headers=h).json()["proposals"][0]["status"] == "proposed"


def test_a_rejected_proposal_keeps_the_page_and_records_the_decision(built):
    client, h, ts, rid = built
    before = page_of(client, h, rid)
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    out = client.post(f"{ts}/reject", json={"id": "t1", "reason": "too dark for our brand"}, headers=h)
    assert out.status_code == 200, out.text
    assert out.json()["proposal"]["status"] == "rejected"
    assert out.json()["proposal"]["result"]["reason"] == "too dark for our brand"
    assert page_of(client, h, rid) == before
    assert state(client, h, rid)["html_version"] == 1


def test_proposals_are_listed_newest_first_with_their_outcomes(built):
    client, h, ts, rid = built
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    client.post(f"{ts}/propose", json={"theme": {"family": "luxury"}}, headers=h)
    client.post(f"{ts}/reject", json={"id": "t1"}, headers=h)
    listed = client.get(ts, headers=h).json()["proposals"]
    assert [e["id"] for e in listed] == ["t2", "t1"]
    assert [e["status"] for e in listed] == ["proposed", "rejected"]
    assert client.get(ts, headers=h).json()["open_id"] == "t2"


def test_an_applied_theme_is_undone_and_redone_with_the_design_that_went_with_it(built):
    """Undoing the page but keeping the theme in the brief would rebuild the theme straight back in.

    The design travels with the snapshot: an undo puts the run's direction and spec back the way they
    were before the theme edit, and a redo takes both forward again.
    """
    client, h, ts, rid = built
    plain = page_of(client, h, rid)
    client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=h)
    client.post(f"{ts}/apply", json={"id": "t1", "base_version": 1}, headers=h)
    themed = state(client, h, rid)

    back = client.post(f"/api/runs/{rid}/workspace/undo", headers=h, json={"base_version": 2})
    assert back.status_code == 202, back.text
    s = state(client, h, rid)
    assert block(page_of(client, h, rid))["--bg"] == block(plain)["--bg"]
    assert s["style"]["theme"] == {} and s["spec"].get("theme", {}) == {}

    forward = client.post(f"/api/runs/{rid}/workspace/redo", headers=h, json={"base_version": 3})
    assert forward.status_code == 202, forward.text
    s = state(client, h, rid)
    assert block(page_of(client, h, rid))["--radius"] == "999px"
    assert s["style"]["theme"] == themed["style"]["theme"] == themed["spec"]["theme"]


def test_another_users_run_has_no_theme_to_read_or_apply(built):
    client, h, ts, rid = built
    other = client.post("/api/auth/register", json={"email": "other2@example.com",
                                                   "password": "supersecret1"}).json()
    ho = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(ts.replace(rid, rid), headers=ho).status_code == 404
    assert client.post(f"{ts}/propose", json={"theme": CONTROLS}, headers=ho).status_code == 404
    assert client.post(f"{ts}/apply", json={"id": "t1"}, headers=ho).status_code == 404
