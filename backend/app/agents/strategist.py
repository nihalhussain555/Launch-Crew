import json

from app.agents.base import BaseAgent, fixes_block
from app.agents.schemas import Strategy


class StrategistAgent(BaseAgent):
    name = "strategist"
    model_kind = "fast"
    max_tokens = 900

    async def run(self, ctx) -> str:
        s, b = ctx.state, ctx.state.brief
        # only the needed fields from the brief
        slim = {"competitors": [{"name": c.name, "weakness": c.weakness} for c in b.competitors],
                "pain_points": b.audience_pain_points, "keywords": b.keywords, "opportunity": b.opportunity}
        s.strategy = await self.call_json(ctx, f"IDEA: {s.idea}\nBRIEF_JSON: {json.dumps(slim)}", Strategy)
        return s.strategy.positioning
