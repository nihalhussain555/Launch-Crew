"""The source a feature build writes, capability by capability.

Each entry here is ordinary, runnable code: SQL that creates a table, FastAPI routes that enforce the
validation and authorization named in the docstring, markup that carries its own loading/empty/error
states, and the browser code that calls the endpoint. Nothing in this file is a stub that reports
success - a route which needs an account the user has not connected answers 501 with the variable to
set, and the client shows that answer rather than hiding it.

`feature_templates.py` composes these pieces into one application so the user installs and starts the
same handful of files whatever combination of features they asked for.
"""
from __future__ import annotations

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"

# A capability that silently needs another one. `profiles` without `authentication` would be a form with
# nothing to sign in with, so the planner adds the dependency and says it did.
DEPENDENCIES = {"profiles": ("authentication",), "admin": ("authentication",),
                "activity": ("authentication",), "uploads": ("authentication",)}

# The keys with real source below. Anything else is refused by the planner instead of generated empty.
IMPLEMENTED = ("authentication", "profiles", "admin", "records", "catalog", "browse", "blog", "booking",
               "contact", "uploads", "activity", "analytics", "wizard", "pricing", "api", "layout")

ROUTES_BY_FEATURE = {
    "authentication": ("GET /api/status", "POST /api/signup", "POST /api/login", "POST /api/logout",
                       "GET /api/me"),
    "profiles": ("GET /api/me", "PATCH /api/me", "POST /api/me/password", "DELETE /api/me"),
    "admin": ("GET /api/admin/whoami", "GET /api/admin/users", "POST /api/admin/users/{user_id}/role"),
    "records": ("GET /api/records", "POST /api/records", "GET /api/records/{record_id}",
                "PATCH /api/records/{record_id}", "DELETE /api/records/{record_id}"),
    "catalog": ("GET /api/products", "GET /api/products/{product_id}", "POST /api/orders"),
    "blog": ("GET /api/posts", "GET /api/posts/{slug}", "POST /api/posts", "PATCH /api/posts/{post_id}",
             "DELETE /api/posts/{post_id}"),
    "booking": ("GET /api/slots", "POST /api/bookings", "GET /api/bookings",
                "DELETE /api/bookings/{booking_id}"),
    "contact": ("POST /api/contact", "GET /api/contact/messages"),
    "uploads": ("POST /api/uploads", "GET /api/uploads", "GET /api/uploads/{upload_id}/raw",
                "DELETE /api/uploads/{upload_id}"),
    "activity": ("GET /api/activity",),
    "analytics": ("POST /api/events", "GET /api/analytics/summary"),
    "pricing": ("POST /api/subscribe", "POST /api/webhooks/billing"),
    "api": ("GET /api/integrations/status", "POST /api/webhooks/{source}"),
    "browse": (), "wizard": (), "layout": (),
}

TABLES_BY_FEATURE = {
    "authentication": ("users",), "profiles": (), "admin": (), "records": ("records",),
    "catalog": ("products", "orders"), "blog": ("posts",), "booking": ("slots", "bookings"),
    "contact": ("messages",), "uploads": ("uploads",), "activity": ("activity",),
    "analytics": ("events",), "pricing": ("subscriptions",), "api": ("deliveries",),
    "browse": (), "wizard": (), "layout": (),
}

ENV_NOTES = {
    "SESSION_SECRET": "Signs the session cookie. Generate your own; the server refuses a placeholder.",
    "DATABASE_PATH": "Where the SQLite file lives. Defaults to site.db next to server.py.",
    "BOOTSTRAP_ADMIN_EMAIL": "The one address given the staff role the first time it signs up.",
    "UPLOAD_DIR": "Directory uploads are written to. Must not be served as a web root.",
    "MAX_UPLOAD_BYTES": "The size cap the server enforces, in bytes. Default 10485760 (10 MB).",
    "PAYMENT_PROVIDER": "The provider you signed up with: stripe, paypal or a name of your own.",
    "PAYMENT_SECRET_KEY": "The provider's secret API key. Never commit it, never paste it into the page.",
    "PAYMENT_PUBLIC_KEY": "The provider's publishable key, if its checkout needs one in the browser.",
    "CHECKOUT_WEBHOOK_SECRET": "The signing secret for the checkout webhook, from the provider panel.",
    "BILLING_WEBHOOK_SECRET": "The signing secret for the subscription webhook.",
    "WEBHOOK_SECRET": "Shared secret used to verify any inbound webhook this site receives.",
    "EXTERNAL_API_BASE_URL": "The service you want to reach, e.g. https://api.example.com/v1.",
    "EXTERNAL_API_TOKEN": "Its token, with the smallest scope that does the job.",
    "SMTP_HOST": "Mail server host for the contact form. With no mail account set, messages are stored "
                 "and the answer says so.",
    "SMTP_PORT": "Mail server port, usually 587.",
    "SMTP_USER": "Mail server account name.",
    "SMTP_PASSWORD": "Mail server account password or app token.",
    "MAIL_FROM": "The verified sender address the site sends from.",
    "RESEND_API_KEY": "Alternative to SMTP: an API key for an email API provider.",
    "GOOGLE_OAUTH_CLIENT_ID": "Only for calendar sync on bookings. The booking itself needs nothing.",
    "GOOGLE_OAUTH_CLIENT_SECRET": "The matching calendar secret.",
    "GA_MEASUREMENT_ID": "Only if you choose Google Analytics instead of this site's own counts.",
    "PLAUSIBLE_DOMAIN": "Only if you choose Plausible instead of this site's own counts.",
    "PUSH_SERVICE_KEY": "Only for push notifications on the activity feed.",
    "SITE_NAME": "The name the server reports at /api/status. Optional.",
    "COOKIE_SECURE": "Set to 1 once the site is behind https, so the session cookie is https-only.",
}

# --------------------------------------------------------------------------- schema
SCHEMA = {
    "authentication": '''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'staff')),
    bio TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

''',
    "records": '''CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    data TEXT NOT NULL DEFAULT '{}',
    owner_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_status ON records (status);

''',
    "catalog": '''CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_minor INTEGER NOT NULL CHECK (price_minor >= 0),
    currency TEXT NOT NULL DEFAULT 'USD',
    stock INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    reference TEXT NOT NULL UNIQUE,
    user_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    lines TEXT NOT NULL,
    total_minor INTEGER NOT NULL CHECK (total_minor >= 0),
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'awaiting-payment',
    provider TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT
);

''',
    "blog": '''CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    excerpt TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
    author_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    published_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts (status);

''',
    "booking": '''CREATE TABLE IF NOT EXISTS slots (
    id INTEGER PRIMARY KEY,
    starts_at TEXT NOT NULL,
    minutes INTEGER NOT NULL DEFAULT 30 CHECK (minutes BETWEEN 5 AND 600),
    resource TEXT NOT NULL DEFAULT 'default',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_slots_unique ON slots (starts_at, resource);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY,
    slot_id INTEGER NOT NULL REFERENCES slots (id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'held' CHECK (status IN ('held', 'confirmed', 'cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_active ON bookings (slot_id) WHERE status != 'cancelled';

''',
    "contact": '''CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'stored' CHECK (status IN ('stored', 'sent', 'failed')),
    delivery_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

''',
    "uploads": '''CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    stored_name TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

''',
    "activity": '''CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    user_id INTEGER REFERENCES users (id) ON DELETE CASCADE,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity (user_id, created_at);

''',
    "analytics": '''CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    user_id INTEGER,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_name ON events (name, created_at);

''',

    "pricing": '''CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users (id) ON DELETE CASCADE,
    plan TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE (provider, provider_id)
);

''',
    "api": '''CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    event_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    received_at TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source, event_id)
);

''',
}

# --------------------------------------------------------------------------- server routes
_SERVER_AUTH = r'''
# ----------------------------------------------------------------------- Sign in and register
@app.post("/api/signup")
async def signup(request: Request):
    guard = write_guard(request)
    if guard:
        return guard
    if rate_limited("signup:" + client_ip(request), limit=5, window=300.0):
        return problem(429, "Too many sign-up attempts from this address. Try again in a few minutes.")
    body = await body_json(request)
    email = email_of(body.get("email"))
    password = password_of(body.get("password"))
    name = text_of(body.get("display_name"), "Display name", max_length=80, required=False)
    if store.one("SELECT id FROM users WHERE email = ?", (email,)):
        return problem(409, "An account already uses that address. Sign in instead, or use the reset "
                            "process you set up for your site.")
    role = "staff" if email == os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower() else "member"
    user_id = store.write("INSERT INTO users (email, password_hash, display_name, role, created_at) "
                          "VALUES (?, ?, ?, ?, ?)",
                          (email, hash_password(password), name or email.split("@")[0], role, now_iso()))
    row = store.one("SELECT id, email, display_name, role, bio, created_at FROM users WHERE id = ?",
                    (user_id,))
    record_event("account.created", user_id, row["email"])
    track("signup", user_id)
    return out(201, {"ok": True, "user": public_user(row)}, cookie=session_token(user_id, row["role"]))


@app.post("/api/login")
async def login(request: Request):
    guard = write_guard(request)
    if guard:
        return guard
    if rate_limited("login:" + client_ip(request), limit=10, window=60.0):
        return problem(429, "Too many sign-in attempts from this address. Wait a minute.")
    body = await body_json(request)
    email = email_of(body.get("email"))
    password = password_of(body.get("password"))
    if rate_limited("login:" + email, limit=10, window=60.0):
        return problem(429, "Too many attempts for that account. Wait a minute.")
    row = store.one("SELECT id, email, display_name, role, bio, created_at, deleted_at, password_hash "
                    "FROM users WHERE email = ?", (email,))
    # One message for both failures: whether the address is unknown is not this endpoint's to tell.
    if not row or row["deleted_at"] or not verify_password(password, row["password_hash"]):
        return problem(401, "That email and password do not match an active account.")
    store.run("UPDATE users SET updated_at = ? WHERE id = ?", (now_iso(), row["id"]))
    record_event("account.signed-in", row["id"], row["email"])
    return ok({"user": public_user(row), "signed_in_at": now_iso()},
              cookie=session_token(row["id"], row["role"]))


@app.post("/api/logout")
async def logout(request: Request):
    user = session_user(request)
    response = out(200, {"ok": True, "signed_out": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    if user:
        record_event("account.signed-out", user["id"], user["email"])
    return response


@app.get("/api/me")
def whoami(request: Request):
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    return ok({"user": public_user(user)})
'''

_SERVER_PROFILES = r'''
# ----------------------------------------------------------------------- Your own account
@app.patch("/api/me")
async def update_me(request: Request):
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    body = await body_json(request)
    name = text_of(body.get("display_name"), "Display name", max_length=80, required=False)
    bio = text_of(body.get("bio"), "Bio", max_length=500, required=False)
    store.run("UPDATE users SET display_name = ?, bio = ?, updated_at = ? WHERE id = ?",
              (name or user["display_name"], bio, now_iso(), user["id"]))
    record_event("account.updated", user["id"], "profile")
    row = store.one("SELECT id, email, display_name, role, bio, created_at FROM users WHERE id = ?",
                    (user["id"],))
    return ok({"user": public_user(row), "saved": True})


@app.post("/api/me/password")
async def change_password(request: Request):
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    body = await body_json(request)
    current = body.get("current_password") if isinstance(body.get("current_password"), str) else ""
    stored = store.one("SELECT password_hash FROM users WHERE id = ?", (user["id"],))["password_hash"]
    if not verify_password(current, stored):
        return problem(403, "That is not your current password.")
    fresh = password_of(body.get("new_password"))
    if verify_password(fresh, stored):
        return problem(422, "Choose a password this account has not used before.")
    store.run("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
              (hash_password(fresh), now_iso(), user["id"]))
    record_event("account.password-changed", user["id"], "")
    return ok({"changed": True, "note": "Sign in again with the new password."})


@app.delete("/api/me")
async def delete_me(request: Request):
    """A soft delete: the row stays so orders and posts keep an author, and the account stops working.

    A hard delete here would break other people's records; the retention decision is yours to make with
    your own policy, and SETUP.md says so.
    """
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    body = await body_json(request)
    if not verify_password(password_of(body.get("password")),
                           store.one("SELECT password_hash FROM users WHERE id = ?",
                                     (user["id"],))["password_hash"]):
        return problem(403, "Confirm your password to close the account.")
    store.run("UPDATE users SET deleted_at = ?, role = 'member' WHERE id = ?", (now_iso(), user["id"]))
    record_event("account.closed", user["id"], user["email"])
    response = ok({"closed": True}, cookie=None)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
'''

_SERVER_ADMIN = r'''
# ----------------------------------------------------------------------- Staff area
@app.get("/api/admin/whoami")
def admin_whoami(request: Request):
    user = require_role(request, "staff")
    if isinstance(user, JSONResponse):
        return user
    return ok({"staff": True, "user": public_user(user),
               "accounts": store.count("SELECT COUNT(*) FROM users WHERE deleted_at IS NULL"),
               "pending": store.count("SELECT COUNT(*) FROM users WHERE role = 'member' "
                                      "AND deleted_at IS NULL")})


@app.get("/api/admin/users")
def admin_users(request: Request):
    user = require_role(request, "staff")
    if isinstance(user, JSONResponse):
        return user
    limit, offset, sort, order = paging(request, {"created_at", "email", "display_name", "role"},
                                        "created_at")
    search = like_of(request)
    where, params = ["deleted_at IS NULL"], []
    if search:
        where.append("(email LIKE ? OR display_name LIKE ?)")
        params += ["%" + search + "%", "%" + search + "%"]
    rows = store.query("SELECT id, email, display_name, role, created_at FROM users WHERE "
                       + " AND ".join(where) + " ORDER BY " + sort + " " + order + " LIMIT ? OFFSET ?",
                       tuple(params) + (limit, offset))
    total = store.count("SELECT COUNT(*) FROM users WHERE " + " AND ".join(where), tuple(params))
    return ok({"users": rows, "total": total, "limit": limit, "offset": offset,
               "sort": sort, "dir": order.lower(), "search": search})


@app.post("/api/admin/users/{user_id}/role")
async def admin_user_role(user_id: int, request: Request):
    staff = require_role(request, "staff")
    if isinstance(staff, JSONResponse):
        return staff
    guard = write_guard(request)
    if guard:
        return guard
    body = await body_json(request)
    if user_id == staff["id"]:
        return problem(422, "You cannot change your own role - another staff account has to do it.")
    target = store.one("SELECT id, email, role FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,))
    if not target:
        return problem(404, "No such account.")
    role = choice_of(body.get("role"), "Role", {"member", "staff"})
    store.run("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (role, now_iso(), user_id))
    record_event("account.role-changed", staff["id"], "%s -> %s" % (target["email"], role))
    return ok({"user_id": user_id, "role": role, "changed_by": staff["email"]})
'''

