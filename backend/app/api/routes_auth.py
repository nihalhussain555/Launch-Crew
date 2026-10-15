from fastapi import APIRouter, Depends, HTTPException, Request
from pymongo.errors import DuplicateKeyError

from app.core.deps import get_current_user, get_db, get_settings_dep
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import ForgotIn, ForgotOut, ResetIn, TokenOut, UserCreate, UserLogin, UserOut, user_out
from app.orchestrator.runner import now
from app.services import password_reset

router = APIRouter(prefix="/api/auth", tags=["auth"])
_auth_limiter = SlidingWindowLimiter(limit=20, window_s=60)


def _ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for", "").split(",")[0].strip()) or (request.client.host if request.client else "?")


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(body: UserCreate, request: Request, db=Depends(get_db), settings=Depends(get_settings_dep)):
    _auth_limiter.check(_ip(request))
    doc = {"email": body.email.lower().strip(), "name": body.name.strip(), "password_hash": hash_password(body.password), "created_at": now()}
    try:
        res = await db.users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "An account with this email already exists")
    doc["_id"] = res.inserted_id
    return TokenOut(access_token=create_access_token(str(res.inserted_id), settings), user=user_out(doc))


@router.post("/login", response_model=TokenOut)
async def login(body: UserLogin, request: Request, db=Depends(get_db), settings=Depends(get_settings_dep)):
    _auth_limiter.check(_ip(request))
    user = await db.users.find_one({"email": body.email.lower().strip()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Incorrect email or password")
    return TokenOut(access_token=create_access_token(str(user["_id"]), settings, user.get("token_epoch", 0)),
                    user=user_out(user))


@router.post("/forgot-password", response_model=ForgotOut, status_code=202)
async def forgot_password(body: ForgotIn, request: Request, db=Depends(get_db),
                          settings=Depends(get_settings_dep)):
    """Ask for a reset link.

    An address with no account gets the same status, the same shape and the same message as one with
    an account, because a form that answers "no such user" is a directory of who uses this product.
    `channel` is how this server delivers links in general, so naming it leaks nothing either.
    """
    _auth_limiter.check(_ip(request))
    used = await password_reset.issue(db, settings, body.email)
    channel = used or ("email" if settings.email_configured else password_reset.CHANNEL_LOG)
    if channel == password_reset.CHANNEL_EMAIL:
        message = (f"If that address has an account, a link to choose a new password is on its way. "
                   f"It works once and expires in {settings.password_reset_ttl_minutes} minutes.")
    else:
        message = ("This server has no email service configured, so a reset link is written to its own log "
                   "instead of an inbox. If that address has an account, its link is in the log of the "
                   "process running this app - ask whoever operates it.")
    return ForgotOut(message=message, channel=channel)


@router.post("/reset-password", status_code=200)
async def reset_password(body: ResetIn, request: Request, db=Depends(get_db), settings=Depends(get_settings_dep)):
    """Redeem a link and set the new password. Sessions minted before this moment stop working, so a
    reset really signs the old device out - see app/core/deps.py."""
    _auth_limiter.check(_ip(request))
    outcome = await password_reset.consume(db, settings, body.token, body.password)
    if outcome == password_reset.OUTCOME_EXPIRED:
        raise HTTPException(400, "That reset link has expired. Ask for a new one.")
    if outcome != password_reset.OUTCOME_OK:
        raise HTTPException(400, "That reset link is not valid. Ask for a new one.")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return user_out(user)
