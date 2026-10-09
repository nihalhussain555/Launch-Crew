"""Deterministic offline provider (MOCK_LLM=true). Returns schema-valid output for every agent,
so the full pipeline (including the Playwright critic and deploy gate) works with no API keys.

Revisions go through app.llm.mock_edits, which reads the FIXES / CURRENT_JSON / CURRENT_HTML
blocks and applies the requested change mechanically, so an edit visibly alters the page offline."""
from __future__ import annotations

import html
import json
import re

from app.agents import variants
from app.llm import mock_edits as edits
from app.llm.client import LLMResult, ToolCall, Usage
from app.utils.color import mix

STOP = {"a", "an", "the", "for", "to", "of", "that", "and", "with", "who", "in", "on", "my", "your", "app", "tool"}


def _all_text(messages: list[dict]) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages)


def _idea(messages: list[dict]) -> str:
    m = re.search(r"IDEA:\s*(.+)", _all_text(messages))
    return (m.group(1).strip() if m else "A helpful product")[:200]


def _direction_from(blob: str) -> dict:
    """The DESIGN_DIRECTION block from an agent prompt, or the fallback direction."""
    m = re.search(r"DESIGN_DIRECTION: (\{.*\})[ \t]*$", blob, re.M)
    return json.loads(m.group(1)) if m else variants.fallback_dict()


