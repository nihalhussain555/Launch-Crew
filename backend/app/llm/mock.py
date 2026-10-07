"""Deterministic offline provider (MOCK_LLM=true). Returns schema-valid output for every agent,
so the full pipeline (including the Playwright critic and deploy gate) works with no API keys."""
from __future__ import annotations

import html
import json
import re

from app.llm.client import LLMResult, ToolCall, Usage

STOP = {"a", "an", "the", "for", "to", "of", "that", "and", "with", "who", "in", "on", "my", "your", "app", "tool"}


def _all_text(messages: list[dict]) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages)


def _idea(messages: list[dict]) -> str:
    m = re.search(r"IDEA:\s*(.+)", _all_text(messages))
    return (m.group(1).strip() if m else "A helpful product")[:200]


def _name(idea: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+", idea) if w.lower() not in STOP]
    return " ".join(w.capitalize() for w in words[:2]) or "Launchly"


def _audience(idea: str) -> str:
    m = re.search(r"\bfor\s+(.+)$", idea, re.I)
    return m.group(1).strip().rstrip(".") if m else "busy people"


def build_page(payload: dict) -> str:
    """Self-contained, accessible, responsive landing page used by the mock Engineer."""
    c, d = payload["copy"], payload["design"]
    p, f = d["palette"], d["fonts"]
    e = html.escape
    features = "".join(
        f'<article class="card"><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></article>' for x in c["features"]
    )
    faqs = "".join(f"<details><summary>{e(x['question'])}</summary><p>{e(x['answer'])}</p></details>" for x in c["faq"])
    css = """
:root{--bg:__bg__;--surface:__surface__;--text:__text__;--muted:__muted__;--primary:__primary__;--on-primary:__onprimary__;--accent:__accent__}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font-family:__body__;line-height:1.6;font-size:17px;overflow-wrap:anywhere}
.wrap{max-width:1040px;margin:0 auto;padding:0 20px}
nav{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;padding:12px 0}
.brand{font-family:__heading__;font-weight:800;font-size:20px}
nav a{display:inline-flex;align-items:center;min-height:44px;padding:0 12px;color:var(--muted);text-decoration:none}
nav a:hover{color:var(--text)}
.hero{padding:48px 0 72px}
h1{font-family:__heading__;font-size:clamp(32px,7vw,56px);line-height:1.1;margin:16px 0}
h2{font-family:__heading__;font-size:clamp(26px,5vw,36px);margin:0 0 24px}
.sub{color:var(--muted);font-size:clamp(18px,3vw,22px);max-width:640px}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:0 28px;border:0;border-radius:12px;background:var(--primary);color:var(--on-primary);font-size:17px;font-weight:700;text-decoration:none;cursor:pointer}
section{padding:56px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}
.card{background:var(--surface);border-radius:16px;padding:24px}.card h3{margin:0 0 8px;color:var(--accent);font-size:20px}.card p{margin:0;color:var(--muted)}
details{background:var(--surface);border-radius:12px;margin-bottom:12px;padding:0 20px}
summary{min-height:48px;display:flex;align-items:center;cursor:pointer;font-weight:600}
details p{color:var(--muted);margin:0 0 16px}
#cta{text-align:center}.signup{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:20px}
input{min-height:48px;min-width:0;flex:1 1 220px;max-width:340px;padding:0 16px;border-radius:12px;border:2px solid var(--muted);background:var(--surface);color:var(--text);font-size:17px}
#msg{min-height:28px;color:var(--accent)}
footer{padding:32px 0;color:var(--muted);font-size:15px;text-align:center}
"""
    for k, v in {"bg": p["background"], "surface": p["surface"], "text": p["text"], "muted": p["muted_text"],
                 "primary": p["primary"], "onprimary": p["primary_text"], "accent": p["accent"],
                 "body": f["body"], "heading": f["heading"]}.items():
        css = css.replace(f"__{k}__", v)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c["product_name"])} - {e(c["headline"])}</title><style>{css}</style></head>
