"""Deterministic offline provider (MOCK_LLM=true). Returns schema-valid output for every agent,
so the full pipeline (including the Playwright critic and deploy gate) works with no API keys.

The page builder below is the offline renderer for the style system (app/agents/styles.py): each of
the 12 styles composes a different hero, navigation, feature layout, motif and token set, so a run in
"Brutalist & bold" and a run in "Luxury & premium" share nothing but the copy. Sections the brief
adds (testimonials, pricing, gallery, team, contact) are rendered here too, each labelled as sample
content when the crew had nothing real to put in it.

Revisions go through app.llm.mock_edits, which reads the FIXES / CURRENT_JSON / CURRENT_HTML blocks
and applies the requested change mechanically, so an edit visibly alters the page offline.
"""
from __future__ import annotations

import html
import json
import re

from app.agents import variants
from app.llm import mock_edits as edits
from app.llm.client import LLMResult, ToolCall, Usage
from app.utils.color import mix

STOP = {"a", "an", "the", "for", "to", "of", "that", "and", "with", "who", "in", "on", "my", "your", "app", "tool"}

# Every token the page is drawn with: token name -> (placeholder in the CSS templates below, the CSS
# custom property the page declares). `app/agents/styles.py` supplies the layout ones and
# `app/agents/theme.py` supplies the appearance ones under the same names, so a theme is one block of
# `:root` variables rather than a patch applied to every element on the page.
_TOKEN_KEYS = {
    "width": ("width", "--wrap"), "pad": ("sectionpad", "--pad"), "pad_half": ("halfpad", "--pad-half"),
    "hero_pad": ("heropad", "--hero-pad"), "gap": ("gap", "--gap"), "base": ("base", "--base"),
    "lh": ("lh", "--lh"), "h1": ("h1", "--h1"), "h2": ("h2", "--h2"), "h3": ("h3", "--h3"),
    "small": ("small", "--small"), "track": ("track", "--track"), "h1_case": ("h1case", "--h1-case"),
    "h2_case": ("h2case", "--h2-case"), "label_case": ("labelcase", "--label-case"),
    "label_track": ("labeltrack", "--label-track"), "btn_case": ("btncase", "--btn-case"),
    "btn_pad": ("btnpad", "--btn-pad"), "btn_min": ("btnmin", "--btn-min"), "rule": ("rule", "--rule"),
    "cta_align": ("ctaalign", "--cta-align"), "art_radius": ("artradious", "--art-radius"),
}
# Theme tokens the CSS reaches for directly, without a placeholder of their own. The theme's border
# colour writes `--line`, the hairline every rule already reads, rather than a variable of its own that
# each component would have to be patched to use; `--border` stays an alias of it.
_THEME_VARS = {
    "shadow": "--shadow", "shadow_strong": "--shadow-strong", "radius": "--radius",
    "btn_bg": "--btn-bg", "btn_fg": "--btn-fg", "btn_border": "--btn-border",
    "btn_radius": "--btn-radius", "btn_shadow": "--btn-shadow", "card_bg": "--card-bg",
    "card_border": "--card-border", "card_shadow": "--card-shadow", "card_blur": "--card-blur",
    "card_radius": "--card-radius", "card_pad": "--card-pad", "secondary": "--secondary",
    "secondary_text": "--on-secondary", "border": "--line", "band": "--band",
    "focus_ring": "--focus",
}
# An unthemed page renders exactly what it rendered before the customizer existed, so these defaults are
# its old literals; a theme replaces them one property at a time.
_VAR_DEFAULTS = {"--shadow": "none", "--shadow-strong": "none", "--radius": "12px",
                 "--btn-bg": "var(--primary)", "--btn-fg": "var(--on-primary)",
                 "--btn-border": "0 solid transparent", "--btn-radius": "var(--radius)",
                 "--btn-shadow": "none", "--card-bg": "var(--surface)", "--card-border": "0 solid transparent",
                 "--card-shadow": "none", "--card-blur": "none", "--card-radius": "var(--radius)",
                 "--card-pad": "22px", "--secondary": "var(--accent)", "--on-secondary": "var(--text)",
                 "--border": "var(--line)", "--focus": "var(--primary)", "--band": "var(--surface)"}

# The palette's seven colours and the custom properties each one is declared under. Public, together with
# `token_variables()` below, because the theme editor patches the very same properties this builder
# writes: one vocabulary, two readers, so a renamed variable cannot leave the editor writing a name no
# rule reads.
PALETTE_VARS = {"background": "--bg", "surface": "--surface", "text": "--text", "muted_text": "--muted",
                "primary": "--primary", "primary_text": "--on-primary", "accent": "--accent"}


def token_variables() -> dict[str, str]:
    """Every token key that becomes a custom property here, mapped to its variable name."""
    out = {key: var for key, (_placeholder, var) in _TOKEN_KEYS.items()}
    out.update(_THEME_VARS)
    return out


def _all_text(messages: list[dict]) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages)


def _idea(messages: list[dict]) -> str:
    m = re.search(r"IDEA:\s*(.+)", _all_text(messages))
    return (m.group(1).strip() if m else "A helpful product")[:200]


def _direction_from(blob: str) -> dict:
    """The DESIGN_DIRECTION block from an agent prompt, or the fallback direction."""
    m = re.search(r"DESIGN_DIRECTION: (\{.*\})[ \t]*$", blob, re.M)
    return json.loads(m.group(1)) if m else variants.fallback_dict()


def _sections_from(blob: str) -> list[str]:
    """The SECTIONS line the Copywriter is given: the sections this page will actually render."""
    m = re.search(r"^SECTIONS:\s*(.+)$", blob, re.M)
    return [s.strip().lower() for s in m.group(1).split(",")] if m else []