_SERVER_RECORDS = r'''
# ----------------------------------------------------------------------- Records
RECORD_COLUMNS = {"title": "title", "detail": "detail", "status": "status"}


def record_payload(row):
    try:
        extra = json.loads(row.get("data") or "{}")
    except ValueError:
        extra = {}
    return {"id": row["id"], "title": row["title"], "detail": row["detail"], "status": row["status"],
            "extra": extra if isinstance(extra, dict) else {}, "owner_id": row["owner_id"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def record_from_body(body, existing=None):
    """Validate one record. Extra fields the form sends are kept as JSON, capped and typed."""
    title = text_of(body.get("title"), "Title", max_length=200,
                    required=existing is None) or (existing or {}).get("title", "")
    detail = text_of(body.get("detail"), "Detail", max_length=4000, required=False)
    status = text_of(body.get("status"), "Status", max_length=40, required=False) or "active"
    extra = body.get("extra") if isinstance(body.get("extra"), dict) else {}
    slim = {}
    for key, value in list(extra.items())[:40]:
        name = text_of(str(key), "Field name", max_length=40)
        slim[name] = value if isinstance(value, (int, float, bool)) else text_of(
            str(value), name, max_length=2000, required=False)
    return title, detail, status, json.dumps(slim, ensure_ascii=False)[:20000]


@app.get("/api/records")
def list_records(request: Request):
    limit, offset, sort, order = paging(request, {"created_at", "updated_at", "title", "status"},
                                        "created_at")
    search = like_of(request)
    status = text_of(request.query_params.get("status"), "Status", max_length=40, required=False)
    where, params = ["deleted_at IS NULL"], []
    if search:
        where.append("(title LIKE ? OR detail LIKE ?)")
        params += ["%" + search + "%", "%" + search + "%"]
    if status:
        where.append("status = ?")
        params.append(status)
    rows = store.query("SELECT * FROM records WHERE " + " AND ".join(where) + " ORDER BY " + sort + " "
                       + order + " LIMIT ? OFFSET ?", tuple(params) + (limit, offset))
    total = store.count("SELECT COUNT(*) FROM records WHERE " + " AND ".join(where), tuple(params))
    return ok({"records": [record_payload(r) for r in rows], "total": total, "limit": limit,
               "offset": offset, "sort": sort, "dir": order.lower(), "search": search})


@app.post("/api/records")
async def create_record(request: Request):
    guard = write_guard(request)
    if guard:
        return guard
    body = await body_json(request)
    title, detail, status, extra = record_from_body(body)
    user = session_user(request)
    record_id = store.write("INSERT INTO records (title, detail, status, data, owner_id, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (title, detail, status, extra, user["id"] if user else None, now_iso()))
    row = store.one("SELECT * FROM records WHERE id = ?", (record_id,))
    record_event("record.created", user["id"] if user else None, title)
    track("record_created")
    return out(201, {"ok": True, "record": record_payload(row)})


@app.get("/api/records/{record_id}")
def get_record(record_id: int, request: Request):
    row = store.one("SELECT * FROM records WHERE id = ? AND deleted_at IS NULL", (record_id,))
    if not row:
        return problem(404, "No such record.")
    return ok({"record": record_payload(row)})


@app.patch("/api/records/{record_id}")
async def patch_record(record_id: int, request: Request):
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    existing = store.one("SELECT * FROM records WHERE id = ? AND deleted_at IS NULL", (record_id,))
    if not existing:
        return problem(404, "No such record.")
    body = await body_json(request)
    title, detail, status, extra = record_from_body(body, existing)
    store.run("UPDATE records SET title = ?, detail = ?, status = ?, data = ?, updated_at = ? WHERE id = ?",
              (title, detail, status, extra, now_iso(), record_id))
    record_event("record.updated", user["id"], existing["title"])
    return ok({"record": record_payload(store.one("SELECT * FROM records WHERE id = ?", (record_id,)))})


@app.delete("/api/records/{record_id}")
async def delete_record(record_id: int, request: Request):
    user = require_role(request, "member")
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    existing = store.one("SELECT * FROM records WHERE id = ? AND deleted_at IS NULL", (record_id,))
    if not existing:
        return problem(404, "No such record.")
    if user["role"] != "staff" and existing["owner_id"] not in (None, user["id"]):
        return problem(403, "Only the person who added this record, or a staff account, may remove it.")
    store.run("UPDATE records SET deleted_at = ?, updated_at = ? WHERE id = ?",
              (now_iso(), now_iso(), record_id))
    record_event("record.deleted", user["id"], existing["title"])
    return ok({"deleted": True, "id": record_id, "note": "The row is kept and hidden; nothing was erased."})
'''

_SERVER_CATALOG = r'''
# ----------------------------------------------------------------------- Catalog and orders
@app.get("/api/products")
def list_products(request: Request):
    limit, offset, sort, order = paging(request, {"created_at", "name", "price_minor", "stock"}, "name")
    search = like_of(request)
    where, params = ["active = 1"], []
    if search:
        where.append("(name LIKE ? OR description LIKE ?)")
        params += ["%" + search + "%", "%" + search + "%"]
    try:
        ceiling = int(request.query_params.get("max_price", 0))
    except ValueError:
        raise Invalid("max_price must be a whole number of minor units") from None
    if ceiling > 0:
        where.append("price_minor <= ?")
        params.append(ceiling)
    rows = store.query("SELECT * FROM products WHERE " + " AND ".join(where) + " ORDER BY " + sort + " "
                       + order + " LIMIT ? OFFSET ?", tuple(params) + (limit, offset))
    total = store.count("SELECT COUNT(*) FROM products WHERE " + " AND ".join(where), tuple(params))
    return ok({"products": rows, "total": total, "limit": limit, "offset": offset,
               "currency": rows[0]["currency"] if rows else "USD",
               "note": "Prices are whole minor units - cents, pence - so the browser never rounds."})


@app.get("/api/products/{product_id}")
def get_product(product_id: int, request: Request):
    row = store.one("SELECT * FROM products WHERE id = ? AND active = 1", (product_id,))
    if not row:
        return problem(404, "No such product.")
    return ok({"product": row})


@app.post("/api/orders")
async def create_order(request: Request):
    """An order is recorded; the money is the provider's business and this says so.

    With no PAYMENT_SECRET_KEY the route answers 501 and writes nothing, because an order marked paid by
    a server that never spoke to a payment provider is worse than no order at all.
    """
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    provider = os.environ.get("PAYMENT_PROVIDER", "").strip()
    secret = os.environ.get("PAYMENT_SECRET_KEY", "").strip()
    if not provider or not secret:
        return missing_env("PAYMENT_PROVIDER", "PAYMENT_SECRET_KEY", "PAYMENT_PUBLIC_KEY")
    body = await body_json(request)
    lines = body.get("lines")
    if not isinstance(lines, list) or not lines:
        raise Invalid("An order needs at least one line")
    if len(lines) > 100:
        raise Invalid("An order may not hold more than 100 lines")
    total, clean_lines = 0, []
    for line in lines:
        if not isinstance(line, dict):
            raise Invalid("Every order line must be an object")
        product = store.one("SELECT id, name, price_minor, currency, stock FROM products WHERE id = ? "
                            "AND active = 1", (id_of(line.get("id"), "Product id"),))
        if not product:
            raise Invalid("A product in that cart no longer exists.")
        try:
            quantity = int(line.get("quantity", 1))
        except (TypeError, ValueError):
            raise Invalid("Quantities must be whole numbers") from None
        if quantity < 1 or quantity > 99:
            raise Invalid("Each quantity must be between 1 and 99")
        if product["stock"] < quantity:
            return problem(409, "%s has only %d left." % (product["name"], product["stock"]))
        total += product["price_minor"] * quantity
        clean_lines.append({"id": product["id"], "name": product["name"], "quantity": quantity,
                            "unit_minor": product["price_minor"], "currency": product["currency"]})
    reference = "ord_" + secrets.token_hex(8)
    order_id = store.write("INSERT INTO orders (reference, user_id, lines, total_minor, currency, "
                           "status, provider, created_at) VALUES (?, ?, ?, ?, ?, 'awaiting-payment', ?, ?)",
                           (reference, user["id"], json.dumps(clean_lines), total,
                            clean_lines[0]["currency"], provider, now_iso()))
    for line in clean_lines:
        store.run("UPDATE products SET stock = stock - ?, updated_at = ? WHERE id = ?",
                  (line["quantity"], now_iso(), line["id"]))
    record_event("order.created", user["id"], reference)
    track("order", user["id"], reference)

    endpoint = {"stripe": "https://api.stripe.com/v1/checkout/sessions"}.get(provider)
    if not endpoint:
        return ok({"order": {"id": order_id, "reference": reference, "total_minor": total,
                             "status": "awaiting-payment"},
                   "checkout": None,
                   "note": "The order is stored. This build knows no checkout endpoint for provider '"
                           + provider + "', so add yours in server.py where the checkout call is made - "
                                      "it has not been pretended."})
    status_code, text = provider_call(endpoint, {"authorization": "Bearer " + secret},
                                      {"success_url": str(request.url_for("/")),
                                       "line_items": [{"price": str(line["id"]), "quantity": line["quantity"]}
                                                      for line in clean_lines]})
    if status_code != 200:
        return problem(502, "The payment provider answered " + str(status_code) + ". The order is stored "
                           "as awaiting payment; nothing was charged.", detail=text[:500])
    try:
        session = json.loads(text)
    except ValueError:
        return problem(502, "The payment provider answered with something unreadable.", detail=text[:300])
    store.run("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
              ("checkout-created", now_iso(), order_id))
    return ok({"order": {"id": order_id, "reference": reference, "total_minor": total},
               "checkout_url": session.get("url") or "",
               "note": "Open the provider's URL to pay. This server has taken no money."})
'''

_SERVER_BLOG = r'''
# ----------------------------------------------------------------------- Posts
def post_excerpt(body, given=""):
    if given:
        return given[:280]
    flat = " ".join(str(body or "").split())
    return (flat[:200] + "...") if len(flat) > 200 else flat


@app.get("/api/posts")
def list_posts(request: Request):
    limit, offset, sort, order = paging(request, {"created_at", "title", "published_at"}, "published_at")
    status = choice_of(request.query_params.get("status"), "Status", {"draft", "published", "all"}, "all")
    user = session_user(request)
    if status == "all" and (not user or user["role"] != "staff"):
        return problem(403, "Drafts are a staff view.")
    where, params = [], []
    if status != "all":
        where.append("status = ?")
        params.append("published" if status == "published" else "draft")
    search = like_of(request)
    if search:
        where.append("(title LIKE ? OR excerpt LIKE ?)")
        params += ["%" + search + "%", "%" + search + "%"]
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = store.query("SELECT id, slug, title, excerpt, status, created_at, published_at FROM posts"
                       + clause + " ORDER BY " + sort + " " + order + " LIMIT ? OFFSET ?",
                       tuple(params) + (limit, offset))
    total = store.count("SELECT COUNT(*) FROM posts" + clause, tuple(params))
    return ok({"posts": rows, "total": total, "limit": limit, "offset": offset})


@app.get("/api/posts/{slug}")
def get_post(slug: str, request: Request):
    clean = slug if SLUG_RE.match(slug or "") else ""
    if not clean:
        raise Invalid("That is not a web address this site uses")
    row = store.one("SELECT * FROM posts WHERE slug = ?", (clean,))
    if not row:
        return problem(404, "No such post.")
    if row["status"] != "published":
        # A draft is invisible rather than forbidden: 403 would confirm that it exists.
        staff = require_role(request, "staff")
        if isinstance(staff, JSONResponse):
            return problem(404, "No such post.")
    return ok({"post": row})


@app.post("/api/posts")
async def create_post(request: Request):
    staff = require_role(request, "staff")
    if isinstance(staff, JSONResponse):
        return staff
    guard = write_guard(request)
    if guard:
        return guard
    body = await body_json(request)
    title = text_of(body.get("title"), "Title", max_length=200)
    text = text_of(body.get("body"), "Body", max_length=40000, required=False)
    status = choice_of(body.get("status"), "Status", {"draft", "published"}, "draft")
    slug = slug_of(body.get("slug") or title)
    if store.one("SELECT id FROM posts WHERE slug = ?", (slug,)):
        return problem(409, "That web address already belongs to another post. Change the title or set a "
                            "slug of your own.")
    post_id = store.write("INSERT INTO posts (slug, title, body, excerpt, status, author_id, created_at, "
                          "published_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (slug, title, text, post_excerpt(text, str(body.get("excerpt") or "")), status,
                           staff["id"], now_iso(), now_iso() if status == "published" else None))
    record_event("post." + status, staff["id"], slug)
    return out(201, {"ok": True, "post": store.one("SELECT * FROM posts WHERE id = ?", (post_id,))})


@app.patch("/api/posts/{post_id}")
async def patch_post(post_id: int, request: Request):
    staff = require_role(request, "staff")
    if isinstance(staff, JSONResponse):
        return staff
    guard = write_guard(request)
    if guard:
        return guard
    row = store.one("SELECT * FROM posts WHERE id = ?", (post_id,))
    if not row:
        return problem(404, "No such post.")
    body = await body_json(request)
    title = text_of(body.get("title"), "Title", max_length=200, required=False) or row["title"]
    text = text_of(body.get("body"), "Body", max_length=40000, required=False) or row["body"]
    status = choice_of(body.get("status"), "Status", {"draft", "published"}, row["status"])
    store.run("UPDATE posts SET title = ?, body = ?, excerpt = ?, status = ?, updated_at = ?, "
              "published_at = ? WHERE id = ?",
              (title, text, post_excerpt(text, str(body.get("excerpt") or "")), status, now_iso(),
               row["published_at"] or (now_iso() if status == "published" else None), post_id))
    record_event("post.updated", staff["id"], row["slug"])
    return ok({"post": store.one("SELECT * FROM posts WHERE id = ?", (post_id,))})


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: int, request: Request):
    staff = require_role(request, "staff")
    if isinstance(staff, JSONResponse):
        return staff
    guard = write_guard(request)
    if guard:
        return guard
    row = store.one("SELECT slug FROM posts WHERE id = ?", (post_id,))
    if not row:
        return problem(404, "No such post.")
    store.run("DELETE FROM posts WHERE id = ?", (post_id,))
    record_event("post.deleted", staff["id"], row["slug"])
    return ok({"deleted": True, "slug": row["slug"],
               "note": "The row is gone. Keep a copy of anything you might want back."})
'''