<body>
<header id="hero" class="hero"><div class="wrap">
<nav aria-label="Main"><span class="brand">{e(c["product_name"])}</span><span><a href="#features">Features</a><a href="#faq">FAQ</a><a href="#cta">Join</a></span></nav>
<h1>{e(c["headline"])}</h1><p class="sub">{e(c["subheadline"])}</p>
<p><a class="btn" href="#cta">{e(c["cta"]["label"])}</a></p></div></header>
<main><div class="wrap">
<section id="features"><h2>Why {e(c["product_name"])}</h2><div class="grid">{features}</div></section>
<section id="faq"><h2>Questions, answered</h2>{faqs}</section>
<section id="cta"><h2>{e(c["cta"]["label"])}</h2><p class="sub" style="margin:0 auto">{e(c["cta"]["supporting_text"])}</p>
<form class="signup" id="signup" action="#"><label for="email" class="sr" style="position:absolute;left:-9999px">Email</label>
<input id="email" type="email" placeholder="you@example.com" required><button class="btn" type="submit">{e(c["cta"]["label"])}</button></form>
<p id="msg" role="status"></p></section></div></main>
<footer><div class="wrap">&copy; {e(c["product_name"])}. Built with Launch Crew.</div></footer>
<script>document.getElementById('signup').addEventListener('submit',function(ev){{ev.preventDefault();document.getElementById('msg').textContent="Thanks! You're on the list.";}});</script>
</body></html>"""


class MockProvider:
    async def complete(self, *, agent, model, messages, json_mode, tools, temperature, max_tokens) -> LLMResult:
        text, calls, raw = "", [], None
        idea = _idea(messages)
        name = _name(idea)
        aud = _audience(idea)

        if agent == "researcher" and tools:
            if any(m.get("role") == "tool" for m in messages):
                text = "Research complete."
            else:
                args = {"query": f"{idea} competitors and user pain points"}
                calls = [ToolCall("call_mock_1", "web_search", args)]
                raw = {"role": "assistant", "content": "", "tool_calls": [{
                    "id": "call_mock_1", "type": "function",
                    "function": {"name": "web_search", "arguments": json.dumps(args)}}]}
        elif agent == "researcher":
            text = json.dumps({
                "competitors": [
                    {"name": "GenericApp", "positioning": "One-size-fits-all solution", "weakness": f"Ignores the needs of {aud}"},
                    {"name": "SpreadsheetDIY", "positioning": "Free but manual", "weakness": "Tedious and easy to abandon"}],
                "audience_pain_points": [f"Existing tools are not designed for {aud}", "Too much setup before any value", "Hard to stay consistent"],
                "keywords": [name.lower(), aud.lower(), "simple", "built for you"],
                "opportunity": f"A focused product that treats {aud} as the primary audience, not an afterthought.",
                "sources": ["https://example.com/market-report"]})
        elif agent == "strategist":
            text = json.dumps({
                "positioning": f"{name} is the simplest way for {aud} to get results without the clutter.",
                "persona": {"name": "Sam", "description": f"A busy member of the group: {aud}.",
                            "goals": ["Save time", "Feel in control"], "frustrations": ["Tools that assume a 9-to-5 life", "Complex onboarding"]},
                "key_messages": [f"Built specifically for {aud}", "Useful in under a minute", "Private, calm and distraction-free"]})
        elif agent == "copywriter":
            text = json.dumps({
                "product_name": name[:40], "headline": f"{name}, made for {aud}"[:100],
                "subheadline": f"{idea.rstrip('.')[:150]} - simple, fast and finally designed around you."[:215],
                "features": [
                    {"title": "Made for your routine", "description": f"Designed around how {aud} actually live and work."},
                    {"title": "Set up in a minute", "description": "No account maze. Start getting value immediately."},
                    {"title": "Calm by design", "description": "No noise, no guilt trips - just what you need."}],
                "faq": [
                    {"question": "Who is this for?", "answer": f"Anyone in the group: {aud}."},
                    {"question": "Is it free to try?", "answer": "Join the waitlist and be first to get early access."},
                    {"question": "How is my data handled?", "answer": "We collect the minimum and never sell it."}],
                "cta": {"label": "Get early access", "supporting_text": "Join the waitlist - we will email you the moment we launch."}})
        elif agent == "designer":
            text = json.dumps({
                "palette": {"background": "#0f172a", "surface": "#1e293b", "text": "#f8fafc", "muted_text": "#cbd5e1",
                            "primary": "#38bdf8", "primary_text": "#0f172a", "accent": "#fbbf24"},
                "fonts": {"heading": "'Trebuchet MS', 'Segoe UI', Arial, sans-serif", "body": "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif"},
                "layout_style": "minimal"})
        elif agent == "engineer":
            blob = _all_text(messages)
            m = re.search(r"INPUT_JSON:\s*(\{.*\})", blob)
            page = build_page(json.loads(m.group(1)))
            fx = re.search(r"FIXES \(apply all, keep everything else unchanged\):\n(.*?)\nCURRENT_HTML:", blob, re.S)
            notes = re.findall(r"^- (.+)$", fx.group(1), re.M) if fx else []
            if notes:  # mock only: make a requested revision visible so the feature can be demoed offline
                page = page.replace("</header>", f'<div class="wrap"><p class="sub" id="revision-note">Revision applied: {html.escape(notes[0])}</p></div></header>', 1)
            text = "```html\n" + page + "\n```"
        elif agent == "critic":
            text = json.dumps({"summary": "Automated checks found issues to fix.", "fixes": [
                {"priority": 1, "agent": "engineer", "instruction": "Fix every failed check listed in the report."}]})
        elif agent == "panel":
            text = json.dumps({
                "reactions": [
                    {"persona": "Target user", "score": 8, "first_impression": f"Clear and made for me: {aud}.", "top_objection": "I want to see how it works before I sign up.", "would_sign_up": True},
                    {"persona": "The Skeptic", "score": 6, "first_impression": "Sounds nice, but I have heard big promises before.", "top_objection": "There is no proof or concrete example on the page.", "would_sign_up": False},
                    {"persona": "The Busy Decision-maker", "score": 8, "first_impression": "I understood it in a few seconds.", "top_objection": "Not sure what happens after I click the button.", "would_sign_up": True},
                    {"persona": "The Budget-Conscious User", "score": 7, "first_impression": "Looks simple enough to try.", "top_objection": "Pricing is not mentioned.", "would_sign_up": True}],
                "summary": "Clear positioning; the main gap is proof and what happens next.",
                "suggested_fix": "Add a one-line 'how it works' under the headline and say what happens after sign-up.",
                "suggested_target": "copy"})
        elif agent == "launcher":
            text = json.dumps({
                "social_posts": [
                    {"platform": "X", "text": f"Meet {name}: {idea.rstrip('.')}. Early access is open."},
                    {"platform": "LinkedIn", "text": f"We built {name} for {aud}. Here is why - and how to get in early."},
                    {"platform": "Instagram", "text": f"{name} is live. Built for {aud}. Link in bio."}],
                "email": {"subject": f"{name} is live", "body": f"Hi!\n\n{name} - {idea.rstrip('.')} - is now live.\nTake a look and tell us what you think.\n\nThe {name} team"}})
        else:
            text = "{}" if json_mode else "OK"

        approx = lambda s: max(1, len(s) // 4)  # noqa: E731
        usage = Usage(approx(_all_text(messages)), approx(text), approx(_all_text(messages)) + approx(text))
        return LLMResult(text, usage, model, calls, raw or {"role": "assistant", "content": text})