def _name(idea: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+", idea) if w.lower() not in STOP]
    return " ".join(w.capitalize() for w in words[:2]) or "Launchly"


def _audience(idea: str) -> str:
    m = re.search(r"\bfor\s+(.+)$", idea, re.I)
    return m.group(1).strip().rstrip(".") if m else "busy people"


def _esc(v: str) -> str:
    return html.escape(str(v), quote=True)


_BASE_CSS = """
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font-family:__body__;line-height:1.65;font-size:17px;overflow-wrap:anywhere}
.wrap{max-width:__width__;margin:0 auto;padding:0 20px}
h1{font-family:__heading__;font-size:clamp(31px,6vw,54px);line-height:1.12;margin:14px 0;letter-spacing:__track__}
h2{font-family:__heading__;font-size:clamp(24px,4.4vw,34px);margin:0 0 22px;line-height:1.2}
h3{font-family:__heading__;margin:0 0 8px;font-size:19px}
p{margin:0 0 14px}
.sub{color:var(--muted);font-size:clamp(17px,2.6vw,21px);max-width:60ch}
.kicker{display:inline-block;font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}
a{color:var(--primary)}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:0 26px;border:0;border-radius:var(--radius);background:var(--primary);color:var(--on-primary);font-size:17px;font-weight:700;text-decoration:none;cursor:pointer;font-family:__body__}
section{padding:__sectionpad__ 0}
header{padding:__sectionpad__ 0 __halfpad__}
nav{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:10px 0}
nav .brand{font-family:__heading__;font-weight:800;font-size:19px;margin-right:auto;color:var(--text)}
nav a{display:inline-flex;align-items:center;min-height:44px;padding:0 14px;color:var(--muted);text-decoration:none;font-size:15px}
nav a:hover{color:var(--text)}
.card{background:var(--surface);border-radius:var(--radius);padding:22px}
.card h3{color:var(--text)}
.card p{margin:0;color:var(--muted)}
input{min-height:48px;min-width:0;flex:1 1 220px;max-width:340px;padding:0 16px;border-radius:var(--radius);border:2px solid var(--muted);background:var(--surface);color:var(--text);font-size:17px}
.signup{display:flex;flex-wrap:wrap;gap:12px;justify-content:__ctaalign__;margin-top:18px}
#msg{min-height:28px;color:var(--accent);font-weight:600}
footer{padding:30px 0;color:var(--muted);font-size:15px;text-align:center;border-top:1px solid var(--line)}
details{background:var(--surface);border-radius:var(--radius);margin-bottom:12px;padding:0 20px}
summary{min-height:48px;display:flex;align-items:center;cursor:pointer;font-weight:600}
details p{color:var(--muted);margin:12px 0 16px}
.hero-art{display:flex;align-items:center;justify-content:center;min-height:220px}
.hero-art .rings{position:relative;width:210px;height:210px;flex:none;max-width:100%}
.hero-art .rings i{position:absolute;inset:0;border:2px solid var(--primary);border-radius:50%;opacity:.55}
.hero-art .rings i:nth-child(2){inset:26px;border-color:var(--accent)}
.hero-art .rings i:nth-child(3){inset:64px;background:var(--primary);border:0;opacity:1;border-radius:__artradious__}
@media (max-width:719px){.hero-grid,.rail-grid{grid-template-columns:1fr!important;gap:26px!important}.rail-grid .rail{border:0;padding:0 0 16px}h1{letter-spacing:0}}
"""

_HERO_CSS = {
    "split": """
.hero-grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr);gap:40px;align-items:center}
""",
    "centered": """
#hero{text-align:center}
#hero .wrap>div{margin:0 auto}
#hero .sub{margin-left:auto;margin-right:auto}
#hero .btnrow{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:22px}
""",
    "band": """
#hero{background:var(--band);border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:__bandpad__ 0}
#hero h1{max-width:18ch}
#hero .rule{width:64px;height:3px;background:var(--accent);margin:18px 0 0}
""",
    "rail": """
.rail-grid{display:grid;grid-template-columns:210px minmax(0,1fr);gap:44px;align-items:start}
.rail-grid .rail nav{flex-direction:column;align-items:flex-start;gap:2px}
.rail-grid .rail nav a{width:100%;justify-content:flex-start}
.rail-grid .rail .brand{display:block;font-family:__heading__;font-weight:800;font-size:20px;margin:0 0 10px}
""",
}

_FEATURE_CSS = {
    "grid": """
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}
""",
    "numbered": """
.fnum{list-style:none;margin:0;padding:0;counter-reset:step}
.fnum li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:20px;align-items:start;padding:20px 0;border-top:1px solid var(--line)}
.fnum li:last-child{border-bottom:1px solid var(--line)}
.fnum li::before{counter-increment:step;content:counter(step,decimal-leading-zero);font-family:__heading__;font-size:34px;line-height:1;color:var(--accent)}
.fnum p{margin:0;color:var(--muted)}
.fnum h3{margin:0 0 6px}
@media (max-width:520px){.fnum li{grid-template-columns:minmax(0,1fr);gap:6px}}
""",
    "checklist": """
.fcheck{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.fcheck li{background:var(--surface);border-radius:var(--radius);padding:18px 18px 18px 52px;position:relative}
.fcheck li::before{content:"";position:absolute;left:18px;top:24px;width:14px;height:8px;border:3px solid var(--primary);border-top:0;border-right:0;transform:rotate(-45deg)}
.fcheck p{margin:0;color:var(--muted)}
""",
    "bento": """
.fbento{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}
.fbento .card:first-child{grid-row:span 1}
@media (min-width:720px){.fbento{grid-template-columns:repeat(2,minmax(0,1fr))}.fbento .card:first-child{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px 32px;align-items:center}.fbento .card:first-child p{margin:0}}
""",
}

_MOTIF_CSS = {
    "rules": """
h2{border-bottom:1px solid var(--line);padding-bottom:12px}
section{border-top:0}
""",
    "glow": """
.card,.fcheck li,details{box-shadow:0 0 0 1px var(--line),0 12px 32px rgba(0,0,0,.10)}
""",
    "pills": """
h2{display:inline-block;background:var(--band);padding:6px 18px;border-radius:999px;font-size:clamp(20px,3.4vw,26px)}
.card{border:1px solid var(--line)}
""",
    "circles": """
.fgrid .card{padding-top:46px;position:relative}
.fgrid .card::before{content:"";position:absolute;top:16px;left:22px;width:26px;height:26px;border-radius:50%;background:var(--primary)}
.fgrid .card:nth-child(2)::before{background:var(--accent)}
""",
}


def build_page(payload: dict) -> str:
    """Self-contained, accessible, responsive landing page used by the mock Engineer.

    The composition comes from the run's design direction (see app/agents/variants.py), so
    different runs get different heroes, section orders, feature layouts, motifs and palettes
    instead of one template over and over.
    """
    c, d = payload["copy"], payload["design"]
    direction = variants.from_dict(payload.get("direction"))
    p, f = d["palette"], d["fonts"]
    e = _esc

    band = mix(p["background"], p["surface"], 0.55)
    line = mix(p["background"], p["text"], 0.16)
    tokens = {
        "bg": p["background"], "surface": p["surface"], "text": p["text"], "muted": p["muted_text"],
        "primary": p["primary"], "onprimary": p["primary_text"], "accent": p["accent"],
        "body": f["body"], "heading": f["heading"], "band": band, "line": line,
        "radius": direction.radius,
        "width": "1040px", "sectionpad": "56px", "halfpad": "28px", "bandpad": "64px",
        "track": "-.02em", "artradious": direction.radius, "ctaalign": "center",
    }
    css = _BASE_CSS + _HERO_CSS[direction.hero] + _FEATURE_CSS[direction.features] + _MOTIF_CSS[direction.motif]
    for k, v in tokens.items():
        css = css.replace(f"__{k}__", v)
    css = f":root{{--bg:{tokens['bg']};--surface:{tokens['surface']};--text:{tokens['text']};" \
          f"--muted:{tokens['muted']};--primary:{tokens['primary']};--on-primary:{tokens['onprimary']};" \
          f"--accent:{tokens['accent']};--band:{band};--line:{line};--radius:{direction.radius}}}" + css

    nav = (f'<nav aria-label="Main"><span class="brand">{e(c["product_name"])}</span>'
           f'<a href="#features">Features</a><a href="#faq">FAQ</a><a href="#cta">{e(c["cta"]["label"])[:18]}</a></nav>')
    hero_copy = (f'<h1>{e(c["headline"])}</h1><p class="sub">{e(c["subheadline"])}</p>')
    cta_btn = f'<p><a class="btn" href="#cta">{e(c["cta"]["label"])}</a></p>'

    if direction.hero == "split":
        hero_inner = (f'<div class="hero-grid"><div>{nav}{hero_copy}{cta_btn}</div>'
                      f'<div class="hero-art"><div class="rings"><i></i><i></i><i></i></div></div></div>')
    elif direction.hero == "centered":
        hero_inner = f'{nav}{hero_copy}<div class="btnrow"><a class="btn" href="#cta">{e(c["cta"]["label"])}</a></div>'
    elif direction.hero == "band":
        hero_inner = (f'{nav}<span class="kicker">{e(c["product_name"])}</span>{hero_copy}'
                      f'<div class="rule"></div>{cta_btn}')
    else:  # rail
        hero_inner = (f'<div class="rail-grid"><aside class="rail">{nav}</aside>'
                      f'<div>{hero_copy}{cta_btn}</div></div>')

    feats = c["features"]
    if direction.features == "grid":
        features_body = ('<div class="fgrid">' + "".join(
            f'<article class="card"><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></article>' for x in feats)
            + "</div>")
    elif direction.features == "numbered":
        features_body = ('<ol class="fnum">' + "".join(
            f'<li><div><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></div></li>' for x in feats) + "</ol>")
    elif direction.features == "checklist":
        features_body = ('<ul class="fcheck">' + "".join(
            f'<li><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></li>' for x in feats) + "</ul>")
    else:  # bento
        features_body = ('<div class="fbento">' + "".join(
            f'<article class="card"><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></article>' for x in feats)
            + "</div>")

    faqs = "".join(f'<details><summary>{e(x["question"])}</summary><p>{e(x["answer"])}</p></details>' for x in c["faq"])
    form = (f'<form class="signup" id="signup" action="#">'
            f'<label for="email" style="position:absolute;left:-9999px">Email</label>'
            f'<input id="email" type="email" placeholder="you@example.com" required>'
            f'<button class="btn" type="submit">{e(c["cta"]["label"])}</button></form>'
            f'<p id="msg" role="status"></p>')

    sections = {
        "features": f'<section id="features"><div class="wrap"><h2>Why {e(c["product_name"])}</h2>{features_body}</div></section>',
        "faq": f'<section id="faq"><div class="wrap"><h2>Questions, answered</h2>{faqs}</div></section>',
        "cta": (f'<section id="cta"><div class="wrap"><h2>{e(c["cta"]["label"])}</h2>'
                f'<p class="sub" style="margin:0 auto">{e(c["cta"]["supporting_text"])}</p>{form}</div></section>'),
    }
    body = "".join(sections[name] for name in direction.order if name in sections)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c["product_name"])} - {e(c["headline"])}</title><style>{css}</style></head>
