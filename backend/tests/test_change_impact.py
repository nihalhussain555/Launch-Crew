"""Impact analysis: what a proposed change touches, and what it would leave broken.

The workspace here mirrors how a real build looks: `styles.css` and `app.js` are the page's
embedded blocks copied out, so every name inside them exists in two places.
"""
from app.services import change_impact as ch
from app.services.codebase_index import build_index

from tests.test_codebase_index import MD, PAGE, PY

STYLES = """#hero-title { color: var(--primary) }
.skip-link { position: absolute }
.btn.primary:hover { filter: brightness(.97) }
#lc-main { max-width: 900px }
"""
APP_JS = """function wireUp() {
  document.getElementById('signup').addEventListener('submit', (e) => e.preventDefault());
  document.querySelectorAll('.btn').forEach((b) => b.classList.toggle('armed'));
  document.querySelector('#hero-title').textContent = 'Hi';
}
wireUp();
"""


def workspace_index(version=3):
    return build_index([
        {"name": "index.html", "language": "html", "text": PAGE},
        {"name": "styles.css", "language": "css", "text": STYLES},
        {"name": "app.js", "language": "js", "text": APP_JS},
        {"name": "README.md", "language": "md", "text": MD},
        {"name": "tests/test_page.py", "language": "py", "text": PY},
    ], version=version)


def risk_ids(report):
    return [r["id"] for r in report["risks"]]


def target(report, name):
    return next((t for t in report["targets"] if t["name"] == name), None)


def files_in_scope(report):
    return {f["file"] for f in report["related_files"]}


def risk(report, id_):
    return next(r for r in report["risks"] if r["id"] == id_)


def test_a_named_symbol_becomes_a_target_with_its_sites():
    r = ch.analyze(workspace_index(), "make the signup form wider")
    t = target(r, "signup")
    assert t and t["kind"] == "id" and t["op"] == "modify" and t["found"]
    assert {d["file"] for d in t["declared"]} == {"index.html"}
    assert {r_["file"] for r_ in t["referenced"]} == {"index.html", "app.js"}
    assert files_in_scope(r) == {"index.html", "app.js"}
    assert r["scope"] == "multi-file"          # the page and its derived script both hold the name


def test_a_name_in_the_page_and_its_derived_asset_is_paired():
    r = ch.analyze(workspace_index(), "brighten the hero-title colour")
    paired = risk(r, "paired-copy")
    assert paired["severity"] == "error"
    assert set(paired["files"]) == {"index.html", "app.js", "styles.css"}
    assert "rebuilt from that block" in paired["message"]


def test_rename_that_leaves_references_behind_is_an_error():
    r = ch.analyze(workspace_index(), "rename #lc-main to shell")
    t = target(r, "lc-main")
    assert t["op"] == "rename" and t["rename_to"] == "shell"
    orphan = risk(r, "orphaned-reference")
    assert orphan["severity"] == "error" and "index.html" in orphan["files"]
    assert "styles.css" in orphan["files"]
    assert "leaves 2 reference(s) pointing at nothing" in orphan["message"]
    assert r["counts"]["errors"] >= 2


def test_removing_the_jump_target_breaks_the_skip_link():
    r = ch.analyze(workspace_index(), "remove #lc-main")
    ids = risk_ids(r)
    assert "anchor-target" in ids and "orphaned-reference" in ids
    assert target(r, "lc-main")["op"] == "remove"
    assert "skip link" in risk(r, "anchor-target")["message"]


def test_editing_a_derived_asset_alone_is_caught():
    r = ch.analyze(workspace_index(), "move the padding rule into styles.css")
    canonical = risk(r, "canonical-source")
    assert "index.html" in canonical["files"] and "styles.css" in canonical["files"]
    assert canonical["severity"] == "error"
    assert {"index.html", "styles.css"} <= files_in_scope(r)


def test_unknown_file_and_unknown_name_are_reported_distinctly():
    x = workspace_index()
    r = ch.analyze(x, "add vendor.js to the page")
    assert "unknown-file" in risk_ids(r)
    assert target(r, "vendor.js")["found"] is False
    assert "index.html" in risk(r, "unknown-file")["message"]
    r2 = ch.analyze(x, "style the 'pricing-table' block")
    assert "unknown-name" in risk_ids(r2)
    assert target(r2, "pricing-table")["kind"] == "name"


def test_a_request_that_names_nothing_stays_honest():
    r = ch.analyze(workspace_index(), "make it feel calmer")
    assert r["targets"] == [] and r["related_files"] == [] and r["scope"] == "workspace-wide"
    assert risk_ids(r) == ["no-named-target"]


def test_an_endpoint_is_outside_the_workspace():
    x = build_index([{"name": "app.js", "language": "js",
                      "text": "fetch('/api/keep').catch(() => {});\nimport helpers from './helpers.js';\n"}])
    r = ch.analyze(x, "point fetch /api/keep at the new endpoint")
    ids = risk_ids(r)
    assert "outside-workspace" in ids
    assert target(r, "/api/keep")["kind"] == "endpoint"


def test_stale_index_is_flagged_first():
    r = ch.analyze(workspace_index(version=2), "widen #signup", version=4)
    assert r["risks"][0]["id"] == "stale-index"
    assert "v2" in r["risks"][0]["message"] and "v4" in r["risks"][0]["message"]


def test_prompt_block_is_compact_and_carries_the_plan():
    r = ch.analyze(workspace_index(), "rename #hero-title to page-title")
    block = r["block"]
    assert len(block) <= ch.BLOCK_CHARS + 12
    assert block.startswith("IMPACT REPORT for v3")
    assert "page-title" in block and "RISK ERROR" in block and "RULES:" in block
    assert "index.html" in block
    head = ch.headline(r)
    assert head.startswith(f"{r['scope']} change: ")
    assert f"{r['counts']['targets']} name(s)" in head and "error(s)" in head


def test_reports_are_deterministic_apart_from_their_timestamp():
    x = workspace_index()
    a, b = ch.analyze(x, "widen #signup"), ch.analyze(x, "widen #signup")
    assert {k: v for k, v in a.items() if k != "at"} == {k: v for k, v in b.items() if k != "at"}


def test_empty_or_broken_index_never_raises():
    for x in (None, {}, {"files": [], "symbols": None, "refs": None}):
        r = ch.analyze(x, "widen #signup")
        assert r["scope"] and r["block"] and r["must"]
    e = ch.empty("widen #signup", version=1, reason="no files yet")
    assert e["targets"] == [] and e["risks"][0]["id"] == "no-index"
