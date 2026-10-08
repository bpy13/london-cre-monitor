"""Full chat turns: multi-turn memory, saved conversations, references, API failure."""

from __future__ import annotations

from cre_monitor.graph.builder import ask, delete_conversation, get_chat_graph, new_thread_id
from cre_monitor.store import get_conversation_store


def test_ask_records_turns_and_resume_keeps_context():
    tid = new_thread_id()
    ask("What is happening with interest rates?", thread_id=tid)
    second = ask("And Canary Wharf vacancy?", thread_id=tid)

    assert len(second["messages"]) == 4            # agent memory resumed (2 human + 2 AI)
    conv = get_conversation_store().get(tid)
    assert conv.turn_count == 2
    assert conv.title == "What is happening with interest rates?"
    assert [t.question for t in get_conversation_store().turns(tid)][1] == "And Canary Wharf vacancy?"


def test_ask_with_refs_uses_and_records_them_but_does_not_carry_over():
    earlier = new_thread_id()
    ask("What are prime rents in the West End?", thread_id=earlier)

    tid = new_thread_id()
    state = ask("How has the West End changed since then?", thread_id=tid, refs=[earlier])
    assert state["context_refs"] == [earlier]
    assert 'EARLIER CONVERSATION "What are prime rents in the West End?"' in state["reference_context"]
    assert "Referenced earlier conversations" in state["answer"]        # demo answer lists them
    assert get_conversation_store().turns(tid)[0].refs == [earlier]

    follow_up = ask("And the City?", thread_id=tid)                       # no refs this turn
    assert follow_up["context_refs"] == [] and follow_up["reference_context"] == ""


def test_delete_conversation_removes_index_and_agent_memory():
    tid = new_thread_id()
    ask("Bank Rate?", thread_id=tid)
    config = {"configurable": {"thread_id": tid}}
    assert get_chat_graph().get_state(config).values.get("messages")

    delete_conversation(tid)
    assert get_conversation_store().get(tid) is None
    assert not get_chat_graph().get_state(config).values.get("messages")


def test_chat_with_refused_api_gives_clean_answer_and_incident(api_refuses):
    from cre_monitor.graph.builder import ask
    from cre_monitor.store import get_conversation_store

    state = ask("What are prime rents in the West End?", thread_id="blocked")
    incident = state["incident"]
    assert incident.scope == "total" and incident.category.code == "access_denied"
    assert "Error code" not in state["answer"] and "403" not in state["answer"]   # no raw errors for users
    assert state["answer"] == "I couldn't complete the research for this question."
    assert "answer" in incident.affected and "office-rents" in incident.affected
    # Saved with the turn, so a reopened conversation shows the same reference.
    assert get_conversation_store().turns("blocked")[0].incident.id == incident.id


def test_chat_demo_multi_turn_resets_findings():
    first = ask("What is happening with interest rates?", thread_id="t1")
    assert "macro-economy" in first["selected_skills"]
    assert first["answer"]
    second = ask("And Canary Wharf vacancy?", thread_id="t1")
    # Findings are per turn (not accumulated), messages are per thread (accumulated).
    assert {f.skill for f in second["findings"]} == set(second["selected_skills"])
    assert len(second["messages"]) == 4
