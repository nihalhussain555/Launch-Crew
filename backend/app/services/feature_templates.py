"""The backend Launch Crew writes when a user asks for a real feature.

Nothing here is a mock. Every file this module produces is meant to be downloaded and started: the
server is a normal FastAPI app, the database is a normal SQLite file created from `schema.sql`, and the
password, session, validation, rate-limit and upload rules are the ones the code actually enforces.
What Launch Crew cannot do is run it for you - the published artefact is a static page - so every
capability this file generates is reported as `scaffold`, and `SETUP.md` says exactly how to start it.

Two facts about the published page shape the split:

  * `app/tools/sanitizer.py` removes any inline script that calls `fetch` or touches web storage, and
    injects a CSP that allows no network at all. So the page carries markup, and the code that talks to
    this server is served by the server itself (`/feature_client.js`).
  * a page opened without the server is not broken: its panels say they are waiting for it, which is
    the truth, instead of pretending a form was submitted.

`compose()` is deterministic: the same set of capability keys produces the same files, so a plan, a
diff and a test can all be relied on offline.
"""
from __future__ import annotations

import json
import re

from app.agents import capabilities as caps
from app.services import feature_blocks as blocks

FEATURE_CLIENT = "feature_client.js"
FEATURES_DOC = "FEATURES.md"
PAGE_SECTIONS = "feature_sections.html"
REQUIREMENTS = "requirements.txt"

# The last element of the block `page_markup` writes, and the only thing that tells a later build where
# that block ends. It has to be an element rather than a comment: the publisher strips comments.
#
# Both locators stop at the `class` attribute on purpose. `app/tools/sanitizer.py` re-serialises the page
# through BeautifulSoup, which writes a tag's attributes in alphabetical order - so the published form of
# the opening tag is `<section class="lc-features" data-lc-feature-set="…" id="lc-features">`, and a
# locator that expected `id` second would never find the block again on a page that has been published.
BLOCK_HEAD = '<section class="lc-features"'
BLOCK_OPEN_RE = re.compile(r'<section class="lc-features"[^>]*>')
FEATURE_SET_ATTR = re.compile(r'data-lc-feature-set="([^"]*)"')
BLOCK_TAIL = '<div class="lc-features-end" data-lc-features-end="1"></div>'

# Every file a feature build may write. The workspace refuses a name outside the page files plus these.
TEMPLATE_FILES = (caps.SHARED_SERVER, caps.SHARED_DB, caps.SHARED_SCHEMA, caps.SHARED_ENV,
                  caps.SHARED_SETUP, FEATURES_DOC, REQUIREMENTS, FEATURE_CLIENT, PAGE_SECTIONS)

IMPLEMENTED = blocks.IMPLEMENTED

REQUIREMENTS_TXT = """# What the generated server needs. Nothing here is a placeholder package.
fastapi>=0.110
uvicorn[standard]>=0.27
python-multipart>=0.0.9
"""

# --------------------------------------------------------------------------- db.py
DB_MODULE = r'''"""The SQLite access every route in this project uses.

One file, one connection helper, plain SQL from schema.sql. Moving to Postgres later is a connection
string and a port of the placeholders, not a rewrite of the routes.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent


def path() -> Path:
    """Where the database file lives. DATABASE_PATH in the environment wins."""
    raw = os.environ.get("DATABASE_PATH", "").strip()
    return Path(raw) if raw else HERE / "site.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def schema_sql() -> str:
    return (HERE / "schema.sql").read_text(encoding="utf-8")


def init() -> None:
    """Create whatever schema.sql describes. Idempotent, so it runs on every start."""
    with connect() as conn:
        conn.executescript(schema_sql())


def query(sql: str, params=()) -> list[dict]:
    """Rows as plain dicts, so a route can answer with them without a translation layer."""
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params)]


def one(sql: str, params=()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def write(sql: str, params=()) -> int:
    """Insert, and return the new row's id."""
    with connect() as conn:
        cursor = conn.execute(sql, params)
        conn.commit()
        return int(cursor.lastrowid)


def run(sql: str, params=()) -> int:
    """Update or delete, and return how many rows actually changed."""
    with connect() as conn:
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor.rowcount


def count(sql: str, params=()) -> int:
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0
'''

