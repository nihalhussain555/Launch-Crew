"""The audit crew: six agents that measure the built page and write a report into run state.

None of them calls a model. Each one takes the page (plus the Critic's Chromium measurements where
a property only shows up when rendered) and returns findings, so an audit costs no tokens, repeats
identically, and can be re-run after a repair to prove the fix landed.

Reports land in `state.audits[kind]` tagged with the `html_version` they were taken at, so the UI
can say "this report is for v3, the page is now v4" instead of showing a stale verdict.
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.tools import audit_a11y, audit_perf, audit_security, audit_seo, audit_util as au
from app.tools import dependency_scan, testgen


class AuditAgent(BaseAgent):
    """One audit. Subclasses name themselves, measure, and the shared run() does the rest."""

    kind = ""
    label = ""
    fix_agent = "engineer"      # who receives the fix instructions when this audit repairs the page

    async def measure(self, ctx) -> tuple[list[dict], dict]:
        """Return (findings, evidence)."""
        raise NotImplementedError

    async def run(self, ctx) -> str:
        s = ctx.state
        if not s.html:
            raise ValueError(f"{self.label}: there is no built page to audit yet.")
        findings, evidence = await self.measure(ctx)
        report = au.report(self.kind, self.label, findings, version=s.html_version,
                           evidence=evidence, agent=self.fix_agent)
        s.audits[self.kind] = report
        await ctx.emit("audit_report", audit=report)
        return f"{self.label}: {report['headline']} Score {report['score']}/100 (page v{s.html_version})."


class SecurityAgent(AuditAgent):
    name = "security"
    kind = "security"
    label = "Security audit"

    async def measure(self, ctx):
        s = ctx.state
        files = await au.workspace_texts(ctx)
        findings = audit_security.scan(s.html, files=files)
        return findings, {"csp": "injected by the sanitizer", "files_scanned": sorted([*files, "index.html"]),
                         "secrets_checked": "credential patterns only; values are never recorded"}


class SeoAgent(AuditAgent):
    name = "seo"
    kind = "seo"
    label = "SEO audit"

    async def measure(self, ctx):
        s = ctx.state
        copy = s.content
        keywords = list(s.brief.keywords) if s.brief else []
        findings = audit_seo.scan(
            s.html, keywords=keywords,
            name=copy.product_name if copy else "",
            headline=copy.headline if copy else "",
            subheadline=copy.subheadline if copy else "",
            deploy_url=s.deploy_url)
        return findings, {"keywords": keywords, "deploy_url": s.deploy_url or "",
                         "note": "no crawler is contacted; these are the page's own on-page signals"}


class AccessibilityAgent(AuditAgent):
    name = "accessibility"
    kind = "accessibility"
    label = "Accessibility audit"

    async def measure(self, ctx):
        s = ctx.state
        findings = audit_a11y.scan(s.html, measured=s.check_results)
        measured = [c.get("id") for c in s.check_results or []
                    if c.get("id") in {"contrast", "tap_targets", "font_size"}]
        return findings, {"browser_measurements": sorted(set(measured)),
                          "standard": "WCAG 2.1 AA (4.5:1 text, 44px targets, keyboard and screen-reader structure)"}


class PerformanceAgent(AuditAgent):
    name = "performance"
    kind = "performance"
    label = "Performance audit"

    async def measure(self, ctx):
        s = ctx.state
        assets = await au.workspace_texts(ctx, skip=("index.html",))
        findings = audit_perf.scan(s.html, assets=assets, measured=s.check_results)
        return findings, {"page_bytes": len(s.html.encode()),
                          "workspace_bytes": sum(len(t.encode()) for t in assets.values()),
                          "note": "load time is estimated from measured bytes, not a lab run"}


class DependencyAgent(AuditAgent):
    name = "dependency"
    kind = "dependency"
    label = "Dependency audit"
    fix_agent = ""          # its findings are manifest edits on the host stack, not page edits

    async def measure(self, ctx):
        findings = dependency_scan.scan(ctx.state.html)
        return findings, {"advisories": "not checked - no advisory database is bundled and no network call is made",
                          "manifests": ["backend/requirements.txt", "backend/requirements-dev.txt",
                                        "frontend/package.json"]}


class TestAgent(AuditAgent):
    """Writes a regression suite for this page and actually runs it with this interpreter."""

    name = "tester"
    kind = "tests"
    label = "Generated regression tests"

    async def measure(self, ctx):
        s = ctx.state
        script = testgen.generate(s.html, idea=s.idea, version=s.html_version)
        result = testgen.execute(script, s.html)
        s.tests = {"generated_at": au.stamp(), "version": s.html_version, "cases": result["cases"],
                   "passed": result["passed"], "failed": result["failed"], "ran": result["ran"],
                   "reason": result["reason"], "output": result["output"][-2000:]}
        s.tests["file"] = {"name": "tests/test_page.py", "bytes": len(script.encode()), "text": script}
        findings = testgen.findings(result, version=s.html_version)
        return findings, {"interpreter": "this service's own python", "suite": "tests/test_page.py"}
