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


def make_run(client, email):
    r = client.post("/api/auth/register", json={"email": email, "password": "supersecret1"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A habit tracker for night-shift workers"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    return h, pid, rid


def test_share_feedback_apply_revoke_flow(client):
    h, _, rid = make_run(client, "share@example.com")
    run = client.get(f"/api/runs/{rid}", headers=h).json()
    assert run["status"] == "awaiting_approval" and run["state"]["readiness"]["total"] > 0 and run["state"]["panel"]

    token = client.post(f"/api/runs/{rid}/share", headers=h).json()["token"]
    assert client.get(f"/api/runs/{rid}", headers=h).json()["share_token"] == token

    # public endpoints need no auth and leak no owner data
    info = client.get(f"/api/public/{token}").json()
    assert info["headline"] and "email" not in str(info)
    assert "<html" in client.get(f"/api/public/{token}/html").text.lower()
    assert client.get("/api/public/not-a-real-token").status_code == 404

    assert client.post(f"/api/public/{token}/feedback", json={"message": "x"}).status_code == 422
    ok = client.post(f"/api/public/{token}/feedback", json={"name": "Sam", "message": "Headline is unclear", "rating": 3})
    assert ok.status_code == 201

    items = client.get(f"/api/runs/{rid}/feedback", headers=h).json()
    assert len(items) == 1 and items[0]["applied"] is False and items[0]["rating"] == 3

    assert client.post(f"/api/runs/{rid}/feedback/apply", json={"target": "page"}, headers=h).status_code == 202
    after = client.get(f"/api/runs/{rid}", headers=h).json()
    assert after["status"] == "awaiting_approval" and after["state"]["revisions"] == 1
    assert client.get(f"/api/runs/{rid}/feedback", headers=h).json()[0]["applied"] is True
    assert client.post(f"/api/runs/{rid}/feedback/apply", json={}, headers=h).status_code == 404   # nothing pending

    assert client.delete(f"/api/runs/{rid}/share", headers=h).status_code == 204
    assert client.get(f"/api/public/{token}").status_code == 404


def test_cannot_share_someone_elses_run(client):
    _, _, rid = make_run(client, "owner2@example.com")
    r = client.post("/api/auth/register", json={"email": "intruder@example.com", "password": "supersecret1"})
    h2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.post(f"/api/runs/{rid}/share", headers=h2).status_code == 404
    assert client.get(f"/api/runs/{rid}/feedback", headers=h2).status_code == 404


def test_stats_and_project_delete(client):
    h, pid, rid = make_run(client, "stats@example.com")
    st = client.get("/api/stats", headers=h).json()
    assert st["projects"] == 1 and st["runs"] == 1 and st["avg_readiness"] and st["recent_runs"][0]["id"] == rid
    detail = client.get(f"/api/projects/{pid}", headers=h).json()
    assert detail["runs"][0]["score"] and detail["runs"][0]["idea"]
    assert client.delete(f"/api/projects/{pid}", headers=h).status_code == 204
    assert client.get(f"/api/runs/{rid}", headers=h).status_code == 404
    assert client.get(f"/api/projects/{pid}", headers=h).status_code == 404
    assert client.get("/api/stats", headers=h).json()["projects"] == 0