# --------------------------------------------------------------------------- server.py, the part every build shares
SERVER_HEAD = r'''"""@@SITE@@

Written by Launch Crew from the features asked for in plain English. Every rule named in this file is
one the code below enforces: passwords are hashed with PBKDF2-HMAC-SHA256 at 240,000 rounds and never
stored in plain text, sessions are signed HttpOnly SameSite=Lax cookies, cross-site writes are refused,
each write path is rate limited, uploads are re-checked on the server and stored outside any web root,
and an integration with no account behind it answers 501 naming the variable to set instead of
pretending that it worked.

Start it:
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp env_template.txt .env      then edit .env: SESSION_SECRET has no usable default
    python server.py              or: uvicorn server:app --port 8000
    open http://127.0.0.1:8000

Open the site through this server rather than as a file. index.html on its own is the published static
page, and its Content-Security-Policy allows no network, so the feature panels wait. Served from here
the policy is widened to this origin and /feature_client.js - the browser half of those panels - loads.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import db as store
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

HERE = Path(__file__).resolve().parent
SITE_NAME = os.environ.get("SITE_NAME", "").strip() or @@SITE_NAME@@
FEATURES = set(@@FEATURE_TABLE@@)
FEATURE_SUMMARY = @@FEATURE_SUMMARY@@

PBKDF2_ROUNDS = 240_000
MIN_PASSWORD = 10
MAX_BODY = 1_000_000
SESSION_TTL = 60 * 60 * 24 * 7
COOKIE_NAME = "lc_session"
REQUIRED_ENV = @@REQUIRED_ENV@@
WATCHED_ENV = @@ENV_TABLE@@
NO_SECRET = ("Set SESSION_SECRET in .env to a long random string of your own - "
             "python -c 'import secrets; print(secrets.token_hex(32))' - and start the server again. "
             "It will not run with a shared or placeholder value.")
PLACEHOLDER_SECRETS = {"", "change-me", "changeme", "secret", "password", "xxx", "your-secret-here",
                       "replace-me", "replace_with_a_long_random_string"}

EMAIL_RE = re.compile(r"@@EMAIL_RE@@")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# The page arrives with Launch Crew's published lockdown (no network at all), which is right for a
# static share link and wrong here: this server IS the origin the panels are meant to call.
PAGE_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; "
            "frame-ancestors 'none'")
API_CSP = "default-src 'none'; frame-ancestors 'none'"
CSP_TAG = re.compile('<meta\\\\b[^>]*http-equiv=["\\\']?content-security-policy[^>]*>', re.I)
SCRIPT_TAG = '<script src="/feature_client.js"></script>'

_LIMIT_LOCK = threading.Lock()
_LIMIT_SLOTS: dict[str, list[float]] = {}


class Invalid(Exception):
    """Input this server will not accept. Reported as 422 with the field named."""


def load_env_file() -> None:
    """Read the .env beside this file into the environment. A real environment variable always wins."""
    source = HERE / ".env"
    if not source.exists():
        return
    for line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        name, _, value = text.partition("=")
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


load_env_file()


def _boot() -> None:
    secret = os.environ.get("SESSION_SECRET", "").strip()
    if secret in PLACEHOLDER_SECRETS or len(secret) < 16:
        raise RuntimeError(NO_SECRET)
    store.init()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _boot()
    yield


app = FastAPI(title=SITE_NAME, lifespan=lifespan, docs_url=None, redoc_url=None)


# ----------------------------------------------------------------------- responses
def security_headers(extra: dict | None = None) -> dict:
    headers = {"Content-Security-Policy": API_CSP,
               "X-Content-Type-Options": "nosniff",
               "X-Frame-Options": "DENY",
               "Referrer-Policy": "same-origin",
               "Cache-Control": "no-store"}
    headers.update(extra or {})
    return headers


def out(status: int, payload: dict, *, cookie: str = "") -> JSONResponse:
    response = JSONResponse(status_code=status, content=payload)
    for name, value in security_headers().items():
        response.headers[name] = value
    if cookie:
        response.set_cookie(COOKIE_NAME, cookie, httponly=True, samesite="lax",
                            secure=os.environ.get("COOKIE_SECURE", "").strip().lower() in
                            ("1", "true", "yes"), max_age=SESSION_TTL, path="/")
    return response


def ok(payload: dict, *, cookie: str = "") -> JSONResponse:
    return out(200, dict(payload, ok=True), cookie=cookie)


def problem(status: int, message: str, *, detail: str = "") -> JSONResponse:
    payload = {"ok": False, "error": message}
    if detail:
        payload["detail"] = detail
    return out(status, payload)


def missing_env(*names: str) -> JSONResponse:
    """501 with the exact variables to set. Nothing left this server and nothing was recorded."""
    return out(501, {"ok": False, "configured": False, "needs": list(names),
                     "error": "This feature needs an account you have not connected yet. Set "
                              + ", ".join(names) + " in .env and start the server again. "
                              "Nothing was sent anywhere and no record was created."})


# ----------------------------------------------------------------------- guards
def client_ip(request: Request) -> str:
    forward = request.headers.get("x-forwarded-for", "")
    if forward:
        return forward.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limited(key: str, *, limit: int, window: float) -> bool:
    """A fixed window per key, held in memory: one process, and a restart clears it."""
    now = time.monotonic()
    with _LIMIT_LOCK:
        marks = [stamp for stamp in _LIMIT_SLOTS.get(key, []) if now - stamp < window]
        if len(marks) >= limit:
            _LIMIT_SLOTS[key] = marks
            return True
        marks.append(now)
        _LIMIT_SLOTS[key] = marks
        return False


def write_guard(request: Request):
    """Refuse a cross-site form before it reaches the database. Returns a response, or None."""
    origin = (request.headers.get("origin") or "").strip()
    if origin and origin != "null":
        parts = urllib.parse.urlsplit(origin)
        if parts.netloc and parts.netloc != (request.headers.get("host") or ""):
            return problem(403, "That form was submitted from another site (" + origin[:60]
                           + "). This server only accepts its own.")
    if rate_limited("write:" + client_ip(request), limit=60, window=60.0):
        return problem(429, "Too many writes from this address in one minute. Try again shortly.")
    return None


async def body_json(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise Invalid("That request is larger than this server accepts")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise Invalid("Send a JSON body") from None
    if not isinstance(parsed, dict):
        raise Invalid("Send an object, not a list or a bare value")
    return parsed


# ----------------------------------------------------------------------- validation
def text_of(value, field: str, *, max_length: int = 200, required: bool = True) -> str:
    text = "" if value is None else (value if isinstance(value, str) else str(value))
    text = text.strip()
    if required and not text:
        raise Invalid(field + " is required")
    if len(text) > max_length:
        raise Invalid(field + " is longer than " + str(max_length) + " characters")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise Invalid(field + " contains control characters")
    return text


def email_of(value) -> str:
    email = text_of(value, "Email", max_length=254).lower()
    if not EMAIL_RE.match(email):
        raise Invalid("That is not an email address this server can use")
    return email


def password_of(value) -> str:
    raw = "" if value is None else str(value)
    if len(raw) < MIN_PASSWORD:
        raise Invalid("A password needs at least " + str(MIN_PASSWORD) + " characters")
    if len(raw) > 400:
        raise Invalid("That password is too long to be typed twice on purpose")
    if len(set(raw)) < 4:
        raise Invalid("That password is too simple: use a longer one with different kinds of character")
    return raw


def id_of(value, field: str = "Id") -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise Invalid(field + " must be a whole number") from None
    if number < 1:
        raise Invalid(field + " must be a positive whole number")
    return number


def slug_of(value) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return (words or "untitled")[:80]


def choice_of(value, field: str, allowed, default=None):
    text = str(value).strip() if value is not None else ""
    if not text:
        if default is None:
            raise Invalid(field + " must be one of: " + ", ".join(sorted(allowed)))
        return default
    if text not in allowed:
        raise Invalid(field + " must be one of: " + ", ".join(sorted(allowed)))
    return text


def paging(request: Request, sortable, default_sort: str = "created_at", default_size: int = 25):
    """limit/offset plus a sort column taken only from the caller's own allow-list."""
    try:
        limit = int(request.query_params.get("limit", default_size))
    except ValueError:
        raise Invalid("limit must be a whole number") from None
    try:
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        raise Invalid("offset must be a whole number") from None
    sort = request.query_params.get("sort", default_sort)
    if sort not in sortable:
        sort = default_sort
    order = "DESC" if str(request.query_params.get("dir", "desc")).lower().startswith("desc") else "ASC"
    return max(1, min(limit, 200)), max(0, offset), sort, order


def like_of(request: Request, param: str = "q") -> str:
    """A search term made safe for a LIKE: the wildcards belong to the query, not to the visitor."""
    raw = (request.query_params.get(param) or "").strip()
    if not raw:
        return ""
    for danger in ("%", "_", "\\"):
        raw = raw.replace(danger, "")
    return raw[:120]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_ago(seconds: int) -> str:
    return datetime.fromtimestamp(time.time() - seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------- passwords and sessions
def _secret() -> bytes:
    raw = os.environ.get("SESSION_SECRET", "").strip()
    return raw.encode() if len(raw) >= 16 else b""


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ROUNDS, salt.hex(), digest.hex())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt, digest = str(stored).split("$")
        if scheme != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected.hex(), digest)


def _sign(body: str) -> str:
    return hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()


def session_token(user_id: int, role: str) -> str:
    body = "%d.%s.%d" % (int(user_id), role, int(time.time()) + SESSION_TTL)
    return body + "." + _sign(body)


def read_session(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE_NAME, "")
    if not raw:
        return None
    pieces = raw.split(".")
    if len(pieces) != 4:
        return None
    user_id, role, expires, signature = pieces
    if not hmac.compare_digest(_sign(user_id + "." + role + "." + expires), signature):
        return None
    try:
        if int(expires) < int(time.time()):
            return None
        return {"id": int(user_id), "role": role}
    except ValueError:
        return None


USER_COLUMNS = "id, email, display_name, role, bio, created_at, deleted_at"


def session_user(request: Request) -> dict | None:
    """The cookie is a claim; the database is the answer. A closed or changed account stops working."""
    held = read_session(request)
    if not held:
        return None
    row = store.one("SELECT " + USER_COLUMNS + " FROM users WHERE id = ?", (held["id"],))
    if not row or row["deleted_at"] or row["role"] != held["role"]:
        return None
    return row


def require_user(request: Request):
    user = session_user(request)
    if not user:
        return problem(401, "This needs an account. Sign in first.")
    return user


def require_role(request: Request, role: str):
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    if role == "staff" and user["role"] != "staff":
        return problem(403, "This part of the site is for staff accounts.")
    return user


def public_user(row: dict) -> dict:
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"],
            "role": row["role"], "bio": row.get("bio", ""), "created_at": row.get("created_at"),
            "staff": row["role"] == "staff"}


# ----------------------------------------------------------------------- feeds and counts
def record_event(kind: str, user_id, detail: str = "") -> None:
    """A line in the activity feed, when that feature was asked for. It never fails the action."""
    if "activity" not in FEATURES:
        return
    try:
        store.write("INSERT INTO activity (kind, user_id, detail, created_at) VALUES (?, ?, ?, ?)",
                    (kind[:60], user_id, str(detail or "")[:300], now_iso()))
    except Exception:  # noqa: BLE001 - the signup or the order already happened
        pass


def track(name: str, user_id=None, detail: str = "") -> None:
    """A first-party count for the analytics panel. Same rule: a count never breaks the action."""
    if "analytics" not in FEATURES:
        return
    try:
        store.write("INSERT INTO events (name, user_id, detail, created_at) VALUES (?, ?, ?, ?)",
                    (name[:60], user_id, str(detail or "")[:200], now_iso()))
    except Exception:  # noqa: BLE001
        pass


def provider_call(url: str, headers: dict, payload: dict | None = None) -> tuple[int, str]:
    """One call to the service named in the environment. Its answer comes back as it arrived."""
    if not url.startswith("https://"):
        return 0, "Refused: this server only calls https endpoints."
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method="POST" if body else "GET",
                                     headers=dict(headers, accept="application/json"))
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return int(response.status), response.read(200_000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(200_000).decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001 - an unreachable service is a fact to report
        return 0, type(exc).__name__ + ": " + str(exc)[:200]


# ----------------------------------------------------------------------- the page this server serves
def rendered_page() -> bytes | None:
    source = HERE / "index.html"
    if not source.exists():
        return None
    html = source.read_text(encoding="utf-8", errors="ignore")
    tag = '<meta http-equiv="Content-Security-Policy" content="' + PAGE_CSP + '">'
    if CSP_TAG.search(html):
        html = CSP_TAG.sub(tag, html, count=1)
    elif "<head>" in html:
        html = html.replace("<head>", "<head>" + tag, 1)
    if "/feature_client.js" not in html:
        html = html.replace("</body>", SCRIPT_TAG + "</body>", 1)
    return html.encode("utf-8")


@app.get("/")
def home():
    page = rendered_page()
    if page is None:
        return problem(404, "index.html is not in this folder. Keep the page next to server.py - that is "
                            "how the page and its API find each other.")
    return Response(page, media_type="text/html; charset=utf-8",
                    headers=security_headers({"Content-Security-Policy": PAGE_CSP}))


@app.get("/feature_client.js")
def feature_client():
    """The browser half of every panel, served from here because a published page may not hold it."""
    source = HERE / "feature_client.js"
    if not source.exists():
        return Response(b"", media_type="text/javascript; charset=utf-8",
                        headers=security_headers())
    return Response(source.read_bytes(), media_type="text/javascript; charset=utf-8",
                    headers=security_headers())


@app.get("/api/status")
def status():
    """What this build contains and what it is still waiting for. Values are never returned."""
    return ok({"site": SITE_NAME, "features": sorted(FEATURES), "summary": FEATURE_SUMMARY,
               "page_next_to_server": (HERE / "index.html").exists(),
               "database": str(store.path()),
               "environment": [{"name": name, "set": bool(os.environ.get(name, "").strip())}
                               for name in WATCHED_ENV]})
'''

