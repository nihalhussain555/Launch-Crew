"""The deploy bundle: the page itself, the header rules that stop it arriving as plain text, and the
post-deploy probe that tells the truth about what a visitor gets."""
import io
import zipfile

from app.config import Settings
from app.tools.deploy import HEADERS, _bundle, _diagnose, deploy_html

PAGE = "<!DOCTYPE html>\n\n<html lang=\"en\"><head><title>Clip</title></head><body><h1>Clip</h1></body></html>"


def entries(payload: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        return {i.filename: z.read(i).decode("utf-8") for i in z.infolist()}


def test_bundle_carries_the_page_and_header_rules():
    files = entries(_bundle(PAGE))
    assert files["index.html"] == PAGE
    assert "_headers" in files


def test_header_rules_pin_html_for_both_root_spellings():
    blocks = [b for b in entries(_bundle(PAGE))["_headers"].split("\n\n") if b.strip()]
    paths = {b.splitlines()[0].strip() for b in blocks}
    assert {"/index.html", "/"} <= paths
    for block in blocks:
        assert "Content-Type: text/html" in block


async def test_deploy_without_a_token_stays_simulated():
    settings = Settings(_env_file=None, netlify_auth_token="")
    result = await deploy_html(PAGE, "Podcast Clip Generator", settings)
    assert result.mock and result.url.startswith("https://podcast-clip-generator-")
    assert result.warning is None


def test_a_rendering_page_passes_the_probe_silently():
    assert _diagnose(200, "text/html; charset=utf-8") is None


def test_the_probe_names_the_two_failures_we_actually_saw():
    plain = _diagnose(200, "text/plain; charset=utf-8")
    assert plain and "text/plain" in plain and "not HTML" in plain
    gated = _diagnose(401, "text/html; charset=utf-8")
    assert "Visitor access" in gated and "Public" in gated        # tells the user where to click
    assert "500" in _diagnose(500, "text/html")
