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


@dataclass
class DeployResult:
    url: str
    mock: bool = False
    site_id: str | None = None
    deploy_id: str | None = None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30] or "launch"


async def deploy_html(html: str, name_hint: str, settings: Settings) -> DeployResult:
    if not settings.netlify_auth_token:
        return DeployResult(url=f"https://{_slug(name_hint)}-{uuid.uuid4().hex[:6]}.netlify.app", mock=True)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("index.html", html)
    headers = {"Authorization": f"Bearer {settings.netlify_auth_token}"}

    async with httpx.AsyncClient(base_url=API, headers=headers, timeout=60) as c:
        site = await c.post("/sites", json={"name": f"lc-{_slug(name_hint)}-{uuid.uuid4().hex[:6]}"})
        site.raise_for_status()
        site_json = site.json()
        dep = await c.post(f"/sites/{site_json['id']}/deploys", content=buf.getvalue(), headers={"Content-Type": "application/zip"})
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
        return DeployResult(url=site_json.get("ssl_url") or site_json.get("url"), site_id=site_json["id"], deploy_id=dep_json["id"])
