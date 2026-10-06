"""Rule-based page checks run in Playwright (Chromium) at desktop (1280px) and mobile (375px).

The browser only *collects raw metrics* (JS below). All pass/fail decisions are made by pure Python
functions (`evaluate_metrics`) so they are unit-testable without a browser.

Check dict: {id, label, viewport, passed, severity: error|warning, detail}
"""
from __future__ import annotations

import asyncio
import re
import sys
from typing import Any

from app.utils.color import contrast_ratio, is_large_text

VIEWPORTS = {"desktop": {"width": 1280, "height": 800}, "mobile": {"width": 375, "height": 812}}
MIN_TAP = 44          # px, WCAG 2.5.5 / Apple HIG
MIN_FONT_MOBILE = 12  # px

COLLECT_JS = r"""
() => {
  const num = s => (s || '').match(/-?[\d.]+/g);
  const parse = s => { const m = num(s); if (!m || m.length < 3 || /^color\(|oklch|lab/.test(s)) return null;
    return {r:+m[0], g:+m[1], b:+m[2], a: m.length > 3 ? +m[3] : 1}; };
  const bgOf = el => {
    const layers = []; let cur = el;
    while (cur && cur.nodeType === 1) {
      const cs = getComputedStyle(cur);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;   // gradients/images: unknown
      const c = parse(cs.backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
      cur = cur.parentElement;
    }
    let b = {r:255, g:255, b:255};
    for (let i = layers.length - 1; i >= 0; i--) { const t = layers[i];
      b = {r: t.r*t.a + b.r*(1-t.a), g: t.g*t.a + b.g*(1-t.a), b: t.b*t.a + b.b*(1-t.a)}; }
    return [b.r, b.g, b.b];
  };
  const visible = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (el.checkVisibility && !el.checkVisibility()) return false;
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const label = el => (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.tagName).trim().slice(0, 40);

  const m = {};
  m.innerWidth = window.innerWidth;
  m.scrollWidth = Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0);

  // contrast + font sizes
  const samples = [], fonts = [];
  const skip = new Set(['SCRIPT','STYLE','NOSCRIPT','HEAD','TITLE','META']);
  document.querySelectorAll('body *').forEach(el => {
    if (skip.has(el.tagName) || el.closest('svg')) return;
    const own = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own || !visible(el)) return;
    const cs = getComputedStyle(el), size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const fg = parse(cs.color), bg = bgOf(el);
    if (fg && bg) samples.push({text: label(el), fg: [fg.r, fg.g, fg.b, fg.a], bg, size, bold});
    fonts.push({text: label(el), size});
  });
  m.contrast = samples; m.fonts = fonts;

  // tap targets
  m.taps = [];
  document.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,[role=button],summary').forEach(el => {
    if (!visible(el) || getComputedStyle(el).display === 'inline') return;   // inline text links are exempt
    const r = el.getBoundingClientRect();
    m.taps.push({text: label(el), w: Math.round(r.width), h: Math.round(r.height)});
  });

  // links / anchors / alt
  m.brokenLinks = [];
  document.querySelectorAll('a[href]').forEach(a => {
    const h = a.getAttribute('href').trim();
    if (h === '' ) m.brokenLinks.push('empty href: ' + label(a));
    else if (h.startsWith('#')) { if (h.length > 1) { const id = decodeURIComponent(h.slice(1));
        if (!document.getElementById(id) && !document.getElementsByName(id).length) m.brokenLinks.push('missing anchor target ' + h); } }
    else if (!/^(https?:|mailto:|tel:)/i.test(h)) m.brokenLinks.push('unsupported link ' + h.slice(0, 40));
  });
  m.missingAlt = Array.from(document.querySelectorAll('img:not([alt])')).map(i => (i.getAttribute('src') || '').slice(0, 40) || 'img');

  const has = keys => keys.some(k => document.querySelector(`[id*="${k}" i],[class*="${k}" i]`));
  m.sections = {hero: has(['hero']), features: has(['feature']), faq: has(['faq']), cta: has(['cta','signup','waitlist','get-started'])};
  return m;
}
"""


def _check(id_: str, label: str, viewport: str, passed: bool, severity: str, detail: str = "") -> dict:
    return {"id": id_, "label": label, "viewport": viewport, "passed": passed, "severity": severity, "detail": detail}


def _composite(fg: list[float], bg: list[float]) -> tuple[float, float, float]:
    a = fg[3] if len(fg) > 3 else 1.0
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3))  # type: ignore[return-value]


