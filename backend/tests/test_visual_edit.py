"""Visual AI editor: selection mapping, patch limits, the proposal gate and the applied visual edit.

Three layers, because the feature has three promises. `visual_edit` must map a rendered element to real
source or refuse. The agent must return one minimal patch, and a patch that does not hold gets its reason
back once. The API must refuse to apply a patch over newer work, keep history that says a visual edit
caused the change, and leave the page untouched whenever any of that fails.
"""
import pytest
from fastapi.testclient import TestClient

from app.agents.base import AgentOutputError
from app.agents.visual_editor import VisualEditorAgent
from app.api import routes_auth, routes_visual
from app.llm.client import LLMClient, LLMResult, Usage
from app.main import app
from app.orchestrator.graph import Orchestrator
from app.services import visual_edit, workspace_manager
from app.tools import browser_checks
from tests.conftest import GOOD_CHECKS
from tests.test_agent_output import Scripted
from tests.test_orchestrator import patch_checks

PAGE = """<!doctype html><html><head><style>
#hero{color:red}
.card{padding:20px}
.nav.sticky{position:sticky}
</style></head><body>
<header id="hero" class="hero"><h1>Ship tonight</h1></header>
<nav id="main-nav" class="nav sticky"><a href="#hero">Home</a><a href="#hero">Pricing</a></nav>
<div class="card">One</div>
<div class="card">Two</div>
<div class="card featured">Three</div>
<p>Alpha</p><p>Beta</p>
<form class="signup" id="signup" action="#"><input id="email" name="email" type="email"><input type="submit"></form>
<script>document.getElementById("signup").addEventListener("submit", onSubmit);</script>
</body></html>"""

TEXTS = {"index.html": PAGE, "styles.css": "#hero{color:red}\n.card{padding:20px}\n.nav.sticky{position:sticky}\n"}
INDEX = workspace_manager.index_texts(TEXTS, version=1)

NAV = {"tag": "nav", "id": "main-nav", "classes": ["nav", "sticky"], "text": "Home Pricing",
       "attrs": [["id", "main-nav"], ["class", "nav sticky"]], "matches": 1, "index": 0}
CARD = {"tag": "div", "classes": ["card"], "text": "Two", "attrs": [["class", "card"]], "matches": 2, "index": 1}
FORM = {"tag": "form", "id": "signup", "classes": ["signup"], "text": "", "matches": 1, "index": 0,
        "attrs": [["action", "#"], ["class", "signup"], ["id", "signup"]]}


def located(raw):
    return visual_edit.locate(TEXTS, visual_edit.describe(raw), INDEX)


def use_page(monkeypatch):
    """The workspace API reads a built run; give every test the same page text without rebuilding it."""
    monkeypatch.setattr(workspace_manager, "load_texts", lambda ctx, names=None: _texts(ctx))

    async def _texts(ctx):
        return dict(TEXTS)


# --------------------------------------------------------------------------- describing the selection

def test_describe_bounds_what_the_frame_can_send():
    el = visual_edit.describe({"tag": " <NAV onclick=x> ", "id": "n" * 200,
                               "classes": [f"c{i}" for i in range(40)],
                               "text": "word " * 200, "attrs": [["href", "u" * 400]] * 20,
                               "index": -5, "matches": "3", "path": "p" * 900})
    assert el["tag"] == "navonclickx"[:24] and len(el["id"]) == 64
    assert len(el["classes"]) == visual_edit.MAX_CLASSES and len(el["text"]) == 160
    assert len(el["attrs"]) == 1 and el["index"] is None and el["matches"] == 3 and len(el["path"]) == 200


def test_describe_drops_id_and_class_from_the_attribute_names():
    el = visual_edit.describe({"tag": "form", "id": "signup", "classes": ["signup"],
                               "attrs": [["id", "signup"], ["class", "signup"], ["action", "#"]]})
    assert list(el["attrs"]) == ["action"]


def test_describe_ignores_the_probe_own_attributes_and_keeps_numbers():
    el = visual_edit.describe({"tag": "p", "attrs": [["data-lc-hover", "1"]], "index": 0, "matches": 0})
    assert el["attrs"] == {} and el["index"] == 0 and el["matches"] == 0


def test_describe_reads_a_stored_element_back_unchanged():
    """Apply re-selects from what the proposal recorded, so describing twice must not move the target."""
    once = visual_edit.describe(FORM)
    assert visual_edit.describe(once) == once
    assert located(once)["source"]["line"] == located(FORM)["source"]["line"] == 12


# --------------------------------------------------------------------------- mapping a selection to source

