"""Workspace endpoints: files, versions, diff, restore, chat and debug over the real API."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.api import routes_auth
from app.main import app
from app.orchestrator.graph import AUDIT_ORDER
from app.tools import browser_checks, differ
from tests.conftest import BAD_CHECKS, GOOD_CHECKS


@pytest.fixture
def client(monkeypatch):
    async def fake(html):
        return GOOD_CHECKS, {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    # The auth limiter is a real per-process control (20 calls/min); earlier test files spend that
    # budget, so this file's own registrations would 429. Clear it without changing the limit.
    routes_auth._auth_limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    routes_auth._auth_limiter._hits.clear()


@pytest.fixture
def built(client):
    """A logged-in user with one run that reached the approval gate."""
    r = client.post("/api/auth/register", json={"email": "ws@example.com", "password": "supersecret1", "name": "WS"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A tiny CRM for solo founders"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    run = client.get(f"/api/runs/{rid}", headers=h).json()
    assert run["status"] == "awaiting_approval"
    return client, h, rid, run


def test_run_publishes_a_file_set(built):
    client, h, rid, run = built
    body = client.get(f"/api/runs/{rid}/files", headers=h).json()
    names = [f["name"] for f in body["files"]]
    assert names == ["index.html", "styles.css", "app.js", "README.md"]
    assert body["version"] == run["state"]["html_version"] == 1
    assert all(f["bytes"] > 0 and f["note"] for f in body["files"])


def test_file_content_and_unknown_names(built):
    client, h, rid, _ = built
    css = client.get(f"/api/runs/{rid}/files/styles.css", headers=h)
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert "{" in css.text
    assert client.get(f"/api/runs/{rid}/files/nope.css", headers=h).status_code == 404
    assert client.get(f"/api/runs/{rid}/files/..%2Findex.html", headers=h).status_code == 404


def test_zip_contains_every_workspace_file(built):
    client, h, rid, _ = built
    res = client.get(f"/api/runs/{rid}/files.zip", headers=h)
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    assert "attachment" in res.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        assert sorted(z.namelist()) == ["README.md", "app.js", "index.html", "styles.css"]
        assert b"<html" in z.read("index.html").lower()


def test_versions_track_the_current_build(built):
    client, h, rid, _ = built
    body = client.get(f"/api/runs/{rid}/versions", headers=h).json()
    assert body["current"] == 1 and len(body["versions"]) == 1
    v = body["versions"][0]
    assert v["note"] == "Initial build" and v["current"] is True
    assert v["errors"] == 0 and v["readiness"] is not None
    assert "<html" in client.get(f"/api/runs/{rid}/versions/1/html", headers=h).text.lower()
    assert client.get(f"/api/runs/{rid}/versions/77/html", headers=h).status_code == 404


def test_chat_edits_the_page_and_answers_in_thread(built):
    client, h, rid, run = built
    before = client.get(f"/api/runs/{rid}/html", headers=h).text
    res = client.post(f"/api/runs/{rid}/chat", headers=h, json={"text": "Make the headline friendlier"})
    assert res.status_code == 202
    run = client.get(f"/api/runs/{rid}", headers=h).json()
    assert run["status"] == "awaiting_approval"
    assert run["state"]["html_version"] == 2
    served = client.get(f"/api/runs/{rid}/html", headers=h).text
    assert served != before and "Finally," in served        # the ask is visible in the previewed page
    thread = run["state"]["chat"]
    assert [m["role"] for m in thread] == ["user", "assistant"]
    assert thread[0]["target"] == "copy"                      # "headline" routes to the copywriter
    assert "v2" in thread[1]["text"]
    assert [v["v"] for v in run["state"]["versions"]] == [1, 2]
    assert run["state"]["versions"][-1]["note"].startswith("copy:")


def test_chat_recolours_the_served_page(built):
    client, h, rid, _ = built
    before = client.get(f"/api/runs/{rid}/html", headers=h).text
    client.post(f"/api/runs/{rid}/chat", headers=h, json={"text": "Make the button colour #0F766E"})
    served = client.get(f"/api/runs/{rid}/html", headers=h).text
    assert served != before and "#0f766e" in served.lower()


def test_diff_between_two_versions(built):
    client, h, rid, _ = built
    client.post(f"/api/runs/{rid}/chat", headers=h, json={"text": "Add a pricing table"})
    d = client.get(f"/api/runs/{rid}/diff", headers=h, params={"from": 1, "to": 2}).json()
    assert d["from"]["v"] == 1 and d["to"]["v"] == 2
    assert d["changed"] is True and d["added"] >= 1
    assert {r["kind"] for r in d["rows"]} & {"add", "ctx"}
    assert client.get(f"/api/runs/{rid}/diff", headers=h, params={"from": 1, "to": 9}).status_code == 404
    assert client.get(f"/api/runs/{rid}/diff", headers=h).status_code == 422   # params required


def test_restore_rolls_back_without_spending_an_edit(built):
    client, h, rid, _ = built
    client.post(f"/api/runs/{rid}/chat", headers=h, json={"text": "Warmer colours please"})
    before = client.get(f"/api/runs/{rid}", headers=h).json()["state"]["revisions"]

    assert client.post(f"/api/runs/{rid}/restore", headers=h, json={"version": 1}).status_code == 202
    run = client.get(f"/api/runs/{rid}", headers=h).json()
    s = run["state"]
    assert s["html_version"] == 3 and s["versions"][-1]["note"] == "Restored v1"
    assert s["revisions"] == before                          # rolling back is not an AI edit
    restored = client.get(f"/api/runs/{rid}/html", headers=h).text
    snapshot = client.get(f"/api/runs/{rid}/versions/1/html", headers=h).text
    # restore re-runs the sanitizer as a guardrail, so compare the page itself, not blank-line noise.
    assert differ.readable(restored) == differ.readable(snapshot)
    assert run["status"] == "awaiting_approval"


def test_restore_guardrails(built):
    client, h, rid, _ = built
    assert client.post(f"/api/runs/{rid}/restore", headers=h, json={"version": 1}).status_code == 409
    assert client.post(f"/api/runs/{rid}/restore", headers=h, json={"version": 42}).status_code == 404


def test_debug_pass_rechecks_and_reports(built):
    client, h, rid, _ = built
    assert client.post(f"/api/runs/{rid}/debug", headers=h).status_code == 202
    run = client.get(f"/api/runs/{rid}", headers=h).json()
    assert run["status"] == "awaiting_approval"
    assert "Debug pass" in run["state"]["chat"][-1]["text"]
    assert run["state"]["html_version"] == 1                 # clean page: nothing to repair


def test_debug_pass_repairs_a_broken_page(client, monkeypatch, built):
    calls = {"n": 0}

    async def flaky(html):
        calls["n"] += 1
        return (BAD_CHECKS if calls["n"] <= 2 else GOOD_CHECKS), {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", flaky)

    r = client.post("/api/auth/register", json={"email": "dbg@example.com", "password": "supersecret1", "name": "D"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "An invoice reminder tool"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]

    calls["n"] = 0
    assert client.post(f"/api/runs/{rid}/debug", headers=h).status_code == 202
    run = client.get(f"/api/runs/{rid}", headers=h).json()
    assert run["state"]["html_version"] > 1                  # the crew rebuilt the page
    assert run["state"]["check_summary"]["errors"] == 0      # and the re-check passed
    assert run["status"] == "awaiting_approval"


def test_workspace_requires_ownership(built):
    client, h, rid, _ = built
    r = client.post("/api/auth/register", json={"email": "nosy@example.com", "password": "supersecret1", "name": "N"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for path in (f"/api/runs/{rid}/files", f"/api/runs/{rid}/versions", f"/api/runs/{rid}/files.zip",
                 f"/api/runs/{rid}/tests", f"/api/runs/{rid}/tests/file"):
        assert client.get(path, headers=other).status_code == 404
    for path, payload in ((f"/api/runs/{rid}/chat", {"text": "change it"}),
                          (f"/api/runs/{rid}/restore", {"version": 1}),
                          (f"/api/runs/{rid}/audit", {}),
                          (f"/api/runs/{rid}/audit/repair", {})):
        assert client.post(path, headers=other, json=payload).status_code == 404
    assert client.post(f"/api/runs/{rid}/debug", headers=other).status_code == 404
    assert client.get(f"/api/runs/{rid}/files").status_code == 401


def test_actions_need_the_approval_gate(built):
    client, h, rid, _ = built
    assert client.post(f"/api/runs/{rid}/approve", headers=h).status_code == 202
    assert client.get(f"/api/runs/{rid}", headers=h).json()["status"] == "deployed"
    assert client.post(f"/api/runs/{rid}/debug", headers=h).status_code == 409
    assert client.post(f"/api/runs/{rid}/chat", headers=h, json={"text": "one more tweak"}).status_code == 409
    assert client.post(f"/api/runs/{rid}/audit", headers=h, json={}).status_code == 409


# --------------------------------------------------------------------------- audits + tests
def test_audit_records_every_report_on_the_live_version(built):
    client, h, rid, run = built
    assert client.post(f"/api/runs/{rid}/audit", headers=h, json={}).status_code == 202
    state = client.get(f"/api/runs/{rid}", headers=h).json()["state"]
    assert sorted(state["audits"]) == sorted(AUDIT_ORDER)
    assert all(r["version"] == state["html_version"] == 1 for r in state["audits"].values())
    assert all(r["findings"] and r["score"] is not None and r["headline"] for r in state["audits"].values())
    assert state["audits"]["tests"]["checks"] >= 1
    assert next(c for c in state["readiness"]["components"] if c["id"] == "audits")["max"] == 20
    assert client.get(f"/api/runs/{rid}", headers=h).json()["status"] == "awaiting_approval"


def test_audit_can_run_a_subset_and_rejects_nonsense(built):
    client, h, rid, _ = built
    assert client.post(f"/api/runs/{rid}/audit", headers=h, json={"agents": ["seo"]}).status_code == 202
    state = client.get(f"/api/runs/{rid}", headers=h).json()["state"]
    assert list(state["audits"]) == ["seo"] and state["tests"] is None
    assert client.get(f"/api/runs/{rid}/tests", headers=h).status_code == 404
    assert client.post(f"/api/runs/{rid}/audit", headers=h, json={"agents": ["seo", "magic"]}).status_code == 422
    assert client.post(f"/api/runs/{rid}/audit", headers=h, json={"agents": []}).status_code == 422


def test_audit_repair_rebuilds_the_page_and_the_fixes_are_visible(built):
    client, h, rid, _ = built
    assert client.post(f"/api/runs/{rid}/audit/repair", headers=h, json={}).status_code == 409
    client.post(f"/api/runs/{rid}/audit", headers=h, json={"agents": ["seo", "accessibility"]})
    before = client.get(f"/api/runs/{rid}/html", headers=h).text
    assert "name=\"description\"" not in before

    assert client.post(f"/api/runs/{rid}/audit/repair", headers=h,
                       json={"agents": ["seo", "accessibility"]}).status_code == 202
    state = client.get(f"/api/runs/{rid}", headers=h).json()["state"]
    served = client.get(f"/api/runs/{rid}/html", headers=h).text
    assert state["html_version"] == 2 and served != before
    assert 'name="description"' in served and "application/ld+json" in served
    assert 'class="skip-link"' in served and 'id="lc-main"' in served
    assert all(r["version"] == 2 for r in state["audits"].values())
    assert state["audits"]["seo"]["errors"] == 0
    assert state["chat"][-1]["text"].startswith("Audit repair:")


def test_generated_tests_are_readable_and_downloadable(built):
    client, h, rid, _ = built
    client.post(f"/api/runs/{rid}/audit", headers=h, json={"agents": ["tests"]})
    body = client.get(f"/api/runs/{rid}/tests", headers=h).json()
    assert body["ran"] is True and body["failed"] == 0 and body["passed"] == len(body["cases"])
    assert "file" not in body                                          # the text only comes from /tests/file
    res = client.get(f"/api/runs/{rid}/tests/file", headers=h)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/x-python")
    assert "attachment" in res.headers["content-disposition"]
    compile(res.text, "test_page.py", "exec")
    assert "LC-RESULT" in res.text


def test_audit_repair_stops_at_the_revision_cap(built):
    client, h, rid, _ = built
    client.post(f"/api/runs/{rid}/audit", headers=h, json={"agents": ["seo"]})
    for _ in range(5):                                    # MAX_REVISIONS is 5 per run
        assert client.post(f"/api/runs/{rid}/chat", headers=h, json={"text": "Warmer colours please"}).status_code == 202
    assert client.get(f"/api/runs/{rid}", headers=h).json()["state"]["revisions"] == 5
    assert client.post(f"/api/runs/{rid}/audit/repair", headers=h, json={"agents": ["seo"]}).status_code == 429
    assert client.post(f"/api/runs/{rid}/audit", headers=h, json={"agents": ["seo"]}).status_code == 202