def _name(idea: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+", idea) if w.lower() not in STOP]
    return " ".join(w.capitalize() for w in words[:2]) or "Launchly"


def _audience(idea: str) -> str:
    m = re.search(r"\bfor\s+(.+)$", idea, re.I)
    return m.group(1).strip().rstrip(".") if m else "busy people"


def _esc(v: str) -> str:
    return html.escape(str(v), quote=True)


# ------------------------------------------------------------------ stylesheet
_BASE_CSS = """
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font-family:__body__;line-height:__lh__;font-size:__base__;overflow-wrap:anywhere}
.wrap{max-width:__width__;margin:0 auto;padding:0 20px}
h1{font-family:__heading__;font-size:__h1__;line-height:1.12;margin:14px 0;letter-spacing:__track__;text-transform:__h1case__}
h2{font-family:__heading__;font-size:__h2__;margin:0 0 22px;line-height:1.2;letter-spacing:__track__;text-transform:__h2case__}
h3{font-family:__heading__;margin:0 0 8px;font-size:__h3__}
p{margin:0 0 14px}
.sub{color:var(--muted);font-size:clamp(17px,2.6vw,21px);max-width:60ch}
.kicker{display:inline-block;font-size:__small__;font-weight:700;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--accent)}
a{color:var(--primary)}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:__btnmin__;padding:__btnpad__;border:var(--btn-border);border-radius:var(--btn-radius);background:var(--btn-bg);color:var(--btn-fg);box-shadow:var(--btn-shadow);font-size:17px;font-weight:700;text-decoration:none;cursor:pointer;font-family:__body__;text-transform:__btncase__}
.ghost{display:inline-flex;align-items:center;justify-content:center;min-height:__btnmin__;padding:__btnpad__;border:2px solid var(--primary);border-radius:var(--btn-radius);background:transparent;color:var(--text);font-size:17px;font-weight:700;text-decoration:none}
.badge{display:inline-block;padding:6px 14px;border-radius:999px;background:var(--surface);border:1px solid var(--line);font-size:__small__;font-weight:700;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--text)}
.chip{display:inline-block;padding:6px 14px;border-radius:999px;background:var(--primary);color:var(--on-primary);font-size:__small__;font-weight:700}
section{padding:__sectionpad__ 0}
header{padding:__heropad__ 0 __halfpad__}
nav{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:10px 0}
nav .brand{font-family:__heading__;font-weight:800;font-size:19px;margin-right:auto;color:var(--text)}
nav a{display:inline-flex;align-items:center;min-height:44px;padding:0 14px;color:var(--muted);text-decoration:none;font-size:15px}
nav a:hover{color:var(--text)}
.card{background:var(--card-bg);border:var(--card-border);border-radius:var(--card-radius);box-shadow:var(--card-shadow);backdrop-filter:var(--card-blur);-webkit-backdrop-filter:var(--card-blur);padding:var(--card-pad)}
.card h3{color:var(--text)}
.card p{margin:0;color:var(--muted)}
input{min-height:48px;min-width:0;flex:1 1 220px;max-width:340px;padding:0 16px;border-radius:var(--radius);border:2px solid var(--muted);background:var(--surface);color:var(--text);font-size:17px}
.signup{display:flex;flex-wrap:wrap;gap:12px;justify-content:__ctaalign__;margin-top:18px}
#msg{min-height:28px;color:var(--accent);font-weight:600}
footer{padding:30px 0;color:var(--muted);font-size:15px;text-align:center;border-top:1px solid var(--line)}
details{background:var(--card-bg);border:var(--card-border);border-radius:var(--card-radius);margin-bottom:12px;padding:0 20px}
summary{min-height:48px;display:flex;align-items:center;cursor:pointer;font-weight:600}
details p{color:var(--muted);margin:12px 0 16px}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.hero-art{display:flex;align-items:center;justify-content:center;min-height:220px}
.hero-art .rings{position:relative;width:210px;height:210px;flex:none;max-width:100%}
.hero-art .rings i{position:absolute;inset:0;border:2px solid var(--primary);border-radius:50%;opacity:.55}
.hero-art .rings i:nth-child(2){inset:26px;border-color:var(--accent)}
.hero-art .rings i:nth-child(3){inset:64px;background:var(--primary);border:0;opacity:1;border-radius:__artradious__}
.sample{font-size:__small__;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--muted);margin:18px 0 0}
.sec-alt{background:var(--surface)}
.rows,.cols,.fduo,.fspot,.ftab,.flist{display:grid;gap:__gap__}
.tbody{padding:16px}
.ph{background:var(--band);border-radius:__artradious__;min-height:120px}
@media (max-width:860px){.hero-grid,.rail-grid,.cols,.hero-cols,.fduo,.fspot,.fprod,.ftiles,.plans,.quotes,.roles,.gtiles{grid-template-columns:1fr!important;gap:max(22px,var(--gap))!important}}
@media (max-width:719px){:root{--pad:calc(var(--pad-half) * 1.5);--hero-pad:calc(var(--pad-half) * 1.1)}.hero-grid,.rail-grid{grid-template-columns:1fr!important;gap:max(26px,var(--gap))!important}.rail-grid .rail{border:0;padding:0 0 16px}h1{letter-spacing:0}.flist .row,.ftab .row{grid-template-columns:minmax(0,1fr)!important;gap:6px!important}}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
"""

# ---------------------------------------------------------------- heroes (one per style)
_HERO_CSS = {
    "split": """
.hero-grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr);gap:40px;align-items:center}
""",
    "centered": """
#hero{text-align:center}
#hero .wrap>div{margin:0 auto}
#hero .sub{margin-left:auto;margin-right:auto}
#hero .btnrow{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:22px}
.btnrow .btn+.btn,.btnrow .btn+.ghost{margin-left:0}
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
    "showcase": """
#hero{text-align:center}
#hero .sub{margin:0 auto}
.win{background:var(--surface);border:1px solid var(--line);border-radius:__artradious__;box-shadow:0 20px 44px rgba(0,0,0,.12);margin:__gap__ auto 0;max-width:760px;text-align:left;padding:0 0 18px}
.win .chrome{display:flex;align-items:center;gap:8px;padding:14px 18px;border-bottom:1px solid var(--line)}
.win .chrome i{width:12px;height:12px;border-radius:50%;background:var(--primary);opacity:.7}
.win .chrome b{margin-left:auto;font-size:__small__;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--muted);font-weight:700}
.win .lines{display:grid;gap:12px;padding:18px}
.win .lines span{display:block;height:14px;border-radius:999px;background:var(--band)}
.win .lines span:nth-child(1){width:70%;height:26px}
.win .lines span:nth-child(3){width:88%}
.win .lines span:nth-child(4){width:52%}
""",
    "editorial": """
.hero-cols{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,.65fr);gap:__gap__;align-items:start}
#hero h1{max-width:20ch}
.hero-meta{display:grid;gap:14px;padding-top:10px;border-top:1px solid var(--line)}
.hero-meta div{display:grid;gap:4px}
.hero-meta b{font-size:__small__;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--muted);font-weight:700}
.hero-meta span{font-family:__heading__;font-size:__h3__}
""",
    "terminal": """