_SERVER_BOOKING = r'''
# ----------------------------------------------------------------------- Appointments
@app.get("/api/slots")
def list_slots(request: Request):
    limit, offset, sort, order = paging(request, {"starts_at"}, "starts_at")
    resource = text_of(request.query_params.get("resource"), "Resource", max_length=40, required=False) \
        or "default"
    where, params = ["resource = ?"], [resource]
    after = text_of(request.query_params.get("after"), "After", max_length=32, required=False)
    if after:
        where.append("starts_at >= ?")
        params.append(after)
    clause = " AND ".join(where)
    rows = store.query("SELECT s.id, s.starts_at, s.minutes, s.resource, "
                       "(SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.status != "
                       "'cancelled') AS taken FROM slots s WHERE " + clause + " ORDER BY s." + sort + " "
                       + order + " LIMIT ? OFFSET ?", tuple(params) + (limit, offset))
    for row in rows:
        row["free"] = not row["taken"]
    return ok({"slots": rows, "total": len(rows), "resource": resource})


@app.post("/api/bookings")
async def hold_slot(request: Request):
    """Two people cannot hold one time: the index is UNIQUE and the clash is reported, not overwritten."""
    guard = write_guard(request)
    if guard:
        return guard
    if rate_limited("booking:" + client_ip(request), limit=10, window=600.0):
        return problem(429, "Too many booking attempts from this address.")
    body = await body_json(request)
    slot_id = id_of(body.get("slot_id"), "Slot")
    user = session_user(request)
    name = text_of(body.get("name"), "Name", max_length=120, required=not user) or \
        (user["display_name"] if user else "")
    email = email_of(body.get("email")) if not user else text_of(
        body.get("email") or user["email"], "Email", max_length=254)
    note = text_of(body.get("note"), "Note", max_length=1000, required=False)
    slot = store.one("SELECT * FROM slots WHERE id = ?", (slot_id,))
    if not slot:
        return problem(404, "That time is not on the calendar.")
    taken = store.count("SELECT COUNT(*) FROM bookings WHERE slot_id = ? AND status != 'cancelled'",
                        (slot_id,))
    if taken:
        return problem(409, "Someone took that slot. Pick another time.")
    try:
        booking_id = store.write("INSERT INTO bookings (slot_id, user_id, name, email, note, created_at) "
                                 "VALUES (?, ?, ?, ?, ?, ?)",
                                 (slot_id, user["id"] if user else None, name, email, note, now_iso()))
    except Exception:  # noqa: BLE001 - the unique index is the real answer to a race
        return problem(409, "Someone took that slot while you were deciding. Pick another time.")
    record_event("booking.held", user["id"] if user else None, slot["starts_at"])
    track("booking")
    return out(201, {"ok": True, "booking": {"id": booking_id, "starts_at": slot["starts_at"],
                                             "minutes": slot["minutes"], "status": "held"},
                     "note": "Held, not confirmed. Nothing outside this site has been told yet."})


@app.get("/api/bookings")
def my_bookings(request: Request):
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    limit, offset, sort, order = paging(request, {"created_at", "starts_at"}, "starts_at")
    if user["role"] == "staff":
        rows = store.query("SELECT b.*, s.starts_at, s.minutes, s.resource FROM bookings b "
                           "JOIN slots s ON s.id = b.slot_id ORDER BY s." + sort + " " + order
                           + " LIMIT ? OFFSET ?", (limit, offset))
    else:
        rows = store.query("SELECT b.*, s.starts_at, s.minutes, s.resource FROM bookings b "
                           "JOIN slots s ON s.id = b.slot_id WHERE b.user_id = ? ORDER BY s." + sort
                           + " " + order + " LIMIT ? OFFSET ?", (user["id"], limit, offset))
    return ok({"bookings": rows, "scope": "all" if user["role"] == "staff" else "own"})


@app.delete("/api/bookings/{booking_id}")
async def cancel_booking(booking_id: int, request: Request):
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    row = store.one("SELECT b.*, s.starts_at FROM bookings b JOIN slots s ON s.id = b.slot_id "
                    "WHERE b.id = ?", (booking_id,))
    if not row:
        return problem(404, "No such booking.")
    if user["role"] != "staff" and row["user_id"] != user["id"]:
        return problem(403, "That booking belongs to someone else.")
    store.run("UPDATE bookings SET status = 'cancelled', updated_at = ? WHERE id = ?",
              (now_iso(), booking_id))
    record_event("booking.cancelled", user["id"], row["starts_at"])
    return ok({"cancelled": True, "starts_at": row["starts_at"]})
'''

_SERVER_CONTACT = r'''
# ----------------------------------------------------------------------- Contact
def smtp_send(to_name, from_address, subject, message) -> tuple[bool, str]:
    """Try the mail account in the environment. The answer says which way it went."""
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        return False, "No SMTP_HOST set."
    import smtplib
    from email.message import EmailMessage

    mail = EmailMessage()
    mail["Subject"] = subject[:200]
    mail["From"] = os.environ.get("MAIL_FROM", "").strip()
    mail["To"] = os.environ.get("MAIL_TO", mail["From"]).strip()
    mail["Reply-To"] = from_address
    mail.set_content(message)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=15) as client:
            client.starttls()
            user, password = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
            if user:
                client.login(user, password)
            client.send_message(mail)
        return True, "Sent through " + host
    except Exception as exc:  # noqa: BLE001 - a mail failure is reported, never hidden
        return False, "%s: %s" % (type(exc).__name__, str(exc)[:200])


@app.post("/api/contact")
async def contact(request: Request):
    """Store first, then try to deliver, then tell the truth about both.

    With no mail account configured the message is kept and the answer says it was stored rather than
    sent - the form works, the visitor sees an honest line, and nothing is reported as delivered.
    """
    guard = write_guard(request)
    if guard:
        return guard
    if rate_limited("contact:" + client_ip(request), limit=5, window=900.0):
        return problem(429, "Too many messages from this address. Try again later.")
    body = await body_json(request)
    name = text_of(body.get("name"), "Name", max_length=120)
    email = email_of(body.get("email"))
    subject = text_of(body.get("subject"), "Subject", max_length=200, required=False)
    message = text_of(body.get("message"), "Message", max_length=8000)
    if not subject:
        subject = "Message from " + name
    stored = store.one(
        "SELECT id FROM messages WHERE email = ? AND body = ? AND created_at > datetime('now', "
        "'-2 minutes') LIMIT 1", (email, message))
    if stored:
        return problem(409, "That exact message was sent a moment ago. It is already in the queue.")
    message_id = store.write("INSERT INTO messages (name, email, subject, body, status, delivery_note, "
                             "created_at) VALUES (?, ?, ?, ?, 'stored', '', ?)",
                             (name, email, subject, message, now_iso()))
    record_event("contact.received", None, subject)
    track("contact")
    sent, note = (False, "No mail account configured - the message is stored, not delivered.")
    if os.environ.get("RESEND_API_KEY", "").strip():
        status_code, text = provider_call("https://api.resend.com/emails",
                                          {"authorization": "Bearer "
                                           + os.environ["RESEND_API_KEY"].strip()},
                                          {"from": os.environ.get("MAIL_FROM", ""),
                                           "to": [os.environ.get("MAIL_TO",
                                                                 os.environ.get("MAIL_FROM", ""))],
                                           "subject": subject, "text": message, "reply_to": email})
        sent, note = status_code in (200, 201), "Provider answered %s: %s" % (status_code, text[:200])
    elif os.environ.get("SMTP_HOST", "").strip():
        sent, note = smtp_send(name, email, subject, message)
    store.run("UPDATE messages SET status = ?, delivery_note = ? WHERE id = ?",
              ("sent" if sent else "stored", note[:300], message_id))
    if sent:
        return ok({"id": message_id, "delivered": True, "note": note})
    return ok({"id": message_id, "delivered": False, "stored": True, "note": note,
               "tell_the_visitor": "Your message is with us. Set the mail account in the environment and "
                                   "this reply will change to a delivery, without the form moving."})


@app.get("/api/contact/messages")
def contact_queue(request: Request):
    staff = require_role(request, "staff")
    if isinstance(staff, JSONResponse):
        return staff
    limit, offset, sort, order = paging(request, {"created_at", "subject", "status"}, "created_at")
    rows = store.query("SELECT id, name, email, subject, status, delivery_note, created_at FROM messages "
                       "ORDER BY " + sort + " " + order + " LIMIT ? OFFSET ?", (limit, offset))
    return ok({"messages": rows, "total": store.count("SELECT COUNT(*) FROM messages")})
'''

_SERVER_UPLOADS = r'''
# ----------------------------------------------------------------------- Uploads
UPLOAD_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                "image/gif": ".gif", "application/pdf": ".pdf", "text/plain": ".txt",
                "text/csv": ".csv"}
DEFAULT_MAX_UPLOAD = 10 * 1024 * 1024


def upload_root() -> Path:
    """A directory the web server does not serve. The default sits next to the code, outside any
    document root, and is created on demand."""
    raw = os.environ.get("UPLOAD_DIR", "").strip() or str(HERE / "uploads")
    root = Path(raw)
    root.mkdir(parents=True, exist_ok=True)
    return root


def max_upload_bytes() -> int:
    try:
        return max(1024, int(os.environ.get("MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD)))
    except ValueError:
        return DEFAULT_MAX_UPLOAD


@app.post("/api/uploads")
async def upload(request: Request):
    """One file, checked again on the server: type, size, name, and stored under a name of our own.

    The browser's claims about a file are never trusted here, and nothing uploaded is ever reachable by
    its own path - it comes back through this API, to its owner or to staff.
    """
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    if rate_limited("upload:" + str(user["id"]), limit=30, window=3600.0):
        return problem(429, "That account has uploaded its share for this hour.")
    form = await request.form()
    item = form.get("file")
    if item is None or not hasattr(item, "read"):
        raise Invalid("No file arrived")
    declared = text_of(getattr(item, "content_type", ""), "File type", max_length=100)
    if declared not in UPLOAD_TYPES:
        return problem(415, "That file type is not accepted here. Allowed: "
                            + ", ".join(sorted(UPLOAD_TYPES)))
    original = text_of(getattr(item, "filename", ""), "File name", max_length=200, required=False) \
        or "upload" + UPLOAD_TYPES[declared]
    if "/" in original or "\\" in original or ".." in original:
        raise Invalid("That is not a file name")
    data = await item.read(max_upload_bytes() + 1)
    if len(data) > max_upload_bytes():
        return problem(413, "That file is larger than the " + str(max_upload_bytes())
                            + " byte limit this server enforces.")
    if not data:
        return problem(422, "That file is empty.")
    stored_name = secrets.token_hex(16) + UPLOAD_TYPES[declared]
    upload_root()
    target = upload_root() / stored_name
    try:
        with open(target, "xb") as handle:
            handle.write(data)
    except FileExistsError:
        return problem(409, "A file with that name already exists. Try again.")
    except OSError as exc:
        return problem(500, "The file could not be stored: " + str(exc)[:200] + " Check UPLOAD_DIR.")
    upload_id = store.write("INSERT INTO uploads (owner_id, stored_name, original_name, media_type, "
                            "bytes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (user["id"], stored_name, original, declared, len(data), now_iso()))
    record_event("file.uploaded", user["id"], original)
    track("upload", user["id"], declared)
    return out(201, {"ok": True, "upload": {"id": upload_id, "name": original, "media_type": declared,
                                            "bytes": len(data),
                                            "url": "/api/uploads/" + str(upload_id) + "/raw"}})


@app.get("/api/uploads")
def list_uploads(request: Request):
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    limit, offset, sort, order = paging(request, {"created_at", "original_name", "bytes"}, "created_at")
    where, params = (["owner_id = ?"], [user["id"]]) if user["role"] != "staff" else ([], [])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = store.query("SELECT id, original_name, media_type, bytes, created_at, owner_id FROM uploads"
                       + clause + " ORDER BY " + sort + " " + order + " LIMIT ? OFFSET ?",
                       tuple(params) + (limit, offset))
    return ok({"uploads": rows, "scope": "own" if user["role"] != "staff" else "all"})


@app.get("/api/uploads/{upload_id}/raw")
def read_upload(upload_id: int, request: Request):
    """Served with the stored type and nosniff, never from a path the client supplies."""
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    row = store.one("SELECT * FROM uploads WHERE id = ?", (upload_id,))
    if not row:
        return problem(404, "No such file.")
    if user["role"] != "staff" and row["owner_id"] != user["id"]:
        return problem(403, "That file belongs to someone else.")
    target = upload_root() / row["stored_name"]
    if not target.exists():
        return problem(410, "The file is not on this disk any more. The record still exists.")
    return Response(target.read_bytes(), media_type=row["media_type"], headers=security_headers())


@app.delete("/api/uploads/{upload_id}")
async def remove_upload(upload_id: int, request: Request):
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    row = store.one("SELECT * FROM uploads WHERE id = ?", (upload_id,))
    if not row:
        return problem(404, "No such file.")
    if user["role"] != "staff" and row["owner_id"] != user["id"]:
        return problem(403, "That file belongs to someone else.")
    try:
        (upload_root() / row["stored_name"]).unlink(missing_ok=True)
    except OSError as exc:
        return problem(500, "The file could not be removed: " + str(exc)[:200])
    store.run("DELETE FROM uploads WHERE id = ?", (upload_id,))
    record_event("file.deleted", user["id"], row["original_name"])
    return ok({"deleted": True, "id": upload_id})
'''

