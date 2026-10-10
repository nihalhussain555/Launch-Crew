"""File-level workspace edits: path rules, patch rules, folding into the page, snapshots."""
import asyncio

import pytest

from app.config import Settings
from app.orchestrator import artifacts
from app.orchestrator.state import RunContext, RunState
from app.services import change_impact, workspace_manager as wm
from app.tools import splitter
from app.tools.file_writer import LocalStorage

from tests.test_change_impact import APP_JS, STYLES

# A page whose embedded <style>/<script> are exactly the fixtures the impact tests use, so the
# workspace the crew publishes (styles.css / app.js) is those same texts copied out.
PAGE = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Night-shift habit tracker</title></head>
<body>
<a class="skip-link" href="#lc-main">Skip to content</a>
<main id="lc-main" class="page">
  <h1 id="hero-title">Track habits on your own shift</h1>
  <form id="signup" action="">
    <label for="email">Email</label>
    <input id="email" name="email_address" type="email">
    <button class="btn primary" type="submit">Join</button>
  </form>
</main>
<style>
{STYLES.strip()}
</style>
<script>
{APP_JS.strip()}
</script>
</body></html>
"""


class MemoryStorage(LocalStorage):
    def __init__(self):
        self.blobs = {}

    async def save(self, run_id, name, data):
        self.blobs[f"{run_id}/{name}"] = data
        return f"{run_id}/{name}"

    async def load(self, key):
        return self.blobs[key]

    async def delete(self, key):
        self.blobs.pop(key, None)


def build_ctx(page=PAGE):
    """A run that has already published its file set, which is the only state worth editing."""
    async def sink(type_, data):
        pass

    state = RunState(idea="Night-shift habit tracker")
    state.html, state.html_version = page, 1
    state.check_summary = {"errors": 0, "warnings": 1}
    ctx = RunContext(run_id="run1", settings=Settings(_env_file=None), llm=None, state=state,
                     sink=sink, storage=MemoryStorage())
    asyncio.run(artifacts.publish(ctx, note="Initial build"))
    return ctx


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ path validation

@pytest.mark.parametrize("bad", ["", "   ", "a/b.css", "..\\escape.css", "../secrets.txt",
                                 "/etc/passwd", ".hidden.css", "styles.css.md.md.md.md.md.x"])
def test_unsafe_or_empty_names_are_rejected(bad):
    with pytest.raises(wm.WorkspaceError):
        wm.validate_name(bad)


def test_plain_workspace_names_pass_and_are_trimmed():
    assert wm.validate_name("  'styles.css'  ") == "styles.css"
    assert wm.validate_name("test_page.py") == "test_page.py"
    with pytest.raises(wm.WorkspaceError, match="unsupported extension"):
        wm.validate_name("shell.sh")


def test_only_files_of_this_build_can_be_patched():
    c = build_ctx()
    assert wm.known_file(c.state, "styles.css")["name"] == "styles.css"
    with pytest.raises(wm.WorkspaceError) as missing:
        wm.known_file(c.state, "vendor.css")
    assert missing.value.status == 404
    with pytest.raises(wm.WorkspaceError, match="rewritten by the crew"):
        wm.known_file(c.state, "README.md")


# ------------------------------------------------------------------ patch validation

def test_patch_shapes_are_checked_before_anything_is_read():
    assert wm.validate_patch({"file": "styles.css", "find": ".a", "replace": ".b"})["op"] == "replace"
    assert wm.validate_patch({"file": "a.js", "op": "SET", "text": "x"})["op"] == "set"
    bad_patches = [{"file": "styles.css", "op": "sed"},
                   {"file": "styles.css", "find": "   "},
                   {"file": "styles.css", "op": "append"},
                   {"file": "styles.css", "op": "set", "text": "x" * (wm.MAX_PATCH_BYTES + 1)}]
    for bad in bad_patches:
        with pytest.raises(wm.WorkspaceError):
            wm.validate_patch(bad)
    with pytest.raises(wm.WorkspaceError):
        wm.validate_patch("not-a-dict")
    with pytest.raises(wm.WorkspaceError, match="appears twice"):
        wm.validate_changes([{"file": "styles.css", "find": "a", "replace": "b"},
                             {"file": "styles.css", "find": "c", "replace": "d"}])


def test_apply_op_is_exact_and_says_what_it_missed():
    css = ".card { padding: 8px }\n.card { padding: 8px }\n"
    append = {"file": "styles.css", "op": "append", "text": ".x { color: red }"}
    assert wm.apply_op(css, append).endswith(".x { color: red }\n")
    assert wm.apply_op(".a { color: red }", {"file": "styles.css", "op": "set", "text": ".a { }"}) == ".a { }"
    with pytest.raises(wm.WorkspaceError, match="occurs 2 times"):
        wm.apply_op(css, {"file": "styles.css", "op": "replace",
                          "find": ".card { padding: 8px }", "replace": ".card { padding: 4px }"})
    replaced = wm.apply_op(css, {"file": "styles.css", "op": "replace_all",
                                 "find": "padding: 8px", "replace": "padding: 16px"})
    assert replaced.count("padding: 16px") == 2 and "padding: 8px" not in replaced
    with pytest.raises(wm.WorkspaceError, match="not in that file") as miss:
        wm.apply_op(css, {"file": "styles.css", "op": "replace", "find": "#hero-title", "replace": "x"})
    assert ".card" in miss.value.message            # the hint shows what the file does hold


def test_fold_writes_an_asset_back_into_the_page_and_survives_a_split():
    c = build_ctx()
    page = c.state.html
    for asset, block in (("styles.css", STYLES), ("app.js", APP_JS)):
        _, assets = splitter.split_page(page)
        original = next(a.text for a in assets if a.name == asset)
        assert original.strip() == block.strip()               # the asset really is the page's block
        extra = "\n.toggled { outline: 2px solid }" if asset == "styles.css" else "\nfunction extra() { return 1; }"
        patched = original + extra
        folded = wm.fold_into_page(page, asset, patched)
        assert (".toggled" if asset == "styles.css" else "extra()") in folded
        _, again = splitter.split_page(folded)
        assert next(a.text for a in again if a.name == asset).strip() == patched.strip()


def test_fold_refuses_a_page_it_cannot_map_back_exactly():
    two_blocks = ("<html><head><style>.a{}</style><style>.b{}</style></head><body>hi</body></html>")
    with pytest.raises(wm.WorkspaceError, match="2 <style> blocks"):
        wm.fold_into_page(two_blocks, "styles.css", ".a{color:red}")
    no_block = "<html><head></head><body>hi</body></html>"
    with pytest.raises(wm.WorkspaceError, match="has none"):
        wm.fold_into_page(no_block, "app.js", "var a = 1;")
    assert wm.fold_into_page(no_block, "README.md", "text") == no_block


# ------------------------------------------------------------------ apply + preserve

def test_prepare_changes_touches_only_what_it_names():
    c = build_ctx()
    before, after, page = run(wm.prepare_changes(c, [
        {"file": "styles.css", "op": "replace", "find": "#lc-main { max-width: 900px }",
         "replace": "#lc-main { max-width: 1100px }"}]))
    assert "max-width: 1100px" in page                      # folded into the canonical document
    assert "max-width: 1100px" in after["styles.css"]
    assert after["index.html"] != before["index.html"]
    assert before["README.md"] == after["README.md"]


def test_commit_publishes_snapshots_and_measures_the_change():
    c = build_ctx()
    before, after, page = run(wm.prepare_changes(c, [
        {"file": "app.js", "op": "append", "text": "function extra() { return 2; }"}]))
    report = run(wm.commit(c, before=before, page=page, note="Added a helper"))
    assert report["version"] == c.state.html_version == 2
    assert "app.js" in report["changed"] and "index.html" in report["changed"]
    assert report["lines_added"] >= 1
    assert c.state.workspace_versions == []                 # capture() is the caller's decision
    assert "extra()" in run(artifacts.file_text(c, "index.html"))
    assert "extra" in run(artifacts.file_text(c, "app.js"))


def test_commit_runs_the_same_sanitizer_a_build_does():
    c = build_ctx()
    before, after, page = run(wm.prepare_changes(c, [
        {"file": "index.html", "op": "replace", "find": "</body>",
         "replace": "<img src=\"https://tracker.example/pixel.png\" alt=\"\"></body>"}]))
    report = run(wm.commit(c, before=before, page=page, note="tried a remote image"))
    assert report["sanitizer_removed"] >= 1
    assert "tracker.example" not in c.state.html


def test_commit_refuses_a_page_that_is_no_longer_a_document_and_writes_nothing():
    c = build_ctx()
    html_version, files = c.state.html_version, list(c.state.files)
    before, after, page = run(wm.prepare_changes(c, [
        {"file": "index.html", "op": "set", "text": "<html><body>not a page"}]))
    with pytest.raises(wm.WorkspaceError) as err:
        run(wm.commit(c, before=before, page=page))
    assert err.value.status == 409
    assert c.state.html_version == html_version and c.state.files == files


def test_a_change_that_would_break_indexing_is_refused(monkeypatch):
    monkeypatch.setattr(wm, "MAX_WORKSPACE_FILE_BYTES", 200)
    with pytest.raises(wm.WorkspaceError, match="indexable"):
        wm.check_sizes({"styles.css": "x" * 201})
    with pytest.raises(wm.WorkspaceError, match="indexable"):
        wm.check_sizes({"index.html": "x" * 500, "styles.css": "x" * 300}, {"styles.css"})
    wm.check_sizes({"index.html": "x" * 500}, {"styles.css"})       # untouched files are not this patch's problem


def test_capture_snapshots_every_file_and_trim_keeps_the_newest():
    c = build_ctx()
    first = run(wm.capture(c, note="before the first edit"))
    assert first["w"] == 1 and {f["name"] for f in first["files"]} >= {"index.html", "styles.css", "app.js"}
    assert all(f["key"] in c.storage.blobs for f in first["files"])
    assert first["html_version"] == c.state.html_version

    for i in range(2, wm.KEEP_WORKSPACE_VERSIONS + 4):
        run(wm.capture(c, note=f"snapshot {i}", changed=["styles.css"]))
    kept = c.state.workspace_versions
    assert len(kept) == wm.KEEP_WORKSPACE_VERSIONS
    assert kept[-1]["w"] == wm.KEEP_WORKSPACE_VERSIONS + 3
    assert kept[0]["changed"] == ["styles.css"]
    dropped = f"run1/workspace/w1/index.html"
    assert dropped not in c.storage.blobs                    # the oldest blobs go with it


def test_snapshot_page_round_trips_the_canonical_document():
    c = build_ctx()
    snapshot = run(wm.capture(c, note="keep this"))
    stored = run(wm.snapshot_page(c, snapshot["w"]))
    assert stored == c.state.html
    with pytest.raises(wm.WorkspaceError) as missing:
        run(wm.snapshot_page(c, 99))
    assert missing.value.status == 404


def test_load_texts_is_strict_about_a_lost_blob():
    c = build_ctx()
    c.storage.blobs.pop(c.state.files[1]["key"])
    with pytest.raises(wm.WorkspaceError):
        run(wm.load_texts(c))


# ------------------------------------------------------------------ index + plan plumbing

def test_index_workspace_reads_the_run_not_the_disk():
    c = build_ctx()
    x = run(wm.index_workspace(c))
    assert x["version"] == c.state.html_version == 1
    assert x["counts"]["indexed"] == x["counts"]["files"] == len(c.state.files)
    assert {f["name"] for f in x["files"]} == {f["name"] for f in c.state.files}
    assert any(s["name"] == "lc-main" and s["file"] == "index.html" for s in x["symbols"])
    assert not x["truncated"]


def test_impact_of_a_planned_change_is_measured_from_the_workspace_index():
    c = build_ctx()
    x = run(wm.index_workspace(c))
    report = change_impact.analyze(x, "rename #lc-main to shell", version=c.state.html_version)
    assert report["targets"][0]["name"] == "lc-main"
    assert report["counts"]["errors"] >= 1


def test_record_plan_keeps_the_impact_beside_the_change():
    c = build_ctx()
    x = run(wm.index_workspace(c))
    report = change_impact.analyze(x, "widen #signup")
    changes = wm.validate_changes([{"file": "index.html", "op": "replace", "find": "id=\"signup\"",
                                    "replace": "id=\"signup\" data-wide"}])
    plan = wm.record_plan(c, request="widen #signup", changes=changes, report=report)
    assert plan["id"] == "p1" and plan["status"] == "proposed"
    assert plan["summary"]["files"] == ["index.html"]
    assert plan["impact"]["scope"] == report["scope"]
    for i in range(25):
        wm.record_plan(c, request=f"plan {i}", changes=changes, report=report)
    assert len(c.state.change_plans) == 20


def test_summarise_index_keeps_state_small():
    x = run(wm.index_workspace(build_ctx()))
    s = wm.summarise_index(x)
    assert s["version"] == 1 and s["counts"]["files"] == len(s["files"])
    assert "lc-main" in s["names"] and "symbols" not in s