def evaluate_metrics(m: dict[str, Any], viewport: str) -> list[dict]:
    """Pure function: raw browser metrics -> list of checks."""
    checks: list[dict] = []

    over = m["scrollWidth"] - m["innerWidth"]
    checks.append(_check("overflow", "No horizontal overflow", viewport, over <= 1, "error",
                         f"Page is {over}px wider than the {m['innerWidth']}px viewport" if over > 1 else ""))

    bad, seen = [], set()
    for s in m.get("contrast", []):
        fg = _composite(s["fg"], s["bg"])
        ratio = contrast_ratio(fg, tuple(s["bg"]))
        need = 3.0 if is_large_text(s["size"], s["bold"]) else 4.5
        key = (round(ratio, 2), tuple(round(x) for x in fg), tuple(round(x) for x in s["bg"]))
        if ratio < need and key not in seen:
            seen.add(key)
            bad.append(f"'{s['text']}' ratio {ratio:.2f} (needs {need})")
    checks.append(_check("contrast", "Text contrast meets WCAG AA", viewport, not bad, "error", "; ".join(bad[:6])))

    if viewport == "mobile":
        small_font = [f"'{f['text']}' {f['size']:.0f}px" for f in m.get("fonts", []) if f["size"] < MIN_FONT_MOBILE]
        checks.append(_check("font_size", f"Text >= {MIN_FONT_MOBILE}px on mobile", viewport, not small_font, "warning", "; ".join(small_font[:6])))
        small_tap = [f"'{t['text']}' {t['w']}x{t['h']}px" for t in m.get("taps", []) if t["w"] < MIN_TAP or t["h"] < MIN_TAP]
        checks.append(_check("tap_targets", f"Tap targets >= {MIN_TAP}x{MIN_TAP}px", viewport, not small_tap, "warning", "; ".join(small_tap[:6])))
    else:  # page-content checks are viewport independent: report once, on desktop
        broken = m.get("brokenLinks", [])
        checks.append(_check("links", "No broken links or anchors", viewport, not broken, "error", "; ".join(broken[:6])))
        alt = m.get("missingAlt", [])
        checks.append(_check("alt_text", "Images have alt text", viewport, not alt, "error", f"{len(alt)} image(s) missing alt" if alt else ""))
        missing = [k for k, v in m.get("sections", {}).items() if not v]
        checks.append(_check("sections", "Required sections present (hero, features, FAQ, CTA)", viewport, not missing, "error",
                             f"Missing: {', '.join(missing)}" if missing else ""))
    return checks


def summarize(checks: list[dict]) -> dict:
    failed = [c for c in checks if not c["passed"]]
    return {
        "total": len(checks), "failed": len(failed),
        "errors": sum(1 for c in failed if c["severity"] == "error"),
        "warnings": sum(1 for c in failed if c["severity"] == "warning"),
    }


class BrowserUnavailable(RuntimeError):
    pass


async def run_checks(html: str) -> tuple[list[dict], dict[str, bytes]]:
    """Render `html` at both viewports; returns (checks, {viewport: jpeg bytes}).

    Windows note: Playwright spawns a browser subprocess, which needs a ProactorEventLoop. `uvicorn --reload`
    forces a SelectorEventLoop on Windows, so there we run the browser work in a thread with its own Proactor loop.
    """
    if sys.platform == "win32":
        def _in_proactor():
            loop = asyncio.ProactorEventLoop()
            try:
                return loop.run_until_complete(_run_checks(html))
            finally:
                loop.close()
        return await asyncio.to_thread(_in_proactor)
    return await _run_checks(html)


async def _run_checks(html: str) -> tuple[list[dict], dict[str, bytes]]:
    from playwright.async_api import async_playwright

    checks: list[dict] = []
    shots: dict[str, bytes] = {}
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        except Exception as exc:  # missing browser binaries etc.
            raise BrowserUnavailable(f"Could not launch Chromium: {exc}") from exc
        try:
            for name, vp in VIEWPORTS.items():
                ctx = await browser.new_context(viewport=vp, device_scale_factor=1)
                # Generated pages must be self-contained: block any network access (also prevents SSRF).
                await ctx.route(re.compile(r"^https?://"), lambda route: route.abort())
                page = await ctx.new_page()
                await page.set_content(html, wait_until="load", timeout=15000)
                await page.wait_for_timeout(150)
                metrics = await page.evaluate(COLLECT_JS)
                checks.extend(evaluate_metrics(metrics, name))
                shots[name] = await page.screenshot(full_page=True, type="jpeg", quality=70)
                await ctx.close()
        finally:
            await browser.close()
    return checks, shots