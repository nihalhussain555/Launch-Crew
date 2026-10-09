"""The audit crew: what each deterministic scanner reports, and how the agents and repair loop use them."""
import json
import re

import pytest

from app.agents.audits import DependencyAgent
from app.orchestrator.graph import AUDIT_ORDER, Orchestrator
from app.tools import audit_a11y, audit_perf, audit_security, audit_seo, audit_util as au
from app.tools import dependency_scan, secret_scan
from app.tools.sanitizer import sanitize_html
from tests.conftest import BAD_CHECKS, GOOD_CHECKS
from tests.test_orchestrator import patch_checks

# A page that does the things the crew is asked not to do: it reaches off-site, frames another site,
# carries a key, and is unusable by keyboard.
DIRTY = """<!doctype html><html><head><title>x</title>
<link rel="stylesheet" href="https://cdn.example.com/a.css">
<script src="https://cdn.example.com/app.js"></script></head>
<body><iframe src="https://evil.example"></iframe>
<a href="https://other.example" target="_blank">partner</a>
<form action="https://collect.example/submit"><input type="password" name="pw"></form>
<script>const k="gsk_abcdefghijklmnopqrstuvwxyz12";fetch("/track")</script>
<div onclick="steal()">click me</div>
<img src="https://cdn.example.com/p.png">
</body></html>"""

_DESCRIPTION = "A habit tracker built around night-shift schedules, so small wins survive odd hours. "
CLEAN = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width, initial-scale=1">'
         '<title>Habit Tracker for night shift workers</title>'
         f'<meta name="description" content="{_DESCRIPTION}">'
         '<meta property="og:title" content="Habit Tracker">'
         '<meta property="og:description" content="Built for nights">'
         '<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebSite",'
         '"name":"Habit Tracker"}</script></head>'
         '<body><a class="skip-link" href="#lc-main">Skip to content</a>'
         '<main id="lc-main"><nav aria-label="Sections"><a href="#lc-main">Top</a></nav>'
         '<h1>Habit Tracker</h1><h2>How it works</h2>'
         '<p>Track a streak, keep the win. Night shift friendly. </p><p>' + "Small steps, counted daily. " * 10 + '</p>'
         '<a href="#cta">See pricing</a><button id="cta" type="button">Get early access</button>'
         '<style>:focus-visible{outline:3px solid #22d3ee}</style></main></body></html>')


def one(findings, id_):
    return next((f for f in findings if f["id"] == id_), None)


def statuses(findings):
    return {f["id"]: f["status"] for f in findings}


def failed(findings):
    return {f["id"] for f in findings if f["status"] == au.FAIL}


# ------------------------------------------------------------------------ security
def test_security_audit_names_every_off_site_and_unsafe_thing():
    f = audit_security.scan(DIRTY)
    assert {"no_external", "no_frames", "opener", "credentials_collected", "secret_material",
            "script_apis", "csp"} <= failed(f), statuses(f)
    assert statuses(f)["handlers"] == au.WARN
    assert "gsk_abcdefghijklmnopqrstuvwxyz12" not in json.dumps(f)   # the report says where, never what


def test_the_sanitizer_catches_some_things_and_the_audit_reports_the_rest():
    clean, _ = sanitize_html(DIRTY)
    f = audit_security.scan(clean, files={"index.html": clean})
    assert statuses(f)["csp"] == au.PASS and statuses(f)["no_external"] == au.PASS
    assert statuses(f)["script_apis"] == au.PASS          # the fetch() script was removed wholesale
    assert statuses(f)["secret_material"] == au.PASS      # ...and the key left the file with it
    assert statuses(f)["form_action"] == au.WARN          # action="#" is safe, but stores nothing
    assert failed(f) == {"opener", "credentials_collected"}    # the sanitizer does not fix these


def test_secret_scan_reports_where_a_key_is_never_what_it_is():
    hits = secret_scan.find_secrets('api_key = "sk-abcdefghijklmnopqrstuvwxy"\npassword: "Hunter2Hunt3rX"\n')
    assert {h["id"] for h in hits} >= {"openai_style_key", "assignment"}
    assert all(h["line"] > 0 and h["file"] for h in hits)
    assert all("sk-abc" not in json.dumps(h) and "Hunter2" not in json.dumps(h) for h in hits)


def test_secret_scan_ignores_placeholders_and_empties():
    assert secret_scan.find_secrets('api_key = "change-me-please-1234567890"') == []
    assert secret_scan.find_secrets("") == []


