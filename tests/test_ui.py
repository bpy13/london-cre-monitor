"""Streamlit UI smoke tests using Streamlit's headless AppTest harness."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "src" / "cre_monitor" / "ui" / "app.py")


def test_app_renders_all_tabs_without_errors():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == ["💬 Chat", "📄 Briefs", "📈 Dashboard"]


def test_chat_turn_produces_answer_and_skill_caption():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.chat_input[0].set_value("What are prime rents in the West End?").run()
    assert not at.exception, at.exception
    assistant = [m for m in at.chat_message if m.name == "assistant"]
    assert assistant, "expected an assistant reply"
    text = " ".join(md.value for md in assistant[0].markdown)
    assert "190" in text  # West End prime rent from the fixture finding
    assert any("office-rents" in c.value for c in at.caption)