.term{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:__halfpad__;font-family:__heading__;margin-bottom:__gap__}
.term .ln{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;font-size:__small__;letter-spacing:__labeltrack__;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
.term .ln b{color:var(--accent);font-weight:700}
.term .ln:last-child{margin:0}
#hero h1{margin-top:0}
""",
    "marquee": """
#hero h1{max-width:14ch;margin:12px 0 18px}
#hero .lede{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:__gap__;align-items:end}
@media (max-width:860px){#hero .lede{grid-template-columns:1fr}}
""",
    "storefront": """
.promo{display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between;align-items:center;background:var(--primary);color:var(--on-primary);border-radius:__artradious__;padding:14px 20px;font-weight:700;margin-bottom:__gap__}
.promo span{font-size:__small__;letter-spacing:__labeltrack__;text-transform:uppercase;font-weight:700}
.cats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:__gap__}
.cats .cat{background:var(--surface);border:1px solid var(--line);border-radius:__artradious__;padding:16px}
.cats .cat b{display:block;font-size:__small__;letter-spacing:__labeltrack__;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.cats .cat span{font-family:__heading__;font-size:__h3__}
""",
    "masthead": """
.mast{text-align:center;border-top:__rule__ solid var(--text);border-bottom:1px solid var(--line);padding:__halfpad__ 0 __gap__}
.mast .brandbig{display:block;font-family:__heading__;font-weight:800;font-size:clamp(26px,4.6vw,44px);letter-spacing:__labeltrack__;text-transform:__labelcase__}
#hero{text-align:center}
#hero .sub{margin:0 auto}
""",
    "poster": """
.poster{background:var(--surface);border:__rule__ solid var(--text);box-shadow:14px 14px 0 var(--band);padding:__halfpad__}
.poster .kicker{border:__rule__ solid var(--text);padding:6px 12px;color:var(--on-primary);background:var(--primary)}
.poster h1{margin-top:6px}
.poster .tag{display:flex;flex-wrap:wrap;gap:10px;margin-top:__gap__}
.poster .tag em{font-style:normal;font-size:__small__;font-weight:700;letter-spacing:__labeltrack__;text-transform:uppercase;border:__rule__ solid var(--text);padding:6px 12px}
""",
    "orb": """
#hero{position:relative;overflow:hidden;padding:__heropad__ 0}
.orb{position:absolute;border-radius:50%;filter:blur(2px);opacity:.55;width:340px;height:340px;pointer-events:none;background:radial-gradient(circle at 35% 35%, var(--primary), transparent 68%)}
.orb.two{right:-40px;top:120px;width:260px;height:260px;background:radial-gradient(circle at 35% 35%, var(--accent), transparent 68%)}
#hero .wrap{position:relative}
.panel{background:var(--surface);border-radius:__artradious__;padding:__halfpad__;box-shadow:0 24px 60px rgba(0,0,0,.35)}
#hero .sub{margin:0 auto}
#hero{text-align:center}
""",
}

# ---------------------------------------------------------------- navigation (one per style)
_NAV_CSS = {
    "rail-left": "",
    "top-links": "",
    "wide-labels": """
nav.v-wide{justify-content:flex-end}
nav.v-wide .brand{margin-right:auto}
nav.v-wide a{text-transform:uppercase;font-size:__small__;letter-spacing:__labeltrack__;padding:0 16px}
""",
    "pill-bar": """
nav.v-pill{background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:6px 8px;width:max-content;max-width:100%;margin-bottom:__gap__}
nav.v-pill a{border-radius:999px}
nav.v-pill .brand{margin-right:14px;padding-left:8px}
""",
    "index-list": """
nav.v-index ol{list-style:none;display:flex;flex-wrap:wrap;gap:__gap__;margin:0;padding:0;counter-reset:idx}
nav.v-index ol li{display:flex}
nav.v-index ol a{padding:0}
nav.v-index ol a::before{counter-increment:idx;content:counter(idx,decimal-leading-zero) " ";color:var(--accent);font-weight:700;font-size:__small__;letter-spacing:__labeltrack__}
""",
    "underline-bar": """
nav.v-underline{border-bottom:1px solid var(--line);padding-bottom:0}
nav.v-underline a{border-bottom:__rule__ solid var(--primary);border-radius:0;margin-bottom:-1px}
""",
    "bracket": """
nav.v-bracket a{text-transform:uppercase;font-size:__small__;letter-spacing:__labeltrack__}
nav.v-bracket a::before{content:"[";color:var(--accent);margin-right:6px}
nav.v-bracket a::after{content:"]";color:var(--accent);margin-left:6px}
""",
    "store-bar": """
nav.v-store{flex-direction:column;align-items:stretch;gap:10px}
nav.v-store .grp{display:flex;flex-wrap:wrap;align-items:center;gap:6px;width:100%}
nav.v-store .catline{display:flex;flex-wrap:wrap;gap:8px}
nav.v-store .catline em{font-style:normal;font-size:__small__;font-weight:700;letter-spacing:__labeltrack__;text-transform:uppercase;background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:8px 14px;color:var(--text)}
""",
    "masthead-nav": """
nav.v-mast{justify-content:center;text-align:center;border-top:1px solid var(--line);margin-top:__gap__;padding-top:__gap__}
nav.v-mast .brand{display:none}
nav.v-mast a{text-transform:uppercase;font-size:__small__;letter-spacing:__labeltrack__}
nav.v-mast a+a{border-left:1px solid var(--line);border-radius:0}
""",
    "mono-strip": """
nav.v-mono{border-top:__rule__ solid var(--text);border-bottom:__rule__ solid var(--text);justify-content:space-between;padding:12px 0}
nav.v-mono a{font-size:__small__;letter-spacing:__labeltrack__;text-transform:uppercase;color:var(--text)}
nav.v-mono .brand{font-size:__small__;letter-spacing:__labeltrack__;text-transform:uppercase}
""",
    "plain-brand": """
nav.v-plain a{margin-left:auto}
""",
    "split-links": """
nav.v-split{justify-content:space-between}
nav.v-split .brand{margin-right:0}
nav.v-split .grp{display:flex;flex-wrap:wrap;gap:6px}
nav.v-split .grp a+a{border-left:1px solid var(--line);border-radius:0}
""",
}

# ---------------------------------------------------------------- feature layouts (one per style)
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
    "plain-list": """
.flist .row{display:grid;grid-template-columns:minmax(0,240px) minmax(0,1fr);gap:__gap__;padding:__halfpad__ 0;border-top:1px solid var(--line)}
.flist .row:last-child{border-bottom:1px solid var(--line)}
.flist p{margin:0;color:var(--muted)}
.flist h3{margin:0}
""",
    "index-table": """
.ftab .row{display:grid;grid-template-columns:56px minmax(0,220px) minmax(0,1fr);gap:__gap__;align-items:baseline;padding:__halfpad__ 0;border-top:1px solid var(--line)}
.ftab .row:last-child{border-bottom:1px solid var(--line)}
.ftab .no{font-size:__small__;letter-spacing:__labeltrack__;text-transform:uppercase;color:var(--muted);font-weight:700}
.ftab h3{margin:0}
.ftab p{margin:0;color:var(--muted)}
""",
    "tiles": """
.ftiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:__gap__}
.ftiles .card{border-radius:__artradious__;padding:18px;display:grid;gap:10px;align-content:space-between;min-height:160px}
.ftiles .card .kicker{color:var(--muted)}
.ftiles .card h3{margin:0}
""",
    "spotlight": """
.fspot .lead{background:var(--surface);border-radius:__artradious__;padding:__halfpad__}
.fspot .lead h3{font-size:__h2__;margin:0 0 10px}
.fspot .rest{display:grid;gap:0}
.fspot .rest .row{display:grid;grid-template-columns:minmax(0,240px) minmax(0,1fr);gap:__gap__;padding:18px 0;border-top:1px solid var(--line)}
.fspot .rest h3{margin:0}
.fspot .rest p{margin:0;color:var(--muted)}
@media (max-width:860px){.fspot .rest .row{grid-template-columns:minmax(0,1fr);gap:6px}}
""",
    "products": """
.fprod{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:__gap__}
.fprod .card{padding:0;overflow:hidden;border:1px solid var(--line);border-radius:__artradious__;display:grid}
.fprod .card .tbody{display:grid;gap:10px}
.fprod .card h3{margin:0}
.fprod .card p{margin:0;color:var(--muted)}
""",
    "articles": """
.farts .art{padding:__halfpad__ 0;border-bottom:1px solid var(--line);display:grid;gap:8px}
.farts .art:first-child{border-top:1px solid var(--line)}
.farts .art h3{margin:0;font-size:__h2__}
.farts .art p{margin:0;color:var(--muted)}
""",
    "manifest": """
.fman{list-style:none;margin:0;padding:0;counter-reset:m}
.fman li{counter-increment:m;display:grid;grid-template-columns:64px minmax(0,1fr);gap:__gap__;padding:__halfpad__ 0;border-top:__rule__ solid var(--text)}
.fman li:last-child{border-bottom:__rule__ solid var(--text)}
.fman li::before{content:counter(m,decimal-leading-zero);font-family:__heading__;font-size:__h2__;line-height:1}
.fman h3{margin:0 0 8px;text-transform:uppercase;letter-spacing:__labeltrack__}
.fman p{margin:0;color:var(--muted)}
@media (max-width:520px){.fman li{grid-template-columns:minmax(0,1fr);gap:6px}}
""",
    "duo": """
.fduo{grid-template-columns:minmax(0,1.2fr) minmax(0,.8fr);align-items:start}
.fduo .tall{background:var(--surface);border-radius:__artradious__;padding:__halfpad__;min-height:260px;display:grid;align-content:space-between}
.fduo .stack{display:grid;gap:__gap__}
.fduo .stack .card{border-radius:__artradious__}
.fduo h3{margin:0 0 8px}
.fduo p{margin:0;color:var(--muted)}
""",
}

# ---------------------------------------------------------------- motifs (decoration only)
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
.fgrid .card,.ftiles .card,.rows .card{padding-top:46px;position:relative}
.fgrid .card::before,.ftiles .card::before,.rows .card::before{content:"";position:absolute;top:16px;left:22px;width:26px;height:26px;border-radius:50%;background:var(--primary)}
.fgrid .card:nth-child(2)::before,.ftiles .card:nth-child(2)::before,.rows .card:nth-child(2)::before{background:var(--accent)}
""",
    "hairline-caps": """
h2{border-top:1px solid var(--line);padding-top:14px;text-transform:uppercase;letter-spacing:__labeltrack__;font-weight:400}
.sec-alt{background:transparent;border-left:1px solid var(--line);padding-left:__halfpad__}
""",
    "blur": """
.card,.win,.poster,.panel{position:relative;overflow:hidden}
.card::after,.win::after,.panel::after{content:"";position:absolute;inset:0;background:linear-gradient(160deg,rgba(255,255,255,.34),rgba(255,255,255,0) 58%);pointer-events:none}
#hero{backdrop-filter:blur(2px)}
""",
    "gridlines": """
section h2::before,.sec-head::before{content:"";display:block;width:100%;height:22px;background:repeating-linear-gradient(90deg,var(--line) 0 1px,transparent 1px 28px);margin-bottom:12px}
""",
    "depth": """
.card,.win,.panel,details,.fspot .lead{box-shadow:0 1px 2px rgba(15,23,42,.08),0 10px 24px rgba(15,23,42,.10)}
.btn:hover{transform:translateY(-1px)}
""",
    "ticker": """
.ticker{overflow:hidden;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:14px 0;margin:__halfpad__ 0 0}
.ticker .strip{display:flex;flex-wrap:nowrap;gap:28px;white-space:nowrap;color:var(--muted);font-size:__small__;letter-spacing:__labeltrack__;text-transform:uppercase;font-weight:700}
""",
    "frame": """
.card,.win,.panel,details,.quotes .tcard{border:1px solid var(--line);outline:1px solid var(--line);outline-offset:6px;box-shadow:none}
""",
    "outline-thick": """
.card,.win,.poster,.panel,details,.plans .plan,.badge,.chip{border:__rule__ solid var(--text)!important;border-radius:0!important;box-shadow:8px 8px 0 var(--text)!important}
h2{border-bottom:__rule__ solid var(--text);padding-bottom:10px}
.btn{border-radius:0!important;box-shadow:6px 6px 0 var(--text)}
""",
    "orbfield": """
.sec-alt .card,.panel{box-shadow:0 18px 40px rgba(0,0,0,.28)}
.btn{box-shadow:0 12px 30px rgba(0,0,0,.35)}
""",
}

