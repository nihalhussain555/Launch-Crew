"""Deterministic offline provider (MOCK_LLM=true). Returns schema-valid output for every agent,
so the full pipeline (including the Playwright critic and deploy gate) works with no API keys.

The page builder below is the offline renderer for the style system (app/agents/styles.py): each of
the 12 styles composes a different hero, navigation, feature layout, motif and token set, so a run in
"Brutalist & bold" and a run in "Luxury & premium" share nothing but the copy. A run that names a
template is drawn through that template's art direction first (app/agents/looks.py), which is what lets
twenty gallery cards produce twenty pages rather than twenty colour swaps. Sections the brief
adds (testimonials, pricing, gallery, team, contact) are rendered here too, each labelled as sample
content when the crew had nothing real to put in it.

Sample photography (app/agents/art.py) rides in as a `data:` URI, because the page is one self-contained
file and its CSP allows no other image source. It is capped by a byte budget and never depicts a person:
people slots are drawn in CSS, since a generated face under "meet our surgeons" would present an invented
person as a real one.

Revisions go through app.llm.mock_edits, which reads the FIXES / CURRENT_JSON / CURRENT_HTML blocks
and applies the requested change mechanically, so an edit visibly alters the page offline.
"""
from __future__ import annotations

import html
import json
import re

from app.agents import art as art_mod
from app.agents import looks as looks_mod
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