# ------------------------------------------------------------------------ seo
def test_seo_audit_asks_for_the_exact_missing_head_tags():
    stripped = CLEAN.replace('<meta name="description"', '<meta name="x-description"')
    f = audit_seo.scan(stripped, keywords=("night shift",), name="Habit Tracker", headline="Habit Tracker")
    rep = au.report("seo", "SEO audit", f, version=1)
    assert statuses(f)["description"] == au.FAIL and statuses(f)["social_preview"] == au.WARN
    assert one(f, "description")["fix"].startswith('Add in <head>: <meta name="description"')
    assert all(fix["agent"] == "engineer" for fix in rep["fixes"])


def test_seo_audit_passes_a_complete_page_and_only_informs_about_indexing():
    f = audit_seo.scan(CLEAN, keywords=("night shift",), name="Habit Tracker", headline="Habit Tracker",
                       subheadline="Built for nights", deploy_url="https://example.netlify.app")
    assert statuses(f)["indexing"] == au.INFO
    assert "example.netlify.app" in one(f, "indexing")["detail"]
    assert failed(f) == set(), [x for x in f if x["status"] == au.FAIL]
    assert "canonical" not in json.dumps([x["label"] for x in f]).lower()   # sanitizer drops <link>


def test_seo_suggestion_and_jsonld_are_usable_text():
    desc = audit_seo.suggest_description("Habit Tracker", "Small wins for people who work overnight.")
    assert 40 <= len(desc) <= 160
    assert json.loads(audit_seo.jsonld("Habit Tracker", desc, "https://x.app"))["@type"] == "WebSite"


# ------------------------------------------------------------------------ accessibility
def test_accessibility_audit_fails_unusable_markup():
    f = audit_a11y.scan(DIRTY)
    assert {"lang", "img_alt", "keyboard_click", "landmark_main", "zoom"} <= failed(f), statuses(f)
    # a skip link only matters once there is a navigation block to skip
    assert statuses(f)["skip_link"] == au.PASS
    nav = DIRTY.replace("<body>", '<body><nav aria-label="Main"><a href="#a">A</a></nav>', 1)
    assert statuses(audit_a11y.scan(nav))["skip_link"] == au.WARN


def test_accessibility_audit_carries_the_browsers_measurements():
    f = audit_a11y.scan(CLEAN, measured=BAD_CHECKS)
    assert statuses(f)["contrast"] == au.FAIL and "real browser" in one(f, "contrast")["label"]
    assert "bad" in one(f, "contrast")["detail"]
    assert one(audit_a11y.scan(CLEAN), "contrast") is None      # nothing measured, nothing claimed


def test_accessibility_audit_passes_a_structured_page():
    measured = [{**c, "passed": True, "detail": ""} for c in BAD_CHECKS] + GOOD_CHECKS
    f = audit_a11y.scan(CLEAN, measured=measured)
    assert statuses(f)["contrast"] == au.PASS and statuses(f)["skip_link"] == au.PASS
    assert failed(f) == set(), [x for x in f if x["status"] == au.FAIL]


# ------------------------------------------------------------------------ performance
def _workspace_kb(findings) -> float:
    return float(re.search(r"([\d.]+) KB for the whole workspace", one(findings, "payload")["detail"]).group(1))


def test_performance_audit_counts_the_whole_workspace_not_just_the_page():
    page_only = audit_perf.scan(CLEAN)
    with_assets = audit_perf.scan(CLEAN, assets={"styles.css": "x" * 40_000, "app.js": "y" * 40_000})
    assert _workspace_kb(with_assets) - _workspace_kb(page_only) > 70
    assert statuses(with_assets)["requests"] == au.PASS          # self-contained: one file, no third parties
    assert "Estimate" in one(with_assets, "transfer")["detail"]   # labelled as an estimate, not a lab run


def test_performance_audit_reports_measured_mobile_overflow_as_an_error():
    overflow = [{"id": "overflow", "label": "x", "viewport": "mobile", "passed": False,
                 "severity": "error", "detail": "375px viewport, 512px of content"}]
    f = audit_perf.scan(CLEAN, measured=overflow)
    assert statuses(f)["overflow"] == au.FAIL and "512" in one(f, "overflow")["detail"]


# ------------------------------------------------------------------------ dependencies
def test_dependency_audit_of_this_repo_reports_no_errors():
    f = dependency_scan.scan("<p>one self-contained file</p>")
    assert failed(f) == set(), [x for x in f if x["status"] == au.FAIL]
    advisories = one(f, "advisories")
    assert advisories["status"] == au.INFO and "does not" in advisories["detail"].lower()