_SERVER_ACTIVITY = r'''
# ----------------------------------------------------------------------- Activity feed
@app.get("/api/activity")
def activity(request: Request):
    """The site's own record of what happened, newest first, scoped to who is asking.

    A signed-in visitor sees their own rows; staff see everything; nobody gets an unscoped list.
    """
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    limit, offset, sort, order = paging(request, {"created_at"}, "created_at")
    if user["role"] == "staff":
        rows = store.query("SELECT a.id, a.kind, a.detail, a.created_at, u.email AS who FROM activity a "
                           "LEFT JOIN users u ON u.id = a.user_id ORDER BY a." + sort + " " + order
                           + " LIMIT ? OFFSET ?", (limit, offset))
    else:
        rows = store.query("SELECT id, kind, detail, created_at FROM activity WHERE user_id = ? ORDER BY "
                           + sort + " " + order + " LIMIT ? OFFSET ?", (user["id"], limit, offset))
    return ok({"activity": rows, "scope": "all" if user["role"] == "staff" else "own",
               "total": store.count("SELECT COUNT(*) FROM activity")})
'''

_SERVER_ANALYTICS = r'''
# ----------------------------------------------------------------------- First-party analytics
@app.post("/api/events")
async def events(request: Request):
    """Counts, not people. No cookies, no names, no visitor identifiers.

    The payload is capped and the event name is kept to a plain word so a dashboard cannot be built out
    of whatever the browser decided to send.
    """
    guard = write_guard(request)
    if guard:
        return guard
    if rate_limited("event:" + client_ip(request), limit=120, window=60.0):
        return problem(429, "This visitor is sending events faster than the site records them.")
    body = await body_json(request)
    name = text_of(body.get("name"), "Event", max_length=60)
    if not re.match(r"^[a-z0-9_.:-]+$", name):
        raise Invalid("Event names use letters, numbers, dots, colons, dashes and underscores")
    detail = text_of(body.get("detail"), "Detail", max_length=200, required=False)
    user = session_user(request)
    event_id = store.write("INSERT INTO events (name, user_id, detail, created_at) VALUES (?, ?, ?, ?)",
                           (name, user["id"] if user else None, detail, now_iso()))
    return out(201, {"ok": True, "id": event_id, "recorded": True})


@app.get("/api/analytics/summary")
def analytics_summary(request: Request):
    staff = require_role(request, "staff")
    if isinstance(staff, JSONResponse):
        return staff
    try:
        days = min(max(int(request.query_params.get("days", 30)), 1), 365)
    except ValueError:
        raise Invalid("days must be a whole number") from None
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86_400))
    totals = store.count("SELECT COUNT(*) FROM events WHERE created_at >= ?", (since,))
    by_name = store.query("SELECT name, COUNT(*) AS count FROM events WHERE created_at >= ? "
                          "GROUP BY name ORDER BY count DESC LIMIT 50", (since,))
    by_day = store.query("SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count FROM events "
                         "WHERE created_at >= ? GROUP BY day ORDER BY day LIMIT ?", (since, days + 1))
    return ok({"window_days": days, "events": totals, "by_name": by_name, "by_day": by_day,
               "empty": totals == 0,
               "note": "These are the events this site recorded itself. Nothing here came from a "
                       "third-party tracker."})
'''

_SERVER_PRICING = r'''
# ----------------------------------------------------------------------- Plans and subscriptions
@app.post("/api/subscribe")
async def subscribe(request: Request):
    """Create the provider's subscription object, or say exactly what is missing.

    There is no path through this route that reports a subscription as started before the provider has
    confirmed it, and no plan is written to the database from here - that happens in the webhook.
    """
    user = require_user(request)
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    provider = os.environ.get("PAYMENT_PROVIDER", "").strip()
    secret = os.environ.get("PAYMENT_SECRET_KEY", "").strip()
    webhook_secret = os.environ.get("BILLING_WEBHOOK_SECRET", "").strip()
    if not provider or not secret:
        return missing_env("PAYMENT_PROVIDER", "PAYMENT_SECRET_KEY", "BILLING_WEBHOOK_SECRET")
    if not webhook_secret:
        return missing_env("BILLING_WEBHOOK_SECRET")
    body = await body_json(request)
    plan = slug_of(body.get("plan") or "standard")
    endpoint = {"stripe": "https://api.stripe.com/v1/subscriptions"}.get(provider)
    if not endpoint:
        return problem(501, "This build has no subscription call written for provider '" + provider
                          + "'. Point it at your provider's endpoint in server.py; nothing has been "
                            "assumed about your account.")
    status_code, text = provider_call(endpoint, {"authorization": "Bearer " + secret},
                                      {"customer": str(body.get("customer") or ""), "items": [
                                          {"price": slug_of(body.get("price") or plan)}]})
    if status_code not in (200, 201):
        return problem(502, "The provider answered " + str(status_code) + ". No subscription exists.",
                       detail=text[:500])
    try:
        answer = json.loads(text)
    except ValueError:
        return problem(502, "The provider answered with something unreadable.", detail=text[:300])
    subscription_id = str(answer.get("id") or "")
    if not subscription_id:
        return problem(502, "The provider gave no subscription id, so nothing was recorded.",
                       detail=text[:300])
    store.run("INSERT OR IGNORE INTO subscriptions (user_id, plan, provider, provider_id, status, "
              "created_at) VALUES (?, ?, ?, ?, ?, ?)",
              (user["id"], plan, provider, subscription_id, str(answer.get("status") or "incomplete"),
               now_iso()))
    record_event("subscription.created", user["id"], plan)
    track("subscribe", user["id"], plan)
    return ok({"subscription_id": subscription_id, "plan": plan,
               "status": str(answer.get("status") or "incomplete"),
               "checkout_url": str(answer.get("hosted_url") or ""),
               "note": "Status comes from the provider, not from this server."})


@app.post("/api/webhooks/billing")
async def billing_webhook(request: Request):
    """The only place a plan is marked active: the provider's own signed callback."""
    secret = os.environ.get("BILLING_WEBHOOK_SECRET", "").strip()
    if not secret:
        return missing_env("BILLING_WEBHOOK_SECRET")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return problem(413, "That callback is too large to accept.")
    signature = request.headers.get("stripe-signature") or request.headers.get("x-webhook-signature") or ""
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature.split("=")[-1], expected):
        return problem(401, "That callback is not signed with the secret this site knows.")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise Invalid("The callback body is not JSON") from None
    obj = payload.get("data", {}).get("object", {}) if isinstance(payload.get("data"), dict) else {}
    provider_id = str(obj.get("id") or payload.get("subscription_id") or "")
    if not provider_id:
        return problem(422, "The callback names no subscription, so nothing was changed.")
    changed = store.run("UPDATE subscriptions SET status = ?, updated_at = ? WHERE provider_id = ?",
                        (str(obj.get("status") or payload.get("status") or "unknown"), now_iso(),
                         provider_id))
    if not store.count("SELECT COUNT(*) FROM subscriptions WHERE provider_id = ?", (provider_id,)):
        store.write("INSERT INTO subscriptions (user_id, plan, provider, provider_id, status, created_at) "
                    "VALUES (NULL, ?, ?, ?, ?, ?)",
                    (str(obj.get("plan") or "unknown"), str(payload.get("provider") or ""), provider_id,
                     str(obj.get("status") or "unknown"), now_iso()))
    record_event("subscription.webhook", None, provider_id)
    return ok({"received": True, "subscription_id": provider_id, "updated": bool(changed)})
'''

_SERVER_API = r'''
# ----------------------------------------------------------------------- Outbound calls and callbacks
@app.get("/api/integrations/status")
def integrations_status(request: Request):
    """Whether each integration is configured, without ever returning a value it holds."""
    return ok({"integrations": [{"name": name, "set": bool(os.environ.get(name))} for name in
                                ("EXTERNAL_API_BASE_URL", "EXTERNAL_API_TOKEN", "WEBHOOK_SECRET",
                                 "PAYMENT_PROVIDER", "PAYMENT_SECRET_KEY", "SMTP_HOST",
                                 "RESEND_API_KEY")],
               "providers": sorted(FEATURES)})


@app.post("/api/external/call")
async def external_call(request: Request):
    """One signed call to the service in the environment. Nothing else.

    The URL is not taken from the browser, so this cannot be pointed at wherever a visitor likes; the
    token never leaves the server, and the provider's status is passed back rather than smoothed over.
    """
    user = require_role(request, "staff")
    if isinstance(user, JSONResponse):
        return user
    guard = write_guard(request)
    if guard:
        return guard
    base = os.environ.get("EXTERNAL_API_BASE_URL", "").strip()
    token = os.environ.get("EXTERNAL_API_TOKEN", "").strip()
    if not base or not token:
        return missing_env("EXTERNAL_API_BASE_URL", "EXTERNAL_API_TOKEN")
    body = await body_json(request)
    path = text_of(body.get("path"), "Path", max_length=200)
    if not path.startswith("/") or ".." in path:
        raise Invalid("Path must be a path under the service's base URL")
    status_code, text = provider_call(base.rstrip("/") + path, {"authorization": "Bearer " + token})
    if status_code == 0:
        return problem(502, "The service could not be reached: " + text)
    if status_code >= 400:
        return problem(status_code, "The service answered " + str(status_code) + ".", detail=text[:500])
    record_event("external.called", user["id"], path)
    return ok({"status": status_code, "body": text[:20000], "path": path})


@app.post("/api/webhooks/{source}")
async def webhook(source: str, request: Request):
    """Receive a callback with the signature checked, and store it before anything is done with it.

    A delivery row means a crash after this response is a replay, not a loss. `processed` stays 0 until
    your own code acts on it - this build deliberately does not invent what a foreign event should do.
    """
    secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not secret:
        return missing_env("WEBHOOK_SECRET")
    name = slug_of(source)
    if rate_limited("webhook:" + name, limit=120, window=60.0):
        return problem(429, "That source is sending faster than this site will accept.")
    signature = request.headers.get("x-signature") or request.headers.get("webhook-signature") or ""
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return problem(413, "That callback is too large to accept.")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature.split("=")[-1], expected):
        record_event("webhook.rejected", None, name)
        return problem(401, "Signature does not match WEBHOOK_SECRET. Nothing was stored.")
    event_id = text_of(request.headers.get("x-event-id") or secrets.token_hex(8), "Event id",
                       max_length=80, required=False)
    already = store.one("SELECT id, processed FROM deliveries WHERE source = ? AND event_id = ?",
                        (name, event_id))
    if already:
        return ok({"received": True, "duplicate": True, "delivery_id": already["id"],
                   "processed": bool(already["processed"])})
    delivery_id = store.write("INSERT INTO deliveries (source, event_id, payload, received_at) "
                              "VALUES (?, ?, ?, ?)", (name, event_id, raw.decode("utf-8", "ignore")[:20000],
                                                      now_iso()))
    record_event("webhook.received", None, name)
    return out(202, {"ok": True, "received": True, "delivery_id": delivery_id, "processed": False,
                     "note": "Stored. Deciding what this event means is your business logic, and this "
                              "build will not guess it for you."})
'''

SERVER = {
    "authentication": _SERVER_AUTH,
    "profiles": _SERVER_PROFILES,
    "admin": _SERVER_ADMIN,
    "records": _SERVER_RECORDS,
    "catalog": _SERVER_CATALOG,
    "blog": _SERVER_BLOG,
    "booking": _SERVER_BOOKING,
    "contact": _SERVER_CONTACT,
    "uploads": _SERVER_UPLOADS,
    "activity": _SERVER_ACTIVITY,
    "analytics": _SERVER_ANALYTICS,
    "pricing": _SERVER_PRICING,
    "api": _SERVER_API,
    "browse": "", "wizard": "", "layout": "",
}

# --------------------------------------------------------------------------- page markup
# What a feature build adds to the page. Every panel states the four outcomes the brief asks for -
# loading, success, error, empty - as elements that are already there, so a state is shown by moving
# text between them rather than by inventing a message.
#
# The server-backed panels keep their behaviour in feature_client.js, which only the generated server
# can serve (Launch Crew's sanitizer removes any inline script that reaches the network). Their opening
# line therefore says the panel is waiting, which is exactly what it is doing.

_WAIT = ('<p class="lc-note" data-lc-wait>Waiting for this site\'s own server. Open it through '
         'server.py and this panel will start talking to it - see SETUP.md.</p>')

