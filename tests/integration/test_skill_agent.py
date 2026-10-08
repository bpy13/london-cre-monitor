"""The ReAct skill sub-agent driven by the scripted fake LLM against offline tools."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from cre_monitor.config import get_settings
from cre_monitor.graph.builder import run_brief
from tests.support.fake_llm import submit_call, tool_call


def _skill_run(fake_llm, responses):
    from cre_monitor.graph.nodes.skill_runner import run_skill

    fake_llm.responses[:] = responses
    return run_skill("macro-economy", "Where is Bank Rate?")


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
