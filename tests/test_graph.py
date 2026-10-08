"""End-to-end graph tests.

* Demo path: the whole pipeline (planner -> parallel skills -> validator ->
  persist -> synthesis -> report / chat answer) with canned findings.
* LLM path: the real ReAct skill sub-agent driven by a scripted fake model
  that issues genuine tool calls against offline fixtures.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from cre_monitor.config import get_settings
from cre_monitor.graph.builder import ask, build_graph, run_brief
from cre_monitor.graph.nodes.planner import keyword_route
from cre_monitor.schemas import Citation, ExecutiveSynthesis, Metric, Severity, Signal, SignalType, SkillFinding, SkillSelection
from tests.fake_llm import ScriptedChatModel, tool_call

# --------------------------------------------------------------------------
# Demo mode (no LLM)
# --------------------------------------------------------------------------


def test_brief_demo_end_to_end_writes_report(monkeypatch):
    monkeypatch.setenv("REPORT_PNG", "1")  # exercise the kaleido PNG path once
    get_settings.cache_clear()
    state = run_brief()
    findings = state["findings"]
    assert len(findings) == 8 and not any(f.error for f in findings)
    assert state["synthesis"].key_takeaways

    html = Path(state["report_paths"]["html"]).read_text(encoding="utf-8")
    md = Path(state["report_paths"]["markdown"]).read_text(encoding="utf-8")
    for section in ("Executive summary", "Risks &amp; opportunities", "Research by topic", "Sources"):
        assert section in html
    assert "plotly" in html.lower() and "chart-prime_rent_by_submarket" in html
    assert "## Executive summary" in md and "&amp;" not in md  # markdown must not be HTML-escaped
    pngs = list((Path(state["report_paths"]["html"]).parent / "charts" / state["run_id"]).glob("*.png"))
    assert pngs, "expected PNG charts (kaleido needs a local Chrome - run `plotly_get_chrome`)"
    assert f"](charts/{state['run_id']}/" in md


def test_same_day_briefs_keep_their_own_charts(monkeypatch):
    """Regression: a second brief on the same day must not overwrite the first's PNGs."""
    import cre_monitor.reporting.render as render

    def fake_export(figures, charts_dir, rel_prefix):  # no Chrome needed
        for cid in figures:
            (charts_dir / f"{cid}.png").write_bytes(b"png")
        return {cid: f"{rel_prefix}/{cid}.png" for cid in figures}

    monkeypatch.setattr(render, "export_pngs", fake_export)
    monkeypatch.setenv("REPORT_PNG", "1")
    get_settings.cache_clear()

    first, second = run_brief(), run_brief()
    for state in (first, second):
        md_path = Path(state["report_paths"]["markdown"])
        links = [line.split("](")[1].rstrip(")") for line in md_path.read_text(encoding="utf-8").splitlines()
                 if line.startswith("![")]
        assert links and all(f"charts/{state['run_id']}/" in link for link in links)
        assert all((md_path.parent / link).exists() for link in links)
    assert first["run_id"] != second["run_id"]


def test_first_brief_detects_changes_vs_seeded_history():
    state = run_brief()
    # Seed history ends one quarter before the fixture findings -> deltas exist.
    assert state["deltas"], "expected period-on-period changes vs seeded history"
    assert state["synthesis"].what_changed


def test_brief_skill_subset():
    state = run_brief(["office-rents", "macro-economy"])
    assert sorted(f.skill for f in state["findings"]) == ["macro-economy", "office-rents"]


def test_unknown_skill_override_raises():
    with pytest.raises(ValueError, match="Unknown skills"):
        build_graph().invoke({"mode": "brief", "messages": [], "skills_override": ["nope"]})


def test_keyword_routing():
    assert keyword_route("What is the prime rent in Mayfair?")[0] == "office-rents"
    assert "macro-economy" in keyword_route("Will the Bank of England cut interest rates?")
    assert "supply-pipeline" in keyword_route("How much speculative development completes in 2027?")


def test_chat_demo_multi_turn_resets_findings():
    first = ask("What is happening with interest rates?", thread_id="t1")
    assert "macro-economy" in first["selected_skills"]
    assert first["answer"]
    second = ask("And Canary Wharf vacancy?", thread_id="t1")
    # Findings are per turn (not accumulated), messages are per thread (accumulated).
    assert {f.skill for f in second["findings"]} == set(second["selected_skills"])
    assert len(second["messages"]) == 4


# --------------------------------------------------------------------------
# LLM path with a scripted fake model
# --------------------------------------------------------------------------


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
            AIMessage("I have enough evidence."),
        ],
        structured={
            "SkillFinding": macro,
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
    return model


def test_llm_skill_agent_calls_tools_and_returns_structured_finding(fake_llm):
    state = run_brief(["macro-economy"])
    (finding,) = state["findings"]
    assert finding.skill == "macro-economy"  # overwritten, not trusted from the LLM
    assert finding.metrics[0].value == 3.75

    # The second LLM turn must have received both tool results from the fixtures.
    tool_msgs = [m for m in fake_llm.calls[1] if isinstance(m, ToolMessage)]
    assert {m.tool_call_id for m in tool_msgs} == {"c1", "c2"}
    assert "Bank Rate" in tool_msgs[0].content
    # The system prompt carried the skill instructions (progressive disclosure level 2).
    assert "SKILL INSTRUCTIONS: macro-economy" in fake_llm.calls[0][0].content
    assert state["synthesis"].title == "London Office Market Brief - Test"


def test_llm_router_filters_unknown_skills(fake_llm):
    fake_llm.responses.append(AIMessage("Bank Rate is 3.75% [Bank of England](https://www.bankofengland.co.uk/)."))
    state = ask("Where are interest rates?", thread_id="llm")
    assert state["selected_skills"] == ["macro-economy"]
    assert state["answer"].startswith("Bank Rate is 3.75%")
