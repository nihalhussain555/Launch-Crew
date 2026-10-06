import pytest

from app.llm.mock import build_page
from app.tools import browser_checks
from app.tools.browser_checks import BrowserUnavailable, evaluate_metrics, run_checks, summarize

PAYLOAD = {"copy": {"product_name": "Nightly", "headline": "Habits for nights", "subheadline": "Sub",
                    "features": [{"title": "A", "description": "a"}] * 3, "faq": [{"question": "Q", "answer": "A"}] * 3,
                    "cta": {"label": "Join", "supporting_text": "Soon"}},
           "design": {"palette": {"background": "#0f172a", "surface": "#1e293b", "text": "#f8fafc", "muted_text": "#cbd5e1",
                                  "primary": "#38bdf8", "primary_text": "#0f172a", "accent": "#fbbf24"},
                      "fonts": {"heading": "Arial", "body": "Arial"}, "layout_style": "minimal"}}

BAD_PAGE = """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background:#fff"><div style="width:900px;color:#ccc;font-size:16px">Low contrast text</div>
<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw="><a href="#nowhere">broken</a>
<a href="#x" style="display:block;width:20px;height:20px">t</a><p style="font-size:9px;color:#000">tiny</p></body></html>"""


# ---------- pure logic (no browser)
def test_evaluate_metrics_flags_everything():
    m = {"innerWidth": 375, "scrollWidth": 600,
         "contrast": [{"text": "x", "fg": [200, 200, 200, 1], "bg": [255, 255, 255], "size": 16, "bold": False}],
         "fonts": [{"text": "t", "size": 9}], "taps": [{"text": "b", "w": 20, "h": 20}]}
    c = {x["id"]: x for x in evaluate_metrics(m, "mobile")}
    assert not c["overflow"]["passed"] and not c["contrast"]["passed"]
    assert not c["font_size"]["passed"] and not c["tap_targets"]["passed"]
    d = {x["id"]: x for x in evaluate_metrics({"innerWidth": 1280, "scrollWidth": 1280, "brokenLinks": ["x"], "missingAlt": ["i"],
                                               "sections": {"hero": True, "features": True, "faq": False, "cta": True}}, "desktop")}
    assert not d["links"]["passed"] and not d["alt_text"]["passed"] and "faq" in d["sections"]["detail"]
    assert summarize(list(c.values())) ["errors"] == 2


def test_large_text_threshold():
    m = {"innerWidth": 1280, "scrollWidth": 1280, "fonts": [], "taps": [],
         "contrast": [{"text": "big", "fg": [140, 140, 140, 1], "bg": [255, 255, 255], "size": 32, "bold": False}]}
    assert next(c for c in evaluate_metrics(m, "desktop") if c["id"] == "contrast")["passed"]  # ~3.3:1 ok for large text


# ---------- real Chromium (skipped if browsers aren't installed)
@pytest.fixture
async def browser_ok():
    try:
        await run_checks("<html><body>x</body></html>")
    except (BrowserUnavailable, ImportError):
        pytest.skip("Playwright/Chromium not available")


async def test_good_page_passes(browser_ok):
    checks, shots = await run_checks(build_page(PAYLOAD))
    assert summarize(checks)["errors"] == 0, [c for c in checks if not c["passed"]]
    assert set(shots) == {"desktop", "mobile"} and shots["mobile"][:2] == b"\xff\xd8"


async def test_bad_page_flagged(browser_ok):
    checks, _ = await run_checks(BAD_PAGE)
    failed = {(c["id"], c["viewport"]) for c in checks if not c["passed"]}
    assert {("overflow", "mobile"), ("contrast", "mobile"), ("links", "desktop"), ("alt_text", "desktop"),
            ("sections", "desktop"), ("tap_targets", "mobile"), ("font_size", "mobile")} <= failed
