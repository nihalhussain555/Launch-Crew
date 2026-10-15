"""Password reset: what a link is, where it goes, and what changes when it is used.

The interesting part of a reset is not the form - it is that a link is a bearer credential. These
tests follow one token from issue to redemption and check the properties that make it safe: only its
hash is stored, the newest link retires the previous one, redemption is single use, expiry is real,
and a password change ends the sessions that started before it.
"""
import logging
import re
from datetime import timedelta, timezone
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.core.security import hash_password, hash_token, verify_password
from app.db.mongo import create_client
from app.main import app
from app.orchestrator.runner import now
from app.services import password_reset
from app.tools import browser_checks
from tests.conftest import GOOD_CHECKS, make_settings

RESET = "/api/auth/forgot-password"
APPLY = "/api/auth/reset-password"
LINK = re.compile(r"token=([A-Za-z0-9_-]+)")
PW_LOG = "app.password_reset"


def token_of(link: str) -> str:
    return LINK.search(link).group(1)


def as_utc(value):
    """Documents come back from Mongo as naive UTC while the app clock is aware."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def token_in_log(caplog) -> str:
    for record in caplog.records:
        found = LINK.search(record.getMessage())
        if found:
            return found.group(1)
    raise AssertionError("no reset link was written to the log")


@pytest.fixture
def store():
    """A fresh in-memory database, the way the app builds its own."""
    settings = make_settings()
    return SimpleNamespace(settings=settings, db=create_client(settings)[settings.mongo_db])


@pytest.fixture
async def user(store):
    res = await store.db.users.insert_one({"email": "reset-me@example.com", "name": "A",
                                           "password_hash": hash_password("supersecret1"), "created_at": now()})
    return {"email": "reset-me@example.com", "id": str(res.inserted_id)}


@pytest.fixture
def issued(monkeypatch):
    """Capture the link instead of sending it, so a test can read the token the user would get."""
    got: list[tuple[str, str]] = []

    async def fake_deliver(settings, to, link):
        got.append((to, link))
        return password_reset.CHANNEL_LOG

    monkeypatch.setattr(password_reset, "deliver", fake_deliver)
    return got


# ---------------------------------------------------------------- what a link is
async def test_only_the_hash_of_a_link_is_stored(store, user, issued):
    await password_reset.issue(store.db, store.settings, user["email"])
    doc = await store.db.password_resets.find_one({"user_id": user["id"]})
    raw = token_of(issued[0][1])
    assert doc["token_hash"] == hash_token(raw) != raw and raw not in str(doc)
    assert as_utc(doc["expires_at"]) > now()


async def test_the_newest_link_retires_the_previous_one(store, user, issued):
    await password_reset.issue(store.db, store.settings, user["email"])
    await password_reset.issue(store.db, store.settings, user["email"])
    first, second = (token_of(link) for _, link in issued)
    assert await password_reset.consume(store.db, store.settings, first, "brandnewpass1") == password_reset.OUTCOME_INVALID
    assert await password_reset.consume(store.db, store.settings, second, "brandnewpass1") == password_reset.OUTCOME_OK
    assert await store.db.password_resets.count_documents({}) == 0


async def test_an_address_with_no_account_is_issued_nothing(store, issued):
    assert await password_reset.issue(store.db, store.settings, "nobody@example.com") is None
    assert issued == [] and await store.db.password_resets.count_documents({}) == 0


# ---------------------------------------------------------------- what using one does
async def test_a_link_sets_the_new_password_and_works_once(store, user, issued):
    await password_reset.issue(store.db, store.settings, user["email"])
    token = token_of(issued[0][1])
    assert await password_reset.consume(store.db, store.settings, token, "brandnewpass1") == password_reset.OUTCOME_OK
    assert await password_reset.consume(store.db, store.settings, token, "thirdpassword1") == password_reset.OUTCOME_INVALID
    doc = await store.db.users.find_one({"_id": ObjectId(user["id"])})
    assert verify_password("supersecret1", doc["password_hash"]) is False
    assert verify_password("brandnewpass1", doc["password_hash"]) is True
    assert as_utc(doc["password_changed_at"]) > now() - timedelta(minutes=1)
    assert doc["token_epoch"] == 1          # every session minted before this one is a generation behind


async def test_an_expired_link_is_refused_as_expired(store, user, issued):
    await password_reset.issue(store.db, store.settings, user["email"])
    token = token_of(issued[0][1])
    await store.db.password_resets.update_one({"token_hash": hash_token(token)},
                                              {"$set": {"expires_at": now() - timedelta(seconds=1)}})
    assert await password_reset.consume(store.db, store.settings, token, "brandnewpass1") == password_reset.OUTCOME_EXPIRED


async def test_a_link_that_was_never_issued_is_refused(store, user):
    assert await password_reset.consume(store.db, store.settings, "x" * 43, "brandnewpass1") == password_reset.OUTCOME_INVALID
    assert await password_reset.consume(store.db, store.settings, "   ", "brandnewpass1") == password_reset.OUTCOME_INVALID
    doc = await store.db.users.find_one({"_id": ObjectId(user["id"])})
    assert verify_password("supersecret1", doc["password_hash"]) is True   # untouched
    assert "password_changed_at" not in doc and "token_epoch" not in doc


# ---------------------------------------------------------------- where the link goes
async def test_without_a_mail_server_the_link_is_written_to_the_log(store, user, caplog):
    with caplog.at_level(logging.WARNING, logger=PW_LOG):
        channel = await password_reset.issue(store.db, store.settings, user["email"])
    assert channel == password_reset.CHANNEL_LOG
    assert "SMTP is not configured" in caplog.text and "token=" in caplog.text


async def test_a_mail_server_receives_the_link_and_the_log_stays_clean(store, user, monkeypatch, caplog):
    sent = []
    monkeypatch.setattr(password_reset, "_send_email", lambda settings, to, link: sent.append((to, link)))
    settings = make_settings(smtp_host="smtp.example.com", smtp_from="crew@example.com")
    with caplog.at_level(logging.WARNING, logger=PW_LOG):
        channel = await password_reset.issue(store.db, settings, user["email"])
    assert channel == password_reset.CHANNEL_EMAIL and sent[0][0] == user["email"]
    assert settings.reset_link(token_of(sent[0][1])) == sent[0][1]
    assert "token=" not in caplog.text


async def test_the_mail_message_explains_the_link(store, user):
    settings = make_settings(smtp_host="smtp.example.com", smtp_from="crew@example.com")
    body = password_reset._email_body(settings, "http://localhost:5173/reset-password?token=abc")
    assert "abc" in body and str(settings.password_reset_ttl_minutes) in body and "works once" in body


async def test_a_mail_server_that_is_down_falls_back_to_the_log(store, user, monkeypatch, caplog):
    def broken(settings, to, link):
        raise OSError("smtp refused the connection")

    monkeypatch.setattr(password_reset, "_send_email", broken)
    settings = make_settings(smtp_host="smtp.example.com", smtp_from="crew@example.com")
    with caplog.at_level(logging.WARNING, logger=PW_LOG):
        channel = await password_reset.issue(store.db, settings, user["email"])
    assert channel == password_reset.CHANNEL_LOG          # the answer reports what happened, not the plan
    assert "SMTP send failed" in caplog.text and "token=" in caplog.text


# ---------------------------------------------------------------- the HTTP contract
@pytest.fixture
def client(monkeypatch):
    async def fake(html):
        return GOOD_CHECKS, {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    with TestClient(app) as c:
        yield c


def test_the_answer_cannot_be_used_to_ask_who_has_an_account(client, caplog):
    email = "contract@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "supersecret1", "name": "A"})
    with caplog.at_level(logging.WARNING, logger=PW_LOG):
        known = client.post(RESET, json={"email": email})
        caplog.clear()
        unknown = client.post(RESET, json={"email": "nobody-at-all@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()                 # no user directory behind the form
    assert "nobody-at-all" not in caplog.text


def test_a_link_issued_over_http_changes_the_password_and_ends_older_sessions(client, caplog):
    email = "sessions@example.com"
    registered = client.post("/api/auth/register", json={"email": email, "password": "supersecret1", "name": "A"})
    token = registered.json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    with caplog.at_level(logging.WARNING, logger=PW_LOG):
        r = client.post(RESET, json={"email": email})
        assert r.status_code == 202 and r.json()["channel"] == "server_log"
        link = token_in_log(caplog)
    assert client.post(APPLY, json={"token": link, "password": "brandnewpass1"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": "supersecret1"}).status_code == 401

    # The session that existed when the password changed is over, even though it was minted seconds
    # ago: the token carries the account's session generation, and a reset bumps it.
    gone = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert gone.status_code == 401 and "password changed" in gone.json()["detail"]
    fresh = client.post("/api/auth/login", json={"email": email, "password": "brandnewpass1"}).json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {fresh}"}).status_code == 200


def test_the_reset_endpoints_answer_a_stranger_like_a_dead_link(client):
    assert client.post(RESET, json={"email": "whoever@example.com"}).status_code == 202
    assert client.post(APPLY, json={"token": "x" * 43, "password": "brandnewpass1"}).status_code == 400
    assert "not valid" in client.post(APPLY, json={"token": "x" * 43, "password": "brandnewpass1"}).json()["detail"]


def test_a_new_password_is_held_to_the_same_rule_as_a_first_one(client):
    assert client.post(APPLY, json={"token": "x" * 43, "password": "short"}).status_code == 422
