import json

from app.agents import variants
from app.agents.base import BaseAgent, fixes_block
from app.agents.schemas import CopyDoc, brief_line


class CopywriterAgent(BaseAgent):
    name = "copywriter"
    max_tokens = 1800
    temperature = 0.7

    async def run(self, ctx) -> str:
        s = ctx.state
        st = s.strategy
        direction = variants.from_dict(s.style)
        # The page is built from this document, so the writer is told which sections it needs copy for
        # - and nothing else, so a section nobody asked for does not arrive fully invented.
        needed = ",".join(direction.sections)
        slim = {"positioning": st.positioning, "persona": {"name": st.persona.name, "description": st.persona.description,
                "frustrations": st.persona.frustrations}, "key_messages": st.key_messages, "keywords": s.brief.keywords}
        user = (f"IDEA: {s.idea}\nBRIEF: {brief_line(s.spec)}\nSECTIONS: {needed}\n"
                f"STRATEGY_JSON: {json.dumps(slim)}" + fixes_block(s, self.name, s.content))
        s.content = await self.call_json(ctx, user, CopyDoc)
        return f"Headline: {s.content.headline}"