SERVER_TAIL = r'''
@app.exception_handler(Invalid)
async def refused(request: Request, exc: Invalid):
    return problem(422, str(exc) or "That input was not accepted.")


@app.exception_handler(Exception)
async def failed(request: Request, exc: Exception):
    # The stack trace goes to the terminal you started this from, not to the visitor reading the page.
    print("[server] %s while serving %s %s" % (type(exc).__name__, request.method, request.url.path))
    return problem(500, "Something went wrong on this server. Nothing was saved that you did not see "
                        "confirmed.")


if __name__ == "__main__":
    import uvicorn

    if os.environ.get("SESSION_SECRET", "").strip() in PLACEHOLDER_SECRETS:
        raise SystemExit(NO_SECRET)
    uvicorn.run("server:app", host="127.0.0.1", port=8000)
'''

# --------------------------------------------------------------------------- setup and reporting
SETUP_HEAD = """# Setting this site up

Written by Launch Crew for: @@IDEA@@

Features in this build: @@FEATURES@@

These files are the whole application. Nothing in them is a mock, and nothing in them runs until you
start it - Launch Crew publishes a static page, so the server, the database and the mail account are
yours to start. Keep every file in one folder.

| file | what it is |
| --- | --- |
| server.py | the FastAPI application: routes, validation, sessions, rate limits, uploads |
| db.py | the SQLite helpers every route calls |
| schema.sql | the tables, created on first start |
| env_template.txt | the variable names this build reads - copy to .env and fill in |
| feature_client.js | the browser half of the panels, served by server.py |
| feature_sections.html | the markup that was added to index.html, for reference |
| FEATURES.md | exactly what is implemented and what is still waiting |
| requirements.txt | the three packages this needs |
| index.html | the page itself; serve it from this folder and it comes alive |

## Start it

    python -m venv .venv
    source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
    pip install -r requirements.txt
    cp env_template.txt .env
    # edit .env: SESSION_SECRET must be your own long random string
    python -c "import secrets; print(secrets.token_hex(32))"
    python server.py                   # or: uvicorn server:app --port 8000
    # then open http://127.0.0.1:8000 - not the file

The first start creates site.db from schema.sql. The server refuses to boot if SESSION_SECRET is empty,
a placeholder, or shorter than 16 characters; that check is in `_boot` in server.py.

## The rules this server already enforces

* passwords: PBKDF2-HMAC-SHA256, 240,000 rounds, per-password salt, minimum 10 characters
* sessions: signed cookie, HttpOnly, SameSite=Lax, 7 days, invalidated when the role changes or the
  account closes; set COOKIE_SECURE=1 once you are behind https
* writes: origin check plus a 60-per-minute-per-address budget, and tighter budgets on signup, login,
  booking, upload and events
* input: every field length-capped and typed, sort columns and statuses from an allow-list, LIKE
  wildcards stripped from search terms
* uploads: type allow-list re-checked on the server, size cap, stored under a random name in UPLOAD_DIR
  which is not a web root, served back to its owner or staff with `X-Content-Type-Options: nosniff`
* authorization: `/api/me` family needs a session, `/api/admin` and `/api/analytics` need the staff role,
  a record, booking or file belonging to someone else answers 403
* secrets: only read from the environment, never written into a response, never echoed by
  `/api/integrations/status` - that route reports which names are set and nothing more
"""