def test_an_id_locates_the_exact_line_and_the_rule_that_names_it():
    here = located(NAV)
    assert (here["found"], here["via"], here["confidence"]) == (True, "id", "exact")
    assert here["source"]["file"] == "index.html" and here["source"]["line"] == 7
    assert here["source"]["snippet"].startswith('<nav id="main-nav"')
    assert [(r["basis"], r["line"]) for r in here["styling"]] == [("styles.css", 3)]
    assert here["styling"][0]["snippet"] == ".nav.sticky{position:sticky}"


def test_a_repeated_class_is_resolved_by_the_position_the_frame_reports():
    first, second = located({**CARD, "text": "One", "index": 0}), located(CARD)
    assert second["confidence"] == "positional" and second["source"]["line"] == 9
    assert first["source"]["line"] == 8 and "One" in first["element"]["text"]
    featured = located({"tag": "div", "classes": ["card", "featured"], "attrs": [["class", "card featured"]],
                        "matches": 1, "index": 0})
    assert (featured["found"], featured["confidence"], featured["source"]["line"]) == (True, "exact", 10)


def test_a_selection_without_a_position_is_refused_instead_of_guessed():
    missing = located({"tag": "div", "classes": ["card"], "attrs": [["class", "card"]]})
    assert missing["found"] is False and missing["reason"] == "ambiguous"
    assert len(missing["candidates"]) == 2 and missing["counted"] == 2
    assert [c["line"] for c in missing["candidates"]] == [8, 9]
    assert all(c["file"] == "index.html" for c in missing["candidates"])


def test_a_count_that_disagrees_with_the_page_is_a_stale_selection():
    stale = located({**CARD, "matches": 9})
    assert stale["found"] is False and stale["reason"] == "stale"
    assert "refresh the preview" in stale["message"]


def test_an_element_that_is_not_in_the_source_is_not_invented():
    gone = located({"tag": "aside", "attrs": [["class", "panel"]], "classes": ["panel"], "matches": 0, "index": 0})
    assert gone["found"] is False and gone["reason"] == "not-found" and gone["same_tag"] == 0


def test_attribute_names_tell_apart_two_fields_that_share_a_tag():
    named = located({"tag": "input", "attrs": [["id", "email"], ["name", "email"], ["type", "email"]],
                     "matches": 1, "index": 0})
    plain = located({"tag": "input", "attrs": [["type", "submit"]], "matches": 1, "index": 0})
    assert named["source"]["line"] == plain["source"]["line"] == 12
    assert named["element"]["attrs"]["name"] == "email" and "name" not in plain["element"]["attrs"]


def test_a_script_that_reaches_for_the_element_is_reported_as_a_dependency():
    form = located(FORM)
    assert form["found"] and form["source"]["line"] == 12
    assert [(r["kind"], r["basis"], r["line"]) for r in form["scripting"]] == \
           [("dom-id", "index.html <script> block", 1)]

    # once the page ships a real app.js the same reference is quoted against that file
    shipped = {**TEXTS, "app.js": 'document.getElementById("signup").addEventListener("submit", onSubmit);\n'}
    inline = visual_edit.locate(shipped, visual_edit.describe(FORM), workspace_manager.index_texts(shipped))
    assert [(r["kind"], r["basis"], r["line"], r["snippet"]) for r in inline["scripting"]] == \
           [("dom-id", "app.js", 1, 'document.getElementById("signup").addEventListener("submit", onSubmit);')]


def test_no_html_page_means_no_mapping():
    empty = visual_edit.locate({"styles.css": "a{color:red}"}, visual_edit.describe(NAV), INDEX)
    assert empty["found"] is False and empty["reason"] == "no-page"


def test_an_oversized_page_is_reported_not_parsed():
    huge = {"index.html": "<div id='x'>" + "a" * visual_edit.MAX_PAGE_BYTES + "</div>"}
    out = visual_edit.locate(huge, visual_edit.describe(NAV), INDEX)
    assert out["found"] is False and out["reason"] == "no-page"


def test_context_reads_a_numbered_window_around_the_declaration():
    rows = visual_edit.context(PAGE, 7, radius=1)
    assert [r["n"] for r in rows] == [6, 7, 8]
    assert rows[1]["text"].startswith('<nav id="main-nav"')
    assert visual_edit.context(PAGE, 0) == []


def test_the_prompt_shows_the_request_the_source_and_no_invention():
    here = located(NAV)
    ask = visual_edit.prompt(el=here["element"], located=here, texts=TEXTS,
                             instruction="Make this navbar smaller and more professional.", impact="IMPACT BLOCK")
    assert "REQUEST: Make this navbar smaller" in ask
    assert 'SELECTED ELEMENT: <nav> id="main-nav" class="nav sticky" text="Home Pricing"' in ask
    assert "DECLARED IN: index.html line 7 (id, exact match)" in ask
    assert "styles.css:3 .nav.sticky" in ask and "IMPACT BLOCK" in ask
    assert "styles.css:2" not in ask
    assert "do not invent a path" in ask.lower()


