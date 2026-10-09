"""SEO audit of the built page.

Every check here is measurable from the document itself; where the fix is a tag the page is
missing, the instruction spells out that exact tag so the repair step can insert it. The
suggested description is built from the page's own approved copy - not invented.
"""
from __future__ import annotations

import html as html_mod
import json
import re

from app.tools import audit_util as au

GENERIC_LINK_TEXT = {"here", "click here", "link", "read more", "more", "this", "go", "learn more"}


def _meta(page, *, name=None, prop=None):
    if name:
        return page.find("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
    return page.find("meta", attrs={"property": re.compile(f"^{re.escape(prop)}$", re.I)})


def _esc(value: str) -> str:
    return html_mod.escape(value[:200], quote=True)


def suggest_description(headline: str, subheadline: str) -> str:
    """A meta description from the approved copy: subheadline first, headline as fallback."""
    text = (subheadline or "").strip() or (headline or "").strip()
    text = re.sub(r"\s+-\s+", " - ", text)
    text = text.rstrip(". ")
    if len(text) > 155:
        cut = text[:155].rsplit(" ", 1)[0]
        text = cut if len(cut) >= 80 else text[:152].rstrip() + "..."
    return text


def jsonld(name: str, description: str, url: str | None = None) -> str:
    graph = {"@context": "https://schema.org", "@type": "WebSite", "name": name, "description": description}
    if url:
        graph["url"] = url
    return json.dumps(graph, separators=(",", ":"))


def scan(html: str, *, keywords: tuple[str, ...] | list[str] = (), name: str = "", headline: str = "",
         subheadline: str = "", deploy_url: str | None = None) -> list[dict]:
    page = au.soup(html)
    findings: list[dict] = []

    description = suggest_description(headline, subheadline) or (headline or name or "Product")
    og_needed = [("og:title", name or headline), ("og:description", description), ("og:type", "website")]
    if deploy_url:
        og_needed.append(("og:url", deploy_url))

    title = (page.title.get_text(strip=True) if page.title else "")
    if not title:
        findings.append(au.finding("title", "Title tag present", au.FAIL,
                                   "The document has no <title>.",
                                   f'Add in <head>: <title>{_esc(name or headline or "Product")}</title>'))
    elif len(title) < 10 or len(title) > 65:
        findings.append(au.finding("title", "Title length works in search results", au.WARN,
                                   f'{len(title)} characters: "{title[:60]}"',
                                   "Rewrite the <title> so it is 10-65 characters and starts with the product name."))
    else:
        findings.append(au.ok("title", "Title tag present and well sized", f'{len(title)} characters: "{title[:60]}"'))

    desc = _meta(page, name="description")
    if not desc or not (desc.get("content") or "").strip():
        findings.append(au.finding("description", "Meta description present", au.FAIL,
                                   "No <meta name=description>, so search engines write their own snippet.",
                                   f'Add in <head>: <meta name="description" content="{_esc(description)}">'))
    else:
        content = desc["content"].strip()
        if len(content) < 50 or len(content) > 160:
            findings.append(au.finding("description", "Meta description length", au.WARN,
                                       f"{len(content)} characters (50-160 is shown in full).",
                                       "Rewrite the meta description to 50-160 characters."))
        else:
            findings.append(au.ok("description", "Meta description present and well sized", f"{len(content)} characters"))

    h1s = page.find_all("h1")
    if not h1s:
        findings.append(au.finding("h1", "Exactly one H1", au.FAIL, "No <h1> in the document.",
                                   "Give the page one <h1> containing the main value proposition."))
    elif len(h1s) > 1:
        findings.append(au.finding("h1", "Exactly one H1", au.FAIL, f"{len(h1s)} <h1> elements found.",
                                   "Keep one <h1> (the headline); make the others <h2>."))
    else:
        findings.append(au.ok("h1", "Exactly one H1", f'"{h1s[0].get_text(" ", strip=True)[:60]}"'))

    seq = au.heading_sequence(page)
    skips = [f"h{seq[i - 1]} to h{seq[i]}" for i in range(1, len(seq)) if seq[i] - seq[i - 1] > 1]
    findings.append(au.ok("heading_order", "Heading levels do not skip", f"{len(seq)} headings")
                    if not skips else
                    au.finding("heading_order", "Heading levels do not skip", au.WARN,
                               "Skipped a level: " + ", ".join(skips[:4]),
                               "Re-level the headings so each step moves by one level, and nest sections under the "
                               "heading above them."))

    viewport = _meta(page, name="viewport")
    findings.append(au.ok("viewport", "Viewport declared (mobile indexing)", (viewport.get("content") or "")[:60])
                    if viewport else
                    au.finding("viewport", "Viewport declared (mobile indexing)", au.FAIL,
                               "No <meta name=viewport>; the page is judged not mobile-friendly.",
                               'Add in <head>: <meta name="viewport" content="width=device-width, initial-scale=1">'))

    robots = _meta(page, name="robots")
    if robots and "noindex" in (robots.get("content") or "").lower():
        findings.append(au.finding("robots", "Page is indexable", au.FAIL,
                                   f'robots="{robots["content"]}" blocks indexing.',
                                   "Remove the noindex directive from the robots meta tag."))
    else:
        findings.append(au.ok("robots", "Page is indexable", "no robots directive blocking indexes"))

    missing_og = [k for k, _v in og_needed if not (_meta(page, prop=k) if k.startswith("og:") else _meta(page, name=k))]
    if not _meta(page, name="twitter:card"):
        missing_og.append("twitter:card")
    if missing_og:
        want = {k: v for k, v in og_needed}
        want["twitter:card"] = "summary_large_image"
        tags = ", ".join(f'<meta {"property" if k.startswith("og:") else "name"}="{k}" content="{_esc(str(want[k]))}">'
                         for k in missing_og)
        findings.append(au.finding("social_preview", "Social cards (Open Graph / Twitter) present", au.WARN,
                                   "Missing: " + ", ".join(missing_og),
                                   f"Add in <head>: {tags}"))
    else:
        findings.append(au.ok("social_preview", "Social cards (Open Graph / Twitter) present",
                              f"{len(og_needed) + 1} preview tags"))

    if not page.find("script", type="application/ld+json"):
        findings.append(au.finding("structured_data", "Structured data (JSON-LD) present", au.WARN,
                                   "No schema.org markup, so the page cannot earn a rich result or branded sitelink.",
                                   f'Add in <head>: <script type="application/ld+json">{jsonld(name or headline, description, deploy_url)}</script>'))
    else:
        findings.append(au.ok("structured_data", "Structured data (JSON-LD) present"))

    words = au.visible_text(page).split()
    body = " ".join(words).lower()
    title_blob = " ".join([title, *(h.get_text(" ", strip=True) for h in page.find_all(re.compile("^h[1-6]$")))]).lower()
    found = [k for k in keywords if k and k.lower() in body]
    in_titles = [k for k in keywords if k and k.lower() in title_blob]
    if len(words) < 120:
        findings.append(au.finding("content_depth", "Enough content to rank", au.WARN,
                                   f"{len(words)} words of visible text.",
                                   "Ask the copywriter to expand the feature and FAQ sections; thin pages get skipped."))
    elif not found:
        findings.append(au.finding("content_depth", "Enough content to rank", au.WARN,
                                   f"{len(words)} words, but none of the researched keywords appear in the body.",
                                   "Rewrite the headline and section copy to include the researched keywords naturally."))
    else:
        findings.append(au.ok("content_depth", "Content depth and keywords",
                              f"{len(words)} words; {len(found)}/{len(list(keywords))} researched keywords in the body"
                              f" ({', '.join(found[:3])}); {len(in_titles)} in headings"))

    generic = [text for _href, text in au.anchors(page) if text.lower().strip(". ") in GENERIC_LINK_TEXT]
    findings.append(au.ok("link_text", "Link text describes its target", f"{len(generic)} generic")
                    if not generic else
                    au.finding("link_text", "Link text describes its target", au.WARN,
                               "Generic labels: " + ", ".join(generic[:4]),
                               "Rewrite the link text to name what the reader gets, in the page's own words."))

    imgs = page.find_all("img")
    if not imgs:
        findings.append(au.ok("images_seo", "Image assets", "No raster images: the page carries no image weight and "
                                                            "has no alt-text debt."))
    else:
        empty_alt = [i for i in imgs if not (i.get("alt") or "").strip()]
        findings.append(au.ok("images_seo", "Images are described and named", f"{len(imgs)} image(s)")
                        if not empty_alt else
                        au.finding("images_seo", "Images are described and named", au.WARN,
                                   f"{len(empty_alt)} image(s) with empty or missing alt.",
                                   "Give each content image a short, literal alt description."))

    if deploy_url:
        findings.append(au.finding("indexing", "Submit the live URL for indexing", au.INFO,
                                   f"The page is live at {deploy_url}. Nothing in the build pings a sitemap, so the "
                                   "first crawl depends on you: submit the URL in Google Search Console and add it to "
                                   "a sitemap.", severity=au.INFO_SEVERITY))
    else:
        findings.append(au.finding("indexing", "Indexing starts at deploy", au.INFO,
                                   "The page is not deployed yet, so there is nothing for a crawler to reach. After "
                                   "approval, submit the live URL in Google Search Console.",
                                   severity=au.INFO_SEVERITY))

    return findings
