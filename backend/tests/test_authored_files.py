"""Feature source written beside the page: listed with the build, kept through a rebuild, restored with it.

`app/agents/styles.py` and the Engineer own the page; a feature build (Brief 1) additionally hands over
server code, a database schema and setup notes the user runs somewhere else. Four promises are tested
here: those files cannot take a name the page owns, they are not quietly dropped by the next publish,
they are snapshotted and restored as part of the file set, and a patch aimed at one is refused rather
than measured and discarded.
"""
import pytest

from app.orchestrator import artifacts
from app.orchestrator.state import RunState
from app.services import workspace_manager as wm

from tests.test_workspace_manager import PAGE, build_ctx, run

AUTHORED = "def register(email: str, password: str) -> None:\n    raise NotImplementedError\n"


def write(ctx, name="feature_auth.py", text=AUTHORED, source="authentication"):
    entries = run(wm.stage_authored(ctx, [{"name": name, "text": text, "source": source}]))
    return wm.register_authored(ctx.state, entries)


# ------------------------------------------------------------------ writing and listing

def test_an_authored_file_is_listed_with_the_pages_files_and_reads_back():
    ctx = build_ctx()
    assert write(ctx) == ["feature_auth.py"]
    run(artifacts.publish(ctx))
    names = {f["name"] for f in ctx.state.files}
    assert {"index.html", "styles.css", "app.js", "README.md", "feature_auth.py"} <= names
    entry = next(f for f in ctx.state.files if f["name"] == "feature_auth.py")
    assert entry["language"] == "py" and entry["bytes"] == len(AUTHORED.encode())
    assert run(artifacts.file_text(ctx, "feature_auth.py")) == AUTHORED


def test_a_rebuild_never_drops_source_the_crew_cannot_derive():
    ctx = build_ctx()
    write(ctx)
    run(artifacts.publish(ctx))
    # The crew rebuilds: a different page, same run. The page's own files are re-cut from it.
    ctx.state.html = PAGE.replace("Track habits on your own shift", "Track habits every night shift")
    files = run(artifacts.publish(ctx, note="Crew rebuild"))
    by_name = {f["name"]: f for f in files}
    assert "feature_auth.py" in by_name, "a rebuild deleted someone's server code"
    assert by_name["feature_auth.py"]["bytes"] == len(AUTHORED.encode())
    assert run(artifacts.file_text(ctx, "feature_auth.py")) == AUTHORED


def test_the_page_never_absorbs_authored_source():
    ctx = build_ctx()
    write(ctx)
    before = ctx.state.html
    run(artifacts.publish(ctx))
    assert ctx.state.html == before
    assert "NotImplementedError" not in run(artifacts.file_text(ctx, "index.html"))


def test_an_authored_entry_survives_the_run_state_round_trip():
    ctx = build_ctx()
    write(ctx)
    restored = RunState.model_validate(ctx.state.persisted())
    assert [f["name"] for f in restored.authored_files] == ["feature_auth.py"]
    assert restored.authored_files[0]["source"] == "authentication"


# ------------------------------------------------------------------ what it may not be called

@pytest.mark.parametrize("name", ["index.html", "styles.css", "app.js", "README.md"])
def test_an_authored_file_cannot_take_a_name_the_page_owns(name):
    ctx = build_ctx()
    with pytest.raises(wm.WorkspaceError, match="rebuilt from the page"):
        write(ctx, name=name)


@pytest.mark.parametrize("bad", ["", "a/b.py", "../escape.py", ".hidden.py", "no_extension",
                                 "run.exe", "two words.py", "server/main.py"])
def test_an_authored_name_follows_the_same_path_rules_as_any_other(bad):
    with pytest.raises(wm.WorkspaceError):
        wm.validate_authored([{"name": bad, "text": AUTHORED}])


def test_authored_source_is_refused_when_it_is_empty_oversized_or_repeated():
    with pytest.raises(wm.WorkspaceError, match="empty or stub"):
        wm.validate_authored([{"name": "a.py", "text": "   "}])
    with pytest.raises(wm.WorkspaceError, match="larger than"):
        wm.validate_authored([{"name": "a.py", "text": "x" * (wm.MAX_WORKSPACE_FILE_BYTES + 1)}])
    with pytest.raises(wm.WorkspaceError, match="appears twice"):
        wm.validate_authored([{"name": "a.py", "text": AUTHORED}, {"name": "a.py", "text": AUTHORED}])
    with pytest.raises(wm.WorkspaceError, match="Too many files"):
        wm.validate_authored([{"name": f"f{i}.py", "text": AUTHORED} for i in range(30)])
    with pytest.raises(wm.WorkspaceError, match="No files"):
        wm.validate_authored([])


