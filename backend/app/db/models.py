"""API/DB models. Mongo documents are plain dicts; these models define the API contract."""
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(default="", max_length=80)


class UserLogin(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str = ""


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ProjectCreate(BaseModel):
    idea: str = Field(min_length=5, max_length=500)
    name: str = Field(default="", max_length=120)


class ProjectOut(BaseModel):
    id: str
    name: str
    idea: str
    created_at: datetime
    runs: list[dict[str, Any]] = []


class RunOut(BaseModel):
    id: str
    project_id: str
    idea: str
    status: str
    error: str | None = None
    tokens_used: int = 0
    steps: int = 0
    state: dict[str, Any] = {}
    share_token: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


# ----------------------------------------------------- workspace records (app/services/workspace_manager.py)
class WorkspaceFileRecord(BaseModel):
    """One file inside a workspace snapshot. Storage keys stay server-side."""
    name: str
    bytes: int = 0
    hash: str = ""


class WorkspaceVersionRecord(BaseModel):
    """The whole file set as it stood before a change - what a workspace restore puts back."""
    w: int
    at: str = ""
    note: str = ""
    html_version: int = 0
    files: list[WorkspaceFileRecord] = []
    changed: list[str] = []


class ChangePlanStep(BaseModel):
    """One named edit: which file, which operation, what it looks for."""
    file: str
    op: str = "replace"
    find: str = ""
    note: str = ""


class ChangePlanSummary(BaseModel):
    changes: list[ChangePlanStep] = []
    files: list[str] = []
    scope: str = "unknown"
    impact_version: int | None = None
    risk_errors: int = 0
    risk_warnings: int = 0


class ChangePlanRecord(BaseModel):
    """A proposed or applied file-level change, kept beside the impact it was measured against."""
    id: str
    at: str = ""
    request: str = ""
    status: str = "proposed"
    version: int = 0
    summary: ChangePlanSummary = ChangePlanSummary()
    impact: dict[str, Any] = {}
    result: dict[str, Any] = {}


def workspace_version_out(entry: dict) -> WorkspaceVersionRecord:
    """A snapshot record without its storage keys."""
    files = [WorkspaceFileRecord.model_validate({k: f.get(k, "") for k in ("name", "bytes", "hash")})
             for f in entry.get("files") or []]
    return WorkspaceVersionRecord(w=entry.get("w", 0), at=entry.get("at", ""), note=entry.get("note", ""),
                                  html_version=entry.get("html_version", 0), files=files,
                                  changed=entry.get("changed") or [])


def change_plan_out(entry: dict) -> ChangePlanRecord:
    return ChangePlanRecord.model_validate(entry)


def _utc(dt):
    """PyMongo returns naive UTC datetimes; tag them so JSON carries a timezone."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(404, "Not found")
    return ObjectId(value)


def user_out(doc: dict) -> UserOut:
    return UserOut(id=str(doc["_id"]), email=doc["email"], name=doc.get("name", ""))


def project_out(doc: dict, runs: list[dict] | None = None) -> ProjectOut:
    return ProjectOut(
        id=str(doc["_id"]), name=doc["name"], idea=doc["idea"], created_at=_utc(doc["created_at"]), runs=runs or []
    )


def run_out(doc: dict) -> RunOut:
    return RunOut(
        id=str(doc["_id"]),
        project_id=doc["project_id"],
        idea=doc["idea"],
        status=doc["status"],
        error=doc.get("error"),
        tokens_used=doc.get("tokens_used", 0),
        steps=doc.get("steps", 0),
        state=doc.get("state", {}),
        share_token=doc.get("share_token"),
        created_at=_utc(doc["created_at"]),
        updated_at=_utc(doc.get("updated_at")),
    )


def run_summary(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "status": doc["status"],
        "created_at": _utc(doc["created_at"]).isoformat(),
        "tokens_used": doc.get("tokens_used", 0),
        "idea": doc.get("idea", ""),
        "score": ((doc.get("state") or {}).get("readiness") or {}).get("total"),
    }
