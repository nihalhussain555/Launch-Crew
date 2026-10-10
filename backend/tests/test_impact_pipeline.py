"""The impact-aware edit pipeline: measure before writing, prove what moved, keep the workspace restorable."""
import pytest

from app.orchestrator import artifacts
from app.orchestrator.graph import Orchestrator
from app.services import workspace_manager
from tests.conftest import GOOD_CHECKS
from tests.test_orchestrator import patch_checks


async def build(make_ctx, monkeypatch):
    patch_checks(monkeypatch, [GOOD_CHECKS])
    ctx, events = make_ctx()
    orch = Orchestrator(ctx)
    await orch.run_until_approval()
    return ctx, events, orch


def engineer_prompt(spy):
    return next(content for agent, content in spy if agent == "engineer" and "CURRENT_HTML" in content)


@pytest.fixture
def spy_on_prompts():
    """Record every (agent, user prompt) the crew sends, then let the mock provider answer as usual."""
    def attach(ctx):
        calls, original = [], ctx.llm.chat

        async def wrapped(*, agent, messages, **kw):
            calls.append((agent, messages[-1]["content"]))
            return await original(agent=agent, messages=messages, **kw)

        ctx.llm.chat = wrapped
        return calls
    return attach


async def test_revise_measures_the_change_before_the_engineer_writes(make_ctx, monkeypatch, spy_on_prompts):
    ctx, _, orch = await build(make_ctx, monkeypatch)
    prompts = spy_on_prompts(ctx)
    v = ctx.state.html_version

    await orch.revise("Make the hero button bigger", "page")
    s = ctx.state

    prompt = engineer_prompt(prompts)
    assert "IMPACT REPORT for v1" in prompt and "RULES:" in prompt
    assert prompt.index("IMPACT REPORT") < prompt.index("CURRENT_HTML:")   # measured first, then asked for
    assert s.impact["version"] == v and s.html_version == v + 1             # the report describes the pre-edit build
    assert s.impact["request"] == "Make the hero button bigger"
    assert s.impact["counts"]["files"] >= 1
    assert {"index.html", "styles.css"} <= set(s.changed_files["changed"])  # the page and its derived copy moved
    assert s.validation == {**s.validation, "version": s.html_version, "status": "clean",
                            "kind": "crew rebuild", "check_errors": 0, "sanitizer_removed": 0}
    assert s.validation["lines_added"] + s.validation["lines_removed"] >= 1


async def test_impact_degrades_instead_of_blocking_a_rebuild(make_ctx, monkeypatch):
    """A workspace it cannot read costs the report, not the run."""
    ctx, _, orch = await build(make_ctx, monkeypatch)
    ctx.state.files[1]["key"] = f"{ctx.run_id}/workspace/lost.css"   # styles.css is no longer readable

    await orch.revise("Make the hero button bigger", "page")
    s = ctx.state

    assert s.impact["risks"][0]["id"] == "no-index"
    assert "could not be read" in s.impact["risks"][0]["message"]
    assert s.changed_files is None and s.validation is None      # nothing was measured, so nothing is claimed
    assert s.html_version == 2                                   # and the rebuild went ahead anyway
    assert sorted(await workspace_manager.load_texts(ctx)) == sorted(f["name"] for f in s.files)


async def test_a_file_level_change_snapshots_then_patches_both_copies(make_ctx, monkeypatch):
    ctx, _, orch = await build(make_ctx, monkeypatch)
    css = await artifacts.file_text(ctx, "styles.css")
    changes = [{"file": "styles.css", "op": "append", "text": "/* touched */", "note": "marker"}]

    plan = await orch.apply_workspace_changes(changes, "append a marker to styles.css")
    s = ctx.state

    assert plan["status"] == "applied"
    assert plan["summary"]["files"] == ["styles.css"]
    assert s.impact["counts"]["targets"] >= 1
    assert plan["summary"]["scope"] in ("single-file", "multi-file")   # the named file is what the report scoped
    assert plan["result"]["version"] == s.html_version == 2
    assert set(plan["result"]["changed"]) == {"index.html", "styles.css", "README.md"}
    assert next(r for r in s.changed_files["files"] if r["file"] == "app.js")["status"] == "unchanged"
    assert s.workspace_versions[0]["w"] == 1 and s.workspace_versions[0]["html_version"] == 1
    assert {f["name"] for f in s.workspace_versions[0]["files"]} >= {"index.html", "styles.css"}

    captured = await workspace_manager.snapshot_page(ctx, 1)
    assert "<html" in captured.lower() and "/* touched */" not in captured   # the workspace as it was before

    page = await artifacts.file_text(ctx, "index.html")
    derived = await artifacts.file_text(ctx, "styles.css")
    assert page.count("/* touched */") == 1 and derived.count("/* touched */") == 1   # folded, not just patched
    assert derived.startswith(css.rstrip()[:40])                 # the edit was appended to what was there
    assert s.revisions == 1 and s.chat[-2]["target"] == "files"
    assert s.validation["kind"] == "file patch" and s.validation["status"] == "clean"
    assert s.validation["workspace_version"] == 1


async def test_apply_refuses_without_touching_the_workspace(make_ctx, monkeypatch):
    ctx, _, orch = await build(make_ctx, monkeypatch)
    before = ctx.state.html_version, ctx.state.files, ctx.state.workspace_versions

    with pytest.raises(workspace_manager.WorkspaceError, match="not in that file"):
        await orch.apply_workspace_changes(
            [{"file": "styles.css", "op": "replace", "find": "#no-such-selector-xyz", "replace": "x"}], "nope")

    assert (ctx.state.html_version, ctx.state.files, ctx.state.workspace_versions) == before


async def test_restoring_a_snapshot_puts_every_file_back(make_ctx, monkeypatch):
    ctx, _, orch = await build(make_ctx, monkeypatch)
    original = await artifacts.file_text(ctx, "index.html")
    plan = await orch.apply_workspace_changes([{"file": "styles.css", "op": "append", "text": "/* touched */"}],
                                              "add a marker")
    assert "/* touched */" in await artifacts.file_text(ctx, "styles.css")

    await orch.restore_workspace_snapshot(plan["result"]["workspace_version"])
    s = ctx.state

    assert "/* touched */" not in s.html
    assert s.html_version == 3
    restored = await artifacts.file_text(ctx, "index.html")
    assert restored == original                                  # the page is byte-for-byte the captured one
    assert [v["w"] for v in s.workspace_versions] == [1, 2]      # restoring snapshots the state it replaced
    assert s.validation["kind"] == "workspace restore" and s.validation["restored_from"] == 1
    assert "Restored workspace snapshot w1 as v3" in s.chat[-1]["text"]
