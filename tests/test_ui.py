"""Streamlit UI smoke tests using Streamlit's headless AppTest harness."""

from __future__ import annotations

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "src" / "cre_monitor" / "ui" / "app.py")


def _assistant_text(at: AppTest) -> str:
    return " ".join(md.value for m in at.chat_message if m.name == "assistant" for md in m.markdown)


def test_app_renders_all_tabs_without_errors():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == ["💬 Chat", "📄 Briefs", "📈 Dashboard"]


def test_chat_turn_produces_answer_and_skill_caption():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.chat_input[0].set_value("What are prime rents in the West End?").run()
    assert not at.exception, at.exception
    assert "190" in _assistant_text(at)  # West End prime rent from the fixture finding
    assert any("office-rents" in c.value for c in at.caption)


def test_conversation_is_listed_and_can_be_reopened():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.chat_input[0].set_value("What are prime rents in the West End?").run()
    tid = at.session_state["thread_id"]

    # Listed in the sidebar, titled by the first question, and kept in the URL.
    open_btn = at.button(key=f"open-{tid}")
    assert open_btn.label == "What are prime rents in the West End?"
    assert at.query_params["thread"] == [tid] or at.query_params["thread"] == tid

    # New chat clears the view; clicking the conversation brings it back.
    at.button(key="new-chat").click().run()
    assert at.session_state["thread_id"] != tid and not at.chat_message
    at.button(key=f"open-{tid}").click().run()
    assert not at.exception, at.exception
    assert at.session_state["thread_id"] == tid
    assert "190" in _assistant_text(at)


def test_reference_picker_adds_earlier_conversation_as_context():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.chat_input[0].set_value("What are prime rents in the West End?").run()
    earlier = at.session_state["thread_id"]

    at.button(key="new-chat").click().run()
    picker = at.multiselect(key=f"refs-{at.session_state['thread_id']}")
    # Options are shown via format_func as "<title>  ·  <date>"; the current chat is excluded.
    assert len(picker.options) == 1 and picker.options[0].startswith("What are prime rents in the West End?")
    picker.set_value([earlier]).run()
    at.chat_input[0].set_value("How has that changed?").run()
    assert not at.exception, at.exception
    assert any(c.value.startswith("📎 Referenced: What are prime rents in the West End?") for c in at.caption)
    assert "Referenced earlier conversations" in _assistant_text(at)


def test_api_failure_shows_decorated_panel_with_reference(monkeypatch):
    """When Claude refuses requests, users get a friendly panel + reference ID, not raw errors."""
    import importlib

    from cre_monitor.config import get_settings

    monkeypatch.setenv("CRE_DEMO_MODE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("SUPPORT_CONTACT", "the London FDE team")
    get_settings.cache_clear()

    def refuse(tier="skill"):
        raise RuntimeError("Error code: 403 - {'error': {'type': 'forbidden', 'message': 'Request not allowed'}}")

    for module in ("planner", "skill_runner", "synthesis", "chat_answer"):
        monkeypatch.setattr(importlib.import_module(f"cre_monitor.graph.nodes.{module}"), "get_llm", refuse)

    at = AppTest.from_file(APP, default_timeout=60).run()
    at.chat_input[0].set_value("What are prime rents in the West End?").run()
    assert not at.exception, at.exception

    assert any("The AI service refused the request" in e.value for e in at.error)
    reference = next(c.value for c in at.code if c.value.startswith("ERR-"))
    assert re.fullmatch(r"ERR-\d{8}-\d{4}-[0-9A-F]{4}", reference)
    assert any("the London FDE team" in m.value for m in at.markdown)
    assert "Error code" not in _assistant_text(at)          # raw text only inside "for engineers"


def test_conversation_opens_from_url():
    first = AppTest.from_file(APP, default_timeout=60).run()
    first.chat_input[0].set_value("Bank Rate?").run()
    tid = first.session_state["thread_id"]

    fresh = AppTest.from_file(APP, default_timeout=60)   # a new browser session
    fresh.query_params["thread"] = tid
    fresh.run()
    assert not fresh.exception, fresh.exception
    assert fresh.session_state["thread_id"] == tid
    assert [m.name for m in fresh.chat_message] == ["user", "assistant"]
