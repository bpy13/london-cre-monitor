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
    # The real 400 seen in the first live run (thinking-block signature / tool list mismatch).
    ("AnthropicInvalidRequestError: Error code: 400 - {'type': 'error', 'error': {'type': "
     "'invalid_request_error', 'message': 'messages.1.content.4: Invalid `signature` in `thinking` block.'}}",
     "app_error"),
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


REAL_400 = ("AnthropicInvalidRequestError: Error code: 400 - {'type': 'error', 'error': {'type': "
            "'invalid_request_error', 'message': 'messages.1.content.4: Invalid `signature` in `thinking` block.'}}")


def _report_texts(state):
    from pathlib import Path

    html = Path(state["report_paths"]["html"]).read_text(encoding="utf-8")
    md = Path(state["report_paths"]["markdown"]).read_text(encoding="utf-8")
    raw_json = Path(state["report_paths"]["json"]).read_text(encoding="utf-8")
    return html, md, raw_json


def test_report_shows_friendly_panel_for_partial_failure(monkeypatch):
    """One skill fails (the real live 400), the other succeeds -> amber panel, no raw text for readers."""
    from cre_monitor.graph.builder import run_brief

    # importlib: graph/nodes/__init__ re-exports a *function* named skill_runner, shadowing the module.
    sr = importlib.import_module("cre_monitor.graph.nodes.skill_runner")
    real_demo = sr.demo_finding

    def flaky_demo(name):
        if name == "office-rents":
            raise RuntimeError(REAL_400)
        return real_demo(name)

    monkeypatch.setattr(sr, "demo_finding", flaky_demo)
    state = run_brief(["office-rents", "macro-economy"])
    incident = state["incident"]
    assert incident.scope == "partial" and incident.category.code == "app_error"

    html, md, raw_json = _report_texts(state)
    readable_html = html.split('<details class="tech">')[0]
    readable_md = md.split("## Technical details for engineers")[0]
    for readable in (readable_html, readable_md):
        assert "The app sent a request the AI service rejected" in readable   # plain-English title
        assert incident.id in readable                                       # same reference as CLI/UI
        assert "Not available this time" in readable                         # per-skill line
        assert "Error code" not in readable and "Skill failed:" not in readable   # no raw text for readers
    assert 'class="incident partial"' in html
    assert "the London engineering team" in readable_html                    # support contact
    assert "Error code: 400" in html.split('<details class="tech">')[1]      # raw kept for engineers ...
    assert "Error code: 400" in md.split("## Technical details for engineers")[1]
    assert "Skill failed:" in raw_json and incident.id in raw_json           # ... and in the audit JSON


def test_report_shows_red_panel_when_nothing_usable(api_refuses):
    from cre_monitor.graph.builder import run_brief

    state = run_brief(["macro-economy"])
    html, md, _ = _report_texts(state)
    assert 'class="incident total"' in html
    assert "This brief could not be produced from fresh research." in html
    assert "🚫" in md.split("## Executive summary")[0]


def test_brief_with_refused_api_reports_incident(api_refuses):
    from cre_monitor.graph.builder import run_brief

    state = run_brief(["macro-economy"])
    assert state["incident"].scope == "total"
    assert "synthesis" in state["incident"].affected
    # The report's watch list no longer carries the raw exception text.
    assert not any("Error code" in w for w in state["synthesis"].watch_list)
