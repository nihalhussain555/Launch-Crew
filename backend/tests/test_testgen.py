"""The generated regression suite: written from a real page, executed for real, and honest when it fails."""
import re
import tempfile
from pathlib import Path

from app.tools import testgen

PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
        '<title>Habit Tracker for night shift workers</title></head>'
        '<body><main id="lc-main"><header><nav aria-label="Sections"><a href="#how">How it works</a></nav>'
        '<h1>Small wins, night shift proof</h1></header>'
        '<section id="how"><h2>How it works</h2><p>Track one streak and keep the win.</p>'
        '<form action="#"><label for="email">Email</label>'
        '<input id="email" name="email" type="email"><button type="submit">Get early access</button></form>'
        '</section></main>'
        '<style>:root{--text:#0b1220;--bg:#f6f9fc;--on-primary:#ffffff;--primary:#0e7490}'
        'body{color:var(--text);background:var(--bg)}</style>'
        '<script>document.getElementById("email").addEventListener("submit",()=>{})</script></body></html>')

STDLIB = {"__future__", "json", "re", "sys", "pathlib", "string"}


def cases(result):
    return {c["name"]: c["ok"] for c in result["cases"]}


def test_the_generated_suite_passes_the_page_it_was_written_from():
    script = testgen.generate(PAGE, idea="A habit tracker for night-shift workers", version=1)
    result = testgen.execute(script, PAGE)
    assert result["ran"] is True, result["reason"]
    assert result["failed"] == 0, [c for c in result["cases"] if not c["ok"]]
    assert result["passed"] >= 12
    assert all(cases(result).values())


def test_the_generated_file_is_self_contained_python():
    script = testgen.generate(PAGE, idea="tracker", version=1)
    compile(script, "test_page.py", "exec")
    assert {m.group(1) for m in re.finditer(r"^import ([a-z_]+)", script, re.M)} <= STDLIB
    assert "pytest" not in script.lower() or "Run:" in script        # runs without third-party packages


def test_expectations_are_the_values_this_page_actually_has():
    script = testgen.generate(PAGE, idea="tracker", version=3)
    assert "page v3" in script
    expect = re.search(r"EXPECTED = (\{.*?\})\n", script, re.S).group(1)
    for phrase in ("Habit Tracker for night shift workers", "Small wins, night shift proof",
                   "Get early access", "lc-main", "email"):
        assert phrase in expect, phrase
    assert "True" in expect and "true" not in expect                 # Python literals, not JSON


def test_the_suite_fails_when_the_page_breaks_one_of_its_own_promises():
    script = testgen.generate(PAGE, idea="tracker", version=1)
    broken = PAGE.replace("<h1>Small wins, night shift proof</h1>", "<h1>Something else entirely</h1>")
    result = testgen.execute(script, broken)
    assert result["ran"] is True and result["failed"] >= 1
    failed = [name for name, ok in cases(result).items() if not ok]
    assert any("headline" in name for name in failed), failed

    findings = testgen.findings(result, version=2)
    assert any(f["status"] == "fail" and "headline" in f["id"] for f in findings), findings
    assert all("Repair the page" in f["fix"] for f in findings if f["status"] == "fail")


def test_findings_report_a_suite_that_could_not_run():
    result = testgen.execute("this is not python", PAGE)
    assert result["ran"] is False and result["reason"]
    findings = testgen.findings(result, version=1)
    assert findings[0]["id"] == "suite_ran" and findings[0]["status"] == "fail"
    # the failure never becomes an instruction to edit the test
    assert "report this run" in findings[0]["fix"]


FAKE_PASS = ("import json\nprint('LC-RESULT ' + json.dumps("
             "{'passed': 1, 'failed': 0, 'cases': [{'name': 'x', 'ok': True}]}))")


def test_execute_cleans_up_the_directory_it_ran_in():
    tmp = Path(tempfile.gettempdir())
    leftover = lambda: [p for p in tmp.glob("lc-tests-*")]
    before = len(leftover())
    result = testgen.execute(FAKE_PASS, PAGE)
    assert result["ran"] is True and result["passed"] == 1 and result["cases"][0]["ok"] is True
    assert len(leftover()) <= before
