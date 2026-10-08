"""Conversation history: index store, resume via ask(), deletion, recency grouping."""

from __future__ import annotations

from datetime import datetime

from cre_monitor.graph.builder import ask, delete_conversation, get_chat_graph, new_thread_id
from cre_monitor.schemas import SkillFinding, ValidationIssue
from cre_monitor.store import get_conversation_store
from cre_monitor.store.conversations import Conversation, ConversationStore, group_by_recency, make_title


def test_store_records_lists_and_redraws_turns(tmp_path):
    store = ConversationStore(tmp_path / "c.sqlite")
    finding = SkillFinding(skill="office-rents", headline="h", summary="s")
    issue = ValidationIssue(level="warning", skill="office-rents", message="m")
    store.record_turn("t1", "What are prime rents in the West End?", "GBP 190 psf", ["office-rents"], "rents q", [issue], [finding])
    store.record_turn("t1", "And the City?", "GBP 95 psf", ["office-rents"])
    store.record_turn("t2", "Bank Rate?", "3.75%", ["macro-economy"])

    convs = store.list()
    assert [c.thread_id for c in convs][0] == "t2"            # most recent first
    t1 = store.get("t1")
    assert t1.title == "What are prime rents in the West End?"  # title = first question
    assert t1.turn_count == 2

    turns = store.turns("t1")
    assert [t.idx for t in turns] == [0, 1]
    assert turns[0].findings[0].skill == "office-rents" and turns[0].issues[0].message == "m"

    store.rename("t1", "West End rents")
    assert store.get("t1").title == "West End rents"
    store.delete("t1")
    assert store.get("t1") is None and store.turns("t1") == []


def test_make_title_is_single_line_and_truncated():
    assert make_title("  a\n b  ") == "a b"
    long = make_title("x" * 200)
    assert len(long) <= 60 and long.endswith("…")


def test_group_by_recency():
    now = datetime(2026, 10, 8, 12, 0)
    mk = lambda tid, ts: Conversation(thread_id=tid, title=tid, created_at=ts, updated_at=ts)  # noqa: E731
    groups = group_by_recency(
        [mk("a", datetime(2026, 10, 8, 9)), mk("b", datetime(2026, 10, 7, 9)),
         mk("c", datetime(2026, 10, 3, 9)), mk("d", datetime(2026, 9, 1, 9))],
        now=now,
    )
    assert [(label, [c.thread_id for c in items]) for label, items in groups] == [
        ("Today", ["a"]), ("Yesterday", ["b"]), ("Previous 7 days", ["c"]), ("Older", ["d"]),
    ]


def test_ask_records_turns_and_resume_keeps_context():
    tid = new_thread_id()
    ask("What is happening with interest rates?", thread_id=tid)
    second = ask("And Canary Wharf vacancy?", thread_id=tid)

    assert len(second["messages"]) == 4            # agent memory resumed (2 human + 2 AI)
    conv = get_conversation_store().get(tid)
    assert conv.turn_count == 2
    assert conv.title == "What is happening with interest rates?"
    assert [t.question for t in get_conversation_store().turns(tid)][1] == "And Canary Wharf vacancy?"


def test_delete_conversation_removes_index_and_agent_memory():
    tid = new_thread_id()
    ask("Bank Rate?", thread_id=tid)
    config = {"configurable": {"thread_id": tid}}
    assert get_chat_graph().get_state(config).values.get("messages")

    delete_conversation(tid)
    assert get_conversation_store().get(tid) is None
    assert not get_chat_graph().get_state(config).values.get("messages")
