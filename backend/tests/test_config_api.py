"""Environment manager: what the service is configured with, and the guarantee that values stay server-side.

The two endpoints read the same cached Settings object the app runs on, so what they report is what
the process uses - and for anything secret, they report shape (length + fingerprint), never the value.
"""
import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from app.api import routes_auth, routes_config
from app.config import DEFAULT_JWT_SECRET, Settings
from app.main import app
from app.tools import secret_scan

# conftest.py puts these in os.environ before the app imports its settings.
LIVE_JWT_SECRET = "test-secret"


@pytest.fixture
def client():
    # The auth limiter is a real per-process control (20 calls/min); other test files spend it first.
    routes_auth._auth_limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    routes_auth._auth_limiter._hits.clear()


@pytest.fixture
def auth(client):
    r = client.post("/api/auth/register", json={"email": "env@example.com", "password": "supersecret1", "name": "Env"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def by_field(body):
    return {v["field"]: v for v in body["variables"]}


def test_status_needs_a_signed_in_user(client):
    assert client.get("/api/config/status").status_code == 401
    assert client.get("/api/config/env-example").status_code == 401


def test_status_inventories_every_setting_the_app_reads(client, auth):
    body = client.get("/api/config/status", headers=auth).json()
    assert {v["field"] for v in body["variables"]} == set(Settings.model_fields)   # cannot drift from the code
    assert {g["group"] for g in body["groups"]} == set(routes_config.GROUPS)
    assert body["counts"]["total"] == len(Settings.model_fields)
    assert body["app_env"] == "development"
    assert body["missing_required"] == []

    entries = by_field(body)
    assert entries["mock_llm"]["source"] == "environment"
    assert entries["jwt_secret"]["required"] is True
    assert entries["storage_dir"]["required"] is False
    assert {"str", "int", "float", "bool"} <= {v["type"] for v in body["variables"]}


def test_a_secret_shows_its_shape_and_never_its_value(client, auth):
    body = client.get("/api/config/status", headers=auth)
    assert LIVE_JWT_SECRET not in body.text
    jwt = by_field(body.json())["jwt_secret"]
    assert jwt["secret"] is True and jwt["value"] is None
    assert jwt["length"] == len(LIVE_JWT_SECRET)
    assert re.fullmatch(r"[0-9a-f]{12}", jwt["fingerprint"])
    assert jwt["fingerprint"] == hashlib.sha256(LIVE_JWT_SECRET.encode()).hexdigest()[:12]
    assert jwt["source"] == "environment"


def test_empty_keys_are_reported_as_unset_not_hidden(client, auth):
    entries = by_field(client.get("/api/config/status", headers=auth).json())
    for field in ("groq_api_key", "groq_model", "tavily_api_key", "netlify_auth_token"):
        assert entries[field]["set"] is False, field
        if entries[field]["secret"]:
            assert entries[field]["length"] == 0 and entries[field]["fingerprint"] == ""
        else:
            assert entries[field]["value"] == ""


def test_env_example_is_a_template_not_a_dump(client, auth):
    body = client.get("/api/config/env-example", headers=auth).json()
    assert body["secrets_included"] is False and body["bytes"] > 500
    keys = dict(re.findall(r"^([A-Z0-9_]+)=(.*?)\s+#", body["text"], re.M))
    assert set(keys) == {f.upper() for f in Settings.model_fields}
    assert keys["GROQ_API_KEY"] == "your-value-here"
    assert keys["GROQ_MODEL"] == ""                                   # no default on purpose
    assert LIVE_JWT_SECRET not in body["text"] and body["text"].count("REQUIRED") >= 4
    assert secret_scan.find_secrets(body["text"]) == []               # nothing credential-shaped leaves here


# ------------------------------------------------------------------- advice + masking, unit level
def configured(**kw) -> Settings:
    base = dict(mock_llm=False, groq_api_key="gsk_livekeyaaaaaaaaaaaaaaaaaaaa", groq_model="llama-model",
                mongo_uri="mongodb://real-host:27017", jwt_secret="a-long-random-secret-value-9f3a2b",
                tavily_api_key="tvly-somelongvaluehere123", netlify_auth_token="nfp_somelongtokenvalue123")
    base.update(kw)
    return Settings(**base)


def test_advice_warns_about_each_real_configuration_fault():
    messages = " ".join(a["message"] for a in routes_config._advice(configured()))
    assert messages == ""                                                 # a correct setup says nothing

    placeholder = routes_config._advice(configured(jwt_secret=DEFAULT_JWT_SECRET))
    assert any(a["level"] == "warn" and "placeholder" in a["message"] for a in placeholder)
    production = routes_config._advice(configured(jwt_secret=DEFAULT_JWT_SECRET, app_env="production"))
    assert production[0]["level"] == "error" and "forge sessions" in production[0]["message"]

    mocked = routes_config._advice(configured(mock_llm=True, groq_model=""))
    assert any("MOCK_LLM=true" in a["message"] for a in mocked)
    no_backend = routes_config._advice(configured(groq_api_key="", groq_api_keys=""))
    assert any(a["level"] == "error" and "Groq key" in a["message"] for a in no_backend)
    no_model = routes_config._advice(configured(groq_model=""))
    assert any(a["level"] == "error" and "GROQ_MODEL" in a["message"] for a in no_model)
    mock_db = routes_config._advice(configured(mongo_uri="mock://"))
    assert any("in-memory mock" in a["message"] for a in mock_db)


def test_a_live_secret_never_reaches_an_entry_or_the_template():
    s = configured(groq_api_keys="gsk_livekeybbbbbbbbbbbbbbbbbbbb", tavily_api_key="tvly-livekeycccccccccccccc",
                   netlify_auth_token="nfp_liveddddddddddddddddddddd")
    for field in routes_config.SECRET:
        value = str(getattr(s, field, "") or "")
        entry = routes_config._entry(s, field)
        assert entry["value"] is None and value not in str(entry)
        assert value not in routes_config._template_value(field, entry, s), field
    assert s.groq_key_pool and "gsk_livekeyaaaaaaaaaaaaaaaaaaaa" in s.groq_key_pool


def test_non_secret_settings_show_their_real_value_because_they_are_not_secrets():
    s = configured()
    entries = {e["field"]: e for e in (routes_config._entry(s, f) for f in Settings.model_fields)}
    assert entries["groq_model"]["value"] == "llama-model" and entries["groq_model"]["secret"] is False
    assert entries["mock_llm"]["value"] is False
    assert entries["max_revisions"]["value"] == s.max_revisions
    assert entries["mongo_db"]["source"] in ("environment", ".env file", "default")
