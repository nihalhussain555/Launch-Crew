"""Tests for the diff helper: version pairs must report honest line counts and readable hunks."""
from app.tools.differ import diff, readable, stats

V1 = "<html><body><h1>Old headline</h1><p>Same line</p></body></html>"
V2 = "<html><body><h1>New headline</h1><p>Same line</p><p>Fresh line</p></body></html>"


def test_readability_splits_dense_markup_into_lines():
    lines = readable(V1)
    assert len(lines) > 1
    assert any("Old headline" in line for line in lines)
    assert all(line.strip() for line in lines)                 # blank lines dropped


def test_diff_reports_the_edit_and_the_insertion():
    d = diff(V1, V2, "v1", "v2")
    assert d["changed"] is True
    assert d["removed"] == 1                    # the headline line
    assert d["added"] >= 2                      # tag-breaking puts "<p>" and its text on separate lines
    kinds = {r["kind"] for r in d["rows"]}
    assert {"add", "del", "ctx", "hunk"} <= kinds
    assert not any(r["text"].startswith(("+++", "---")) for r in d["rows"])


def test_identical_versions_have_no_changes():
    d = diff(V1, V1, "v1", "v1")
    assert d["changed"] is False and d["rows"] == []


def test_diff_text_carries_the_new_content():
    d = diff(V1, V2, "v1", "v2")
    assert any("New headline" in r["text"] for r in d["rows"] if r["kind"] == "add")
    assert any("Old headline" in r["text"] for r in d["rows"] if r["kind"] == "del")
    assert any("Same line" in r["text"] for r in d["rows"] if r["kind"] == "ctx")


def test_stats_of_a_rewrite_are_not_zero():
    s = stats(V1, "<html><body><h1>Completely different</h1></body></html>")
    assert s["same"] is False and s["lines_added"] >= 1


def test_stats_of_the_same_page():
    assert stats(V1, V1) == {"lines_added": 0, "lines_removed": 0, "same": True}


def test_empty_side_is_handled():
    assert readable("") == []
    d = diff("", V2, "v1", "v2")
    assert d["changed"] is True and d["removed"] == 0
