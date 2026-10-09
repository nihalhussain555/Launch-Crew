"""Automated test generation: a regression suite written from the page that was actually built.

The generated file needs nothing but the standard library. It asserts the concrete things this page
promised at build time - its title, headline, call-to-action labels, section ids, anchor targets,
labelled fields, palette contrast, the absence of network APIs - so a later edit that quietly drops
one of them fails a test. Expectations are extracted with the same regular expressions the test file
uses, so the two sides can never disagree about one build.

It runs under pytest (`pytest -q tests/test_page.py`) and standalone (`python tests/test_page.py`),
which prints one `LC-RESULT {json}` line the crew parses into real pass/fail numbers.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from string import Template

from app.tools import audit_util as au

RESULT_PREFIX = "LC-RESULT "
TIMEOUT_S = 90

_TAG_TEXT = re.compile(r"<{tag}\b[^>]*>(.*?)</{tag}>", re.S | re.I)


def _inner_text(html: str, pattern: str) -> list[str]:
    """Text of every element matching `pattern` (tags stripped, whitespace collapsed)."""
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m)).strip()
            for m in re.findall(pattern, html, re.S | re.I)]


_TEMPLATE = Template(r'''"""Launch Crew regression tests for "$idea".

Generated from page v$version on $stamp. Every expectation below is the value this page had when
the crew built it; if a later edit changes one of them, the matching test fails.

Run:  pytest -q tests/test_page.py     (or)  python tests/test_page.py
Needs: Python 3.9 or newer. No third-party packages.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

EXPECTED = $expect_literal
MAX_BYTES = $max_bytes
RESULT_PREFIX = "LC-RESULT "


def page_text():
    for candidate in (Path(__file__).parent / "index.html", Path(__file__).parent.parent / "index.html",
                      Path.cwd() / "index.html"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("index.html is not next to this test or one level up - re-export the workspace.")


def inner(pattern):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m)).strip()
            for m in re.findall(pattern, page_text(), re.S | re.I)]


def all_tags():
    return re.findall(r"<([a-z0-9]+)\b([^>]*)>", page_text(), re.I)


def parse_attrs(raw):
    found = {k.lower(): v for k, v in re.findall(r"([a-zA-Z0-9_:.-]+)\s*=\s*" + '"' + r"([^" + '"' + r"]*)" + '"', raw)}
    found.update({k.lower(): v for k, v in re.findall(r"([a-zA-Z0-9_:.-]+)\s*=\s*'([^']*)'", raw)})
    for bare in re.findall(r"[a-zA-Z0-9_:.-]+(?=[\s>]?)", raw):
        found.setdefault(bare.lower(), "")
    return found


def all_attrs():
    return [parse_attrs(raw) for _name, raw in all_tags()]


def attrs_of(tag):
    return [parse_attrs(raw) for name, raw in all_tags() if name == tag]


def ids():
    return [a["id"] for a in all_attrs() if a.get("id")]


