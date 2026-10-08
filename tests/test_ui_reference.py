"""📚 Reference reports tab: library roles, house style (moved from the sidebar) and the
performance check (answer key moderation, figure run scorecard, brief judgement).

AppTest cannot edit st.data_editor cells, so table moderation is covered through
``answer_key.apply_edits`` (tested here directly) and the "Accept all safe" button.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from cre_monitor.benchmark import answer_key as ak
from cre_monitor.benchmark.store import list_runs
from cre_monitor.style import file_roles, save_example, set_roles
from tests.test_benchmark import REPORT, _entry, _script_skill
from tests.test_graph import fake_llm  # noqa: F401  (pytest fixture)

APP = str(Path(__file__).resolve().parents[1] / "src" / "cre_monitor" / "ui" / "app.py")


def _app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    return at


def _benchmark_report(with_key: bool = True) -> ak.AnswerKey | None:
    save_example("ref.md", REPORT.encode())
    set_roles("ref.md", benchmark=True)
    if not with_key:
        return None
    key = ak.AnswerKey(report="ref.md", period="2026-Q2", publisher="Avison Young", themes=["Take-up steady"],
                       entries=[_entry(), _entry(key="vacancy_rate", value=9.9, unit="%")])  # 2nd: not in report
    ak.compute_signals(key, REPORT)
    ak.save_key(key)
    return key


def test_house_style_moved_to_the_tab_and_library_roles_are_saved():
    save_example("ref.md", REPORT.encode())
    at = _app()
    labels = [t.label for t in at.tabs]                                   # includes nested sub-tabs
    assert {"📚 Reference reports", "🎨 House style", "🎯 Performance check"} <= set(labels)
    assert at.button(key="style-learn")                                   # house style lives in the tab now
    assert not [e for e in at.sidebar.expander if "House style" in e.label]
    at.checkbox(key="role-benchmark-ref.md").check().run()
    assert file_roles("ref.md") == {"style": True, "benchmark": True}
    assert at.selectbox(key="bench-report").value == "ref.md"


def test_answer_key_moderation_in_demo_mode():
    _benchmark_report()
    at = _app()
    labels = {m.label: m.value for m in at.metric}
    assert labels["Figures"] == "2" and labels["In the document"] == "1/2" and labels["Safe"] == "1"
    at.button(key="bench-accept-safe").click().run()
    assert ak.load_key("ref.md").stats()["accepted"] == 1
    at.button(key="bench-build").click().run()                           # rebuild needs Claude
    assert any("needs Claude" in w.value for w in at.warning)
    at.button(key="bench-run").click().run()
    assert any("needs live mode" in w.value for w in at.warning)


def test_apply_edits_changes_status_value_and_rechecks_signals():
    import pytest

    key = _benchmark_report()
    bad = next(e for e in key.entries if not e.in_document)
    n = ak.apply_edits(key, [{"id": bad.id, "value": 6.3, "status": "accepted"}], REPORT)
    assert n == 1 and bad.in_document and bad.status == "accepted"            # corrected value is in the report
    with pytest.raises(ValueError, match="Unknown status"):
        ak.apply_edits(key, [{"id": bad.id, "status": "maybe"}], REPORT)


def test_figure_run_and_scorecard(fake_llm, monkeypatch):  # noqa: F811
    key = _benchmark_report()
    key.accept_safe()
    ak.save_key(key)
    _script_skill(fake_llm, monkeypatch)
    at = _app()
    at.button(key="bench-run").click().run()
    assert not at.exception, at.exception
    tiles = {m.label: m.value for m in at.metric}
    assert tiles["Coverage"] == "100%" and tiles["Accuracy"] == "100%" and tiles["Grounding"] == "50%"
    assert list_runs("ref.md", "figures")
    assert any("above the" in w.value for w in at.warning)                  # cost over the (test) target


def test_brief_judgement_in_demo_mode_shows_free_statistics():
    from cre_monitor.graph.builder import run_brief

    _benchmark_report()
    run_brief(["office-rents"])
    at = _app()
    at.button(key="bench-judge").click().run()
    assert not at.exception, at.exception
    assert list_runs("ref.md", "judge")[0].readability_brief["flesch"] is not None
    assert any("needs Claude" in w.value for w in at.warning)