def _business_from(blob: str) -> str:
    """The business key off the BRIEF line - `business type: Restaurant / cafe (restaurant)`.

    The offline sample uses it for section wording only (a cafe lists its Menu, a school its Courses);
    a real provider gets the same line in its prompt and writes its own headings into `titles`.

    The brief's parts are separated by semicolons and a template names its industries in brackets, so the
    search stops at the first `;`: reading past it lands on the design style's key instead.
    """
    m = re.search(r"business type:[^\n;]*\(([a-z]+)\)", blob)
    return m.group(1) if m else ""


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
.shot{display:block;width:100%;height:auto;object-fit:cover;border-radius:__artradious__}
.hero-figure{margin:26px 0 0}
.hero-figure .shot{border-radius:__artradious__;max-height:min(58vh,480px)}
.hero-art .shot{max-height:440px;border-radius:0}
.fprod .shot{border-radius:0}
.gtiles .shot,.case .shot,.ware .shot{margin:0 0 12px}
.case .shot,.ware .shot{aspect-ratio:3/2}
.pills{list-style:none;display:flex;flex-wrap:wrap;gap:10px;padding:0;margin:26px 0 0}
.pills li{display:flex;align-items:baseline;gap:8px;padding:9px 16px;border:1px solid var(--line);border-radius:999px;background:var(--surface)}
.pills b{font-family:__heading__;font-size:__h3__;color:var(--text)}
.pills span{font-size:__small__;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--muted)}
@media (max-width:719px){.gtiles .shot,.case .shot,.ware .shot{margin-bottom:10px}}
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
.farts .art .shot{max-width:340px}
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
/* who you are: the intro, the facts a client checks, the credentials behind them */
.lede{font-size:clamp(18px,2.4vw,22px);max-width:62ch;margin:0 0 24px}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:__gap__;margin:0}
.facts>div{display:grid;gap:4px;padding-bottom:12px;border-bottom:1px solid var(--line)}
.facts b{font-size:__small__;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--muted);font-weight:700}
.facts span{font-family:__heading__;font-size:__h3__}
.creds{list-style:none;display:flex;flex-wrap:wrap;gap:10px;padding:0;margin:24px 0 0}
.creds li{font-size:__small__;font-weight:700;letter-spacing:__labeltrack__;text-transform:__labelcase__;padding:7px 14px;border:1px solid var(--line);border-radius:999px;color:var(--muted)}
/* the record, as figures */
.figures{list-style:none;display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:__gap__;padding:0;margin:0}
.figures li{display:grid;gap:8px;padding:var(--card-pad);background:var(--card-bg);border:var(--card-border);border-radius:var(--card-radius);box-shadow:var(--card-shadow)}
.figures b{font-family:__heading__;font-size:clamp(30px,4.6vw,46px);line-height:1;color:var(--primary)}
.figures span{font-size:__small__;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--muted);font-weight:700}
/* what the work runs on: grouped, each item its own chip */
.skwrap{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:__gap__}
.skgroup h3{font-size:__small__;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--muted);margin:0 0 12px}
.tags{list-style:none;display:flex;flex-wrap:wrap;gap:8px;padding:0;margin:0}
.tags li{padding:7px 13px;border:1px solid var(--line);border-radius:var(--radius);font-size:15px;font-weight:600}
/* services: the name, the line that decides it, what it covers */
.svc{list-style:none;padding:0;margin:0;display:grid;gap:__gap__}
.svc li{display:grid;gap:8px;padding-bottom:__halfpad__;border-bottom:1px solid var(--line)}
.svc-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:12px}
.svc-head h3{margin:0}
.priced{font-size:__small__;font-weight:700;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--accent)}
.svc p{margin:0;color:var(--muted);max-width:70ch}
/* case work: client, brief, result */
.cases{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:__gap__}
.cases .case{display:grid;gap:10px;align-content:start;background:var(--card-bg);border:var(--card-border);border-radius:var(--card-radius);box-shadow:var(--card-shadow);padding:var(--card-pad)}
.cases p{margin:0;color:var(--muted)}
.cases .metric{font-family:__heading__;font-size:__h3__;color:var(--primary)}
/* catalogue: category, item, note, spec lines, price */
.ware-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:__gap__}
.ware{background:var(--card-bg);border:var(--card-border);border-radius:var(--card-radius);box-shadow:var(--card-shadow);overflow:hidden}
.ware .ph{min-height:150px;border-radius:0}
.ware .shot{border-radius:0}
.ware h3{margin:0 0 6px}
.ware p{margin:0;color:var(--muted)}
.tagline{font-size:__small__;font-weight:700;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--accent);display:block;margin-bottom:6px}
.specs{list-style:none;padding:0;margin:12px 0 0;display:flex;flex-wrap:wrap;gap:6px}
.specs li{font-size:__small__;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:4px 11px}
.cost{font-family:__heading__;font-weight:700;font-size:__h3__;margin:14px 0 0}
/* the product drawn in CSS - no screenshot of a product that does not exist yet */
.demo{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:calc(__gap__ * 1.6);align-items:center}
.frame{position:relative;background:var(--card-bg);border:var(--card-border);border-radius:calc(var(--card-radius) + 6px);box-shadow:var(--card-shadow);padding:14px}
.frame .chrome{display:flex;align-items:center;gap:6px;padding:0 6px 12px}
.frame .chrome i{width:10px;height:10px;border-radius:50%;background:var(--line)}
.frame .chrome b{margin-left:auto;font-size:__small__;font-weight:700;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--muted)}
.frame .screen{background:var(--band);border-radius:__artradious__;min-height:180px;padding:24px;display:grid;gap:12px;align-content:start}
.frame .ln{display:block;height:12px;border-radius:999px;background:var(--line)}
.frame .ln.one{width:58%;background:var(--primary);opacity:.7}
.frame .ln.two{width:82%}
.frame.phone{max-width:260px;margin:0 auto;border-radius:34px;padding:22px 16px}
.frame.phone .notch{display:block;width:96px;height:16px;margin:0 auto 16px;border-radius:999px;background:var(--line)}
.frame.phone .screen{min-height:270px}
/* a real picture inside the drawn window: the frame stays, the filler lines go */
.frame.photo .screen{padding:0;background:transparent;min-height:240px}
.frame.photo .screen .shot{height:100%;min-height:240px;border-radius:__artradious__}
.frame.phone.photo .screen .shot{min-height:300px}
.demo-copy h3{margin:0 0 10px}
.demo-copy p{color:var(--muted)}
.pointers{list-style:none;padding:0;margin:16px 0 0;display:grid;gap:10px}
.pointers li{padding-left:26px;position:relative;color:var(--muted)}
.pointers li::before{content:"";position:absolute;left:0;top:.55em;width:10px;height:10px;border-radius:50%;background:var(--accent)}
/* dated lines: agenda, learning path, history, announcements */
.tl{list-style:none;padding:0;margin:0;display:grid;gap:__gap__}
.tl li{display:grid;grid-template-columns:120px minmax(0,1fr);gap:__gap__;padding-bottom:__halfpad__;border-bottom:1px solid var(--line)}
.tl b{font-size:__small__;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--accent);font-weight:700}
.tl p{margin:0;color:var(--muted)}
.tl .where{display:inline-block;margin-top:8px;font-size:__small__;color:var(--muted);letter-spacing:__labeltrack__;text-transform:__labelcase__}
/* where it is and when it opens */
.sec-visit address{font-style:normal;font-family:__heading__;font-size:__h3__;line-height:1.5;max-width:44ch}
.hours{display:grid;gap:8px;margin:24px 0;max-width:440px}
.hrow{display:flex;justify-content:space-between;gap:16px;padding-bottom:8px;border-bottom:1px solid var(--line);font-size:15px}
.hrow span{color:var(--muted)}
.travel{color:var(--muted);max-width:60ch;margin:0}
/* booking: the fields, then the plain words about where the request goes */
.book{display:grid;gap:12px;max-width:560px;margin-top:8px}
.book label{font-size:__small__;font-weight:700;letter-spacing:__labeltrack__;text-transform:__labelcase__;color:var(--muted)}
.book input,.book select,.book textarea{width:100%;max-width:560px;min-height:48px;padding:0 16px;border-radius:var(--radius);border:2px solid var(--muted);background:var(--surface);color:var(--text);font-size:17px;font-family:__body__}
.book textarea{min-height:112px;padding:14px 16px;resize:vertical}
.book .btn{margin-top:6px}
#bkmsg{min-height:28px;color:var(--accent);font-weight:600;margin:0}
.book-note{color:var(--muted);font-size:__small__;max-width:62ch;margin:20px 0 0}
.muted-line{color:var(--muted);margin:10px 0 0}
@media (max-width:860px){.demo,.ware-grid,.figures,.facts,.skwrap,.svc{gap:max(22px,var(--gap))!important}.demo{grid-template-columns:1fr!important}}
@media (max-width:719px){.tl li{grid-template-columns:minmax(0,1fr)!important;gap:6px!important}}
"""


# ------------------------------------------------------------------ page behaviour
# A shipped page has no server of its own, so its two forms report that instead of pretending: the
# waitlist box and the booking request validate in the browser and then say, in the status line, that
# nothing was sent. Submitting to a made-up "thanks" would be the one thing on this page that lies.
# No banned API appears here (see app/tools/sanitizer.py): the handlers only talk to the visitor.
_PAGE_JS = """
(function () {
  function say(id, text) { var el = document.getElementById(id); if (el) { el.textContent = text; } }
  function wire(formId, msgId, text) {
    var form = document.getElementById(formId);
    if (!form) { return; }
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (!form.checkValidity()) { form.reportValidity(); return; }
      say(msgId, text);
    });
  }
  wire('signup', 'msg', 'Nothing was sent: this page has no form service connected yet. Connect one, '
    + 'or use the contact details on this page.');
  wire('book', 'bkmsg', 'Checked in your browser only - this page stores and sends nothing. '
    + 'Connect the booking feature to capture these requests.');
})();
"""


# ------------------------------------------------------------------ sample photography
# A template's pictures are handed out in slot order, then round again until the page's shot limit runs
# out; the CSS treatment that was here first fills any slot left over, so a page with no photography at all
# is still a complete design rather than a page with holes in it.
class _Tiles:
    """The template's card pictures, handed out in order and then round again, up to the page's shot limit.

    A catalogue of six items with three pictures would otherwise show three photographs and three empty
    boxes, which reads as a page that broke rather than one that is short of art. Reusing the three is the
    sample-photography behaviour the hero labels. The limit is what keeps that reuse inside the byte
    budget the pictures were chosen against.
    """

    def __init__(self, entries: list[dict], shots: int = 0):
        self._all = list(entries)
        self._left = list(entries)
        self._shots = int(shots) if self._all else 0

    def next(self) -> dict | None:
        if not self._all or self._shots <= 0:
            return None
        self._shots -= 1
        if not self._left:
            self._left = list(self._all)
        return self._left.pop(0)

    @property
    def any_left(self) -> bool:
        return bool(self._all) and self._shots > 0


def _art_for(direction: variants.DesignDirection) -> dict:
    """The pictures this run's template ships, already cut to `app/agents/art.py`'s byte budget.

    A direction with no look - a hand-written brief, a legacy run - has none, and the page is drawn in CSS
    exactly as it was before the gallery existed.
    """
    if not getattr(direction, "look", ""):
        return {"hero": None, "tiles": [], "shots": 0}
    return art_mod.art_for(direction.look)


def _shot(entry: dict | None, alt: str, eager: bool = False, cls: str = "shot") -> str:
    """One inlined picture. Nothing about it is remote: the page's CSP permits `data:` images and the
    sanitizer deletes anything else, which is the only way an image survives a sandboxed preview, a
    download and a static deploy alike.

    `width`/`height` are the file's own pixels. The CSS sizes the element, but those two attributes are
    what reserve the space before the bytes decode, and the performance audit looks for them by name.
    """
    if not entry:
        return ""
    uri = art_mod.data_uri(entry)
    if not uri:
        return ""
    return (f'<img class="{cls}" src="{uri}" width="{entry["w"]}" height="{entry["h"]}"'
            f' alt="{_esc(alt)}" loading="{"eager" if eager else "lazy"}" decoding="async">')


def _art_note() -> str:
    """Says out loud that the photography is ours, not the business's."""
    return '<p class="sample">Sample photography - replace it with your own images in the editor.</p>'


