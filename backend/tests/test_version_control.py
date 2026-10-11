"""Version control over the workspace: checkpoints, undo/redo, conflicts, renames and both diff views.

The route tests drive the real endpoints with the offline crew (MOCK_LLM), so a checkpoint is proven to
be a file set that can be read back and put in place of a newer one - not a bookkeeping entry that only
looks right. The unit tests cover the timeline bookkeeping that a background pipeline would hide.
"""
import pytest
from fastapi.testclient import TestClient

from app.api import routes_auth
from app.main import app
from app.services import workspace_manager
from app.tools import browser_checks, differ
from tests.conftest import GOOD_CHECKS

MARKER = "/* workspace-marker */"
OTHER = "/* second-change-marker */"


@pytest.fixture
def client(monkeypatch):
    async def fake(html):
        return GOOD_CHECKS, {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    routes_auth._auth_limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    routes_auth._auth_limiter._hits.clear()


@pytest.fixture
def built(client):
    """A logged-in user with one run sitting at the approval gate."""
    r = client.post("/api/auth/register", json={"email": "vc@example.com", "password": "supersecret1", "name": "VC"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A tiny CRM for solo founders"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    return client, h, f"/api/runs/{rid}/workspace", rid


def state(client, h, rid):
    return client.get(f"/api/runs/{rid}", headers=h).json()["state"]


def status(client, h, rid):
    """The run's own status lives on the run document, not inside its state."""
    return client.get(f"/api/runs/{rid}", headers=h).json()["status"]


def raw(client, h, rid, v):
    return client.get(f"/api/runs/{rid}/versions/{v}/html", headers=h).text


def page(client, h, rid, v):
    """The saved page build, broken onto lines the same way every comparison here does it."""
    return differ.readable(raw(client, h, rid, v))


def patch(client, h, ws, text=MARKER, **kw):
    return client.post(f"{ws}/apply", headers=h,
                       json={"changes": [{"file": "styles.css", "op": "append", "text": text}], **kw})


def chat(client, h, rid, text="Make the button bigger"):
    return client.post(f"/api/runs/{rid}/chat", headers=h, json={"text": text})


# --------------------------------------------------------------------------- automatic checkpoints

def test_a_patched_change_checkpoints_the_file_set_it_replaced(built):
    client, h, ws, rid = built
    assert patch(client, h, ws).status_code == 202

    s = state(client, h, rid)
    snap = s["workspace_versions"][-1]
    assert snap["cause"] == {"kind": "file patch", "agent": "user", "plan": "p1", "run_id": rid, "version": 1}
    assert snap["html_version"] == 1 and snap["changed"] == ["index.html", "styles.css"]
    assert {f["name"] for f in snap["files"]} == {"index.html", "styles.css", "app.js", "README.md"}
    assert s["undo_stack"] == [snap["w"]] and s["redo_stack"] == []


def test_a_crew_rebuild_checkpoints_too_and_becomes_the_step_back(built):
    """The reason the checkpoint system exists: an edit nobody chose to snapshot is still undoable."""
    client, h, ws, rid = built
    assert chat(client, h, rid).status_code == 202

    s = state(client, h, rid)
    assert s["html_version"] == 2 and len(s["workspace_versions"]) == 1
    assert s["workspace_versions"][0]["cause"]["kind"] == "crew rebuild"
    assert s["validation"]["kind"] == "crew rebuild"
    assert s["validation"]["workspace_version"] == s["workspace_versions"][0]["w"]


def test_every_change_in_a_mixed_session_gets_its_own_checkpoint(built):
    client, h, ws, rid = built
    patch(client, h, ws, MARKER)
    patch(client, h, ws, OTHER)
    chat(client, h, rid)

    s = state(client, h, rid)
    assert [v["cause"]["kind"] for v in s["workspace_versions"]] == ["file patch", "file patch", "crew rebuild"]
    assert [v["w"] for v in s["workspace_versions"]] == [1, 2, 3]
    assert s["undo_stack"] == [1, 2, 3]


def test_a_version_restore_is_a_checkpointed_change_too(built):
    client, h, ws, rid = built
    chat(client, h, rid)                                    # v2, checkpoint w1 holds v1
    assert client.post(f"/api/runs/{rid}/restore", headers=h, json={"version": 1}).status_code == 202

    s = state(client, h, rid)
    kinds = [v["cause"]["kind"] for v in s["workspace_versions"]]
    assert kinds == ["crew rebuild", "version restore"]     # the rollback is itself reversible
    assert s["undo_stack"] == [1, 2]


# --------------------------------------------------------------------------- undo and redo

def test_undo_returns_the_page_the_crew_rebuilt_and_redo_goes_forward_again(built):
    client, h, ws, rid = built
    before = page(client, h, rid, 1)
    chat(client, h, rid)
    rebuilt = page(client, h, rid, 2)
    assert rebuilt != before

    assert client.post(f"{ws}/undo", headers=h, json={}).status_code == 202
    s = state(client, h, rid)
    assert s["html_version"] == 3                           # a new entry, not a deleted one
    assert page(client, h, rid, 3) == before
    assert s["undo_stack"] == [] and len(s["redo_stack"]) == 1
    assert s["validation"]["step"] == "undo" and s["validation"]["restored_from"] == 1

    assert client.post(f"{ws}/redo", headers=h, json={}).status_code == 202
    s = state(client, h, rid)
    assert page(client, h, rid, 4) == rebuilt
    assert len(s["undo_stack"]) == 1 and s["redo_stack"] == []


def test_history_keeps_every_step_a_restore_replaced(built):
    """The brief's hard rule: putting an old version back must not destroy the newer one."""
    client, h, ws, rid = built
    chat(client, h, rid)
    client.post(f"{ws}/undo", headers=h, json={})

    versions = [v["v"] for v in state(client, h, rid)["versions"]]
    assert versions == [1, 2, 3]                            # v2 is still stored after being undone
    assert client.get(f"/api/runs/{rid}/versions/2/html", headers=h).status_code == 200


def test_undo_walks_back_over_several_changes_one_step_at_a_time(built):
    client, h, ws, rid = built
    patch(client, h, ws, MARKER)
    first = page(client, h, rid, 2)
    patch(client, h, ws, OTHER)
    assert page(client, h, rid, 3) != first

    assert client.post(f"{ws}/undo", headers=h, json={}).status_code == 202
    s = state(client, h, rid)
    assert page(client, h, rid, s["html_version"]) == first
    assert s["undo_stack"] == [1] and len(s["redo_stack"]) == 1

    assert client.post(f"{ws}/undo", headers=h, json={}).status_code == 202
    s = state(client, h, rid)
    assert page(client, h, rid, s["html_version"]) == page(client, h, rid, 1)
    assert s["undo_stack"] == [] and len(s["redo_stack"]) == 2


def test_undo_then_a_new_change_clears_the_redo_chain(built):
    """Standard editor rule, and the honest one: a new change invalidates what was ahead of it."""
    client, h, ws, rid = built
    chat(client, h, rid)
    client.post(f"{ws}/undo", headers=h, json={})
    assert state(client, h, rid)["redo_stack"]

    patch(client, h, ws, OTHER)
    s = state(client, h, rid)
    assert s["redo_stack"] == []
    assert s["undo_stack"][-1] == s["workspace_versions"][-1]["w"]


def test_undo_with_nothing_recorded_is_refused_without_moving_the_run(built):
    client, h, ws, rid = built
    res = client.post(f"{ws}/undo", headers=h, json={})
    assert res.status_code == 409 and "Nothing to undo" in res.json()["detail"]
    s = state(client, h, rid)
    assert status(client, h, rid) == "awaiting_approval"
    assert s["html_version"] == 1 and s["workspace_versions"] == []


def test_redo_with_nothing_stepped_back_is_refused(built):
    client, h, ws, rid = built
    chat(client, h, rid)
    res = client.post(f"{ws}/redo", headers=h, json={})
    assert res.status_code == 409 and "Nothing to redo" in res.json()["detail"]


def test_stepping_the_workspace_costs_no_revision_and_no_tokens(built):
    client, h, ws, rid = built
    chat(client, h, rid)
    run = client.get(f"/api/runs/{rid}", headers=h).json()
    tokens, revisions = run["tokens_used"], state(client, h, rid)["revisions"]

    client.post(f"{ws}/undo", headers=h, json={})
    client.post(f"{ws}/redo", headers=h, json={})
    assert client.get(f"/api/runs/{rid}", headers=h).json()["tokens_used"] == tokens
    assert state(client, h, rid)["revisions"] == revisions


async def test_a_step_swaps_its_pointer_instead_of_losing_it(make_ctx):
    """Undo spends one pointer and keeps the state it left as the reverse move - nothing else moves."""
    ctx, events = make_ctx()
    key = await ctx.storage.save(ctx.run_id, "index.html", b"<html><body>one</body></html>")
    ctx.state.files = [{"name": "index.html", "key": key, "bytes": 30, "language": "html", "note": ""}]
    snap = await workspace_manager.capture(ctx, note="before", cause={"kind": "file patch"})
    workspace_manager.record_change(ctx.state, snap["w"])

    assert workspace_manager.next_step(ctx.state, "undo") == 1      # reading is not spending
    assert workspace_manager.next_step(ctx.state, "undo") == 1
    assert ctx.state.undo_stack == [1] and ctx.state.redo_stack == []

    left = await workspace_manager.capture(ctx, note="left", cause={"kind": "workspace restore"})
    workspace_manager.record_step(ctx.state, left["w"], forward=False)
    assert ctx.state.undo_stack == [] and ctx.state.redo_stack == [2]
    with pytest.raises(workspace_manager.WorkspaceError, match="Nothing to undo"):
        workspace_manager.next_step(ctx.state, "undo")
    assert workspace_manager.next_step(ctx.state, "redo") == 2      # and the way forward is still there


async def test_a_dead_pointer_is_dropped_rather_than_restored(make_ctx):
    """Once the keep window prunes a snapshot its step goes with it, so a step never targets a dead blob."""
    ctx, events = make_ctx(workspace_versions_keep=2)
    key = await ctx.storage.save(ctx.run_id, "index.html", b"<html><body>one</body></html>")
    ctx.state.files = [{"name": "index.html", "key": key, "bytes": 30, "language": "html", "note": ""}]
    for _ in range(3):
        snap = await workspace_manager.capture(ctx, note="x", cause={"kind": "file patch"})
        workspace_manager.record_change(ctx.state, snap["w"])

    assert [v["w"] for v in ctx.state.workspace_versions] == [2, 3]
    assert ctx.state.undo_stack == [2, 3]              # w1's step was dropped as its files were deleted

    left = await workspace_manager.capture(ctx, note="left", cause={"kind": "workspace restore"})
    workspace_manager.record_step(ctx.state, left["w"], forward=False)   # w4 now prunes w2
    assert [v["w"] for v in ctx.state.workspace_versions] == [3, 4]
    assert ctx.state.undo_stack == []                  # w3 spent, the dead w2 never offered
    assert ctx.state.redo_stack == [4]
    with pytest.raises(workspace_manager.WorkspaceError, match="Nothing to undo"):
        workspace_manager.next_step(ctx.state, "undo")


def test_a_step_is_never_attempted_against_a_pruned_snapshot(built, monkeypatch):
    """End-to-end version of the same rule: the run answers with a message, never a broken restore."""
    client, h, ws, rid = built
    monkeypatch.setattr(app.state.settings, "workspace_versions_keep", 2)
    for text in (MARKER, OTHER, "/* third */", "/* fourth */"):
        assert patch(client, h, ws, text).status_code == 202

    res = None
    for _ in range(6):
        res = client.post(f"{ws}/undo", headers=h, json={})
        if res.status_code == 409:
            break
        assert res.status_code == 202
    assert res.status_code == 409 and "Nothing to undo" in res.json()["detail"]
    assert status(client, h, rid) == "awaiting_approval"          # the refused step left the run at the gate


# --------------------------------------------------------------------------- named checkpoints

def test_a_named_checkpoint_stores_history_without_changing_the_page(built):
    client, h, ws, rid = built
    before = page(client, h, rid, 1)
    res = client.post(f"{ws}/checkpoint", headers=h,
                      json={"label": "before pricing rewrite", "note": "reviewed with the founder"})
    assert res.status_code == 200
    snap = res.json()["snapshot"]
    assert snap["label"] == "before pricing rewrite" and snap["cause"]["kind"] == "manual checkpoint"
    assert snap["html_version"] == 1
    assert snap["note"] == "reviewed with the founder"      # the note describes, the label names

    s = state(client, h, rid)
    assert page(client, h, rid, 1) == before                # nothing was rewritten
    assert s["undo_stack"] == []                            # and it is not a step back
    assert s["revisions"] == 0                              # nor does it spend the run's edit budget
    assert res.json()["undo"] == {"can_undo": False, "can_redo": False, "undo_steps": 0, "redo_steps": 0,
                                  "next_undo": None, "next_redo": None}


def test_a_checkpoint_is_undoable_as_a_state_but_not_as_a_change(built):
    """A checkpoint marks a moment; the change that follows it is what undo steps back over."""
    client, h, ws, rid = built
    client.post(f"{ws}/checkpoint", headers=h, json={"label": "release candidate"})
    patch(client, h, ws, MARKER)

    s = state(client, h, rid)
    assert [v["label"] for v in s["workspace_versions"]] == ["release candidate", ""]
    assert s["undo_stack"] == [2]                           # only the patch is a step back
    client.post(f"{ws}/undo", headers=h, json={})
    assert page(client, h, rid, state(client, h, rid)["html_version"]) == page(client, h, rid, 1)


def test_a_checkpoint_labels_the_snapshot_that_later_diffs(built):
    client, h, ws, rid = built
    client.post(f"{ws}/checkpoint", headers=h, json={"label": "release candidate"})
    patch(client, h, ws, MARKER)

    data = client.get(f"{ws}/versions", headers=h).json()
    assert {s["label"] for s in data["snapshots"]} == {"release candidate", ""}
    diff = client.get(f"{ws}/diff?w=1", headers=h).json()
    assert diff["from"]["label"] == "release candidate" and diff["from"]["cause"]["kind"] == "manual checkpoint"


def test_renaming_a_snapshot_keeps_every_entry_and_its_content(built):
    client, h, ws, rid = built
    patch(client, h, ws, MARKER)
    numbers = [v["w"] for v in state(client, h, rid)["workspace_versions"]]

    res = client.post(f"{ws}/versions/{numbers[0]}/label", headers=h, json={"label": "the one before the fix"})
    assert res.status_code == 200 and res.json()["snapshot"]["label"] == "the one before the fix"
    s = state(client, h, rid)
    assert [v["w"] for v in s["workspace_versions"]] == numbers
    assert s["workspace_versions"][0]["label"] == "the one before the fix"
    assert MARKER in client.get(f"/api/runs/{rid}/files/styles.css", headers=h).text


def test_an_empty_snapshot_name_is_refused(built):
    client, h, ws, rid = built
    patch(client, h, ws, MARKER)
    assert client.post(f"{ws}/versions/1/label", headers=h, json={"label": "   "}).status_code == 422
    assert client.post(f"{ws}/versions/9/label", headers=h, json={"label": "x"}).status_code == 404


async def test_a_checkpoint_needs_a_workspace_to_hold(make_ctx):
    """A run that has published no files has no file set to keep: the answer says so, in plain words."""
    ctx, _ = make_ctx()
    with pytest.raises(workspace_manager.WorkspaceError) as exc:
        await workspace_manager.checkpoint(ctx, label="empty")
    assert exc.value.status == 409 and "no workspace files" in exc.value.message


# --------------------------------------------------------------------------- conflict detection

def test_a_plan_measured_on_an_old_version_is_refused_before_it_writes(built):
    client, h, ws, rid = built
    body = {"changes": [{"file": "styles.css", "op": "append", "text": MARKER}], "base_version": 1}
    assert client.post(f"{ws}/plan", headers=h, json=body).status_code == 200

    patch(client, h, ws, OTHER)                             # another tab lands a change: now v2
    res = client.post(f"{ws}/plan", headers=h, json=body)
    assert res.status_code == 409
    assert "Conflict" in res.json()["detail"] and "v1" in res.json()["detail"] and "v2" in res.json()["detail"]
    assert OTHER in client.get(f"/api/runs/{rid}/files/styles.css", headers=h).text
    assert MARKER not in client.get(f"/api/runs/{rid}/files/styles.css", headers=h).text


def test_applying_over_a_newer_change_is_blocked(built):
    client, h, ws, rid = built
    stale = {"changes": [{"file": "styles.css", "op": "append", "text": OTHER}], "base_version": 1}
    patch(client, h, ws, MARKER)                            # v2 exists
    res = client.post(f"{ws}/apply", headers=h, json=stale)
    assert res.status_code == 409 and "Conflict" in res.json()["detail"]
    css = client.get(f"/api/runs/{rid}/files/styles.css", headers=h).text
    assert MARKER in css and OTHER not in css


def test_a_restore_onto_a_workspace_that_moved_is_refused(built):
    client, h, ws, rid = built
    patch(client, h, ws, MARKER)
    patch(client, h, ws, OTHER)
    assert client.post(f"{ws}/restore", headers=h, json={"w": 1, "base_version": 1}).status_code == 409
    assert client.post(f"{ws}/restore", headers=h, json={"w": 1}).status_code == 202


def test_a_step_planned_on_a_stale_view_is_refused(built):
    client, h, ws, rid = built
    chat(client, h, rid)
    assert client.post(f"{ws}/undo", headers=h, json={"base_version": 1}).status_code == 409
    assert client.post(f"{ws}/undo", headers=h, json={"base_version": 2}).status_code == 202


def test_the_plan_hands_back_the_version_to_apply_against(built):
    """The view cannot send a base version it never read, so the plan is where it comes from."""
    client, h, ws, rid = built
    changes = [{"file": "styles.css", "op": "append", "text": MARKER}]
    plan = client.post(f"{ws}/plan", headers=h, json={"changes": changes}).json()
    assert plan["base_version"] == 1
    assert client.post(f"{ws}/apply", headers=h,
                       json={"changes": changes, "base_version": plan["base_version"]}).status_code == 202


async def test_check_base_names_both_versions(make_ctx):
    ctx, _ = make_ctx()
    ctx.state.html_version = 5
    ctx.state.workspace_versions = []
    with pytest.raises(workspace_manager.WorkspaceError) as exc:
        workspace_manager.check_base(ctx.state, 3)
    assert exc.value.status == 409
    assert "v3" in exc.value.message and "v5" in exc.value.message
    workspace_manager.check_base(ctx.state, None)          # a client that sends nothing is not blocked
    workspace_manager.check_base(ctx.state, 5)


# --------------------------------------------------------------------------- diff views

def test_the_snapshot_diff_carries_both_readings_of_one_change(built):
    client, h, ws, rid = built
    patch(client, h, ws, MARKER)
    data = client.get(f"{ws}/diff?w=1", headers=h).json()

    css = next(f for f in data["files"] if f["file"] == "styles.css")
    assert css["added"] == 1 and css["removed"] == 0
    assert css["rows"][-1]["kind"] == "add"
    side = [r for r in css["side"] if r["kind"] == "add"][-1]
    assert side["r"]["text"] == MARKER and side["l"] is None
    assert css["left_lines"] < css["right_lines"]


def test_two_snapshots_diff_against_each_other_not_only_live(built):
    client, h, ws, rid = built
    patch(client, h, ws, MARKER)
    patch(client, h, ws, OTHER)
    data = client.get(f"{ws}/diff?w=1&to=2", headers=h).json()
    assert data["to"] == "w2" and data["from"]["w"] == 1

    added = [r["r"]["text"] for f in data["files"] for r in f["side"] if r["kind"] == "add" and r["r"]]
    assert MARKER in added and OTHER not in added


def test_the_page_level_diff_reads_the_same_change_both_ways(built):
    client, h, ws, rid = built
    chat(client, h, rid)
    data = client.get(f"/api/runs/{rid}/diff?from=1&to=2", headers=h).json()
    assert {"rows", "side", "added", "removed", "left_lines", "right_lines", "truncated"} <= set(data)
    assert data["changed"] is True and data["added"] > 0
    expected = differ.compare(raw(client, h, rid, 1), raw(client, h, rid, 2), "v1", "v2")
    assert data["rows"] == expected["rows"] and data["side"] == expected["side"]
    assert (data["added"], data["removed"]) == (expected["added"], expected["removed"])
    assert (data["left_lines"], data["right_lines"]) == (expected["left_lines"], expected["right_lines"])


# --------------------------------------------------------------------------- change classification

def test_files_that_move_are_renamed_not_deleted_then_added():
    texts = {"index.html": "<html>a</html>", "styles.css": "a{}", "app.js": "console.log(1)"}
    moved = {"index.html": "<html>a</html>", "theme.css": "a{}", "app.js": "console.log(2)"}
    report = workspace_manager.stats(texts, moved)

    assert {r["file"]: r["status"] for r in report["files"]} == {
        "index.html": "unchanged", "app.js": "changed", "theme.css": "renamed"}
    assert report["renamed"] == [{"from": "styles.css", "to": "theme.css"}]
    assert report["removed"] == [] and report["added"] == [] and report["changed"] == ["app.js"]


def test_a_rename_is_only_claimed_when_the_bytes_are_identical():
    report = workspace_manager.stats({"a.css": "one\n"}, {"b.css": "two\n", "c.css": "one\n"})
    assert report["renamed"] == [{"from": "a.css", "to": "c.css"}]
    assert [r["status"] for r in report["files"]] == ["added", "renamed"]


def test_a_deleted_file_still_reads_as_deleted_when_nothing_matches_it():
    report = workspace_manager.stats({"a.css": "one\n", "b.js": "two\n"}, {"a.css": "one\n"})
    assert report["removed"] == ["b.js"]
    assert report["renamed"] == []


def test_the_line_counts_of_a_change_set_are_the_ones_the_page_shows(built):
    client, h, ws, rid = built
    res = client.post(f"{ws}/plan", headers=h,
                      json={"changes": [{"file": "app.js", "op": "append", "text": "console.log(1);"}]}).json()
    row = next(r for r in res["projection"]["files"] if r["file"] == "app.js")
    assert row["status"] == "changed" and row["lines_added"] == 1 and row["lines_removed"] == 0
    assert res["projection"]["added"] == [] and res["projection"]["removed"] == []


# --------------------------------------------------------------------------- side-by-side alignment

def test_side_by_side_pairs_a_replaced_line_and_marks_both_sides():
    out = differ.align("<p>old</p>", "<p>new</p>")
    assert [r["kind"] for r in out["rows"]] == ["chg"]
    row = out["rows"][0]
    assert row["l"] == {"n": 1, "text": "<p>old</p>"} and row["r"] == {"n": 1, "text": "<p>new</p>"}
    assert (out["added"], out["removed"]) == (1, 1)


def test_an_insert_and_a_delete_keep_their_line_numbers_on_one_side():
    out = differ.align("a\nb\nc", "a\nb\nc\nd")
    assert out["rows"][-1] == {"kind": "add", "l": None, "r": {"n": 4, "text": "d"}}
    assert out["added"] == 1 and out["removed"] == 0

    gone = differ.align("a\nb\nc", "a\nc")
    assert gone["rows"][1] == {"kind": "del", "l": {"n": 2, "text": "b"}, "r": None}
    assert gone["added"] == 0 and gone["removed"] == 1


def test_a_shorter_replacement_block_pads_the_side_with_more_lines():
    out = differ.align("a\nx\ny\nb", "a\nz\nb")
    kinds = [r["kind"] for r in out["rows"]]
    assert kinds == ["ctx", "chg", "del", "ctx"]


def test_long_unchanged_runs_fold_into_gap_rows_with_their_line_count():
    old = "\n".join(f"<i>{n}</i>" for n in range(40))
    assert differ.align(old, old)["rows"] == []            # identical files say nothing twice
    changed = old.replace("<i>30</i>", "<i>30!</i>")
    out = differ.align(old, changed)
    gaps = [r for r in out["rows"] if r["kind"] == "gap"]
    assert len(gaps) == 2 and sum(g["lines"] for g in gaps) == 27
    # each of the two unchanged runs keeps three lines either side: 6 visible in the 30-line run, 6 in the 9
    assert len([r for r in out["rows"] if r["kind"] == "ctx"]) == 12
    assert out["changed"] is True


def test_the_unified_and_aligned_views_agree_on_the_totals():
    a = "<section><h1>T</h1><p>one</p></section>"
    b = "<section><h1>T</h1><p>two</p><p>three</p></section>"
    unified, side = differ.diff(a, b, "a", "b"), differ.align(a, b)
    assert unified["added"] == side["added"] == 2
    assert unified["removed"] == side["removed"] == 1


# --------------------------------------------------------------------------- attribution + reporting

def test_history_says_which_agent_moved_the_workspace(built):
    client, h, ws, rid = built
    chat(client, h, rid, "Rewrite the headline")
    cause = state(client, h, rid)["workspace_versions"][-1]["cause"]
    assert cause["kind"] == "crew rebuild" and cause["agent"] and cause["run_id"] == rid


def test_the_undo_window_is_reported_rather_than_guessed(built):
    client, h, ws, rid = built
    patch(client, h, ws, MARKER)
    patch(client, h, ws, OTHER)
    undo = client.get(f"{ws}/versions", headers=h).json()["undo"]
    assert undo == {"can_undo": True, "can_redo": False, "undo_steps": 2, "redo_steps": 0,
                    "next_undo": 2, "next_redo": None}

    client.post(f"{ws}/undo", headers=h, json={})
    undo = client.get(f"{ws}/versions", headers=h).json()["undo"]
    assert undo["undo_steps"] == 1 and undo["redo_steps"] == 1
    assert undo["next_undo"] == 1 and undo["next_redo"] == 3


async def test_an_unknown_cause_is_recorded_as_unattributed_not_rounded_up(make_ctx):
    """History that guesses is worse than history that admits it does not know."""
    ctx, _ = make_ctx()
    key = await ctx.storage.save(ctx.run_id, "index.html", b"<html><body>one</body></html>")
    ctx.state.files = [{"name": "index.html", "key": key, "bytes": 30, "language": "html", "note": ""}]
    snap = await workspace_manager.capture(ctx, cause={"kind": "teleport", "agent": ""})
    assert snap["cause"] == {"kind": "unattributed"}


async def test_a_checkpoint_never_gates_the_edit_it_records(make_ctx, monkeypatch):
    """Storage that refuses is reported in the trace; the crew's change still goes ahead."""
    ctx, events = make_ctx()

    async def boom(*args, **kwargs):
        raise RuntimeError("gridfs is down")

    key = await ctx.storage.save(ctx.run_id, "index.html", b"<html><body>one</body></html>")
    ctx.state.files = [{"name": "index.html", "key": key, "bytes": 30, "language": "html", "note": ""}]
    monkeypatch.setattr(ctx.storage, "load", boom)

    from app.orchestrator.graph import Orchestrator   # noqa: PLC0415 - the helper is what is under test
    orch = Orchestrator(ctx)
    assert await orch._checkpoint_workspace(kind="crew rebuild", note="before") is None
    assert any(t == "agent_message" and "No checkpoint taken" in d.get("message", "")
               for t, d in events)
    assert ctx.state.undo_stack == []             # and nothing claims to be undoable that never was