# ---------------------------------------------------------------- extra sections
_EXTRA_CSS = """
.quotes{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:__gap__}
.quotes .tcard{background:var(--card-bg);border:var(--card-border);border-radius:__artradious__;box-shadow:var(--card-shadow);backdrop-filter:var(--card-blur);padding:__halfpad__;display:grid;gap:12px}
.quotes blockquote{margin:0;font-size:__h3__;color:var(--text)}
.quotes figcaption{font-size:__small__;letter-spacing:__labeltrack__;text-transform:uppercase;color:var(--muted);font-weight:700}
.plans{--card-border:1px solid var(--line);display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:__gap__;align-items:start}
.plans .plan{background:var(--card-bg);border:var(--card-border);border-radius:var(--card-radius);box-shadow:var(--card-shadow);padding:__halfpad__;display:grid;gap:12px}
.plans .plan.feat{border:__rule__ solid var(--primary)}
.plans h3{margin:0}
.plans .price{font-family:__heading__;font-size:__h2__}
.plans ul{margin:0;padding-left:20px;color:var(--muted)}
.plans .blurb{margin:0;color:var(--muted)}
.gtiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:__gap__}
.gtiles figure{margin:0;display:grid;gap:10px}
.gtiles figcaption{display:grid;gap:4px}
.gtiles b{font-family:__heading__;font-size:__h3__}
.gtiles span{font-size:__small__;color:var(--muted)}
.roles{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:__gap__}
.roles .rcard{background:var(--card-bg);border:var(--card-border);border-radius:var(--card-radius);box-shadow:var(--card-shadow);padding:__halfpad__;display:grid;gap:10px}
.roles .rcard p{margin:0;color:var(--muted)}
.paths{display:grid;gap:14px;max-width:640px}
.paths div{display:grid;gap:4px;padding-bottom:14px;border-bottom:1px solid var(--line)}
.paths b{font-size:__small__;letter-spacing:__labeltrack__;text-transform:uppercase;color:var(--muted);font-weight:700}
.paths span{font-family:__heading__;font-size:__h3__}
"""


