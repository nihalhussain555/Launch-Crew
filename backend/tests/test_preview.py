"""Preview lifecycle: honest support verdicts, expiring sandboxed links, and no path a caller can choose."""
import pytest
from fastapi.testclient import TestClient

from app.api.routes_preview import GONE
from app.main import app
from app.services import preview
from app.tools import browser_checks
from tests.conftest import GOOD_CHECKS

NEEDS_BUILD = {"supported": False, "kind": "needs-build", "entry": None, "blocked": ["package.json"],
               "reason": "These files must be compiled or served before they render (package.json)."}


@pytest.fixture
def client(monkeypatch):
    async def fake(html):
        return GOOD_CHECKS, {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    with TestClient(app) as c:
        yield c


def make_run(client, email):
    r = client.post("/api/auth/register", json={"email": email, "password": "supersecret1"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A habit tracker for night-shift workers"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    return h, rid


def start(client, h, rid):
    res = client.post(f"/api/runs/{rid}/preview", headers=h)
    assert res.status_code == 201, res.text
    return res.json()["ticket"]


# ------------------------------------------------------------------ can this environment run it?

def test_a_static_page_is_previewable():
    verdict = preview.support([{"name": "index.html"}, {"name": "styles.css"}, {"name": "app.js"},
                               {"name": "README.md"}])
    assert verdict["supported"] and verdict["kind"] == "static-page" and verdict["entry"] == "index.html"
    assert verdict["blocked"] == []


def test_a_build_step_is_named_rather_than_simulated():
    verdict = preview.support([{"name": "index.html"}, {"name": "package.json"}, {"name": "src/App.jsx"}])
    assert not verdict["supported"] and verdict["kind"] == "needs-build"
    assert "package.json" in verdict["blocked"] and "src/app.jsx" in verdict["blocked"]
    assert "compiled" in verdict["reason"]
    assert verdict["entry"] is None       # no entry to load, so no partial page can be shown either


@pytest.mark.parametrize("files,kind", [
    ([], "empty"),
    ([{"name": "styles.css"}, {"name": "app.js"}], "no-page"),
    ([{"name": "index.html"}, {"name": "server.py"}], "needs-build"),
    ([{"name": "Index.HTML"}, {"name": "logo.svg"}], "static-page"),
])
def test_support_covers_the_cases_the_ui_has_to_explain(files, kind):
    assert preview.support(files)["kind"] == kind


# ------------------------------------------------------------------ status

def test_status_reports_the_page_and_the_checks_that_actually_ran(client):
    h, rid = make_run(client, "pv-status@example.com")
    d = client.get(f"/api/runs/{rid}/preview", headers=h).json()
    assert d["preview"]["supported"] is True and d["preview"]["kind"] == "static-page"
    assert d["page"]["name"] == "index.html" and d["page"]["bytes"] > 0
    assert d["page"]["version"] == d["version"] == 1
    assert d["build"]["checks"] == len(GOOD_CHECKS) and d["build"]["errors"] == 0
    assert d["build"]["readiness"] > 0 and d["ticket"] is None and d["tickets"]["active"] == 0
    assert d["runtime_channel"] == "postMessage"


def test_a_read_of_the_status_never_reveals_a_live_link(client):
    h, rid = make_run(client, "pv-noecho@example.com")
    ticket = start(client, h, rid)
    after = client.get(f"/api/runs/{rid}/preview", headers=h).json()
    assert after["ticket"] is None                       # the plaintext token is only ever in POST's answer
    assert after["tickets"]["active"] == 1
    assert ticket["token"] not in str(after)             # and it is not hiding in any other field


def test_another_users_run_has_no_preview_at_all(client):
    h, rid = make_run(client, "pv-owner@example.com")
    other = client.post("/api/auth/register", json={"email": "pv-thief@example.com", "password": "supersecret1"})
    hh = {"Authorization": f"Bearer {other.json()['access_token']}"}
    for method in ("get", "post", "delete"):
        assert getattr(client, method)(f"/api/runs/{rid}/preview", headers=hh).status_code == 404
    assert client.get(f"/api/runs/{rid}/preview").status_code == 401     # and no route is anonymous


# ------------------------------------------------------------------ start, look, stop

def test_a_ticket_serves_the_published_page_sandboxed(client):
    h, rid = make_run(client, "pv-look@example.com")
    ticket = start(client, h, rid)
    assert ticket["path"] == f"/api/preview/{ticket['token']}" and ticket["version"] == 1
    assert ticket["expires_in"] == client.app.state.settings.preview_ttl_seconds

    r = client.get(ticket["path"])                        # no Authorization header: the link is the credential
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == "sandbox allow-scripts"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert "noindex" in r.headers["x-robots-tag"]
    assert r.headers["content-type"].startswith("text/html")
    assert r.text == client.get(f"/api/runs/{rid}/html", headers=h).text   # byte for byte what was published


def test_stopping_revokes_every_link_immediately(client):
    h, rid = make_run(client, "pv-stop@example.com")
    first = start(client, h, rid)
    second = start(client, h, rid)
    assert client.delete(f"/api/runs/{rid}/preview", headers=h).json()["revoked"] == 2
    assert client.get(first["path"]).status_code == 404
    assert client.get(second["path"]).status_code == 404
    assert client.get(f"/api/runs/{rid}/preview", headers=h).json()["tickets"]["active"] == 0


def test_an_expired_link_is_gone_rather_than_renewed(client):
    client.app.state.settings.preview_ttl_seconds = 0
    try:
        h, rid = make_run(client, "pv-expired@example.com")
        ticket = start(client, h, rid)
        gone = client.get(ticket["path"])
        assert gone.status_code == 404 and "expired" in gone.json()["detail"]
        assert client.get(f"/api/runs/{rid}/preview", headers=h).json()["tickets"]["active"] == 0
    finally:
        client.app.state.settings.preview_ttl_seconds = 300


def test_the_link_count_per_run_is_capped(client):
    client.app.state.settings.preview_tickets_per_run = 1
    try:
        h, rid = make_run(client, "pv-cap@example.com")
        start(client, h, rid)
        r = client.post(f"/api/runs/{rid}/preview", headers=h)
        assert r.status_code == 429 and "1 live preview link" in r.json()["detail"]
        assert client.get(f"/api/runs/{rid}/preview", headers=h).json()["tickets"]["active"] == 1
    finally:
        client.app.state.settings.preview_tickets_per_run = 5


# ------------------------------------------------------------------ guesses, traversal, broken storage

@pytest.mark.parametrize("guess", ["", "short", "a" * 64, "not-a-real-token",
                                   "..%2F..%2F..%2Fetc%2Fpasswd", "../../secrets", "*"])
def test_a_fabricated_or_travelling_token_gets_nothing(client, guess):
    h, rid = make_run(client, "pv-guess@example.com")
    token = start(client, h, rid)["token"]
    assert client.get(f"/api/preview/{token}").status_code == 200      # the real one still works
    r = client.get(f"/api/preview/{guess}")
    assert r.status_code == 404
    assert "<!doctype html" not in r.text.lower()                     # no page, whichever layer refused
    assert r.json()["detail"] in (GONE, "Not Found")                  # ticket lookup or router, both say no
    assert rid not in r.text and token not in r.text


def test_a_token_for_one_run_never_opens_another(client):
    h1, rid1 = make_run(client, "pv-pair-a@example.com")
    h2, rid2 = make_run(client, "pv-pair-b@example.com")
    ta = start(client, h1, rid1)["token"]
    assert client.get(f"/api/preview/{ta}").status_code == 200
    assert rid2 not in client.get(f"/api/preview/{ta}").text
    assert ta not in start(client, h2, rid2)["token"]


def test_no_link_is_handed_out_for_a_page_storage_cannot_read(client, monkeypatch):
    h, rid = make_run(client, "pv-lost@example.com")
    storage = client.app.state.storage

    async def boom(key):
        raise FileNotFoundError(f"no blob for {key}")
    monkeypatch.setattr(storage, "load", boom)
    r = client.post(f"/api/runs/{rid}/preview", headers=h)
    assert r.status_code == 409 and "could not be read" in r.json()["detail"]
    assert client.get(f"/api/runs/{rid}/preview", headers=h).json()["tickets"]["active"] == 0


def test_an_unsupported_file_set_is_refused_instead_of_previewed(client, monkeypatch):
    monkeypatch.setattr(preview, "support", lambda files: dict(NEEDS_BUILD))
    h, rid = make_run(client, "pv-build@example.com")
    r = client.post(f"/api/runs/{rid}/preview", headers=h)
    assert r.status_code == 415 and "compiled" in r.json()["detail"]
    d = client.get(f"/api/runs/{rid}/preview", headers=h).json()
    assert d["preview"]["supported"] is False and d["preview"]["blocked"] == ["package.json"]
    assert d["tickets"]["active"] == 0                                  # nothing was opened, nothing to revoke
