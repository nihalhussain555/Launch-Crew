from app.orchestrator.graph import Orchestrator
from tests.conftest import GOOD_CHECKS
from tests.test_orchestrator import patch_checks


def started(events, after):
    return [d["agent"] for t, d in events[after:] if t == "agent_started"]


async def test_revise_page_rebuilds_and_returns_to_approval(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()
    v, mark = ctx.state.html_version, len(events)

    await orch.revise("Make the hero button bigger", "page")

    s = ctx.state
    assert s.revisions == 1 and s.html_version == v + 1 and s.pending_fixes == {}
    assert "Make the hero button bigger" in s.html            # mock engineer echoes the requested change
    assert started(events, mark) == ["copywriter", "engineer", "critic", "panel"]   # words changed -> audience re-tested
    assert events[-1][0] == "awaiting_approval" and "deployed" not in [t for t, _ in events]


async def test_revise_copy_reruns_copywriter_then_engineer(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()
    mark = len(events)
    await orch.revise("Use a friendlier headline", "copy")
    assert started(events, mark) == ["copywriter", "engineer", "critic"]


async def test_revise_design_reruns_designer_then_engineer(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()
    mark = len(events)
    await orch.revise("Warmer colours", "design")
    assert started(events, mark) == ["designer", "engineer", "critic"]