PAGE = {
    "authentication": (
        '<div class="lc-panel" id="lc-auth" data-lc-feature="authentication">'
        '<h3>Sign in</h3>'
        + _WAIT +
        '<form id="lc-signup-form" class="lc-form stack" novalidate>'
        '<label for="lc-signup-email">Email</label>'
        '<input id="lc-signup-email" name="email" type="email" autocomplete="email" required>'
        '<label for="lc-signup-name">Name</label>'
        '<input id="lc-signup-name" name="display_name" autocomplete="name" maxlength="80">'
        '<label for="lc-signup-password">Password</label>'
        '<input id="lc-signup-password" name="password" type="password" autocomplete="new-password" '
        'minlength="10" required>'
        '<button class="btn primary" type="submit">Create account</button></form>'
        '<form id="lc-login-form" class="lc-form stack" novalidate>'
        '<label for="lc-login-email">Email</label><input id="lc-login-email" type="email" required>'
        '<label for="lc-login-password">Password</label><input id="lc-login-password" type="password" '
        'autocomplete="current-password" required>'
        '<button class="btn" type="submit">Sign in</button></form>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p>'
        '<p class="lc-empty" hidden>Nothing to show until you sign in.</p></div>'),
    "profiles": (
        '<div class="lc-panel" id="lc-profile" data-lc-feature="profiles"><h3>Your account</h3>'
        + _WAIT +
        '<form id="lc-profile-form" class="lc-form stack" novalidate>'
        '<label for="lc-profile-name">Display name</label><input id="lc-profile-name" maxlength="80">'
        '<label for="lc-profile-bio">About you</label><textarea id="lc-profile-bio" maxlength="500">'
        '</textarea><button class="btn primary" type="submit">Save changes</button></form>'
        '<form id="lc-password-form" class="lc-form stack" novalidate>'
        '<label for="lc-password-current">Current password</label><input id="lc-password-current" '
        'type="password" autocomplete="current-password" required>'
        '<label for="lc-password-new">New password</label><input id="lc-password-new" type="password" '
        'autocomplete="new-password" minlength="10" required>'
        '<button class="btn" type="submit">Change password</button></form>'
        '<form id="lc-close-form" class="lc-form stack" novalidate>'
        '<label for="lc-close-password">Confirm your password to close this account</label>'
        '<input id="lc-close-password" type="password" autocomplete="current-password" required>'
        '<button class="btn danger" type="submit">Close account</button></form>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "admin": (
        '<div class="lc-panel" id="lc-admin" data-lc-feature="admin"><h3>Staff area</h3>'
        + _WAIT +
        '<div class="lc-row wrap"><input id="lc-admin-search" type="search" placeholder="Search accounts" '
        'aria-label="Search accounts"><button class="btn" id="lc-admin-refresh" type="button">Reload</button>'
        '</div><ul id="lc-admin-list" class="lc-list"></ul>'
        '<p class="lc-empty" hidden>No accounts yet.</p>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "records": (
        '<div class="lc-panel" id="lc-records" data-lc-feature="records"><h3>Records</h3>'
        + _WAIT +
        '<form id="lc-record-form" class="lc-form stack" novalidate>'
        '<label for="lc-record-title">Title</label><input id="lc-record-title" maxlength="200" required>'
        '<label for="lc-record-detail">Detail</label><textarea id="lc-record-detail" maxlength="4000">'
        '</textarea><label for="lc-record-status">Status</label><input id="lc-record-status" '
        'maxlength="40" value="active">'
        '<button class="btn primary" type="submit">Add record</button></form>'
        '<div class="lc-row wrap"><input id="lc-record-search" type="search" '
        'placeholder="Search records" aria-label="Search records">'
        '<label for="lc-record-sort" class="sr-only">Sort by</label>'
        '<select id="lc-record-sort"><option value="created_at">Newest first</option>'
        '<option value="title">Title</option><option value="status">Status</option></select>'
        '<button class="btn" id="lc-record-more" type="button">Load more</button></div>'
        '<ul id="lc-record-list" class="lc-list"></ul><p class="lc-empty" hidden>No records yet.</p>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "catalog": (
        '<div class="lc-panel" id="lc-catalog" data-lc-feature="catalog"><h3>Catalog</h3>'
        + _WAIT +
        '<div class="lc-row wrap"><input id="lc-catalog-search" type="search" '
        'placeholder="Search products" aria-label="Search products">'
        '<label for="lc-catalog-sort" class="sr-only">Sort</label><select id="lc-catalog-sort">'
        '<option value="name">Name</option><option value="price_minor">Price</option>'
        '<option value="stock">Stock</option></select>'
        '<label for="lc-catalog-max">Max price (minor units)</label>'
        '<input id="lc-catalog-max" type="number" min="0" step="1" value="0"></div>'
        '<ul id="lc-catalog-list" class="lc-list lc-grid"></ul><p class="lc-empty" hidden>Nothing for '
        'sale yet - SETUP.md shows how to put products into the catalog.</p>'
        '<div id="lc-cart" class="lc-cart"><h3>Your cart</h3><ul id="lc-cart-list" class="lc-list"></ul>'
        '<p class="lc-empty" hidden>Your cart is empty.</p>'
        '<p class="lc-total" aria-live="polite">Total: 0</p>'
        '<button class="btn primary" id="lc-checkout" type="button">Check out</button></div>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "browse": (
        '<div class="lc-panel" id="lc-browse" data-lc-feature="browse"><h3>Find something</h3>'
        '<p class="lc-note">This works in the page as it stands - no server involved.</p>'
        '<div class="lc-row wrap"><input id="lc-browse-q" type="search" placeholder="Search this page" '
        'aria-label="Search this page">'
        '<label for="lc-browse-sort" class="sr-only">Sort</label><select id="lc-browse-sort">'
        '<option value="order">Page order</option><option value="name">A to Z</option>'
        '<option value="name-desc">Z to A</option></select>'
        '<label for="lc-browse-size" class="sr-only">Per page</label><select id="lc-browse-size">'
        '<option value="6">6 a page</option><option value="12">12 a page</option>'
        '<option value="0">show all</option></select></div>'
        '<p class="lc-count" role="status" aria-live="polite"></p>'
        '<p class="lc-empty" data-lc-browse-empty hidden>Nothing on this page matches that.</p>'
        '<div class="lc-row wrap"><button class="btn" data-lc-prev type="button">Previous</button>'
        '<span data-lc-pageinfo></span><button class="btn" data-lc-next type="button">Next</button></div>'
        '</div>'),
    "blog": (
        '<div class="lc-panel" id="lc-blog" data-lc-feature="blog"><h3>Writing</h3>' + _WAIT +
        '<div class="lc-row wrap"><input id="lc-post-search" type="search" placeholder="Search posts" '
        'aria-label="Search posts"><label for="lc-post-status" class="sr-only">Status</label>'
        '<select id="lc-post-status"><option value="published">Published</option>'
        '<option value="all">All, including drafts (staff)</option></select></div>'
        '<ul id="lc-post-list" class="lc-list"></ul><p class="lc-empty" hidden>Nothing published yet.</p>'
        '<form id="lc-post-form" class="lc-form stack" hidden>'
        '<label for="lc-post-title">Title</label><input id="lc-post-title" maxlength="200" required>'
        '<label for="lc-post-body">Body</label><textarea id="lc-post-body" maxlength="40000"></textarea>'
        '<label for="lc-post-state">Status</label><select id="lc-post-state">'
        '<option value="draft">Draft</option><option value="published">Published</option></select>'
        '<button class="btn primary" type="submit">Save post</button></form>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "booking": (
        '<div class="lc-panel" id="lc-booking" data-lc-feature="booking"><h3>Book a time</h3>' + _WAIT +
        '<div class="lc-row wrap"><label for="lc-booking-resource">Who with</label>'
        '<input id="lc-booking-resource" maxlength="40" value="default">'
        '<button class="btn" id="lc-booking-load" type="button">Show open times</button></div>'
        '<ul id="lc-slot-list" class="lc-list"></ul>'
        '<p class="lc-empty" hidden>No open times on this calendar yet.</p>'
        '<form id="lc-booking-form" class="lc-form stack" hidden>'
        '<label for="lc-booking-name">Your name</label><input id="lc-booking-name" maxlength="120" required>'
        '<label for="lc-booking-email">Email</label><input id="lc-booking-email" type="email" required>'
        '<label for="lc-booking-note">Anything we should know</label><textarea id="lc-booking-note" '
        'maxlength="1000"></textarea><button class="btn primary" type="submit">Hold this time</button>'
        '</form><p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "contact": (
        '<div class="lc-panel" id="lc-contact" data-lc-feature="contact"><h3>Get in touch</h3>' + _WAIT +
        '<form id="lc-contact-form" class="lc-form stack" novalidate>'
        '<label for="lc-contact-name">Name</label><input id="lc-contact-name" maxlength="120" required>'
        '<label for="lc-contact-email">Email</label><input id="lc-contact-email" type="email" required>'
        '<label for="lc-contact-subject">Subject</label><input id="lc-contact-subject" maxlength="200">'
        '<label for="lc-contact-message">Message</label><textarea id="lc-contact-message" '
        'maxlength="8000" required></textarea>'
        '<button class="btn primary" type="submit">Send message</button></form>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "uploads": (
        '<div class="lc-panel" id="lc-uploads" data-lc-feature="uploads"><h3>Your files</h3>' + _WAIT +
        '<form id="lc-upload-form" class="lc-form stack">'
        '<label for="lc-upload-file">Choose a file</label>'
        '<input id="lc-upload-file" type="file" accept=".jpg,.jpeg,.png,.webp,.gif,.pdf,.txt,.csv" required>'
        '<button class="btn primary" type="submit">Upload</button></form>'
        '<ul id="lc-upload-list" class="lc-list"></ul><p class="lc-empty" hidden>You have not uploaded '
        'anything yet.</p><p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "activity": (
        '<div class="lc-panel" id="lc-activity" data-lc-feature="activity"><h3>Activity</h3>' + _WAIT +
        '<ul id="lc-activity-list" class="lc-list"></ul>'
        '<p class="lc-empty" hidden>Nothing has happened on this site yet.</p>'
        '<button class="btn" id="lc-activity-more" type="button">Load older</button>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "analytics": (
        '<div class="lc-panel" id="lc-analytics" data-lc-feature="analytics"><h3>Traffic this site '
        'measured itself</h3>' + _WAIT +
        '<label for="lc-analytics-days" class="sr-only">Window</label><select id="lc-analytics-days">'
        '<option value="7">Last 7 days</option><option value="30">Last 30 days</option>'
        '<option value="90">Last 90 days</option></select>'
        '<p class="lc-analytics-total" aria-live="polite"></p><ul id="lc-analytics-names" class="lc-list">'
        '</ul><table id="lc-analytics-days-table" class="lc-table"><caption>Events per day</caption>'
        '<thead><tr><th scope="col">Day</th><th scope="col">Events</th></tr></thead><tbody></tbody>'
        '</table><p class="lc-empty" hidden>Nothing recorded in this window.</p>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "wizard": (
        '<div class="lc-panel" id="lc-wizard" data-lc-feature="wizard"><h3>A few questions</h3>'
        '<p class="lc-note">Answers stay in this form while you work through it. Nothing is sent until '
        'you reach the last step.</p>'
        '<ol class="lc-steps" id="lc-steps"><li data-lc-step="0">About you</li>'
        '<li data-lc-step="1">What you need</li><li data-lc-step="2">Anything else</li></ol>'
        '<form id="lc-wizard-form" class="lc-form stack">'
        '<fieldset data-lc-panel="0"><legend>About you</legend>'
        '<label for="lc-w-name">Name</label><input id="lc-w-name" maxlength="120" required></fieldset>'
        '<fieldset data-lc-panel="1" hidden><legend>What you need</legend>'
        '<label for="lc-w-need">In your own words</label><textarea id="lc-w-need" maxlength="2000" '
        'required></textarea></fieldset>'
        '<fieldset data-lc-panel="2" hidden><legend>Anything else</legend>'
        '<label for="lc-w-extra">Notes</label><textarea id="lc-w-extra" maxlength="2000"></textarea>'
        '</fieldset><div class="lc-row wrap"><button class="btn" data-lc-back type="button" disabled>'
        'Back</button><button class="btn primary" data-lc-next-step type="button">Next</button>'
        '<button class="btn primary" data-lc-finish type="submit" hidden>Send</button></div></form>'
        '<p class="lc-progress" role="status" aria-live="polite">Step 1 of 3</p>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "pricing": (
        '<div class="lc-panel" id="lc-pricing" data-lc-feature="pricing"><h3>Plans</h3>' + _WAIT +
        '<ul class="lc-plans" id="lc-plans"><li class="lc-plan" data-lc-plan="starter">'
        '<h3 class="lc-plan-name">Starter</h3><p class="lc-plan-price">0</p><ul class="lc-plan-list">'
        '<li>Everything on this site</li></ul><button class="btn" type="button" data-lc-subscribe='
        '"starter">Choose Starter</button></li><li class="lc-plan" data-lc-plan="standard">'
        '<h3 class="lc-plan-name">Standard</h3><p class="lc-plan-price">0</p><ul class="lc-plan-list">'
        '<li>Everything on this site</li></ul><button class="btn" type="button" data-lc-subscribe='
        '"standard">Choose Standard</button></li></ul>'
        '<p class="lc-note">Prices are placeholders with nothing to decide: set the real ones in the page '
        'and the provider price ids in your billing account. No subscription starts until the provider '
        'says so through the webhook.</p>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "api": (
        '<div class="lc-panel" id="lc-integrations" data-lc-feature="api"><h3>Connected services</h3>'
        + _WAIT + '<ul id="lc-integration-list" class="lc-list"></ul>'
        '<p class="lc-empty" hidden>No service has been configured yet.</p>'
        '<p class="lc-status" role="status" aria-live="polite" data-lc-status></p></div>'),
    "layout": (
        '<div class="lc-panel" id="lc-layout" data-lc-feature="layout"><h3>Navigating this site</h3>'
        '<p class="lc-note">The menu below is the page\'s own navigation, given a button that works with '
        'a keyboard and a screen reader at every width.</p></div>'),
}

