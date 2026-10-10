"""Custom orchestrator (no framework): a small explicit pipeline with a bounded critic loop.

researcher -> strategist -> copywriter -> designer -> engineer -> [critic -> fixes -> engineer]* -> panel -> (human approval) -> launcher
                                                                      ^---- revise(): user feedback re-enters here ----'
"""
import asyncio
from collections import defaultdict

from app.agents import variants
from app.agents.audits import (AccessibilityAgent, DependencyAgent, PerformanceAgent, SeoAgent,
                               SecurityAgent, TestAgent)
from app.agents.copywriter import CopywriterAgent
from app.agents.critic import CriticAgent
from app.agents.designer import DesignerAgent
from app.agents.engineer import EngineerAgent
from app.agents.launcher import LauncherAgent
from app.agents.panel import PanelAgent
from app.agents.researcher import ResearcherAgent
from app.agents.strategist import StrategistAgent
from app.agents.base import looks_like_html
from app.orchestrator import artifacts
from app.orchestrator.readiness import compute_readiness
from app.orchestrator.state import GuardrailError, RunContext
from app.services import change_impact, workspace_manager
from app.tools.sanitizer import sanitize_html

TARGET_AGENT = {"page": "engineer", "copy": "copywriter", "design": "designer"}

# On-demand audits, keyed by the name the API and UI use. Order is the order they run in.
AUDIT_AGENTS = {"security": SecurityAgent, "seo": SeoAgent, "accessibility": AccessibilityAgent,
                "performance": PerformanceAgent, "dependency": DependencyAgent, "tests": TestAgent}
AUDIT_ORDER = ("security", "seo", "accessibility", "performance", "dependency", "tests")

# Conversational editing: map a plain-language request to the agent that owns the change.
# Styling words are checked first, so "add more spacing" goes to the Designer and not the Copywriter.
TARGET_HINTS = (
    ("design", ("colour", "color", "palette", "background", "theme", "dark", "light mode", "font", "typeface",
                "spacing", "padding", "margin", "bigger", "smaller", "larger", "wider", "narrower", "rounded",
                "sharp", "centre", "center", "align", "look", "style", "type")),
    ("copy", ("word", "words", "headline", "subheadline", "tagline", "copy", "text", "say", "rewrite", "tone",
              "title", "cta", "button label", "faq", "question", "feature", "benefit", "spell", "english",
              "shorter", "punchier", "friendly", "formal", "professional", "jargon", "add", "include", "remove",
              "delete", "mention")),
)


def infer_target(text: str) -> str:
    """Which agent should hear this message. Defaults to "page" so an ambiguous ask still does something."""
    low = (text or "").lower()
    for target, hints in TARGET_HINTS:
        if any(h in low for h in hints):
            return target
    return "page"