SETUP_TAIL = """
## What is deliberately not here

* No OAuth, magic link or two-factor sign-in: those need a provider account you connect, and a generated
  button that only pretended to talk to one would be worse than none. `/api/signup` and `/api/login` are
  real email-and-password routes.
* No money moves: an order is recorded as `awaiting-payment` and the provider's own checkout URL or 501
  answer is what the visitor sees. Nothing marks an order paid except your webhook.
* No mail leaves the machine until SMTP_HOST or RESEND_API_KEY is set. Until then the contact form stores
  the message and says so - the reply the visitor reads is different on purpose.
* No third-party tracker: the analytics panel counts events this server wrote itself.
* Tables start empty. The empty states you see in the page are the real ones; SETUP.md's SQL lines below
  put the first rows in.
"""


def chosen(keys) -> tuple[str, ...]:
    """The capability keys this build will write, in catalog order, dependencies pulled in."""
    wanted = {key for key in (keys or ()) if key in blocks.IMPLEMENTED}
    grown = set(wanted)
    for key in list(grown):
        grown.update(blocks.DEPENDENCIES.get(key, ()))
    return tuple(key for key in caps.keys() if key in grown)


def needs_server(keys) -> bool:
    """True when at least one chosen capability asks for a route, a table or a service."""
    return any(part.surface in ("server", "database", "integration")
               for key in chosen(keys) for part in caps.get(key).parts)