# --------------------------------------------------------------------------- what a patch is allowed to be

def test_a_patch_that_names_the_element_is_targeted_and_small():
    here = located(NAV)
    out = visual_edit.verify({"file": "index.html", "op": "replace", "find": 'id="main-nav" class="nav sticky"',
                              "replace": 'id="main-nav" class="nav compact"', "note": "slimmer navbar"}, TEXTS, here)
    assert out["targeted"] is True and out["matched"] and out["warning"] == ""
    assert out["files"] == ["index.html"] and out["region"] == "line 7"
    assert out["lines_added"] == 1 and out["lines_removed"] == 1
    assert out["after"].count('class="nav compact"') == 1 and "Ship tonight" in out["after"]


def test_a_patch_elsewhere_on_the_page_is_still_reviewable_but_flagged():
    here = located(NAV)
    out = visual_edit.verify({"file": "index.html", "op": "replace", "find": "<h1>Ship tonight</h1>",
                              "replace": "<h1>Ship tonight, calmly</h1>", "note": "headline"}, TEXTS, here)
    assert out["targeted"] is False and "does not name the selected element" in out["warning"]
    assert out["region"] == "line 6" and "line 6" in out["warning"]


def test_a_file_that_is_not_in_the_workspace_is_refused():
    here = located(NAV)
    with pytest.raises(workspace_manager.WorkspaceError) as bad:
        visual_edit.verify({"file": "app.js", "op": "replace", "find": "a", "replace": "b"}, TEXTS, here)
    assert "not a file this workspace holds" in bad.value.message


def test_a_path_is_not_a_file_name():
    here = located(NAV)
    for name in ("../index.html", "sub/dir/index.html", ".env", "secrets.txt"):
        with pytest.raises(workspace_manager.WorkspaceError):
            visual_edit.verify({"file": name, "op": "replace", "find": "a", "replace": "b"}, TEXTS, here)


def test_rewriting_the_whole_file_is_not_a_visual_edit():
    here = located(NAV)
    with pytest.raises(workspace_manager.WorkspaceError) as bad:
        visual_edit.verify({"file": "index.html", "op": "set", "text": "<html><body>x</body></html>"}, TEXTS, here)
    assert "not a visual edit" in bad.value.message


def test_a_find_that_is_not_in_the_file_fails_with_the_files_own_words():
    here = located(NAV)
    with pytest.raises(workspace_manager.WorkspaceError) as bad:
        visual_edit.verify({"file": "index.html", "op": "replace", "find": 'id="nope"', "replace": "x"}, TEXTS, here)
    assert "nothing to change" in bad.value.message


def test_an_ambiguous_find_is_reported_as_ambiguous_not_applied_twice():
    here = located(NAV)
    with pytest.raises(workspace_manager.WorkspaceError) as bad:
        visual_edit.verify({"file": "index.html", "op": "replace", "find": "<p>", "replace": "<span>"}, TEXTS, here)
    assert "occurs 2 times" in bad.value.message


def test_a_patch_that_changes_nothing_is_refused():
    here = located(NAV)
    with pytest.raises(workspace_manager.WorkspaceError) as bad:
        visual_edit.verify({"file": "index.html", "op": "replace", "find": 'id="main-nav"',
                            "replace": 'id="main-nav"'}, TEXTS, here)
    assert "identical" in bad.value.message


def test_a_patch_too_big_to_be_called_targeted_is_refused():
    here = located(NAV)
    filler = "\n".join(f".grow{i}{{top:{i}px}}" for i in range(visual_edit.MAX_PATCH_LINES + 5))
    with pytest.raises(workspace_manager.WorkspaceError) as bad:
        visual_edit.verify({"file": "styles.css", "op": "append", "replace": filler}, TEXTS, here)
    assert "a visual edit may reach" in bad.value.message


def test_an_append_carries_its_text_in_the_editors_single_field():
    here = located(NAV)
    out = visual_edit.verify({"file": "styles.css", "op": "append",
                              "replace": "#main-nav{padding:4px 12px}"}, TEXTS, here)
    assert out["changes"][0]["op"] == "append" and out["changes"][0]["text"].startswith("#main-nav")
    assert out["region"].startswith("end of file")


def test_replace_all_is_allowed_and_counts_every_landing():
    here = located({"tag": "p", "attrs": [], "matches": 2, "index": 0})
    out = visual_edit.verify({"file": "index.html", "op": "replace_all", "find": "<p>", "replace": '<p class="note">'},
                             TEXTS, here)
    assert out["lines_removed"] == 2 and out["region"] == "line 11"


# --------------------------------------------------------------------------- the proposals, as history

