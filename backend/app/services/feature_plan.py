"""What a sentence about features means as a build - or the reason it cannot mean one.

The brief asks for plain-English feature requests. A model could answer that, and its answer would be a
guess about whether the code exists. This module is deliberately not a model: it reads the capability
catalog in `app/agents/capabilities.py`, so every key it returns names source that
`app/services/feature_templates.py` really writes, and every count it reports is measured from those
bytes rather than asserted.

Three rules hold the whole thing honest:

* A request naming nothing is refused with the words that do work. Nothing is substituted for a
  near-miss, because "I added a blog" after a sentence that asked for one is only checkable next release.
* An unknown key asked for explicitly is refused too. Dropping it quietly would let a plan read as if
  the user's list had been honoured.
* Dependencies are added *and said*: profiles and admin need accounts, so `authentication` joins the
  build and the plan names it as a feature the user did not ask for by name.

The plan also splits each capability by surface - frontend, backend, database, external - and reports
the weakest state as its own, which is how a cart whose payment provider is unconfigured stays "needs
your account or keys" instead of becoming "shopping cart implemented".
"""
from __future__ import annotations

from app.agents import capabilities as caps
from app.services import feature_blocks as blocks
from app.services import feature_templates as templates
from app.services.workspace_manager import WorkspaceError

MAX_REQUEST_CHARS = 500
MAX_KEYS = 16
MAX_WARNINGS = 12

# The brief's own four words for a surface, so the plan answers "does this need frontend changes,
# backend logic, database changes, or external integrations?" in the order it asks.
NEED_WORDS = {"page": "frontend changes", "server": "backend logic",
              "database": "database changes", "integration": "external integrations"}

_STATUS_RANK = {caps.GENERATED: 0, caps.SCAFFOLD: 1, caps.NEEDS_SETUP: 2}


def _labels(keys) -> str:
    return ", ".join(caps.get(key).label for key in caps.keys() if key in set(keys))


def _checked(keys) -> list[str]:
    """Explicit keys are verified one by one. An unknown one is a refusal, never a silent drop."""
    out: list[str] = []
    for raw in keys or ():
        key = str(raw or "").strip().lower()
        if not key:
            continue
        if caps.get(key) is None:
            raise WorkspaceError(
                f"'{key[:40]}' is not a feature Launch Crew has source for, so it will not be built - "
                f"and it will not be replaced by something close. Ask for one of: "
                f"{', '.join(caps.get(k).label for k in caps.keys())}.", 422)
        if key not in out:
            out.append(key)
    if len(out) > MAX_KEYS:
        raise WorkspaceError(f"Too many features in one request (max {MAX_KEYS}).", 422)
    return out


def named(request: str) -> list[dict]:
    """The capabilities a sentence names, with the phrase that named each. Words only: no keys chosen."""
    return caps.match(request or "")


def resolve(request: str, *, keys: list[str] | None = None, include: list[str] | None = None,
            site: str = "", idea: str = "") -> dict:
    """Keys to build, in catalog order, plus what each one costs. Refuses when the answer is nothing.

    `keys` is what the user or the wizard picked; `request` is what they wrote. Either alone is enough.
    With both, the picked list wins and the sentence is still searched, so a click on "Contact form"
    beside a sentence that also mentions a blog reports both rather than whichever arrived first.
    """
    asked = _checked(keys)
    words = named(request)
    if include:
        asked = list(dict.fromkeys(asked + _checked(include)))
    for row in words:
        if row["key"] not in asked:
            asked.append(row["key"])
    if not asked:
        raise WorkspaceError(
            f"Nothing in “{(request or '').strip()[:160]}” names a feature this product can build. "
            f"Ask for one of: {_labels(caps.keys())}.", 422)
    out = build(asked, request=request, matched=words, site=site, idea=idea)
    # What the user can be credited with asking for, before dependencies grew the list. A caller that
    # rebuilds this set - `feature_build.plan` unions it with the keys already on the page - passes it
    # back as `origin`, so "pulled in by a dependency" stays true after the union.
    out["origin"] = list(asked)
    return out


