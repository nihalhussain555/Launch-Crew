import json

from app.agents.base import BaseAgent, extract_html, looks_like_html
from app.tools.sanitizer import sanitize_html


class EngineerAgent(BaseAgent):
    name = "engineer"

    async def run(self, ctx) -> str:
        s = ctx.state
        payload = {"copy": s.content.model_dump(), "design": s.design.model_dump()}
        user = f"INPUT_JSON: {json.dumps(payload, separators=(',', ':'))}\n"
        fixes = s.pending_fixes.get("engineer")
        if fixes and s.html:  # patch mode: send the current page + fixes
            user += "FIXES (apply all, keep everything else unchanged):\n" + "\n".join(f"- {f}" for f in fixes)
            user += f"\nCURRENT_HTML:\n{s.html}"
        messages = [self.system_message(), {"role": "user", "content": user}]

        clean, violations = "", []
        for attempt in (1, 2):
            res = await self.llm(ctx, messages, max_tokens=ctx.settings.engineer_max_tokens)
            clean, violations = sanitize_html(extract_html(res.text))
            if looks_like_html(clean) and res.finish_reason != "length":
                break
            if attempt == 2:
                raise ValueError("Engineer did not return a complete HTML document")
            messages = [*messages, {"role": "assistant", "content": res.text[:800]},
                        {"role": "user", "content": "Incomplete output. Return the COMPLETE document, from <!DOCTYPE html> to </html>, in one ```html block, as compact as possible."}]

        s.html, s.sanitizer_violations = clean, violations
        s.html_version += 1
        s.html_key = await ctx.storage.save(ctx.run_id, "index.html", clean.encode("utf-8"))
        note = f" Sanitizer removed {len(violations)} item(s)." if violations else ""
        return f"Built index.html ({len(clean) // 1024 or 1} KB, v{s.html_version}).{note}"
