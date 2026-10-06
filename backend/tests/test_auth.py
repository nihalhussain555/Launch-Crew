import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools import browser_checks
from tests.conftest import GOOD_CHECKS


@pytest.fixture
def client(monkeypatch):
    async def fake(html):
        return GOOD_CHECKS, {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    with TestClient(app) as c:
        yield c


def register(client, email="a@example.com", pw="supersecret1"):
    r = client.post("/api/auth/register", json={"email": email, "password": pw, "name": "A"})
    return r, {"Authorization": f"Bearer {r.json().get('access_token', '')}"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_login_me(client):
    r, h = register(client)
    assert r.status_code == 201
    assert client.post("/api/auth/login", json={"email": "A@example.com", "password": "supersecret1"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrongpass"}).status_code == 401
    assert client.get("/api/auth/me", headers=h).json()["email"] == "a@example.com"


def test_duplicate_and_validation(client):
    register(client, "dup@example.com")
    assert register(client, "dup@example.com")[0].status_code == 409
    assert client.post("/api/auth/register", json={"email": "bad", "password": "supersecret1"}).status_code == 422
    assert client.post("/api/auth/register", json={"email": "s@example.com", "password": "short"}).status_code == 422


def test_protected_routes_require_auth(client):
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_full_flow_with_approval_gate_and_isolation(client):
    _, h = register(client, "flow@example.com")
    pid = client.post("/api/projects", json={"idea": "A habit tracker for night-shift workers"}, headers=h).json()["id"]
    run = client.post(f"/api/projects/{pid}/runs", headers=h).json()
    rid = run["id"]

    got = client.get(f"/api/runs/{rid}", headers=h).json()       # background task finished (mock pipeline)
    assert got["status"] == "awaiting_approval" and got["state"]["html_key"]
    assert "<html" in client.get(f"/api/runs/{rid}/html", headers=h).text.lower()
    assert client.get(f"/api/runs/{rid}/screenshots/mobile", headers=h).status_code == 200

    # SSE replay (token via query param) ends at the last event of the current phase
    assert client.get(f"/api/runs/{rid}/stream").status_code == 401
    # other users can't see it
    _, h2 = register(client, "other@example.com")
    assert client.get(f"/api/runs/{rid}", headers=h2).status_code == 404
    assert client.post(f"/api/runs/{rid}/approve", headers=h2).status_code in (404, 409)

    assert client.post(f"/api/runs/{rid}/approve", headers=h).status_code == 202
    done = client.get(f"/api/runs/{rid}", headers=h).json()
    assert done["status"] == "deployed" and done["state"]["deploy_url"] and len(done["state"]["social_posts"]) == 3
    assert client.post(f"/api/runs/{rid}/approve", headers=h).status_code == 409      # no double deploy

    token = h["Authorization"].split()[1]
    body = client.get(f"/api/runs/{rid}/stream?token={token}").text
    assert "event: awaiting_approval" in body and "event: deployed" in body


def test_run_creation_rate_limited(client, monkeypatch):
    from app.main import app as a
    _, h = register(client, "rl@example.com")
    pid = client.post("/api/projects", json={"idea": "Some idea here"}, headers=h).json()["id"]
    a.state.settings.runs_per_hour = 2
    codes = [client.post(f"/api/projects/{pid}/runs", headers=h).status_code for _ in range(3)]
    assert codes == [202, 202, 429]
