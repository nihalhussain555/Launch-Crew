import json

from app.agents.base import BaseAgent
from app.agents.schemas import MarketBrief
from app.tools.web_search import WEB_SEARCH_TOOL, get_search_tool


class ResearcherAgent(BaseAgent):
    name = "researcher"
    json_prompt = "researcher_brief"          # the brief is written without tools; see prompts/
    max_tokens = 1500

    async def run(self, ctx) -> str:
        s = ctx.state
        # A tool round is only honest when something can actually answer it. With a real model and no
        # TAVILY_API_KEY the brief comes from the model's own knowledge - which is what /api/config
        # already promises - so no search tool is offered at all. Mock mode keeps it for the demo.
        live = ctx.settings.mock_llm or bool(ctx.settings.tavily_api_key)
        notes = await self._search_rounds(ctx) if live else []

        notes_blob = json.dumps(notes)[:6000] if live else "none - this run has no web search"
        prompt = f"IDEA: {s.idea}\nSEARCH_NOTES: {notes_blob}\nWrite the market brief as JSON."
        s.brief = await self.call_json(ctx, prompt, MarketBrief)
        return f"Found {len(s.brief.competitors)} competitors, {len(s.brief.audience_pain_points)} pain points, {len(s.brief.keywords)} keywords."

    async def _search_rounds(self, ctx) -> list[dict]:
        """Capped tool-calling rounds against the one registered tool, `web_search`."""
        s, cap = ctx.state, ctx.settings.tool_rounds_cap
        search = get_search_tool(ctx.settings)
        known = {WEB_SEARCH_TOOL["function"]["name"]}
        messages = [self.system_message(),
                    {"role": "user", "content": f"IDEA: {s.idea}\nYou may call web_search at most {cap} times."}]
        notes: list[dict] = []

        for _ in range(cap):
            res = await self.llm(ctx, messages, tools=[WEB_SEARCH_TOOL])
            if not res.tool_calls:
                break
            messages.append(res.raw_message)
            unregistered = [tc for tc in res.tool_calls if tc.name not in known]
            if unregistered:
                # gpt-oss models carry a built-in `web.run` in their vocabulary. Nothing here can run
                # it, so every call id still gets an answer (a dangling one fails the next request)
                # and the round ends instead of burning the remaining budget.
                for tc in unregistered:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(
                        {"error": f"{tc.name} is not available in this run; only web_search is."})})
                await ctx.emit("tool_call", agent=self.name, tool="unregistered",
                               args={"names": sorted({tc.name for tc in unregistered})}, result_count=0)
                break
            for tc in res.tool_calls[:3]:
                query = str(tc.arguments.get("query", s.idea))[:200]
                try:
                    results = await search.search(query)
                except Exception as exc:  # a failing search must not kill the run
                    results = [{"title": "search failed", "url": "", "snippet": str(exc)[:120]}]
                notes.append({"query": query, "results": results})
                await ctx.emit("tool_call", agent=self.name, tool=tc.name, args={"query": query}, result_count=len(results))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(results)})
        return notes
