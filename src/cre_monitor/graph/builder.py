"""Wire the nodes into the top-level LangGraph.

::

    START -> planner --Send x N--> skill_runner (parallel) -> validator -> persist
                 \\                                                       |
                  \\--(no skills needed)--> chat_answer <--(chat)----------+
                                                                          |
                                     report_writer <- synthesis <--(brief)-+

Public helpers:

* :func:`build_graph` - compile the graph (optionally with a checkpointer).
* :func:`run_brief`   - run the full market brief once (CLI / scheduler).
* :func:`ask`         - one chat turn on a persistent thread (CLI / UI);
  reusing a ``thread_id`` resumes that conversation.
* :func:`new_thread_id` / :func:`delete_conversation` - conversation lifecycle.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from functools import lru_cache

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from cre_monitor.config import get_settings
from cre_monitor.graph.nodes import (
    chat_answer, fan_out, persist, planner, report_writer, route_after_persist,
    skill_runner, synthesis, validator,
)
from cre_monitor.graph.state import AgentState
from cre_monitor.store import get_conversation_store

logger = logging.getLogger(__name__)


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Build and compile the monitor graph.

    Args:
        checkpointer: Persists state per ``thread_id`` (needed for multi-turn
            chat). ``None`` is fine for one-shot briefs and for LangGraph
            Studio, which injects its own.
    """
    g = StateGraph(AgentState)
    g.add_node("planner", planner)
    g.add_node("skill_runner", skill_runner)
    g.add_node("validator", validator)
    g.add_node("persist", persist)
    g.add_node("synthesis", synthesis)
    g.add_node("report_writer", report_writer)
    g.add_node("chat_answer", chat_answer)

    g.add_edge(START, "planner")
    # fan_out returns Send objects (parallel skills) or "chat_answer".
    g.add_conditional_edges("planner", fan_out, ["skill_runner", "chat_answer"])
    # LangGraph waits for ALL parallel skill_runner branches before validator.
    g.add_edge("skill_runner", "validator")
    g.add_edge("validator", "persist")
    g.add_conditional_edges("persist", route_after_persist, ["synthesis", "chat_answer"])
    g.add_edge("synthesis", "report_writer")
    g.add_edge("report_writer", END)
    g.add_edge("chat_answer", END)
    return g.compile(checkpointer=checkpointer, name="london-cre-monitor")


@lru_cache(maxsize=1)
def get_chat_graph() -> CompiledStateGraph:
    """Graph with a SQLite checkpointer so chat threads survive restarts."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    s = get_settings()
    s.ensure_dirs()
    # check_same_thread=False: Streamlit and LangGraph may call from worker threads.
    conn = sqlite3.connect(s.checkpoint_db_path, check_same_thread=False)
    return build_graph(SqliteSaver(conn))


def run_brief(skills: list[str] | None = None) -> AgentState:
    """Run the full scheduled market brief once.

    Args:
        skills: Optional subset of skills (defaults to all brief skills).

    Returns:
        Final state; ``state["report_paths"]`` holds the written files.
    """
    get_settings().ensure_dirs()
    return build_graph().invoke({"mode": "brief", "messages": [], "skills_override": skills})


def new_thread_id() -> str:
    """A fresh, unique conversation id."""
    return uuid.uuid4().hex[:12]


def ask(question: str, thread_id: str = "default", stream_handler=None) -> AgentState:
    """Ask one chat question on a persistent conversation thread.

    Reusing a ``thread_id`` resumes that conversation: the checkpointer gives the
    agent the earlier messages. Every turn is also recorded in the conversation
    index (:mod:`cre_monitor.store.conversations`) so it can be listed and redrawn.

    Args:
        question: The user's question.
        thread_id: Conversation id; reuse it for follow-up questions.
        stream_handler: Optional callable ``(node_name, update_dict)`` invoked
            as each node finishes - used by the UI to show progress.

    Returns:
        Final state; ``state["answer"]`` is the reply.
    """
    graph = get_chat_graph()
    config = {"configurable": {"thread_id": thread_id}}
    inputs = {"mode": "chat", "messages": [HumanMessage(question)], "skills_override": None}
    if stream_handler is None:
        state = graph.invoke(inputs, config)
    else:
        for chunk in graph.stream(inputs, config, stream_mode="updates"):
            for node, update in chunk.items():
                stream_handler(node, update)
        state = graph.get_state(config).values
    _record_turn(thread_id, question, state)
    return state


def _record_turn(thread_id: str, question: str, state: AgentState) -> None:
    """Save the turn to the conversation index. Never fails the chat turn itself."""
    try:
        get_conversation_store().record_turn(
            thread_id, question, state.get("answer", ""),
            skills=state.get("selected_skills"), reasoning=state.get("planner_reasoning"),
            issues=state.get("validation_issues"), findings=state.get("findings"),
        )
    except Exception:  # noqa: BLE001 - history is a convenience; the answer matters more
        logger.exception("Could not record conversation turn for thread %s", thread_id)


def delete_conversation(thread_id: str) -> None:
    """Delete a conversation everywhere: the sidebar index and the agent's memory."""
    get_conversation_store().delete(thread_id)
    get_chat_graph().checkpointer.delete_thread(thread_id)


#: Module-level graph for LangGraph Studio / ``langgraph dev`` (see langgraph.json).
#: Compiling is cheap and side-effect free, so doing it at import is fine.
graph = build_graph()

__all__ = ["build_graph", "get_chat_graph", "run_brief", "ask", "new_thread_id", "delete_conversation", "graph"]