def required_env(keys) -> tuple[str, ...]:
    """Every variable name the chosen parts read, first-seen, SESSION_SECRET always present."""
    names = ["SESSION_SECRET"]
    for key in chosen(keys):
        for part in caps.get(key).parts:
            for name in part.env:
                if name not in names:
                    names.append(name)
    return tuple(names)


def route_map(keys) -> list[dict]:
    """The route and table inventory of this build, per capability."""
    out = []
    for key in chosen(keys):
        card = caps.card(caps.get(key))
        out.append({"key": key, "label": card["label"], "status": card["status"],
                    "needs": card["needs"], "routes": list(blocks.ROUTES_BY_FEATURE.get(key, ())),
                    "tables": list(blocks.TABLES_BY_FEATURE.get(key, ())),
                    "env": list(card["env"]), "files": card["files"],
                    "setup": list(card["setup"]), "limits": card["limits"]})
    return out


def _plain(text: str, limit: int = 300) -> str:
    """One line, no quotes, no wrapping: safe to drop into a Python or JS literal."""
    flat = " ".join(str(text or "").replace('"', "'").split())
    return flat[:limit]


def _tuple_literal(names) -> str:
    joined = ", ".join(f'"{name}"' for name in names)
    return f"({joined}{',' if len(names) == 1 else ''})"


