import json

from app.agents.base import BaseAgent
from app.agents.schemas import MarketBrief
from app.tools.web_search import WEB_SEARCH_TOOL, get_search_tool


class ResearcherAgent(BaseAgent):
    name = "researcher"
    max_tokens = 1500

    async def run(self, ctx) -> str:
        s, cap = ctx.state, ctx.settings.tool_rounds_cap
        search = get_search_tool(ctx.settings)
        messages = [self.system_message(), {"role": "user", "content": f"IDEA: {s.idea}\nYou may call web_search at most {cap} times."}]
        notes: list[dict] = []

        for _ in range(cap):  # capped tool-calling rounds
            res = await self.llm(ctx, messages, tools=[WEB_SEARCH_TOOL])
            if not res.tool_calls:
                break
            messages.append(res.raw_message)
            for tc in res.tool_calls[:3]:
                query = str(tc.arguments.get("query", s.idea))[:200]
                try:
                    results = await search.search(query)
                except Exception as exc:  # a failing search must not kill the run
                    results = [{"title": "search failed", "url": "", "snippet": str(exc)[:120]}]
                notes.append({"query": query, "results": results})
                await ctx.emit("tool_call", agent=self.name, tool=tc.name, args={"query": query}, result_count=len(results))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(results)})

        # Fresh, compact context for the structured answer (saves tokens; avoids tool messages in JSON mode).
        prompt = f"IDEA: {s.idea}\nSEARCH_NOTES: {json.dumps(notes)[:6000]}\nWrite the market brief as JSON."
        s.brief = await self.call_json(ctx, prompt, MarketBrief)
        return f"Found {len(s.brief.competitors)} competitors, {len(s.brief.audience_pain_points)} pain points, {len(s.brief.keywords)} keywords."