def rgb_of(value):
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def luminance(rgb):
    r, g, b = [(c / 255 / 12.92 if c / 255 <= 0.03928 else ((c / 255 + 0.055) / 1.055) ** 2.4) for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(rgb_of(a)), luminance(rgb_of(b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_document_is_a_complete_page():
    html = page_text()
    assert html.lstrip().lower().startswith("<!doctype html"), "missing doctype"
    assert re.search(r"<html\b", html), "missing <html>"
    assert re.search(r"<head\b", html) and re.search(r"<body\b", html), "missing head or body"
    assert "</html>" in html, "the document is truncated"


def test_title_has_not_changed():
    titles = inner(r"<title\b[^>]*>(.*?)</title>")
    assert titles == [EXPECTED["title"]], f"title is {titles[:1]!r}, was {EXPECTED['title']!r}"


def test_headline_has_not_changed():
    h1 = inner(r"<h1\b[^>]*>(.*?)</h1>")
    assert len(h1) == 1, f"{len(h1)} h1 elements, expected exactly 1"
    assert h1[0] == EXPECTED["h1"], f"h1 is {h1[0]!r}, was {EXPECTED['h1']!r}"


def test_sections_are_still_present():
    missing = [i for i in EXPECTED["sections"] if i not in ids()]
    assert not missing, f"section ids gone: {missing}"


def test_in_page_links_still_resolve():
    targets = set(ids()) | {a.get("name") for a in all_attrs() if a.get("name")}
    broken = [h for h in [a.get("href") for a in attrs_of("a")] if h and h.startswith("#") and h[1:] not in targets]
    assert not broken, f"anchors without a target: {broken}"


def test_form_fields_stay_labelled():
    labelled = {v.get("for") for v in attrs_of("label")}
    controls = attrs_of("input") + attrs_of("select") + attrs_of("textarea")
    controls = [c for c in controls if c.get("type") not in ("hidden", "submit", "button", "reset")]
    unlabelled = [c.get("id") or c.get("type") or "control" for c in controls
                  if not (c.get("aria-label") or c.get("title") or c.get("id") in labelled)]
    assert not unlabelled, f"{len(unlabelled)} control(s) lost their programmatic label: {unlabelled}"
    assert len(controls) == EXPECTED["fields"], f"field count changed: {len(controls)} vs {EXPECTED['fields']}"


def test_images_stay_described():
    missing = [i.get("src", "img")[:40] for i in attrs_of("img") if "alt" not in i]
    assert not missing, f"images without alt: {missing}"


def test_no_external_resource_appeared():
    refs = [v for tag in ("script", "img", "link", "source", "iframe", "video", "audio")
            for v in [a.get("src") for a in attrs_of(tag)] if v and re.match(r"^(https?:)?//", v, re.I)]
    refs += [h for h in [a.get("href") for a in attrs_of("a")] if h and re.match(r"^(https?:)?//", h, re.I)]
    refs += re.findall(r"url\(\s*[\"']?\s*(?:https?:)?//[^)]*", page_text(), re.I)
    assert not refs, f"the page now reaches off-page: {refs[:4]}"


def test_no_network_or_storage_apis():
    scripts = [s for s in re.findall(r"<script\b([^>]*)>(.*?)</script>", page_text(), re.S | re.I)
               if "ld+json" not in s[0].lower()]
    risky = re.compile(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|localStorage|sessionStorage|"
                       r"indexedDB|document\.cookie|eval)\s*\(|new\s+Function\s*\(")
    hits = sorted({m.group(0) for _attrs, body in scripts for m in risky.finditer(body)})
    assert not hits, f"the page script gained risky APIs: {hits}"


def test_content_security_policy_is_still_injected():
    if not EXPECTED["csp"]:
        return
    metas = [m for m in attrs_of("meta") if m.get("http-equiv", "").lower() == "content-security-policy"]
    assert metas and "default-src 'none'" in metas[0].get("content", ""), "the CSP meta tag is missing or loosened"


def test_mobile_viewport_is_declared():
    viewport = [m.get("content", "") for m in attrs_of("meta") if m.get("name") == "viewport"]
    assert viewport and "width=device-width" in viewport[0], f"viewport meta is {viewport}"
    assert not re.search(r"user-scalable\s*=\s*no|maximum-scale\s*=\s*[12]\b", viewport[0]), "pinch zoom is blocked"


def test_language_is_declared():
    root = attrs_of("html")
    assert root and root[0].get("lang"), "<html> has no lang attribute"


def test_palette_still_passes_wcag_aa():
    tokens = EXPECTED["tokens"]
    bad = [f"{fg} on {bg} is {contrast(tokens[fg], tokens[bg]):.2f}:1"
           for fg, bg, _what in EXPECTED["pairs"] if tokens.get(fg) and tokens.get(bg)
           and contrast(tokens[fg], tokens[bg]) < 4.5]
    assert not bad, f"the palette fell below WCAG AA: {bad}"


def test_heading_levels_do_not_skip():
    levels = [int(t[1]) for t, _raw in all_tags() if re.fullmatch(r"h[1-6]", t)]
    skips = [f"h{levels[i - 1]} then h{levels[i]}" for i in range(1, len(levels)) if levels[i] - levels[i - 1] > 1]
    assert not skips, f"a heading level was skipped: {skips}"


def test_ids_are_unique():
    seen = [i for i in ids() if i]
    dupes = sorted({i for i in seen if seen.count(i) > 1})
    assert not dupes, f"duplicate ids: {dupes}"


def test_page_is_within_its_budget():
    size = len(page_text().encode("utf-8"))
    assert size <= MAX_BYTES, f"the page grew to {size} bytes (budget {MAX_BYTES})"


def test_forms_cannot_post_off_page():
    stray = [f.get("action") for f in attrs_of("form") if (f.get("action") or "#").strip() not in ("", "#")]
    assert not stray, f"a form action points off-page: {stray}"


def test_call_to_action_labels_have_not_changed():
    now = inner(r"<a\b[^>]*class=\"[^\"]*\bbtn\b[^\"]*\"[^>]*>(.*?)</a>") + inner(r"<button\b[^>]*>(.*?)</button>")
    assert now == EXPECTED["cta"], f"button text changed: {now} was {EXPECTED['cta']}"


def main():
    cases, failures = [], 0
    for name in sorted(k for k in globals() if k.startswith("test_")):
        try:
            globals()[name]()
            cases.append({"name": name, "ok": True, "detail": ""})
            print(f"PASS {name}")
        except AssertionError as exc:
            failures += 1
            cases.append({"name": name, "ok": False, "detail": str(exc)[:240]})
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - a broken test is still a signal worth reporting
            failures += 1
            cases.append({"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"[:240]})
            print(f"ERROR {name}: {exc}")
    print(RESULT_PREFIX + json.dumps({"passed": len(cases) - failures, "failed": failures, "cases": cases}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
''')


def _expectations(html: str) -> dict:
    """The values this page has right now, read with the same expressions the test file uses."""
    title = _inner_text(html, r"<title\b[^>]*>(.*?)</title>")
    h1 = _inner_text(html, r"<h1\b[^>]*>(.*?)</h1>")
    cta = _inner_text(html, r'<a\b[^>]*class="[^"]*\bbtn\b[^"]*"[^>]*>(.*?)</a>') + \
          _inner_text(html, r"<button\b[^>]*>(.*?)</button>")
    sections = sorted(set(re.findall(r"\bid=\"([a-zA-Z][\w-]*)\"", html)))
    fields = re.findall(r"<(?:input|select|textarea)\b([^>]*)>", html, re.I)
    fields = [a for a in fields if not re.search(r"""type\s*=\s*["'](?:hidden|submit|button|reset)""", a, re.I)]
    tokens = au.hex_tokens(html)
    pairs = [[fg, bg, what] for fg, bg, what in au.AA_PAIRS if tokens.get(fg) and tokens.get(bg)]
    return {"title": title[0] if title else "", "h1": h1[0] if h1 else "",
            "sections": sections,
            "fields": len(fields), "imgs": len(re.findall(r"<img\b", html, re.I)),
            "csp": bool(re.search(r"""<meta[^>]+http-equiv=["']?content-security-policy""", html, re.I)),
            "cta": cta, "tokens": tokens, "pairs": pairs}


def generate(html: str, *, idea: str, version: int) -> str:
    expect = _expectations(html)
    max_bytes = max(90_000, int(len(html.encode("utf-8")) * 1.6))
    return _TEMPLATE.substitute(idea=(idea or "the generated page")[:120].replace('"', "'").replace("$", "-"),
                               version=version, stamp=au.stamp(),
                               # a Python literal, so booleans are True/False rather than JSON's true/false
                               expect_literal=repr(expect),
                               max_bytes=max_bytes)


def execute(test_text: str, html: str) -> dict:
    """Run the generated suite in a throwaway directory with this interpreter. Never raises."""
    tmp = Path(tempfile.mkdtemp(prefix="lc-tests-"))
    try:
        (tmp / "index.html").write_text(html, encoding="utf-8")
        script = tmp / "test_page.py"
        script.write_text(test_text, encoding="utf-8")
        try:
            done = subprocess.run([sys.executable, "-X", "utf8", script.name], cwd=str(tmp),
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {"ran": False, "reason": f"The generated suite did not finish in {TIMEOUT_S}s.",
                    "passed": 0, "failed": 0, "cases": [], "output": ""}
        except OSError as exc:
            return {"ran": False, "reason": f"Could not start Python to run the suite: {exc}",
                    "passed": 0, "failed": 0, "cases": [], "output": ""}
        payload = next((line[len(RESULT_PREFIX):] for line in (done.stdout or "").splitlines()
                        if line.startswith(RESULT_PREFIX)), "")
        if not payload:
            return {"ran": False, "reason": ((done.stderr or "") or (done.stdout or "") or "no output")[-400:].strip(),
                    "passed": 0, "failed": 0, "cases": [], "output": (done.stdout or "")[-800:]}
        try:
            result = json.loads(payload)
        except ValueError:
            return {"ran": False, "reason": "The suite reported unparseable results.",
                    "passed": 0, "failed": 0, "cases": [], "output": (done.stdout or "")[-800:]}
        return {"ran": True,
                "reason": "" if done.returncode == 0 else f"{result.get('failed', 0)} test(s) failed",
                "passed": int(result.get("passed", 0)), "failed": int(result.get("failed", 0)),
                "cases": result.get("cases", []), "output": (done.stdout or "")[-800:]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def findings(result: dict, *, version: int) -> list[dict]:
    """Turn a real run of the generated suite into audit findings.

    The suite is written from the page that is live, so a case that fails here is the page breaking
    one of its own promises - the fix instruction says to repair the page, never the test.
    """
    if not result.get("ran"):
        return [au.finding("suite_ran", "The generated suite executes", au.FAIL,
                           f"The suite did not run: {(result.get('reason') or '')[:240]}",
                           "The generated file could not be executed; report this run instead of editing the test.")]
    total = int(result.get("passed", 0)) + int(result.get("failed", 0))
    failed = [c for c in result.get("cases", []) if not c.get("ok")]
    out = [au.ok("suite_ran", "The generated suite executes",
                 f"{result.get('passed', 0)}/{total} regression case(s) pass against page v{version}.")]
    for case in failed[:8]:
        out.append(au.finding(str(case.get("name", "case")), f"Regression: {case.get('name')}", au.FAIL,
                              str(case.get("detail", ""))[:300],
                              f"Repair the page so {case.get('name')} holds again: {str(case.get('detail', ''))[:160]}"))
    if len(failed) > 8:
        out.append(au.finding("more_cases", "Further failing cases", au.FAIL, f"{len(failed) - 8} more in the report."))
    return out
