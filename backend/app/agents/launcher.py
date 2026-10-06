"""Launcher: runs ONLY after human approval. Deploys to Netlify, then drafts the launch kit."""
import json

from app.agents.base import BaseAgent
from app.agents.schemas import LaunchKit
from app.tools.deploy import deploy_html


class LauncherAgent(BaseAgent):
    name = "launcher"
    model_kind = "fast"
    max_tokens = 1200
    temperature = 0.8

    async def run(self, ctx) -> str:
        s = ctx.state
        name = s.content.product_name
        result = await deploy_html(s.html, name, ctx.settings)
        s.deploy_url, s.deploy_mock = result.url, result.mock
        await ctx.emit("tool_call", agent=self.name, tool="netlify_deploy", args={"site": name},
                       result_count=1, url=result.url, mock=result.mock)

        slim = {"product": name, "headline": s.content.headline, "subheadline": s.content.subheadline,
                "key_messages": s.strategy.key_messages, "url": result.url}
        kit = await self.call_json(ctx, f"IDEA: {s.idea}\nLAUNCH_JSON: {json.dumps(slim)}", LaunchKit)
        s.social_posts = [p.model_dump() for p in kit.social_posts]
        s.email = kit.email.model_dump()
        return f"Deployed to {result.url}{' (simulated)' if result.mock else ''}; drafted 3 posts + 1 email."