def server_text(keys, *, site: str = "") -> str:
    picked = chosen(keys)
    labels = ", ".join(caps.get(key).label.lower() for key in picked)
    head = (SERVER_HEAD
            .replace("@@SITE@@", _plain(site or "This site"))
            .replace("@@SITE_NAME@@", json.dumps(_plain(site or "This site", 120)))
            .replace("@@FEATURE_TABLE@@", _tuple_literal(picked))
            .replace("@@FEATURE_SUMMARY@@", json.dumps(_plain(labels)))
            .replace("@@EMAIL_RE@@", blocks.EMAIL_PATTERN)
            .replace("@@REQUIRED_ENV@@", _tuple_literal(("SESSION_SECRET",)))
            .replace("@@ENV_TABLE@@", _tuple_literal(required_env(keys))))
    body = "\n\n".join(blocks.SERVER[key].strip("\n") for key in picked if blocks.SERVER.get(key))
    return head + body + SERVER_TAIL


def schema_text(keys) -> str:
    picked = [key for key in chosen(keys) if blocks.SCHEMA.get(key)]
    if not picked:
        return "-- This build needs no tables.\n"
    header = ("-- Created on first start by db.init(). Every statement is IF NOT EXISTS, so restarting\n"
              "-- is safe and an existing site.db keeps its rows.\n\n")
    return header + "".join(blocks.SCHEMA[key] for key in picked)


