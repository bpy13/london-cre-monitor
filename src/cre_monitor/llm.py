"""Chat model factory.

All LLM construction goes through :func:`get_llm` so that:

* model choice is driven by *tier* (``router`` / ``skill`` / ``synthesis``)
  configured in :mod:`cre_monitor.config`, never hard-coded in nodes;
* the HTTP transport (proxy, CA bundle, timeouts) is configured in one place
  (:func:`build_http_clients`) and injected into every model;
* tests can swap in a fake model by patching one function
  (see ``tests/conftest.py``).

HTTP client injection
---------------------
LangChain's ``ChatAnthropic`` has no ``http_client`` argument: it builds its
Anthropic SDK client internally in a cached ``_client`` property. The
:class:`ChatAnthropicHTTP` subclass below adds ``http_client`` /
``http_async_client`` fields and uses them when provided, otherwise it falls
back to LangChain's default behaviour unchanged.

Note: ``anthropic`` 1.x is built on **httpx2**, not ``httpx``. Pass
``anthropic.DefaultHttpxClient`` / ``DefaultAsyncHttpxClient`` (subclasses of
``httpx2.Client``, which keep the SDK's default connection limits) - a client
from the ``httpx`` package is rejected by the SDK.
"""

from __future__ import annotations

from functools import cached_property, lru_cache
from typing import Any

from langchain_core.language_models import BaseChatModel
from pydantic import Field

from cre_monitor.config import get_settings

_TIER_TO_SETTING = {
    "router": "model_router",
    "skill": "model_skill",
    "synthesis": "model_synthesis",
}
#: Tier -> settings field holding its reasoning effort (router has none: Haiku 4.5
#: rejects the effort parameter).
_TIER_TO_EFFORT = {"skill": "effort_skill", "synthesis": "effort_synthesis"}

#: Use with ``llm.with_structured_output(Schema, **STRUCTURED)``. Native
#: structured outputs (JSON schema) - current models reject *forced* tool calls,
#: which is how the default "function_calling" method guarantees a result.
STRUCTURED = {"method": "json_schema"}


@lru_cache(maxsize=1)
def _chat_anthropic_http_class():
    """Define the subclass lazily so importing this module never requires
    ``langchain_anthropic`` (demo mode and most tests don't need it)."""
    import anthropic
    from langchain_anthropic import ChatAnthropic

    class ChatAnthropicHTTP(ChatAnthropic):
        """``ChatAnthropic`` that accepts pre-built HTTP clients.

        Both fields are optional; ``None`` keeps LangChain's default client.
        They are excluded from serialisation (not JSON-safe, and may hold
        credentials such as proxy auth).
        """

        http_client: Any = Field(default=None, exclude=True)
        """Sync client, e.g. ``anthropic.DefaultHttpxClient(proxy=...)``."""
        http_async_client: Any = Field(default=None, exclude=True)
        """Async client, e.g. ``anthropic.DefaultAsyncHttpxClient(proxy=...)``."""

        @cached_property
        def _client(self) -> anthropic.Client:
            if self.http_client is None:
                return ChatAnthropic._client.func(self)
            return anthropic.Client(**self._client_params, http_client=self.http_client)

        @cached_property
        def _async_client(self) -> anthropic.AsyncClient:
            if self.http_async_client is None:
                return ChatAnthropic._async_client.func(self)
            return anthropic.AsyncClient(**self._client_params, http_client=self.http_async_client)

    return ChatAnthropicHTTP


def build_http_clients() -> tuple[Any, Any]:
    """Build the sync + async HTTP clients from settings.

    Returns ``(None, None)`` when no custom transport setting is in use, so the
    SDK defaults apply. Settings: ``LLM_PROXY_URL``, ``LLM_CA_BUNDLE``,
    ``LLM_TIMEOUT_S``, ``LLM_CONNECT_TIMEOUT_S``.
    """
    import anthropic

    s = get_settings()
    customised = s.llm_proxy_url or s.llm_ca_bundle or s.llm_timeout_s != 600.0 or s.llm_connect_timeout_s != 10.0
    if not customised:
        return None, None
    kwargs: dict[str, Any] = {
        "timeout": anthropic.Timeout(s.llm_timeout_s, connect=s.llm_connect_timeout_s),
    }
    if s.llm_proxy_url:
        kwargs["proxy"] = s.llm_proxy_url
    if s.llm_ca_bundle:
        kwargs["verify"] = str(s.llm_ca_bundle)
    return anthropic.DefaultHttpxClient(**kwargs), anthropic.DefaultAsyncHttpxClient(**kwargs)


def get_llm(tier: str = "skill", *, http_client: Any = None, http_async_client: Any = None) -> BaseChatModel:
    """Return a chat model for the given tier.

    Args:
        tier: ``"router"``, ``"skill"`` or ``"synthesis"``.
        http_client: Optional sync HTTP client to inject (overrides settings).
        http_async_client: Optional async HTTP client to inject (overrides settings).

    Raises:
        RuntimeError: If called in demo mode (no API key) - nodes must check
            ``settings.cre_demo_mode`` and use their rule-based path instead.
    """
    s = get_settings()
    if s.cre_demo_mode:
        raise RuntimeError(
            "LLM requested while CRE_DEMO_MODE is on. Set ANTHROPIC_API_KEY "
            "(and CRE_DEMO_MODE=0) to use the real agent."
        )
    if http_client is None and http_async_client is None:
        http_client, http_async_client = build_http_clients()

    # No `temperature`: Claude Opus 5.5 / Sonnet 5.5 reject non-default sampling
    # parameters. Depth and cost are controlled with `effort` instead.
    effort_field = _TIER_TO_EFFORT.get(tier)
    extra = {"output_config": {"effort": getattr(s, effort_field)}} if effort_field else {}
    return _chat_anthropic_http_class()(
        model=getattr(s, _TIER_TO_SETTING[tier]),
        api_key=s.anthropic_api_key,
        max_tokens=s.llm_max_tokens,
        max_retries=3,
        http_client=http_client,
        http_async_client=http_async_client,
        **extra,
    )
