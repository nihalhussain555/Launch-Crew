import json

from app.agents.base import BaseAgent, fixes_block
from app.agents.schemas import Design


class DesignerAgent(BaseAgent):
    name = "designer"
    model_kind = "fast"
    max_tokens = 700

    async def run(self, ctx) -> str:
        s = ctx.state
        slim = {"idea": s.idea, "positioning": s.strategy.positioning, "persona": s.strategy.persona.description,
                "tone_keywords": s.brief.keywords[:5]}
        user = f"IDEA: {s.idea}\nCONTEXT_JSON: {json.dumps(slim)}" + fixes_block(s, self.name, s.design)
        s.design = await self.call_json(ctx, user, Design)
        return f"{s.design.layout_style} layout, primary {s.design.palette.primary}"
