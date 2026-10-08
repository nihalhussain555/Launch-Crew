import json

from app.agents import variants
from app.agents.base import BaseAgent, fixes_block
from app.agents.schemas import Design


class DesignerAgent(BaseAgent):
    name = "designer"
    model_kind = "fast"
    temperature = 0.7      # composition varies per run; the direction keeps it on-brief
    max_tokens = 700

    async def run(self, ctx) -> str:
        s = ctx.state
        direction = variants.from_dict(s.style)
        slim = {"idea": s.idea, "positioning": s.strategy.positioning, "persona": s.strategy.persona.description,
                "tone_keywords": s.brief.keywords[:5]}
        user = (f"IDEA: {s.idea}\nCONTEXT_JSON: {json.dumps(slim)}"
                + fixes_block(s, self.name, s.design) + variants.prompt_block(direction))
        s.design = await self.call_json(ctx, user, Design)
        return f"{direction.label} ({s.design.layout_style} layout, primary {s.design.palette.primary})"
