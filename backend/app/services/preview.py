"""Preview lifecycle for one run's published page: can this environment run it, and who is allowed to look.

Two isolated ways to see a generated page, and neither one runs inside the Launch Crew app's origin:

  * the embedded frame in the Code Workspace - `srcDoc` inside `sandbox="allow-scripts"`, which gives the
    page an opaque origin, so it cannot read this app's localStorage, its cookies or its same-origin APIs;
  * an expiring, revocable, single-run link served with `Content-Security-Policy: sandbox allow-scripts`
    for "open in a new tab". The link carries its own random token, so it needs no login and grants access
    to exactly one published file for one short window.

Nothing here starts a server, a container or a build: a Launch Crew project is static HTML, and a file set
that would need a build step before it renders is reported as unsupported rather than shown as something it
is not. Callers get the same verdict from `support()` before any preview is offered.
"""
from __future__ import annotations

import hashlib
import re
import secrets

# Owner routes and the public content route share these limits.
TOKEN_RE = re.compile(r"\A[A-Za-z0-9_-]{16,64}\Z")
MAX_TICKETS_PER_RUN = 5
TTL_SECONDS = 300
CANONICAL = "index.html"

# Extensions a browser renders as they are written - no compiler, no package install, no server process.
STATIC = {"html", "htm", "css", "js", "mjs", "cjs", "svg", "png", "jpg", "jpeg", "gif", "webp", "avif",
          "ico", "md", "txt", "json", "webmanifest", "woff", "woff2", "ttf", "otf"}
# Files whose presence means something has to be built or served before the page exists.
BUILD_MARKERS = {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "requirements.txt",
                 "pyproject.toml", "setup.py", "gemfile", "go.mod", "composer.json", "pom.xml",
                 "build.gradle", "cargo.toml", "dockerfile", "docker-compose.yml", "makefile", "webpack.config.js",
                 "vite.config.js", "vite.config.ts", "next.config.js", "nuxt.config.ts", "svelte.config.js",
                 "angular.json", "tailwind.config.js", "postcss.config.js", "tsconfig.json"}
# Source languages that are only a page after a compiler touches them.
NEEDS_BUILD = {"jsx", "tsx", "ts", "vue", "svelte", "astro", "py", "rb", "go", "rs", "java", "kt", "kts",
               "scala", "php", "cs", "c", "cpp", "swift", "ipynb", "dart", "clj", "ex", "exs"}

KINDS = ("static-page", "no-page", "needs-build", "empty")


def extension(name: str) -> str:
    tail = name.rsplit(".", 1)
    return tail[1].lower() if len(tail) > 1 and tail[1] else ""


def support(files: list[dict]) -> dict:
    """Can this file set actually render here? Answers with the evidence, never with a placeholder page.

    `blocked` names the specific files that make the answer no, so the UI can say why instead of showing
    a preview of nothing.
    """
    names = [str(f.get("name") or "") for f in files if f.get("name")]
    if not names:
        return {"supported": False, "kind": "empty", "entry": None, "blocked": [],
                "reason": "No files have been published for this run yet, so there is nothing to preview."}
    lowered = [n.lower() for n in names]
    markers = sorted({n for n in lowered if n in BUILD_MARKERS})
    sources = sorted({n for n in lowered if extension(n) in NEEDS_BUILD})
    if markers or sources:
        blocked = markers + [n for n in sources if n not in markers]
        return {"supported": False, "kind": "needs-build", "entry": None, "blocked": blocked,
                "reason": f"These files must be compiled or served before they render ({', '.join(blocked[:6])}). "
                          f"The preview environment runs static files only, so no page is shown rather than a "
                          f"broken or fake one."}
    entry = CANONICAL if CANONICAL in lowered else next((n for n in lowered if extension(n) in {"html", "htm"}), None)
    if not entry:
        return {"supported": False, "kind": "no-page", "entry": None, "blocked": sorted(lowered),
                "reason": "This workspace has no HTML document to load, so there is nothing to preview."}
    stray = sorted(n for n in lowered if extension(n) not in STATIC and n != "readme.md")
    if stray:
        return {"supported": False, "kind": "needs-build", "entry": None, "blocked": stray,
                "reason": f"These files are not static assets the preview can serve ({', '.join(stray[:6])})."}
    return {"supported": True, "kind": "static-page", "entry": entry, "blocked": [],
            "reason": "A static page plus its assets: the browser in front of you is the execution environment."}


def new_token() -> str:
    return secrets.token_urlsafe(24)


def token_hash(token: str) -> str:
    """Tickets are stored as digests: a read of the previews collection cannot hand out a live link."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.match(token or ""))
