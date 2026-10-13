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
from app.orchestrator.state import GuardrailError, RunCancelled, RunContext
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
        await ctx.check_cancelled(f"before {agent.name} could start")   # a stop is never charged for a step
        ctx.next_step(agent.name)                       # guardrail: max steps
        await ctx.emit("agent_started", agent=agent.name)
        before = ctx.tokens_used
        try:
            summary = await self._interruptibly(agent.run(ctx), agent.name)
        except asyncio.TimeoutError:
            raise GuardrailError(f"Agent '{agent.name}' timed out after {ctx.settings.agent_timeout_s:.0f}s") from None
        await ctx.emit("agent_message", agent=agent.name, message=summary,
                       tokens=ctx.tokens_used - before, total_tokens=ctx.tokens_used)
        await ctx.checkpoint()

    async def _interruptibly(self, step, agent_name: str):
        """Await one agent step, abandoning it the moment a Stop arrives.

        This is the only place a stop is allowed to interrupt work, and it is safe because an agent's
        output reaches the run only after this returns - the step's checkpoint, the page write and the
        publish all happen later. What an abandoned step costs is the tokens it had already spent, which
        stay counted against the run's budget, and nothing else.
        """
        ctx = self.ctx
        task = asyncio.ensure_future(step)
        if ctx.cancel_event is None:            # no stop watch (a phase that cannot be interrupted mid-step)
            return await asyncio.wait_for(task, timeout=ctx.settings.agent_timeout_s)
        wake = asyncio.ensure_future(ctx.cancel_event.wait())
        done, pending = await asyncio.wait({task, wake}, timeout=ctx.settings.agent_timeout_s,
                                           return_when=asyncio.FIRST_COMPLETED)
        for leftover in pending:            # whichever half lost is not left running behind us
            leftover.cancel()
            await self._settle(leftover)
        if not done:
            raise asyncio.TimeoutError()
        if wake in done:
            raise RunCancelled(f"Stopped by you while {agent_name} was working.", agent=agent_name)
        return task.result()

    @staticmethod
    async def _settle(task) -> None:
        """Let a cancelled step finish dying, so its exception is not left unconsumed."""
        try:
            await task
        except (asyncio.CancelledError, Exception):     # noqa: BLE001 - the stop is the news, not this
            pass

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
            except RunCancelled:
                raise                            # the user asked for this build to end; a bonus agent cannot overrule it
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
            ctx.state.style = variants.seed_state(ctx.run_id or ctx.state.idea, ctx.state.spec)
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
        # A page rollback rewrites the workspace too, so it gets the same pre-change checkpoint.
        await self._checkpoint_workspace(kind="version restore", agent="user", changed=None,
                                         note=f"Before restoring v{version} (was v{s.html_version - 1})")
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

    async def apply_workspace_changes(self, changes: list[dict], request: str = "",
                                      *, kind: str = "file patch", authored: list[dict] | None = None) -> dict:
        """Patch named files, then judge the result exactly like a generated build.

        A model is called only by the caller that produced `changes`: this step itself spends no tokens,
        and it is the same step whether the patch was typed by hand or clicked out of the preview. The
        workspace is indexed and the impact measured first, every file is snapshotted before anything is
        overwritten, and the patched page goes through the sanitizer, the Chromium checks and the
        readiness score afterwards - a hand-written edit gets no free pass.

        `kind` is the attribution the checkpoint carries, so history can tell a typed patch apart from a
        visual edit without anyone re-reading the events.

        `authored` is the extra source a feature build ships beside the page (server code, schema,
        `.env.example`, setup notes). It is stored, listed and snapshotted with the rest of the file set,
        but it is never executed here and never folded into the page - and if the page change is refused,
        the file set is rolled back to what it was, because a half-written feature would be the one thing
        this pipeline must not report as done.
        """
        ctx, s = self.ctx, self.ctx.state
        label = {"visual edit": "Visual edit", "theme edit": "Theme edit",
                 "feature build": "Feature build", "assistant edit": "Assistant edit"}.get(kind, "File-level change")
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
        staged = await workspace_manager.stage_authored(ctx, authored) if authored else []
        files_touched = sorted({c["file"] for c in validated} | {"index.html"}
                               | {e["name"] for e in staged})
        previous_authored = list(s.authored_files or [])
        try:
            snapshot = await workspace_manager.capture(
                ctx, note=f"Before change {plan['id']} (v{s.html_version})", changed=files_touched,
                cause={"kind": kind, "plan": plan["id"], "run_id": ctx.run_id,
                       "version": s.html_version, "agent": "user"})
            workspace_manager.record_change(s, snapshot["w"])
            await ctx.emit("checkpoint", w=snapshot["w"], kind=kind, agent="user",
                           version=s.html_version, files=len(snapshot["files"]))
            written = workspace_manager.register_authored(s, staged) if staged else []
            try:
                result = await workspace_manager.commit(ctx, before=before, page=page,
                                                        note=f"{label} {plan['id']}: {ask[:120]}")
            except Exception:
                s.authored_files = previous_authored
                raise
        except Exception as exc:  # noqa: BLE001 - the plan says what was attempted, then the failure stands
            plan["status"] = "rejected"
            plan["result"] = {"error": (getattr(exc, "message", None) or str(exc))[:300]}
            raise

        s.revisions += 1
        s.changed_files = {k: result[k] for k in ("files", "changed", "lines_added", "lines_removed")}
        s.validation = {"at": artifacts.stamp(), "version": s.html_version, "status": "pending",
                        "kind": kind, "workspace_version": snapshot["w"],
                        "measured_from": report["version"], "plan": plan["id"],
                        "changed": result["changed"], "lines_added": result["lines_added"],
                        "lines_removed": result["lines_removed"],
                        "authored": written,
                        "sanitizer_removed": result["sanitizer_removed"]}
        plan["status"] = "applied"
        plan["result"] = {"version": s.html_version, "workspace_version": snapshot["w"],
                          "changed": result["changed"], "lines_added": result["lines_added"],
                          "lines_removed": result["lines_removed"], "authored": written,
                          "sanitizer_removed": result["sanitizer_removed"]}
        await ctx.emit("workspace_updated", version=s.html_version,
                       files=[{"name": f["name"], "bytes": f["bytes"]} for f in s.files])
        s.chat.append({"role": "user", "text": ask, "at": artifacts.stamp(), "target": "files"})
        await ctx.emit("agent_message", agent="you",
                       message=f"{label} #{s.revisions}: {ask}")

        s.iteration = 0
        await self._run(self.critic)                   # re-measure the patched page, same rule as restore()
        await artifacts.annotate(ctx)
        await self._assess(rerun_panel=False)
        plan["result"].update({"check_errors": s.check_summary.get("errors", 0),
                               "check_warnings": s.check_summary.get("warnings", 0),
                               "readiness": (s.readiness or {}).get("total")})
        s.chat.append({"role": "assistant", "at": artifacts.stamp(), "version": s.html_version,
                       "text": self._reply()})
        await self._await_approval(f"{label} applied. Review the diff, then approve to deploy.")
        return plan

    async def restore_workspace_snapshot(self, w: int, *, stepping: str | None = None) -> dict:
        """Roll the whole workspace - page plus derived files - back to a captured snapshot.

        `stepping` marks this as an undo or a redo rather than a user-picked restore: the state being
        left is still snapshotted, but it goes onto the opposite stack so the move can be reversed.
        A plain restore is a change like any other, so it becomes undoable and clears the redo chain.
        """
        ctx, s = self.ctx, self.ctx.state
        await ctx.checkpoint("running")
        target = workspace_manager.find_snapshot(s.workspace_versions, w)
        page = await workspace_manager.snapshot_page(ctx, w)
        before = await workspace_manager.load_texts(ctx)
        before.setdefault("index.html", s.html)
        clean, violations = sanitize_html(page)        # the same guardrail a fresh build goes through
        if not looks_like_html(clean):
            raise GuardrailError(f"Workspace snapshot w{w} is no longer a complete page; nothing was restored.")

        snapshot = await workspace_manager.capture(
            ctx, note=f"Before restoring w{w}", changed=sorted(before),
            cause={"kind": "workspace restore", "run_id": ctx.run_id, "version": s.html_version,
                   "agent": "user", "plan": f"w{w}"})
        if stepping == "undo":
            workspace_manager.record_step(s, snapshot["w"], forward=False)
        elif stepping == "redo":
            workspace_manager.record_step(s, snapshot["w"], forward=True)
        else:
            workspace_manager.record_change(s, snapshot["w"])
        self._sync_design(target)
        s.html, s.sanitizer_violations = clean, violations
        s.html_version += 1
        s.note = f"Restored workspace w{w}"
        # Feature source is not derivable from the page, so it comes back from the snapshot itself before
        # publish re-lists the file set.
        await workspace_manager.restore_authored(ctx, w)
        files = await artifacts.publish(ctx)
        s.html_key = next(f["key"] for f in files if f["name"] == "index.html")
        after = await workspace_manager.load_texts(ctx)
        after["index.html"] = clean
        s.changed_files = workspace_manager.stats(before, after)
        s.validation = {"at": artifacts.stamp(), "version": s.html_version, "status": "pending",
                        "kind": "workspace restore", "workspace_version": snapshot["w"],
                        "restored_from": w, "step": stepping or "restore",
                        "changed": s.changed_files["changed"],
                        "added": s.changed_files["added"],
                        "removed": s.changed_files["removed"],
                        "renamed": s.changed_files["renamed"],
                        "lines_added": s.changed_files["lines_added"],
                        "lines_removed": s.changed_files["lines_removed"],
                        "sanitizer_removed": len(violations)}
        await ctx.emit("checkpoint", w=snapshot["w"], kind="workspace restore", agent="user",
                       version=s.html_version, files=len(snapshot["files"]))
        await ctx.emit("workspace_updated", version=s.html_version,
                       files=[{"name": f["name"], "bytes": f["bytes"]} for f in files])
        s.iteration = 0
        await self._run(self.critic)
        await artifacts.annotate(ctx)
        await self._assess(rerun_panel=False)
        label = {"undo": "Undid one change: back to", "redo": "Redid one change: forward to"}.get(
            stepping or "", f"Restored workspace snapshot")
        s.chat.append({"role": "assistant", "at": artifacts.stamp(), "version": s.html_version,
                       "text": f"{label} w{w} as v{s.html_version}. {self._reply()}"})
        await self._await_approval(f"{'Undone' if stepping == 'undo' else 'Redone' if stepping == 'redo' else 'Workspace restored'}"
                                   f" - the workspace now matches w{w}, kept as v{s.html_version}.")
        return {"w": w, "restored_as": s.html_version, "checkpoint": snapshot["w"],
                **workspace_manager.undo_status(s)}

    def _sync_design(self, target: dict) -> None:
        """Move the run's design with the file set a restore just put back.

        A theme edit is the one workspace change that also rewrites the run's own direction and brief, so
        undoing it has to take those back too - otherwise the next rebuild would draw the theme the user
        just removed onto a page they had un-themed. A redo restores the themed design instead. The
        snapshot being restored carries the cause of the change it precedes; a redo's target is the
        checkpoint an undo left behind, which names the snapshot before it, so that is followed once.
        """
        s = self.ctx.state
        cause = target.get("cause") or {}
        entry = self._theme_step(cause)
        if entry is None:
            return
        design = entry.get("design_after" if cause.get("kind") != "theme edit" else "design_before") or {}
        if design.get("style"):
            s.style = dict(design["style"])
        if "spec_theme" in design:
            s.spec = {**(s.spec or {}), "theme": design["spec_theme"]}

    def _theme_step(self, cause: dict, *, depth: int = 0) -> dict | None:
        """The theme proposal a step is reversing, when the change it steps over was a theme edit."""
        if cause.get("kind") == "theme edit":
            return next((e for e in self.ctx.state.theme_edits or [] if e.get("plan") == cause.get("plan")), None)
        if depth or cause.get("kind") != "workspace restore":
            return None
        number = str(cause.get("plan") or "").lstrip("w")
        previous = next((v for v in self.ctx.state.workspace_versions or []
                        if str(v.get("w")) == number), None)
        return self._theme_step((previous or {}).get("cause") or {}, depth=1) if previous else None

    async def undo(self) -> dict:
        """Step the workspace back to the checkpoint taken before the last change. No model, no tokens."""
        return await self._step("undo")

    async def redo(self) -> dict:
        """Step forward again after an undo, using the checkpoint the undo itself kept."""
        return await self._step("redo")

    async def _step(self, side: str) -> dict:
        """Read the pointer the timeline offers, then let the restore swap it as it captures."""
        w = workspace_manager.next_step(self.ctx.state, side)
        return await self.restore_workspace_snapshot(w, stepping=side)

    async def _apply_fixes(self, fixes: list[dict], note: str = "") -> None:
        """Route fixes to the owning agent, then always rebuild the page.

        The change is measured against the workspace index first (no model, no cost) so the Engineer
        sees which files a name actually lives in - and which are rebuilt from the page on every
        publish - before it writes anything. The whole file set is snapshotted at that point too, so
        every rebuild the crew makes has a state to go back to. What the rebuild really moved is
        measured again after it.
        """
        s = self.ctx.state
        s.note = note or s.note
        before = await self._impact_for(" ".join(f["instruction"] for f in fixes))
        by_agent: dict[str, list[str]] = defaultdict(list)
        for f in sorted(fixes, key=lambda f: f.get("priority", 1)):
            by_agent[f["agent"]].append(f["instruction"])
        checkpoint = await self._checkpoint_workspace(
            kind="crew rebuild", agent="+".join(sorted(by_agent)),
            note=f"Before {note[:60] or 'crew change'} (v{s.html_version})", changed=sorted(before))
        s.pending_fixes = dict(by_agent)
        try:
            if "copywriter" in by_agent:
                await self._run(self.copywriter)
            if "designer" in by_agent:
                await self._run(self.designer)
            await self._run(self.engineer)
        finally:
            s.pending_fixes = {}
        await self._measure_edit(before, checkpoint=checkpoint)

    async def _checkpoint_workspace(self, *, kind: str, note: str, agent: str = "",
                                    plan: str = "", changed: list[str] | None = None) -> dict | None:
        """Snapshot the file set about to be overwritten, and make it the step back.

        Returns None when there is nothing to snapshot yet (the first build has published no files) or
        when storage refused: a checkpoint is what makes an edit reversible, never a gate on it.
        """
        ctx, s = self.ctx, self.ctx.state
        if not s.files:
            return None
        try:
            snap = await workspace_manager.capture(
                ctx, note=note, changed=changed,
                cause={"kind": kind, "agent": agent, "plan": plan, "run_id": ctx.run_id,
                       "version": s.html_version})
        except Exception as exc:  # noqa: BLE001 - the edit goes ahead; the gap is reported, not hidden
            await ctx.emit("agent_message", agent="system",
                           message=f"No checkpoint taken before this {kind}: {str(exc)[:160]}. "
                                   f"It cannot be undone by workspace version.")
            return None
        workspace_manager.record_change(s, snap["w"])
        await ctx.emit("checkpoint", w=snap["w"], kind=kind, agent=agent or "crew",
                       version=s.html_version, files=len(snap["files"]))
        return snap

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

    async def _measure_edit(self, before: dict[str, str], checkpoint: dict | None = None) -> None:
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
                        "workspace_version": (checkpoint or {}).get("w"),
                        "restored_from": None,
                        "changed": s.changed_files["changed"],
                        "added": s.changed_files["added"],
                        "removed": s.changed_files["removed"],
                        "renamed": s.changed_files["renamed"],
                        "lines_added": s.changed_files["lines_added"],
                        "lines_removed": s.changed_files["lines_removed"],
                        "sanitizer_removed": len(s.sanitizer_violations)}
        await ctx.emit("agent_message", agent="system",
                       message=f"Impact: {change_impact.headline(s.impact or {})} "
                               f"Rebuild moved {s.changed_files['lines_added']} line(s) over "
                               f"{len(s.changed_files['changed'])} file(s)."
                               + (f" Undo returns the workspace to w{checkpoint['w']}." if checkpoint else ""))

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