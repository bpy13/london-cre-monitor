"""User-facing error handling: classification, incidents, and the end-to-end
behaviour when the Claude API refuses requests (the real-world 403 case)."""

from __future__ import annotations

import importlib
import logging
import re

import pytest

from cre_monitor.config import get_settings
from cre_monitor.errors import classify, incident_from_exception, make_incident, new_incident_id

#: The exact error seen when the API was blocked at the network edge.
REAL_403 = ("AnthropicPermissionDeniedError: Error code: 403 - "
            "{'error': {'type': 'forbidden', 'message': 'Request not allowed'}}")


@pytest.mark.parametrize("text, code", [
    (REAL_403, "access_denied"),
    ("AuthenticationError: Error code: 401 - invalid x-api-key", "auth"),
    ("BadRequestError: Error code: 400 - Your credit balance is too low to access the Anthropic API", "credit"),
    ("RateLimitError: Error code: 429 - rate_limit_error", "rate_limit"),
    ("InternalServerError: Error code: 529 - overloaded_error", "service"),
    ("APIConnectionError: Connection error. ConnectTimeout", "network"),
    ("RuntimeError: LLM requested while CRE_DEMO_MODE is on", "config"),
    ("ValueError: something odd", "unknown"),
])
def test_classify(text, code):
    assert classify(text).code == code


def test_incident_id_format():
    assert re.fullmatch(r"ERR-\d{8}-\d{4}-[0-9A-F]{4}", new_incident_id())


def test_make_incident_logs_traceable_record(caplog):
    assert make_incident([], total=True) is None
    with caplog.at_level(logging.ERROR, logger="cre_monitor.errors"):
        inc = make_incident(
            [("office-rents", "ValueError: odd"), ("macro-economy", REAL_403)],
            total=False, thread_id="t1", run_id="r1",
        )
    assert inc.category.code == "access_denied"          # most actionable known category wins
    assert inc.scope == "partial" and inc.affected == ["office-rents", "macro-economy"]
    record = caplog.text
    assert inc.id in record and "thread=t1" in record and "Request not allowed" in record


def test_incident_from_exception_is_total():
    inc = incident_from_exception(ConnectionError("Connection refused"), step="chat", thread_id="t9")
    assert inc.scope == "total" and inc.category.code == "network" and inc.thread_id == "t9"


# ---------------------------------------------------------------------------
# End to end: the API refuses every call (as from an unsupported region)
# ---------------------------------------------------------------------------

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


def test_brief_with_refused_api_reports_incident(api_refuses):
    from cre_monitor.graph.builder import run_brief

    state = run_brief(["macro-economy"])
    assert state["incident"].scope == "total"
    assert "synthesis" in state["incident"].affected
    # The report's watch list no longer carries the raw exception text.
    assert not any("Error code" in w for w in state["synthesis"].watch_list)
