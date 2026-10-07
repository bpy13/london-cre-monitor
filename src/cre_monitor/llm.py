"""Chat model factory.

All LLM construction goes through :func:`get_llm` so that:

* model choice is driven by *tier* (``router`` / ``skill`` / ``synthesis``)
  configured in :mod:`cre_monitor.config`, never hard-coded in nodes;
* tests can swap in a fake model by patching one function
  (see ``tests/conftest.py``).
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

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


def get_llm(tier: str = "skill") -> BaseChatModel:
    """Return a chat model for the given tier.

    Args:
        tier: ``"router"``, ``"skill"`` or ``"synthesis"``.

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
    from langchain_anthropic import ChatAnthropic

    # No `temperature`: Claude Opus 5.5 / Sonnet 5.5 reject non-default sampling
    # parameters. Depth and cost are controlled with `effort` instead.
    effort_field = _TIER_TO_EFFORT.get(tier)
    extra = {"output_config": {"effort": getattr(s, effort_field)}} if effort_field else {}
    return ChatAnthropic(
        model=getattr(s, _TIER_TO_SETTING[tier]),
        api_key=s.anthropic_api_key,
        max_tokens=s.llm_max_tokens,
        max_retries=3,
        **extra,
    )
