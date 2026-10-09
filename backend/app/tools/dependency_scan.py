"""Dependency audit: what this build actually pulls in, and what the stack around it declares.

Two halves, both measured from files on disk:
  * the deliverable - the generated page, which should reference nothing;
  * the host stack - backend requirements and the frontend manifest, checked for pinning, imports
    no manifest declares, declared packages nothing imports, and installed versions.

No vulnerability advisory database is bundled and nothing phones home, so the report says that
plainly and names the command to run instead of pretending to have checked.
"""
from __future__ import annotations

import ast
import importlib.metadata as md
import json
import re
import sys
from pathlib import Path

from app.tools import audit_util as au

BACKEND_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"

# distribution name -> import name, where they differ
ALIASES = {"beautifulsoup4": "bs4", "pyjwt": "jwt", "pillow": "PIL", "scikit-learn": "sklearn",
           "opencv-python": "cv2", "python-dotenv": "dotenv", "pyyaml": "yaml"}
LOCAL_ROOTS = {"app", "tests", "conftest", "main"}
_REQ_LINE = re.compile(r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._\-]*(?:\[[^\]]+\])?)\s*(?P<spec>[<>=!~].*)?$")


def import_name(dist: str) -> str:
    base = dist.strip()
    if base.lower() in ALIASES:
        return ALIASES[base.lower()]
    return re.sub(r"[._-]+", "_", base.split("[")[0].strip())


def parse_requirements(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _REQ_LINE.match(line)
        if m:
            out.append({"name": m["name"], "spec": (m["spec"] or "").strip(), "raw": line})
    return out


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", value.split("+")[0])[:4]) or (0,)


def satisfies(installed: str, spec: str) -> bool:
    """Small specifier check for the pinned forms this project uses (==, >=, <=, >, <, !=, ~=)."""
    for clause in (spec or "").split(","):
        m = re.match(r"(===|==|>=|<=|~=|!=|>|<)?\s*([A-Za-z0-9._\-*]+)", clause.strip())
        if not m:
            continue
        op, want = m.group(1) or "==", m.group(2)
        if want == "*":
            continue
        a, b = list(_version_tuple(installed)), list(_version_tuple(want))
        n = max(len(a), len(b))
        a += [0] * (n - len(a))
        b += [0] * (n - len(b))
        if op in ("==", "===") and a != b:
            return False
        if op == ">=" and a < b:
            return False
        if op == "<=" and a > b:
            return False
        if op == "<" and a >= b:
            return False
        if op == ">" and a <= b:
            return False
        if op == "!=" and a == b:
            return False
        if op == "~=" and (a[:2] < b[:2] or a < b):
            return False
    return True


def python_imports(root: Path) -> dict[str, str]:
    """{top-level module: first file that imports it} for code under `root`."""
    found: dict[str, str] = {}
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] if node.level == 0 else []
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top and top not in stdlib and top not in LOCAL_ROOTS and top not in found:
                    found[top] = path.relative_to(root).as_posix()
    return found


def _installed(dist: str) -> str | None:
    try:
        return md.version(dist)
    except Exception:  # noqa: BLE001 - PackageNotFoundError or broken metadata
        return None


def _providers() -> dict[str, list[str]]:
    """{top-level module: distributions that install it} as this interpreter sees them."""
    try:
        return {k.lower(): list(v) for k, v in md.packages_distributions().items()}
    except Exception:  # noqa: BLE001 - older/broken metadata
        return {}


