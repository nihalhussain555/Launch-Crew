import re

import pytest

from app.llm.mock import build_page
from app.tools import browser_checks
from app.tools.browser_checks import BrowserUnavailable, VIEWPORTS, evaluate_metrics, run_checks, summarize
from app.utils.color import hex_to_rgb

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


# ---------- a themed page, measured through the real cascade
def themed_page():
    """A saas page drawn in a theme that moves colour, radius, shadow, card treatment, density and type."""
    from app.agents import variants
    d = variants.direction_for("studio desk", {"style": "saas", "theme": {
        "family": "futuristic", "mode": "dark", "card": "glass", "shadow": "strong",
        "button": "pill", "radius": "rounded", "density": "roomy", "scale": 1.15}})
    return d, build_page({"copy": PAYLOAD["copy"], "design": {"palette": dict(d.palette),
                                                              "fonts": dict(d.fonts),
                                                              "layout_style": d.layout_style},
                          "direction": variants.as_dict(d)})


PROBE_JS = """() => {
  const at = sel => { const el = document.querySelector(sel); if (!el) return null;
    const cs = getComputedStyle(el);
    return {bg: cs.backgroundColor, color: cs.color, radius: cs.borderRadius, blur: cs.backdropFilter,
            pad: cs.paddingTop, fs: cs.fontSize, width: cs.maxWidth}; };
  return {body: at('body'), card: at('.card'), btn: at('.btn'), section: at('section'), wrap: at('.wrap')};
}"""


async def _computed(html: str, viewport: dict) -> dict:
    import asyncio
    import sys

    async def _gather():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                ctx = await browser.new_context(viewport=viewport, device_scale_factor=1)
                await ctx.route(re.compile(r"^https?://"), lambda route: route.abort())
                page = await ctx.new_page()
                await page.set_content(html, wait_until="load", timeout=15000)
                return await page.evaluate(PROBE_JS)
            finally:
                await browser.close()

    if sys.platform == "win32":                      # same Proactor-loop workaround run_checks uses
        def _in_proactor():
            loop = asyncio.ProactorEventLoop()
            try:
                return loop.run_until_complete(_gather())
            finally:
                loop.close()
        return await asyncio.to_thread(_in_proactor)
    return await _gather()


def _rgb(hexc: str) -> str:
    r, g, b = hex_to_rgb(hexc)
    return f"rgb({int(r)}, {int(g)}, {int(b)})"


async def test_a_theme_edit_is_rendered_from_its_tokens_alone(browser_ok):
    """The patch only writes `:root`; every component that picks the theme up has to do it in the browser."""
    from app.agents import theme as design_theme, variants
    from app.services import theme_edit, workspace_manager

    plain_direction = variants.direction_for("studio desk", {"style": "saas"})
    plain = build_page({"copy": PAYLOAD["copy"], "design": {"palette": dict(plain_direction.palette),
                                                            "fonts": dict(plain_direction.fonts),
                                                            "layout_style": plain_direction.layout_style},
                       "direction": variants.as_dict(plain_direction)})
    controls = {"family": "futuristic", "mode": "dark", "radius": "pill", "card": "glass", "scale": 1.15}
    resolved = design_theme.resolve(controls)
    patch = theme_edit.plan({"index.html": plain},
                            variants.retheme(plain_direction, design_theme.as_stored(resolved)))["changes"][0]
    patched = workspace_manager.apply_op(plain, patch)
    assert patched != plain
    assert patched.split("</style>")[1] == plain.split("</style>")[1]   # only the token block moved

    before, after = (await _computed(plain, VIEWPORTS["desktop"]),
                     await _computed(patched, VIEWPORTS["desktop"]))
    assert after["body"]["bg"] == _rgb(resolved["palette"]["background"]) != before["body"]["bg"]
    assert after["btn"]["bg"] == _rgb(resolved["palette"]["primary"])
    assert float(after["card"]["radius"][:-2]) > float(before["card"]["radius"][:-2])
    assert after["card"]["blur"].startswith("blur(") and before["card"]["blur"] in ("none", "blur(0px)")
    assert float(after["body"]["fs"][:-2]) > float(before["body"]["fs"][:-2])   # the theme's type scale
    checks, _ = await run_checks(patched)
    assert summarize(checks)["errors"] == 0, [c for c in checks if not c["passed"]]


async def test_the_theme_is_applied_by_the_browser_not_only_declared(browser_ok):
    """The point of the variable block is that components pick it up, so measure the real cascade."""
    d, html = themed_page()
    desk, mob = await _computed(html, VIEWPORTS["desktop"]), await _computed(html, VIEWPORTS["mobile"])
    assert desk["btn"]["bg"] == _rgb(d.palette["primary"])       # --btn-bg -> var(--primary)
    assert desk["btn"]["color"] == _rgb(d.palette["primary_text"])
    assert desk["body"]["bg"] == _rgb(d.palette["background"])
    assert desk["body"]["fs"] == d.tokens["base"]                 # the theme's type scale, not the style's
    assert desk["card"]["blur"].startswith("blur(")               # glass cards really blur
    assert float(desk["card"]["radius"][:-2]) > 0
    assert float(desk["section"]["pad"][:-2]) > float(mob["section"]["pad"][:-2])  # --pad per breakpoint
    assert desk["wrap"]["width"] == d.tokens["width"]
    checks, _ = await run_checks(html)
    assert summarize(checks)["errors"] == 0, [c for c in checks if not c["passed"]]
