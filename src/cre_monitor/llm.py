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

    return ChatAnthropic(
        model=getattr(s, _TIER_TO_SETTING[tier]),
        api_key=s.anthropic_api_key,
        temperature=s.llm_temperature,
        max_tokens=s.llm_max_tokens,
        max_retries=3,
    )
