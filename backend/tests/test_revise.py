from app.orchestrator.graph import Orchestrator
from app.utils.color import contrast_ratio, hex_to_rgb, relative_luminance
from tests.conftest import GOOD_CHECKS
from tests.test_orchestrator import patch_checks


def started(events, after):
    return [d["agent"] for t, d in events[after:] if t == "agent_started"]


async def test_revise_page_rebuilds_and_returns_to_approval(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()
    v, before, mark = ctx.state.html_version, ctx.state.html, len(events)

    await orch.revise("Make the hero button bigger", "page")

    s = ctx.state
    assert s.revisions == 1 and s.html_version == v + 1 and s.pending_fixes == {}
    assert s.html != before and ".btn{min-height:60px;padding:0 38px;font-size:19px}" in s.html
    assert started(events, mark) == ["engineer", "critic"]   # page-only edit: the audience is not re-tested
    assert events[-1][0] == "awaiting_approval" and "deployed" not in [t for t, _ in events]


async def test_revise_copy_changes_the_words_on_the_page(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, _ = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()

    await orch.revise('Change the headline to "Track habits, night shift style"', "copy")

    s = ctx.state
    assert s.content.headline == "Track habits, night shift style"
    assert "Track habits, night shift style" in s.html            # the rebuild carried the new words


async def test_revise_design_recolours_the_page(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, _ = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()

    await orch.revise("Make the button #0F766E", "design")

    s = ctx.state
    assert s.design.palette.primary.lower() == "#0f766e"
    assert "#0f766e" in s.html.lower()


async def test_revise_dark_request_actually_goes_dark(make_ctx, monkeypatch):
    """'Make the page dark' has to land on the dark side of the band where AA text is reachable."""
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, _ = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()

    await orch.revise("make the page dark with a green button", "design")

    pal = ctx.state.design.palette
    assert relative_luminance(hex_to_rgb(pal.background)) < 0.16
    assert contrast_ratio(pal.text, pal.background) >= 4.5
    assert pal.background.lower() in ctx.state.html.lower()


async def test_earlier_page_edits_survive_later_revisions(make_ctx, monkeypatch):
    """Every build is re-composed from copy + design, so a CSS edit has to be replayed to stick."""
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, _ = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()
    await orch.revise("Make the hero button bigger", "page")
    await orch.revise("Add more spacing between the sections", "page")
    await orch.revise('Change the subheadline to "Calm check-ins for nights"', "copy")

    html = ctx.state.html
    assert ".btn{min-height:60px" in html and "section{padding:84px 0}" in html
    assert "Calm check-ins for nights" in html


async def test_revise_copy_reruns_copywriter_then_engineer(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()
    mark = len(events)
    await orch.revise("Use a friendlier headline", "copy")
    assert started(events, mark) == ["copywriter", "engineer", "critic", "panel"]   # words changed -> audience re-tested


async def test_revise_design_reruns_designer_then_engineer(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()
    mark = len(events)
    await orch.revise("Warmer colours", "design")
    assert started(events, mark) == ["designer", "engineer", "critic"]