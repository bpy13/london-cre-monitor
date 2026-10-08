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
from tests.fake_llm import ScriptedChatModel, submit_call, tool_call

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
    model.__dict__["macro"] = macro  # handy for tests that script their own responses
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


def test_skill_conversation_is_append_only_with_one_tool_list(fake_llm):
    """Regression for the live 400 'Invalid signature in thinking block ... tools list differs'.

    Every request in a skill must use the same tool list, and each request must
    extend the previous one (never edit or drop earlier messages).
    """
    run_brief(["macro-economy"])
    assert len(fake_llm.bound_tools) == 1 and fake_llm.bound_tools[0][-1] == "submit_finding"
    assert not any(k == "structured:SkillFinding" for k in fake_llm.kinds)   # no separate output call
    skill_calls = [c for c in fake_llm.calls if "SKILL INSTRUCTIONS" in str(c[0].content)]
    assert len(skill_calls) == 2
    for earlier, later in zip(skill_calls, skill_calls[1:]):
        assert later[: len(earlier)] == earlier                               # strictly append-only


def _skill_run(fake_llm, responses):
    from cre_monitor.graph.nodes.skill_runner import run_skill

    fake_llm.responses[:] = responses
    return run_skill("macro-economy", "Where is Bank Rate?")


def test_plain_text_answer_gets_a_nudge_then_submits(fake_llm):
    from cre_monitor.graph.nodes.skill_runner import NUDGE_PROMPT

    finding = _skill_run(fake_llm, [AIMessage("Bank Rate is 3.75%."), submit_call(fake_llm.macro)])
    assert finding.error is None and finding.metrics[0].value == 3.75
    assert fake_llm.calls[1][-1].content == NUDGE_PROMPT                      # appended, not replaced


def test_invalid_submission_is_returned_as_tool_error_and_resubmitted(fake_llm):
    bad = AIMessage("", tool_calls=[tool_call("submit_finding", {"headline": "missing summary"}, "s1")])
    finding = _skill_run(fake_llm, [bad, submit_call(fake_llm.macro, "s2")])
    assert finding.error is None
    feedback = fake_llm.calls[1][-1]
    assert isinstance(feedback, ToolMessage) and feedback.tool_call_id == "s1"
    assert "Invalid submission" in feedback.content


def test_budget_exhausted_asks_to_wrap_up(fake_llm, monkeypatch):
    from cre_monitor.graph.nodes.skill_runner import WRAP_UP_PROMPT

    monkeypatch.setenv("SKILL_MAX_STEPS", "1")
    get_settings.cache_clear()
    research = AIMessage("", tool_calls=[tool_call("boe_series", {"name": "bank_rate"}, "c1")])
    finding = _skill_run(fake_llm, [research, submit_call(fake_llm.macro)])
    assert finding.error is None
    last_request = fake_llm.calls[1]
    assert isinstance(last_request[-2], ToolMessage) and last_request[-1].content == WRAP_UP_PROMPT


def test_agent_that_never_submits_becomes_error_finding(fake_llm):
    finding = _skill_run(fake_llm, [AIMessage("text 1"), AIMessage("text 2"), AIMessage("text 3")])
    assert finding.error and "did not submit" in finding.error


def test_llm_references_reach_router_and_answer_but_never_skills(fake_llm):
    from langchain_core.messages import SystemMessage

    from cre_monitor.store import get_conversation_store

    get_conversation_store().record_turn("earlier01", "Where was Bank Rate in September?", "Bank Rate was 3.75%.")
    fake_llm.responses.append(AIMessage("Still 3.75%, unchanged since our 7 Oct conversation."))

    state = ask("Has Bank Rate changed since then?", thread_id="llm-refs", refs=["earlier01"])
    assert state["context_refs"] == ["earlier01"]

    def system_text(call):
        return " ".join(m.content for m in call if isinstance(m, SystemMessage))

    marker = 'EARLIER CONVERSATION "Where was Bank Rate in September?"'
    router_call, *middle, answer_call = fake_llm.calls
    assert marker in system_text(router_call)                       # router sees the context pack
    assert marker in system_text(answer_call)                       # answer step sees it ...
    assert "Current RESEARCH FINDINGS take precedence" in system_text(answer_call)  # ... with the rules
    skill_calls = [c for c in middle if "SKILL INSTRUCTIONS" in system_text(c)]
    assert skill_calls and all(marker not in system_text(c) for c in skill_calls)  # skills never do


def test_llm_router_filters_unknown_skills(fake_llm):
    fake_llm.responses.append(AIMessage("Bank Rate is 3.75% [Bank of England](https://www.bankofengland.co.uk/)."))
    state = ask("Where are interest rates?", thread_id="llm")
    assert state["selected_skills"] == ["macro-economy"]
    assert state["answer"].startswith("Bank Rate is 3.75%")