def env_text(keys) -> str:
    names = required_env(keys)
    lines = ["# Copy this file to .env and fill it in. Never commit .env, never paste a real value into",
             "# a page, a screenshot or a chat. server.py reads .env from its own folder at start.", ""]
    for name in names:
        note = blocks.ENV_NOTES.get(name, "")
        if note:
            lines.append("# " + note)
        lines.append(f"{name}=")
        lines.append("")
    optional = [name for name in ("SITE_NAME", "COOKIE_SECURE") if name not in names]
    for name in optional:
        lines.append("# optional - " + blocks.ENV_NOTES[name])
        lines.append(f"{name}=")
        lines.append("")
    return "\n".join(lines)


def client_text(keys) -> str:
    wired = [key for key in chosen(keys) if blocks.CLIENT.get(key)]
    if not wired:
        return ""
    return "\n".join([blocks.CLIENT_HEAD.strip(),
                      "\n".join(blocks.CLIENT[key].strip("\n") for key in wired),
                      blocks.CLIENT_TAIL.strip()]) + "\n"


def page_markup(keys) -> str:
    """The block that goes into index.html: panels, their styles, and the page-only behaviour.

    It ends with `BLOCK_TAIL` because a second feature build has to find this block again *after* the
    publisher has re-serialised the page: HTML comments are stripped by the sanitizer, so no delimiter
    that survives could be a comment, and the block's own closing tag is whichever inline script last
    happened to be included. One empty element with a name of its own is the end of the region.
    """
    picked = chosen(keys)
    panels = "".join(blocks.PAGE[key] for key in picked if blocks.PAGE.get(key))
    if not panels:
        return ""
    css = blocks.SHARED_STYLE + "".join(blocks.STYLE.get(key, "") for key in picked)
    inline = "".join(blocks.INLINE[key] for key in picked if blocks.INLINE.get(key))
    return (BLOCK_HEAD + ' data-lc-feature-set="' + ",".join(picked) + '" id="lc-features">'
            + panels + "</section><style>" + css + "</style>" + inline + BLOCK_TAIL)


def setup_text(keys, *, idea: str = "") -> str:
    picked = chosen(keys)
    text = (SETUP_HEAD
            .replace("@@IDEA@@", _plain(idea or "a site requested in plain English", 200))
            .replace("@@FEATURES@@", _plain(", ".join(caps.get(key).label for key in picked), 800)))
    if not needs_server(picked):
        text += ("\n## This build is page-only\n\nNo server was written because nothing asked for one: "
                 + ", ".join(caps.get(key).label for key in picked)
                 + " all run inside the published page.\n")
        return text + SETUP_TAIL

    text += "\n## Variables this build reads\n\n"
    for name in required_env(picked):
        text += f"* `{name}` - {blocks.ENV_NOTES.get(name, 'read by server.py')}\n"

    text += "\n## Each feature, and what it still needs from you\n"
    for row in route_map(picked):
        text += f"\n### {row['label']} - {caps.STATE_LABEL[row['status']]}\n"
        if row["routes"]:
            text += "Routes: " + ", ".join("`" + route + "`" for route in row["routes"]) + "\n"
        if row["tables"]:
            text += "Tables: " + ", ".join("`" + table + "`" for table in row["tables"]) + "\n"
        if row["setup"]:
            text += "To set up:\n"
            text += "".join(f"{index}. {step}\n" for index, step in enumerate(row["setup"], start=1))
        else:
            text += "To set up: nothing - it runs once the server is started.\n"
        text += "Limits, stated plainly: " + row["limits"] + "\n"

    seeds = [key for key in picked if blocks.TABLES_BY_FEATURE.get(key)]
    if seeds:
        text += ("\n## Putting the first rows in\n\nThe tables start empty, so an empty state on the page "
                 "is the truth rather than a bug. To add a row by hand:\n\n"
                 "    sqlite3 site.db \"INSERT INTO records (title, detail, status, created_at) "
                 "VALUES ('First record', '', 'active', datetime('now'));\"\n\n"
                 "Add products to `products` (prices in whole minor units), open times to `slots` "
                 "(`starts_at` as `YYYY-MM-DDTHH:MM:SSZ`), and posts through the staff panel on the page "
                 "rather than by hand - the slug is generated there.\n")
    return text + SETUP_TAIL


