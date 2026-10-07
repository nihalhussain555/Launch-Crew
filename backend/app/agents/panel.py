"""Audience Panel: synthetic user testing. LLM personas react to the page copy; produces scores, objections
and one concrete fix. Failure here never fails the run (the orchestrator treats it as optional)."""
import json

from app.agents.base import BaseAgent
from app.agents.schemas import PanelReport

PERSONAS = [
    ("The Skeptic", "Has been burned by hype before; wants proof and clarity, distrusts vague claims."),
    ("The Busy Decision-maker", "Skims for 8 seconds; must understand what it is, who it is for and what to do next."),
    ("The Budget-Conscious User", "Cares about cost, effort to start, and whether switching is worth it."),
]


class PanelAgent(BaseAgent):
    name = "panel"
    model_kind = "fast"
    max_tokens = 1000
    temperature = 0.7

    async def run(self, ctx) -> str:
        s, c = ctx.state, ctx.state.content
        personas = [{"name": f"Target user ({s.strategy.persona.name})", "traits": s.strategy.persona.description[:200]}]
        personas += [{"name": n, "traits": t} for n, t in PERSONAS]
        page = {"product": c.product_name, "headline": c.headline, "subheadline": c.subheadline,
                "features": [f.title for f in c.features], "faq": [q.question for q in c.faq], "cta": c.cta.label}
        user = f"IDEA: {s.idea}\nPAGE_JSON: {json.dumps(page)}\nPERSONAS_JSON: {json.dumps(personas)}"
        report = await self.call_json(ctx, user, PanelReport)

        data = report.model_dump()
        for r in data["reactions"]:
            r["first_impression"], r["top_objection"] = r["first_impression"][:300], r["top_objection"][:300]
        data["summary"], data["suggested_fix"] = data["summary"][:400], data["suggested_fix"][:400]
        n = len(data["reactions"])
        data["avg_score"] = round(sum(r["score"] for r in data["reactions"]) / n, 1)
        data["signups"] = sum(1 for r in data["reactions"] if r["would_sign_up"])
        s.panel = data
        return f"Audience panel: {data['avg_score']}/10 average, {data['signups']}/{n} would sign up."