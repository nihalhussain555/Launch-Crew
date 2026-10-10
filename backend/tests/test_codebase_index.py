"""The workspace index: what each file declares, what it reaches for, and the bounds it obeys."""
import pytest

from app.services import codebase_index as ci

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Night-shift habit tracker</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<a class="skip-link" href="#lc-main">Skip to content</a>
<main id="lc-main" class="page">
  <h1 id="hero-title">Track habits on your own shift</h1>
  <p class="lede">Built for night workers.</p>
  <form id="signup" action="">
    <label for="email">Email</label>
    <input id="email" name="email_address" type="email">
    <button class="btn primary" type="submit">Join</button>
  </form>
</main>
<style>
:root { --primary: #0e7490; --bg: #f6f9fc; }
.skip-link { position: absolute; }
.btn.primary:hover { filter: brightness(.97) }
#hero-title { color: var(--primary); background: url("bg.png") }
@media (max-width: 640px) { .lede { font-size: 15px } }
</style>
<script>
const root = document.documentElement;
function wireUp() {
  const form = document.getElementById('signup');
  form.addEventListener('submit', (e) => e.preventDefault());
  document.querySelectorAll('.btn').forEach((b) => b.classList.toggle('armed'));
  document.querySelector('#hero-title').textContent = 'Hi';
}
wireUp();
</script>
<script src="app.js"></script>
</body>
</html>
"""

CSS = ':root { --accent: #14b8a6 }\n.card { padding: 12px; color: var(--accent) }\n#lc-main { max-width: 900px }\n'
JS = "const theme = getComputedStyle(document.documentElement);\n" \
     "document.getElementsByClassName('btn').item(0).hidden = true;\n" \
     "import helpers from './helpers.js';\n" \
     "fetch('/api/keep').catch(() => {});\n"
MD = "# Handoff\n\nEdit `styles.css` and reopen `index.html`.\n"
PY = "import re\nfrom pathlib import Path\n\n\ndef check_page(html):\n    return Path(html).exists()\n\n\nclass Probe:\n    pass\n"


def index():
    return ci.build_index([
        {"name": "index.html", "language": "html", "text": PAGE},
        {"name": "styles.css", "language": "css", "text": CSS},
        {"name": "app.js", "language": "js", "text": JS},
        {"name": "README.md", "language": "md", "text": MD},
        {"name": "tests/test_page.py", "language": "py", "text": PY},
    ], version=3)


def names(symbols, kind):
    return {s["name"] for s in symbols if s["kind"] == kind}


def targets(refs, kind):
    return {r["to"] for r in refs if r["kind"] == kind}


def test_declared_symbols_are_found_per_language():
    x = index()
    assert names(x["symbols"], "id") >= {"lc-main", "hero-title", "signup", "email"}
    assert names(x["symbols"], "class") >= {"skip-link", "page", "btn", "primary", "lede"}
    assert names(x["symbols"], "field") == {"email_address"}
    assert names(x["symbols"], "var") == {"primary", "bg", "accent"}
    assert "Track habits on your own shift" in names(x["symbols"], "heading")
    assert names(x["symbols"], "fn") >= {"wireUp", "check_page"}
    assert names(x["symbols"], "type") == {"Probe"}
    assert names(x["symbols"], "const") >= {"root", "theme"}


def test_references_link_files_together():
    x = index()
    refs = x["refs"]
    assert targets([r for r in refs if r["from"] == "index.html"], "anchor") == {"lc-main"}
    assert targets([r for r in refs if r["from"] == "index.html" and r["kind"] == "file"], "file") == {"styles.css", "app.js"}
    assert targets([r for r in refs if r["from"] == "index.html" and r["where"] == "style"], "css-id") == {"hero-title"}
    assert targets([r for r in refs if r["from"] == "index.html" and r["where"] == "style"], "css-class") >= {"skip-link", "btn", "primary", "lede"}
    assert targets([r for r in refs if r["from"] == "index.html" and r["where"] == "script"], "dom-id") == {"signup", "hero-title"}
    assert targets([r for r in refs if r["from"] == "index.html" and r["where"] == "script"], "dom-class") == {"btn", "armed"}
    assert targets([r for r in refs if r["from"] == "styles.css"], "css-id") == {"lc-main"}
    assert targets([r for r in refs if r["from"] == "styles.css"], "css-var") == {"accent"}
    assert targets([r for r in refs if r["from"] == "app.js"], "import") == {"./helpers.js"}
    assert targets([r for r in refs if r["from"] == "app.js"], "request") == {"/api/keep"}
    assert targets([r for r in refs if r["from"] == "README.md"], "mention") == {"styles.css", "index.html"}
    assert targets([r for r in refs if r["from"] == "tests/test_page.py"], "import") == {"re", "pathlib"}


def test_embedded_blocks_are_tagged_separately_from_markup():
    x = index()
    hero = [s for s in x["symbols"] if s["name"] == "hero-title"]
    assert {s["where"] for s in hero} == {"markup"}          # declared once, in the page's markup
    assert {r["where"] for r in x["refs"] if r["to"] == "hero-title"} == {"style", "script"}
    assert all(s["where"] == "source" for s in x["symbols"] if s["file"] == "styles.css")
    assert any(s["line"] > 1 for s in x["symbols"] if s["file"] == "index.html")


def test_index_carries_version_counts_and_helpers():
    x = index()
    assert x["version"] == 3 and x["at"]
    assert x["counts"]["files"] == 5 and x["counts"]["indexed"] == 5
    assert x["counts"]["by_kind"]["ref:css-class"] >= 4
    assert ci.files_of(x) == ["index.html", "styles.css", "app.js", "README.md", "tests/test_page.py"]
    assert {d["file"] for d in ci.declarations(x, "btn")} == {"index.html"}
    assert {r["from"] for r in ci.references(x, "hero-title")} == {"index.html"}
    assert ci.snippet(PAGE, 1) == "<!DOCTYPE html>"
    assert ci.snippet(PAGE, 0) == ""
    assert not x["truncated"]


def test_oversized_and_unknown_files_are_reported_instead_of_parsed():
    big = ci.scan("huge.css", "a" * (ci.MAX_FILE_BYTES + 10), "css")
    assert not big["file"]["indexed"] and "cap" in big["file"]["reason"]
    bin_file = ci.scan("pixel.png", "binary", "text")
    assert not bin_file["file"]["indexed"] and "no scanner" in bin_file["file"]["reason"]
    assert ci.language_of("app.js") == "js" and ci.language_of("x", "css") == "css"


def test_workspace_byte_budget_stops_indexing_later_files(monkeypatch):
    monkeypatch.setattr(ci, "MAX_TOTAL_BYTES", len(PAGE) + 40)
    x = ci.build_index([{"name": "index.html", "language": "html", "text": PAGE},
                        {"name": "styles.css", "language": "css", "text": CSS},
                        {"name": "app.js", "language": "js", "text": JS}])
    assert x["truncated"]
    skipped = [f for f in x["files"] if not f["indexed"]]
    assert [f["name"] for f in skipped] == ["styles.css", "app.js"]
    assert "workspace over" in skipped[0]["reason"]
    assert next(f for f in x["files"] if f["name"] == "index.html")["indexed"]


def test_file_limit_is_honest():
    monkey_files = [{"name": f"f{i}.css", "language": "css", "text": ".a{}"} for i in range(ci.MAX_FILES + 2)]
    x = ci.build_index(monkey_files)
    assert x["truncated"]
    assert sum(1 for f in x["files"] if not f["indexed"]) == 2


@pytest.mark.parametrize("text,language,kind", [(".a{}", "css", "css-class"), ("var f = 1;", "js", "const")])
def test_scanners_do_not_crash_on_fragments(text, language, kind):
    part = ci.scan(f"frag.{language}", text, language)
    assert part["file"]["indexed"]
