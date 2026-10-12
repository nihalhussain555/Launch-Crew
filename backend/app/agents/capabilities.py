"""What Launch Crew can actually build when someone asks for a feature in plain English.

This module exists to stop the system saying more than it means. A request is broken into *surfaces* -
the page, a server, a database, a third-party account - and each surface gets one honest state:

  generated            the code is written into the run and works as it stands
  scaffold             real, runnable source is written into the workspace, but nothing runs until the
                       user installs and start it - so no message may call it live
  needs-external-setup it depends on an account, keys or a domain the user must supply first; the
                       generated part is configuration and instructions, never a working integration

The brief's rule is followed exactly: payments, email providers, OAuth and other external services are
handed over as integration scaffolding with explicit setup steps, and a feature that this product cannot
implement without infrastructure it does not have is documented rather than pretended. Nothing here
claims a capability the builder in `app/services/feature_build.py` cannot write, and the catalog is what
the wizard and the Features panel draw from, so the UI cannot offer a thing the crew would fake.

Every capability names the plain-English words that select it, the env vars it reads, the files it
writes and the limits a user should be told about before they approve the change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# The four surfaces a feature can touch. The brief asks for exactly this split: "frontend changes,
# backend logic, database changes, or external integrations".
SURFACES = ("page", "server", "database", "integration")

# The honest states, worst last.
GENERATED = "generated"
SCAFFOLD = "scaffold"
NEEDS_SETUP = "needs-external-setup"

STATES = (GENERATED, SCAFFOLD, NEEDS_SETUP)

STATE_LABEL = {
    GENERATED: "works in the published page now",
    SCAFFOLD: "runnable source in the workspace - start it yourself",
    NEEDS_SETUP: "needs your account or keys before it can do anything",
}

# A capability's overall status is its weakest part, because a feature whose email provider is un-
# configured is not "implemented" and must not be reported as if it were.
_STATUS_RANK = {GENERATED: 0, SCAFFOLD: 1, NEEDS_SETUP: 2}


def overall_status(parts: tuple) -> str:
    return max((part.state for part in parts), key=lambda s: _STATUS_RANK[s], default=GENERATED)


@dataclass(frozen=True)
class Part:
    """One surface of one capability, and how far this product takes it."""
    surface: str
    state: str
    detail: str
    files: tuple[str, ...] = ()          # workspace file names this part writes
    env: tuple[str, ...] = ()            # environment variables it reads (never values)


@dataclass(frozen=True)
class Capability:
    key: str
    label: str
    blurb: str                            # one line, shown where the user picks it
    aliases: tuple[str, ...]              # words in a sentence that name this capability
    parts: tuple[Part, ...]
    setup: tuple[str, ...]                # what the user must do, in order
    limits: str                           # what this does NOT do, said out loud
    needs_approval: bool = True           # every build is reviewed; kept for the UI's wording
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        return overall_status(self.parts)

    @property
    def needs(self) -> tuple[str, ...]:
        return tuple(s for s in SURFACES if any(p.surface == s for p in self.parts))

    @property
    def files(self) -> tuple[str, ...]:
        seen: list[str] = []
        for part in self.parts:
            seen.extend(f for f in part.files if f not in seen)
        return tuple(seen)

    @property
    def env(self) -> tuple[str, ...]:
        seen: list[str] = []
        for part in self.parts:
            seen.extend(e for e in part.env if e not in seen)
        return tuple(seen)


# ------------------------------------------------------------------ the shared server scaffold
# These four files are written once, whatever combination of server features was asked for: the app,
# its database helper, the environment template and the setup notes. Feature code is composed into
# them by app/services/feature_templates.py rather than being a file per capability, so what the user
# has to install and run stays small enough to actually run.
SHARED_SERVER = "server.py"
SHARED_DB = "db.py"
SHARED_SCHEMA = "schema.sql"
SHARED_ENV = "env_template.txt"
SHARED_SETUP = "SETUP.md"
SHARED_FILES = (SHARED_SERVER, SHARED_DB, SHARED_SCHEMA, SHARED_ENV, SHARED_SETUP)


def _server_and_db(detail: str, *, env: tuple[str, ...] = ()) -> tuple[Part, Part]:
    """The usual pair: endpoints on the bundled server, tables in its database."""
    return (Part("server", SCAFFOLD, detail, (SHARED_SERVER, SHARED_ENV, SHARED_SETUP), env),
            Part("database", SCAFFOLD, "One SQLite table in the bundled database, created on first run "
                                       "from schema.sql.", (SHARED_DB, SHARED_SCHEMA)))


# ------------------------------------------------------------------ the catalog
CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "authentication", "Sign in and register",
        "Email and password accounts: a signup form, a sign-in form, and a server that checks both.",
        ("auth", "authentication", "login", "log in", "sign in", "signin", "register", "registration",
         "sign up", "signup", "account creation", "password"),
        (Part("page", GENERATED,
              "A signup panel and a sign-in panel in the page, with the browser's own validation on every "
              "field and a status line that reports what the server actually answered.",
              ("index.html",)),
         *_server_and_db("POST /api/signup, POST /api/login, POST /api/logout and GET /api/me, with "
                         "PBKDF2-HMAC-SHA256 password hashing, a signed session cookie and per-IP rate "
                         "limiting. Nothing about it is a stub.",
                         env=("SESSION_SECRET", "DATABASE_PATH"))),
        ("Install the two packages named in SETUP.md.",
         "Set SESSION_SECRET to a long random string of your own - the generated file refuses to start "
         "with the placeholder value.",
         "Run `uvicorn server:app` and open the site from that server so the session cookie is set."),
        "Accounts live in the database file you start, not in Launch Crew: signing in against the "
        "published static page alone will report that the API is not reachable, which is the truth. "
        "No OAuth, magic link or two-factor flow is generated - those need a provider you connect "
        "yourself.",
        tags=("accounts",),
    ),
    Capability(
        "profiles", "User profiles and account settings",
        "The signed-in user's own details: view them, edit them, change the password, delete the account.",
        ("profile", "profiles", "account settings", "my account", "user settings", "avatar",
         "personal details", "delete account"),
        (Part("page", GENERATED,
              "A settings panel that reads the signed-in record from /api/me, sends only the fields that "
              "changed, and shows the server's answer instead of assuming it.",
              ("index.html",)),
         *_server_and_db("GET /api/me, PATCH /api/me, POST /api/me/password and DELETE /api/me, every "
                         "one behind the same session check, with Pydantic-style field validation and no "
                         "route that accepts another user's id.",
                         env=("SESSION_SECRET", "DATABASE_PATH"))),
        ("Start the bundled server and sign in (the authentication capability is what creates the account).",),
        "Profile fields are the ones this generator writes - display name, email, and a short bio. A "
        "social profile import, an avatar CDN or SSO directory sync is not generated.",
        tags=("accounts",),
    ),
    Capability(
        "admin", "Admin dashboard and role-based access",
        "A staff area that only a role-carrier can reach: users, records, and the actions on them.",
        ("admin", "administration", "dashboard", "back office", "backend office", "staff area", "cms",
         "moderator", "roles", "rbac", "permissions", "role based", "role-based"),
        (Part("page", GENERATED,
              "An admin panel in the page that asks /api/admin/whoami, and either renders the tables it "
              "reads or says you are not signed in with the staff role. It never renders an empty success.",
              ("index.html",)),
         *_server_and_db("A `role` column on the accounts table, a require_role() dependency on every "
                         "admin route, and list/modify endpoints that filter server-side. Authorization "
                         "is checked in the server, not by hiding buttons.",
                         env=("SESSION_SECRET", "DATABASE_PATH", "BOOTSTRAP_ADMIN_EMAIL"))),
        ("Set BOOTSTRAP_ADMIN_EMAIL to the address that should get the first staff account.",
         "Start the server, then sign in with that address to see the panel."),
        "One role ladder (member / staff) is generated. A full permission matrix, per-object ownership "
        "rules and an audit trail of staff actions are the kind of thing an operations team builds "
        "against its own data, and are not claimed here.",
        tags=("accounts",),
    ),
    Capability(
        "records", "CRUD operations and database-backed forms",
        "Create, read, update and delete a record type through a form that talks to the database.",
        ("crud", "create read update delete", "database backed", "database-backed", "records", "entries",
         "add item", "edit item", "delete item", "manage items", "data entry", "forms with a database"),
        (Part("page", GENERATED,
              "A record panel: the list read from the server, a form for one record, inline validation "
              "matching the server's rules, and the server's own error text on a rejection.",
              ("index.html",)),
         *_server_and_db("A table with an id, timestamps and the fields named in the request, plus "
                         "GET/POST/PATCH/DELETE on /api/records. Reads are parameterised SQL, writes are "
                         "validated field by field, and a delete is a soft delete so nothing is lost "
                         "quietly.",
                         env=("DATABASE_PATH",))),
        ("Start the bundled server; the table is created on first run.",),
        "The record type is built from the fields the request names, from one text field to several. It "
        "is one table on one SQLite file - a sharded or replicated store, migrations under version "
        "control, and an admin import from CSV are yours to add.",
        tags=("data",),
    ),
    Capability(
        "catalog", "Product catalog, cart and checkout scaffolding",
        "A browsable catalog with search and prices, a cart that adds up as you work through it, and the "
        "checkout calls wired to a payment provider you connect.",
        ("catalog", "catalogue", "products", "shop", "store", "cart", "basket", "checkout", "e commerce",
         "e-commerce", "payment", "payments", "buy", "shopping cart", "order"),
        (Part("page", GENERATED,
              "Catalog cards rendered from data in the page, working filters, and a cart that adds up "
              "while the page is open. Remembering a cart across visits needs this site's own "
              "feature_client.js, which its server serves. The cart is real; the money is not, until "
              "you connect a provider.",
              ("index.html",)),
         *_server_and_db("Products and orders tables, and GET /api/products with server-side filtering. "
                         "Prices are stored in whole minor units so no rounding decision is left to the "
                         "browser.",
                         env=("DATABASE_PATH",)),
         Part("integration", NEEDS_SETUP,
              "POST /api/checkout creates a checkout session through the provider's API and returns its "
              "URL. It reads the secret from the environment and answers with the exact variable to set "
              "when it is missing - it never fakes a completed order.",
              (SHARED_SERVER, SHARED_ENV, SHARED_SETUP),
              ("PAYMENT_PROVIDER", "PAYMENT_SECRET_KEY", "PAYMENT_PUBLIC_KEY", "CHECKOUT_WEBHOOK_SECRET"))),
        ("Choose a provider and set PAYMENT_PROVIDER, PAYMENT_SECRET_KEY and PAYMENT_PUBLIC_KEY.",
         "Create the webhook in the provider's dashboard and set CHECKOUT_WEBHOOK_SECRET to its signing "
         "secret.",
         "Test with the provider's sandbox keys before pointing live keys at it."),
        "No payment is taken by anything Launch Crew generated: the checkout route is scaffolding that "
        "calls the provider's API once you give it real keys, and it refuses without them. PCI scope, "
        "tax, shipping rules and refunds are the provider's and your accountant's business.",
        tags=("commerce",),
    ),
    Capability(
        "browse", "Search, sorting, filters and pagination",
        "Find things on the page you already have, in the order you want, a page at a time.",
        ("search", "searching", "sort", "sorting", "filter", "filtering", "facets", "pagination",
         "paginate", "sort by", "order by"),
        (Part("page", GENERATED,
              "A toolbar that filters, sorts and pages the items in the page's own catalog or article "
              "list. It works with no server, says when nothing matches instead of showing an empty "
              "box, and keeps the result count in a live region.",
              ("index.html",)),),
        ("Nothing to set up - this one runs in the published page as it is.",),
        "This searches what the page carries. Once a catalog or blog is served from the database, that "
        "server's list endpoints do the same filtering so the two never disagree about the total.",
        tags=("page",),
    ),
    Capability(
        "blog", "Blog publishing and content management",
        "Posts written as content the site renders, an index with excerpts, and a draft-to-live path on "
        "the bundled server.",
        ("blog", "blogs", "article", "articles", "posts", "publishing", "content management", "newsletter",
         "writing", "news", "magazine"),
        (Part("page", GENERATED,
              "An article index and a single-post view rendered from the page's own content, with an "
              "empty state when there are no posts yet.",
              ("index.html",)),
         *_server_and_db("Posts, drafts and slugs in the database with GET /api/posts and "
                         "GET /api/posts/{slug} open to readers and POST/PATCH/DELETE behind the staff "
                         "role. Slug collisions are refused, not silently re-numbered.",
                         env=("SESSION_SECRET", "DATABASE_PATH"))),
        ("Start the bundled server to publish from the browser; otherwise the posts live in the page's "
         "own content block.",),
        "A rich text editor, an image pipeline and a comment system are not generated. The editor writes "
        "a constrained markdown subset that the page renders through the same escaping the rest of the "
        "site uses.",
        tags=("content",),
    ),
    Capability(
        "booking", "Booking and appointment systems",
        "Pick a date, pick a slot, hold it, and get the confirmation into the site's own record.",
        ("booking", "book", "bookings", "appointment", "appointments", "reserve", "reservation",
         "availability", "calendar", "scheduling", "slots"),
        (Part("page", GENERATED,
              "A slot picker that asks the server which times are free and renders only what it returns, "
              "with a clear 'not confirmed' message when the API is not running.",
              ("index.html",)),
         *_server_and_db("A slots table with a UNIQUE constraint on (slot, resource) so two people "
                         "cannot hold the same time, and POST /api/bookings that reports the clash "
                         "instead of overwriting.",
                         env=("DATABASE_PATH",)),
         Part("integration", NEEDS_SETUP,
              "A calendar or reminder outside the site needs its own credentials; the generated code "
              "writes the booking to the database and leaves the notification to the provider you set.",
              (SHARED_ENV, SHARED_SETUP), ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"))),
        ("Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET only if you want calendar sync; the "
         "booking itself works without them.",),
        "Payments for appointments, staff rotas and timezone-aware working hours are not modelled here: "
        "slots are stored in UTC and shown in the visitor's own timezone.",
        tags=("data",),
    ),
    Capability(
        "contact", "Contact forms and email integration",
        "A message form that validates, submits and reports the truth about where the message went.",
        ("contact form", "contact", "get in touch", "enquiry", "inquiry", "message form", "email form",
         "reach us", "send message", "smtp"),
        (Part("page", GENERATED,
              "A contact form with required-field validation, a disabled submit while a send is in "
              "flight, and three states: sent, refused with the server's reason, unreachable.",
              ("index.html",)),
         Part("server", SCAFFOLD,
              "POST /api/contact validates the fields, rate limits the IP, and either queues the message "
              "in the database for a provider to pick up or answers that no provider is configured.",
              (SHARED_SERVER, SHARED_ENV, SHARED_SETUP), ("DATABASE_PATH",)),
         Part("integration", NEEDS_SETUP,
              "Delivery needs a real mail account. The generated sender reads SMTP or an API key from the "
              "environment and refuses to pretend it sent anything while those are unset.",
              (SHARED_ENV, SHARED_SETUP),
              ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM", "RESEND_API_KEY")),
         ),
        ("Point SMTP_* or RESEND_API_KEY at an account you own, then set MAIL_FROM to a verified sender "
         "address.", "Put the address you want replies to in the form's own configuration.",),
        "No email is sent by the published page alone, and nothing here generates a working mail "
        "account. Spam filtering, attachments and a ticketing history are not part of this.",
        tags=("messaging",),
    ),
    Capability(
        "uploads", "File and image uploads",
        "Let a visitor send a file, with the checks that keep the server from becoming a download host.",
        ("upload", "uploads", "file upload", "image upload", "attach", "attachment", "drop zone",
         "drag and drop files", "photos upload"),
        (Part("page", GENERATED,
              "A picker that checks the type and size you allowed before sending, shows progress, and "
              "names the file it stored.",
              ("index.html",)),
         Part("server", SCAFFOLD,
              "POST /api/uploads that re-checks the MIME type against an allow-list, enforces the size "
              "cap on the server, stores outside the web root with a generated name, and never serves "
              "the upload directory as scripts.",
              (SHARED_SERVER, SHARED_ENV, SHARED_SETUP), ("UPLOAD_DIR", "MAX_UPLOAD_BYTES")),
         Part("integration", NEEDS_SETUP,
              "Object storage (S3, R2, Blob Storage) means its own keys. The generated code writes to the "
              "local UPLOAD_DIR; a bucket adapter is a swap you make with your credentials.",
              (SHARED_ENV, SHARED_SETUP),
              ("S3_BUCKET", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")),
         ),
        ("Set UPLOAD_DIR to a directory the server process can write and the web server does not serve.",
         "Keep MAX_UPLOAD_BYTES at what your host actually allows.",),
        "Virus scanning, image transcoding and a CDN are not generated. Files are stored as received and "
        "served only to a signed-in owner of that record.",
        tags=("data",),
    ),
    Capability(
        "activity", "Notifications and activity feeds",
        "A running list of what happened, newest first, plus the fan-out that tells someone about it.",
        ("notification", "notifications", "activity feed", "feed", "alerts", "inbox", "update feed",
         "real time updates", "push"),
        (Part("page", GENERATED,
              "A feed panel that reads /api/activity, shows the server's own timestamps, and says when "
              "there is nothing to show yet.",
              ("index.html",)),
         *_server_and_db("An activity table written by the other features as they act, and GET "
                         "/api/activity scoped to the signed-in user's own rows.",
                         env=("DATABASE_PATH", "SESSION_SECRET")),
         Part("integration", NEEDS_SETUP,
              "Delivery outside the site - email, push, Slack - needs the provider's credentials and its "
              "own consent. The feed works without any of it.",
              (SHARED_ENV, SHARED_SETUP),
              ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "PUSH_SERVICE_KEY"))),
        ("Set the provider keys for whichever channel you want to fan out to.",),
        "No push certificates, no SMS and no subscriber list are generated. The feed is the site's own "
        "record of events; a channel only ever gets what you configure it to send.",
        tags=("messaging", "data"),
    ),
    Capability(
        "analytics", "Analytics dashboard",
        "Numbers about this site's own traffic and events, kept on this site's own server.",
        ("analytics", "metrics", "tracking", "insights", "dashboard charts", "visitor stats", "stats",
         "measurement", "kpi"),
        (Part("page", GENERATED,
              "A dashboard that renders the counts the server returns from recorded events, with a "
              "loading state and an empty state that says 'nothing recorded yet' rather than zeroes "
              "presented as success.",
              ("index.html",)),
         *_server_and_db("An events table plus POST /api/events (no personal data, no cookies) and GET "
                         "/api/analytics/summary with the window you ask for.",
                         env=("DATABASE_PATH",)),
         Part("integration", NEEDS_SETUP,
              "A third-party product (GA4, Plausible, Mixpanel) is a separate account and its own script "
              "tag; the generator writes the variable to set and does not embed a tracker you have not "
              "authorised.",
              (SHARED_ENV, SHARED_SETUP), ("GA_MEASUREMENT_ID", "PLAUSIBLE_DOMAIN"))),
        ("If you want a third-party analytics account instead, set its id in env_template.txt and add "
         "its script tag yourself.",),
        "First-party counts only, and no cross-site identifiers. Cookie consent, GDPR export tooling and "
        "session-level re-identification are not generated.",
        tags=("data",),
    ),
    Capability(
        "wizard", "Multi-step forms and onboarding",
        "One request collected over several steps, with progress, back-navigation and answers that are "
        "checked before the form will move on.",
        ("multi step", "multi-step", "wizard", "onboarding", "step by step", "steps form", "setup flow",
         "quiz", "typeform"),
        (Part("page", GENERATED,
              "A step machine in the page: one panel visible at a time, a progress indicator with "
              "aria-live, and per-step validation that will not advance on a bad answer. The answers "
              "live in the form while the page is open; surviving a reload needs this site's own "
              "feature_client.js, because browser storage is stripped from a published page.",
              ("index.html",)),),
        ("Nothing to set up - it runs in the published page.",),
        "It ends by posting the finished answers to whatever endpoint you give it (the records "
        "capability generates one). Conditional-logic scripting beyond 'show this step when that answer "
        "is set' is not generated.",
        tags=("page",),
    ),
    Capability(
        "pricing", "Pricing page and subscription integration scaffolding",
        "Plans, prices and a subscribe button, plus the billing calls that need your provider.",
        ("pricing", "pricing page", "plans", "tiers", "subscriptions", "subscribe", "billing", "recurring",
         "plans and pricing", "stripe"),
        (Part("page", GENERATED,
              "A plan table with the periods and features you named, a highlighted tier, and a button "
              "per plan that calls the checkout route rather than pretending to be a subscription.",
              ("index.html",)),
         Part("integration", NEEDS_SETUP,
              "POST /api/subscribe creates the provider's subscription object and returns its checkout "
              "URL. Without the keys it answers which environment variables are missing - a subscription "
              "is never reported as started before the provider confirms it.",
              (SHARED_SERVER, SHARED_ENV, SHARED_SETUP),
              ("PAYMENT_PROVIDER", "PAYMENT_SECRET_KEY", "PAYMENT_PUBLIC_KEY", "BILLING_WEBHOOK_SECRET")),
         *_server_and_db("A subscriptions table that mirrors the provider's own status, written only "
                         "from its verified webhook, so the site never claims a plan it has not been "
                         "told about.", env=("DATABASE_PATH",))),
        ("Set PAYMENT_PROVIDER, PAYMENT_SECRET_KEY and PAYMENT_PUBLIC_KEY.",
         "Create the billing webhook with the provider and set BILLING_WEBHOOK_SECRET.",),
        "Invoices, dunning, proration and tax reporting are the provider's features and are not "
        "implemented here. Cancelling is mirrored from the webhook, not offered as a button that "
        "assumes success.",
        tags=("commerce",),
    ),
    Capability(
        "api", "API integrations and webhook endpoints",
        "Call another service from the server, and receive its callbacks with the signature checked.",
        ("api integration", "api", "rest api", "webhook", "webhooks", "third party", "third-party",
         "external service", "connect", "zapier", "sync"),
        (Part("server", SCAFFOLD,
              "A small outbound client that reads the base URL and token from the environment, times out, "
              "and surfaces the provider's status; plus POST /api/webhooks/{source} which rejects any "
              "payload whose signature does not match the shared secret.",
              (SHARED_SERVER, SHARED_ENV, SHARED_SETUP),
              ("EXTERNAL_API_BASE_URL", "EXTERNAL_API_TOKEN", "WEBHOOK_SECRET")),
         *_server_and_db("A delivery table for received webhooks, so a callback can be replayed after a "
                         "crash instead of being lost with the request.",
                         env=("DATABASE_PATH",)),
         Part("integration", NEEDS_SETUP,
              "Each provider's own account, token scope and callback URL are yours to create; the "
              "generated code names the variables and refuses to run without them.",
              (SHARED_ENV, SHARED_SETUP),
              ("EXTERNAL_API_BASE_URL", "EXTERNAL_API_TOKEN", "WEBHOOK_SECRET")),),
        ("Create the API token with the smallest scope that does the job and put it in the environment.",
         "Register the callback URL at the provider and copy its signing secret into WEBHOOK_SECRET.",),
        "No provider-specific business logic is written: the shape is a signed, retried, logged call. "
        "Rate-limit budgeting, OAuth token refresh and idempotency keys across services are yours to "
        "design.",
        tags=("integration",),
    ),
    Capability(
        "layout", "Responsive navigation and accessible layouts",
        "A nav that works at every width, a page that reads in order, and keyboard paths that actually go.",
        ("navigation", "nav", "responsive", "mobile menu", "hamburger", "accessible", "accessibility",
         "a11y", "keyboard", "screen reader", "semantic", "layout", "skip link"),
        (Part("page", GENERATED,
              "A nav bar with a real disclosure button under the breakpoint, a skip link, landmarks and "
              "headings in order, focus visible on every control, and motion that respects "
              "prefers-reduced-motion.",
              ("index.html",)),),
        ("Nothing to set up.",),
        "It fixes the page's own structure and controls. It cannot make third-party embeds accessible "
        "and is not a WCAG audit - the Security & Quality page's accessibility scan is the report.",
        tags=("page",),
    ),
)

BY_KEY: dict[str, Capability] = {c.key: c for c in CAPABILITIES}


def get(key: str) -> Capability | None:
    """The capability with this key, or None. Nothing here substitutes a near-miss for it."""
    return BY_KEY.get(str(key or ""))


def keys() -> tuple[str, ...]:
    return tuple(c.key for c in CAPABILITIES)


def _phrase_in(text: str, phrase: str) -> bool:
    """A whole-phrase hit, hyphen and space interchangeable, never a fragment inside a word.

    A trailing -s is tolerated on every word so "staff logins" and "carts" name the same features as
    the singular, which is how people actually write a brief.
    """
    body = r"[\s\-]+".join(rf"{re.escape(w)}s?" for w in phrase.split())
    return re.search(rf"(?<![a-z0-9]){body}(?![a-z0-9])", text) is not None


def match(text: str) -> list[dict]:
    """Which capabilities a sentence names, with the words that said it.

    Longest alias wins the match and the shorter ones on the same capability are not reported twice, so
    "e-commerce checkout" names one capability rather than three.
    """
    blob = f" {str(text or "").lower()} "
    found = []
    for cap in CAPABILITIES:
        hit = None
        for alias in sorted(cap.aliases, key=len, reverse=True):
            if _phrase_in(blob, alias):
                hit = alias
                break
        if hit:
            found.append({"key": cap.key, "label": cap.label, "matched": hit, "status": cap.status})
    found.sort(key=lambda row: -len(row["matched"]))
    return found


def card(cap: Capability) -> dict:
    """One capability as the UI draws it: what it is, what it needs, how far this product takes it."""
    return {
        "key": cap.key, "label": cap.label, "blurb": cap.blurb, "status": cap.status,
        "status_label": STATE_LABEL[cap.status], "needs": list(cap.needs), "tags": list(cap.tags),
        "aliases": list(cap.aliases)[:8],
        "parts": [{"surface": p.surface, "state": p.state, "detail": p.detail, "files": list(p.files),
                   "env": list(p.env)} for p in cap.parts],
        "files": list(cap.files), "env": list(cap.env), "setup": list(cap.setup), "limits": cap.limits,
    }


def cards() -> list[dict]:
    return [card(c) for c in CAPABILITIES]


def catalog() -> dict:
    """The whole honest picture, in one payload."""
    return {
        "capabilities": cards(),
        "surfaces": list(SURFACES),
        "states": [{"state": s, "label": STATE_LABEL[s]} for s in STATES],
        "shared_files": list(SHARED_FILES),
        "counts": {"capabilities": len(CAPABILITIES),
                   **{s: sum(1 for c in CAPABILITIES if c.status == s) for s in STATES}},
    }
