"""Conversation history: index store, resume via ask(), deletion, recency grouping,
and cross-conversation references (context packs)."""

from __future__ import annotations

from datetime import datetime

import sqlite3

from cre_monitor.graph.builder import ask, delete_conversation, get_chat_graph, new_thread_id, resolve_refs
from cre_monitor.schemas import Metric, SkillFinding, ValidationIssue
from cre_monitor.store import get_conversation_store
from cre_monitor.store.conversations import (
    MAX_REFS, PACK_MAX_CHARS, Conversation, ConversationStore, group_by_recency, make_title,
)


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


def _rent_finding() -> SkillFinding:
    metric = Metric(key="prime_rent", submarket="West End", value=190.0, unit="GBP psf pa",
                    period="2026-Q2", source="JLL")
    return SkillFinding(skill="office-rents", headline="h", summary="s", metrics=[metric])


def test_context_pack_is_dated_excerpted_and_lists_figures(tmp_path):
    store = ConversationStore(tmp_path / "c.sqlite")
    store.record_turn("t1", "Prime rents in the West End?", "Long answer " * 100, ["office-rents"],
                      findings=[_rent_finding()])
    pack = store.context_pack("t1")

    assert pack.startswith('=== EARLIER CONVERSATION "Prime rents in the West End?" (id t1, last active ')
    assert "Q: Prime rents in the West End?" in pack
    assert "A (excerpt): Long answer" in pack and "…" in pack           # answer truncated
    assert "West End prime rent: 190 GBP psf pa (2026-Q2, JLL; recorded " in pack
    assert "may be superseded" in pack                                  # staleness warning
    assert store.context_pack("unknown") == ""


def test_context_pack_is_capped(tmp_path):
    store = ConversationStore(tmp_path / "c.sqlite")
    for i in range(10):
        store.record_turn("t1", f"Question {i} " + "x" * 300, "y" * 1000)
    assert len(store.context_pack("t1")) <= PACK_MAX_CHARS
    pack = store.context_pack("t1")
    assert "Q: Question 9" in pack                                       # most recent turns kept
    assert "Q: Question 0" not in pack                                   # oldest turns dropped (title still names it)


def test_old_database_is_upgraded_with_refs_column(tmp_path):
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE conversations (thread_id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
        "CREATE TABLE turns (thread_id TEXT NOT NULL, idx INTEGER NOT NULL, created_at TEXT NOT NULL, question TEXT NOT NULL,"
        " answer TEXT NOT NULL, skills_json TEXT NOT NULL, reasoning TEXT, issues_json TEXT NOT NULL, findings_json TEXT NOT NULL,"
        " PRIMARY KEY (thread_id, idx));"
        "INSERT INTO conversations VALUES ('old', 'Old chat', '2026-10-01T09:00:00', '2026-10-01T09:00:00');"
        "INSERT INTO turns VALUES ('old', 0, '2026-10-01T09:00:00', 'q', 'a', '[]', NULL, '[]', '[]');"
    )
    conn.commit()
    conn.close()

    store = ConversationStore(path)
    assert store.turns("old")[0].refs == []                              # existing rows readable
    store.record_turn("new", "q2", "a2", refs=["old"])
    assert store.turns("new")[0].refs == ["old"]


def test_resolve_refs_drops_invalid_and_caps():
    store = get_conversation_store()
    ids = [new_thread_id() for _ in range(MAX_REFS + 1)]
    for tid in ids:
        store.record_turn(tid, f"q {tid}", "a")
    current = ids[0]
    refs = [current, "nope", ids[1], ids[1], *ids[2:]]
    assert resolve_refs(current, refs) == ids[1:MAX_REFS + 1]           # self, unknown, dup dropped; capped


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
