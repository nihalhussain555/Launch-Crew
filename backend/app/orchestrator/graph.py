"""Custom orchestrator (no framework): a small explicit pipeline with a bounded critic loop.

researcher -> strategist -> copywriter -> designer -> engineer -> [critic -> fixes -> engineer]* -> (human approval) -> launcher
                                                                      ^---- revise(): user feedback re-enters here ----'
"""
import asyncio
from collections import defaultdict

from app.agents.copywriter import CopywriterAgent
from app.agents.critic import CriticAgent
from app.agents.designer import DesignerAgent
from app.agents.engineer import EngineerAgent
from app.agents.launcher import LauncherAgent
from app.agents.researcher import ResearcherAgent
from app.agents.strategist import StrategistAgent
from app.orchestrator.state import GuardrailError, RunContext

TARGET_AGENT = {"page": "engineer", "copy": "copywriter", "design": "designer"}


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
            if s.check_summary.get("errors", 0) == 0 or i == ctx.settings.max_critic_iterations or not s.critic_feedback:
                break
            await self._apply_fixes(s.critic_feedback["fixes"])

    async def _await_approval(self, message: str) -> None:
        ctx, s = self.ctx, self.ctx.state
        await ctx.checkpoint("awaiting_approval")
        await ctx.emit("awaiting_approval", message=message,
                       remaining_errors=s.check_summary.get("errors", 0), html_version=s.html_version)

    async def run_until_approval(self) -> None:
        ctx = self.ctx
        await ctx.checkpoint("running")
        for agent in (ResearcherAgent(), StrategistAgent(), self.copywriter, self.designer, self.engineer):
            await self._run(agent)
        await self._critic_loop()
        await self._await_approval("Review the preview, then approve to deploy.")

    async def revise(self, instruction: str, target: str = "page") -> None:
        """Human-in-the-loop edit: apply the user's feedback, re-check, and return to the approval gate.

        target: "page" -> Engineer only | "copy" -> Copywriter then Engineer | "design" -> Designer then Engineer
        """
        ctx, s = self.ctx, self.ctx.state
        agent = TARGET_AGENT.get(target, "engineer")
        s.revisions += 1
        await ctx.emit("agent_message", agent="you",
                       message=f"Change #{s.revisions} ({target}): {instruction}")
        await ctx.checkpoint("running")
        fixes = [{"priority": 1, "agent": agent, "instruction": instruction}]
        if agent != "engineer":
            fixes.append({"priority": 2, "agent": "engineer",
                          "instruction": f"Apply the updated {target} from INPUT_JSON. Requested change: {instruction}"})
        await self._apply_fixes(fixes)
        s.iteration = 0                                  # fresh critic budget for this revision
        await self._critic_loop()
        await self._await_approval("Revision applied. Review the preview, then approve to deploy.")

    async def _apply_fixes(self, fixes: list[dict]) -> None:
        """Route fixes to the owning agent, then always rebuild the page."""
        s = self.ctx.state
        by_agent: dict[str, list[str]] = defaultdict(list)
        for f in sorted(fixes, key=lambda f: f["priority"]):
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

    async def launch(self) -> None:
        """Called only after the user approved."""
        ctx = self.ctx
        await ctx.checkpoint("deploying")
        await self._run(LauncherAgent())
        s = ctx.state
        await ctx.checkpoint("deployed")
        await ctx.emit("deployed", url=s.deploy_url, mock=s.deploy_mock, social_posts=s.social_posts, email=s.email)