"""The Researcher's structured-output path: a JSON-only call must never invite a tool call.

Groq answers HTTP 400 ("Tool choice is none, but model called a tool") when a tool-less request
gets back a call - which is what happened with GROQ_MODEL=openai/gpt-oss-120b reaching for its
built-in `web.run`. These cover the request shape, the classification, and the retry actually
being a different request.
"""
import json
import sys
import types
from types import SimpleNamespace

import pytest

from app.agents.base import AgentOutputError, BaseAgent
from app.agents.researcher import ResearcherAgent
from app.agents.schemas import MarketBrief, Strategy
from app.llm.client import (GroqProvider, LLMClient, LLMError, LLMOutputError, LLMResult, LLMToolRequestError,
                            ToolCall, Usage, classify_bad_request)
from app.tools.web_search import WEB_SEARCH_TOOL
from tests.conftest import make_settings

BRIEF = json.dumps({"competitors": [{"name": "Rival", "positioning": "old", "weakness": "slow"}],
                    "audience_pain_points": ["too slow"], "keywords": ["clips"], "opportunity": "faster",
                    "sources": ["https://example.com/market"]})
STRATEGY = '{"positioning":"p","persona":{"name":"n","description":"d"},"key_messages":["a","b","c"]}'


def tool_reply(name="web.run", text=""):
    """What a model that ignored the JSON instruction answers with: a call, no content."""
    calls = [ToolCall("call_1", name, {"url": "https://x.com", "cursor": 0})]
    raw = {"role": "assistant", "content": text,
           "tool_calls": [{"id": "call_1", "type": "function",
                           "function": {"name": name, "arguments": json.dumps({"url": "https://x.com"})}}]}
    return LLMResult(text, Usage(1, 1, 2), "m", calls, raw, "tool_calls")


class Scripted:
    """Provider stand-in: replays canned results (or raises them) and records each request."""

    def __init__(self, *results):
        self.results = list(results)
        self.requests: list[dict] = []

    async def complete(self, *, agent, model, messages, json_mode, tools, temperature, max_tokens):
        self.requests.append({"agent": agent, "messages": messages, "json_mode": json_mode, "tools": tools})
        outcome = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def client(ctx, *results) -> Scripted:
    provider = Scripted(*results)
    ctx.llm = LLMClient(ctx.settings, provider=provider)
    return provider


# ------------------------------------------------------------------ request shape
async def test_the_brief_call_carries_no_tools_and_no_tool_instructions(make_ctx):
    ctx, _ = make_ctx()
    provider = client(ctx, LLMResult(BRIEF, Usage(1, 1, 2)))

    brief = await ResearcherAgent().call_json(ctx, "IDEA: clips", MarketBrief)

    assert brief.competitors[0].name == "Rival" and brief.keywords == ["clips"]
    request = provider.requests[0]
    assert request["tools"] is None and request["json_mode"] is True
    system = " ".join(request["messages"][0]["content"].split())        # the prompt wraps mid-sentence
    assert "web_search tool" not in system                     # the prompt that invites a call is gone
    assert "you have no tools in this request" in system.lower()
    assert "never invent urls" in system.lower()


async def test_agents_without_a_tool_prompt_keep_using_their_only_prompt(make_ctx):
    ctx, _ = make_ctx()
    provider = client(ctx, LLMResult(STRATEGY, Usage(1, 1, 2)))
    agent = BaseAgent()
    agent.name = "strategist"

    await agent.call_json(ctx, "IDEA: x", Strategy)

    assert provider.requests[0]["messages"][0]["content"] == agent.system_message()["content"]


# ------------------------------------------------------------------ malformed output
async def test_malformed_json_is_retried_once_and_recovers(make_ctx):
    ctx, _ = make_ctx()
    provider = client(ctx, LLMResult("this is not json", Usage(1, 1, 2)), LLMResult(BRIEF, Usage(1, 1, 2)))

    brief = await ResearcherAgent().call_json(ctx, "IDEA: clips", MarketBrief)

    assert brief.opportunity == "faster" and len(provider.requests) == 2
    assert "That output was invalid" in provider.requests[1]["messages"][-1]["content"]