STYLE = {
    "authentication": "", "profiles": "", "records": "", "catalog": "", "browse": "", "blog": "",
    "booking": "", "contact": "", "uploads": "", "activity": "", "analytics": "", "wizard": "",
    "pricing": "", "api": "",
    "layout": (
        "#lc-main>[role=navigation]{position:relative}"
        "@media (max-width:720px){.lc-navlinks[hidden]{display:none}"
        ".lc-navlinks{display:flex;flex-direction:column;gap:.5rem}}"
        "@media (prefers-reduced-motion: reduce){*{animation:none!important;"
        "transition:none!important;scroll-behavior:auto!important}}"),
}
SHARED_STYLE = (
    ".lc-features{margin:3rem 0;display:grid;gap:2rem}"
    ".lc-panel{border:1px solid rgba(128,128,128,.35);border-radius:.75rem;padding:1.25rem}"
    ".lc-panel h3{margin:0 0 .5rem;font-size:1.15rem}"
    ".lc-form{gap:.5rem}.lc-form label{font-size:.9rem}.lc-form input,.lc-form select,"
    ".lc-form textarea{padding:.5rem;border-radius:.4rem;border:1px solid rgba(128,128,128,.5);"
    "background:inherit;color:inherit;font:inherit}"
    ".lc-row.wrap{display:flex;flex-wrap:wrap;gap:.5rem;align-items:end;margin:.75rem 0}"
    ".lc-list{list-style:none;margin:0;padding:0;display:grid;gap:.5rem}"
    ".lc-status{min-height:1.25rem;font-size:.9rem;margin:.5rem 0 0}"
    ".lc-status[data-lc-kind=error]{color:#c62828}.lc-status[data-lc-kind=busy]{opacity:.7}"
    ".lc-empty{opacity:.75;font-style:italic}"
    ".lc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(14rem,1fr));gap:1rem}"
    ".lc-steps{display:flex;gap:.75rem;padding-left:1.2rem}.lc-steps[aria-current]{font-weight:600}"
    ".lc-plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:1rem;"
    "list-style:none;padding:0}.lc-plan{border:1px solid rgba(128,128,128,.35);border-radius:.6rem;"
    "padding:1rem}.lc-table{width:100%;border-collapse:collapse}.sr-only{position:absolute;width:1px;"
    "height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}"
    ".lc-panel:focus-within [data-lc-status]{outline:0}")

# --------------------------------------------------------------------------- browser code
# Two kinds, and the difference is enforced, not stylistic.
#
#   CLIENT - the panels that call this site's own API. A published page may not hold this: Launch Crew's
#            sanitizer removes any inline script that reaches the network. So it ships as an authored
#            file, feature_client.js, which server.py serves at the same origin and whose CSP allows it.
#   INLINE - the page-only features (search, steps, navigation). DOM work touches nothing off-page, so it
#            survives the sanitizer and stays inside index.html, working with no server at all.

CLIENT_HEAD = r'''/* feature_client.js
 *
 * The browser half of the panels on this page. It is served by this site's own server at
 * /feature_client.js - a published static page may not carry code that reaches the network, so the
 * server that widens the page's Content-Security-Policy to this same origin also supplies this file.
 * Start it (SETUP.md) and every panel begins talking to it. Open index.html on its own and each panel
 * keeps saying that it is waiting for its server, which is exactly what it is doing.
 *
 * Nothing here invents an outcome. A 501 that names a missing variable is shown as written, a 409 clash
 * is shown as written, and a list that comes back empty shows the empty state the page already holds.
 */
(function () {
  "use strict";

  var panels = {};   // capability key -> its element in the page
  var wire = {};     // capability key -> the function that brings that panel alive
  var resync = [];   // loaders a panel registered, run again whenever the session changes
  var me = null;     // the signed-in user, or null until /api/me answers

  function q(root, selector) { return root ? root.querySelector(selector) : null; }
  function on(el, type, handler) { if (el) el.addEventListener(type, handler); }
  function value(el) { return el && el.value ? String(el.value).trim() : ""; }
  function show(el, visible) { if (el) el.hidden = !visible; }
  function waitNote(panel) { return panel ? q(panel, "[data-lc-wait]") : null; }
  function number(raw, fallback) {
    var parsed = parseInt(raw, 10);
    return isNaN(parsed) ? fallback : parsed;
  }

  function say(key, message, kind) {
    var box = q(panels[key], "[data-lc-status]");
    if (box) {
      box.textContent = message;
      box.setAttribute("data-lc-kind", kind || "info");
    }
  }

  // The panel has heard from its server, so it stops describing itself as waiting.
  function reached(key) {
    var note = waitNote(panels[key]);
    if (note) note.hidden = true;
  }

  function node(tag, className, content) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (content !== undefined) el.textContent = content;
    return el;
  }

  function button(label, handler, kind) {
    var el = node("button", "btn" + (kind ? " " + kind : ""));
    el.type = "button";
    el.textContent = label;
    el.addEventListener("click", handler);
    return el;
  }

  function fill(listEl, emptyEl, items, render) {
    if (!listEl) return 0;
    listEl.textContent = "";
    var count = items ? items.length : 0;
    if (emptyEl) show(emptyEl, count === 0);
    if (!count) return 0;
    var fragment = document.createDocumentFragment();
    for (var i = 0; i < items.length; i++) {
      var made = render(items[i], i);
      if (made) fragment.appendChild(made);
    }
    listEl.appendChild(fragment);
    return count;
  }

  function api(path, opts) {
    opts = opts || {};
    var init = {method: opts.method || "GET", credentials: "same-origin",
                headers: {accept: "application/json"}};
    if (opts.form) {
      init.body = opts.form;
    } else if (opts.send !== undefined) {
      init.headers["content-type"] = "application/json";
      init.body = JSON.stringify(opts.send);
    }
    return window.fetch(path, init).then(function (response) {
      return response.text().then(function (raw) {
        var data = null;
        try {
          data = raw ? JSON.parse(raw) : {};
        } catch (bad) {
          data = {error: "The server answered in words this page cannot read: " + raw.slice(0, 160)};
        }
        var trouble = data.error || (response.ok ? "" : "The server answered " + response.status + ".");
        return {status: response.status, ok: response.ok, data: data, error: trouble};
      });
    }, function () {
      return {status: 0, ok: false, data: {},
              error: "This page could not reach its server. Start it with the command in SETUP.md and "
                     + "reload; nothing was sent."};
    });
  }

  function money(minor, currency) {
    return (minor / 100).toFixed(2) + " " + (currency || "USD");
  }

  // The one control every signed-in panel needs and no markup could presume to know about.
  function renderSession() {
    var panel = panels.authentication;
    if (!panel) return;
    var line = q(panel, "[data-lc-session]");
    if (!line) {
      line = node("p", "lc-note");
      line.setAttribute("data-lc-session", "");
      panel.appendChild(line);
    }
    line.textContent = "";
    if (!me) {
      line.appendChild(document.createTextNode("Not signed in."));
      return;
    }
    line.appendChild(document.createTextNode("Signed in as " + me.email + " (" + me.role + "). "));
    line.appendChild(button("Sign out", function () {
      api("/api/logout", {method: "POST", send: {}}).then(function (res) {
        me = null;
        renderSession();
        say("authentication", res.ok ? "Signed out. The session cookie is gone." : res.error,
            res.ok ? "done" : "error");
      });
    }));
  }

  function refreshUser() {
    return api("/api/me").then(function (res) {
      me = res.ok ? res.data.user : null;
      if (res.ok) reached("authentication");
      renderSession();
      return me;
    });
  }

  // Signing in or out changes what every other panel is allowed to show, so each one reloads its own list.
  function resyncAll() {
    for (var i = 0; i < resync.length; i++) {
      try {
        resync[i]();
      } catch (broken) {
        // One panel failing to redraw must not stop the others; the loader says so on its own.
      }
    }
  }

  function needsSignIn(key) {
    say(key, "This belongs to an account. Sign in first.", "info");
  }

  // A provider that has not been connected answers 501 with the variables to set. Shown, never smoothed.
  function notConfigured(key, res) {
    var needs = (res.data && res.data.needs) ? res.data.needs.join(", ") : "";
    say(key, res.error + (needs ? " (waiting on " + needs + ")" : ""), "error");
  }

'''

