"""SSRF guard: the agent may only fetch public http(s) URLs (tools/_http.py). No network needed."""

from __future__ import annotations

import pytest

from cre_monitor.config import get_settings
from cre_monitor.tools._http import BlockedURL, check_public_url


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",                         # not http(s)
    "ftp://example.com/x",
    "http://127.0.0.1:8501/",                     # loopback (e.g. this app's own UI)
    "http://localhost/admin",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata endpoint
    "http://10.0.0.5/intranet",                   # private ranges
    "http://192.168.1.1/",
    "http://[::1]/",
])
def test_internal_or_non_http_urls_are_blocked(url):
    with pytest.raises(BlockedURL):
        check_public_url(url)


def test_public_ip_literal_is_allowed():
    check_public_url("https://8.8.8.8/")          # literal public IP: no DNS lookup needed


def test_fetch_document_reports_a_blocked_url_to_the_agent(monkeypatch):
    from cre_monitor.tools import TOOLS

    monkeypatch.setenv("CRE_OFFLINE", "0")
    get_settings.cache_clear()
    out = TOOLS["fetch_document"].invoke({"url": "http://169.254.169.254/latest/meta-data/"})
    assert "non-public address" in out                         # error text, no request sent
