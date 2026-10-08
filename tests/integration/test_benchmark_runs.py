"""Performance-check answer-key extraction, figure runs and brief judgement."""

from __future__ import annotations

import pytest

from cre_monitor.benchmark import answer_key as ak, runner
from cre_monitor.benchmark.answer_key import AnswerKey
from cre_monitor.benchmark.judge import BriefJudgement, Score, ThemeVerdict
from cre_monitor.benchmark.store import list_runs
from cre_monitor.config import get_settings
from cre_monitor.style import save_example
from tests.support.samples import AY_URL, REPORT, key_entry, run_key, script_benchmark_skill


def test_build_key_with_ai_computes_signals_and_dedupes(fake_llm):
    save_example("ref.md", REPORT.encode())
    e = dict(key="take_up_sqft", submarket="Central London", period="2026-Q2", value=2_600_000, unit="sq ft",
             source="Avison Young", citation=AY_URL, confidence=0.95)
    fake_llm.structured["_KeyOut"] = ak._KeyOut(
        title="Central London Office Market Update", publisher="Avison Young", period="2026-Q2",
        themes=["Take-up steady", "Vacancy flat"],
        entries=[ak._EntryOut(**e), ak._EntryOut(**e),                             # duplicate
                 ak._EntryOut(**(e | {"key": "vacancy_rate", "value": 7.7, "unit": "%"}))])   # invented
    key = ak.build_key("ref.md")
    assert key.publisher == "Avison Young" and len(key.entries) == 2
    assert [x.in_document for x in key.entries] == [True, False]
    assert "METRIC CATALOGUE" in fake_llm.calls[-1][0].content and "2.6m sq ft" in fake_llm.calls[-1][1].content


def test_build_key_needs_live_mode():
    from cre_monitor.authoring import NeedsLiveMode

    save_example("ref.md", REPORT.encode())
    with pytest.raises(NeedsLiveMode):
        ak.build_key("ref.md")


def test_figure_run_scores_grounds_checks_citations_and_costs(fake_llm, monkeypatch):
    save_example("ref.md", REPORT.encode())
    script_benchmark_skill(fake_llm, monkeypatch)
    rec = runner.run_figures(run_key())
    assert rec.skills == ["submarket-dynamics"] and rec.hints
    assert rec.figure["coverage"] == 100.0 and rec.figure["accuracy"] == 50.0
    assert rec.figure["grounding"] == 50.0                    # 9.9% never appeared in a tool result
    assert rec.citation["pct_opened"] == 100.0 and rec.citation["pct_contains"] == 50.0
    assert rec.tokens_in == 40_000 and rec.tokens_out == 4_000
    assert rec.cost_usd == pytest.approx(runner.usd(40_000, 4_000, get_settings().model_skill))
    assert any("above the $0.01 target" in w for w in rec.warnings)
    assert "Performance check task" in str(fake_llm.calls[0][1].content)
    assert list_runs("ref.md")[0].run_id == rec.run_id


def test_optional_cap_skips_further_skills_only_when_set(fake_llm, monkeypatch):
    key = run_key()
    key.entries.append(key_entry(key="bank_rate", submarket="UK", value=3.75, unit="%", source="Bank of England",
                              status="accepted"))
    script_benchmark_skill(fake_llm, monkeypatch)
    rec = runner.run_figures(key, max_usd=0.0001)               # first skill always starts
    assert len(rec.skills) == 1 and len(rec.skipped_skills) == 1
    assert any("Cap of $0.00 reached" in w for w in rec.warnings)
    assert get_settings().benchmark_max_usd is None             # off by default


def test_figure_run_needs_live_mode_and_accepted_entries(fake_llm):
    with pytest.raises(ValueError, match="Accept at least one"):
        runner.run_figures(AnswerKey(report="r.md", entries=[key_entry()]))


def test_judge_demo_mode_still_gives_free_statistics():
    from cre_monitor.graph.builder import run_brief

    save_example("ref.md", REPORT.encode())
    run_brief(["office-rents"])
    rec = runner.run_judge(run_key())
    assert rec.judgement is None and any("needs Claude" in w for w in rec.warnings)
    assert rec.readability_brief["flesch"] is not None and rec.readability_reference["words"] > 0
    assert rec.citation["checked"] > 0                        # the brief's figures were checked


def test_judge_with_ai(fake_llm):
    from cre_monitor.graph.builder import run_brief

    run_brief(["macro-economy"])
    fake_llm.structured["BriefJudgement"] = BriefJudgement(
        themes=[ThemeVerdict(theme="Take-up steady", coverage="partly")],
        consistency=Score(score=4, reason="ok"), so_what=Score(score=3, reason="generic"),
        structure=Score(score=4, reason="clear"), readability=Score(score=4, reason="plain"), summary="s")
    rec = runner.run_judge(run_key())
    assert rec.judgement["theme_coverage"] == 50.0 and rec.judgement["so_what"]["score"] == 3
    assert rec.cost_usd > 0
    assert "THEMES:" in fake_llm.calls[-1][1].content and "ACCEPTED FIGURES" in fake_llm.calls[-1][1].content
