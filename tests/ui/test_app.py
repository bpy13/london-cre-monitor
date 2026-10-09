"""Chat, briefs, sidebar (settings, partial brief, export, house-style toggle)."""

from __future__ import annotations

import re

from streamlit.testing.v1 import AppTest

from tests.support.apptest import APP, assistant_text


def test_app_renders_all_tabs_without_errors():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    labels = [t.label for t in at.tabs]
    assert labels[:3] == ["💬 Chat", "📄 Briefs", "📈 Dashboard"]
    assert {"📊 Overview", "⚙️ Metrics", "📍 Submarkets"} <= set(labels)     # Dashboard sub-tabs


def test_chat_turn_produces_answer_and_skill_caption():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.chat_input[0].set_value("What are prime rents in the West End?").run()
    assert not at.exception, at.exception
    assert "190" in assistant_text(at)  # West End prime rent from the fixture finding
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
    assert "190" in assistant_text(at)


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
    assert "Referenced earlier conversations" in assistant_text(at)


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
    assert "Error code" not in assistant_text(at)          # raw text only inside "for engineers"


def test_sample_brief_shown_only_while_there_are_no_briefs(monkeypatch, tmp_path):
    from cre_monitor.config import get_settings
    from cre_monitor.graph.builder import run_brief
    from cre_monitor.reporting.briefs import list_briefs, sample_brief

    assert sample_brief() is not None and list_briefs() == []      # the repo's examples/sample-brief
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert any("Sample brief" in m.value for m in at.markdown)
    assert not [b for b in at.button if (b.key or "").startswith("del-brief-")]   # read-only

    run_brief(["office-rents"])                                      # a brief of our own...
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not any("Sample brief" in m.value for m in at.markdown)    # ... replaces the sample

    monkeypatch.setenv("SAMPLE_BRIEF_DIR", str(tmp_path / "none"))   # no sample folder: nothing breaks
    get_settings.cache_clear()
    assert sample_brief() is None


def test_delete_brief_from_briefs_tab():
    from cre_monitor.graph.builder import run_brief
    from cre_monitor.reporting.briefs import get_brief

    run_id = run_brief(["office-rents"])["run_id"]
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.button(key=f"del-brief-{run_id}").click().run()
    assert not at.exception, at.exception
    assert get_brief(run_id) is None
    assert any(f"Deleted brief {run_id}" in s.value for s in at.success)
    assert any("No briefs yet" in i.value for i in at.info)


def test_export_from_sidebar():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.chat_input[0].set_value("Bank Rate?").run()
    at.button(key="export-run").click().run()
    assert not at.exception, at.exception
    result = at.session_state["export_result"]
    assert result.path.exists() and result.counts["conversations"] == 1
    assert at.get("download_button")                        # zip offered for download


def test_house_style_panel_learn_show_clear_and_delete_example():
    """🎨 House style (Reference reports tab) and the sidebar's Use-house-style toggle. AppTest can't
    drive st.file_uploader, so files are saved via save_example - the function the upload button
    calls - which is unit-tested in tests/unit/test_style_profile.py."""
    from cre_monitor.style import list_examples, load_profile, save_example
    from tests.support.samples import EXAMPLE_A, EXAMPLE_B

    save_example("a.md", EXAMPLE_A.encode())
    save_example("b.md", EXAMPLE_B.encode())
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert any("No house style yet" in i.value for i in at.info)
    assert at.toggle(key="brief-style-none").disabled                  # nothing to apply yet

    at.button(key="style-learn").click().run()                        # demo mode -> rule-based
    assert not at.exception, at.exception
    assert load_profile() is not None
    assert any(s.value.startswith("Learned:") for s in at.success)
    assert not at.toggle(key="brief-style").disabled and at.toggle(key="brief-style").value

    at.toggle(key="style-show").set_value(True).run()
    assert any("Key themes" in m.value for m in at.markdown)          # learned heading shown

    at.button(key="style-del-b.md").click().run()
    assert [p.name for p in list_examples()] == ["a.md"]

    at.button(key="style-clear").click().run()
    assert not at.exception, at.exception
    assert load_profile() is None and any("House style removed" in s.value for s in at.success)


def test_brief_from_ui_honours_house_style_toggle():
    from cre_monitor.config import get_settings
    from cre_monitor.style import learn_profile, save_example
    from tests.support.samples import EXAMPLE_A

    save_example("a.md", EXAMPLE_A.encode())
    learn_profile()
    at = AppTest.from_file(APP, default_timeout=60).run()

    def latest_html() -> str:
        return max(get_settings().reports_dir.rglob("brief_*.html"), key=lambda p: p.stat().st_mtime_ns).read_text(encoding="utf-8")

    at.button(key="run-brief").click().run()
    assert not at.exception, at.exception
    assert "<h2>Key themes</h2>" in latest_html()                    # styled by default

    at.toggle(key="brief-style").set_value(False).run()
    at.button(key="run-brief").click().run()
    assert "<h2>Executive summary</h2>" in latest_html() and "Key themes" not in latest_html()


def test_partial_brief_runs_only_ticked_skills():
    import json

    from cre_monitor.config import get_settings
    from cre_monitor.skills.registry import get_registry

    total = len(get_registry().brief_skills())
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert at.button(key="run-brief").label == "Run full brief now"     # all ticked by default

    at.button(key="brief-skills-none").click().run()
    assert at.button(key="run-brief").disabled                          # nothing to run
    at.checkbox(key="brief-skill-office-rents").check().run()
    at.checkbox(key="brief-skill-macro-economy").check().run()
    assert at.button(key="run-brief").label == f"Run partial brief (2 of {total} skills)"

    at.button(key="run-brief").click().run()
    assert not at.exception, at.exception
    findings = sorted(get_settings().reports_dir.rglob("findings_*.json"))[-1]
    ran = {f["skill"] for f in json.loads(findings.read_text(encoding="utf-8"))["findings"]}
    assert ran == {"office-rents", "macro-economy"}

    at.button(key="brief-skills-all").click().run()
    assert at.button(key="run-brief").label == "Run full brief now"


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