def features_text(keys, *, idea: str = "", plan: dict | None = None) -> str:
    """What was implemented, surface by surface, in the same words the catalog uses."""
    picked = chosen(keys)
    lines = ["# What this build contains", "",
             "Written by Launch Crew for: " + _plain(idea or "a site requested in plain English", 200),
             "",
             "Each capability is reported per surface, and the report is the weakest of them:",
         "",
         "* `generated` - the code is here and works as it stands",
         "* `scaffold` - the code is here and correct, and it needs the steps in SETUP.md to run",
         "* `needs-external-setup` - waiting on an account whose details belong to you",
             ""]
    if plan and plan.get("request"):
        lines += ["## What you asked for", "", '"' + _plain(plan["request"], 600) + '"', ""]
        if plan.get("added"):
            lines += ["Pulled in by dependencies you did not name: "
                      + ", ".join(_plain(caps.get(key).label) for key in plan["added"]), ""]
        for warning in plan.get("warnings") or []:
            lines += ["Note: " + _plain(warning, 300)]
        lines.append("")

    lines.append("## Feature by feature")
    for row in route_map(picked):
        lines += ["", f"### {row['label']} - {caps.STATE_LABEL[row['status']]}"]
        lines.append("Surfaces: " + ", ".join(f"{need} ({caps.STATE_LABEL[need_state(row, need)]})"
                                              for need in row["needs"]))
        if row["routes"]:
            lines.append("API: " + ", ".join("`" + route + "`" for route in row["routes"]))
        if row["tables"]:
            lines.append("Tables: " + ", ".join(row["tables"]))
        if row["env"]:
            lines.append("Waiting on these variables: " + ", ".join("`" + name + "`" for name in row["env"]))
        lines.append("Files: " + ", ".join("`" + name + "`" for name in sorted(set(
            row["files"] + [caps.SHARED_DB, caps.SHARED_SCHEMA] if needs_server(picked) else row["files"]))))
        lines.append("Limit: " + row["limits"])

    if needs_server(picked):
        lines += ["", "## How to start it", "",
                  "See SETUP.md. Short version: `pip install -r requirements.txt`, copy "
                  "env_template.txt to .env, set SESSION_SECRET, run `python server.py`, and open "
                  "http://127.0.0.1:8000.", "",
                  "The panels in index.html say they are waiting for the server until they can hear it. "
                  "That is deliberate: opened as a file, there is no API to reach, and a form that "
                  "pretended to submit would be worse than an honest line."]
    else:
        lines += ["", "## Page only", "",
                  "Nothing in this build needs a server, so the panels work in the published page as it "
                  "stands."]
    lines += ["", "_Report generated from the capability catalog, not typed by hand - "
                  "the statuses come from the same data the API serves at /api/capabilities._", ""]
    return "\n".join(lines)


def need_state(row: dict, surface: str) -> str:
    """The state this build reports for one surface of one capability."""
    capability = caps.get(row["key"])
    for part in capability.parts:
        if part.surface == surface:
            return part.state
    return caps.GENERATED if surface == "page" else caps.NEEDS_SETUP


def compose(keys, *, site: str = "", idea: str = "", plan: dict | None = None) -> dict[str, str]:
    """Every file a feature build writes, by name. Keys the catalog does not know are dropped here."""
    picked = chosen(keys)
    if not picked:
        return {}
    files = {FEATURES_DOC: features_text(picked, idea=idea, plan=plan)}
    markup = page_markup(picked)
    if markup:
        files[PAGE_SECTIONS] = markup
    if needs_server(picked):
        files[caps.SHARED_SERVER] = server_text(picked, site=site)
        files[caps.SHARED_DB] = DB_MODULE
        files[caps.SHARED_SCHEMA] = schema_text(picked)
        files[caps.SHARED_ENV] = env_text(picked)
        files[caps.SHARED_SETUP] = setup_text(picked, idea=idea)
        files[REQUIREMENTS] = REQUIREMENTS_TXT
        client = client_text(picked)
        if client:
            files[FEATURE_CLIENT] = client
    return files