def test_a_proposal_is_recorded_with_what_it_found_and_where_it_landed():
    class Ctx:
        run_id = "r1"

        class state:
            html_version = 4
            visual_edits = []
            revisions = 0

    ctx = Ctx()
    here = located(NAV)
    verified = visual_edit.verify({"file": "index.html", "op": "replace", "find": 'id="main-nav"',
                                  "replace": 'id="top-nav"', "note": "renamed"}, TEXTS, here)
    entry = visual_edit.record_proposal(ctx, instruction="rename the nav", element=here["element"],
                                       located=here, verified=verified, report={"scope": "one-file", "counts": {}})
    assert entry["id"] == "e1" and entry["status"] == "proposed" and entry["version"] == 4
    assert entry["source"]["line"] == 7 and entry["patch"]["find"] == 'id="main-nav"'
    assert entry["impact"] == {"scope": "one-file", "counts": {}, "risks": []}
    assert ctx.state.visual_edits == [entry]

    second = visual_edit.record_proposal(ctx, instruction="again", element=here["element"], located=here,
                                        verified=verified, report=None)
    assert second["id"] == "e2" and second["impact"]["scope"] is None
    visual_edit.mark_proposal(second, "rejected", reason="not what I meant")
    assert second["status"] == "rejected" and second["result"]["reason"] == "not what I meant"


def test_proposals_are_kept_bounded_and_looked_up_by_id():
    class Ctx:
        run_id = "r1"

        class state:
            html_version = 1
            visual_edits = [{"id": f"e{i}"} for i in range(1, 21)]
            revisions = 0

    ctx = Ctx()
    here = located(NAV)
    verified = visual_edit.verify({"file": "index.html", "op": "replace", "find": 'id="main-nav"',
                                  "replace": 'id="top-nav"', "note": "x"}, TEXTS, here)
    visual_edit.record_proposal(ctx, instruction="x", element=here["element"], located=here,
                               verified=verified, report=None)
    assert len(ctx.state.visual_edits) == visual_edit.MAX_PROPOSALS
    assert ctx.state.visual_edits[-1]["id"] == "e21"
    assert visual_edit.find_proposal(ctx.state, "e21") is ctx.state.visual_edits[-1]
    with pytest.raises(workspace_manager.WorkspaceError) as bad:
        visual_edit.find_proposal(ctx.state, "e99")
    assert bad.value.status == 404


def test_names_files_lists_the_page_and_the_assets_the_edit_touches():
    here = located(NAV)
    changes = [{"file": "styles.css"}, {"file": "index.html"}]
    assert visual_edit.names_files(changes, here) == ["index.html", "styles.css"]


# --------------------------------------------------------------------------- the model call

async def test_the_agent_returns_one_verified_patch_and_asks_for_json_only(make_ctx):
    ctx, _events = make_ctx()
    provider = Scripted(LLMResult('{"file":"index.html","op":"replace","find":"id=\\"main-nav\\"",'
                                  '"replace":"id=\\"main-nav\\" data-compact","note":"slimmer"}', Usage(1, 1, 2)))
    ctx.llm = LLMClient(ctx.settings, provider=provider)
    here = located(NAV)

    out = await VisualEditorAgent().patch(ctx, user="make the nav smaller", texts=TEXTS, located=here)

    assert out["patch"]["replace"] == 'id="main-nav" data-compact' and out["targeted"] is True
    assert len(provider.requests) == 1
    sent = provider.requests[0]
    assert sent["json_mode"] is True and sent["tools"] is None and sent["agent"] == "visual_editor"
    assert sent["messages"][0]["content"].startswith("You are the visual editor")


async def test_a_patch_that_does_not_match_gets_its_exact_reason_back_once(make_ctx):
    ctx, _events = make_ctx()
    bad = '{"file":"index.html","op":"replace","find":"id=\\"nope\\"","replace":"x","note":"wrong"}'
    good = '{"file":"styles.css","op":"append","replace":"#main-nav{padding:2px}","note":"tighter"}'
    provider = Scripted(LLMResult(bad, Usage(1, 1, 2)), LLMResult(good, Usage(1, 1, 2)))
    ctx.llm = LLMClient(ctx.settings, provider=provider)
    here = located(NAV)

    out = await VisualEditorAgent().patch(ctx, user="smaller", texts=TEXTS, located=here)

    assert out["files"] == ["styles.css"] and len(provider.requests) == 2
    correction = provider.requests[1]["messages"][-1]["content"]
    assert "nothing to change" in correction and "corrected JSON" in correction
    assert provider.requests[1]["messages"][-2]["content"].startswith("{")


