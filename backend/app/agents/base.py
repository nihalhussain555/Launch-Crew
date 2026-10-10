"""BaseAgent: prompt loading, LLM calls with token accounting, JSON parsing + one validation retry."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.llm.client import LLMOutputError, LLMResult, LLMToolRequestError

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


class AgentOutputError(Exception):
    """Agent output stayed invalid after the retry."""


def extract_json(text: str) -> dict:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    return json.loads(t[start : end + 1])


def extract_html(text: str) -> str:
    m = re.search(r"```(?:html)?\s*(.*?)```", text, re.S | re.I)
    body = m.group(1) if m else text
    i = body.lower().find("<!doctype")
    if i == -1:
        i = body.lower().find("<html")
    return body[i:].strip() if i != -1 else body.strip()


def looks_like_html(html: str) -> bool:
    low = html.lower()
    return "<html" in low and "</html>" in low and len(html) > 300


class BaseAgent:
    name = "base"
    model_kind = "default"   # "default" | "fast" | "vision"
    temperature = 0.4
    max_tokens = 2048
    # Prompt file used for JSON-only calls when the agent's main prompt describes tool use. A
    # request that registers no tools must not carry instructions that ask the model to call one.
    json_prompt: str | None = None

    NO_TOOLS = ("No tools are available in this request. Do not call web_search, web.run or any "
                "other tool - reply with the JSON object itself.")

    async def run(self, ctx) -> str:  # returns a short human summary
        raise NotImplementedError

    def system_message(self, *, json_only: bool = False) -> dict:
        return {"role": "system", "content": load_prompt(self.json_prompt if json_only and self.json_prompt else self.name)}

    def json_messages(self, user: str) -> list[dict]:
        """System + user turns for a structured-answer call: the tool-free prompt where there is one."""
        return [self.system_message(json_only=True), {"role": "user", "content": user}]

    async def llm(self, ctx, messages, *, json_mode=False, tools=None, kind=None, max_tokens=None) -> LLMResult:
        ctx.check_budget()

        async def on_retry(info: dict) -> None:
            await ctx.emit("rate_limited", agent=self.name, **info)

        res = await ctx.llm.chat(
            agent=self.name, messages=messages, kind=kind or self.model_kind, json_mode=json_mode, tools=tools,
            temperature=self.temperature, max_tokens=max_tokens or self.max_tokens, on_retry=on_retry,
        )
        ctx.add_tokens(res.usage)
        return res

    async def json_from(self, ctx, messages: list[dict], schema: type[BaseModel]) -> BaseModel:
        """JSON-mode call -> Pydantic validation. One corrective retry, then AgentOutputError."""
        last_text, error = "", ""
        for attempt in (1, 2):
            try:
                res = await self.llm(ctx, messages, json_mode=True)
                last_text = res.text
                if not res.text.strip() and res.tool_calls:
                    raise LLMToolRequestError("the model answered with a call to "
                                              + ", ".join(c.name for c in res.tool_calls))
                return schema.model_validate(extract_json(res.text))
            except (LLMOutputError, ValueError) as exc:  # JSONDecodeError and pydantic ValidationError are ValueErrors
                error = str(exc)[:600]
                if attempt == 2:
                    break
                messages = self._correction(messages, last_text, error)
        raise AgentOutputError(f"{self.name}: invalid output after retry: {error}")

    def _correction(self, messages: list[dict], last_text: str, error: str) -> list[dict]:
        """Attempt 2 must not be the request that just failed. Re-sending the same system prompt
        reproduces the same refusal; this swaps in the tool-free prompt and says in words that no
        tool exists here."""
        body = [m for m in messages if m.get("role") != "system"]
        return [self.system_message(json_only=True), *body,
                {"role": "assistant", "content": last_text[:1500] or "{}"},
                {"role": "user", "content": f"That output was invalid: {error}\n{self.NO_TOOLS}\n"
                                            "Return ONLY the corrected JSON object."}]

    async def call_json(self, ctx, user: str, schema: type[BaseModel]) -> BaseModel:
        return await self.json_from(ctx, self.json_messages(user), schema)


def fixes_block(state, agent: str, current: BaseModel | None) -> str:
    """Extra prompt text when the Critic routed fix instructions to this agent."""
    fixes = state.pending_fixes.get(agent)
    if not fixes or current is None:
        return ""
    return "\nFIXES (apply all; keep everything else unchanged):\n" + "\n".join(f"- {f}" for f in fixes) + \
           "\nCURRENT_JSON: " + current.model_dump_json()