async def test_a_schema_violation_counts_as_invalid_output_and_retries(make_ctx):
    ctx, _ = make_ctx()
    provider = client(ctx, LLMResult('{"competitors": []}', Usage(1, 1, 2)), LLMResult(BRIEF, Usage(1, 1, 2)))

    brief = await ResearcherAgent().call_json(ctx, "IDEA: clips", MarketBrief)

    assert brief.keywords == ["clips"]
    assert "ValidationError" in provider.requests[1]["messages"][-1]["content"] or "validation" in \
        provider.requests[1]["messages"][-1]["content"].lower()


# ------------------------------------------------------------------ unexpected tool calls
async def test_a_tool_call_in_place_of_json_retries_with_a_different_request(make_ctx):
    ctx, _ = make_ctx()
    provider = client(ctx, tool_reply("web.run"), LLMResult(BRIEF, Usage(1, 1, 2)))

    brief = await ResearcherAgent().call_json(ctx, "IDEA: clips", MarketBrief)

    assert brief.opportunity == "faster" and len(provider.requests) == 2
    assert provider.requests[1]["messages"] != provider.requests[0]["messages"]   # never the same ask twice
    assert "web.run" in provider.requests[1]["messages"][-1]["content"]


def test_the_correction_swaps_a_tool_prompt_for_the_tool_free_one():
    agent = ResearcherAgent()
    messages = [agent.system_message(), {"role": "user", "content": "IDEA: clips"}]
    assert "web_search tool" in messages[0]["content"]                # attempt 1 is the research prompt

    fixed = agent._correction(messages, "", "the model called a tool")

    assert fixed[0]["content"] == agent.system_message(json_only=True)["content"]
    assert "web_search tool" not in fixed[0]["content"]
    assert fixed[1] == messages[1]                                    # the real question survives
    assert "No tools are available in this request" in fixed[-1]["content"]


async def test_a_provider_tool_refusal_also_recovers_on_the_retry(make_ctx):
    ctx, _ = make_ctx()
    provider = client(ctx,
                      LLMToolRequestError("Error code: 400 - Tool choice is none, but model called a tool"),
                      LLMResult(BRIEF, Usage(1, 1, 2)))

    brief = await ResearcherAgent().call_json(ctx, "IDEA: clips", MarketBrief)

    assert brief.competitors[0].name == "Rival"
    assert "No tools are available in this request" in provider.requests[1]["messages"][-1]["content"]


async def test_still_failing_after_the_retry_raises_once_with_the_tool_named(make_ctx):
    ctx, _ = make_ctx()
    provider = client(ctx, tool_reply("web.run"))

    with pytest.raises(AgentOutputError) as exc:
        await ResearcherAgent().call_json(ctx, "IDEA: clips", MarketBrief)

    assert "web.run" in str(exc.value) and "researcher" in str(exc.value)
    assert len(provider.requests) == 2                                 # bounded: exactly one retry


# ------------------------------------------------------------------ provider error mapping
def test_http_400s_are_split_by_the_recovery_they_need():
    assert classify_bad_request("Error code: 400 - {'error': {'code': 'tool_use_failed'}}") is LLMToolRequestError
    assert classify_bad_request("Tool choice is none, but model called a tool") is LLMToolRequestError
    assert classify_bad_request("json_validate_failed") is LLMOutputError
    assert classify_bad_request("max_tokens exceeded context length") is LLMError
    assert issubclass(LLMToolRequestError, LLMOutputError)             # existing handlers keep working


class FakeBadRequest(Exception):
    pass


