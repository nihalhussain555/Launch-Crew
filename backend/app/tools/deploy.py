"""Deploy the approved HTML to Netlify via its REST API (zip deploy). Falls back to a clearly-labelled simulation."""
import asyncio
import io
import re
import uuid
import zipfile
from dataclasses import dataclass

import httpx

from app.config import Settings

API = "https://api.netlify.com/api/v1"

# Netlify picks the response Content-Type from the file, and a deploy whose only page is reached at
# "/" can come back as text/plain - the browser then shows the source instead of rendering it.
# Pinning the header for both spellings of the root makes the page render either way.
HEADERS = """/index.html
  Content-Type: text/html; charset=utf-8

/
  Content-Type: text/html; charset=utf-8
"""


@dataclass
class DeployResult:
    url: str
    mock: bool = False
    site_id: str | None = None
    deploy_id: str | None = None
    warning: str | None = None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30] or "launch"


def _bundle(html: str) -> bytes:
    """The deploy archive: the page plus the header rules that keep it an HTML document."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("index.html", html)
        z.writestr("_headers", HEADERS)
    return buf.getvalue()


def _diagnose(status: int, content_type: str) -> str | None:
    """What a first-time visitor actually gets from the new URL. Both answers below have been seen in
    practice: Netlify serving our HTML bytes as text/plain (browser prints the source), and a team's
    visitor access turning every launch page into a login wall."""
    if status in (401, 403):
        return (f"Netlify answers {status} for that URL, so it is not public yet - in Netlify: "
                "Site configuration > Access control & security > Visitor access > Public")
    if status >= 400:
        return f"the live URL answered {status}"
    if "text/html" not in content_type:
        return f"the live URL is serving {content_type.split(';')[0].strip() or 'no Content-Type'}, not HTML"
    return None


async def _probe(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            page = await c.get(url)
    except httpx.HTTPError as exc:
        return f"the live URL could not be reached ({type(exc).__name__})"
    return _diagnose(page.status_code, page.headers.get("content-type", ""))


async def deploy_html(html: str, name_hint: str, settings: Settings) -> DeployResult:
    if not settings.netlify_auth_token:
        return DeployResult(url=f"https://{_slug(name_hint)}-{uuid.uuid4().hex[:6]}.netlify.app", mock=True)

    payload = _bundle(html)
    headers = {"Authorization": f"Bearer {settings.netlify_auth_token}"}

    async with httpx.AsyncClient(base_url=API, headers=headers, timeout=60) as c:
        site = await c.post("/sites", json={"name": f"lc-{_slug(name_hint)}-{uuid.uuid4().hex[:6]}"})
        site.raise_for_status()
        site_json = site.json()
        dep = await c.post(f"/sites/{site_json['id']}/deploys", content=payload, headers={"Content-Type": "application/zip"})
        dep.raise_for_status()
        dep_json = dep.json()
        for _ in range(30):  # poll up to ~60s for "ready"
            state = dep_json.get("state")
            if state == "ready":
                break
            if state == "error":
                raise RuntimeError(f"Netlify deploy failed: {dep_json.get('error_message')}")
            await asyncio.sleep(2)
            dep_json = (await c.get(f"/deploys/{dep_json['id']}")).json()
        else:
            raise RuntimeError("Netlify deploy timed out")
        url = site_json.get("ssl_url") or site_json.get("url")
        return DeployResult(url=url, site_id=site_json["id"], deploy_id=dep_json["id"], warning=await _probe(url))