<body>
<header id="hero" class="hero hero-{direction.hero}"><div class="wrap">{hero_inner}</div></header>
<main>{body}</main>
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
            default = {
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
                "cta": {"label": "Get early access", "supporting_text": "Join the waitlist - we will email you the moment we launch."}}
            blob = _all_text(messages)
            current, fixes = edits.current_json(blob), edits.fixes_from(blob)
            text = json.dumps(edits.apply_copy(current, fixes) if current and fixes else default)
        elif agent == "designer":
            # The direction carries the run's palette/fonts; re-emitting it keeps designer and
            # Engineer agrees, and revisions reuse it instead of re-skinning the page.
            blob = _all_text(messages)
            direction = _direction_from(blob)
            design = {"palette": dict(direction["palette"]), "fonts": dict(direction["fonts"]),
                      "layout_style": direction["layout_style"]}
            current, fixes = edits.current_json(blob), edits.fixes_from(blob)
            text = json.dumps(edits.apply_design(current, fixes) if current and fixes else design)
        elif agent == "engineer":
            blob = _all_text(messages)
            m = re.search(r"INPUT_JSON:\s*(\{[^\n]*)", blob)
            page = build_page(json.loads(m.group(1)))
            fixes, previous = edits.fixes_from(blob), edits.current_html(blob)
            if fixes and previous:      # patch mode: the page is the one the user is looking at
                page = edits.apply_page(page, previous, fixes)
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
