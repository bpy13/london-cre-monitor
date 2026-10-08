"""Helpers for UI tests with Streamlit's headless ``AppTest`` harness."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

#: The Streamlit app under test (tests/support/apptest.py -> repo root -> src/...).
APP = str(Path(__file__).resolve().parents[2] / "src" / "cre_monitor" / "ui" / "app.py")


def run_app() -> AppTest:
    """Load and run the app once; fail the test if the script raised."""
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    return at


def button_labelled(at: AppTest, label: str):
    """The first button with this exact label (for buttons without a key, e.g. form submits)."""
    return next(b for b in at.button if b.label == label)


def assistant_text(at: AppTest) -> str:
    """All Markdown shown in assistant chat messages, joined."""
    return " ".join(md.value for m in at.chat_message if m.name == "assistant" for md in m.markdown)