class Orchestrator:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.copywriter, self.designer, self.engineer = CopywriterAgent(), DesignerAgent(), EngineerAgent()
        self.critic = CriticAgent()

    async def _run(self, agent) -> None:
        ctx = self.ctx
        ctx.next_step(agent.name)                       # guardrail: max steps
        await ctx.emit("agent_started", agent=agent.name)
        before = ctx.tokens_used
        try:
            summary = await asyncio.wait_for(agent.run(ctx), timeout=ctx.settings.agent_timeout_s)  # guardrail: timeout
        except asyncio.TimeoutError:
            raise GuardrailError(f"Agent '{agent.name}' timed out after {ctx.settings.agent_timeout_s:.0f}s") from None
        await ctx.emit("agent_message", agent=agent.name, message=summary,
                       tokens=ctx.tokens_used - before, total_tokens=ctx.tokens_used)
        await ctx.checkpoint()

    async def _critic_loop(self) -> None:
        """Review -> route fixes -> rebuild, at most MAX_CRITIC_ITERATIONS reviews."""
        ctx, s = self.ctx, self.ctx.state
        for i in range(1, ctx.settings.max_critic_iterations + 1):   # hard cap
            s.iteration = i
            await self._run(self.critic)
            await artifacts.annotate(ctx)
            if s.check_summary.get("errors", 0) == 0 or i == ctx.settings.max_critic_iterations or not s.critic_feedback:
                break
            await self._apply_fixes(s.critic_feedback["fixes"],
                                    note=f"Self-heal round {i}: {s.critic_feedback.get('summary', '')[:120]}")

    async def _assess(self, rerun_panel: bool = True) -> None:
        """Audience panel (optional - never fails the run) + Launch Readiness Score."""
        ctx, s = self.ctx, self.ctx.state
        if rerun_panel or not s.panel:
            try:
                await self._run(PanelAgent())
            except Exception as exc:  # noqa: BLE001 - the panel is a bonus, not a gate
                await ctx.emit("agent_message", agent="system", message=f"Audience panel skipped: {str(exc)[:160]}")
        s.readiness = compute_readiness(s)
        await artifacts.annotate(ctx)          # version history shows the score each build ended with
        self._close_validation()

    def _close_validation(self) -> None:
        """Say how the checks scored the page the last change produced, next to that change."""
        s = self.ctx.state
        v = s.validation
        if not v or v.get("version") != s.html_version:
            return                             # a later rebuild owns the validation now
        errors = s.check_summary.get("errors", 0)
        v.update({"status": "clean" if not errors else "issues",
                  "check_errors": errors, "check_warnings": s.check_summary.get("warnings", 0),
                  "readiness": (s.readiness or {}).get("total"),
                  "impact_errors": (s.impact or {}).get("counts", {}).get("errors", 0)})

    async def _await_approval(self, message: str) -> None:
        ctx, s = self.ctx, self.ctx.state
        await ctx.checkpoint("awaiting_approval")
        await ctx.emit("awaiting_approval", message=message,
                       remaining_errors=s.check_summary.get("errors", 0), html_version=s.html_version)

    async def run_until_approval(self) -> None:
        ctx = self.ctx
        if not ctx.state.style:  # one design direction per run, reused by every later revision
            ctx.state.style = variants.seed_state(ctx.run_id or ctx.state.idea)
        await ctx.checkpoint("running")
        ctx.state.note = "Initial build"
        for agent in (ResearcherAgent(), StrategistAgent(), self.copywriter, self.designer, self.engineer):
            await self._run(agent)
        await self._critic_loop()
        await self._assess()
        await self._await_approval("Review the preview, then approve to deploy.")

    async def revise(self, instruction: str, target: str = "page") -> None:
        """Human-in-the-loop edit: apply the user's feedback, re-check, and return to the approval gate.

        target: "page" -> Engineer only | "copy" -> Copywriter then Engineer | "design" -> Designer then Engineer
        Every call is also recorded in the run's conversation thread.
        """
        ctx, s = self.ctx, self.ctx.state
        agent = TARGET_AGENT.get(target, "engineer")
        s.revisions += 1
        s.chat.append({"role": "user", "text": instruction, "at": artifacts.stamp(), "target": target})
        await ctx.emit("agent_message", agent="you",
                       message=f"Change #{s.revisions} ({target}): {instruction}")
        await ctx.checkpoint("running")
        fixes = [{"priority": 1, "agent": agent, "instruction": instruction}]
        if agent != "engineer":
            fixes.append({"priority": 2, "agent": "engineer",
                          "instruction": f"Apply the updated {target} from INPUT_JSON. Requested change: {instruction}"})
        await self._apply_fixes(fixes, note=f"{target}: {instruction[:120]}")
        s.iteration = 0                                  # fresh critic budget for this revision
        await self._critic_loop()
        await self._assess(rerun_panel=(target == "copy"))   # re-test the audience only when the words changed
        s.chat.append({"role": "assistant", "at": artifacts.stamp(), "version": s.html_version,
                       "text": self._reply()})
        await self._await_approval("Revision applied. Review the preview, then approve to deploy.")

    def _reply(self) -> str:
        """What the crew says back in the conversation after finishing an edit."""
        s = self.ctx.state
        errors = s.check_summary.get("errors", 0)
        score = (s.readiness or {}).get("total")
        bits = [f"Done - page is now v{s.html_version}."]
        bits.append("All browser checks pass." if not errors else f"{errors} check error(s) still open.")
        if score is not None:
            bits.append(f"Readiness {score}/100.")
        if s.sanitizer_violations:
            bits.append(f"Sanitizer stripped {len(s.sanitizer_violations)} unsafe item(s).")
        return " ".join(bits)

    async def debug(self) -> None:
        """Autonomous debugging on demand: re-check the live page, fix what breaks, re-verify."""
        ctx, s = self.ctx, self.ctx.state
        await ctx.emit("agent_message", agent="system", message="Debug pass: re-running browser checks on the current page.")
        await ctx.checkpoint("running")
        started_at = s.html_version
        s.iteration = 0                                # fresh critic budget, or the critic reports and stops
        await self._run(self.critic)                       # checks + (if needed) LLM fix instructions
        await artifacts.annotate(ctx)
        fixes = (s.critic_feedback or {}).get("fixes") or []
        if fixes:
            await self._apply_fixes(fixes, note=f"Debugged: {s.critic_feedback.get('summary', '')[:120]}")
            s.iteration = 0
            await self._critic_loop()                      # verify the repair actually landed
        else:
            s.iteration = 0
        await self._assess(rerun_panel=False)
        rebuilt = s.html_version > started_at
        s.chat.append({"role": "assistant", "at": artifacts.stamp(), "version": s.html_version,
                       "text": (f"Debug pass: {len(fixes)} fix(es) applied, page rebuilt to v{s.html_version}."
                                if rebuilt else f"Debug pass: checks clean, page unchanged at v{s.html_version}.")})
        await self._await_approval("Debug pass finished.")

    async def restore(self, version: int) -> None:
        """Roll the page back to a saved version. No LLM, no tokens - checks and score are recomputed."""
        ctx, s = self.ctx, self.ctx.state
        await ctx.checkpoint("running")
        html = await artifacts.load(ctx, version)          # raises KeyError if the snapshot is gone
        clean, violations = sanitize_html(html)            # same guardrail a fresh build goes through
        if not looks_like_html(clean):
            raise GuardrailError(f"Snapshot v{version} is no longer a complete page; nothing was restored.")
        s.html, s.sanitizer_violations = clean, violations
        s.html_version += 1
        s.note = f"Restored v{version}"
        files = await artifacts.publish(ctx)
        s.html_key = next(f["key"] for f in files if f["name"] == "index.html")
        await ctx.emit("workspace_updated", version=s.html_version,
                       files=[{"name": f["name"], "bytes": f["bytes"]} for f in files])
        s.iteration = 0
        await self._run(self.critic)                       # re-measure the restored page honestly
        await artifacts.annotate(ctx)
        await self._assess(rerun_panel=False)
        s.chat.append({"role": "assistant", "at": artifacts.stamp(), "version": s.html_version,
                       "text": f"Restored v{version} as v{s.html_version}. {(s.readiness or {}).get('total', '-')}/100 readiness."})
        await self._await_approval(f"v{version} restored as v{s.html_version}.")

    # ------------------------------------------------------------- file-level edits (workspace API)

    async def apply_workspace_changes(self, changes: list[dict], request: str = "") -> dict:
        """Patch named files, then judge the result exactly like a generated build.

        No model is called, so this spends no tokens. The workspace is indexed and the impact measured
        first, every file is snapshotted before anything is overwritten, and the patched page goes
        through the sanitizer, the Chromium checks and the readiness score afterwards - a hand-written
        edit gets no free pass.
        """
        ctx, s = self.ctx, self.ctx.state
        await ctx.checkpoint("running")
        texts = await workspace_manager.load_texts(ctx)
        texts.setdefault("index.html", s.html)
        index = workspace_manager.index_texts(texts, version=s.html_version)
        ask = (request or " ".join(f"{c.get('file', '')} {c.get('op', '')} {c.get('note', '')}"
                                   for c in changes)).strip()[:500]
        report = change_impact.analyze(index, ask, version=s.html_version)
        s.impact = report

        validated = workspace_manager.validate_changes(changes)
        before, _, page = await workspace_manager.prepare_changes(ctx, validated)
        plan = workspace_manager.record_plan(ctx, request=ask, changes=validated, report=report,
                                             status="applying")
        files_touched = sorted({c["file"] for c in validated} | {"index.html"})
        try:
            snapshot = await workspace_manager.capture(ctx, note=f"Before change {plan['id']} (v{s.html_version})",
                                                       changed=files_touched)
            result = await workspace_manager.commit(ctx, before=before, page=page,
                                                    note=f"File-level change {plan['id']}: {ask[:120]}")
        except Exception as exc:  # noqa: BLE001 - the plan says what was attempted, then the failure stands
            plan["status"] = "rejected"
            plan["result"] = {"error": (getattr(exc, "message", None) or str(exc))[:300]}
            raise

        s.revisions += 1
        s.changed_files = {k: result[k] for k in ("files", "changed", "lines_added", "lines_removed")}
        s.validation = {"at": artifacts.stamp(), "version": s.html_version, "status": "pending",
                        "kind": "file patch", "workspace_version": snapshot["w"],
                        "measured_from": report["version"], "plan": plan["id"],
                        "changed": result["changed"], "lines_added": result["lines_added"],
                        "lines_removed": result["lines_removed"],
                        "sanitizer_removed": result["sanitizer_removed"]}
        plan["status"] = "applied"
        plan["result"] = {"version": s.html_version, "workspace_version": snapshot["w"],
                          "changed": result["changed"], "lines_added": result["lines_added"],
                          "lines_removed": result["lines_removed"],
                          "sanitizer_removed": result["sanitizer_removed"]}
        await ctx.emit("workspace_updated", version=s.html_version,
                       files=[{"name": f["name"], "bytes": f["bytes"]} for f in s.files])
        s.chat.append({"role": "user", "text": ask, "at": artifacts.stamp(), "target": "files"})
        await ctx.emit("agent_message", agent="you",
                       message=f"Workspace change #{s.revisions}: {ask}")

        s.iteration = 0
        await self._run(self.critic)                   # re-measure the patched page, same rule as restore()
        await artifacts.annotate(ctx)
        await self._assess(rerun_panel=False)
        plan["result"].update({"check_errors": s.check_summary.get("errors", 0),
                               "check_warnings": s.check_summary.get("warnings", 0),
                               "readiness": (s.readiness or {}).get("total")})
        s.chat.append({"role": "assistant", "at": artifacts.stamp(), "version": s.html_version,
                       "text": self._reply()})
        await self._await_approval("File-level change applied. Review the diff, then approve to deploy.")
        return plan

    async def restore_workspace_snapshot(self, w: int) -> None:
        """Roll the whole workspace - page plus derived files - back to a captured snapshot."""
        ctx, s = self.ctx, self.ctx.state
        await ctx.checkpoint("running")
        page = await workspace_manager.snapshot_page(ctx, w)
        before = await workspace_manager.load_texts(ctx)
        before.setdefault("index.html", s.html)
        clean, violations = sanitize_html(page)        # the same guardrail a fresh build goes through
        if not looks_like_html(clean):
            raise GuardrailError(f"Workspace snapshot w{w} is no longer a complete page; nothing was restored.")

        snapshot = await workspace_manager.capture(ctx, note=f"Before restoring w{w}",
                                                   changed=sorted(before))
        s.html, s.sanitizer_violations = clean, violations
        s.html_version += 1
        s.note = f"Restored workspace w{w}"
        files = await artifacts.publish(ctx)
        s.html_key = next(f["key"] for f in files if f["name"] == "index.html")
        after = await workspace_manager.load_texts(ctx)
        after["index.html"] = clean
        s.changed_files = workspace_manager.stats(before, after)
        s.validation = {"at": artifacts.stamp(), "version": s.html_version, "status": "pending",
                        "kind": "workspace restore", "workspace_version": snapshot["w"],
                        "restored_from": w, "changed": s.changed_files["changed"],
                        "lines_added": s.changed_files["lines_added"],
                        "lines_removed": s.changed_files["lines_removed"],
                        "sanitizer_removed": len(violations)}
        await ctx.emit("workspace_updated", version=s.html_version,
                       files=[{"name": f["name"], "bytes": f["bytes"]} for f in files])
        s.iteration = 0
        await self._run(self.critic)
        await artifacts.annotate(ctx)
        await self._assess(rerun_panel=False)
        s.chat.append({"role": "assistant", "at": artifacts.stamp(), "version": s.html_version,
                       "text": f"Restored workspace snapshot w{w} as v{s.html_version}. "
                               f"{self._reply()}"})
        await self._await_approval(f"Workspace w{w} restored as v{s.html_version}.")

    async def _apply_fixes(self, fixes: list[dict], note: str = "") -> None:
        """Route fixes to the owning agent, then always rebuild the page.

        The change is measured against the workspace index first (no model, no cost) so the Engineer
        sees which files a name actually lives in - and which are rebuilt from the page on every
        publish - before it writes anything. What the rebuild really moved is measured again after it.
        """
        s = self.ctx.state
        s.note = note or s.note
        before = await self._impact_for(" ".join(f["instruction"] for f in fixes))
        by_agent: dict[str, list[str]] = defaultdict(list)
        for f in sorted(fixes, key=lambda f: f.get("priority", 1)):
            by_agent[f["agent"]].append(f["instruction"])
        s.pending_fixes = dict(by_agent)
        try:
            if "copywriter" in by_agent:
                await self._run(self.copywriter)
            if "designer" in by_agent:
                await self._run(self.designer)
            await self._run(self.engineer)
        finally:
            s.pending_fixes = {}
        await self._measure_edit(before)

    async def _impact_for(self, request: str) -> dict[str, str]:
        """Impact report for a change about to be made, plus the file texts to diff it against.

        Returns {} when there is nothing to index: the analysis is an aid to the edit, never a gate
        on it, so an unreadable workspace must not stop the crew from rebuilding.
        """
        ctx, s = self.ctx, self.ctx.state
        if not s.html:
            s.impact = None
            return {}
        try:
            texts = await workspace_manager.load_texts(ctx)
            texts.setdefault("index.html", s.html)
            index = workspace_manager.index_texts(texts, version=s.html_version)
        except Exception as exc:  # noqa: BLE001 - a lost blob costs a report, not a run
            s.impact = change_impact.empty(request, version=s.html_version,
                                           reason=f"The workspace could not be indexed ({str(exc)[:120]}).")
            return {}
        s.impact = change_impact.analyze(index, request, version=s.html_version)
        return texts

    async def _measure_edit(self, before: dict[str, str]) -> None:
        """Compare the workspace the rebuild published against the one it replaced."""
        ctx, s = self.ctx, self.ctx.state
        if not before:
            return
        try:
            after = await workspace_manager.load_texts(ctx)
        except Exception:  # noqa: BLE001 - the page is already rebuilt; the stats are a bonus
            return
        after.setdefault("index.html", s.html)
        s.changed_files = workspace_manager.stats(before, after)
        s.validation = {"at": artifacts.stamp(), "version": s.html_version, "status": "pending",
                        "kind": "crew rebuild", "measured_from": (s.impact or {}).get("version"),
                        "changed": s.changed_files["changed"],
                        "lines_added": s.changed_files["lines_added"],
                        "lines_removed": s.changed_files["lines_removed"],
                        "sanitizer_removed": len(s.sanitizer_violations)}
        await ctx.emit("agent_message", agent="system",
                       message=f"Impact: {change_impact.headline(s.impact or {})} "
                               f"Rebuild moved {s.changed_files['lines_added']} line(s) over "
                               f"{len(s.changed_files['changed'])} file(s).")

    async def audit(self, kinds: list[str]) -> None:
        """On-demand audits: measure the live page, record the reports, return to the gate.

        No model is called, so an audit spends no tokens and cannot change the page.
        """
        ctx = self.ctx
        await ctx.checkpoint("running")
        await self._run_audits(kinds)
        await self._assess(rerun_panel=False)
        await ctx.emit("agent_message", agent="system", message=self._audit_summary(kinds))
        await self._await_approval("Audits finished. Review the reports, repair what they found, or approve to deploy.")

    async def repair(self, kinds: list[str]) -> None:
        """Apply the fix instructions the current audits produced, then re-audit to prove they landed.

        Reports taken against an older build are ignored: their findings describe markup that no
        longer exists. The page is rebuilt through the same routed-fix path the critic loop uses, so
        the sanitizer, browser checks and readiness score all re-run over the result.
        """
        ctx, s = self.ctx, self.ctx.state
        fixes = [dict(f, priority=f.get("priority", 1)) for kind in kinds
                 for f in (s.audits.get(kind) or {}).get("fixes", [])
                 if (s.audits.get(kind) or {}).get("version") == s.html_version]
        if not fixes:
            await ctx.emit("agent_message", agent="system",
                           message="Nothing to repair: run the audits again against this build first.")
            await self._await_approval("No open audit findings to repair.")
            return
        s.revisions += 1
        await ctx.emit("agent_message", agent="you",
                       message=f"Audit repair #{s.revisions}: {len(fixes)} instruction(s) from "
                               + ", ".join(k for k in kinds if (s.audits.get(k) or {}).get("fixes")))
        await ctx.checkpoint("running")
        await self._apply_fixes(fixes, note=f"Audit repair: {len(fixes)} fix(es)")
        s.iteration = 0                                  # fresh critic budget for the repaired page
        await self._critic_loop()
        await self._run_audits(kinds)                    # same audits, against the new build
        await self._assess(rerun_panel=False)
        s.chat.append({"role": "assistant", "at": artifacts.stamp(), "version": s.html_version,
                       "text": f"Audit repair: {len(fixes)} instruction(s) applied, page rebuilt to v{s.html_version}. "
                               f"{self._audit_summary(kinds)}"})
        await self._await_approval("Audits re-run after the repair. Review, then approve to deploy.")

    async def _run_audits(self, kinds: list[str]) -> None:
        unknown = [k for k in kinds if k not in AUDIT_AGENTS]
        if unknown:
            raise ValueError(f"Unknown audit(s): {', '.join(unknown)}")
        for kind in (k for k in AUDIT_ORDER if k in set(kinds)):
            await self._run(AUDIT_AGENTS[kind]())

    def _audit_summary(self, kinds: list[str]) -> str:
        s = self.ctx.state
        bits = []
        for kind in kinds:
            rep = s.audits.get(kind)
            if rep and rep.get("version") == s.html_version:
                bits.append(f"{rep['label']}: {rep['score']}/100 ({rep['errors']} error(s), {rep['warnings']} warning(s))")
        return "; ".join(bits) or "No current audit report for this build."

    async def launch(self) -> None:
        """Called only after the user approved."""
        ctx = self.ctx
        await ctx.checkpoint("deploying")
        await self._run(LauncherAgent())
        s = ctx.state
        await ctx.checkpoint("deployed")
        await ctx.emit("deployed", url=s.deploy_url, mock=s.deploy_mock, social_posts=s.social_posts, email=s.email)