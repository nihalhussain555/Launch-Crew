"""Password reset: single-use tokens, mailed when the server can mail, logged when it cannot.

A reset token is 256 bits of CSPRNG output. Only its sha256 is stored, so a database dump gives an
attacker nothing they can post straight to the reset endpoint. Each issue replaces the account's
previous live token, so the newest link is the only one that works, and `find_one_and_delete` makes
redemption single use even when two requests arrive at once.

Delivery is the part this app cannot invent. With SMTP_HOST set the link is mailed; without it the
link goes to the server log and the caller is told that is where it went. Nothing here ever claims an
email was sent when it was not, and nothing here ever returns the link over the API - whoever asked
for the reset is the one person who must not receive it by HTTP.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import timedelta, timezone
from email.message import EmailMessage

from app.config import Settings
from app.core.security import hash_password, hash_token, new_reset_token
from app.db.models import oid
from app.orchestrator.runner import now

log = logging.getLogger("app.password_reset")

# "email" mailed to the address, "server_log" printed for whoever runs this process.
CHANNEL_EMAIL = "email"
CHANNEL_LOG = "server_log"

# What redeeming a token ended up doing.
OUTCOME_OK = "ok"
OUTCOME_INVALID = "invalid"
OUTCOME_EXPIRED = "expired"


def _as_utc(value):
    """Mongo hands back naive UTC while the app clock is aware: normalise before comparing the two."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _email_body(settings: Settings, link: str) -> str:
    mins = settings.password_reset_ttl_minutes
    return (
        "Someone asked to reset the password on your Launch Crew account.\n\n"
        f"Open this link to choose a new password:\n\n{link}\n\n"
        f"It works once and expires in {mins} minutes.\n"
        "If you did not ask for this, ignore the email - your password stays as it is.\n"
    )


def _send_email(settings: Settings, to: str, link: str) -> None:
    """Blocking SMTP call. Run through asyncio.to_thread, never on the event loop."""
    msg = EmailMessage()
    msg["Subject"] = "Reset your Launch Crew password"
    msg["From"] = settings.smtp_from.strip() or settings.smtp_user.strip()
    msg["To"] = to
    msg.set_content(_email_body(settings, link))

    with smtplib.SMTP(settings.smtp_host.strip(), settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user.strip():
            smtp.login(settings.smtp_user.strip(), settings.smtp_password)
        smtp.send_message(msg)


def _log_link(where: str, to: str, link: str) -> None:
    log.warning("Password reset link for %s written to the server log (%s): %s", to, where, link)


async def deliver(settings: Settings, to: str, link: str) -> str:
    """Send the link, and report the channel it actually reached. An SMTP failure falls back to the
    log rather than dropping the reset on the floor, and the caller reports what was used."""
    if settings.email_configured:
        try:
            await asyncio.to_thread(_send_email, settings, to, link)
            log.info("Password reset link mailed to %s", to)
            return CHANNEL_EMAIL
        except Exception as exc:  # noqa: BLE001 - a mail server being down must not lose the request
            log.exception("SMTP send to %s failed, falling back to the server log: %s", to, exc)
            _log_link("SMTP send failed", to, link)
            return CHANNEL_LOG
    _log_link("SMTP is not configured", to, link)
    return CHANNEL_LOG


async def issue(db, settings: Settings, email: str) -> str | None:
    """Create and deliver a link for `email`, answering with the channel it reached - or None when no
    account matched. The caller must not turn that None into a different-looking answer, because a
    forgot-password form that says "no such account" is a directory of who uses the product."""
    user = await db.users.find_one({"email": email.lower().strip()})
    if not user:
        return None
    token = new_reset_token()
    await db.password_resets.delete_many({"user_id": str(user["_id"])})   # one live link per account
    await db.password_resets.insert_one({
        "user_id": str(user["_id"]),
        "token_hash": hash_token(token),
        "created_at": now(),
        "expires_at": now() + timedelta(minutes=settings.password_reset_ttl_minutes),
    })
    return await deliver(settings, user["email"], settings.reset_link(token))


async def consume(db, settings: Settings, token: str, password: str) -> str:
    """Redeem a token and set the new password. Returns OUTCOME_OK, OUTCOME_INVALID or OUTCOME_EXPIRED -
    the last two say the same thing to the client, so guessing is not rewarded with detail."""
    token = (token or "").strip()
    if not token:
        return OUTCOME_INVALID
    doc = await db.password_resets.find_one_and_delete({"token_hash": hash_token(token)})
    if not doc:
        return OUTCOME_INVALID
    if _as_utc(doc["expires_at"]) < now():
        return OUTCOME_EXPIRED
    uid = oid(doc["user_id"])
    await db.users.update_one({"_id": uid}, {"$set": {
        "password_hash": hash_password(password),
        # Kept as the record of when the change happened. What actually ends the old sessions is the
        # bumped generation below, because a JWT timestamp cannot separate two events in one second.
        "password_changed_at": now(),
    }, "$inc": {"token_epoch": 1}})
    log.info("Password reset for user %s", uid)
    return OUTCOME_OK