def scan(html: str, *, backend_root: Path | None = None, frontend_root: Path | None = None) -> list[dict]:
    backend_root = backend_root or BACKEND_ROOT
    frontend_root = frontend_root or FRONTEND_ROOT
    findings: list[dict] = []

    refs = au.external_refs(html)
    findings.append(au.ok("deliverable", "The shipped page has no runtime dependencies",
                          "index.html loads itself: no CDN script, no framework, no build step, nothing to install.")
                    if not refs else
                    au.finding("deliverable", "The shipped page has no runtime dependencies", au.FAIL,
                               "Page references: " + ", ".join(refs[:5]),
                               "Remove the external references so the deliverable has nothing to install or fetch."))

    req_file, dev_file = backend_root / "requirements.txt", backend_root / "requirements-dev.txt"
    if not req_file.exists():
        findings.append(au.finding("manifest", "Backend dependency manifest", au.FAIL,
                                   f"No requirements.txt next to the running service ({req_file}).",
                                   "Restore requirements.txt: an unlisted environment cannot be rebuilt."))
        return findings

    reqs = parse_requirements(req_file.read_text(encoding="utf-8"))
    dev_reqs = parse_requirements(dev_file.read_text(encoding="utf-8")) if dev_file.exists() else []
    pinned = [r for r in reqs if r["spec"].startswith("==")]
    findings.append(au.ok("manifest", "Backend dependency manifest",
                          f"{len(reqs)} declared in requirements.txt, {len(pinned)} pinned exactly, "
                          f"{len(dev_reqs)} dev-only"))

    loose = [r for r in reqs if r["spec"] and not r["spec"].startswith("==")]
    findings.append(au.ok("pinning", "Runtime pins are exact", f"{len(pinned)}/{len(reqs)} use ==")
                    if not loose else
                    au.finding("pinning", "Runtime pins are exact", au.WARN,
                               "Open ranges: " + ", ".join(r["raw"] for r in loose[:4]) +
                               ". A fresh install can pull a version nobody ran the tests against.",
                               "Pin the remaining ranges to the versions this build was tested with, or add a "
                               "pip-compile lockfile next to requirements.txt."))

    declared = {import_name(r["name"]): r for r in reqs}
    dev_only_names = {import_name(r["name"]) for r in dev_reqs} - set(declared)
    imports = python_imports(backend_root / "app")
    providers = _providers()
    declared_dists = {r["name"].split("[")[0].lower() for r in reqs} | {r["name"].split("[")[0].lower() for r in dev_reqs}

    undeclared, dev_only, indirect = [], [], []
    for mod, where in sorted(imports.items()):
        if mod in declared:
            continue
        if mod in dev_only_names:
            dev_only.append(f"{mod} ({where})")
            continue
        # bson ships inside pymongo, jwt inside PyJWT: the import is fine as long as the parent is declared.
        sources = providers.get(mod, [])
        if sources and not any(d.lower() in declared_dists for d in sources):
            indirect.append(f"{mod} ({where}, from {sources[0]})")
        elif not sources and not (_installed(mod) or _installed(mod.replace("_", "-"))):
            undeclared.append(f"{mod} ({where})")

    if undeclared:
        findings.append(au.finding("undeclared", "Every import is declared in a manifest", au.FAIL,
                                   "Not declared and not installed here either: " + ", ".join(undeclared[:4]),
                                   "Add these to requirements.txt at the version currently installed."))
    elif indirect:
        findings.append(au.finding("undeclared", "Every import is declared in a manifest", au.WARN,
                                   "Imported but only present as someone else's dependency: " + ", ".join(indirect[:4]) +
                                   ". The import works today; a bump of the package that provides it can drop it.",
                                   "Declare these directly in requirements.txt so the install is explicit."))
    elif dev_only:
        findings.append(au.finding("undeclared", "Every import is declared in a manifest", au.WARN,
                                   "Runtime code can import a dev-only package: " + ", ".join(dev_only[:3]) +
                                   ". With a real MONGO_URI that branch never runs, but mock:// in production fails "
                                   "at startup.",
                                   "Keep the dev-only import behind the same runtime guard, and fail fast with a clear "
                                   "message if the dev package is missing."))
    else:
        findings.append(au.ok("undeclared", "Every import is declared in a manifest",
                              f"{len(imports)} top-level module(s) imported by app/, all accounted for"))

    drift = []
    for mod, req in declared.items():
        got = _installed(req["name"].split("[")[0])
        if got is None:
            drift.append(f"{req['name']} is not installed here")
        elif req["spec"] and not satisfies(got, req["spec"]):
            drift.append(f"{req['name']}: installed {got}, declared {req['raw']}")
    findings.append(au.ok("installed", "Installed environment matches the manifest", f"{len(declared)} checked")
                    if not drift else
                    au.finding("installed", "Installed environment matches the manifest", au.WARN,
                               "; ".join(drift[:4]),
                               "Reinstall with pip install -r requirements.txt, or update the pin to what runs."))

    never = [req["name"] for mod, req in declared.items() if mod not in imports]
    findings.append(au.ok("unused", "Declared packages are imported somewhere", f"{len(never)} unimported")
                    if not never else
                    au.finding("unused", "Declared packages are imported somewhere", au.INFO,
                               "Never imported by app/: " + ", ".join(never[:5]) +
                               ". Some are indirect (email-validator powers EmailStr, uvicorn[standard] pulls extras), "
                               "so this is a review list, not a delete list.",
                               severity=au.INFO_SEVERITY))

    findings.append(au.finding("advisories", "Vulnerability advisories", au.INFO,
                               "This audit does not ship an advisory database and makes no network calls, so it cannot "
                               "say whether a pinned version has a published CVE. Run `pip install pip-audit && "
                               "pip-audit -r requirements.txt` and `npm audit` in the frontend to close that gap.",
                               severity=au.INFO_SEVERITY))

    pkg = frontend_root / "package.json"
    if not pkg.exists():
        findings.append(au.finding("frontend", "Frontend manifest", au.INFO,
                                   f"No package.json at {frontend_root} - expected for a backend-only deployment.",
                                   severity=au.INFO_SEVERITY))
        return findings

    data = json.loads(pkg.read_text(encoding="utf-8"))
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    runtime = data.get("dependencies", {})
    lock = (frontend_root / "package-lock.json").exists()
    findings.append(au.ok("frontend", "Frontend manifest and lockfile",
                          f"{len(deps)} package(s); lockfile {'present' if lock else 'missing'}"))
    if not lock and deps:
        findings.append(au.finding("frontend_lock", "Frontend install is reproducible", au.FAIL,
                                   "^ ranges with no package-lock.json, so npm install resolves differently per machine.",
                                   "Commit package-lock.json and install with npm ci."))

    src = frontend_root / "src"
    bundle = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                       for p in list(src.rglob("*.js")) + list(src.rglob("*.jsx")) + list(frontend_root.glob("vite.config.js")))
    unused_fe = [name for name in runtime if not re.search(rf"""from\s*["']{re.escape(name)}(?:/[^"']*)?["']""", bundle)]
    findings.append(au.ok("frontend_unused", "Every runtime dependency is imported", f"{len(runtime)} checked")
                    if not unused_fe else
                    au.finding("frontend_unused", "Every runtime dependency is imported", au.INFO,
                               "Not imported by src/: " + ", ".join(unused_fe[:4]) +
                               ". A dev-only entry or a re-export can look unused from here.",
                               severity=au.INFO_SEVERITY))
    return findings
