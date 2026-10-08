"""LLM router and answer step with the fake LLM (incl. referenced conversations)."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from cre_monitor.graph.builder import ask


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