# ------------------------------------------------------------------ markup builders
def _style_tokens(direction: variants.DesignDirection) -> dict:
    """Placeholder -> the custom property that carries it.

    The templates below keep their `__token__` literals, but each one is filled with a `var()` reference
    instead of the raw value: the numbers live in one `:root` block, so restyling the whole page is a
    token edit rather than an edit per element.
    """
    out = {placeholder: f"var({var})" for _key, (placeholder, var) in _TOKEN_KEYS.items()}
    out["bandpad"] = out["heropad"]
    return out


def is_css(value: str) -> bool:
    """A token that reached run state has to survive Mongo and a browser: plain CSS, no braces."""
    return bool(value) and len(value) <= 160 and not re.search(r"[{}<>;]|url\(|expression|javascript", value)


def root_vars(direction: variants.DesignDirection, p: dict, band: str, line: str) -> dict:
    """Every custom property the page declares, in declaration order.

    Colours come from the run's palette (already WCAG-checked by the Designer's schema), spacing and
    type from the direction's token map (the style's own values with this run's theme applied), and the
    treatment of buttons, cards and shadows from the theme - or from the unthemed defaults, which are
    the values this builder used before the customizer existed.
    """
    vars_ = {"--bg": p["background"], "--surface": p["surface"], "--text": p["text"],
             "--muted": p["muted_text"], "--primary": p["primary"], "--on-primary": p["primary_text"],
             "--accent": p["accent"], "--band": band, "--line": line}
    vars_.update(_VAR_DEFAULTS)
    vars_["--band"] = band
    tokens = direction.tokens
    for key, (_placeholder, var) in _TOKEN_KEYS.items():
        value = str(tokens.get(key) or variants.LEGACY_TOKENS.get(key) or "")
        if is_css(value):
            vars_[var] = value
    for key, var in _THEME_VARS.items():
        value = str(tokens.get(key) or "")
        if is_css(value):
            vars_[var] = value
    if not is_css(str(tokens.get("radius") or "")):
        vars_["--radius"] = direction.radius
    return {k: v for k, v in vars_.items() if is_css(v)}


_LABELS = {"features": "Features", "testimonials": "Reviews", "pricing": "Pricing", "gallery": "Work",
           "team": "Team", "faq": "FAQ", "contact": "Contact", "cta": "Get started"}
