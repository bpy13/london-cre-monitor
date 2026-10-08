"""Reference reports tab: library, house style, performance check."""

from __future__ import annotations

from cre_monitor.benchmark import answer_key as ak
from cre_monitor.benchmark.store import list_runs
from cre_monitor.style import file_roles, save_example, set_roles
from tests.support.apptest import run_app
from tests.support.samples import REPORT, key_entry, script_benchmark_skill


def _benchmark_report(with_key: bool = True) -> ak.AnswerKey | None:
    save_example("ref.md", REPORT.encode())
    set_roles("ref.md", benchmark=True)
    if not with_key:
        return None
    key = ak.AnswerKey(report="ref.md", period="2026-Q2", publisher="Avison Young", themes=["Take-up steady"],
                       entries=[key_entry(), key_entry(key="vacancy_rate", value=9.9, unit="%")])  # 2nd: not in report
    ak.compute_signals(key, REPORT)
    ak.save_key(key)
    return key


def test_house_style_moved_to_the_tab_and_library_roles_are_saved():
    save_example("ref.md", REPORT.encode())
    at = run_app()
    labels = [t.label for t in at.tabs]                                   # includes nested sub-tabs
    assert {"📚 Reference reports", "🎨 House style", "🎯 Performance check"} <= set(labels)
    assert at.button(key="style-learn")                                   # house style lives in the tab now
    assert not [e for e in at.sidebar.expander if "House style" in e.label]
    at.checkbox(key="role-benchmark-ref.md").check().run()
    assert file_roles("ref.md") == {"style": True, "benchmark": True}
    assert at.selectbox(key="bench-report").value == "ref.md"


def test_answer_key_moderation_in_demo_mode():
    _benchmark_report()
    at = run_app()
    labels = {m.label: m.value for m in at.metric}
    assert labels["Figures"] == "2" and labels["In the document"] == "1/2" and labels["Safe"] == "1"
    at.button(key="bench-accept-safe").click().run()
    assert ak.load_key("ref.md").stats()["accepted"] == 1
    at.button(key="bench-build").click().run()                           # rebuild needs Claude
    assert any("needs Claude" in w.value for w in at.warning)
    at.button(key="bench-run").click().run()
    assert any("needs live mode" in w.value for w in at.warning)


def test_figure_run_and_scorecard(fake_llm, monkeypatch):
    key = _benchmark_report()
    key.accept_safe()
    ak.save_key(key)
    script_benchmark_skill(fake_llm, monkeypatch)
    at = run_app()
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
    at = run_app()
    at.button(key="bench-judge").click().run()
    assert not at.exception, at.exception
    assert list_runs("ref.md", "judge")[0].readability_brief["flesch"] is not None
    assert any("needs Claude" in w.value for w in at.warning)