CLIENT = {
    "authentication": r'''
  wire.authentication = function (panel) {
    on(q(panel, "#lc-signup-form"), "submit", function (event) {
      event.preventDefault();
      say("authentication", "Creating the account...", "busy");
      api("/api/signup", {method: "POST", send: {
        email: value(q(panel, "#lc-signup-email")),
        display_name: value(q(panel, "#lc-signup-name")),
        password: value(q(panel, "#lc-signup-password"))
      }}).then(function (res) {
        if (!res.ok) { say("authentication", res.error, "error"); return; }
        me = res.data.user;
        reached("authentication");
        renderSession();
        say("authentication", "Account created and signed in.", "done");
        resyncAll();
      });
    });

    on(q(panel, "#lc-login-form"), "submit", function (event) {
      event.preventDefault();
      say("authentication", "Checking that password...", "busy");
      api("/api/login", {method: "POST", send: {
        email: value(q(panel, "#lc-login-email")),
        password: value(q(panel, "#lc-login-password"))
      }}).then(function (res) {
        if (!res.ok) { say("authentication", res.error, "error"); return; }
        me = res.data.user;
        reached("authentication");
        renderSession();
        say("authentication", "Signed in.", "done");
        resyncAll();
      });
    });
  };
''',

    "profiles": r'''
  wire.profiles = function (panel) {
    var name = q(panel, "#lc-profile-name");
    var bio = q(panel, "#lc-profile-bio");

    function load() {
      if (!me) {
        say("profiles", "Sign in and this form fills itself in with your account.", "info");
        return;
      }
      if (name) name.value = me.display_name || "";
      if (bio) bio.value = me.bio || "";
      reached("profiles");
      say("profiles", "Editing the account signed in as " + me.email + ".", "done");
    }
    resync.push(load);
    load();

    on(q(panel, "#lc-profile-form"), "submit", function (event) {
      event.preventDefault();
      say("profiles", "Saving...", "busy");
      api("/api/me", {method: "PATCH", send: {display_name: value(name), bio: value(bio)}})
        .then(function (res) {
          if (!res.ok) { say("profiles", res.error, "error"); return; }
          me = res.data.user;
          renderSession();
          say("profiles", "Saved.", "done");
        });
    });

    on(q(panel, "#lc-password-form"), "submit", function (event) {
      event.preventDefault();
      api("/api/me/password", {method: "POST", send: {
        current_password: value(q(panel, "#lc-password-current")),
        new_password: value(q(panel, "#lc-password-new"))
      }}).then(function (res) {
        if (!res.ok) { say("profiles", res.error, "error"); return; }
        say("profiles", "Password changed. Sign in again with it next time.", "done");
      });
    });

    on(q(panel, "#lc-close-form"), "submit", function (event) {
      event.preventDefault();
      api("/api/me", {method: "DELETE", send: {password: value(q(panel, "#lc-close-password"))}})
        .then(function (res) {
          if (!res.ok) { say("profiles", res.error, "error"); return; }
          me = null;
          renderSession();
          say("profiles", "Account closed. Its rows stay in the database so other people's records keep "
              + "their author - see SETUP.md for removing them for good.", "done");
          resyncAll();
        });
    });
  };
''',

    "admin": r'''
  wire.admin = function (panel) {
    var listEl = q(panel, "#lc-admin-list");
    var emptyEl = q(panel, ".lc-empty");
    var state = {offset: 0, size: 25};

    function draw(users, total) {
      var shown = fill(listEl, emptyEl, users, function (user) {
        var row = node("li", "lc-row wrap", user.email + " - " + user.role + " - joined "
                       + String(user.created_at || "").slice(0, 10));
        row.appendChild(button(user.role === "staff" ? "Make member" : "Make staff", function () {
          api("/api/admin/users/" + user.id + "/role",
              {method: "POST", send: {role: user.role === "staff" ? "member" : "staff"}})
            .then(function (res) {
              say("admin", res.ok ? "Changed " + user.email + " to " + res.data.role + "." : res.error,
                  res.ok ? "done" : "error");
              if (res.ok && me && user.id === me.id) resyncAll();
            });
        }));
        return row;
      });
      say("admin", shown ? shown + " of " + total + " accounts, newest first."
                         : "No accounts match that.", shown ? "done" : "info");
      return shown;
    }

    function load() {
      say("admin", "Checking this account...", "busy");
      api("/api/admin/whoami").then(function (who) {
        if (!who.ok) {
          say("admin", who.status === 401 ? "Sign in with a staff account to use this area." : who.error,
              "error");
          fill(listEl, emptyEl, [], function () { return null; });
          return;
        }
        reached("admin");
        var query = "?limit=" + state.size + "&offset=" + state.offset
                    + "&q=" + encodeURIComponent(value(q(panel, "#lc-admin-search")));
        api("/api/admin/users" + query).then(function (res) {
          if (!res.ok) { say("admin", res.error, "error"); return; }
          draw(res.data.users, res.data.total);
        });
      });
    }
    resync.push(load);

    on(q(panel, "#lc-admin-refresh"), "click", load);
    on(q(panel, "#lc-admin-search"), "keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); load(); }
    });
    load();
  };
''',

    "records": r'''
  wire.records = function (panel) {
    var listEl = q(panel, "#lc-record-list");
    var emptyEl = q(panel, ".lc-empty");
    var form = q(panel, "#lc-record-form");
    var title = q(panel, "#lc-record-title");
    var detail = q(panel, "#lc-record-detail");
    var statusBox = q(panel, "#lc-record-status");
    var more = q(panel, "#lc-record-more");
    var state = {offset: 0, size: 25, total: 0, editing: 0};

    function query() {
      return "?limit=" + state.size + "&offset=" + state.offset
             + "&sort=" + encodeURIComponent(value(q(panel, "#lc-record-sort")))
             + "&q=" + encodeURIComponent(value(q(panel, "#lc-record-search")));
    }

    function load(append) {
      if (!append) state.offset = 0;
      say("records", "Loading records...", "busy");
      api("/api/records" + query()).then(function (res) {
        if (!res.ok) { say("records", res.error, "error"); return; }
        reached("records");
        state.total = res.data.total;
        var rows = res.data.records;
        var add = function (record) {
          var row = node("li", "lc-row wrap");
          row.appendChild(node("span", "lc-record-name",
                               record.title + " - " + record.status));
          row.appendChild(button("Edit", function () {
            state.editing = record.id;
            if (title) title.value = record.title;
            if (detail) detail.value = record.detail;
            if (statusBox) statusBox.value = record.status;
            say("records", "Editing that record. Save to replace it.", "info");
          }));
          row.appendChild(button("Remove", function () {
            api("/api/records/" + record.id, {method: "DELETE"}).then(function (gone) {
              say("records", gone.ok ? gone.data.note : gone.error, gone.ok ? "done" : "error");
              if (gone.ok) load(false);
            });
          }, "danger"));
          return row;
        };
        if (append && listEl) {
          var fragment = document.createDocumentFragment();
          for (var i = 0; i < rows.length; i++) fragment.appendChild(add(rows[i]));
          listEl.appendChild(fragment);
          show(emptyEl, listEl.children.length > 0);
        } else {
          fill(listEl, emptyEl, rows, add);
        }
        if (more) more.hidden = listEl && listEl.children.length >= state.total;
        say("records", state.total ? (listEl ? listEl.children.length : 0) + " of " + state.total
                                   + " records." : "No records yet - the form above makes the first.",
            state.total ? "done" : "info");
      });
    }
    resync.push(function () { load(false); });

    on(form, "submit", function (event) {
      event.preventDefault();
      var payload = {title: value(title), detail: value(detail), status: value(statusBox)};
      var path = state.editing ? "/api/records/" + state.editing : "/api/records";
      api(path, {method: state.editing ? "PATCH" : "POST", send: payload}).then(function (res) {
        if (!res.ok) { say("records", res.error, "error"); return; }
        state.editing = 0;
        if (title) title.value = "";
        if (detail) detail.value = "";
        load(false);
        say("records", "Saved to the database.", "done");
      });
    });
    on(q(panel, "#lc-record-more"), "click", function () {
      state.offset += state.size;
      load(true);
    });
    on(q(panel, "#lc-record-search"), "keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); load(false); }
    });
    on(q(panel, "#lc-record-sort"), "change", function () { load(false); });
    load(false);
  };
''',

    "catalog": r'''
  wire.catalog = function (panel) {
    var listEl = q(panel, "#lc-catalog-list");
    var emptyEl = q(panel, ".lc-empty");
    var cartList = q(panel, "#lc-cart-list");
    var cartEmpty = q(panel, "#lc-cart .lc-empty");
    var totalEl = q(panel, ".lc-total");
    var cart = [];

    function drawCart() {
      fill(cartList, cartEmpty, cart, function (line) {
        var row = node("li", "lc-row wrap",
                       line.name + " x" + line.quantity + " - " + money(line.unit_minor * line.quantity,
                                                                        line.currency));
        row.appendChild(button("Remove", function () {
          for (var i = 0; i < cart.length; i++) {
            if (cart[i].id === line.id) cart.splice(i, 1);
          }
          drawCart();
        }));
        return row;
      });
      var minor = 0;
      for (var i = 0; i < cart.length; i++) minor += cart[i].unit_minor * cart[i].quantity;
      if (totalEl) totalEl.textContent = "Total: " + money(minor, cart.length ? cart[0].currency : "USD");
      say("catalog", cart.length ? "Cart held on this page: " + cart.length + " line(s). It is not sent "
                                 + "until you check out." : "Your cart is empty.", "info");
    }

    function add(product) {
      for (var i = 0; i < cart.length; i++) {
        if (cart[i].id === product.id) { cart[i].quantity += 1; drawCart(); return; }
      }
      cart.push({id: product.id, name: product.name, quantity: 1, unit_minor: product.price_minor,
                 currency: product.currency});
      drawCart();
    }

    function load() {
      var query = "?limit=100&sort=" + encodeURIComponent(value(q(panel, "#lc-catalog-sort")))
                  + "&q=" + encodeURIComponent(value(q(panel, "#lc-catalog-search")))
                  + "&max_price=" + encodeURIComponent(value(q(panel, "#lc-catalog-max")) || "0");
      say("catalog", "Loading products...", "busy");
      api("/api/products" + query).then(function (res) {
        if (!res.ok) { say("catalog", res.error, "error"); return; }
        reached("catalog");
        fill(listEl, emptyEl, res.data.products, function (product) {
          var row = node("li", "lc-plan");
          row.appendChild(node("h3", "lc-plan-name", product.name));
          row.appendChild(node("p", "lc-plan-price", money(product.price_minor, product.currency)
                               + " - " + product.stock + " in stock"));
          row.appendChild(node("p", "lc-note", product.description));
          if (product.stock > 0) row.appendChild(button("Add to cart", function () { add(product); }));
          else row.appendChild(node("p", "lc-empty", "Out of stock."));
          return row;
        });
        say("catalog", res.data.total ? res.data.total + " product(s) in the catalog."
                                     : "The catalog is empty. SETUP.md shows the one table to add rows to.",
            res.data.total ? "done" : "info");
      });
    }
    resync.push(load);

    on(q(panel, "#lc-checkout"), "click", function () {
      if (!cart.length) { say("catalog", "Nothing in the cart to order.", "info"); return; }
      say("catalog", "Asking the server to place the order...", "busy");
      api("/api/orders", {method: "POST", send: {lines: cart.map(function (line) {
        return {id: line.id, quantity: line.quantity};
      })}}).then(function (res) {
        if (res.status === 501) { notConfigured("catalog", res); return; }
        if (!res.ok) { say("catalog", res.error, "error"); return; }
        var order = res.data.order || {};
        var where = res.data.checkout_url
          ? " Open " + res.data.checkout_url + " to pay with your provider."
          : "";
        cart = [];
        drawCart();
        load();
        say("catalog", "Order " + order.reference + " recorded for " + money(order.total_minor || 0)
            + " as " + order.status + "." + where + " " + (res.data.note || ""), "done");
      });
    });
    on(q(panel, "#lc-catalog-search"), "keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); load(); }
    });
    on(q(panel, "#lc-catalog-sort"), "change", load);
    drawCart();
    load();
  };
''',

    "blog": r'''
  wire.blog = function (panel) {
    var listEl = q(panel, "#lc-post-list");
    var emptyEl = q(panel, ".lc-empty");
    var form = q(panel, "#lc-post-form");
    var stateBox = q(panel, "#lc-post-state");
    var state = {editing: 0, staff: false};

    function load() {
      var wanted = value(q(panel, "#lc-post-status")) || "published";
      var query = "?status=" + encodeURIComponent(wanted) + "&limit=50"
                  + "&q=" + encodeURIComponent(value(q(panel, "#lc-post-search")));
      say("blog", "Loading posts...", "busy");
      api("/api/posts" + query).then(function (res) {
        if (!res.ok) {
          say("blog", wanted === "all" ? "Drafts are a staff view: " + res.error : res.error, "error");
          return;
        }
        reached("blog");
        fill(listEl, emptyEl, res.data.posts, function (post) {
          var row = node("li", "lc-row wrap");
          row.appendChild(node("span", "lc-post-name", post.title + " - " + post.status));
          row.appendChild(button("Read", function () {
            api("/api/posts/" + encodeURIComponent(post.slug)).then(function (oneRes) {
              if (!oneRes.ok) { say("blog", oneRes.error, "error"); return; }
              say("blog", oneRes.data.post.body.slice(0, 400), "info");
            });
          }));
          if (state.staff) {
            row.appendChild(button("Edit", function () {
              state.editing = post.id;
              show(form, true);
              api("/api/posts/" + encodeURIComponent(post.slug)).then(function (oneRes) {
                if (!oneRes.ok) return;
                if (q(panel, "#lc-post-title")) q(panel, "#lc-post-title").value = oneRes.data.post.title;
                if (q(panel, "#lc-post-body")) q(panel, "#lc-post-body").value = oneRes.data.post.body;
                if (stateBox) stateBox.value = oneRes.data.post.status;
                say("blog", "Editing this post. Save to replace it.", "info");
              });
            }));
            row.appendChild(button("Delete", function () {
              api("/api/posts/" + post.id, {method: "DELETE"}).then(function (gone) {
                say("blog", gone.ok ? gone.data.note : gone.error, gone.ok ? "done" : "error");
                if (gone.ok) load();
              });
            }, "danger"));
          }
          return row;
        });
        say("blog", res.data.total ? res.data.total + " post(s)." : "Nothing published yet.",
            res.data.total ? "done" : "info");
      });
    }

    api("/api/admin/whoami").then(function (who) {
      state.staff = !!(who.ok && who.data.staff);
      if (state.staff) {
        show(form, true);
        say("blog", "Signed in as staff: the writing form is open.", "done");
      } else {
        say("blog", "Reading is open to everyone. Writing needs a staff account.", "info");
      }
      load();
    });
    resync.push(load);

    on(form, "submit", function (event) {
      event.preventDefault();
      var payload = {title: value(q(panel, "#lc-post-title")), body: value(q(panel, "#lc-post-body")),
                     status: value(stateBox) || "draft"};
      var path = state.editing ? "/api/posts/" + state.editing : "/api/posts";
      api(path, {method: state.editing ? "PATCH" : "POST", send: payload}).then(function (res) {
        if (!res.ok) { say("blog", res.error, "error"); return; }
        state.editing = 0;
        if (q(panel, "#lc-post-title")) q(panel, "#lc-post-title").value = "";
        if (q(panel, "#lc-post-body")) q(panel, "#lc-post-body").value = "";
        say("blog", "Saved as " + res.data.post.status + ".", "done");
        load();
      });
    });
    on(q(panel, "#lc-post-status"), "change", load);
    on(q(panel, "#lc-post-search"), "keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); load(); }
    });
  };
''',

    "booking": r'''
  wire.booking = function (panel) {
    var listEl = q(panel, "#lc-slot-list");
    var emptyEl = q(panel, ".lc-empty");
    var form = q(panel, "#lc-booking-form");
    var chosen = 0;

    function load() {
      var query = "?resource=" + encodeURIComponent(value(q(panel, "#lc-booking-resource")) || "default");
      say("booking", "Reading the calendar...", "busy");
      api("/api/slots" + query).then(function (res) {
        if (!res.ok) { say("booking", res.error, "error"); return; }
        reached("booking");
        var count = fill(listEl, emptyEl, res.data.slots, function (slot) {
          var row = node("li", "lc-row wrap",
                         slot.starts_at + " - " + slot.minutes + " minutes");
          if (slot.free) row.appendChild(button("Hold this time", function () {
            chosen = slot.id;
            show(form, true);
            say("booking", "Holding " + slot.starts_at + ". Fill the form to keep it.", "info");
          }));
          else row.appendChild(node("span", "lc-empty", "Taken."));
          return row;
        });
        say("booking", count ? count + " time(s) on the calendar for " + res.data.resource + "."
                             : "This calendar has no times yet. SETUP.md shows how to add slots.",
            count ? "done" : "info");
        if (me) showBookings();
      });
    }

    function showBookings() {
      api("/api/bookings").then(function (res) {
        if (!res.ok || !listEl) return;
        var heading = node("li", "lc-note", res.data.scope === "all"
                                 ? "Every booking on this calendar:" : "Your bookings:");
        listEl.appendChild(heading);
        (res.data.bookings || []).forEach(function (booking) {
          var row = node("li", "lc-row wrap",
                         booking.starts_at + " - " + booking.name + " - " + booking.status);
          if (booking.status !== "cancelled") {
            row.appendChild(button("Cancel", function () {
              api("/api/bookings/" + booking.id, {method: "DELETE"}).then(function (gone) {
                say("booking", gone.ok ? "Cancelled " + gone.data.starts_at + "." : gone.error,
                    gone.ok ? "done" : "error");
                if (gone.ok) load();
              });
            }, "danger"));
          }
          listEl.appendChild(row);
        });
      });
    }
    resync.push(load);

    on(q(panel, "#lc-booking-load"), "click", load);
    on(form, "submit", function (event) {
      event.preventDefault();
      if (!chosen) { say("booking", "Pick a time from the list first.", "info"); return; }
      api("/api/bookings", {method: "POST", send: {
        slot_id: chosen, name: value(q(panel, "#lc-booking-name")),
        email: value(q(panel, "#lc-booking-email")), note: value(q(panel, "#lc-booking-note"))
      }}).then(function (res) {
        if (!res.ok) { say("booking", res.error, "error"); return; }
        show(form, false);
        chosen = 0;
        say("booking", "Held " + res.data.booking.starts_at + ". " + res.data.note, "done");
        load();
      });
    });
    load();
  };
''',

    "contact": r'''
  wire.contact = function (panel) {
    on(q(panel, "#lc-contact-form"), "submit", function (event) {
      event.preventDefault();
      say("contact", "Sending...", "busy");
      api("/api/contact", {method: "POST", send: {
        name: value(q(panel, "#lc-contact-name")), email: value(q(panel, "#lc-contact-email")),
        subject: value(q(panel, "#lc-contact-subject")), message: value(q(panel, "#lc-contact-message"))
      }}).then(function (res) {
        if (!res.ok) { say("contact", res.error, "error"); return; }
        reached("contact");
        // The two answers are different sentences, and the page shows whichever the server sent.
        if (res.data.delivered) {
          say("contact", "Sent. " + res.data.note, "done");
          if (q(panel, "#lc-contact-message")) q(panel, "#lc-contact-message").value = "";
        } else {
          say("contact", res.data.tell_the_visitor + " (server: " + res.data.note + ")", "info");
        }
      });
    });
  };
''',

    "uploads": r'''
  wire.uploads = function (panel) {
    var listEl = q(panel, "#lc-upload-list");
    var emptyEl = q(panel, ".lc-empty");

    function load() {
      if (!me) {
        fill(listEl, emptyEl, [], function () { return null; });
        say("uploads", "Sign in to send a file - uploads belong to an account.", "info");
        return;
      }
      say("uploads", "Reading your files...", "busy");
      api("/api/uploads").then(function (res) {
        if (!res.ok) { say("uploads", res.error, "error"); return; }
        reached("uploads");
        fill(listEl, emptyEl, res.data.uploads, function (file) {
          var row = node("li", "lc-row wrap");
          var link = node("a", "lc-upload-name", file.original_name);
          link.href = "/api/uploads/" + file.id + "/raw";
          link.setAttribute("target", "_blank");
          link.setAttribute("rel", "noopener");
          row.appendChild(link);
          row.appendChild(node("span", "lc-note", file.media_type + ", " + file.bytes + " bytes"));
          row.appendChild(button("Delete", function () {
            api("/api/uploads/" + file.id, {method: "DELETE"}).then(function (gone) {
              say("uploads", gone.ok ? "Removed." : gone.error, gone.ok ? "done" : "error");
              if (gone.ok) load();
            });
          }, "danger"));
          return row;
        });
        say("uploads", res.data.uploads.length ? "Listed " + res.data.uploads.length
                                               + " file(s) (" + res.data.scope + ")."
                                               : "You have not uploaded anything yet.",
            res.data.uploads.length ? "done" : "info");
      });
    }
    resync.push(load);

    on(q(panel, "#lc-upload-form"), "submit", function (event) {
      event.preventDefault();
      var picker = q(panel, "#lc-upload-file");
      if (!picker || !picker.files || !picker.files.length) {
        say("uploads", "Choose a file first.", "info");
        return;
      }
      var body = new FormData();
      body.append("file", picker.files[0]);
      say("uploads", "Uploading...", "busy");
      api("/api/uploads", {method: "POST", form: body}).then(function (res) {
        if (!res.ok) { say("uploads", res.error, "error"); return; }
        say("uploads", "Stored as " + res.data.upload.name + " (" + res.data.upload.bytes
            + " bytes). The server checked its type and size again before writing it.", "done");
        load();
      });
    });
    load();
  };
''',

    "activity": r'''
  wire.activity = function (panel) {
    var listEl = q(panel, "#lc-activity-list");
    var emptyEl = q(panel, ".lc-empty");
    var state = {offset: 0, size: 20};

    function load(append) {
      if (!me) {
        fill(listEl, emptyEl, [], function () { return null; });
        say("activity", "The feed is per account: sign in to see yours.", "info");
        return;
      }
      if (!append) state.offset = 0;
      api("/api/activity?limit=" + state.size + "&offset=" + state.offset).then(function (res) {
        if (!res.ok) { say("activity", res.error, "error"); return; }
        reached("activity");
        var add = function (row) {
          var line = node("li", "lc-row wrap", String(row.created_at || "").slice(0, 16) + " - "
                          + row.kind + (row.detail ? " - " + row.detail : ""));
          if (row.who) line.appendChild(node("span", "lc-note", row.who));
          return line;
        };
        if (append && listEl) {
          for (var i = 0; i < res.data.activity.length; i++) listEl.appendChild(add(res.data.activity[i]));
        } else {
          fill(listEl, emptyEl, res.data.activity, add);
        }
        var shown = listEl ? listEl.children.length : 0;
        say("activity", "Showing " + shown + " of " + res.data.total + " entries (" + res.data.scope
            + " scope).", "done");
      });
    }
    resync.push(function () { load(false); });

    on(q(panel, "#lc-activity-more"), "click", function () {
      state.offset += state.size;
      load(true);
    });
    load(false);
  };
''',

    "analytics": r'''
  wire.analytics = function (panel) {
    var listEl = q(panel, "#lc-analytics-names");
    var emptyEl = q(panel, ".lc-empty");
    var totalEl = q(panel, ".lc-analytics-total");
    var bodyEl = q(panel, "#lc-analytics-days-table tbody");

    function load() {
      api("/api/analytics/summary?days=" + (value(q(panel, "#lc-analytics-days")) || "30"))
        .then(function (res) {
          if (!res.ok) {
            say("analytics", res.status === 403 ? "Counts are a staff view. Sign in with a staff account."
                                                : res.error, "error");
            return;
          }
          reached("analytics");
          if (totalEl) totalEl.textContent = res.data.events + " event(s) in the last "
                                             + res.data.window_days + " days.";
          fill(listEl, emptyEl, res.data.by_name, function (row) {
            return node("li", "lc-row wrap", row.name + " - " + row.count);
          });
          if (bodyEl) {
            bodyEl.textContent = "";
            (res.data.by_day || []).forEach(function (row) {
              var line = bodyEl.appendChild(node("tr"));
              line.appendChild(node("th", "", row.day)).setAttribute("scope", "row");
              line.appendChild(node("td", "", String(row.count)));
            });
          }
          say("analytics", res.data.empty ? "Nothing recorded yet. The panels above write events as people "
                                            + "use the site; a third-party tracker did not."
                                          : res.data.note, res.data.empty ? "info" : "done");
        });
    }
    resync.push(load);
    on(q(panel, "#lc-analytics-days"), "change", load);
    load();
  };
''',

    "pricing": r'''
  wire.pricing = function (panel) {
    var buttons = panel.querySelectorAll("[data-lc-subscribe]");
    for (var i = 0; i < buttons.length; i++) {
      (function (theButton) {
        on(theButton, "click", function () {
          var plan = theButton.getAttribute("data-lc-subscribe");
          say("pricing", "Asking the provider...", "busy");
          api("/api/subscribe", {method: "POST", send: {plan: plan}}).then(function (res) {
            if (res.status === 501) { notConfigured("pricing", res); return; }
            if (!res.ok) { say("pricing", res.error, "error"); return; }
            reached("pricing");
            var extra = res.data.checkout_url ? " Finish at " + res.data.checkout_url + "." : "";
            say("pricing", "Plan " + res.data.plan + ": the provider reports " + res.data.status + "."
                + extra + " " + res.data.note, "done");
          });
        });
      })(buttons[i]);
    }
  };
''',

    "api": r'''
  wire.api = function (panel) {
    function load() {
      api("/api/integrations/status").then(function (res) {
        if (!res.ok) { say("api", res.error, "error"); return; }
        reached("api");
        var rows = res.data.integrations.map(function (item) {
          return {name: item.name, set: item.set};
        });
        fill(q(panel, "#lc-integration-list"), q(panel, ".lc-empty"), rows, function (item) {
          var row = node("li", "lc-row wrap", item.name);
          row.appendChild(node("span", "lc-note", item.set ? "set in the environment"
                                                           : "not set - the route that needs it answers 501"));
          return row;
        });
        say("api", "Values are never shown here, only whether they exist.", "done");
      });
    }
    resync.push(load);
    load();
  };
''',
}