def _plate(tiles: "_Tiles", alt: str) -> str:
    """A picture where the template has one left to spend, the drawn placeholder where it does not.

    Both are the same box in the layout, so a page that ran out of budget - or a template that ships no
    photography at all - is the same design with its own art in that slot, not a gap.
    """
    entry = tiles.next()
    return _shot(entry, alt) if entry else f'<div class="ph" role="img" aria-label="{_esc(alt)} illustration"></div>'


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
           "team": "Team", "faq": "FAQ", "contact": "Contact", "cta": "Get started",
           "about": "About", "stats": "Numbers", "skills": "Skills", "services": "Services",
           "work": "Work", "catalog": "Catalogue", "preview": "Preview", "timeline": "Schedule",
           "visit": "Visit", "booking": "Book"}

# The heading a section gets when the copy does not name it. Business voice beats these wherever the
# Copywriter (or the offline sample) supplies a `titles` entry, so a cafe's list reads "Menu".
_DEFAULT_TITLES = {"about": "About", "stats": "By the numbers", "skills": "Skills",
                   "services": "What we do", "work": "Selected work", "catalog": "Catalogue",
                   "preview": "See it working", "timeline": "Schedule", "visit": "Find us",
                   "booking": "Book", "testimonials": "What people say", "pricing": "Plans",
                   "gallery": "Gallery", "team": "The people", "contact": "Contact",
                   "features": "Features", "faq": "Questions, answered", "cta": "Get started"}

# How each trade names the blocks a template asks for. The business key arrives on the brief line the
# Copywriter is given, so the same catalog block reads as a menu in one run and a course list in another.
_BUSINESS_TITLES = {
    "corporate": {"services": "What we do", "work": "Case studies", "stats": "The firm in numbers",
                  "about": "Who we are", "team": "Leadership", "booking": "Arrange a meeting"},
    "legal": {"services": "Practice areas", "work": "Case notes", "stats": "Credentials",
              "team": "The team", "about": "About the practice", "booking": "Request a consultation"},
    "saas": {"preview": "Take a look", "skills": "Integrations", "services": "What you get",
             "timeline": "Product updates", "booking": "Book a demo"},
    "ai": {"preview": "See it work", "skills": "Capabilities", "stats": "How it performs",
           "timeline": "Roadmap", "booking": "Book a walkthrough"},
    "store": {"catalog": "Products", "services": "Support", "visit": "Visit us",
              "timeline": "What's new", "booking": "Book an appointment"},
    "restaurant": {"catalog": "Menu", "visit": "Opening hours", "booking": "Book a table",
                   "services": "What we serve", "about": "The place"},
    "realestate": {"catalog": "Properties", "team": "Agents", "booking": "Book a viewing",
                   "visit": "The office", "work": "Recent lettings"},
    "health": {"services": "Treatments", "team": "Practitioners", "booking": "Request an appointment",
               "visit": "Clinic and hours", "about": "About the clinic"},
    "education": {"catalog": "Courses", "team": "Instructors", "timeline": "The path you follow",
                  "booking": "Enquire about a place", "stats": "Where our students get to"},
    "media": {"catalog": "Latest", "team": "Writers", "about": "About the publication",
              "timeline": "Archive"},
    "event": {"timeline": "The agenda", "team": "Speakers", "booking": "Register",
              "stats": "Last year in numbers", "catalog": "Sessions"},
    "portfolio": {"work": "Projects", "skills": "Tools I use", "timeline": "Experience",
                  "stats": "Career in numbers", "about": "About me"},
    "freelance": {"services": "What I do", "work": "Projects", "timeline": "How we work",
                  "booking": "Book a call", "about": "About me"},
    "agency": {"services": "Services", "work": "Client projects", "team": "The studio",
               "about": "About the studio", "booking": "Start a project"},
    "local": {"services": "Services and prices", "catalog": "In store", "visit": "Where we are",
              "booking": "Book a slot", "about": "About us"},
    "other": {},
}


def _titles(c: dict) -> dict[str, str]:
    """Section -> heading, as the copy asked for it. Later entries do not replace earlier ones: the
    first name a section is given is the one the page uses."""
    out: dict[str, str] = {}
    for row in c.get("titles") or []:
        if isinstance(row, dict):
            key, text = str(row.get("section") or ""), str(row.get("text") or "").strip()
            if key in variants.SECTIONS and text and key not in out:
                out[key] = text[:48]
    return out


