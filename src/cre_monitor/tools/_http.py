"""Shared HTTP helpers so every tool uses the same timeout, User-Agent, error handling and
network guard. Keep network code out of individual tools where possible.

**Network guard (SSRF protection).** URLs fetched by the agent are chosen by the model,
which reads untrusted web pages and user-supplied reports - text that could try to steer
it towards internal addresses (cloud metadata endpoints, intranet services). So every
request, *including each redirect hop*, must be ``http(s)`` to a host that resolves only
to public IP addresses; anything else raises :class:`BlockedURL`. (A hostile DNS server
could still answer differently between the check and the connection; acceptable for this
use, and hosting behind an egress firewall closes that gap.)
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from cre_monitor.config import get_settings


class BlockedURL(ValueError):
    """The URL is not allowed: not http(s), or it points at a private / internal address."""


def check_public_url(url: str) -> None:
    """Raise :class:`BlockedURL` unless ``url`` is http(s) and its host resolves to public IPs only."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BlockedURL(f"Only http(s) URLs can be fetched, not {url!r}.")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise httpx.ConnectError(f"Cannot resolve {parts.hostname}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])  # strip IPv6 zone ids
        if not ip.is_global:
            raise BlockedURL(f"Refusing to fetch {parts.hostname}: it resolves to a non-public address ({ip}).")


def _guard(request: httpx.Request) -> None:
    check_public_url(str(request.url))


def http_get(url: str, *, params: dict | None = None, timeout: float | None = None) -> httpx.Response:
    """GET ``url`` with project defaults and raise for non-2xx responses.

    Args:
        url: Absolute URL.
        params: Optional query parameters.
        timeout: Override the default timeout (seconds).

    Returns:
        The ``httpx.Response`` (already checked with ``raise_for_status``).

    Raises:
        BlockedURL: Not http(s), or the host (or a redirect target) is private/internal.
        httpx.HTTPError: On network failure or non-2xx status. Tools catch errors and
            return an error string to the LLM instead of crashing.
    """
    s = get_settings()
    # The request hook runs for the first request and for every redirect hop.
    with httpx.Client(headers={"User-Agent": s.http_user_agent}, timeout=timeout or s.http_timeout_s,
                      follow_redirects=True, event_hooks={"request": [_guard]}) as client:
        resp = client.get(url, params=params)
    resp.raise_for_status()
    return resp
