"""Password hashing (bcrypt) and JWT helpers."""
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


def create_access_token(user_id: str, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings) -> str | None:
    """Returns the user id, or None if the token is invalid/expired."""
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return data.get("sub")
    except jwt.PyJWTError:
        return None