def _title(c: dict, section: str) -> str:
    return _titles(c).get(section) or _DEFAULT_TITLES.get(section, section.capitalize())


# The nav bar carries the page's own words when they fit: a cafe's list should read "Menu" in the bar as
# well as in the heading. A name longer than a nav slot can hold falls back to the short label, so a
# Copywriter's long heading never wrecks the bar.
_NAV_MAX = 16
_NAV_CLASS = {"wide-labels": "v-wide", "pill-bar": "v-pill", "index-list": "v-index",
              "underline-bar": "v-underline", "bracket": "v-bracket", "store-bar": "v-store",
              "masthead-nav": "v-mast", "mono-strip": "v-mono", "plain-brand": "v-plain",
              "split-links": "v-split"}


def _nav_labels(c: dict, ids: list[str]) -> dict[str, str]:
    voice = _titles(c)
    labels = {}
    for i in ids:
        said = voice.get(i)
        labels[i] = said if said and len(said) <= _NAV_MAX else _LABELS.get(i, i.capitalize())
    return labels


def _nav_html(direction: variants.DesignDirection, name: str, ids: list[str],
              labels: dict[str, str] | None = None) -> str:
    """The style's navigation: the same real targets, arranged differently."""
    words = lambda i: _esc((labels or {}).get(i) or _LABELS.get(i, i.capitalize()))  # noqa: E731
    links = [f'<a href="#{i}">{words(i)}</a>' for i in ids if i != "hero"]
    kind, brand = direction.nav, f'<span class="brand">{_esc(name)}</span>'
    cls = _NAV_CLASS.get(kind, "")
    attrs = f' class="{cls}"' if cls else ""
    if kind == "plain-brand":
        return f'<nav aria-label="Main"{attrs}>{brand}{links[0] if links else ""}</nav>'
    if kind == "index-list":
        return f'<nav aria-label="Main"{attrs}>{brand}<ol>{"".join(f"<li>{a}</li>" for a in links)}</ol></nav>'
    if kind == "store-bar":
        cats = "".join(f'<em>{words(i)}</em>'
                       for i in ids if i in ("catalog", "gallery", "pricing", "visit", "contact"))
        return (f'<nav aria-label="Main"{attrs}><span class="grp">{brand}{"".join(links)}</span>'
                f'<span class="catline">{cats}</span></nav>')
    if kind == "split-links":
        return f'<nav aria-label="Main"{attrs}>{brand}<span class="grp">{"".join(links)}</span></nav>'
    return f'<nav aria-label="Main"{attrs}>{brand}{"".join(links)}</nav>'


# Where a template's hero picture belongs, per hero kind. Two kinds deliberately take none: `showcase`
# and `terminal` are built around a drawn product window and a drawn terminal, and a photograph would sit
# on top of the thing they exist to show.
_HERO_FIGURE_AFTER = frozenset({"rail", "band", "editorial", "marquee", "storefront", "masthead",
                                "poster", "centered", "orb"})


def _hero_html(direction: variants.DesignDirection, c: dict, nav: str, art: dict | None = None) -> str:
    e, hero = _esc, direction.hero
    art = art or {"hero": None, "tiles": []}
    picture = art["hero"]
    headline = f'<h1>{e(c["headline"])}</h1>'
    sub = f'<p class="sub">{e(c["subheadline"])}</p>'
    cta = f'<p><a class="btn" href="#cta">{e(c["cta"]["label"])}</a></p>'
    name = e(c["product_name"])
    tagline = f'<span class="kicker">{name}</span>'
    # The caption is the page's own promise, not a description of the file: it says what the slot is for.
    fig = _shot(picture, f'Sample photography for {c["product_name"]}', eager=True)
    figure = f'<figure class="hero-figure">{fig}{_art_note() if fig else ""}</figure>' if picture else ""

    if hero == "split":
        art_panel = fig or '<div class="rings"><i></i><i></i><i></i></div>'
        return (f'<div class="hero-grid"><div>{nav}{headline}{sub}{cta}</div>'
                f'<div class="hero-art">{art_panel}</div></div>'
                + (f'{_art_note()}' if fig else ""))
    if hero == "centered":
        badge = f'<span class="badge">{name}</span>'
        return (f'<div>{nav}{badge}{headline}{sub}<div class="btnrow">'
                f'<a class="btn" href="#cta">{e(c["cta"]["label"])}</a>'
                f'<a class="ghost" href="#features">See how it works</a></div>{figure}</div>')
    if hero == "band":
        return f'{nav}{tagline}{headline}{sub}<div class="rule"></div>{cta}{figure}'
    if hero == "rail":
        return f'<div class="rail-grid"><aside class="rail">{nav}</aside><div>{headline}{sub}{cta}{figure}</div></div>'
    if hero == "showcase":
        return (f'<div>{nav}{tagline}{headline}{sub}{cta}'
                f'<div class="win" role="img" aria-label="{name} product interface, drawn in CSS">'
                f'<div class="chrome"><i></i><i></i><i></i><b>{name}</b></div>'
                f'<div class="lines"><span></span><span></span><span></span><span></span></div></div></div>')
    if hero == "editorial":
        meta = "".join(f'<div><b>{e(t)}</b><span>{e(c["features"][i]["title"])}</span></div>'
                       for i, t in enumerate(("Focus", "Built for", "Ready")) if i < len(c["features"]))
        return (f'{nav}<div class="hero-cols"><div>{tagline}{headline}{sub}{cta}</div>'
                f'<div class="hero-meta">{figure}{meta}</div></div>')
    if hero == "terminal":
        lines = "".join(f'<p class="ln"><b>&gt;</b><span>{e(x)}</span></p>'
                        for x in (f'{name} init', "brief accepted", "deploy in one pass"))
        return f'{nav}<div class="term">{lines}</div>{headline}{sub}{cta}'
    if hero == "marquee":
        return (f'{nav}{tagline}{headline}<div class="lede">{sub}'
                f'<p style="margin:0;color:var(--muted)">{e(c["cta"]["supporting_text"])}</p></div>{cta}{figure}')
    if hero == "storefront":
        cats = "".join(f'<div class="cat"><b>0{i + 1}</b><span>{e(x["title"])}</span></div>'
                       for i, x in enumerate(c["features"][:3]))
        return (f'{nav}<div class="promo"><span>New this season</span><span>{name}</span></div>'
                f'{headline}{sub}{cta}<div class="cats">{cats}</div>{figure}')
    if hero == "masthead":
        return (f'<div class="mast"><span class="brandbig">{name}</span></div>'
                f'{nav}{headline}{sub}{cta}{figure}')
    if hero == "poster":
        tags = "".join(f'<em>{e(x["title"])}</em>' for x in c["features"][:3])
        return (f'{nav}<div class="poster">{tagline}{headline}{sub}{cta}<div class="tag">{tags}</div></div>'
                f'{figure}')
    # "orb" (and anything unknown): copy on a solid panel, decoration behind it and clipped by the hero.
    return (f'<span class="orb" aria-hidden="true"></span><span class="orb two" aria-hidden="true"></span>'
            f'<div class="panel">{nav}{tagline}{headline}{sub}{figure}</div>{cta}')