# ------------------------------------------------------------------ patching rules

def test_patching_an_authored_file_is_refused_instead_of_quietly_dropped():
    """Only the page is published, so a patch to a stored file would be measured, then lost.

    `prepare_changes` folds derived-asset edits back into the page and publishes the page; an authored
    file has no such path back. The workspace says so at plan time instead of reporting a change that
    never arrives.
    """
    ctx = build_ctx()
    write(ctx)
    run(artifacts.publish(ctx))
    with pytest.raises(wm.WorkspaceError, match="feature source"):
        run(wm.prepare_changes(ctx, [{"file": "feature_auth.py", "op": "replace",
                                      "find": "NotImplementedError", "replace": "pass"}]))
    assert run(artifacts.file_text(ctx, "feature_auth.py")) == AUTHORED


def test_an_authored_file_appears_in_the_workspace_index_like_any_other():
    ctx = build_ctx()
    write(ctx)
    run(artifacts.publish(ctx))
    index = run(wm.index_workspace(ctx))
    entry = next(f for f in index["files"] if f["name"] == "feature_auth.py")
    assert entry["language"] == "py" and entry["indexed"] is True


# ------------------------------------------------------------------ snapshots and restore

def test_a_snapshot_carries_the_authored_files_with_the_page():
    ctx = build_ctx()
    write(ctx)
    run(artifacts.publish(ctx))
    record = run(wm.capture(ctx, note="before a feature change"))
    entry = next(f for f in record["files"] if f["name"] == "feature_auth.py")
    assert run(ctx.storage.load(entry["key"])).decode() == AUTHORED


def test_restoring_a_snapshot_rolls_feature_source_back_with_the_page():
    ctx = build_ctx()
    write(ctx, text="def register(email: str) -> None:\n    pass\n")
    run(artifacts.publish(ctx))
    record = run(wm.capture(ctx, note="v1 of the feature"))
    write(ctx, text="def register(email: str, password: str) -> None:\n    raise RuntimeError('nope')\n")
    run(artifacts.publish(ctx))
    assert "RuntimeError" in run(artifacts.file_text(ctx, "feature_auth.py"))

    assert run(wm.restore_authored(ctx, record["w"])) == ["feature_auth.py"]
    assert ctx.state.authored_files[0]["bytes"] == len("def register(email: str) -> None:\n    pass\n")
    assert run(artifacts.file_text(ctx, "feature_auth.py")) == "def register(email: str) -> None:\n    pass\n"
    # publish re-lists what the state now holds, so the restored file is still in the workspace
    assert "feature_auth.py" in {f["name"] for f in run(artifacts.publish(ctx))}


def test_a_snapshot_from_before_the_feature_existed_clears_it_on_restore():
    ctx = build_ctx()
    record = run(wm.capture(ctx, note="nothing authored yet"))
    write(ctx)
    run(artifacts.publish(ctx))
    assert run(wm.restore_authored(ctx, record["w"])) == []
    assert ctx.state.authored_files == []
    assert "feature_auth.py" not in {f["name"] for f in run(artifacts.publish(ctx))}


def test_a_restore_reports_a_snapshot_whose_blob_is_gone():
    ctx = build_ctx()
    write(ctx)
    record = run(wm.capture(ctx, note="doomed"))
    entry = next(f for f in record["files"] if f["name"] == "feature_auth.py")
    run(ctx.storage.delete(entry["key"]))
    with pytest.raises(wm.WorkspaceError, match="could not be read from snapshot"):
        run(wm.restore_authored(ctx, record["w"]))


def test_writing_the_same_name_twice_replaces_it_instead_of_listing_it_twice():
    ctx = build_ctx()
    write(ctx, text="ONE = 1\n")
    write(ctx, text="TWO = 2\n")
    assert len(ctx.state.authored_files) == 1
    assert ctx.state.authored_files[0]["bytes"] == len("TWO = 2\n")
    run(artifacts.publish(ctx))
    assert [f["name"] for f in ctx.state.files].count("feature_auth.py") == 1
    assert run(artifacts.file_text(ctx, "feature_auth.py")) == "TWO = 2\n"