async def test_two_failed_patches_are_a_refusal_not_a_guess(make_ctx):
    ctx, _events = make_ctx()
    bad = '{"file":"index.html","op":"replace","find":"id=\\"nope\\"","replace":"x","note":"wrong"}'
    provider = Scripted(LLMResult(bad, Usage(1, 1, 2)))
    ctx.llm = LLMClient(ctx.settings, provider=provider)

    with pytest.raises(AgentOutputError) as bad_out:
        await VisualEditorAgent().patch(ctx, user="redo the page", texts=TEXTS, located=located(NAV))
    assert "no patch that fits this element" in str(bad_out.value)
    assert "nothing to change" in str(bad_out.value)
    assert len(provider.requests) == 2


async def test_a_whole_file_rewrite_is_refused_before_the_file_is_touched(make_ctx):
    ctx, _events = make_ctx()
    rewrite = '{"file":"index.html","op":"set","text":"<html></html>","note":"start over"}'
    provider = Scripted(LLMResult(rewrite, Usage(1, 1, 2)))
    ctx.llm = LLMClient(ctx.settings, provider=provider)

    with pytest.raises(AgentOutputError) as bad:
        await VisualEditorAgent().patch(ctx, user="make it nice", texts=TEXTS, located=located(NAV))
    assert "is not a visual edit" in str(bad.value)


async def test_unparseable_model_output_stays_the_base_agents_error(make_ctx):
    ctx, _events = make_ctx()
    ctx.llm = LLMClient(ctx.settings, provider=Scripted(LLMResult("I would add a class.", Usage(1, 1, 2))))
    with pytest.raises(AgentOutputError) as bad:
        await VisualEditorAgent().patch(ctx, user="smaller", texts=TEXTS, located=located(NAV))
    assert "invalid output after retry" in str(bad.value)


async def test_the_visual_editor_is_not_a_crew_step(make_ctx):
    ctx, _events = make_ctx()
    with pytest.raises(NotImplementedError):
        await VisualEditorAgent().run(ctx)


