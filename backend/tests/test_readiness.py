from types import SimpleNamespace as NS

from app.orchestrator.readiness import compute_readiness


def state(errors=0, warnings=0, avg=None, violations=0, checks=True):
    panel = None if avg is None else {"avg_score": avg, "signups": 3, "reactions": [1, 2, 3, 4]}
    return NS(check_results=[1] if checks else [], check_summary={"errors": errors, "warnings": warnings},
              panel=panel, sanitizer_violations=["x"] * violations)


def test_perfect_page_scores_100():
    r = compute_readiness(state(avg=10))
    assert r["total"] == 100 and r["verdict"] == "Ready to launch"


def test_errors_and_warnings_reduce_quality():
    r = compute_readiness(state(errors=2, warnings=1, avg=10))
    q = next(c for c in r["components"] if c["id"] == "quality")
    assert q["score"] == 50 - 24 - 3 and r["total"] < 100


def test_total_is_renormalised_when_panel_missing():
    r = compute_readiness(state(avg=None))
    assert [c["id"] for c in r["components"]] == ["quality", "hygiene"] and r["total"] == 100


def test_sanitizer_violations_cost_hygiene_points_floor_zero():
    r = compute_readiness(state(avg=8, violations=10))
    assert next(c for c in r["components"] if c["id"] == "hygiene")["score"] == 0


def test_verdict_thresholds():
    assert compute_readiness(state(errors=3, avg=3))["verdict"] == "Needs work"
    assert compute_readiness(state(errors=1, avg=7))["verdict"] == "Almost there"