def test_dependency_audit_spots_a_script_the_deliverable_cannot_run():
    f = dependency_scan.scan('<script src="https://cdn.example.com/react.js"></script>')
    assert statuses(f)["deliverable"] == au.FAIL


def test_dependency_findings_are_never_routed_into_a_page_rebuild():
    rep = au.report("dependency", "Dependency audit", dependency_scan.scan("<p>hi</p>"),
                    version=1, agent=DependencyAgent.fix_agent)
    assert rep["fixes"] == []
    assert any(x["fix"] for x in rep["findings"])                 # still written for the operator


# ------------------------------------------------------------------------ agents + pipeline
async def built(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    await Orchestrator(ctx).run_until_approval()
    events.clear()
    return ctx, events


async def test_audit_agents_record_version_stamped_reports_and_cost_no_tokens(make_ctx, monkeypatch):
    ctx, events = await built(make_ctx, monkeypatch)
    before_tokens = ctx.tokens_used
    await Orchestrator(ctx).audit(list(AUDIT_ORDER))

    s = ctx.state
    assert sorted(s.audits) == sorted(AUDIT_ORDER)
    assert all(r["version"] == s.html_version for r in s.audits.values())
    started = [e["agent"] for t, e in events if t == "agent_started"]
    assert started == ["security", "seo", "accessibility", "performance", "dependency", "tester"]
    assert [e["audit"]["kind"] for t, e in events if t == "audit_report"] == list(AUDIT_ORDER)
    assert events[-1][0] == "awaiting_approval"
    assert ctx.tokens_used == before_tokens                        # deterministic: no model called
    assert s.tests["ran"] is True and s.tests["failed"] == 0 and s.tests["version"] == s.html_version
    assert s.tests["file"]["name"] == "tests/test_page.py"
    compile(s.tests["file"]["text"], "test_page.py", "exec")        # the file is real Python


async def test_repair_applies_open_findings_and_the_scores_rise(make_ctx, monkeypatch):
    ctx, _ = await built(make_ctx, monkeypatch)
    orch = Orchestrator(ctx)
    await orch.audit(list(AUDIT_ORDER))
    s = ctx.state
    assert sum(len(s.audits[k]["fixes"]) for k in ("seo", "accessibility")) >= 2

    before_html, before_version = s.html, s.html_version
    await orch.repair(list(AUDIT_ORDER))

    assert s.html != before_html and s.html_version == before_version + 1
    assert all(r["version"] == s.html_version for r in s.audits.values())   # re-measured, not left stale
    assert failed(audit_seo.scan(s.html)) == set()
    assert 'name="description"' in s.html and "application/ld+json" in s.html
    assert s.tests["version"] == s.html_version and s.tests["failed"] == 0
    assert s.chat[-1]["text"].startswith("Audit repair:")
    assert s.check_summary["errors"] == 0                            # the critic still passes the page


async def test_repair_ignores_reports_measured_against_an_older_build(make_ctx, monkeypatch):
    ctx, events = await built(make_ctx, monkeypatch)
    orch = Orchestrator(ctx)
    await orch.audit(["seo"])
    ctx.state.audits["seo"]["version"] = ctx.state.html_version + 1
    events.clear()

    await orch.repair(["seo"])
    assert ctx.state.html_version == 1                               # nothing was rebuilt
    assert "Nothing to repair" in next(e["message"] for t, e in events if t == "agent_message")


async def test_audit_needs_a_page_and_a_known_kind(make_ctx):
    ctx, _ = make_ctx()
    orch = Orchestrator(ctx)
    with pytest.raises(ValueError, match="no built page"):
        await orch._run_audits(["seo"])
    with pytest.raises(ValueError, match="Unknown audit"):
        await orch._run_audits(["seo", "ghost"])


# ------------------------------------------------------------------------ readiness
def test_readiness_counts_only_current_version_audits():
    from types import SimpleNamespace as NS

    from app.orchestrator.readiness import compute_readiness
    state = NS(check_results=[1], check_summary={"errors": 0, "warnings": 0}, panel={"avg_score": 9, "signups": 3,
              "reactions": [1, 2, 3, 4]}, sanitizer_violations=[], html_version=2,
              audits={"seo": {"kind": "seo", "version": 2, "score": 90, "label": "SEO audit"},
                      "security": {"kind": "security", "version": 1, "score": 40, "label": "Security audit"}})
    audits = next(c for c in compute_readiness(state)["components"] if c["id"] == "audits")
    assert audits["score"] == 18 and "seo 90" in audits["detail"]
    assert "security" not in audits["detail"]