def build(asked: list[str], *, request: str = "", matched: list[dict] | None = None,
          site: str = "", idea: str = "", origin: list[str] | None = None) -> dict:
    """The plan for a set of keys the caller has already vouched for.

    `origin` is the part of that set the user asked for; the difference between it and the built set is
    reported as pulled in by a dependency and quoted into FEATURES.md. Left unset it is the asked list,
    which is the right answer for a caller planning straight from a request.
    """
    picked = templates.chosen(asked)              # dependency-expanded, catalog order
    if not picked:
        raise WorkspaceError("No feature was left to plan.", 422)
    wanted = set(origin) if origin is not None else set(asked)
    grown = [key for key in picked if key not in wanted]
    rows = templates.route_map(picked)

    needs: dict[str, list[str]] = {}
    for key in picked:
        for surface in caps.get(key).needs:
            needs.setdefault(surface, []).append(key)
    statuses = {row["key"]: row["status"] for row in rows}
    overall = max(statuses.values(), key=lambda s: _STATUS_RANK[s])
    server = templates.needs_server(picked)
    has_panels = any(blocks.PAGE.get(key) for key in picked)

    warnings: list[str] = []
    if grown:
        warnings.append("Pulled in because the features you named depend on it: "
                        + _labels(grown) + ".")
    if server:
        warnings.append(
            "The panels that call an API work when the page is opened through the generated server.py. "
            "They cannot reach it from Launch Crew's own published preview, because a published page is "
            "not allowed to make network calls at all.")
    for row in rows:
        cap = caps.get(row["key"])
        if row["status"] != caps.GENERATED:
            warnings.append(f"{row['label']} - {caps.STATE_LABEL[row['status']]}. {cap.limits}")
        if not blocks.PAGE.get(row["key"]):
            warnings.append(f"{row['label']} writes no panel: it is endpoints and records only.")
        if cap.env:
            warnings.append(f"{row['label']} reads: {', '.join(cap.env)}.")
    if not has_panels:
        warnings.append("No page markup for this set: every feature asked for lives behind its API.")

    # The three fields FEATURES.md quotes. Fixed here rather than at build time so the byte counts this
    # plan reports are the bytes the build later writes: a plan that measured a different document than
    # the one shipped would make every number in the review a rough estimate.
    doc = {"request": (request or "").strip()[:MAX_REQUEST_CHARS], "added": grown,
           "warnings": warnings[:MAX_WARNINGS]}
    files = templates.compose(picked, site=site, idea=idea or request, plan=doc)
    page_markup = files.get(templates.PAGE_SECTIONS, "")

    out = {
        "request": doc["request"],
        "doc": doc,
        "keys": list(picked),
        "named": sorted(wanted & set(picked)),
        "added": grown,
        "matched": [row["matched"] for row in (matched or []) if row["key"] in set(picked)],
        "features": rows,
        "statuses": statuses,
        "overall": overall,
        "overall_label": caps.STATE_LABEL[overall],
        "needs": needs,
        "need_words": [NEED_WORDS[s] for s in caps.SURFACES if s in needs],
        "server": server,
        "files": [{"name": name, "bytes": len(text.encode("utf-8", "ignore")),
                   "role": "page" if name == templates.PAGE_SECTIONS else "source",
                   "language": name.rsplit(".", 1)[-1] if "." in name else "text"}
                  for name, text in sorted(files.items())],
        "total_bytes": sum(len(text.encode("utf-8", "ignore")) for text in files.values()),
        "page_bytes": len(page_markup.encode("utf-8", "ignore")),
        "env": list(templates.required_env(picked)) if server else [],
        "routes": {row["key"]: row["routes"] for row in rows if row["routes"]},
        "tables": {row["key"]: row["tables"] for row in rows if row["tables"]},
        "setup": {row["key"]: row["setup"] for row in rows if row["setup"]},
        "warnings": doc["warnings"],
    }
    out["summary"] = summarise(out)
    return out


def summarise(plan: dict) -> str:
    """One line for history and the approval panel: what it is, how far it goes, what it costs."""
    labels = [caps.get(key).label for key in plan["keys"]]
    head = ", ".join(labels[:3]) + (f" (+{len(labels) - 3} more)" if len(labels) > 3 else "")
    parts = [", ".join(plan["need_words"]) or "frontend changes"]
    waiting = sum(1 for status in plan["statuses"].values() if status != caps.GENERATED)
    tail = (f"{len(plan['files'])} files, {plan['total_bytes']:,} bytes"
            + (f", {waiting} still needing setup" if waiting else ", nothing left to set up"))
    return f"{head}: {', '.join(parts)} - {plan['overall_label']}; {tail}."[:240]
