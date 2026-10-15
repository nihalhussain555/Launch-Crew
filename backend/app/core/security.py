"""Password hashing (bcrypt) and JWT helpers."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import Settings


def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; the API schema caps passwords at 72 chars.
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: str, settings: Settings, epoch: int = 0) -> str:
    """A session token. `epoch` is the account's session generation, which a password reset bumps:
    every token carries the number it was minted under, so a reset can end sessions precisely instead
    of comparing them to a timestamp that JWT only records to the whole second."""
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "iat": now, "epoch": int(epoch),
               "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_payload(token: str, settings: Settings) -> dict | None:
    """The whole claim set, or None if the token is invalid/expired. Callers read `sub` from it, and
    the session generation too, since that has to be checked against the account rather than the token."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None


def new_reset_token() -> str:
    """The plaintext half of a password-reset token. Only its hash is ever stored."""
    return secrets.token_urlsafe(32)


def hash_token(value: str) -> str:
    """A one-way form of a token we have to look up by value. Unlike a password, this input is
    256 bits of CSPRNG output, so a fast hash is enough and the lookup stays an index hit."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
