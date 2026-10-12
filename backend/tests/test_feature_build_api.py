"""Real website features over HTTP: a plain-English ask, the patch and source it means, what Apply writes.

Four promises the brief makes are tested here against the running API rather than against the services in
isolation:

* a sentence becomes a build without the user naming a key - and a sentence that names nothing, or a key
  Launch Crew has no source for, is refused instead of being swapped for the nearest real thing;
* nothing is claimed that is not measured: the byte counts a proposal lists are the bytes the workspace
  holds afterwards, and a feature whose provider is unconfigured comes back `needs-external-setup` with
  the variables and the steps that remain, never as "store added";
* the change goes through the same gate as every other edit - snapshot, sanitizer, checks, new version -
  and a proposal that no longer means this page is refused rather than forced onto it;
* what ships beside the page is source, not a stub: real routes, real tables, and every credential read
  from the environment, with no value for one anywhere in the file set.
"""
import pytest
from fastapi.testclient import TestClient

from app.agents import capabilities as caps
from app.api import routes_auth
from app.main import app
from app.services import feature_blocks as blocks
from app.services import feature_build, feature_plan, feature_templates as templates
from app.services.workspace_manager import WorkspaceError
from app.tools import browser_checks
from tests.conftest import GOOD_CHECKS


@pytest.fixture
def client(monkeypatch):
    """Chromium is not the subject here - the build just has to reach the checks and pass them."""
    async def fake(html):
        return GOOD_CHECKS, {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    routes_auth._auth_limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    routes_auth._auth_limiter._hits.clear()


@pytest.fixture
def built(client):
    """One logged-in user, one project, one run sitting at the approval gate."""
    r = client.post("/api/auth/register", json={"email": "greenhouse@example.com",
                                                "password": "supersecret1", "name": "Greenhouse"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A plant shop with a workshop booking desk",
                                             "spec": {"style": "startup"}}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    assert client.get(f"/api/runs/{rid}", headers=h).json()["status"] == "awaiting_approval"
    return client, h, rid, f"/api/runs/{rid}/features"


def state(client, h, rid):
    return client.get(f"/api/runs/{rid}", headers=h).json()["state"]


def page_of(client, h, rid):
    return client.get(f"/api/runs/{rid}/html", headers=h).text


def names(client, h, rid):
    return [f["name"] for f in client.get(f"/api/runs/{rid}/files", headers=h).json()["files"]]


def sizes(client, h, rid):
    return {f["name"]: f["bytes"] for f in client.get(f"/api/runs/{rid}/files", headers=h).json()["files"]}


def proposals(client, h, fs):
    return client.get(fs, headers=h).json()["proposals"]


def plan(client, h, fs, **body):
    return client.post(f"{fs}/plan", json=body, headers=h)


def propose(client, h, fs, **body):
    return client.post(f"{fs}/propose", json=body, headers=h)


def apply(client, h, fs, proposal_id, **body):
    return client.post(f"{fs}/apply", json={"id": proposal_id, **body}, headers=h)


# ------------------------------------------------------------------ the catalog and the doors

def test_the_feature_routes_need_a_signed_in_user(client):
    assert client.get("/api/capabilities").status_code == 401
    missing = "000000000000000000000000"
    assert client.get(f"/api/runs/{missing}/features").status_code == 401
    for path in ("/plan", "/propose", "/apply", "/reject"):
        res = client.post(f"/api/runs/{missing}/features{path}", json={})
        assert res.status_code == 401, path


def test_the_catalog_offers_only_features_that_have_source(client):
    r = client.post("/api/auth/register", json={"email": "cat@example.com", "password": "supersecret1",
                                                "name": "Cat"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    body = client.get("/api/capabilities", headers=h).json()
    assert [c["key"] for c in body["capabilities"]] == list(caps.keys())
    assert set(body["surfaces"]) == set(caps.SURFACES)
    for card in body["capabilities"]:
        assert card["key"] in blocks.IMPLEMENTED, "the picker offered a feature with no source behind it"
        # a card is only as good as its weakest surface, and it says so in the catalog's own words
        weakest = caps.overall_status(tuple(caps.Part(p["surface"], p["state"], "", (), ())
                                            for p in card["parts"]))
        assert card["status"] == weakest == caps.overall_status(caps.get(card["key"]).parts)
        assert card["status_label"] == caps.STATE_LABEL[card["status"]]
    assert body["counts"]["capabilities"] == len(caps.keys())
    assert set(caps.keys()) == set(blocks.IMPLEMENTED)


def test_a_run_that_is_not_yours_has_no_feature_routes(client):
    first = client.post("/api/auth/register", json={"email": "mine@example.com",
                                                    "password": "supersecret1", "name": "Mine"})
    h = {"Authorization": f"Bearer {first.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A reading list for a book club"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    second = client.post("/api/auth/register", json={"email": "other@example.com",
                                                     "password": "supersecret1", "name": "Other"})
    ho = {"Authorization": f"Bearer {second.json()['access_token']}"}
    assert client.get(f"/api/runs/{rid}/features", headers=ho).status_code == 404
    for path in ("/plan", "/propose", "/apply", "/reject"):
        res = client.post(f"/api/runs/{rid}/features{path}", json={"id": "f1", "keys": ["blog"]}, headers=ho)
        assert res.status_code == 404, path
    # the owner's own record is honest about having nothing on offer yet
    body = client.get(f"/api/runs/{rid}/features", headers=h).json()
    assert body["proposals"] == [] and body["built"] == [] and body["panels_present"] == []
    assert body["status"] == "awaiting_approval" and body["version"] == 1


# ------------------------------------------------------------------ asking in plain English

def test_a_plain_english_ask_becomes_a_build_without_naming_a_key(built):
    client, h, rid, fs = built
    out = plan(client, h, fs, request="I want a contact form and a blog people can publish to")
    assert out.status_code == 200, out.text
    data = out.json()
    assert {"blog", "contact"} <= set(data["keys"])
    assert {"blog", "contact"} <= set(data["introduces"])
    assert {row["key"] for row in data["features"]} >= {"blog", "contact"}
    assert "frontend changes" in data["need_words"] and "backend logic" in data["need_words"]
    assert data["present_before"] == [] and data["replacing"] is False
    assert data["page_bytes"] > 0 and all(f["bytes"] > 0 for f in data["files"])
    assert data["overall"] in caps.STATES and data["overall_label"] == caps.STATE_LABEL[data["overall"]]


def test_planning_a_request_records_nothing_and_writes_no_file(built):
    client, h, rid, fs = built
    before, measured = names(client, h, rid), sizes(client, h, rid)
    page = page_of(client, h, rid)
    out = plan(client, h, fs, request="add a shopping cart and checkout")
    assert out.status_code == 200, out.text
    assert "catalog" in out.json()["keys"]
    assert proposals(client, h, fs) == []
    assert state(client, h, rid)["feature_edits"] == []
    assert names(client, h, rid) == before and sizes(client, h, rid) == measured
    assert page_of(client, h, rid) == page


def test_a_key_launch_crew_has_no_source_for_is_refused_not_swapped(built):
    """A click on something that cannot be built must not buy a plausible-looking substitute."""
    client, h, rid, fs = built
    out = plan(client, h, fs, keys=["payments"])
    assert out.status_code == 422, out.text
    detail = out.json()["detail"]
    assert "'payments'" in detail and "will not be built" in detail
    assert "Contact forms" in detail
    assert proposals(client, h, fs) == []


def test_a_sentence_that_names_no_feature_is_refused_with_the_list_that_works(built):
    client, h, rid, fs = built
    out = plan(client, h, fs, request="make it sing")
    assert out.status_code == 422, out.text
    assert "make it sing" in out.json()["detail"] and "Contact forms" in out.json()["detail"]
    assert proposals(client, h, fs) == []


def test_a_feature_that_needs_accounts_says_which_one_it_pulled_in(built):
    client, h, rid, fs = built
    out = plan(client, h, fs, request="let signed-in members edit their own profile settings")
    assert out.status_code == 200, out.text
    data = out.json()
    assert data["keys"] == ["authentication", "profiles"]
    assert data["added"] == ["authentication"] and data["named"] == ["profiles"]
    assert any(w.startswith("Pulled in") for w in data["warnings"])


# ------------------------------------------------------------------ proposing

def test_a_proposal_carries_the_patch_and_the_source_and_writes_nothing(built):
    client, h, rid, fs = built
    before, measured = names(client, h, rid), sizes(client, h, rid)
    out = propose(client, h, fs, request="add a contact form", base_version=1)
    assert out.status_code == 200, out.text
    data = out.json()
    entry = data["proposal"]
    assert entry["id"] == "f1" and entry["status"] == "proposed" and entry["version"] == 1
    assert entry["keys"] == ["contact"] and entry["introduces"] == ["contact"]
    assert entry["patch"]["file"] == "index.html" and entry["patch"]["op"] == "replace"
    assert entry["patch"]["find_quote"] == "</main>", "a first block goes in front of the content area"
    # the patch writes the block and keeps its anchor, which is the only difference from `markup_bytes`
    assert entry["patch"]["replace_bytes"] == entry["markup_bytes"] + len(entry["patch"]["find_quote"])
    assert entry["page_bytes"] == entry["markup_bytes"]
    assert {"server.py", "db.py", "schema.sql", "env_template.txt", "SETUP.md", "FEATURES.md",
            "feature_client.js", "requirements.txt"} == {f["name"] for f in entry["files"]}
    assert all(f["bytes"] > 0 and f["note"] for f in entry["files"])
    assert names(client, h, rid) == before and sizes(client, h, rid) == measured
    assert state(client, h, rid)["html_version"] == 1
    assert data["projection"]["changed"] == ["index.html"]
    assert data["diffs"]["index.html"]["added"] >= 1
    assert data["safe_to_apply"] is True and data["headline"] and data["impact"]["version"] == 1
    listed = proposals(client, h, fs)
    assert [e["id"] for e in listed] == ["f1"]
    assert "changes" not in listed[0], "the status listing must not carry a whole page block per proposal"


def test_a_page_only_feature_promises_no_server(built):
    """Search over what the page already carries is genuinely complete, so it may be reported with no
    environment variables and no setup steps - the one case where that claim is true."""
    client, h, rid, fs = built
    out = plan(client, h, fs, keys=["browse"])
    assert out.status_code == 200, out.text
    data = out.json()
    assert data["keys"] == ["browse"] and data["overall"] == caps.GENERATED
    assert data["env"] == []
    assert [f["name"] for f in data["files"]] == ["FEATURES.md", "feature_sections.html"]
    assert "nothing left to set up" in data["summary"]
    entry = propose(client, h, fs, keys=["browse"]).json()["proposal"]
    assert entry["server"] is False and entry["authored_names"] == ["FEATURES.md"]
    assert apply(client, h, fs, entry["id"], base_version=1).status_code == 202
    assert not {"server.py", "db.py", "schema.sql", "feature_client.js"} & set(names(client, h, rid))
    assert 'data-lc-feature="browse"' in page_of(client, h, rid)
    assert "data-lc-wait" not in page_of(client, h, rid), "a panel that works must not say it is waiting"


# ------------------------------------------------------------------ applying

def test_applying_a_feature_build_writes_the_block_and_the_source_it_promised(built):
    client, h, rid, fs = built
    entry = propose(client, h, fs, request="add a contact form").json()["proposal"]
    promised = {f["name"]: f["bytes"] for f in entry["files"]}
    assert apply(client, h, fs, entry["id"], base_version=1).status_code == 202

    s = state(client, h, rid)
    page = page_of(client, h, rid)
    assert s["html_version"] == 2 and s["revisions"] == 1
    assert s["validation"]["kind"] == "feature build" and s["validation"]["version"] == 2
    assert s["workspace_versions"][-1]["cause"]["kind"] == "feature build"
    # the page carries the panel and declares exactly the keys the reviewer read, in one block
    assert page.count(templates.BLOCK_HEAD) == 1
    assert feature_build.present_keys(page) == entry["keys"]
    assert 'data-lc-feature="contact"' in page
    # the source is there, at the sizes the proposal listed
    assert set(promised) <= set(names(client, h, rid))
    assert {name: sizes(client, h, rid)[name] for name in promised} == promised
    assert {(f["name"], f["bytes"]) for f in s["authored_files"]} == set(promised.items())
    assert all(f["source"] == "feature build" and f["note"] for f in s["authored_files"])

    out = proposals(client, h, fs)[0]
    assert out["status"] == "applied" and out["plan"] == "p1"
    assert out["result"]["version"] == 2 and set(out["result"]["authored"]) == set(promised)
    assert out["result"]["check_errors"] == 0
    body = client.get(fs, headers=h).json()
    assert body["panels_present"] == entry["keys"] and body["panels_missing"] == []
    assert body["built"][0]["keys"] == entry["keys"] and body["server_files"] is True


def test_the_generated_server_reads_every_credential_from_the_environment(built):
    """Env vars for external services, never a hardcoded value, and no fake OAuth standing in for it."""
    client, h, rid, fs = built
    entry = propose(client, h, fs, request="let people sign up and log in to accounts").json()["proposal"]
    assert entry["env"] and "SESSION_SECRET" in entry["env"]
    assert apply(client, h, fs, entry["id"], base_version=1).status_code == 202

    server = client.get(f"/api/runs/{rid}/files/server.py", headers=h).text
    assert 'os.environ.get("SESSION_SECRET"' in server
    assert "pbkdf2_hmac" in server and "/api/signup" in server and "/api/login" in server
    assert "/feature_client.js" in server, "the browser half of the panels is served, not inlined"
    env = client.get(f"/api/runs/{rid}/files/env_template.txt", headers=h).text
    assigned = [line.split("=", 1) for line in env.splitlines()
                if line and not line.startswith("#") and "=" in line]
    required = [name for name, _ in assigned if name in entry["env"]]
    assert required == entry["env"], "every name the plan reads must be in the template, in order"
    assert all(value.strip() == "" for _, value in assigned), "an env template carries names, not values"
    setup = client.get(f"/api/runs/{rid}/files/SETUP.md", headers=h).text
    assert all(name in server or name in setup for name in entry["env"])
    assert "oauth" not in server.lower() or "not generated" in server.lower()


def test_a_second_build_adds_to_the_page_and_leaves_the_first_features_on_it(built):
    client, h, rid, fs = built
    first = propose(client, h, fs, keys=["contact"]).json()["proposal"]
    assert apply(client, h, fs, first["id"], base_version=1).status_code == 202

    second = propose(client, h, fs, keys=["blog"], base_version=2)
    assert second.status_code == 200, second.text
    entry = second.json()["proposal"]
    assert entry["present_before"] == ["contact"] and entry["introduces"] == ["blog"]
    assert entry["keys"] == ["blog", "contact"] and entry["replacing"] is True
    assert apply(client, h, fs, entry["id"], base_version=2).status_code == 202

    page = page_of(client, h, rid)
    assert page.count(templates.BLOCK_HEAD) == 1, "the second build stacked a second copy of the panels"
    assert feature_build.present_keys(page) == ["blog", "contact"]
    assert 'data-lc-feature="contact"' in page and 'data-lc-feature="blog"' in page
    assert state(client, h, rid)["html_version"] == 3
    body = client.get(fs, headers=h).json()
    assert body["panels_missing"] == []
    assert [b["keys"] for b in body["built"]] == [["contact"], ["blog", "contact"]]


def test_a_feature_build_reports_the_setup_that_is_still_the_users(built):
    """No fake success: a checkout with no provider is returned as work remaining, in the catalog's words."""
    client, h, rid, fs = built
    entry = propose(client, h, fs,
                    request="sell plants online with a shopping cart and checkout").json()["proposal"]
    assert entry["overall"] == caps.NEEDS_SETUP
    assert entry["overall_label"] == caps.STATE_LABEL[caps.NEEDS_SETUP]
    assert {"PAYMENT_PROVIDER", "PAYMENT_SECRET_KEY", "PAYMENT_PUBLIC_KEY"} <= set(entry["env"])
    assert entry["setup"]["catalog"] and any("PAYMENT" in w for w in entry["warnings"])
    assert apply(client, h, fs, entry["id"], base_version=1).status_code == 202
    assert [e["status"] for e in proposals(client, h, fs)] == ["applied"]
    page = page_of(client, h, rid)
    assert "data-lc-wait" in page, "the panel says it is waiting for its server rather than claiming orders"
    assert proposals(client, h, fs)[0]["result"]["check_errors"] == 0


def test_the_same_proposal_cannot_be_applied_twice(built):
    client, h, rid, fs = built
    entry = propose(client, h, fs, keys=["browse"]).json()["proposal"]
    assert apply(client, h, fs, entry["id"], base_version=1).status_code == 202
    again = apply(client, h, fs, entry["id"])
    assert again.status_code == 409, again.text
    assert "already applied" in again.json()["detail"]
    assert state(client, h, rid)["html_version"] == 2
    assert page_of(client, h, rid).count(templates.BLOCK_HEAD) == 1


def test_a_proposal_read_at_an_older_version_is_refused_as_a_conflict(built):
    client, h, rid, fs = built
    entry = propose(client, h, fs, keys=["browse"]).json()["proposal"]
    moved = client.post(f"/api/runs/{rid}/workspace/apply", headers=h, json={"changes": [
        {"file": "index.html", "op": "replace", "find": "<title>", "replace": "<title>x</title><!--"}],
        "request": "someone else edited the page"})
    assert moved.status_code == 202, moved.text
    clash = apply(client, h, fs, entry["id"], base_version=1)
    assert clash.status_code == 409, clash.text
    assert "Conflict" in clash.json()["detail"]
    assert proposals(client, h, fs)[0]["status"] == "proposed"
    assert templates.BLOCK_HEAD not in page_of(client, h, rid)


def test_a_rejected_proposal_keeps_every_file_as_it_was(built):
    client, h, rid, fs = built
    before, measured = names(client, h, rid), sizes(client, h, rid)
    entry = propose(client, h, fs, request="add a contact form").json()["proposal"]
    out = client.post(f"{fs}/reject", json={"id": entry["id"], "reason": "not for this launch"}, headers=h)
    assert out.status_code == 200, out.text
    assert out.json()["proposal"]["status"] == "rejected"
    assert out.json()["proposal"]["result"]["reason"] == "not for this launch"
    assert names(client, h, rid) == before and sizes(client, h, rid) == measured
    assert state(client, h, rid)["html_version"] == 1
    refused = apply(client, h, fs, entry["id"])
    assert refused.status_code == 409 and "already rejected" in refused.json()["detail"]


def test_an_unknown_proposal_is_named_not_guessed(built):
    client, h, rid, fs = built
    propose(client, h, fs, keys=["browse"])
    missing = apply(client, h, fs, "f9")
    assert missing.status_code == 404, missing.text
    assert "'f9'" in missing.json()["detail"] and "f1" in missing.json()["detail"]


# ------------------------------------------------------------------ the same guarantees at the service edge

def test_a_patch_whose_place_in_the_page_is_gone_cannot_be_applied(built):
    """The version guard catches most edits; this catches an edit that leaves the version number intact."""
    client, h, rid, fs = built
    entry = propose(client, h, fs, keys=["contact"]).json()["proposal"]
    stored = next(e for e in state(client, h, rid)["feature_edits"] if e["id"] == entry["id"])
    page = page_of(client, h, rid)
    twice = page + page[page.find("</main>"):]          # the anchor no longer stands alone
    assert twice.count("</main>") == 2
    with pytest.raises(WorkspaceError, match="no longer here on its own"):
        feature_build.recheck(stored, {"index.html": twice})
    with pytest.raises(WorkspaceError, match="no longer writes"):
        feature_build.recheck({**stored, "keys": ["blog", "contact"]}, {"index.html": page})
    files = feature_build.authored_for(stored)
    assert {f["name"] for f in files} == set(stored["authored_names"])
    with pytest.raises(WorkspaceError, match="not what the current catalog writes"):
        feature_build.authored_for({**stored, "authored_names": ["server.py"]})


def test_a_rebuild_that_drops_the_panels_is_reported_as_missing(built):
    """History cannot prove the page still shows a feature; the page is the only witness."""
    client, h, rid, fs = built
    entry = propose(client, h, fs, keys=["browse"]).json()["proposal"]
    assert apply(client, h, fs, entry["id"], base_version=1).status_code == 202
    assert client.get(fs, headers=h).json()["panels_missing"] == []
    assert client.post(f"/api/runs/{rid}/restore", headers=h, json={"version": 1}).status_code == 202
    body = client.get(fs, headers=h).json()
    assert body["panels_present"] == [] and body["panels_missing"] == ["browse"]
    assert body["panels_declared"] is True
    assert body["built"][0]["keys"] == ["browse"], "the record is kept; only the claim changes"


def test_proposals_are_bounded_and_listed_newest_first(built):
    client, h, rid, fs = built
    asked = feature_build.MAX_FEATURE_PROPOSALS + 2
    for i in range(asked):
        out = propose(client, h, fs, keys=["browse"], request=f"browse {i}")
        assert out.status_code == 200, out.text
    body = client.get(fs, headers=h).json()
    ids = [e["id"] for e in body["proposals"]]
    assert len(ids) == feature_build.MAX_FEATURE_PROPOSALS
    assert ids == [f"f{n}" for n in range(asked, asked - feature_build.MAX_FEATURE_PROPOSALS, -1)]
    assert body["count"] == feature_build.MAX_FEATURE_PROPOSALS and body["max"] == len(ids)
    assert body["open"] is True and body["open_id"] == f"f{asked}"
    assert all(feature_plan.MAX_REQUEST_CHARS >= len(e["request"]) for e in body["proposals"])

# ------------------------------------------------------------------ the brief, the studio card, the panel

def test_a_briefs_tick_list_arrives_as_a_request_and_stays_one(client):
    """What the wizard ticks must reach both surfaces that read it, without ever reading as a build.

    The Agent Studio's counts and the panel's pre-fill come from the same stored keys, and the honest part of
    both is what neither claims: a page with no feature block has nothing live, however many boxes were ticked.
    """
    r = client.post("/api/auth/register", json={"email": "brief@example.com", "password": "supersecret1",
                                                "name": "Brief"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A yoga studio with classes to book",
                                             "spec": {"style": "startup",
                                                      "feature_keys": ["booking", "contact"]}},
                      headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    fs = f"/api/runs/{rid}/features"

    def counts():
        row = next(x for x in client.get("/api/stats", headers=h).json()["recent_runs"] if x["id"] == rid)
        return row["feature_asked"], row["feature_open"], row["feature_built"]

    assert client.get(f"/api/runs/{rid}", headers=h).json()["spec"]["feature_keys"] == ["booking", "contact"]
    assert counts() == (2, 0, 0), "the brief asked; nothing has been offered or built"
    body = client.get(fs, headers=h).json()
    assert body["proposals"] == [] and body["panels_present"] == []
    assert templates.BLOCK_HEAD not in client.get(f"/api/runs/{rid}/html", headers=h).text, \
        "a tick writes no markup: the page the crew generated is the page it always was"

    out = propose(client, h, fs, keys=["booking", "contact"], request="classes to book and a contact form")
    assert out.status_code == 200, out.text
    assert counts() == (2, 1, 0), "a proposal is an open decision, not a build"
    assert client.get(fs, headers=h).json()["panels_present"] == []

    res = apply(client, h, fs, out.json()["proposal"]["id"], base_version=out.json()["base_version"])
    assert res.status_code == 202, res.text
    assert counts() == (2, 0, 1), "applied, and the count says applied rather than asked"
    assert client.get(fs, headers=h).json()["panels_present"] == ["booking", "contact"]
