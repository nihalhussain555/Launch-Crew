"""Tests for the workspace splitter: the canonical page must stay intact and every asset must be real."""
from app.tools.splitter import readme, split_page

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Demo - Headline</title>
<style>:root{--radius:4px}body{background:#fff}</style>
<style>.hero{display:grid}</style>
</head>
<body>
<header id="hero"><h1>Hello</h1></header>
<script type="application/ld+json">{"@context":"https://schema.org"}</script>
<script>document.getElementById('hero').addEventListener('click',function(){});</script>
</body></html>
"""


def names(assets):
    return [a.name for a in assets]


def test_extracts_css_and_js():
    standalone, assets = split_page(PAGE)
    assert names(assets) == ["styles.css", "app.js"]
    assert ":root{--radius:4px}body{background:#fff}" in assets[0].text
    assert ".hero{display:grid}" in assets[0].text          # both blocks fold into one stylesheet
    assert "addEventListener('click'" in assets[1].text


def test_standalone_page_references_the_assets():
    standalone, _ = split_page(PAGE)
    assert '<link rel="stylesheet" href="styles.css">' in standalone
    assert '<script src="app.js"></script>' in standalone
    assert "<style>" not in standalone                       # moved out, not duplicated


def test_structured_data_script_stays_inline():
    standalone, assets = split_page(PAGE)
    assert "application/ld+json" in standalone              # not JS: must not be moved or parsed as code
    assert "schema.org" in standalone
    assert "schema.org" not in "".join(a.text for a in assets if a.name == "app.js")


def test_body_content_is_untouched():
    standalone, _ = split_page(PAGE)
    assert '<header id="hero"><h1>Hello</h1></header>' in standalone
    assert standalone.startswith("<!DOCTYPE html>")
    assert standalone.rstrip().endswith("</html>")


def test_page_without_js_omits_app_js():
    _, assets = split_page("<html><head><style>a{}</style></head><body>x</body></html>")
    assert names(assets) == ["styles.css"]


def test_plain_page_yields_no_assets():
    _, assets = split_page("<html><body><p>Hi</p></body></html>")
    assert assets == []


def test_empty_script_is_not_shipped():
    _, assets = split_page("<html><head><style>a{}</style></head><body><script></script></body></html>")
    assert names(assets) == ["styles.css"]


def test_readme_documents_the_files():
    _, assets = split_page(PAGE)
    doc = readme("A tiny CRM", assets, version=3, readiness=92)
    assert doc.name == "README.md"
    assert "A tiny CRM" in doc.text and "v3" in doc.text and "92/100" in doc.text
    assert "styles.css" in doc.text and "app.js" in doc.text


def test_readme_without_readiness():
    doc = readme("Idea", [], version=1, readiness=None)
    assert "/100" not in doc.text and "v1" in doc.text
