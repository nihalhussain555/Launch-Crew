from fastapi import APIRouter, Depends, HTTPException, Request
from pymongo.errors import DuplicateKeyError

from app.core.deps import get_current_user, get_db, get_settings_dep
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import TokenOut, UserCreate, UserLogin, UserOut, user_out
from app.orchestrator.runner import now

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
    return TokenOut(access_token=create_access_token(str(user["_id"]), settings), user=user_out(user))


@router.get("/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return user_out(user)
