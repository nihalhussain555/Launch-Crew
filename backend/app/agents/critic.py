"""Critic: deterministic Playwright checks (no LLM for the checking itself), then the LLM turns
failures into prioritised fix instructions routed to engineer/designer/copywriter."""
import base64
import json

from app.agents.base import BaseAgent
from app.agents.schemas import CriticFeedback
from app.tools import browser_checks
from app.tools.browser_checks import summarize


class CriticAgent(BaseAgent):
    name = "critic"
    max_tokens = 1000
    temperature = 0.2

    async def run(self, ctx) -> str:
        s, cfg = ctx.state, ctx.settings
        # looked up via module attribute so tests can monkeypatch browser_checks.run_checks
        checks, shots = await browser_checks.run_checks(s.html)
        s.check_results, s.check_summary = checks, summarize(checks)
        await ctx.emit("check_results", iteration=s.iteration, summary=s.check_summary, checks=checks)

        for viewport, data in shots.items():
            s.screenshot_keys[viewport] = await ctx.storage.save(ctx.run_id, f"{viewport}.jpg", data)
            await ctx.emit("screenshot_ready", viewport=viewport, version=s.html_version)

        s.critic_feedback = None
        errors = s.check_summary["errors"]
        is_last_review = s.iteration >= cfg.max_critic_iterations

        if errors and not is_last_review:
            failed = [{k: c[k] for k in ("id", "viewport", "severity", "detail")} for c in checks if not c["passed"]]
            user = (f"CHECK_RESULTS_JSON: {json.dumps(failed)}\n"
                    f"SANITIZER_NOTES: {json.dumps(s.sanitizer_violations[:5])}\n"
                    "Return prioritised fixes as JSON. Route each fix to the agent that owns the problem.")
            fb = await self.call_json(ctx, user, CriticFeedback)
            fb.fixes.sort(key=lambda f: f.priority)
            s.critic_feedback = fb.model_dump()
            await ctx.emit("critic_feedback", iteration=s.iteration, **s.critic_feedback)
            msg = f"{errors} error(s), {s.check_summary['warnings']} warning(s): {fb.summary}"
        elif errors:
            msg = f"{errors} error(s) remain after {s.iteration} review(s); iteration cap reached."
        else:
            msg = f"All required checks passed ({s.check_summary['warnings']} warning(s))."
            await self._visual_review(ctx, shots)

        s.critic_history.append({"iteration": s.iteration, "summary": s.check_summary, "message": msg})
        return msg

    async def _visual_review(self, ctx, shots: dict[str, bytes]) -> None:
        """Optional advisory visual review (only when GROQ_VISION_MODEL is set)."""
        if ctx.settings.mock_llm or not ctx.settings.groq_vision_model or "mobile" not in shots:
            return
        b64 = base64.b64encode(shots["mobile"]).decode()
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "You are a UI reviewer. In <=4 short bullet points, note visual problems "
                                     "(alignment, spacing, hierarchy, legibility) in this mobile landing-page screenshot."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
        try:
            res = await self.llm(ctx, messages, kind="vision", max_tokens=300)
            ctx.state.critic_feedback = {"summary": "Visual review (advisory)", "fixes": [], "visual_notes": res.text}
            await ctx.emit("critic_feedback", iteration=ctx.state.iteration, **ctx.state.critic_feedback)
        except Exception as exc:  # advisory only - never fail the run
            await ctx.emit("agent_message", agent=self.name, message=f"Visual review skipped: {str(exc)[:120]}")