def _stat_pills(direction: variants.DesignDirection, c: dict) -> str:
    """The look's figure row: the page's own numbers, drawn as pills under the hero's ask.

    Only ever the copywriter's `stats`, which the Numbers section labels as sample content when the brief
    supplied none - the pill row adds no figure the page does not already carry somewhere else.
    """
    if not looks_mod.has(direction, "stat-pills"):
        return ""
    figures = [x for x in (c.get("stats") or []) if isinstance(x, dict) and str(x.get("value") or "").strip()][:3]
    if not figures:
        return ""
    return ('<ul class="pills">' + "".join(
        f'<li><b>{_esc(x["value"])}</b><span>{_esc(str(x.get("label", "")))}</span></li>' for x in figures)
        + "</ul>")


def _features_html(direction: variants.DesignDirection, c: dict, tiles: _Tiles | None = None) -> str:
    e, feats, kind = _esc, c["features"], direction.features
    tiles = tiles or _Tiles([])
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
            f'<article class="card">{_plate(tiles, x["title"])}'
            f'<div class="tbody"><span class="kicker">Available</span><h3>{e(x["title"])}</h3>'
            f'<p>{e(x["description"])}</p></div></article>' for x in feats) + "</div>")
    if kind == "articles":
        return ('<div class="farts">' + "".join(
            f'<article class="art">{_plate(tiles, x["title"])}<span class="kicker">Read</span>'
            f'<h3>{e(x["title"])}</h3>'
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
    return '<p class="sample">Sample content - replace it with your own words and pictures in the editor.</p>'


def _section_html(name: str, heading: str, inner: str, note: str = "", alt: bool = False) -> str:
    cls = " sec-alt" if alt else ""
    return (f'<section id="{name}" class="sec-{name}{cls}"><div class="wrap"><h2>{_esc(heading)}</h2>'
            f'{inner}{note}</div></section>')


def _doc_note(doc: dict) -> str:
    """The same admission a list section makes, for the blocks that are one document rather than rows."""
    return '<p class="sample">Sample content - replace it with your own words in the editor.</p>' \
        if isinstance(doc, dict) and doc.get("sample", True) else ""


def _extra_sections(direction: variants.DesignDirection, c: dict, tiles: "_Tiles | None" = None) -> dict[str, str]:
    """The optional sections, rendered only when there is something to put in them.

    Each block is its own markup, because each carries its own kind of information: a service has a
    lead time, a case has an outcome, a menu item has a price, an opening-hours row has days and a
    time. One generic list would make every template the same page with different words.
    """
    e, out = _esc, {}
    tiles = tiles or _Tiles([])

    def add(name: str, inner: str, note: str = "", alt: bool = False) -> None:
        out[name] = _section_html(name, _title(c, name), inner, note, alt)

    # -- who you are: the intro, the facts a client checks, the credentials behind them
    about = c.get("about") or {}
    facts = "".join(f'<div><b>{e(x.get("label", ""))}</b><span>{e(x.get("value", ""))}</span></div>'
                    for x in about.get("facts") or []
                    if isinstance(x, dict) and str(x.get("value") or "").strip())
    creds = "".join(f"<li>{e(x)}</li>" for x in about.get("credentials") or [] if str(x or "").strip())
    intro = f'<p class="lede">{e(about.get("intro", ""))}</p>' if about.get("intro") else ""
    body = intro + (f'<dl class="facts">{facts}</dl>' if facts else "") \
        + (f'<ul class="creds">{creds}</ul>' if creds else "")
    if body:
        add("about", body, _doc_note(about))

    # -- the record, as figures
    figures = c.get("stats") or []
    if figures:
        rows = "".join(f'<li><b>{e(x.get("value", ""))}</b><span>{e(x.get("label", ""))}</span></li>'
                       for x in figures if isinstance(x, dict))
        add("stats", f'<ul class="figures">{rows}</ul>', _sample_note(figures), True)

    # -- what the work uses / what it runs on
    groups = c.get("skills") or []
    if groups:
        blocks = "".join(f'<div class="skgroup"><h3>{e(x.get("group", ""))}</h3>'
                         f'<ul class="tags">{"".join(f"<li>{e(i)}</li>" for i in x.get("items") or [] if str(i or "").strip())}</ul></div>'
                         for x in groups if isinstance(x, dict))
        add("skills", f'<div class="skwrap">{blocks}</div>', _sample_note(groups))

    # -- services, each with the line a buyer checks (a lead time, a starting price, a format)
    services = c.get("services") or []
    rows = []
    for x in services:
        if not isinstance(x, dict):
            continue
        detail = f'<span class="priced">{e(x.get("detail", ""))}</span>' if x.get("detail") else ""
        rows.append(f'<li><div class="svc-head"><h3>{e(x.get("name", ""))}</h3>{detail}</div>'
                    f'<p>{e(x.get("description", ""))}</p></li>')
    if rows:
        add("services", f'<ul class="svc">{"".join(rows)}</ul>', _sample_note(services), True)

    # -- case work: the client, the brief, the result
    cases = c.get("work") or []
    cards = []
    for x in cases:
        if not isinstance(x, dict):
            continue
        sector = f" - {e(x.get('sector', ''))}" if x.get("sector") else ""
        metric = f'<b class="metric">{e(x.get("metric", ""))}</b>' if x.get("metric") else ""
        cards.append(f'<article class="case">{_plate(tiles, x.get("title", ""))}'
                     f'<span class="kicker">{e(x.get("client", ""))}{sector}</span>'
                     f'<h3>{e(x.get("title", ""))}</h3><p>{e(x.get("outcome", ""))}</p>{metric}</article>')
    if cards:
        add("work", f'<div class="cases">{"".join(cards)}</div>', _sample_note(cases))

    # -- catalogue: products, dishes, courses, listings, writings - one card per item, each with the
    #    two or three lines that decide it: a price, a spec list, a category
    items = c.get("catalog") or []
    cards = []
    for x in items:
        if not isinstance(x, dict):
            continue
        name = e(x.get("name", ""))
        tag_text = str(x.get("tag") or "").strip()
        tag = f'<span class="tagline">{e(tag_text)}</span>' if tag_text else ""
        specs = [str(s) for s in x.get("specs") or [] if str(s or "").strip()]
        spec_list = f'<ul class="specs">{"".join(f"<li>{e(s)}</li>" for s in specs)}</ul>' if specs else ""
        cost = f'<p class="cost">{e(x.get("price", ""))}</p>' if x.get("price") else ""
        cards.append(f'<article class="ware">{_plate(tiles, x.get("name", ""))}'
                     f'<div class="tbody">{tag}<h3>{name}</h3><p>{e(x.get("note", ""))}</p>'
                     f'{spec_list}{cost}</div></article>')
    if cards:
        add("catalog", f'<div class="ware-grid">{"".join(cards)}</div>', _sample_note(items), True)

    # -- the product: a screenshot where the template ships one, otherwise drawn rather than faked
    #    (a real screenshot needs the product, and inventing one would be the page lying about itself)
    demo = c.get("preview") or {}
    if demo.get("title") or demo.get("caption") or demo.get("points"):
        # A template whose whole subject is a phone draws its preview as one, whatever the copy guessed.
        phone = str(demo.get("device")) == "phone" or looks_mod.has(direction, "device-frame")
        edge = ('<span class="notch" aria-hidden="true"></span>' if phone
                else '<span class="chrome"><i></i><i></i><i></i><b>preview</b></span>')
        drawn = '<span class="ln one"></span><span class="ln two"></span><span class="ln"></span>'
        plate = _shot(tiles.next(), demo.get("title") or f"{demo.get('caption') or 'The product'} preview")
        screen = plate or drawn
        points = "".join(f"<li>{e(p)}</li>" for p in demo.get("points") or [] if str(p or "").strip())
        copy = ((f'<h3>{e(demo.get("title", ""))}</h3>' if demo.get("title") else "")
                + (f'<p>{e(demo.get("caption", ""))}</p>' if demo.get("caption") else "")
                + (f'<ul class="pointers">{points}</ul>' if points else "")
                + (_art_note() if plate else ""))
        # Only the drawn frame is a role="img" label; once a real picture is inside, the picture speaks.
        label = ("" if plate else
                 f' role="img" aria-label="{e(demo.get("title") or "Product preview")} illustration"')
        add("preview",
            f'<div class="demo"><div class="frame{" phone" if phone else ""}{" photo" if plate else ""}"'
            f'{label}>{edge}<div class="screen">{screen}</div></div><div class="demo-copy">{copy}</div></div>',
            _doc_note(demo))

    # -- dated rows: an agenda, a learning path, a career history, launch announcements
    entries = c.get("timeline") or []
    line = []
    for x in entries:
        if not isinstance(x, dict):
            continue
        where = f'<span class="where">{e(x.get("place", ""))}</span>' if x.get("place") else ""
        line.append(f'<li><b>{e(x.get("when", ""))}</b><div><h3>{e(x.get("title", ""))}</h3>'
                    f'<p>{e(x.get("note", ""))}</p>{where}</div></li>')
    if line:
        add("timeline", f'<ol class="tl">{"".join(line)}</ol>', _sample_note(entries))

    # -- quotes, plans, pictures, people (the sections that predate the templates)
    quotes = c.get("testimonials") or []
    if quotes:
        inner = '<div class="quotes">' + "".join(
            f'<figure class="tcard"><blockquote>{e(x.get("quote", ""))}</blockquote>'
            f'<figcaption>{e(x.get("attribution", ""))}</figcaption></figure>' for x in quotes) + "</div>"
        add("testimonials", inner, _sample_note(quotes), True)

    plans = c.get("pricing") or []
    if plans:
        cards = "".join(
            f'<article class="plan{" feat" if x.get("featured") else ""}"><h3>{e(x.get("name", ""))}</h3>'
            f'<p class="price">{e(x.get("price", ""))}</p><p class="blurb">{e(x.get("blurb", ""))}</p>'
            f'<ul>{"".join(f"<li>{e(i)}</li>" for i in (x.get("items") or []))}</ul></article>' for x in plans)
        add("pricing", f'<div class="plans">{cards}</div>', _sample_note(plans))

    shots = c.get("gallery") or []
    if shots:
        tiles_html = "".join(
            f'<figure>{_plate(tiles, x.get("title", ""))}'
            f'<figcaption><b>{e(x.get("title", ""))}</b><span>{e(x.get("caption", ""))}</span></figcaption></figure>'
            for x in shots)
        add("gallery", f'<div class="gtiles">{tiles_html}</div>', _sample_note(shots), True)

    people = c.get("team") or []
    if people:
        roles = "".join(
            f'<article class="rcard"><span class="kicker">{e(x.get("role", ""))}</span>'
            f'<p>{e(x.get("focus", ""))}</p></article>' for x in people)
        add("team", f'<div class="roles">{roles}</div>', _sample_note(people))

    # -- where it is and when it opens
    visit = c.get("visit") or {}
    hours = "".join(f'<div class="hrow"><b>{e(x.get("days", ""))}</b><span>{e(x.get("time", ""))}</span></div>'
                    for x in visit.get("hours") or [] if isinstance(x, dict))
    body = ((f'<address>{e(visit.get("address", ""))}</address>' if visit.get("address") else "")
            + (f'<div class="hours">{hours}</div>' if hours else "")
            + (f'<p class="travel">{e(visit.get("getting_here", ""))}</p>' if visit.get("getting_here") else ""))
    if body:
        add("visit", body, _doc_note(visit), True)

    # -- contact rows the owner can actually be reached on
    contact = c.get("contact") or {}
    paths = [f'<div><b>{label}</b><span>{e(contact.get(key))}</span></div>'
             for label, key in (("Email", "email"), ("Phone", "phone"), ("Where", "location"))
             if str(contact.get(key) or "").strip()]
    if contact.get("note"):
        paths.append(f'<div><b>Note</b><span>{e(contact["note"])}</span></div>')
    if paths:
        add("contact", f'<div class="paths">{"".join(paths)}</div>', "", True)

    book = c.get("booking") or {}
    if book.get("title") or book.get("intro") or book.get("options"):
        add("booking", _booking_html(book, contact), _doc_note(book), True)
    return out


# The fields each kind of booking asks for. A table needs a party size, a consultation needs a subject -
# one generic form for all of them is how a booking page ends up useless to the business using it.
BOOKING_FIELDS = {
    "reservation": (("date", "date", "Date"), ("time", "time", "Time"), ("number", "number", "How many")),
    "appointment": (("date", "date", "Preferred date"), ("time", "time", "Preferred time"),
                    ("text", "service", "What for")),
    "consultation": (("date", "date", "Preferred date"), ("text", "subject", "Subject"),
                     ("textarea", "detail", "A few lines about it")),
    "registration": (("text", "session", "Which session"), ("number", "places", "How many places")),
    "enquiry": (("text", "subject", "What you need"), ("textarea", "detail", "Details")),
}

# Which request a trade actually takes: a cafe books a table, a clinic an appointment, a school a place,
# an estate agent a viewing. The kind decides the fields above, so the form fits the business using it.
_BOOKING_KIND = {"restaurant": "reservation", "realestate": "enquiry", "health": "appointment",
                 "local": "appointment", "store": "appointment",
                 "legal": "consultation", "corporate": "consultation", "agency": "consultation",
                 "freelance": "consultation", "saas": "consultation", "ai": "consultation",
                 "portfolio": "consultation", "education": "registration", "event": "registration",
                 "media": "enquiry", "other": "appointment"}


def _booking_html(book: dict, contact: dict) -> str:
    """The booking form, and the plain words about where the request actually goes.

    A page in this product ships with no server, so a submitted booking can arrive nowhere. Saying so on
    the page is the difference between a reservation form and a fake one: the fields validate, the status
    line reports what happened, and the owner's real contact route is printed beside it when the brief
    supplied one.
    """
    e = _esc
    kind = str(book.get("kind") or "appointment")
    fields = BOOKING_FIELDS.get(kind, BOOKING_FIELDS["appointment"])
    options = [str(x) for x in (book.get("options") or []) if str(x or "").strip()]
    parts = []
    if book.get("intro"):
        parts.append(f'<p class="sub">{e(book["intro"])}</p>')
    rows = ['<label for="bk-name">Name</label><input id="bk-name" name="name" maxlength="80" required>',
            '<label for="bk-email">Email</label><input id="bk-email" name="email" type="email" '
            'autocomplete="email" required>']
    for itype, name, label in fields:
        fid = f"bk-{name}"
        if itype == "textarea":
            rows.append(f'<label for="{fid}">{e(label)}</label>'
                        f'<textarea id="{fid}" name="{name}" maxlength="600"></textarea>')
        elif itype == "select" or (name == "service" and options):
            opts = "".join(f'<option value="{e(o)}">{e(o)}</option>' for o in options)
            rows.append(f'<label for="{fid}">{e(label)}</label><select id="{fid}" name="{name}">{opts}</select>')
        else:
            extra = ' min="1" max="99"' if itype == "number" else ""
            rows.append(f'<label for="{fid}">{e(label)}</label>'
                        f'<input id="{fid}" name="{name}" type="{itype}"{extra} required>')
    parts.append('<form class="book" id="book" action="#" data-kind="' + e(kind) + '">'
                 + "".join(rows)
                 + '<button class="btn" type="submit">Send this request</button>'
                 + '<p id="bkmsg" role="status"></p></form>')
    route = [str(contact.get(k) or "").strip() for k in ("email", "phone")]
    reachable = " or ".join(f"<b>{e(x)}</b>" for x in route if x)
    parts.append('<p class="book-note">'
                 + (f'This page stores nothing. Until the booking feature is connected, use {reachable} - '
                    'the request below is checked here in the browser and nowhere else.'
                    if reachable else
                    'This page stores nothing: the request is checked here in the browser only, until the '
                    'booking feature is connected to your calendar or inbox.'))
    if book.get("note"):
        parts.append(f'<p class="muted-line">{e(book["note"])}</p>')
    return "".join(parts)


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

    art_map = _art_for(direction)
    tiles = _Tiles(art_map["tiles"], art_map.get("shots", 0))
    extras = _extra_sections(direction, c, tiles)
    parts = dict(extras)
    parts["features"] = _section_html("features", f'Why {c["product_name"]}',
                                      _features_html(direction, c, tiles))
    faqs = "".join(f'<details><summary>{e(x["question"])}</summary><p>{e(x["answer"])}</p></details>' for x in c["faq"])
    parts["faq"] = _section_html("faq", "Questions, answered", faqs, alt=True)
    form = (f'<form class="signup" id="signup" action="#">'
            f'<label for="email" style="position:absolute;left:-9999px">Email</label>'
            f'<input id="email" type="email" placeholder="you@example.com" required>'
            f'<button class="btn" type="submit">{e(c["cta"]["label"])}</button></form>'
            f'<p id="msg" role="status"></p>')
    parts["cta"] = _section_html("cta", c["cta"]["label"], f'<p class="sub">{e(c["cta"]["supporting_text"])}</p>{form}')

    ids = [name for name in direction.order if name in parts]
    hero_inner = _hero_html(direction, c, _nav_html(direction, c["product_name"], ids, _nav_labels(c, ids)), art_map) \
        + _stat_pills(direction, c)
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
<script>{_PAGE_JS}</script>
</body></html>"""


def design_sample_page(direction: variants.DesignDirection, business: str = "", idea: str = "") -> str:
    """One page drawn from a design direction, for the theme customizer's live preview and the template
    gallery's previews.

    This is the same `build_page` an offline run renders with, so the preview carries the real
    consequence of a theme: the `:root` block the theme editor patches, and the components that read it.
    The copy is the deterministic sample, with every stand-in placeholder marked `sample`, because a
    preview of *appearance* has no business inventing quotes, prices or screenshots.

    `business` decides which section names appear in the nav and headings (a cafe preview reads Menu),
    and `idea` supplies the subheadline the page is built around.
    """
    copy = _sample_copy("This page", "you",
                        idea or "Every colour, font and spacing value here is drawn from the theme you are setting",
                        list(direction.optional_sections()), business)
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
            blob = _all_text(messages)
            default = _sample_copy(name, aud, idea, _sections_from(blob), _business_from(blob))
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


def _sample_copy(name: str, aud: str, idea: str, sections: list[str], business: str = "") -> dict:
    """The offline Copywriter's answer: core copy, plus placeholder content for the sections the
    direction asks for. Everything invented here is marked `sample` so the page labels it and the
    user is never shown a testimonial or price the crew made up without saying so.

    `business` only changes the words a section is introduced with - a cafe's list is headed `Menu`,
    a school's `Courses` - because the same block reads differently in different trades. The
    placeholder content itself stays obviously a placeholder either way.
    """
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
    voice = _BUSINESS_TITLES.get(business, {})
    wanted = [key for key in variants.SECTIONS if key in sections and key in voice]
    if wanted:
        doc["titles"] = [{"section": key, "text": voice[key]} for key in wanted]
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

    # -- everything below is a block a template can ask for. Each is placeholder-shaped on purpose: a
    #    structure the owner can see and fill in, never an invented business fact.
    if "about" in sections:
        doc["about"] = {"intro": "Placeholder - say who you are and why this exists, in two sentences.",
                        "facts": [{"label": "Founded", "value": "Add the year", "sample": True},
                                  {"label": "Based in", "value": "Add the place", "sample": True}],
                        "credentials": ["Add a licence, membership or award here",
                                        "Add a second one here"], "sample": True}
    if "stats" in sections:
        doc["stats"] = [
            {"value": "000", "label": "Add the figure and what it counts", "sample": True},
            {"value": "00", "label": "Add the figure and what it counts", "sample": True},
            {"value": "0", "label": "Add the figure and what it counts", "sample": True}]
    if "skills" in sections:
        doc["skills"] = [
            {"group": "Works with", "items": ["Add an integration", "Add another"], "sample": True},
            {"group": "Built with", "items": ["Add a method", "Add another"], "sample": True}]
    if "services" in sections:
        doc["services"] = [
            {"name": "First service", "description": "What it covers, in one line the buyer recognises.",
             "detail": "Lead time goes here", "sample": True},
            {"name": "Second service", "description": "What it covers, in one line the buyer recognises.",
             "detail": "Starting point goes here", "sample": True},
            {"name": "Third service", "description": "What it covers, in one line the buyer recognises.",
             "detail": "", "sample": True}]
    if "work" in sections:
        doc["work"] = [
            {"client": "Client name", "sector": "Their industry", "title": "What the project was",
             "outcome": "What changed for them - one sentence, no invented numbers.",
             "metric": "", "sample": True},
            {"client": "Client name", "sector": "Their industry", "title": "What the project was",
             "outcome": "What changed for them - one sentence, no invented numbers.",
             "metric": "Add a result you can prove", "sample": True}]
    if "catalog" in sections:
        doc["catalog"] = [
            {"name": "First item", "note": "The line the buyer reads: what it is and who it suits.",
             "price": "Price goes here", "tag": "Category", "specs": ["Spec", "Spec"], "sample": True},
            {"name": "Second item", "note": "The line the buyer reads: what it is and who it suits.",
             "price": "Price goes here", "tag": "Category", "specs": [], "sample": True},
            {"name": "Third item", "note": "The line the buyer reads: what it is and who it suits.",
             "price": "", "tag": "Category", "specs": ["Spec"], "sample": True}]
    if "preview" in sections:
        doc["preview"] = {"title": "What the product shows",
                          "caption": "Placeholder drawing of the interface - replace it with a real "
                                     "screenshot once the product exists.",
                          "points": ["Name one thing a viewer can see here", "And one more"],
                          "device": "phone" if business in ("store", "restaurant", "event") else "window",
                          "sample": True}
    if "timeline" in sections:
        doc["timeline"] = [
            {"when": "Step 1", "title": "What happens first", "note": "One line about it.",
             "place": "", "sample": True},
            {"when": "Step 2", "title": "What happens next", "note": "One line about it.",
             "place": "Room, link or date goes here", "sample": True},
            {"when": "Step 3", "title": "Where it ends", "note": "One line about it.", "place": "",
             "sample": True}]
    if "visit" in sections:
        doc["visit"] = {"address": "Street, city and postcode go here.",
                        "hours": [{"days": "Mon - Fri", "time": "Add the hours"},
                                  {"days": "Saturday", "time": "Add the hours"},
                                  {"days": "Sunday", "time": "Closed - confirm this"}],
                        "getting_here": "One line on the nearest transport or parking.",
                        "sample": True}
    if "booking" in sections:
        kind = _BOOKING_KIND.get(business, "appointment")
        doc["booking"] = {"kind": kind, "title": voice.get("booking") or "Make a request",
                          "intro": "Fill this in and we will come back to you.",
                          "options": ["Option one", "Option two"],
                          "note": "Add how quickly you usually reply.", "sample": True}
    return doc