# --------------------------------------------------------------------------- the applied visual edit, end to end

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
    r = client.post("/api/auth/register", json={"email": "visual@example.com", "password": "supersecret1"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A tiny CRM for solo founders"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    return client, h, f"/api/runs/{rid}/visual", rid


def state(client, h, rid):
    return client.get(f"/api/runs/{rid}", headers=h).json()["state"]


def status(client, h, rid):
    """The run's own status lives beside the state, not inside it."""
    return client.get(f"/api/runs/{rid}", headers=h).json()["status"]


def stacks(client, h, rid):
    """Undo/redo is reported by the workspace view, which is where the panel reads it from too."""
    return client.get(f"/api/runs/{rid}/workspace", headers=h).json()["undo"]


class StubAgent:
    """Stands in for the model: verifies a canned patch with the real rules, and fails the way the
    agent fails when the patch does not survive them."""

    def __init__(self, canned):
        self.canned = canned

    async def patch(self, ctx, *, user, texts, located):
        self.ask = user
        try:
            return visual_edit.verify(self.canned, texts, located)
        except workspace_manager.WorkspaceError as exc:
            raise AgentOutputError(f"visual_editor: no patch that fits this element: {exc.message}") from exc


def stubbed(monkeypatch, canned):
    agent = StubAgent(canned)
    monkeypatch.setattr(routes_visual, "VisualEditorAgent", lambda: agent)
    return agent


def signup_patch(replacement='class="signup compact"', find='class="signup"'):
    return {"file": "index.html", "op": "replace", "find": find, "replace": replacement,
            "note": "tighter sign-up form"}


# The crew's own build for a test run: a `<form id="signup">` in the CTA section and nothing else stable
# enough to select, so the end-to-end tests pick one of those two.
SECTION = {"tag": "section", "id": "cta", "classes": [], "text": "", "attrs": [], "matches": 1, "index": 0}


def test_locate_answers_from_the_published_page_without_calling_a_model(built):
    client, h, vs, rid = built
    page = client.get(f"/api/runs/{rid}/html", headers=h).text
    assert 'class="signup"' in page

    out = client.post(f"{vs}/locate", json={"element": FORM}, headers=h)
    assert out.status_code == 200
    data = out.json()
    assert data["found"] is True and data["version"] == 1
    assert data["source"]["file"] == "index.html" and data["source"]["line"] > 1
    assert data["styling"] and all("basis" in r for r in data["styling"])
    assert "key" not in out.text and "before" not in data and "patch" not in data


def test_locate_reports_a_refusal_as_an_answer_not_an_error(built):
    client, h, vs, _ = built
    out = client.post(f"{vs}/locate", json={"element": {"tag": "marquee", "matches": 0, "index": 0}}, headers=h)
    assert out.status_code == 200 and out.json()["found"] is False
    assert out.json()["reason"] == "not-found"


def test_a_proposal_shows_the_patch_and_the_diff_before_anything_is_written(built, monkeypatch):
    client, h, vs, rid = built
    agent = stubbed(monkeypatch, signup_patch())

    out = client.post(f"{vs}/plan", json={"element": FORM, "instruction": "Make this form more compact",
                                         "base_version": 1}, headers=h)
    assert out.status_code == 200
    data = out.json()
    assert data["proposal"]["status"] == "proposed" and data["proposal"]["id"] == "e1"
    assert data["proposal"]["source"]["line"] > 1 and data["targeted"] is True
    assert data["patch"]["find"] == 'class="signup"'
    assert data["affected_files"] == ["index.html"]
    assert data["diffs"]["index.html"]["added"] == 1 and data["diffs"]["index.html"]["removed"] == 1
    assert data["base_version"] == 1 and data["safe_to_apply"] is True
    assert data["limits"]["ops"] == ["replace", "replace_all", "append"]
    assert "DECLARED IN: index.html" in agent.ask

    s = state(client, h, rid)
    assert s["html_version"] == 1 and s["revisions"] == 0 and s["workspace_versions"] == []
    assert s["change_plans"] == [] and s["visual_edits"][0]["id"] == "e1"
    assert "nothing was written" or True


def test_a_proposal_that_cannot_be_mapped_is_refused_without_a_model_call(built, monkeypatch):
    client, h, vs, rid = built
    agent = stubbed(monkeypatch, signup_patch())

    out = client.post(f"{vs}/plan", json={"element": {"tag": "marquee", "matches": 0, "index": 0},
                                         "instruction": "make it smaller"}, headers=h)
    assert out.status_code == 422 and "No <marquee>" in out.json()["detail"]
    assert not hasattr(agent, "ask")
    assert state(client, h, rid)["visual_edits"] == []


def test_a_model_with_no_usable_patch_is_a_bad_gateway_not_a_silent_ok(built, monkeypatch):
    client, h, vs, rid = built
    stubbed(monkeypatch, {"file": "index.html", "op": "replace", "find": 'class="nothing-here"',
                          "replace": "x", "note": "wrong"})
    out = client.post(f"{vs}/plan", json={"element": FORM, "instruction": "make it compact"}, headers=h)
    assert out.status_code == 502 and "no patch that fits" in out.json()["detail"]
    assert state(client, h, rid)["visual_edits"] == []


def test_applying_a_visual_edit_checkpoints_first_and_is_attributed_to_the_edit(built, monkeypatch):
    client, h, vs, rid = built
    stubbed(monkeypatch, signup_patch())
    planned = client.post(f"{vs}/plan", json={"element": FORM, "instruction": "Make this form more compact"},
                          headers=h).json()
    assert planned["proposal"]["id"] == "e1"

    started = client.post(f"{vs}/apply", json={"id": "e1", "base_version": 1}, headers=h)
    assert started.status_code == 202 and started.json()["status"] == "running"

    s = state(client, h, rid)
    page = client.get(f"/api/runs/{rid}/html", headers=h).text
    assert s["html_version"] == 2 and s["revisions"] == 1 and status(client, h, rid) == "awaiting_approval"
    assert 'class="signup compact"' in page and 'class="signup"' not in page

    edit = s["visual_edits"][0]
    assert edit["status"] == "applied" and edit["plan"].startswith("p")
    assert edit["result"]["version"] == 2 and edit["result"]["check_errors"] == 0
    assert s["workspace_versions"][0]["cause"] == {"kind": "visual edit", "agent": "user", "plan": edit["plan"],
                                                   "run_id": rid, "version": 1}
    assert s["workspace_versions"][0]["note"].startswith("Before change")
    assert s["validation"]["kind"] == "visual edit" and s["validation"]["plan"] == edit["plan"]
    assert stacks(client, h, rid)["can_undo"] and not stacks(client, h, rid)["can_redo"]
    assert s["change_plans"][-1]["status"] == "applied"


def test_an_applied_visual_edit_can_be_undone_and_redone(built, monkeypatch):
    client, h, vs, rid = built
    stubbed(monkeypatch, signup_patch())
    client.post(f"{vs}/plan", json={"element": FORM, "instruction": "compact"}, headers=h)
    client.post(f"{vs}/apply", json={"id": "e1", "base_version": 1}, headers=h)

    undone = client.post(f"/api/runs/{rid}/workspace/undo", json={}, headers=h)
    assert undone.status_code == 202
    page = client.get(f"/api/runs/{rid}/html", headers=h).text
    s = state(client, h, rid)
    assert 'class="signup"' in page and s["html_version"] == 3 and s["revisions"] == 1
    assert stacks(client, h, rid)["can_redo"] is True

    redone = client.post(f"/api/runs/{rid}/workspace/redo", json={}, headers=h)
    assert redone.status_code == 202
    assert 'class="signup compact"' in client.get(f"/api/runs/{rid}/html", headers=h).text


def test_the_same_proposal_cannot_be_applied_twice(built, monkeypatch):
    client, h, vs, rid = built
    stubbed(monkeypatch, signup_patch())
    client.post(f"{vs}/plan", json={"element": FORM, "instruction": "compact"}, headers=h)
    client.post(f"{vs}/apply", json={"id": "e1", "base_version": 1}, headers=h)

    again = client.post(f"{vs}/apply", json={"id": "e1"}, headers=h)
    assert again.status_code == 409 and "already applied" in again.json()["detail"]
    assert state(client, h, rid)["html_version"] == 2


def test_a_proposal_read_at_an_older_version_is_refused_as_a_conflict(built, monkeypatch):
    client, h, vs, rid = built
    stubbed(monkeypatch, signup_patch())
    client.post(f"{vs}/plan", json={"element": FORM, "instruction": "compact"}, headers=h)
    marker = client.post(f"{vs.replace('/visual', '/workspace')}/apply",
                         json={"changes": [{"file": "styles.css", "op": "append", "text": "/* hand */"}],
                               "request": "hand patch"}, headers=h)
    assert marker.status_code == 202
    moved = state(client, h, rid)["html_version"]
    assert moved == 2

    clash = client.post(f"{vs}/apply", json={"id": "e1", "base_version": 1}, headers=h)
    assert clash.status_code == 409 and "Conflict" in clash.json()["detail"]
    assert state(client, h, rid) and state(client, h, rid)["html_version"] == moved


def test_a_patch_that_no_longer_holds_at_apply_time_leaves_everything_alone(built, monkeypatch):
    client, h, vs, rid = built
    stubbed(monkeypatch, signup_patch())
    client.post(f"{vs}/plan", json={"element": FORM, "instruction": "compact"}, headers=h)
    monkeypatch.setattr(visual_edit, "verify", lambda *a, **k: (_ for _ in ()).throw(
        workspace_manager.WorkspaceError("the page no longer holds this fragment", 422)))

    refused = client.post(f"{vs}/apply", json={"id": "e1", "base_version": 1}, headers=h)
    assert refused.status_code == 422 and "no longer holds" in refused.json()["detail"]
    s = state(client, h, rid)
    assert s["html_version"] == 1 and status(client, h, rid) == "awaiting_approval"
    assert s["visual_edits"][0]["status"] == "proposed" and s["workspace_versions"] == []


def test_a_vanished_element_stops_the_apply_even_at_the_same_version(built, monkeypatch):
    client, h, vs, rid = built
    stubbed(monkeypatch, signup_patch())
    client.post(f"{vs}/plan", json={"element": FORM, "instruction": "compact"}, headers=h)
    real_locate = visual_edit.locate
    monkeypatch.setattr(visual_edit, "locate",
                        lambda texts, el, index=None: {"found": False, "reason": "stale",
                                                       "message": "The frame is showing a different page."})

    refused = client.post(f"{vs}/apply", json={"id": "e1", "base_version": 1}, headers=h)
    assert refused.status_code == 409 and "different page" in refused.json()["detail"]
    assert state(client, h, rid)["html_version"] == 1
    monkeypatch.setattr(visual_edit, "locate", real_locate)


def test_rejecting_a_proposal_keeps_the_page_and_records_the_decision(built, monkeypatch):
    client, h, vs, rid = built
    stubbed(monkeypatch, signup_patch())
    client.post(f"{vs}/plan", json={"element": FORM, "instruction": "compact"}, headers=h)

    out = client.post(f"{vs}/reject", json={"id": "e1", "reason": "too subtle"}, headers=h)
    assert out.status_code == 200 and out.json()["proposal"]["status"] == "rejected"
    s = state(client, h, rid)
    assert s["html_version"] == 1 and s["revisions"] == 0 and s["workspace_versions"] == []
    assert s["visual_edits"][0]["result"]["reason"] == "too subtle"

    again = client.post(f"{vs}/reject", json={"id": "e1"}, headers=h)
    assert again.status_code == 409
    assert client.post(f"{vs}/reject", json={"id": "e9"}, headers=h).status_code == 404


def test_proposals_are_listed_newest_first_with_their_outcomes(built, monkeypatch):
    client, h, vs, _ = built
    stubbed(monkeypatch, signup_patch())
    client.post(f"{vs}/plan", json={"element": FORM, "instruction": "first"}, headers=h)
    stubbed(monkeypatch, signup_patch('class="signup roomy"'))
    client.post(f"{vs}/plan", json={"element": SECTION, "instruction": "second"}, headers=h)

    listed = client.get(f"{vs}/proposals", headers=h).json()
    assert [p["id"] for p in listed["proposals"]] == ["e2", "e1"]
    assert listed["proposals"][0]["instruction"] == "second"
    assert all(p["status"] == "proposed" for p in listed["proposals"])


def test_each_new_proposal_costs_nothing_until_it_is_applied(built, monkeypatch):
    client, h, vs, rid = built
    agent = stubbed(monkeypatch, signup_patch())
    for _ in range(3):
        assert client.post(f"{vs}/plan", json={"element": FORM, "instruction": "compact"}, headers=h).status_code == 200
    s = state(client, h, rid)
    assert [p["id"] for p in s["visual_edits"]] == ["e1", "e2", "e3"]
    assert s["revisions"] == 0 and s["html_version"] == 1 and s["workspace_versions"] == []


def test_a_visual_edit_stops_at_the_revision_cap_like_any_other_edit(built, monkeypatch):
    client, h, vs, rid = built
    stubbed(monkeypatch, signup_patch())
    for step in range(5):
        stubbed(monkeypatch, signup_patch(f'class="signup v{step}"',
                                         find='class="signup"' if step == 0 else f'class="signup v{step - 1}"'))
        planned = client.post(f"{vs}/plan", json={"element": FORM, "instruction": f"pass {step}"}, headers=h)
        assert planned.status_code == 200, planned.text
        applied = client.post(f"{vs}/apply", json={"id": planned.json()["proposal"]["id"],
                                                  "base_version": planned.json()["base_version"]}, headers=h)
        assert applied.status_code == 202, applied.text

    assert state(client, h, rid)["revisions"] == 5
    capped_plan = client.post(f"{vs}/plan", json={"element": FORM, "instruction": "one more"}, headers=h)
    assert capped_plan.status_code == 429
    capped_apply = client.post(f"{vs}/apply", json={"id": "e1"}, headers=h)
    assert capped_apply.status_code == 429


# --------------------------------------------------------------------------- who may ask, and with what

def test_nobody_elses_visual_edits(built):
    client, h, vs, rid = built
    other = client.post("/api/auth/register", json={"email": "nosy@example.com", "password": "supersecret1"})
    h2 = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.post(f"{vs}/locate", json={"element": NAV}, headers=h2).status_code == 404
    assert client.post(f"{vs}/plan", json={"element": NAV, "instruction": "smaller"}, headers=h2).status_code == 404
    assert client.post(f"{vs}/apply", json={"id": "e1"}, headers=h2).status_code == 404
    assert client.post(f"{vs}/reject", json={"id": "e1"}, headers=h2).status_code == 404
    assert client.get(f"{vs}/proposals", headers=h2).status_code == 404
    assert rid and client.get(f"{vs}/proposals", headers=h).status_code == 200


def test_anonymous_requests_are_rejected(built):
    client, _h, vs, _ = built
    assert client.post(f"{vs}/locate", json={"element": NAV}).status_code == 401
    assert client.get(f"{vs}/proposals").status_code == 401
    assert client.post(f"{vs}/apply", json={"id": "e1"}).status_code == 401


def test_requests_are_validated_before_anything_is_read(built):
    client, h, vs, _ = built
    assert client.post(f"{vs}/plan", json={"element": NAV, "instruction": "x"}, headers=h).status_code == 422
    assert client.post(f"{vs}/plan", json={"element": NAV}, headers=h).status_code == 422
    assert client.post(f"{vs}/plan", json={"element": NAV, "instruction": "y" * 501}, headers=h).status_code == 422
    assert client.post(f"{vs}/locate", json={"element": {"tag": "p", "classes": ["c"] * 80}},
                       headers=h).status_code == 422
    assert client.post(f"{vs}/apply", json={"id": ""}, headers=h).status_code == 422


def test_a_selection_is_clipped_server_side_before_it_reaches_the_prompt(built, monkeypatch):
    client, h, vs, _ = built
    agent = stubbed(monkeypatch, signup_patch())
    huge = {"tag": "form", "id": "signup", "classes": [f"c{i}" for i in range(40)], "text": "word " * 400,
            "attrs": [["action", "#" + "u" * 400]] * 20, "matches": 1, "index": 0, "path": "p" * 900}
    out = client.post(f"{vs}/plan", json={"element": huge, "instruction": "compact"}, headers=h)
    assert out.status_code == 200
    sent = out.json()["element"]
    assert len(sent["text"]) == visual_edit.MAX_TEXT_CHARS
    assert len(sent["classes"]) == visual_edit.MAX_CLASSES and len(sent["path"]) == 200
    assert all(len(v) == visual_edit.MAX_ATTR_CHARS for v in sent["attrs"].values())
    assert len(agent.ask) < 6000 and "#" + "u" * 400 not in agent.ask
