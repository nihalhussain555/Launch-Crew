"""The IDE's backend: reading and writing workspace files, searching them, and the honest run status.

Nothing in here talks to a model, so none of these requests spend tokens or rebuild the page. What they
do prove is the part the editor depends on: a save lands in the real workspace and survives a crew
rebuild, a page-owned name cannot be written around the sanitizer, a save that races another writer is
refused, and a Run button that has no sandbox says so instead of printing something invented.
"""
import pytest
from fastapi.testclient import TestClient

from app.api import routes_auth, routes_workspace
from app.main import app
from app.tools import browser_checks

SOURCE = {"name": "notes.md", "text": "# Field notes\n\nThe checkout copy needs a second line.\n"}
CSS = {"name": "extras.css", "text": ".editor-only {\n  outline: 2px dashed #111;\n}\n"}


@pytest.fixture
def client(monkeypatch):
    async def fake(html):
        return [{"id": "overflow", "label": "x", "viewport": "mobile", "passed": True,
                 "severity": "error", "detail": ""}], {"desktop": b"d", "mobile": b"m"}
    monkeypatch.setattr(browser_checks, "run_checks", fake)
    routes_auth._auth_limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    routes_auth._auth_limiter._hits.clear()


@pytest.fixture
def built(client):
    """A logged-in user whose run is sitting at the approval gate with a published workspace."""
    r = client.post("/api/auth/register", json={"email": "ide@example.com", "password": "supersecret1",
                                                "name": "IDE"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pid = client.post("/api/projects", json={"idea": "A tiny CRM for solo founders"}, headers=h).json()["id"]
    rid = client.post(f"/api/projects/{pid}/runs", headers=h).json()["id"]
    return client, h, f"/api/runs/{rid}/workspace", rid


def state(client, h, rid):
    return client.get(f"/api/runs/{rid}", headers=h).json()["state"]


def described(client, h, ws, name):
    row = next((f for f in client.get(ws, headers=h).json()["files"] if f["name"] == name), None)
    assert row, f"{name} is not listed by GET /workspace"
    return row


# --------------------------------------------------------------------------- opening a file

def test_a_file_opens_with_the_identity_a_save_has_to_send_back(built):
    client, h, ws, rid = built
    res = client.get(f"{ws}/files/index.html", headers=h)
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "page" and body["save_via"] == "apply" and body["editable"] is True
    assert body["text"] == client.get(f"/api/runs/{rid}/html", headers=h).text
    assert len(body["hash"]) == 12 and body["bytes"] == len(body["text"].encode())
    assert "key" not in res.text                                      # storage keys stay server-side
    assert client.get(f"{ws}/files/nope.css", headers=h).status_code == 404
    # a name with a path separator in it cannot reach a route at all: the workspace is a flat set of bare names
    assert client.get(f"{ws}/files/..%2Findex.html", headers=h).status_code == 404
    assert client.get(f"{ws}/files/.env", headers=h).status_code == 422


def test_the_listing_says_who_owns_each_file(built):
    client, h, ws, rid = built
    files = client.get(ws, headers=h).json()["files"]
    assert [f["name"] for f in files] == ["index.html", "styles.css", "app.js", "README.md"]
    by_name = {f["name"]: f for f in files}
    assert by_name["index.html"]["kind"] == "page"
    assert by_name["styles.css"]["kind"] == "derived" and by_name["styles.css"]["save_via"] == "apply"
    # README.md is rebuilt from the page on every publish, so the editor must not offer to save it.
    assert by_name["README.md"]["kind"] == "generated" and by_name["README.md"]["editable"] is False
    assert "next publish" in by_name["README.md"]["why"]
    assert client.get(ws, headers=h).json()["limits"]["max_file_bytes"] == 200_000


# --------------------------------------------------------------------------- writing source files

def test_creating_saving_renaming_and_deleting_moves_the_real_workspace(built):
    client, h, ws, rid = built

    created = client.post(f"{ws}/files", headers=h, json=SOURCE)
    assert created.status_code == 200, created.text
    made = created.json()
    assert made["file"]["name"] == "notes.md" and made["snapshot"] == 1 and made["undo"]["can_undo"] is True
    assert described(client, h, ws, "notes.md")["kind"] == "source"
    assert client.get(f"/api/runs/{rid}/files/notes.md", headers=h).text == SOURCE["text"]

    # A create is not an edit of the page: no version was spent and nothing was rebuilt.
    s = state(client, h, rid)
    assert s["html_version"] == 1 and s["revisions"] == 0
    assert s["workspace_versions"][0]["cause"]["kind"] == "file create"

    current = client.get(f"{ws}/files/notes.md", headers=h).json()
    saved = client.put(f"{ws}/files/notes.md", headers=h,
                       json={"text": SOURCE["text"] + "\nSecond line from the editor.\n",
                             "base_hash": current["hash"], "note": "added the second line"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["snapshot"] == 2
    assert "Second line" in client.get(f"/api/runs/{rid}/files/notes.md", headers=h).text

    renamed = client.patch(f"{ws}/files/notes.md", headers=h, json={"name": "handoff.md"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["to"] == "handoff.md"
    assert client.get(f"/api/runs/{rid}/files/notes.md", headers=h).status_code == 404
    assert "Second line" in client.get(f"/api/runs/{rid}/files/handoff.md", headers=h).text

    deleted = client.delete(f"{ws}/files/handoff.md", headers=h)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] == "handoff.md"
    assert described(client, h, ws, "index.html")  # the page was never involved in any of this
    assert client.get(f"/api/runs/{rid}/files/handoff.md", headers=h).status_code == 404
    assert state(client, h, rid)["html_version"] == 1


def test_every_file_operation_leaves_the_state_it_found_behind(built):
    client, h, ws, rid = built
    page = client.get(f"/api/runs/{rid}/html", headers=h).text
    client.post(f"{ws}/files", headers=h, json=CSS)
    s = state(client, h, rid)
    assert [v["w"] for v in s["workspace_versions"]] == [1]
    assert {f["name"] for f in s["workspace_versions"][0]["files"]} == {
        "index.html", "styles.css", "app.js", "README.md"}     # captured before the new file existed
    assert s["undo_stack"] == [1]
    assert page == client.get(f"/api/runs/{rid}/html", headers=h).text


def test_an_editor_file_survives_a_crew_rebuild_and_a_snapshot_restore(built):
    """`publish` rebuilds the file list from the page, so authored source has to ride with it."""
    client, h, ws, rid = built
    client.post(f"{ws}/files", headers=h, json=SOURCE)
    assert client.post(f"/api/runs/{rid}/chat", headers=h,
                       json={"text": "Make the button bigger"}).status_code == 202
    assert state(client, h, rid)["html_version"] == 2
    assert described(client, h, ws, "notes.md")["kind"] == "source"
    assert client.get(f"/api/runs/{rid}/files/notes.md", headers=h).text == SOURCE["text"]

    # ... and a workspace restore puts it back as the snapshot that preceded the rebuild held it.
    assert client.post(f"{ws}/restore", headers=h, json={"w": 2}).status_code == 202
    assert client.get(f"/api/runs/{rid}/files/notes.md", headers=h).text == SOURCE["text"]


def test_a_save_that_races_another_writer_is_refused(built):
    client, h, ws, rid = built
    client.post(f"{ws}/files", headers=h, json=SOURCE)
    opened = client.get(f"{ws}/files/notes.md", headers=h).json()["hash"]
    client.put(f"{ws}/files/notes.md", headers=h, json={"text": SOURCE["text"] + "Another edit.\n",
                                                        "base_hash": opened})
    res = client.put(f"{ws}/files/notes.md", headers=h, json={"text": "Stale view of the file.\n",
                                                              "base_hash": opened})
    assert res.status_code == 409 and "Conflict" in res.json()["detail"]
    assert "Another edit" in client.get(f"/api/runs/{rid}/files/notes.md", headers=h).text
    assert state(client, h, rid)["html_version"] == 1


def test_the_page_and_its_derived_names_cannot_be_written_past_the_sanitizer(built):
    client, h, ws, rid = built
    for name in ("index.html", "styles.css", "app.js", "README.md"):
        res = client.put(f"{ws}/files/{name}", headers=h, json={"text": "body { color: red }\n"})
        assert res.status_code == 409, (name, res.text)
        assert "op 'set'" in res.json()["detail"]
    # creating over a name the page owns is the same refusal, in the same terms
    for name in ("index.html", "styles.css", "README.md"):
        res = client.post(f"{ws}/files", headers=h, json={"name": name, "text": ".late { color: red }\n"})
        assert res.status_code == 409, (name, res.text)
        assert "op 'set'" in res.json()["detail"]
    for name in ("index.html", "styles.css", "app.js", "README.md"):
        assert client.delete(f"{ws}/files/{name}", headers=h).status_code == 409
    assert [f["name"] for f in state(client, h, rid)["files"]] == ["index.html", "styles.css", "app.js",
                                                                   "README.md"]


def test_unsafe_names_are_refused_before_anything_is_written(built):
    client, h, ws, rid = built
    for bad in ("../server.py", "nested/dir/notes.md", ".env", "notes.exe", "photo.png", "notes md.md",
                "a", "x" * 70):
        res = client.post(f"{ws}/files", headers=h, json={"name": bad, "text": SOURCE["text"]})
        assert res.status_code == 422, (bad, res.text)
    assert client.post(f"{ws}/files", headers=h, json={"name": "notes.md", "text": "tiny"}).status_code == 422
    assert state(client, h, rid)["authored_files"] == []
    assert [f["name"] for f in state(client, h, rid)["files"]] == ["index.html", "styles.css", "app.js",
                                                                   "README.md"]


def test_a_duplicate_name_and_a_duplicate_rename_target_are_both_refused(built):
    client, h, ws, rid = built
    client.post(f"{ws}/files", headers=h, json=SOURCE)
    client.post(f"{ws}/files", headers=h, json=CSS)
    again = client.post(f"{ws}/files", headers=h, json=SOURCE)
    assert again.status_code == 409 and "already exists" in again.json()["detail"]
    clash = client.patch(f"{ws}/files/notes.md", headers=h, json={"name": "extras.css"})
    assert clash.status_code == 409 and "already exists" in clash.json()["detail"]
    same = client.patch(f"{ws}/files/notes.md", headers=h, json={"name": "notes.md"})
    assert same.status_code == 422 and "already has" in same.json()["detail"]
    assert {f["name"] for f in state(client, h, rid)["authored_files"]} == {"notes.md", "extras.css"}


def test_file_writes_wait_for_the_crew(built, monkeypatch):
    """The guard is the run status: while a pipeline owns the state, no editor write is accepted."""
    client, h, ws, rid = built
    monkeypatch.setattr(routes_workspace, "BUSY", {"awaiting_approval"})
    for call in (lambda: client.post(f"{ws}/files", headers=h, json=SOURCE),
                 lambda: client.put(f"{ws}/files/notes.md", headers=h, json={"text": SOURCE["text"]}),
                 lambda: client.delete(f"{ws}/files/notes.md", headers=h),
                 lambda: client.patch(f"{ws}/files/notes.md", headers=h, json={"name": "other.md"})):
        res = call()
        assert res.status_code == 409 and "The crew is awaiting_approval" in res.json()["detail"]
    assert state(client, h, rid)["authored_files"] == []


# --------------------------------------------------------------------------- searching

def test_search_reads_the_stored_files_and_reports_its_own_bounds(built):
    client, h, ws, rid = built
    client.post(f"{ws}/files", headers=h, json=SOURCE)
    out = client.get(f"{ws}/search", headers=h, params={"q": "checkout"}).json()
    assert out["query"] == "checkout" and out["scope"] == "all files"
    assert [m["file"] for m in out["matches"]] == ["notes.md"]
    assert out["matches"][0]["line"] == 3 and out["matches"][0]["column"] >= 1
    assert out["truncated"] is False and out["reason"] == ""
    assert out["counts"] == {"matches": 1, "files": 1, "scanned": 5}
    assert out["limits"]["max_matches"] == 200

    scoped = client.get(f"{ws}/search", headers=h, params={"q": "checkout", "file": "notes.md"}).json()
    assert scoped["scope"] == "notes.md" and scoped["counts"]["scanned"] == 1

    css = client.get(f"{ws}/search", headers=h, params={"q": "background-color", "file": "styles.css"}).json()
    assert css["files"] == [] and css["counts"]["matches"] == 0


def test_search_takes_regex_and_case_and_refuses_a_pattern_that_does_not_compile(built):
    client, h, ws, _ = built
    hits = client.get(f"{ws}/search", headers=h, params={"q": r"<(h1|h2)\b", "regex": "true"}).json()
    assert hits["regex"] is True and hits["counts"]["matches"] >= 1
    strict = client.get(f"{ws}/search", headers=h, params={"q": "HTML", "case": "true"}).json()
    loose = client.get(f"{ws}/search", headers=h, params={"q": "HTML"}).json()
    assert loose["counts"]["matches"] >= strict["counts"]["matches"]
    bad = client.get(f"{ws}/search", headers=h, params={"q": "(unclosed", "regex": "true"})
    assert bad.status_code == 422 and "does not compile" in bad.json()["detail"]
    assert client.get(f"{ws}/search", headers=h, params={"q": " "}).status_code == 422
    assert client.get(f"{ws}/search", headers=h, params={"q": "x" * 201}).status_code == 422
    assert client.get(f"{ws}/search", headers=h, params={"q": "hero", "file": "missing.css"}).status_code == 404


# --------------------------------------------------------------------------- running the project

def test_run_reports_that_it_needs_a_sandbox_instead_of_inventing_output(built):
    client, h, ws, _ = built
    res = client.get(f"{ws}/exec", headers=h)
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False and body["runtime"] == "" and body["runtime_found"] is False
    assert "not implemented" in body["reason"]
    assert any("container" in line or "sandbox" in line for line in body["missing"])
    assert any("preview" in line.lower() for line in body["safe_alternatives"])
    assert "SANDBOX_RUNTIME" in body["configuration"]

    refused = client.post(f"{ws}/exec", headers=h, json={"file": "notes.md", "args": "--watch"})
    assert refused.status_code == 501 and "cannot run project code" in refused.json()["detail"]
    assert client.post(f"{ws}/exec", headers=h, json={"file": "../etc/passwd"}).status_code == 422


# --------------------------------------------------------------------------- who may reach these routes

def test_another_user_and_no_token_get_nothing_at_all(built):
    client, h, ws, rid = built
    r = client.post("/api/auth/register", json={"email": "nosy2@example.com", "password": "supersecret1",
                                                "name": "N"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for path, call in (("", lambda hh: client.get(ws, headers=hh)),
                       ("/files/index.html", lambda hh: client.get(f"{ws}/files/index.html", headers=hh)),
                       ("/search?q=hero", lambda hh: client.get(f"{ws}/search", headers=hh, params={"q": "hero"})),
                       ("/exec", lambda hh: client.get(f"{ws}/exec", headers=hh))):
        assert call(other).status_code == 404, path
    assert client.post(f"{ws}/files", json=SOURCE).status_code == 401
    assert client.put(f"{ws}/files/notes.md", json={"text": SOURCE["text"]}).status_code == 401
    assert client.delete(f"{ws}/files/notes.md").status_code == 401
    assert client.post(f"{ws}/exec", json={"file": "notes.md"}).status_code == 401

    # the new routes are run-scoped like the rest: a malformed id is a 404, not a crash
    assert client.get("/api/runs/not-an-id/workspace/files/index.html", headers=h).status_code == 404
    assert client.get(f"{ws}/files/index.html", headers=h).status_code == 200
    assert state(client, h, rid)["html_version"] == 1
