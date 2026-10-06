import json

from app.agents.base import BaseAgent, fixes_block
from app.agents.schemas import CopyDoc


class CopywriterAgent(BaseAgent):
    name = "copywriter"
    max_tokens = 1800
    temperature = 0.7

    async def run(self, ctx) -> str:
        s = ctx.state
        st = s.strategy
        slim = {"positioning": st.positioning, "persona": {"name": st.persona.name, "description": st.persona.description,
                "frustrations": st.persona.frustrations}, "key_messages": st.key_messages, "keywords": s.brief.keywords}
        user = f"IDEA: {s.idea}\nSTRATEGY_JSON: {json.dumps(slim)}" + fixes_block(s, self.name, s.content)
        s.content = await self.call_json(ctx, user, CopyDoc)
        return f"Headline: {s.content.headline}"
