"""The IDE assistant: a plain-English request answered with edits to the run's own files.

The model is stubbed everywhere here, so these tests spend no tokens and prove the parts that are ours:
a proposal is measured against the stored text before anyone sees it, nothing is written until Apply, an
applied proposal gets the checkpoint before it and the attribution on it, and a proposal that no longer
means the same thing is a conflict rather than a surprise.

The refusal cases matter as much as the success ones: a change that names a file that is not there, or a
fragment that is not in it, never reaches the reviewer as an option.
"""
import pytest
from fastapi.testclient import TestClient

from app.agents.base import AgentOutputError
from app.api import routes_auth, routes_ide
from app.main import app
from app.services import ide_assistant, workspace_manager
from app.tools import browser_checks

GOOD = [{"id": "overflow", "label": "x", "viewport": "desktop", "passed": True,
         "severity": "error", "detail": ""}]
FIND, REPLACEMENT = 'class="signup"', 'class="signup compact"'


@pytest.fixture
def client(monkeypatch):
    async def fake(html):
        return GOOD, {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    routes_auth._auth_limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    routes_auth._auth_limiter._hits.clear()


@pytest.fixture
def built(client):
    r = client.post("/api/auth/register", json={"email": "assistant@example.com",
                                                "password": "supersecret1", "name": "A"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A tiny CRM for solo founders"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    return client, h, f"/api/runs/{rid}/ide", rid


def state(client, h, rid):
    return client.get(f"/api/runs/{rid}", headers=h).json()["state"]


def status(client, h, rid):
    return client.get(f"/api/runs/{rid}", headers=h).json()["status"]


class StubAgent:
    """Stands in for the model: verifies canned changes with the real rules, and fails the way the
    agent fails when a change does not survive them."""

    def __init__(self, canned):
        self.canned = canned

    async def patch(self, ctx, *, user, texts, allowed=None):
        self.ask = user
        self.allowed = allowed
        try:
            return ide_assistant.verify(self.canned, texts, allowed=allowed)
        except workspace_manager.WorkspaceError as exc:
            raise AgentOutputError(f"ide_assistant: no edit that fits these files: {exc.message}") from exc


def stubbed(monkeypatch, canned):
    agent = StubAgent(canned)
    monkeypatch.setattr(routes_ide, "IdeAssistantAgent", lambda: agent)
    return agent


def page_patch(extra_css=None):
    changes = [{"file": "index.html", "op": "replace", "find": FIND, "replace": REPLACEMENT,
                "note": "tighter sign-up form"}]
    if extra_css:
        changes.append({"file": "styles.css", "op": "append", "text": f"/* {extra_css} */",
                        "note": "the rule the request asked for"})
    return {"summary": "Compact the sign-up form and note why in the stylesheet.", "changes": changes}# --------------------------------------------------------------------------- planning, writing nothing

def test_a_proposal_lists_the_files_it_touches_and_the_diffs_before_anything_is_written(built, monkeypatch):
    client, h, ide, rid = built
    agent = stubbed(monkeypatch, page_patch("hand-written note"))

    out = client.post(f"{ide}/plan", json={"instruction": "Make the sign-up form more compact and note it",
                                           "base_version": 1}, headers=h)
    assert out.status_code == 200
    data = out.json()
    assert data["proposal"]["status"] == "proposed" and data["proposal"]["id"] == "i1"
    assert data["proposal"]["summary"].startswith("Compact the sign-up")
    assert [row["file"] for row in data["affected"]] == ["index.html", "styles.css"]
    assert data["affected"][0]["kind"] == "page" and data["affected"][0]["save_via"] == "apply"
    assert data["affected"][1]["kind"] == "derived"
    # the page is the canonical document, so folding the stylesheet edit back into it moves more than one
    # line there; the diff shown is what the pipeline would actually write, not what was asked for
    assert set(data["diffs"]) == {"index.html", "styles.css"}
    assert data["diffs"]["styles.css"]["added"] == 1
    assert "signup compact" in str(data["diffs"]["index.html"]["side"])
    assert data["base_version"] == 1 and data["safe_to_apply"] is True
    assert data["sent_files"][0] == "index.html" and data["clipped_files"] == []
    assert "checkpoint" in data["applies_through"]
    assert data["limits"]["max_changes"] == 12
    assert "key" not in out.text                                       # storage keys stay server-side

    s = state(client, h, rid)
    assert s["html_version"] == 1 and s["revisions"] == 0 and s["workspace_versions"] == []
    assert s["change_plans"] == [] and s["ide_edits"][0]["id"] == "i1"
    assert "FILES YOU MAY NAME IN `file`" in agent.ask


def test_the_prompt_shows_the_stored_text_verbatim_and_the_request_that_names_it(built, monkeypatch):
    client, h, ide, rid = built
    page = client.get(f"/api/runs/{rid}/html", headers=h).text
    agent = stubbed(monkeypatch, page_patch())

    client.post(f"{ide}/plan", json={"instruction": "tighten the sign-up button", "files": ["index.html"]},
                headers=h)
    assert f"--- index.html ---\n{page}\n--- end index.html ---" in agent.ask
    assert "REQUEST: tighten the sign-up button" in agent.ask
    assert "FILES YOU MAY NAME IN `file`: index.html" in agent.ask


def test_an_explicit_file_list_sends_only_that_file(built, monkeypatch):
    client, h, ide, _ = built
    agent = stubbed(monkeypatch, page_patch())
    out = client.post(f"{ide}/plan", json={"instruction": "touch the page", "files": ["index.html"]}, headers=h)
    assert out.json()["sent_files"] == ["index.html"]
    assert "--- styles.css ---" not in agent.ask
    assert agent.allowed == ["index.html"]


def test_a_chosen_scope_bounds_the_files_the_assistant_may_edit(built, monkeypatch):
    """The reviewer ticked one file; a patch that also reaches into another is refused, not scaled down.

    The file was never sent, so nobody could have read it, so nobody could have approved that edit - which
    is exactly what the panel's "Only these will be sent" line promises.
    """
    client, h, ide, rid = built
    stubbed(monkeypatch, page_patch("unrequested stylesheet rule"))
    out = client.post(f"{ide}/plan", json={"instruction": "touch the page", "files": ["index.html"]}, headers=h)
    assert out.status_code == 502
    detail = out.json()["detail"]
    assert "styles.css was not sent for this request" in detail
    assert "Ask again naming it" in detail
    assert state(client, h, rid)["ide_edits"] == []


def test_an_unbounded_request_can_still_edit_the_page_and_its_assets(built, monkeypatch):
    client, h, ide, _ = built
    agent = stubbed(monkeypatch, page_patch("hand-written note"))
    out = client.post(f"{ide}/plan", json={"instruction": "compact the form and note it"}, headers=h)
    assert out.status_code == 200
    assert set(agent.allowed) >= {"index.html", "styles.css"}


def test_a_change_that_is_not_in_the_file_is_refused_and_records_nothing(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, {"summary": "wrong", "changes": [
        {"file": "index.html", "op": "replace", "find": 'class="nothing-here"', "replace": "x", "note": ""}]})
    out = client.post(f"{ide}/plan", json={"instruction": "make it compact"}, headers=h)
    assert out.status_code == 502 and "no edit that fits" in out.json()["detail"]
    assert state(client, h, rid)["ide_edits"] == []


def test_a_change_naming_a_file_this_workspace_does_not_hold_is_refused(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, {"summary": "invented", "changes": [
        {"file": "backend.py", "op": "set", "text": "print('hi')", "note": ""}]})
    out = client.post(f"{ide}/plan", json={"instruction": "add a server"}, headers=h)
    assert out.status_code == 502 and "not a file this workspace holds" in out.json()["detail"]
    assert state(client, h, rid)["ide_edits"] == []


def test_a_change_that_would_write_what_is_already_there_is_refused(built, monkeypatch):
    client, h, ide, _ = built
    stubbed(monkeypatch, {"summary": "no change", "changes": [
        {"file": "index.html", "op": "replace", "find": FIND, "replace": FIND, "note": "same"}]})
    out = client.post(f"{ide}/plan", json={"instruction": "something"}, headers=h)
    assert out.status_code == 502 and "does nothing" in out.json()["detail"]


# --------------------------------------------------------------------------- applying, rejecting, conflicting

def test_applying_an_assistant_edit_checkpoints_first_and_is_attributed_to_it(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, page_patch())
    assert client.post(f"{ide}/plan", json={"instruction": "compact the form"}, headers=h).status_code == 200

    started = client.post(f"{ide}/apply", json={"id": "i1", "base_version": 1}, headers=h)
    assert started.status_code == 202 and started.json()["status"] == "running"

    s = state(client, h, rid)
    page = client.get(f"/api/runs/{rid}/html", headers=h).text
    assert s["html_version"] == 2 and s["revisions"] == 1 and status(client, h, rid) == "awaiting_approval"
    assert REPLACEMENT in page and FIND not in page

    edit = s["ide_edits"][0]
    assert edit["status"] == "applied" and edit["plan"].startswith("p")
    assert edit["result"]["version"] == 2
    assert s["workspace_versions"][0]["cause"]["kind"] == "assistant edit"
    assert s["workspace_versions"][0]["note"].startswith("Before change")
    assert s["validation"]["kind"] == "assistant edit" and s["validation"]["plan"] == edit["plan"]
    assert s["change_plans"][-1]["status"] == "applied"
    undo = client.get(f"/api/runs/{rid}/workspace", headers=h).json()["undo"]
    assert undo["can_undo"] and not undo["can_redo"]


def test_an_applied_assistant_edit_can_be_undone(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, page_patch())
    client.post(f"{ide}/plan", json={"instruction": "compact"}, headers=h)
    client.post(f"{ide}/apply", json={"id": "i1", "base_version": 1}, headers=h)

    undone = client.post(f"/api/runs/{rid}/workspace/undo", json={}, headers=h)
    assert undone.status_code == 202
    page = client.get(f"/api/runs/{rid}/html", headers=h).text
    assert FIND in page and REPLACEMENT not in page


def test_the_same_proposal_cannot_be_applied_twice(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, page_patch())
    client.post(f"{ide}/plan", json={"instruction": "compact"}, headers=h)
    client.post(f"{ide}/apply", json={"id": "i1", "base_version": 1}, headers=h)

    again = client.post(f"{ide}/apply", json={"id": "i1"}, headers=h)
    assert again.status_code == 409 and "already applied" in again.json()["detail"]
    assert state(client, h, rid)["html_version"] == 2


def test_a_proposal_read_at_an_older_version_is_refused_as_a_conflict(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, page_patch())
    client.post(f"{ide}/plan", json={"instruction": "compact"}, headers=h)
    moved = client.post(f"/api/runs/{rid}/workspace/apply",
                        json={"changes": [{"file": "styles.css", "op": "append", "text": "/* hand */"}],
                              "request": "hand patch"}, headers=h)
    assert moved.status_code == 202
    assert state(client, h, rid)["html_version"] == 2

    clash = client.post(f"{ide}/apply", json={"id": "i1", "base_version": 1}, headers=h)
    assert clash.status_code == 409 and "Conflict" in clash.json()["detail"]


def test_rejecting_a_proposal_leaves_every_file_exactly_as_it_was(built, monkeypatch):
    client, h, ide, rid = built
    before = client.get(f"/api/runs/{rid}/html", headers=h).text
    stubbed(monkeypatch, page_patch("note"))
    planned = client.post(f"{ide}/plan", json={"instruction": "compact and style it"}, headers=h).json()
    assert len(planned["affected"]) == 2

    out = client.post(f"{ide}/reject", json={"id": "i1", "reason": "not the copy I wanted"}, headers=h)
    assert out.status_code == 200 and out.json()["proposal"]["status"] == "rejected"
    s = state(client, h, rid)
    assert s["ide_edits"][0]["result"]["reason"] == "not the copy I wanted"
    assert client.get(f"/api/runs/{rid}/html", headers=h).text == before
    assert s["html_version"] == 1 and s["revisions"] == 0 and s["workspace_versions"] == []


def test_a_proposal_is_listed_newest_first_with_what_became_of_each(built, monkeypatch):
    client, h, ide, _ = built
    stubbed(monkeypatch, page_patch())
    client.post(f"{ide}/plan", json={"instruction": "compact"}, headers=h)
    client.post(f"{ide}/reject", json={"id": "i1"}, headers=h)
    stubbed(monkeypatch, page_patch("second"))
    client.post(f"{ide}/plan", json={"instruction": "and note it"}, headers=h)

    rows = client.get(f"{ide}/proposals", headers=h).json()["proposals"]
    assert [r["id"] for r in rows] == ["i2", "i1"]
    assert rows[1]["status"] == "rejected" and rows[0]["status"] == "proposed"


def test_a_run_out_of_revisions_cannot_ask_for_another_change(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, page_patch())
    client.post(f"{ide}/plan", json={"instruction": "compact"}, headers=h)
    assert client.post(f"{ide}/apply", json={"id": "i1"}, headers=h).status_code == 202

    monkeypatch.setattr(app.state.settings, "max_revisions", 1)
    over = client.post(f"{ide}/plan", json={"instruction": "again"}, headers=h)
    assert over.status_code == 429 and "Revision limit" in over.json()["detail"]
    assert state(client, h, rid)["ide_edits"][0]["id"] == "i1"


# --------------------------------------------------------------------------- adding a file, not only editing one

def new_page(name="contact.html", body="Contact us"):
    return {"summary": "Add a contact page beside the landing page.",
            "changes": [{"file": name, "op": "create",
                         "text": f"<html><body><h1>{body}</h1></body></html>",
                         "note": "the page the request asked for"}]}


def test_a_proposal_can_add_a_file_the_workspace_does_not_hold_yet(built, monkeypatch):
    client, h, ide, rid = built
    agent = stubbed(monkeypatch, new_page())
    out = client.post(f"{ide}/plan", json={"instruction": "add a contact page"}, headers=h)
    assert out.status_code == 200
    data = out.json()
    assert data["affected"][0]["op"] == "create" and data["affected"][0]["kind"] == "source"
    assert data["diffs"]["contact.html"]["added"] >= 1
    # the honest description of what applying this costs: no page rebuild, so no revision spent
    assert "no revision is spent" in data["applies_through"]
    assert data["limits"]["max_new_files"] == ide_assistant.MAX_NEW_FILES
    assert "create" in agent.ask and '"op": "create"' in agent.ask

    s = state(client, h, rid)
    assert "contact.html" not in [f["name"] for f in s["files"]]      # proposed, not written
    assert s["html_version"] == 1 and s["revisions"] == 0


def test_applying_a_new_file_writes_it_without_rebuilding_the_page(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, new_page())
    client.post(f"{ide}/plan", json={"instruction": "add a contact page"}, headers=h)

    started = client.post(f"{ide}/apply", json={"id": "i1", "base_version": 1}, headers=h)
    assert started.status_code == 202 and started.json()["status"] == "awaiting_approval"

    s = state(client, h, rid)
    assert "contact.html" in [f["name"] for f in s["files"]]
    assert s["html_version"] == 1 and s["revisions"] == 0       # the page was not touched, so neither moved
    stored = client.get(f"/api/runs/{rid}/workspace/files/contact.html", headers=h).json()
    assert "<h1>Contact us</h1>" in stored["text"] and stored["kind"] == "source"
    assert stored["save_via"] == "save" and stored["editable"] is True

    edit = s["ide_edits"][0]
    assert edit["status"] == "applied" and edit["result"]["applied_files"] == ["contact.html"]
    # a new file earns the undo step the Explorer gives one, so a bad proposal is walkable back
    assert client.get(f"/api/runs/{rid}/workspace", headers=h).json()["undo"]["can_undo"] is True


def test_creating_a_name_the_workspace_already_holds_is_refused(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, new_page(name="index.html"))
    out = client.post(f"{ide}/plan", json={"instruction": "recreate the page"}, headers=h)
    assert out.status_code == 502 and "already exists" in out.json()["detail"]
    assert state(client, h, rid)["ide_edits"] == []


def test_a_new_file_cannot_take_a_name_the_page_already_owns(built, monkeypatch):
    """README.md is published from the page, so "create" meets the same refusal as any existing name."""
    client, h, ide, _ = built
    stubbed(monkeypatch, new_page(name="README.md"))
    out = client.post(f"{ide}/plan", json={"instruction": "add a readme"}, headers=h)
    assert out.status_code == 502 and "README.md already exists" in out.json()["detail"]
    # and on a workspace that does not hold it, `validate_authored` still refuses the name on ownership
    with pytest.raises(ide_assistant.PatchError) as exc:
        ide_assistant.verify({"changes": [{"file": "README.md", "op": "create", "text": "# mine now"}]},
                             {"index.html": "<html>a</html>"})
    assert "rebuilt from the page" in exc.value.message


def test_a_new_file_is_not_counted_against_the_page_line_budget(built, monkeypatch):
    """"Add a page" writes a whole document; the guard is there to stop a rewrite of the one that exists."""
    client, h, ide, rid = built
    stubbed(monkeypatch, new_page(body="x\n" * 700))
    assert client.post(f"{ide}/plan", json={"instruction": "add a long page"}, headers=h).status_code == 200


# --------------------------------------------------------------------------- accepting part of a proposal

def test_a_reviewer_can_accept_one_file_of_a_proposal_and_leave_the_rest(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, page_patch("note the reviewer did not want"))
    client.post(f"{ide}/plan", json={"instruction": "compact the form and note it"}, headers=h)

    started = client.post(f"{ide}/apply", json={"id": "i1", "files": ["index.html"], "base_version": 1},
                          headers=h)
    assert started.status_code == 202
    page = client.get(f"/api/runs/{rid}/html", headers=h).text
    assert REPLACEMENT in page                                  # the accepted file moved
    assert "note the reviewer did not want" not in page          # the refused one did not

    edit = state(client, h, rid)["ide_edits"][0]
    assert edit["status"] == "applied"
    assert edit["result"]["applied_files"] == ["index.html"]
    assert edit["result"]["skipped_files"] == ["styles.css"]


def test_a_named_file_the_proposal_never_offered_is_refused(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, page_patch())
    client.post(f"{ide}/plan", json={"instruction": "compact the form"}, headers=h)
    out = client.post(f"{ide}/apply", json={"id": "i1", "files": ["app.js"]}, headers=h)
    assert out.status_code == 409 and "does not change app.js" in out.json()["detail"]
    assert state(client, h, rid)["ide_edits"][0]["status"] == "proposed"


def test_accepting_every_named_file_of_a_proposal_is_the_same_as_accepting_it(built, monkeypatch):
    client, h, ide, rid = built
    stubbed(monkeypatch, page_patch("note"))
    client.post(f"{ide}/plan", json={"instruction": "compact and note"}, headers=h)
    out = client.post(f"{ide}/apply", json={"id": "i1", "files": ["index.html", "styles.css"]}, headers=h)
    assert out.status_code == 202
    assert state(client, h, rid)["ide_edits"][0]["result"]["skipped_files"] == []


# --------------------------------------------------------------------------- who may reach these routes

def test_another_user_and_no_token_get_nothing_at_all(built):
    client, h, ide, rid = built
    r = client.post("/api/auth/register", json={"email": "nosy3@example.com", "password": "supersecret1",
                                                "name": "N"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"{ide}/proposals", headers=other).status_code == 404
    assert client.post(f"{ide}/plan", json={"instruction": "change my page"}, headers=other).status_code == 404
    assert client.post(f"{ide}/apply", json={"id": "i1"}).status_code == 401
    assert client.post(f"{ide}/reject", json={"id": "i1"}).status_code == 401
    assert client.get(f"/api/runs/not-an-id/ide/proposals", headers=h).status_code == 404
    assert client.get(f"{ide}/proposals", headers=h).json()["proposals"] == []


# --------------------------------------------------------------------------- the service on its own

TEXTS = {"index.html": "<html><body><p class='a'>One</p></body></html>",
         "styles.css": ".a { color: red }\n", "notes.md": "# notes\n"}


def test_choose_puts_the_files_the_request_names_first_and_reports_what_it_clipped():
    picked, clipped = ide_assistant.choose(TEXTS, "redden the paragraph in styles.css")
    assert picked[0] == "styles.css" and "index.html" in picked and clipped == []
    huge = dict(TEXTS, **{"big.css": "x" * (ide_assistant.MAX_FILE_BYTES_SENT + 10)})
    picked, clipped = ide_assistant.choose(huge, "touch big.css")
    assert picked[0] == "big.css" and clipped == ["big.css"]
    assert "--- big.css ---" in ide_assistant.prompt(instruction="touch big.css", texts=huge, picked=picked,
                                                     clipped=clipped)
    assert "file clipped here" in ide_assistant.prompt(instruction="t", texts=huge, picked=picked, clipped=clipped)


def test_files_over_the_budget_are_dropped_rather_than_sent_thin():
    many = {f"f{i}.css": "y" * 20_000 for i in range(12)}
    picked, clipped = ide_assistant.choose(many, "change all of them")
    assert 0 < len(picked) < len(many)
    assert sum(len(many[n]) for n in picked) <= ide_assistant.MAX_TOTAL_BYTES_SENT + 20_000
    assert clipped == [n for n in picked if len(many[n]) > ide_assistant.MAX_FILE_BYTES_SENT]


def test_the_change_set_is_measured_against_the_text_and_capped_before_it_is_shown():
    ok = ide_assistant.verify({"summary": "s", "changes": [
        {"file": "styles.css", "op": "replace", "find": "color: red", "replace": "color: blue", "note": "n"}]},
        TEXTS)
    assert ok["files"] == ["styles.css"] and ok["lines_added"] == 1 and ok["per_file"]["styles.css"]["same"] is False
    assert ide_assistant.affected(ok)[0]["kind"] == "derived"

    for raw, reason in (({"changes": []}, "No changes given"),
                        ({"changes": [{"file": "styles.css", "op": "replace", "find": "nope", "replace": "x"}]},
                         "not in that file"),
                        ({"changes": [{"file": "styles.css", "op": "teleport", "find": "a", "replace": "b"}]},
                         "Unknown operation"),
                        ({"changes": [{"file": "styles.css", "op": "replace", "find": "color: red",
                                       "replace": "color: red"}]}, "does nothing")):
        with pytest.raises(ide_assistant.PatchError) as exc:
            ide_assistant.verify(raw, TEXTS)
        assert reason in exc.value.message


def test_a_scope_bounds_which_files_a_change_set_may_name():
    """Files that exist in the workspace and files that were sent for this request are two different sets."""
    ok = ide_assistant.verify({"changes": [{"file": "styles.css", "op": "replace", "find": "color: red",
                                            "replace": "color: teal"}]}, TEXTS, allowed=["styles.css"])
    assert ok["files"] == ["styles.css"]

    with pytest.raises(ide_assistant.PatchError) as exc:
        ide_assistant.verify({"changes": [{"file": "notes.md", "op": "append", "text": "more"}]},
                             TEXTS, allowed=["styles.css", "index.html"])
    assert "notes.md was not sent for this request" in exc.value.message
    assert "index.html, styles.css" in exc.value.message
    # with no scope - a request over the whole workspace - the only bound left is that the file is real
    assert ide_assistant.verify({"changes": [{"file": "notes.md", "op": "append", "text": "more"}]},
                                TEXTS)["files"] == ["notes.md"]


def test_two_changes_on_one_file_are_refused_as_they_are_in_the_pipeline():
    with pytest.raises(workspace_manager.WorkspaceError) as exc:
        ide_assistant.verify({"changes": [
            {"file": "styles.css", "op": "replace", "find": "red", "replace": "blue"},
            {"file": "styles.css", "op": "append", "text": "/* more */"}]}, TEXTS)
    assert "appears twice" in exc.value.message


def test_a_proposal_that_rewrites_the_page_is_a_rebuild_not_an_edit():
    with pytest.raises(ide_assistant.PatchError) as exc:
        ide_assistant.verify({"changes": [{"file": "notes.md", "op": "set",
                                           "text": "\n".join(f"line {i}" for i in range(700))}]}, TEXTS)
    assert "assistant edit may reach" in exc.value.message


def test_a_patch_for_text_that_is_not_in_the_page_is_refused_by_name(built):
    with pytest.raises(ide_assistant.PatchError) as exc:
        ide_assistant.verify({"changes": [{"file": "index.html", "op": "replace", "find": "<marquee>",
                                           "replace": "<div>"}]}, TEXTS)
    assert "index.html" in exc.value.message and "not in that file" in exc.value.message


# --------------------------------------------------------------------------- what the editor is showing

def test_the_open_file_and_the_selected_text_reach_the_model(built, monkeypatch):
    """The request says "this button"; only the selection says which one the reviewer meant."""
    client, h, ide, _ = built
    agent = stubbed(monkeypatch, page_patch())
    out = client.post(f"{ide}/plan", json={"instruction": "tighten this button",
                                           "active_file": "styles.css",
                                           "selection": ".signup { padding: 24px }"}, headers=h)
    assert out.status_code == 200
    assert "THE USER IS VIEWING styles.css WITH THIS REGION SELECTED" in agent.ask
    assert ".signup { padding: 24px }" in agent.ask
    assert out.json()["sent_files"][0] == "styles.css"          # the open file leads the set that is sent
    assert out.json()["proposal"]["context"] == {"active_file": "styles.css", "has_selection": True}


def test_an_open_file_a_request_did_not_name_is_still_sent_first(built, monkeypatch):
    client, h, ide, _ = built
    stubbed(monkeypatch, page_patch())
    out = client.post(f"{ide}/plan", json={"instruction": "something vague", "active_file": "app.js"}, headers=h)
    assert out.json()["sent_files"][0] == "app.js"
    # no selection, so the prompt points at the file without claiming a region was highlighted
    assert out.json()["proposal"]["context"]["has_selection"] is False


def test_an_active_file_that_is_not_in_the_workspace_is_ignored_not_an_error(built, monkeypatch):
    client, h, ide, _ = built
    stubbed(monkeypatch, page_patch())
    out = client.post(f"{ide}/plan", json={"instruction": "compact", "active_file": "ghost.tsx"}, headers=h)
    assert out.status_code == 200 and out.json()["proposal"]["context"]["active_file"] == ""


# --------------------------------------------------------------------------- the same rules, off the wire

def test_a_created_file_is_checked_by_the_rules_a_feature_build_is_held_to():
    ok = ide_assistant.verify({"changes": [{"file": "about.html", "op": "create",
                                            "text": "<html><body>About</body></html>"}]}, TEXTS)
    assert ok["changes"] == [] and [c["file"] for c in ok["creates"]] == ["about.html"]
    assert ok["files"] == ["about.html"] and ok["after"]["about.html"].startswith("<html>")
    assert ide_assistant.affected(ok)[0]["save_via"] == "create"

    for raw, reason in (({"changes": [{"file": "styles.css", "op": "create", "text": "<b>new</b>"}]},
                         "already exists"),
                        ({"changes": [{"file": "notes/../evil.md", "op": "create", "text": "content"}]},
                         "not a workspace file name"),
                        ({"changes": [{"file": "app.rb", "op": "create", "text": "puts 1"}]},
                         "unsupported extension"),
                        ({"changes": [{"file": "a.md", "op": "create", "text": "tiny"}]},
                         "empty or stub"),
                        ({"changes": [{"file": "", "op": "create", "text": "some content"}]},
                         "name is required")):
        with pytest.raises(ide_assistant.PatchError) as exc:
            ide_assistant.verify(raw, TEXTS)
        assert reason in exc.value.message


def test_one_request_may_only_add_a_handful_of_files():
    many = [{"file": f"p{i}.html", "op": "create", "text": f"<html>{i}</html>"}
            for i in range(ide_assistant.MAX_NEW_FILES + 1)]
    with pytest.raises(ide_assistant.PatchError) as exc:
        ide_assistant.verify({"changes": many}, TEXTS)
    assert "new files, over the" in exc.value.message


def test_a_proposal_may_be_all_new_files_with_no_edits_at_all():
    """`verify` used to need one patch to exist; a request that only adds a page has none."""
    with pytest.raises(ide_assistant.PatchError) as exc:
        ide_assistant.verify({"changes": []}, TEXTS)
    assert "No changes given" in exc.value.message
    assert ide_assistant.verify({"changes": [{"file": "x.md", "op": "create", "text": "# brand new\n"}]},
                                TEXTS)["changes"] == []


def test_selecting_names_the_files_a_reviewer_accepted_and_refuses_the_rest():
    entry = {"id": "i1", "changes": [{"file": "index.html", "op": "set", "text": "a"}],
             "creates": [{"file": "about.html", "text": "b"}], "files": ["index.html", "about.html"]}
    assert ide_assistant.select(entry, None) == (entry["changes"], entry["creates"])
    assert ide_assistant.select(entry, []) == (entry["changes"], entry["creates"])
    assert ide_assistant.select(entry, ["about.html"]) == ([], entry["creates"])
    with pytest.raises(workspace_manager.WorkspaceError) as exc:
        ide_assistant.select(entry, ["app.js"])
    assert "does not change app.js" in exc.value.message
