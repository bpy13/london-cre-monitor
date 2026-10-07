"""Shared HTTP helpers so every tool uses the same timeout, User-Agent and
error handling. Keep network code out of individual tools where possible."""

from __future__ import annotations

import httpx

from cre_monitor.config import get_settings


def http_get(url: str, *, params: dict | None = None, timeout: float | None = None) -> httpx.Response:
    """GET ``url`` with project defaults and raise for non-2xx responses.

    Args:
        url: Absolute URL.
        params: Optional query parameters.
        timeout: Override the default timeout (seconds).

    Returns:
        The ``httpx.Response`` (already checked with ``raise_for_status``).

    Raises:
        httpx.HTTPError: On network failure or non-2xx status. Tools catch
        this and return an error string to the LLM instead of crashing.
    """
    s = get_settings()
    resp = httpx.get(
        url,
        params=params,
        headers={"User-Agent": s.http_user_agent},
        timeout=timeout or s.http_timeout_s,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp
