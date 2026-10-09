"""Environment manager API: what this service is configured with, without ever exposing a value.

The inventory is derived from the `Settings` model the app actually reads, so it cannot drift from
the code. Each variable reports its name, type, whether it is set, where the value came from
(environment / .env file / built-in default) and, for secret fields, only a length and a short
SHA-256 fingerprint - never the value itself. `/env-example` is generated from the same model, so
no file is read and nothing that looks like a credential can leave this endpoint.
"""
from __future__ import annotations

import hashlib
import os
import re

from fastapi import APIRouter, Depends

from app.config import DEFAULT_JWT_SECRET, Settings, get_settings
from app.core.deps import get_current_user
from app.tools import secret_scan

router = APIRouter(prefix="/api/config", tags=["config"])

# field -> (group, required, secret, note) - the operator-facing explanation of each knob.
GROUPS = {
    "General": ("app_env", "allowed_origin", "jwt_secret", "jwt_algorithm", "jwt_expire_minutes"),
    "Database": ("mongo_uri", "mongo_db"),
    "LLM (Groq)": ("mock_llm", "groq_api_key", "groq_api_keys", "groq_model", "groq_fast_model",
                   "groq_vision_model", "llm_max_concurrency", "llm_max_retries", "llm_key_cooldown_s",
                   "llm_request_timeout_s", "llm_backoff_base_s", "llm_backoff_max_s"),
    "Tools": ("tavily_api_key", "netlify_auth_token"),
    "Guardrails": ("max_steps", "max_token_budget", "agent_timeout_s", "max_critic_iterations",
                   "tool_rounds_cap", "runs_per_hour", "max_revisions", "engineer_max_tokens"),
    "Storage": ("storage_backend", "storage_dir"),
}
REQUIRED = {"jwt_secret", "mongo_uri", "mongo_db", "allowed_origin"}
SECRET = {"jwt_secret", "groq_api_key", "groq_api_keys", "tavily_api_key", "netlify_auth_token", "mongo_uri"}
# Placeholder text for the env template. Secret keys never show a real value, only this shape.
EXAMPLES = {"jwt_secret": DEFAULT_JWT_SECRET, "mongo_uri": "mongodb://localhost:27017"}
NOTES = {
    "mock_llm": "true: the crew edits the artefact mechanically from your instructions; false: Groq rewrites it.",
    "groq_api_keys": "Comma-separated pool. Each key is cooled down individually on a 429.",
    "groq_model": "No default on purpose - set the model name your Groq account has access to.",
    "groq_vision_model": "Optional. Enables the Critic's advisory visual review of the mobile screenshot.",
    "tavily_api_key": "Optional. Without it the Researcher uses its built-in market heuristics.",
    "netlify_auth_token": "Optional. Without it deployment is simulated (deploy_mock=true in the run).",
    "mongo_uri": "mock:// is for dev and tests only; it stores nothing between restarts.",
    "storage_backend": "mongo keeps artefacts in the database so they survive a redeploy.",
    "jwt_secret": "Rotating it signs every existing session out.",
    "max_revisions": "Per-run cap on revise/chat/audit-repair calls; each one can rebuild the page.",
    "engineer_max_tokens": "Budget for one page build. Too low truncates the document mid-markup.",
}


def _env_name(field: str) -> str:
    return field.upper()


def _source(field: str, value, default) -> str:
    if _env_name(field) in os.environ:
        return "environment"
    if value != default:
        return ".env file"
    return "default"


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _entry(settings: Settings, field: str) -> dict:
    model_field = Settings.model_fields[field]
    default = model_field.default
    value = getattr(settings, field)
    secret = field in SECRET
    text = "" if isinstance(value, bool) else str(value or "")
    entry = {"name": _env_name(field), "field": field, "type": type(value).__name__,
             "required": field in REQUIRED, "secret": secret, "set": bool(text) or isinstance(value, bool),
             "source": _source(field, value, default),
             "note": NOTES.get(field, "")}
    if secret:
        entry.update({"length": len(text), "fingerprint": _fingerprint(text) if text else "", "value": None})
    else:
        entry["value"] = value if not isinstance(value, bool) else value
    return entry


