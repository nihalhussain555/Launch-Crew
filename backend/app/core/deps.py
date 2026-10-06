"""FastAPI dependencies: settings, db, current user."""
from bson import ObjectId
from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.core.security import decode_token

bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request):
    return request.app.state.db


async def _load_user(request: Request, token: str | None):
    if not token:
        raise HTTPException(401, "Not authenticated")
    user_id = decode_token(token, request.app.state.settings)
    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(401, "Invalid or expired token")
    user = await request.app.state.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(401, "User not found")
    return user


async def get_current_user(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)
):
    return await _load_user(request, creds.credentials if creds else None)


async def get_user_header_or_query(
    request: Request,
    token: str | None = Query(default=None),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    """Used ONLY by the SSE endpoint: EventSource cannot set headers, so it may pass ?token=."""
    return await _load_user(request, creds.credentials if creds else token)