@pytest.fixture
def fake_groq(monkeypatch):
    class FakeClient:
        def __init__(self, api_key, **kwargs):
            self.errors: list[Exception] = []
            self.kwargs: list[dict] = []
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        async def _create(self, **kwargs):
            self.kwargs.append(kwargs)
            if self.errors:
                raise self.errors.pop(0)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=BRIEF, tool_calls=None), finish_reason="stop")],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    module = types.ModuleType("groq")
    module.AsyncGroq = FakeClient
    module.RateLimitError = type("RateLimitError", (Exception,), {})
    module.APIConnectionError = ConnectionError
    module.APITimeoutError = TimeoutError
    module.BadRequestError = FakeBadRequest
    module.APIStatusError = type("APIStatusError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "groq", module)
    return FakeClient


async def test_groq_tool_refusal_becomes_an_llmtoolrequesterror(fake_groq):
    provider = GroqProvider(make_settings(mock_llm=False, groq_api_key="k", groq_model="m"))
    client_obj = provider._keys[0].client
    client_obj.errors.append(FakeBadRequest(
        "Error code: 400 - {'error': {'message': 'Tool choice is none, but model called a tool', "
        "'code': 'tool_use_failed'}}"))

    with pytest.raises(LLMToolRequestError) as exc:
        await provider.complete(agent="researcher", model="m", messages=[], json_mode=True,
                                tools=None, temperature=0.4, max_tokens=100)
    assert "tool this request does not have" in str(exc.value)


async def test_a_toolless_request_declares_no_tool_choice_at_all(fake_groq):
    provider = GroqProvider(make_settings(mock_llm=False, groq_api_key="k", groq_model="m"))
    await provider.complete(agent="researcher", model="m", messages=[], json_mode=True,
                            tools=None, temperature=0.4, max_tokens=100)
    assert provider._keys[0].client.kwargs[0]["response_format"] == {"type": "json_object"}
    assert "tool_choice" not in provider._keys[0].client.kwargs[0]


async def test_a_tool_round_declares_the_tool_and_auto_choice(fake_groq):
    provider = GroqProvider(make_settings(mock_llm=False, groq_api_key="k", groq_model="m"))
    await provider.complete(agent="researcher", model="m", messages=[], json_mode=False,
                            tools=[WEB_SEARCH_TOOL], temperature=0.4, max_tokens=100)
    sent = provider._keys[0].client.kwargs[0]
    assert sent["tool_choice"] == "auto" and sent["tools"] == [WEB_SEARCH_TOOL]
    assert "response_format" not in sent


def test_bad_request_without_a_known_code_is_not_retried_as_output():
    assert issubclass(LLMError, Exception)
    assert classify_bad_request("unsupported model") is LLMError


# ------------------------------------------------------------------ the researcher loop itself
async def test_an_unregistered_tool_call_is_answered_and_the_round_ends(make_ctx):
    ctx, _ = make_ctx()
    ctx.state.idea = "Clip maker for podcasters"
    provider = client(ctx, tool_reply("web.run"), LLMResult(BRIEF, Usage(1, 1, 2)))

    summary = await ResearcherAgent().run(ctx)

    loop = provider.requests[0]["messages"]
    assert provider.requests[0]["tools"] == [WEB_SEARCH_TOOL]
    answered = [m for m in loop if m.get("role") == "tool"]
    assert len(answered) == 1 and answered[0]["tool_call_id"] == "call_1"   # no dangling call id
    assert "not available" in answered[0]["content"]
    assert "Found 1 competitors" in summary
    assert provider.requests[1]["tools"] is None                            # the brief still runs tool-free


async def test_no_search_backend_offers_no_tool_and_promises_no_research(make_ctx):
    """/api/config says a missing TAVILY_API_KEY means built-in heuristics, so the run must not
    dress canned results up as live research."""
    ctx, _ = make_ctx()
    ctx.settings = ctx.settings.model_copy(update={"mock_llm": False, "groq_model": "openai/gpt-oss-120b",
                                                   "tavily_api_key": ""})
    provider = client(ctx, LLMResult(BRIEF, Usage(1, 1, 2)))

    await ResearcherAgent().run(ctx)

    assert [r["tools"] for r in provider.requests] == [None]          # no tool round at all
    first = provider.requests[0]["messages"]
    assert "no web search" in first[1]["content"]                     # the brief is told research did not run
    assert "web_search tool" not in first[0]["content"]               # and on a tool-free prompt


async def test_a_search_key_turns_the_tool_round_back_on(make_ctx):
    ctx, _ = make_ctx(tavily_api_key="tvly-not-used-because-mock-llm")
    provider = client(ctx, tool_reply("web_search"), LLMResult(BRIEF, Usage(1, 1, 2)))

    summary = await ResearcherAgent().run(ctx)

    assert provider.requests[0]["tools"] == [WEB_SEARCH_TOOL]
    assert "at most 3 times" in provider.requests[0]["messages"][1]["content"]
    assert "Found 1 competitors" in summary
