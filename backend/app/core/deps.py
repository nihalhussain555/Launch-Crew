"""FastAPI dependencies: settings, db, current user."""
from bson import ObjectId
from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.core.security import decode_payload

bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request):
    return request.app.state.db


async def _load_user(request: Request, token: str | None):
    if not token:
        raise HTTPException(401, "Not authenticated")
    claims = decode_payload(token, request.app.state.settings)
    if not claims:
        raise HTTPException(401, "Invalid or expired token")
    user_id = claims.get("sub")
    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(401, "Invalid or expired token")
    user = await request.app.state.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(401, "User not found")
    if int(claims.get("epoch") or 0) != int(user.get("token_epoch") or 0):
        # A password reset bumps the account's session generation, so every token minted before it -
        # including one minted in the same second, which a timestamp check cannot tell apart - stops
        # working. Resetting on a lost laptop really does sign that laptop out.
        raise HTTPException(401, "This session ended when the password changed. Sign in again.")
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