_NAV_CLASS = {"wide-labels": "v-wide", "pill-bar": "v-pill", "index-list": "v-index",
              "underline-bar": "v-underline", "bracket": "v-bracket", "store-bar": "v-store",
              "masthead-nav": "v-mast", "mono-strip": "v-mono", "plain-brand": "v-plain",
              "split-links": "v-split"}


def _nav_html(direction: variants.DesignDirection, name: str, ids: list[str]) -> str:
    """The style's navigation: the same real targets, arranged differently."""
    links = [f'<a href="#{i}">{_esc(_LABELS.get(i, i.capitalize()))}</a>' for i in ids if i != "hero"]
    kind, brand = direction.nav, f'<span class="brand">{_esc(name)}</span>'
    cls = _NAV_CLASS.get(kind, "")
    attrs = f' class="{cls}"' if cls else ""
    if kind == "plain-brand":
        return f'<nav aria-label="Main"{attrs}>{brand}{links[0] if links else ""}</nav>'
    if kind == "index-list":
        return f'<nav aria-label="Main"{attrs}>{brand}<ol>{"".join(f"<li>{a}</li>" for a in links)}</ol></nav>'
    if kind == "store-bar":
        cats = "".join(f'<em>{_esc(_LABELS.get(i, i.capitalize()))}</em>'
                       for i in ids if i in ("gallery", "pricing", "contact"))
        return (f'<nav aria-label="Main"{attrs}><span class="grp">{brand}{"".join(links)}</span>'
                f'<span class="catline">{cats}</span></nav>')
    if kind == "split-links":
        return f'<nav aria-label="Main"{attrs}>{brand}<span class="grp">{"".join(links)}</span></nav>'
    return f'<nav aria-label="Main"{attrs}>{brand}{"".join(links)}</nav>'


def _hero_html(direction: variants.DesignDirection, c: dict, nav: str) -> str:
    e, hero = _esc, direction.hero
    headline = f'<h1>{e(c["headline"])}</h1>'
    sub = f'<p class="sub">{e(c["subheadline"])}</p>'
    cta = f'<p><a class="btn" href="#cta">{e(c["cta"]["label"])}</a></p>'
    name = e(c["product_name"])
    tagline = f'<span class="kicker">{name}</span>'

    if hero == "split":
        return (f'<div class="hero-grid"><div>{nav}{headline}{sub}{cta}</div>'
                f'<div class="hero-art"><div class="rings"><i></i><i></i><i></i></div></div></div>')
    if hero == "centered":
        badge = f'<span class="badge">{name}</span>'
        return (f'<div>{nav}{badge}{headline}{sub}<div class="btnrow">'
                f'<a class="btn" href="#cta">{e(c["cta"]["label"])}</a>'
                f'<a class="ghost" href="#features">See how it works</a></div></div>')
    if hero == "band":
        return f'{nav}{tagline}{headline}{sub}<div class="rule"></div>{cta}'
    if hero == "rail":
        return f'<div class="rail-grid"><aside class="rail">{nav}</aside><div>{headline}{sub}{cta}</div></div>'
    if hero == "showcase":
        return (f'<div>{nav}{tagline}{headline}{sub}{cta}'
                f'<div class="win" role="img" aria-label="{name} product interface, drawn in CSS">'
                f'<div class="chrome"><i></i><i></i><i></i><b>{name}</b></div>'
                f'<div class="lines"><span></span><span></span><span></span><span></span></div></div></div>')
    if hero == "editorial":
        meta = "".join(f'<div><b>{e(t)}</b><span>{e(c["features"][i]["title"])}</span></div>'
                       for i, t in enumerate(("Focus", "Built for", "Ready")) if i < len(c["features"]))
        return (f'{nav}<div class="hero-cols"><div>{tagline}{headline}{sub}{cta}</div>'
                f'<div class="hero-meta">{meta}</div></div>')
    if hero == "terminal":
        lines = "".join(f'<p class="ln"><b>&gt;</b><span>{e(x)}</span></p>'
                        for x in (f'{name} init', "brief accepted", "deploy in one pass"))
        return f'{nav}<div class="term">{lines}</div>{headline}{sub}{cta}'
    if hero == "marquee":
        return (f'{nav}{tagline}{headline}<div class="lede">{sub}'
                f'<p style="margin:0;color:var(--muted)">{e(c["cta"]["supporting_text"])}</p></div>{cta}')
    if hero == "storefront":
        cats = "".join(f'<div class="cat"><b>0{i + 1}</b><span>{e(x["title"])}</span></div>'
                       for i, x in enumerate(c["features"][:3]))
        return (f'{nav}<div class="promo"><span>New this season</span><span>{name}</span></div>'
                f'{headline}{sub}{cta}<div class="cats">{cats}</div>')
    if hero == "masthead":
        return (f'<div class="mast"><span class="brandbig">{name}</span></div>'
                f'{nav}{headline}{sub}{cta}')
    if hero == "poster":
        tags = "".join(f'<em>{e(x["title"])}</em>' for x in c["features"][:3])
        return f'{nav}<div class="poster">{tagline}{headline}{sub}{cta}<div class="tag">{tags}</div></div>'
    # "orb" (and anything unknown): copy on a solid panel, decoration behind it and clipped by the hero.
    return (f'<span class="orb" aria-hidden="true"></span><span class="orb two" aria-hidden="true"></span>'
            f'<div class="panel">{nav}{tagline}{headline}{sub}</div>{cta}')