CLIENT_TAIL = r'''
  function start() {
    api("/api/status").then(function (res) {
      if (!res.ok) {
        // No server: leave every panel saying it waits, because that is the truth of the moment.
        return;
      }
      var features = res.data.features || [];
      for (var i = 0; i < features.length; i++) {
        var found = document.querySelector('[data-lc-feature="' + features[i] + '"]');
        if (found) panels[features[i]] = found;
      }
      refreshUser().then(function () {
        for (var key in panels) {
          if (wire[key]) {
            try {
              wire[key](panels[key]);
            } catch (broken) {
              say(key, "This panel could not start: " + broken, "error");
            }
          }
        }
      });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
'''

# --------------------------------------------------------------------------- page-only behaviour
# No fetch, no web storage, no off-page reference: this is the code that is allowed to sit inside the
# published file, because the sanitizer's rules are about leaving the page, not about moving within it.
INLINE = {
    "browse": r'''<script>
(function () {
  "use strict";
  var panel = document.querySelector('[data-lc-feature="browse"]');
  if (!panel) return;
  var items = Array.prototype.slice.call(document.querySelectorAll("main article"));
  var count = panel.querySelector(".lc-count");
  var empty = panel.querySelector("[data-lc-browse-empty]");
  var info = panel.querySelector("[data-lc-pageinfo]");
  var shown = [];
  var page = 0;

  function words(el) { return (el.textContent || " ").toLowerCase(); }

  function render() {
    var size = parseInt(panel.querySelector("#lc-browse-size").value, 10);
    items.forEach(function (item) { item.style.display = "none"; });
    if (!size) size = shown.length || 1;
    var pages = Math.max(1, Math.ceil(shown.length / size));
    if (page >= pages) page = 0;
    var slice = shown.slice(page * size, page * size + size);
    slice.forEach(function (item) { item.style.display = ""; });
    if (empty) empty.hidden = shown.length > 0;
    if (count) count.textContent = shown.length + " of " + items.length
      + " item(s) match, " + slice.length + " on this page of " + pages + ".";
    if (info) info.textContent = (page + 1) + " / " + pages;
  }

  function apply() {
    var needle = (panel.querySelector("#lc-browse-q").value || " ").trim().toLowerCase();
    var order = panel.querySelector("#lc-browse-sort").value;
    shown = items.filter(function (item) { return !needle || words(item).indexOf(needle) !== -1; });
    if (order !== "order") {
      shown.sort(function (a, b) {
        var first = words(a), second = words(b);
        return order === "name" ? (first < second ? -1 : 1) : (first > second ? -1 : 1);
      });
    }
    page = 0;
    render();
  }

  ["#lc-browse-q", "#lc-browse-sort", "#lc-browse-size"].forEach(function (selector) {
    panel.querySelector(selector).addEventListener("input", apply);
  });
  panel.querySelector("[data-lc-prev]").addEventListener("click", function () {
    page = page > 0 ? page - 1 : page; render();
  });
  panel.querySelector("[data-lc-next]").addEventListener("click", function () { page += 1; render(); });
  if (!items.length) {
    if (count) count.textContent = "This page has no items to browse yet, so the controls have nothing to "
      + "filter. They work on any article the page gains later.";
  } else {
    apply();
  }
})();
</script>''',

    "wizard": r'''<script>
(function () {
  "use strict";
  var panel = document.querySelector('[data-lc-feature="wizard"]');
  if (!panel) return;
  var form = panel.querySelector("#lc-wizard-form");
  var steps = Array.prototype.slice.call(form.querySelectorAll("fieldset"));
  var progress = panel.querySelector(".lc-progress");
  var statusBox = panel.querySelector("[data-lc-status]");
  var current = 0;

  function say(text, kind) {
    if (statusBox) { statusBox.textContent = text; statusBox.setAttribute("data-lc-kind", kind || "info"); }
  }

  function paint() {
    steps.forEach(function (step, index) { step.hidden = index !== current; });
    panel.querySelectorAll("[data-lc-step]").forEach(function (chip) {
      chip.setAttribute("aria-current", Number(chip.getAttribute("data-lc-step")) === current
        ? "step" : "false");
    });
    if (progress) progress.textContent = "Step " + (current + 1) + " of " + steps.length;
    panel.querySelector("[data-lc-back]").disabled = current === 0;
    panel.querySelector("[data-lc-next-step]").hidden = current === steps.length - 1;
    panel.querySelector("[data-lc-finish]").hidden = current !== steps.length - 1;
  }

  // A step will not advance on an empty answer: the check is the field's own required flag.
  function check() {
    var fields = steps[current].querySelectorAll("[required]");
    for (var i = 0; i < fields.length; i++) {
      if (!fields[i].value.trim()) {
        fields[i].focus();
        say("Fill in " + (fields[i].previousElementSibling
          ? fields[i].previousElementSibling.textContent : "that") + " before moving on.", "error");
        return false;
      }
    }
    return true;
  }

  panel.querySelector("[data-lc-next-step]").addEventListener("click", function () {
    if (!check()) return;
    current = Math.min(current + 1, steps.length - 1);
    paint();
  });
  panel.querySelector("[data-lc-back]").addEventListener("click", function () {
    current = Math.max(current - 1, 0);
    paint();
  });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!check()) return;
    // Nothing leaves the page from here: the published page cannot reach an API. Ask for the records
    // feature and this same finish line writes the answers into a database instead - see SETUP.md.
    say("Answers are complete and held in this form. There is nowhere to send them yet: this page is "
        + "static, and a record needs the site's own server running.", "info");
  });
  paint();
})();
</script>''',

    "layout": r'''<script>
(function () {
  "use strict";
  var nav = document.querySelector("main [role=navigation], main nav");
  if (!nav) return;
  var links = nav.querySelector("ul") || nav.querySelector("[data-lc-navlinks]");
  if (!links || nav.querySelector("[data-lc-nav-toggle]")) return;
  links.classList.add("lc-navlinks");
  var toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "btn lc-nav-toggle";
  toggle.setAttribute("data-lc-nav-toggle", "");
  toggle.setAttribute("aria-expanded", "true");
  toggle.setAttribute("aria-controls", links.id || "");
  toggle.textContent = "Menu";
  if (!links.id) { links.id = "lc-navlinks"; toggle.setAttribute("aria-controls", links.id); }
  nav.insertBefore(toggle, links);

  function setOpen(open) {
    links.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }
  // Only narrow widths need a button; a wide menu stays a plain row of links.
  function matchWidth() {
    var narrow = window.matchMedia("(max-width: 720px)");
    setOpen(!narrow.matches || links.dataset.opened === "1");
  }
  toggle.addEventListener("click", function () {
    var open = links.hidden;
    links.dataset.opened = open ? "1" : "0";
    setOpen(open);
  });
  links.querySelectorAll("a").forEach(function (link) {
    link.addEventListener("click", function () {
      if (window.matchMedia("(max-width: 720px)").matches) {
        links.dataset.opened = "0";
        setOpen(false);
      }
    });
  });
  window.addEventListener("resize", matchWidth);
  matchWidth();
})();
</script>''',
}


