"""Pytest fixtures shared across test types, loaded for every test via ``pytest_plugins`` in
tests/conftest.py:

* ``fake_llm``    - demo mode off, every ``get_llm()`` routed to one scripted fake model.
* ``examples``    - two example reports in the (temporary) style/reports/ folder.
* ``api_refuses`` - live mode where every LLM call fails with the real 403 text.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from cre_monitor.config import get_settings
from cre_monitor.schemas import (
    Citation, ExecutiveSynthesis, Metric, Severity, Signal, SignalType, SkillFinding, SkillSelection,
)
from tests.support.fake_llm import ScriptedChatModel, submit_call, tool_call
from tests.support.samples import EXAMPLE_A, EXAMPLE_B, REAL_403


@pytest.fixture
def fake_llm(monkeypatch):
    """Turn demo mode off and route every get_llm() call to one scripted model."""
    monkeypatch.setenv("CRE_DEMO_MODE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()

    macro = SkillFinding(
        skill="ignored-llm-value",
        headline="Bank Rate held at 3.75%.",
        summary="Rates on hold; gilts elevated.",
        metrics=[Metric(key="bank_rate", submarket="UK", value=3.75, unit="%", period="2026-10",
                        source="Bank of England", url="https://www.bankofengland.co.uk/")],
        signals=[Signal(type=SignalType.RISK, severity=Severity.MEDIUM, title="Gilts elevated", rationale="r")],
        citations=[Citation(title="BoE IADB", url="https://www.bankofengland.co.uk/", publisher="Bank of England")],
        confidence=0.9,
    )
    model = ScriptedChatModel(
        responses=[
            AIMessage("", tool_calls=[
                tool_call("boe_series", {"name": "bank_rate"}, "c1"),
                tool_call("ons_series", {"name": "cpih_yoy"}, "c2"),
            ]),
            submit_call(macro),   # the skill delivers its result as a tool call
        ],
        # No "SkillFinding" entry on purpose: skills must not use a separate structured-output
        # call (it changes the tool list and breaks thinking-block signatures on the real API).
        structured={
            "SkillSelection": SkillSelection(skills=["macro-economy", "not-a-skill"], reasoning="rates question"),
            "ExecutiveSynthesis": ExecutiveSynthesis(
                title="London Office Market Brief - Test", executive_summary="Summary.", key_takeaways=["One"],
            ),
        },
    )
    # importlib is needed because graph/nodes/__init__.py re-exports functions with the
    # same names as their modules (e.g. `planner`), which shadows dotted-path lookups.
    for module in ("planner", "skill_runner", "synthesis", "chat_answer"):
        mod = importlib.import_module(f"cre_monitor.graph.nodes.{module}")
        monkeypatch.setattr(mod, "get_llm", lambda tier="skill": model)
    # Modules that import get_llm at call time (style learner / editor) read it from cre_monitor.llm.
    monkeypatch.setattr("cre_monitor.llm.get_llm", lambda tier="skill": model)
    model.__dict__["macro"] = macro  # handy for tests that script their own responses
    return model


@pytest.fixture
def examples(tmp_path) -> Path:
    folder = get_settings().style_dir / "reports"
    folder.mkdir(parents=True)
    (folder / "a.md").write_text(EXAMPLE_A, encoding="utf-8")
    (folder / "b.md").write_text(EXAMPLE_B, encoding="utf-8")
    (folder / "README.md").write_text("instructions - must be ignored", encoding="utf-8")
    return folder


@pytest.fixture
def api_refuses(monkeypatch):
    """Live mode, but every get_llm() call raises the real 403 error."""
    monkeypatch.setenv("CRE_DEMO_MODE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    get_settings.cache_clear()

    def refuse(tier="skill"):
        raise RuntimeError(REAL_403)

    for module in ("planner", "skill_runner", "synthesis", "chat_answer"):
        monkeypatch.setattr(importlib.import_module(f"cre_monitor.graph.nodes.{module}"), "get_llm", refuse)