def _features_html(direction: variants.DesignDirection, c: dict) -> str:
    e, feats, kind = _esc, c["features"], direction.features
    if kind == "grid":
        return ('<div class="fgrid">' + "".join(
            f'<article class="card"><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></article>' for x in feats) + "</div>")
    if kind == "numbered":
        return ('<ol class="fnum">' + "".join(
            f'<li><div><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></div></li>' for x in feats) + "</ol>")
    if kind == "checklist":
        return ('<ul class="fcheck">' + "".join(
            f'<li><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></li>' for x in feats) + "</ul>")
    if kind == "bento":
        return ('<div class="fbento">' + "".join(
            f'<article class="card"><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></article>' for x in feats) + "</div>")
    if kind == "plain-list":
        return ('<div class="flist">' + "".join(
            f'<div class="row"><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></div>' for x in feats) + "</div>")
    if kind == "index-table":
        return ('<div class="ftab">' + "".join(
            f'<div class="row"><span class="no">0{i + 1}</span><h3>{e(x["title"])}</h3>'
            f'<p>{e(x["description"])}</p></div>' for i, x in enumerate(feats)) + "</div>")
    if kind == "tiles":
        return ('<div class="ftiles">' + "".join(
            f'<article class="card"><span class="kicker">0{i + 1}</span><h3>{e(x["title"])}</h3>'
            f'<p>{e(x["description"])}</p></article>' for i, x in enumerate(feats)) + "</div>")
    if kind == "spotlight":
        lead, *rest = feats
        return (f'<div class="fspot"><article class="lead"><h3>{e(lead["title"])}</h3>'
                f'<p>{e(lead["description"])}</p></article><div class="rest">'
                + "".join(f'<div class="row"><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></div>' for x in rest)
                + "</div></div>")
    if kind == "products":
        return ('<div class="fprod">' + "".join(
            f'<article class="card"><div class="ph" role="img" aria-label="{e(x["title"])} illustration"></div>'
            f'<div class="tbody"><span class="kicker">Available</span><h3>{e(x["title"])}</h3>'
            f'<p>{e(x["description"])}</p></div></article>' for x in feats) + "</div>")
    if kind == "articles":
        return ('<div class="farts">' + "".join(
            f'<article class="art"><span class="kicker">Read</span><h3>{e(x["title"])}</h3>'
            f'<p>{e(x["description"])}</p></article>' for x in feats) + "</div>")
    if kind == "manifest":
        return ('<ul class="fman">' + "".join(
            f'<li><div><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></div></li>' for x in feats) + "</ul>")
    # "duo": one tall panel beside a stack.
    first, *rest = feats or [{"title": "", "description": ""}]
    return (f'<div class="fduo"><article class="tall"><h3>{e(first["title"])}</h3>'
            f'<p>{e(first["description"])}</p></article><div class="stack">'
            + "".join(f'<article class="card"><h3>{e(x["title"])}</h3><p>{e(x["description"])}</p></article>'
                      for x in rest) + "</div></div>")


def _sample_note(items: list) -> str:
    """Say out loud when a section is placeholder content the crew invented because the brief had none."""
    if not any(isinstance(x, dict) and x.get("sample", True) for x in items):
        return ""
    return '<p class="sample">Sample content - replace it with your own words in the editor.</p>'


def _section_html(name: str, heading: str, inner: str, note: str = "", alt: bool = False) -> str:
    cls = " sec-alt" if alt else ""
    return (f'<section id="{name}" class="sec-{name}{cls}"><div class="wrap"><h2>{_esc(heading)}</h2>'
            f'{inner}{note}</div></section>')


def _extra_sections(c: dict) -> dict[str, str]:
    """The optional sections, rendered only when there is something to put in them."""
    e, out = _esc, {}

    quotes = c.get("testimonials") or []
    if quotes:
        inner = '<div class="quotes">' + "".join(
            f'<figure class="tcard"><blockquote>{e(x.get("quote", ""))}</blockquote>'
            f'<figcaption>{e(x.get("attribution", ""))}</figcaption></figure>' for x in quotes) + "</div>"
        out["testimonials"] = _section_html("testimonials", "What people say", inner,
                                            _sample_note(quotes), alt=True)

    plans = c.get("pricing") or []
    if plans:
        cards = "".join(
            f'<article class="plan{" feat" if x.get("featured") else ""}"><h3>{e(x.get("name", ""))}</h3>'
            f'<p class="price">{e(x.get("price", ""))}</p><p class="blurb">{e(x.get("blurb", ""))}</p>'
            f'<ul>{"".join(f"<li>{e(i)}</li>" for i in (x.get("items") or []))}</ul></article>' for x in plans)
        out["pricing"] = _section_html("pricing", "Plans", f'<div class="plans">{cards}</div>',
                                       _sample_note(plans))

    shots = c.get("gallery") or []
    if shots:
        tiles = "".join(
            f'<figure><div class="ph" role="img" aria-label="{e(x.get("title", ""))}"></div>'
            f'<figcaption><b>{e(x.get("title", ""))}</b><span>{e(x.get("caption", ""))}</span></figcaption></figure>'
            for x in shots)
        out["gallery"] = _section_html("gallery", "Gallery", f'<div class="gtiles">{tiles}</div>',
                                       _sample_note(shots), alt=True)

    people = c.get("team") or []
    if people:
        roles = "".join(
            f'<article class="rcard"><span class="kicker">{e(x.get("role", ""))}</span>'
            f'<p>{e(x.get("focus", ""))}</p></article>' for x in people)
        out["team"] = _section_html("team", "The people", f'<div class="roles">{roles}</div>',
                                    _sample_note(people))

    contact = c.get("contact") or {}
    rows = [f'<div><b>{label}</b><span>{e(contact.get(key))}</span></div>'
            for label, key in (("Email", "email"), ("Phone", "phone"), ("Where", "location"))
            if str(contact.get(key) or "").strip()]
    if contact.get("note"):
        rows.append(f'<div><b>Note</b><span>{e(contact["note"])}</span></div>')
    if rows:
        out["contact"] = _section_html("contact", "Contact", f'<div class="paths">{"".join(rows)}</div>', alt=True)
    return out


def _ticker(name: str, c: dict) -> str:
    """The agency motif's divider: a clipped strip of capability words, decorative only."""
    words = [x.get("title", "") for x in (c.get("features") or [])[:4] if x.get("title")]
    strip = "".join(f'<span>{_esc(w)}</span>' for w in words * 2)
    return f'<div class="ticker" aria-hidden="true"><div class="strip">{strip}</div></div>'


