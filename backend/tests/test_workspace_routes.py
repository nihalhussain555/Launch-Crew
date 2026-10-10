"""Workspace API: index, impact, plans, patches and snapshots over the real endpoints."""
import pytest
from fastapi.testclient import TestClient

from app.api import routes_auth
from app.main import app
from app.tools import browser_checks, differ
from tests.conftest import GOOD_CHECKS

MARKER = "/* workspace-marker */"


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
    """A logged-in user with one run sitting at the approval gate."""
    r = client.post("/api/auth/register", json={"email": "api@example.com", "password": "supersecret1", "name": "API"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A tiny CRM for solo founders"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    return client, h, f"/api/runs/{rid}/workspace", rid


def state(client, h, rid):
    return client.get(f"/api/runs/{rid}", headers=h).json()["state"]


# --------------------------------------------------------------------------- reading

def test_overview_reports_the_workspace_without_leaking_storage_keys(built):
    client, h, ws, rid = built
    body = client.get(ws, headers=h)
    assert body.status_code == 200
    data = body.json()
    assert data["version"] == 1 and data["status"] == "awaiting_approval" and data["snapshots"] == []
    assert [f["name"] for f in data["files"]] == ["index.html", "styles.css", "app.js", "README.md"]
    assert data["limits"]["ops"] == ["replace", "replace_all", "append", "set"]
    assert data["limits"]["keep_snapshots"] == 10 and data["latest_snapshot"] == 0
    assert "key" not in body.text                                  # storage keys are server-side only
    assert data["impact"] is None and data["changed_files"] is None and data["validation"] is None


def test_index_endpoint_summarises_then_expands(built):
    client, h, ws, _ = built
    summary = client.get(f"{ws}/index", headers=h).json()
    assert summary["version"] == 1 and summary["counts"]["indexed"] == 4
    assert {"name", "language", "bytes", "indexed", "symbols", "refs"} <= set(summary["files"][0])
    assert "hero" in " ".join(summary["names"]) and "symbols" not in summary

    full = client.get(f"{ws}/index", headers=h, params={"full": "true"}).json()
    assert full["symbols"] and full["refs"] and len(full["entries"]) == len(full["files"])
    assert any(s["file"] == "index.html" and s["where"] == "markup" for s in full["symbols"])


def test_impact_endpoint_is_read_only(built):
    client, h, ws, rid = built
    body = client.get(f"{ws}/impact", headers=h, params={"text": "rename the hero card to hero-panel"})
    assert body.status_code == 200
    report = body.json()
    assert report["version"] == 1 and report["counts"]["targets"] >= 1
    assert report["block"].startswith("IMPACT REPORT for v1") and "RULES:" in report["block"]
    assert "workspace change" in report["headline"] or "change:" in report["headline"]
    assert state(client, h, rid)["impact"] is None                 # asking is not the same as recording
    assert client.get(f"{ws}/impact", headers=h, params={"text": "ab"}).status_code == 422


def test_workspace_endpoints_need_a_run_and_a_login(built):
    client, h, ws, rid = built
    assert client.get(ws).status_code == 401
    r = client.post("/api/auth/register", json={"email": "nosy@example.com", "password": "supersecret1", "name": "N"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for path in ("", "/index", "/versions", "/diff?w=1"):
        assert client.get(f"{ws}{path}", headers=other).status_code == 404
    assert client.get(f"/api/runs/{rid}/workspace/impact", headers=other,
                      params={"text": "anything at all"}).status_code == 404
    assert client.post(f"{ws}/plan", headers=other,
                       json={"changes": [{"file": "styles.css", "op": "append", "text": "x"}]}).status_code == 404
    assert client.get("/api/runs/not-an-id/workspace", headers=h).status_code == 404


# --------------------------------------------------------------------------- planning

def test_plan_proves_the_patch_without_writing_a_byte(built):
    client, h, ws, rid = built
    before = client.get(f"/api/runs/{rid}/html", headers=h).text
    res = client.post(f"{ws}/plan", headers=h, json={
        "request": "append a marker to styles.css",
        "changes": [{"file": "styles.css", "op": "append", "text": MARKER, "note": "proof"}]})
    assert res.status_code == 200
    body = res.json()

    assert body["plan"]["status"] == "proposed" and body["plan"]["id"] == "p1"
    assert body["plan"]["summary"]["changes"][0]["file"] == "styles.css"
    assert set(body["projection"]["changed"]) == {"index.html", "styles.css"}   # the patch, before publish rewrites README
    assert body["diffs"]["styles.css"]["added"] >= 1
    assert body["impact"]["request"] == "append a marker to styles.css"
    assert body["safe_to_apply"] in (True, False)

    s = state(client, h, rid)
    assert s["html_version"] == 1 and client.get(f"/api/runs/{rid}/html", headers=h).text == before
    assert [p["id"] for p in s["change_plans"]] == ["p1"] and s["impact"]["version"] == 1
    assert s["workspace_versions"] == []                           # nothing was captured: nothing was written


def test_plan_rejects_the_changes_a_workspace_cannot_apply(built):
    client, h, ws, rid = built
    cases = (
        ({"changes": [{"file": "styles.css", "op": "replace", "find": "#no-such-rule", "replace": "x"}]},
         422, "not in that file"),
        ({"changes": [{"file": "notes.md", "op": "append", "text": "x"}]}, 404, "not in this build"),
        ({"changes": [{"file": "../index.html", "op": "append", "text": "x"}]}, 422, "not a workspace file name"),
        ({"changes": [{"file": "index.html", "op": "swap", "find": "a", "replace": "b"}]}, 422, "Unknown operation"),
        ({"changes": [{"file": "README.md", "op": "append", "text": "x"}]}, 422, "rewritten by the crew"),
        ({"changes": [{"file": "styles.css", "op": "append", "text": "x"},
                      {"file": "styles.css", "op": "append", "text": "y"}]}, 422, "appears twice"),
        ({"changes": [{"file": "styles.css", "op": "append", "text": "x"} for _ in range(13)]}, 422, "at most 12"),
        ({"changes": []}, 422, "at least 1"),
    )
    for payload, code, needle in cases:
        res = client.post(f"{ws}/plan", headers=h, json=payload)
        assert res.status_code == code, (payload, res.text)
        assert needle in res.text
    assert state(client, h, rid)["html_version"] == 1
    assert state(client, h, rid)["change_plans"] == []             # a rejected plan is not kept


# --------------------------------------------------------------------------- applying

def test_apply_patches_the_page_and_its_derived_copy(built):
    client, h, ws, rid = built
    res = client.post(f"{ws}/apply", headers=h, json={
        "request": "append a marker to styles.css",
        "changes": [{"file": "styles.css", "op": "append", "text": MARKER}]})
    assert res.status_code == 202 and res.json()["status"] == "running"   # claimed, then worked in the background
    assert client.get(f"/api/runs/{rid}", headers=h).json()["status"] == "awaiting_approval"

    s = state(client, h, rid)
    assert s["html_version"] == 2 and s["revisions"] == 1
    assert set(s["changed_files"]["changed"]) == {"index.html", "styles.css", "README.md"}
    assert s["validation"] == {**s["validation"], "kind": "file patch", "status": "clean",
                               "version": 2, "check_errors": 0}
    assert s["change_plans"][-1]["status"] == "applied"
    assert s["change_plans"][-1]["result"]["workspace_version"] == 1
    assert s["chat"][-2]["target"] == "files" and s["chat"][-1]["role"] == "assistant"

    page = client.get(f"/api/runs/{rid}/html", headers=h).text          # the canonical page holds the edit
    css = client.get(f"/api/runs/{rid}/files/styles.css", headers=h).text  # and so does the derived file
    assert MARKER in page and MARKER in css and page.count(MARKER) == 1
    assert len(s["workspace_versions"]) == 1 and s["workspace_versions"][0]["w"] == 1


def test_apply_is_refused_before_the_run_leaves_the_gate(built):
    client, h, ws, rid = built
    good = {"changes": [{"file": "styles.css", "op": "append", "text": MARKER}]}
    assert client.post(f"{ws}/apply", headers=h,
                       json={"changes": [{"file": "nope.css", "op": "append", "text": "x"}]}).status_code == 404

    assert client.post(f"{ws}/apply", headers=h, json=good).status_code == 202
    assert client.post(f"/api/runs/{rid}/approve", headers=h).status_code == 202
    assert client.get(f"/api/runs/{rid}", headers=h).json()["status"] == "deployed"
    assert client.post(f"{ws}/apply", headers=h, json=good).status_code == 409
    assert client.post(f"{ws}/restore", headers=h, json={"w": 1}).status_code == 409
    assert state(client, h, rid)["html_version"] == 2                # the deployed build is still what it deployed


def test_apply_stops_at_the_revision_cap(built):
    client, h, ws, rid = built
    for _ in range(5):                                        # MAX_REVISIONS is 5 per run
        assert client.post(f"/api/runs/{rid}/chat", headers=h, json={"text": "Warmer colours please"}).status_code == 202
    assert state(client, h, rid)["revisions"] == 5
    res = client.post(f"{ws}/apply", headers=h,
                      json={"changes": [{"file": "styles.css", "op": "append", "text": MARKER}]})
    assert res.status_code == 429 and "Revision limit" in res.json()["detail"]
    assert state(client, h, rid)["html_version"] == 6          # five edits, no sixth from the capped request


# --------------------------------------------------------------------------- snapshots

def test_snapshots_hold_the_workspace_as_it_was_and_diff_against_it(built):
    client, h, ws, rid = built
    original_css = client.get(f"/api/runs/{rid}/files/styles.css", headers=h).text
    client.post(f"{ws}/apply", headers=h,
                json={"changes": [{"file": "styles.css", "op": "append", "text": MARKER}]})

    listing = client.get(f"{ws}/versions", headers=h).json()
    assert listing["latest"] == 1 and listing["current_version"] == 2
    assert listing["snapshots"][0]["note"].startswith("Before change p1")
    assert {f["name"] for f in listing["snapshots"][0]["files"]} == {"index.html", "styles.css", "app.js", "README.md"}

    detail = client.get(f"{ws}/versions/1", headers=h).json()
    assert detail["html_version"] == 1 and len(detail["files"]) == 4
    assert next(f for f in detail["files"] if f["name"] == "styles.css")["differs_from_live"] is True
    assert next(f for f in detail["files"] if f["name"] == "app.js")["differs_from_live"] is False

    kept = client.get(f"{ws}/versions/1/files/styles.css", headers=h)
    assert kept.status_code == 200 and kept.headers["content-type"].startswith("text/css")
    assert kept.text == original_css and MARKER not in kept.text

    live = client.get(f"{ws}/diff", headers=h, params={"w": 1}).json()
    by_name = {f["file"]: f for f in live["files"]}
    assert live["to"].startswith("live v2") and set(live["changed"]) == {"index.html", "styles.css", "README.md"}
    assert live["added"] >= 1 and any(r["kind"] == "add" for r in by_name["styles.css"]["rows"])
    assert by_name["app.js"]["changed"] is False and by_name["README.md"]["changed"] is True
    same = client.get(f"{ws}/diff", headers=h, params={"w": 1, "to": 1}).json()
    assert same["changed"] == [] and same["added"] == 0

    assert client.get(f"{ws}/versions/9", headers=h).status_code == 404
    assert client.get(f"{ws}/versions/1/files/README.md", headers=h).status_code == 200
    assert client.get(f"{ws}/versions/1/files/app.css", headers=h).status_code == 404
    assert client.get(f"{ws}/versions/1/files/.env.css", headers=h).status_code == 422
    assert client.get(f"{ws}/versions/1/files/..%2Fstyles.css", headers=h).status_code == 404
    assert client.get(f"{ws}/diff", headers=h, params={"w": 42}).status_code == 404


def test_restore_puts_every_file_back(built):
    client, h, ws, rid = built
    before = client.get(f"/api/runs/{rid}/html", headers=h).text
    client.post(f"{ws}/apply", headers=h,
                json={"changes": [{"file": "styles.css", "op": "append", "text": MARKER}]})
    assert client.post(f"{ws}/restore", headers=h, json={"w": 1}).status_code == 202

    s = state(client, h, rid)
    assert s["html_version"] == 3 and s["revisions"] == 1                    # rolling back is not an AI edit
    assert s["validation"]["kind"] == "workspace restore" and s["validation"]["restored_from"] == 1
    assert [v["w"] for v in s["workspace_versions"]] == [1, 2]               # the pre-restore state is kept too
    assert differ.readable(client.get(f"/api/runs/{rid}/html", headers=h).text) == differ.readable(before)
    assert MARKER not in client.get(f"/api/runs/{rid}/files/styles.css", headers=h).text
    assert "Restored workspace snapshot w1 as v3" in s["chat"][-1]["text"]

    assert client.post(f"{ws}/restore", headers=h, json={"w": 77}).status_code == 404
    assert client.post(f"{ws}/restore", headers=h, json={"w": 0}).status_code == 422


def test_the_plan_and_snapshot_records_survive_a_later_ai_revision(built):
    """A crew rebuild must not forget the file-level work that came before it."""
    client, h, ws, rid = built
    client.post(f"{ws}/plan", headers=h, json={"changes": [{"file": "styles.css", "op": "append", "text": MARKER}]})
    client.post(f"{ws}/apply", headers=h,
                json={"changes": [{"file": "styles.css", "op": "append", "text": MARKER}]})
    assert client.post(f"/api/runs/{rid}/chat", headers=h, json={"text": "Make the button bigger"}).status_code == 202

    s = state(client, h, rid)
    assert [p["status"] for p in s["change_plans"]] == ["proposed", "applied"]
    assert len(s["workspace_versions"]) == 1                     # an AI rebuild re-publishes; only patches capture
    assert s["impact"]["version"] == 2                           # the revision measured the patched build
    assert s["validation"]["kind"] == "crew rebuild" and s["validation"]["version"] == s["html_version"] == 3
