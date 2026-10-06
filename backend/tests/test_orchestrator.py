import pytest

from app.agents.base import AgentOutputError, BaseAgent
from app.agents.schemas import Strategy
from app.llm.client import LLMClient, LLMResult, Usage
from app.orchestrator.graph import Orchestrator
from app.orchestrator.state import BudgetExceeded, StepLimitExceeded
from app.tools import browser_checks
from tests.conftest import BAD_CHECKS, GOOD_CHECKS


def patch_checks(monkeypatch, sequence):
    """Replace Playwright with a scripted list of check results (last one repeats)."""
    calls = {"n": 0}

    async def fake(html):
        checks = sequence[min(calls["n"], len(sequence) - 1)]
        calls["n"] += 1
        return checks, {"desktop": b"d", "mobile": b"m"}

    monkeypatch.setattr(browser_checks, "run_checks", fake)
    return calls


def types(events): return [t for t, _ in events]


async def test_full_pipeline_reaches_approval_gate_without_deploying(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    await Orchestrator(ctx).run_until_approval()
    s = ctx.state
    assert s.brief and s.strategy and s.content and s.design and s.html and s.html_key
    assert types(events)[-1] == "awaiting_approval"
    assert "deployed" not in types(events) and s.deploy_url is None      # human approval required
    assert "tool_call" in types(events) and "check_results" in types(events) and "screenshot_ready" in types(events)
    assert [e["agent"] for t, e in events if t == "agent_started"][:5] == ["researcher", "strategist", "copywriter", "designer", "engineer"]


async def test_critic_loop_fixes_then_passes(make_ctx, monkeypatch):
    calls = patch_checks(monkeypatch, [BAD_CHECKS, GOOD_CHECKS])
    ctx, events = make_ctx()
    await Orchestrator(ctx).run_until_approval()
    assert calls["n"] == 2 and ctx.state.html_version == 2 and ctx.state.iteration == 2
    assert "critic_feedback" in types(events)


async def test_critic_iteration_cap(make_ctx, monkeypatch):
    calls = patch_checks(monkeypatch, [BAD_CHECKS])
    ctx, events = make_ctx(max_critic_iterations=2)
    await Orchestrator(ctx).run_until_approval()
    assert calls["n"] == 2 and ctx.state.html_version == 2          # 1 initial build + 1 fix round
    assert events[-1][1]["remaining_errors"] == 1


async def test_launch_after_approval(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()
    await orch.launch()
    s = ctx.state
    assert s.deploy_url and s.deploy_mock and len(s.social_posts) == 3 and s.email
    assert types(events)[-1] == "deployed"


async def test_token_budget_enforced(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, _ = make_ctx(max_token_budget=50)
    with pytest.raises(BudgetExceeded):
        await Orchestrator(ctx).run_until_approval()


async def test_step_limit_enforced(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, _ = make_ctx(max_steps=3)
    with pytest.raises(StepLimitExceeded):
        await Orchestrator(ctx).run_until_approval()


async def test_invalid_output_retried_once_then_fails(make_ctx):
    ctx, _ = make_ctx()
    n = {"c": 0}

    class Bad:
        async def complete(self, **kw):
            n["c"] += 1
            return LLMResult('{"wrong": true}', Usage(1, 1, 2))

    ctx.llm = LLMClient(ctx.settings, provider=Bad())
    agent = BaseAgent(); agent.name = "strategist"
    with pytest.raises(AgentOutputError):
        await agent.call_json(ctx, "IDEA: x", Strategy)
    assert n["c"] == 2                                              # exactly one retry


async def test_invalid_then_valid_recovers(make_ctx):
    ctx, _ = make_ctx()
    good = ('{"positioning":"p","persona":{"name":"n","description":"d"},"key_messages":["a","b","c"]}')
    outs = iter(["not json at all", good])

    class Once:
        async def complete(self, **kw):
            return LLMResult(next(outs), Usage(1, 1, 2))

    ctx.llm = LLMClient(ctx.settings, provider=Once())
    agent = BaseAgent(); agent.name = "strategist"
    assert (await agent.call_json(ctx, "IDEA: x", Strategy)).positioning == "p"