def _advice(settings: Settings) -> list[dict]:
    """Configuration facts worth telling the operator before they launch a run."""
    out = []
    if settings.mock_llm:
        out.append({"level": "info", "message": "MOCK_LLM=true: the crew runs offline. Quoted-text swaps, tone "
                                                "words, palette and spacing asks are applied mechanically; free-text "
                                                "rewrites need GROQ_API_KEY and GROQ_MODEL."})
    elif not settings.groq_model:
        out.append({"level": "error", "message": "MOCK_LLM=false but GROQ_MODEL is empty - runs will fail at startup."})
    if not settings.groq_key_pool and not settings.mock_llm:
        out.append({"level": "error", "message": "No Groq key is configured while MOCK_LLM=false."})
    if settings.jwt_secret == DEFAULT_JWT_SECRET:
        out.append({"level": "error" if settings.app_env == "production" else "warn",
                    "message": "JWT_SECRET is still the placeholder from the template. Anyone who reads the template "
                               "can forge sessions."})
    if settings.mongo_uri.startswith("mock://"):
        out.append({"level": "warn", "message": "MONGO_URI is the in-memory mock: runs and accounts disappear on "
                                                "restart. Point it at a real database to keep data."})
    if not settings.tavily_api_key:
        out.append({"level": "info", "message": "TAVILY_API_KEY is empty, so the Researcher uses built-in heuristics "
                                                "instead of live web results."})
    if not settings.netlify_auth_token:
        out.append({"level": "info", "message": "NETLIFY_AUTH_TOKEN is empty, so approving a run records a simulated "
                                                "deployment instead of a live site."})
    return out


@router.get("/status")
async def status(user=Depends(get_current_user), settings: Settings = Depends(get_settings)):
    group_of = {f: g for g, fields in GROUPS.items() for f in fields}
    entries = [_entry(settings, f) for f in Settings.model_fields]
    groups = [{"group": g, "variables": [e["name"] for e in entries if group_of.get(e["field"]) == g]}
              for g in GROUPS]
    missing = [e["name"] for e in entries if e["required"] and not e["set"]]
    return {"app_env": settings.app_env, "groups": groups,
            "counts": {"total": len(entries), "from_environment": sum(1 for e in entries if e["source"] == "environment"),
                       "from_dotenv": sum(1 for e in entries if e["source"] == ".env file"),
                       "using_default": sum(1 for e in entries if e["source"] == "default"),
                       "secrets": sum(1 for e in entries if e["secret"])},
            "missing_required": missing,
            "advice": _advice(settings),
            "variables": entries,
            "note": "Secret values stay on the server: this reports presence, length and a SHA-256 fingerprint only."}


@router.get("/env-example")
async def env_example(user=Depends(get_current_user), settings: Settings = Depends(get_settings)):
    """A .env template built from the settings this service reads - required keys first, no live values."""
    lines = ["# Launch Crew backend - environment template",
             "# Copy to .env, then fill in the keys marked REQUIRED.",
             "# Generated from app/config.py by GET /api/config/env-example. Secret values are never included."]
    for group, fields in GROUPS.items():
        lines.append("")
        lines.append(f"# --- {group} " + "-" * max(0, 52 - len(group)))
        for field in fields:
            entry = _entry(settings, field)
            if NOTES.get(field):
                lines.append(f"# {NOTES[field]}")
            mark = "# REQUIRED" if entry["required"] else "# optional"
            lines.append(f"{entry['name']}={_template_value(field, entry, settings)}  {mark}")
    text = "\n".join(lines) + "\n"
    # Belt and braces: never hand back a template that contains something credential-shaped.
    if secret_scan.find_secrets(text):
        text = re.sub(r"(?<==)[^\s#]+(?=\s+#)", "<redacted>", text)
    return {"text": text, "bytes": len(text.encode()), "secrets_included": False}


def _template_value(field: str, entry: dict, settings: Settings) -> str:
    """A safe example for this key: real value for plain settings, placeholder for anything secret."""
    if entry["secret"]:
        return EXAMPLES.get(field, "your-value-here")
    value = getattr(settings, field)
    if isinstance(value, bool):
        return str(value)
    return EXAMPLES.get(field, re.sub(r"mock://", "mongodb://", str(value or "")))
