"""UI flows for contributors: the 🧩 Skills tab and Dashboard > Metrics > Add a metric.

Uses Streamlit's AppTest on per-test copies of skills/ and catalog/ (conftest), so
nothing in the repo changes. The plausible-ranges table (st.data_editor) can't be
edited through AppTest; range handling is covered in test_skill_editor.py.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from cre_monitor.authoring import MetricAssessment
from cre_monitor.catalog import get_catalog
from cre_monitor.skills import editor
from cre_monitor.skills.registry import get_registry
from tests.test_graph import fake_llm  # noqa: F401  (pytest fixture)

APP = str(Path(__file__).resolve().parents[1] / "src" / "cre_monitor" / "ui" / "app.py")


def _app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    return at


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


# --------------------------------------------------------------------------- Skills tab

def test_edit_and_save_a_skill():
    at = _app()
    assert at.selectbox(key="skill-select").value == "office-rents"     # first skill opened by default
    at.text_area(key="sk-office-rents-desc").input("Prime and Grade A rents - edited from the Skills tab.")
    _button(at, "💾 Save").click().run()
    assert not at.exception, at.exception
    assert get_registry().get("office-rents").meta.description.endswith("edited from the Skills tab.")
    assert any("Saved **office-rents**" in s.value for s in at.success)
    assert len(editor.versions("office-rents")) == 1


def test_validation_errors_are_shown_and_nothing_is_saved():
    at = _app()
    before = editor.skill_path("office-rents").read_text(encoding="utf-8")
    at.multiselect(key="sk-office-rents-tools").set_value([])
    at.text_area(key="sk-office-rents-instr").input("too short")
    _button(at, "💾 Save").click().run()
    errors = " ".join(e.value for e in at.error)
    assert "choose at least one tool" in errors and "too short" in errors
    assert editor.skill_path("office-rents").read_text(encoding="utf-8") == before


def test_create_skill_from_blank_template_then_delete_and_restore():
    at = _app()
    at.selectbox(key="skill-select").set_value("➕ New skill").run()
    at.text_input(key="new-name").input("lease-events")
    at.text_input(key="new-purpose").input("Lease expiries and break options in central London offices.")
    at.run()
    _button(at, "Start from a blank template").click().run()
    _button(at, "💾 Create skill").click().run()
    assert not at.exception, at.exception
    assert "lease-events" in get_registry()
    assert at.selectbox(key="skill-select").value == "lease-events"   # the new skill is opened

    at.button(key="sk-lease-events-delete").click().run()
    assert "lease-events" not in get_registry()
    (trash_id, _, _), = editor.list_trash()
    at.button(key=f"restore-{trash_id}").click().run()
    assert "lease-events" in get_registry()


def test_protected_skill_has_no_delete_button():
    at = _app()
    at.selectbox(key="skill-select").set_value("market-synthesis").run()
    assert not at.exception, at.exception
    assert not [b for b in at.button if b.key == "sk-market-synthesis-delete"]


# --------------------------------------------------------------------------- Add a metric

def test_add_metric_existing_name_works_in_demo_mode():
    at = _app()
    at.text_input(key="metric-request").input("Rent-free period")
    at.run()
    at.button(key="metric-assess").click().run()
    assert any("Already collected" in s.value for s in at.success)
    at.button(key="am-track").click().run()
    assert get_catalog().metric("rent_free_months").tracked

    at.text_input(key="metric-request").input("average lease length")
    at.run()
    at.button(key="metric-assess").click().run()
    assert any("needs Claude" in w.value for w in at.warning)             # demo mode: no assessment


def test_add_metric_with_skill_change_is_applied_after_approval(fake_llm):  # noqa: F811
    fake_llm.structured["MetricAssessment"] = MetricAssessment(
        verdict="needs_skill_change", reasoning="Published quarterly by brokers.", key="average_lease_length",
        label="Average lease length", unit="years", group="Leasing", definition="Mean term of new leases.",
        target_skill="leasing-take-up", sanity_min=1, sanity_max=25, guidance="Check Savills quarterly reports.")
    at = _app()
    at.text_input(key="metric-request").input("average lease length")
    at.run()
    at.button(key="metric-assess").click().run()
    assert not at.exception, at.exception
    assert any("Can be collected" in i.value for i in at.info)
    assert get_catalog().metric("average_lease_length") is None             # nothing saved before approval
    at.text_input(key="am-label").input("Average lease term")              # the proposal is editable
    at.button(key="am-apply").click().run()
    assert not at.exception, at.exception
    m = get_catalog().metric("average_lease_length")
    assert m.label == "Average lease term" and m.tracked
    assert "average_lease_length" in get_registry().get("leasing-take-up").meta.metrics
    assert any("Added 'Average lease term'" in s.value for s in at.success)