def build_page(payload: dict) -> str:
    """Self-contained, accessible, responsive landing page used by the mock Engineer.

    The composition comes from the run's design direction (app/agents/variants + app/agents/styles),
    so each style gets its own hero, navigation, feature layout, motif, spacing and type scale rather
    than one template with a different background colour.
    """
    c, d = payload["copy"], payload["design"]
    direction = variants.from_dict(payload.get("direction"))
    p, f = d["palette"], d["fonts"]
    e = _esc

    band = mix(p["background"], p["surface"], 0.55)
    line = mix(p["background"], p["text"], 0.16)
    tokens = {"body": f["body"], "heading": f["heading"], **_style_tokens(direction)}
    css = (_BASE_CSS + _NAV_CSS.get(direction.nav, "") + _HERO_CSS.get(direction.hero, "")
           + _FEATURE_CSS.get(direction.features, "") + _MOTIF_CSS.get(direction.motif, "") + _EXTRA_CSS)
    for k, v in tokens.items():
        css = css.replace(f"__{k}__", v)
    root = root_vars(direction, p, band, line)
    css = ":root{" + "".join(f"{k}:{v};" for k, v in root.items()) + "}" + css

    extras = _extra_sections(c)
    parts = dict(extras)
    parts["features"] = _section_html("features", f'Why {c["product_name"]}', _features_html(direction, c))
    faqs = "".join(f'<details><summary>{e(x["question"])}</summary><p>{e(x["answer"])}</p></details>' for x in c["faq"])
    parts["faq"] = _section_html("faq", "Questions, answered", faqs, alt=True)
    form = (f'<form class="signup" id="signup" action="#">'
            f'<label for="email" style="position:absolute;left:-9999px">Email</label>'
            f'<input id="email" type="email" placeholder="you@example.com" required>'
            f'<button class="btn" type="submit">{e(c["cta"]["label"])}</button></form>'
            f'<p id="msg" role="status"></p>')
    parts["cta"] = _section_html("cta", c["cta"]["label"], f'<p class="sub">{e(c["cta"]["supporting_text"])}</p>{form}')

    ids = [name for name in direction.order if name in parts]
    hero_inner = _hero_html(direction, c, _nav_html(direction, c["product_name"], ids))
    body = "".join(parts[name] for name in ids)
    ticker = _ticker(c["product_name"], c) if direction.motif == "ticker" else ""
    if ticker and "features" in ids:
        body = body.replace(parts["features"], parts["features"] + ticker, 1)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c["product_name"])} - {e(c["headline"])}</title><style>{css}</style></head>
<body>
<header id="hero" class="hero hero-{direction.hero}"><div class="wrap">{hero_inner}</div></header>
<main>{body}</main>
<footer><div class="wrap">&copy; {e(c["product_name"])}. Built with Launch Crew.</div></footer>
<script>document.getElementById('signup').addEventListener('submit',function(ev){{ev.preventDefault();document.getElementById('msg').textContent="Thanks! You're on the list.";}});</script>
</body></html>"""


def design_sample_page(direction: variants.DesignDirection) -> str:
    """One page drawn from a design direction, for the theme customizer's live preview.

    This is the same `build_page` an offline run renders with, so the preview carries the real
    consequence of a theme: the `:root` block the theme editor patches, and the components that read it.
    The copy is the deterministic sample, with every stand-in placeholder marked `sample`, because a
    preview of *appearance* has no business inventing quotes, prices or screenshots.
    """
    copy = _sample_copy("This page", "you",
                        "Every colour, font and spacing value here is drawn from the theme you are setting",
                        list(direction.optional_sections()))
    return build_page({"copy": copy,
                       "design": {"palette": dict(direction.palette), "fonts": dict(direction.fonts),
                                  "layout_style": direction.layout_style},
                       "direction": variants.as_dict(direction)})


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
            default = _sample_copy(name, aud, idea, _sections_from(_all_text(messages)))
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


def _sample_copy(name: str, aud: str, idea: str, sections: list[str]) -> dict:
    """The offline Copywriter's answer: core copy, plus placeholder content for the sections the
    direction asks for. Everything invented here is marked `sample` so the page labels it and the
    user is never shown a testimonial or price the crew made up without saying so."""
    doc = {
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
        "cta": {"label": "Get early access", "supporting_text": "Join the waitlist - we will email you the moment we launch."},
    }
    if "testimonials" in sections:
        doc["testimonials"] = [
            {"quote": f"Placeholder quote: {name} would suit how {aud} work.",
             "attribution": "Sample - add a real customer", "sample": True},
            {"quote": "Placeholder quote about saving time on a repetitive task.",
             "attribution": "Sample - add a real customer", "sample": True},
            {"quote": "Placeholder quote about setup being quick.",
             "attribution": "Sample - add a real customer", "sample": True}]
    if "pricing" in sections:
        doc["pricing"] = [
            {"name": "Starter", "price": "Sample price", "blurb": "For trying it out.",
             "items": ["Core features", "One workspace"], "featured": False, "sample": True},
            {"name": "Team", "price": "Sample price", "blurb": "For working together.",
             "items": ["Everything in Starter", "Shared views", "Roles"], "featured": True, "sample": True},
            {"name": "Enterprise", "price": "Tell us what you need", "blurb": "For larger rollouts.",
             "items": ["Priority support", "Invoicing"], "featured": False, "sample": True}]
    if "gallery" in sections:
        doc["gallery"] = [
            {"title": f"{name} overview", "caption": "Placeholder panel - replace with a real screenshot.", "sample": True},
            {"title": "A working view", "caption": "Placeholder panel - replace with a real screenshot.", "sample": True},
            {"title": "The detail view", "caption": "Placeholder panel - replace with a real screenshot.", "sample": True}]
    if "team" in sections:
        doc["team"] = [
            {"role": "Founder", "focus": "Placeholder - name and background go here.", "sample": True},
            {"role": "Product", "focus": "Placeholder - name and background go here.", "sample": True}]
    if "contact" in sections:
        doc["contact"] = {"email": "", "phone": "", "location": "",
                          "note": "Add your contact details in the editor - nothing here is invented.",
                          "sample": True}
    return doc
