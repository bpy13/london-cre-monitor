"""Performance check backend: number matching, scoring, readability, answer keys (signals,
moderation, AI extraction), run planning, a full figure run with the fake LLM (grounding,
citation check, cost), the optional cap, and brief judgement."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from cre_monitor.benchmark import answer_key as ak
from cre_monitor.benchmark import runner, scoring
from cre_monitor.benchmark.answer_key import AnswerKey, KeyEntry
from cre_monitor.benchmark.judge import BriefJudgement, Score, ThemeVerdict
from cre_monitor.benchmark.store import list_runs
from cre_monitor.catalog import get_catalog
from cre_monitor.config import get_settings
from cre_monitor.schemas import Metric
from cre_monitor.style import file_roles, save_example, set_roles
from tests.fake_llm import submit_call, tool_call
from tests.test_graph import fake_llm  # noqa: F401  (pytest fixture)

AY_URL = "https://www.avisonyoung.co.uk/central-london-office-analysis"   # an offline fixture document
REPORT = ("# Central London Office Market Update Q2 2026\n\nTake-up reached 2.6m sq ft in Q2 2026. "
          "Vacancy was unchanged at 6.3%. Prime rents in the West End rose to £190 psf. Source: " + AY_URL)


def _entry(**kw) -> KeyEntry:
    base = dict(key="take_up_sqft", submarket="Central London", period="2026-Q2", value=2_600_000, unit="sq ft",
                source="Avison Young", citation=AY_URL, confidence=0.9)
    return KeyEntry(**(base | kw))


def _metric(**kw) -> Metric:
    base = dict(key="take_up_sqft", submarket="Central London", period="2026-Q2", value=2_600_000, unit="sq ft",
                source="Avison Young", url=AY_URL)
    return Metric(**(base | kw))


# --------------------------------------------------------------------------- number matching

def test_numbers_are_found_whatever_the_format():
    assert scoring.numbers_in_text("2.6m sq ft, £1.2bn, 6.3%, 1,250,000 and 450k") == [2.6e6, 1.2e9, 6.3, 1.25e6, 4.5e5]
    assert scoring.value_in_text(2_600_000, "take-up of 2.6 million sq ft")
    assert scoring.value_in_text(6.3, "vacancy of 6.3%") and not scoring.value_in_text(6.4, "vacancy of 6.3%")
    assert not scoring.value_in_text(2, "Q2 2026")                      # period labels are not figures


# --------------------------------------------------------------------------- scoring

def test_figure_scoring_coverage_accuracy_sources_and_grounding():
    entries = [_entry(id="a"), _entry(id="b", key="vacancy_rate", value=6.3, unit="%"),
               _entry(id="c", key="prime_rent", submarket="West End", value=190, unit="GBP psf pa")]
    metrics = [
        _metric(),                                                                    # exact, same source
        _metric(key="vacancy_rate", value=6.5, unit="%", source="Savills", url=""),   # other source, off by 0.2pp
        _metric(key="prime_rent", submarket="City", value=95, unit="GBP psf pa"),     # different place: no match
    ]
    tool_texts = ["Central London take-up totalled 2.6m sq ft in Q2 2026. Vacancy 6.3%."]
    s = scoring.score_figures(entries, metrics, tool_texts, units=get_catalog().units())
    assert (s.n_entries, s.found, s.accurate) == (3, 2, 1)
    assert s.coverage == 66.7 and s.accuracy == 50.0
    assert s.accuracy_same_source == 100.0 and s.accuracy_other_source == 0.0
    by_id = {r.entry_id: r for r in s.results}
    assert by_id["a"].status == "accurate" and by_id["a"].grounded
    assert by_id["b"].status == "inaccurate" and not by_id["b"].same_source and not by_id["b"].grounded
    assert by_id["c"].status == "missing"
    assert s.grounding == pytest.approx(33.3)                             # 1 of 3 agent figures seen in tools
    # Tolerances: rates in percentage points, others relative.
    assert scoring.is_accurate(6.3, 6.39, "%", 0.1, 0.02) and not scoring.is_accurate(6.3, 6.45, "%", 0.1, 0.02)
    assert scoring.is_accurate(100, 101.9, "GBP psf pa", 0.1, 0.02)


def test_readability_statistics():
    plain = "Rents rose in Q2 2026. Vacancy fell to 6.3% in Q2 2026. Demand is strong."
    dense = ("Notwithstanding considerable macroeconomic uncertainty and persistently elevated financing costs, "
             "institutional occupational demand demonstrated remarkable resilience, characterised by "
             "unprecedented concentration within exceptionally high-specification accommodation offering "
             "comprehensive sustainability credentials and amenity provision across multiple submarkets.")
    p, d = scoring.readability(plain), scoring.readability(dense)
    assert p.flesch > d.flesch and p.avg_sentence_words < d.avg_sentence_words
    assert d.pct_long_sentences == 100.0 and p.pct_long_sentences == 0.0
    assert p.pct_figures_with_period == 100.0
    assert scoring.readability("").flesch is None


# --------------------------------------------------------------------------- answer keys

def test_signals_safe_entries_and_storage():
    key = AnswerKey(report="r.md", entries=[
        _entry(), _entry(key="vacancy_rate", value=9.9, unit="%"),                   # not in the document
        _entry(key="prime_rent", submarket="Mayfair", value=190, unit="GBP psf pa"),  # unknown place
        _entry(key="vacancy_rate", value=6.3, unit="%", period="last quarter"),       # unparseable period
        _entry(key="vacancy_rate", value=6.3, unit="%", source="JLL", confidence=0.5),  # low confidence
    ])
    ak.compute_signals(key, REPORT)
    safe = [e.safe for e in key.entries]
    assert safe == [True, False, False, False, False]
    assert key.entries[1].catalogue_match and not key.entries[1].in_document
    assert not key.entries[2].catalogue_match and not key.entries[3].period_ok
    assert len({e.id for e in key.entries}) == 5                          # stable ids
    assert key.accept_safe() == 1 and key.stats()["accepted"] == 1
    ak.save_key(key)
    assert ak.load_key("r.md") == key


def test_library_roles_default_and_update():
    save_example("ref.md", REPORT.encode())
    assert file_roles("ref.md") == {"style": True, "benchmark": False}
    set_roles("ref.md", benchmark=True, style=False)
    from cre_monitor.style import examples_with_role
    assert [p.name for p in examples_with_role("benchmark")] == ["ref.md"]
    assert examples_with_role("style") == []
    with pytest.raises(ValueError, match="No report"):
        set_roles("ghost.md", benchmark=True)


def test_build_key_with_ai_computes_signals_and_dedupes(fake_llm):  # noqa: F811
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


# --------------------------------------------------------------------------- planning

def test_plan_groups_by_skill_and_task_never_reveals_values():
    from cre_monitor.catalog import MetricDef, add_metric

    add_metric(MetricDef(key="average_lease_length", label="Average lease length", unit="years"))
    key = AnswerKey(report="r.md", period="2026-Q2", publisher="Avison Young", entries=[
        _entry(status="accepted"), _entry(key="vacancy_rate", value=6.3, unit="%", status="accepted"),
        _entry(key="average_lease_length", value=7.0, unit="years", status="accepted"),
        _entry(key="prime_yield", value=5.25, unit="%", status="rejected")])
    plan = runner.plan_run(key)
    assert list(plan.groups) == ["submarket-dynamics"]                     # one skill covers both
    assert [e.key for e in plan.not_collectable] == ["average_lease_length"]
    assert plan.estimate_usd > 0
    task = runner.benchmark_task(plan.groups["submarket-dynamics"], "2026-Q2", hints=True, publisher="Avison Young")
    assert "period 2026-Q2" in task and "Avison Young" in task and AY_URL in task
    assert "2600000" not in task and "6.3" not in task                     # never the answers
    assert AY_URL not in runner.benchmark_task(plan.groups["submarket-dynamics"], "2026-Q2", hints=False)


# --------------------------------------------------------------------------- full run (fake LLM)

def _key_for_run() -> AnswerKey:
    key = AnswerKey(report="ref.md", period="2026-Q2", publisher="Avison Young", themes=["Take-up steady"],
                    entries=[_entry(status="accepted"),
                             _entry(key="vacancy_rate", value=6.3, unit="%", status="accepted")])
    ak.compute_signals(key, REPORT)
    return key


def _script_skill(fake_llm, monkeypatch, tokens=(20_000, 2_000)):  # noqa: F811
    """One skill run: read the cited page, then submit 1 right and 1 invented figure."""
    monkeypatch.setenv("BENCHMARK_TARGET_USD", "0.01")
    get_settings.cache_clear()
    usage = {"input_tokens": tokens[0], "output_tokens": tokens[1], "total_tokens": sum(tokens)}
    finding = fake_llm.macro.model_copy(update={"metrics": [
        _metric(), _metric(key="vacancy_rate", value=9.9, unit="%")]})
    submit = submit_call(finding)
    submit.usage_metadata = usage
    fake_llm.responses[:] = [
        AIMessage("", tool_calls=[tool_call("fetch_document", {"url": AY_URL}, "c1")], usage_metadata=usage),
        submit]


def test_figure_run_scores_grounds_checks_citations_and_costs(fake_llm, monkeypatch):  # noqa: F811
    save_example("ref.md", REPORT.encode())
    _script_skill(fake_llm, monkeypatch)
    rec = runner.run_figures(_key_for_run())
    assert rec.skills == ["submarket-dynamics"] and rec.hints
    assert rec.figure["coverage"] == 100.0 and rec.figure["accuracy"] == 50.0
    assert rec.figure["grounding"] == 50.0                    # 9.9% never appeared in a tool result
    assert rec.citation["pct_opened"] == 100.0 and rec.citation["pct_contains"] == 50.0
    assert rec.tokens_in == 40_000 and rec.tokens_out == 4_000
    assert rec.cost_usd == pytest.approx(runner.usd(40_000, 4_000, get_settings().model_skill))
    assert any("above the $0.01 target" in w for w in rec.warnings)
    assert "Performance check task" in str(fake_llm.calls[0][1].content)
    assert list_runs("ref.md")[0].run_id == rec.run_id


def test_optional_cap_skips_further_skills_only_when_set(fake_llm, monkeypatch):  # noqa: F811
    key = _key_for_run()
    key.entries.append(_entry(key="bank_rate", submarket="UK", value=3.75, unit="%", source="Bank of England",
                              status="accepted"))
    _script_skill(fake_llm, monkeypatch)
    rec = runner.run_figures(key, max_usd=0.0001)               # first skill always starts
    assert len(rec.skills) == 1 and len(rec.skipped_skills) == 1
    assert any("Cap of $0.00 reached" in w for w in rec.warnings)
    assert get_settings().benchmark_max_usd is None             # off by default


def test_figure_run_needs_live_mode_and_accepted_entries(fake_llm):  # noqa: F811
    with pytest.raises(ValueError, match="Accept at least one"):
        runner.run_figures(AnswerKey(report="r.md", entries=[_entry()]))


# --------------------------------------------------------------------------- CLI

def test_cli_bench_commands_in_demo_mode():
    from typer.testing import CliRunner

    from cre_monitor import cli
    from cre_monitor.graph.builder import run_brief

    runner_ = CliRunner()
    save_example("ref.md", REPORT.encode())
    assert "No performance-check runs yet" in runner_.invoke(cli.app, ["bench", "history"]).output
    res = runner_.invoke(cli.app, ["bench", "key", "ref.md"])
    assert res.exit_code == 1 and "needs Claude" in res.output
    assert "No answer key" in runner_.invoke(cli.app, ["bench", "run", "ref.md"]).output
    ak.save_key(_key_for_run())
    run_brief(["office-rents"])
    res = runner_.invoke(cli.app, ["bench", "judge", "ref.md"])
    assert res.exit_code == 0 and "Flesch" in res.output and "needs Claude" in res.output
    assert "judge" in runner_.invoke(cli.app, ["bench", "history", "ref.md"]).output


# --------------------------------------------------------------------------- judge

def test_judge_demo_mode_still_gives_free_statistics():
    from cre_monitor.graph.builder import run_brief

    save_example("ref.md", REPORT.encode())
    run_brief(["office-rents"])
    rec = runner.run_judge(_key_for_run())
    assert rec.judgement is None and any("needs Claude" in w for w in rec.warnings)
    assert rec.readability_brief["flesch"] is not None and rec.readability_reference["words"] > 0
    assert rec.citation["checked"] > 0                        # the brief's figures were checked


def test_judge_with_ai(fake_llm):  # noqa: F811
    from cre_monitor.graph.builder import run_brief

    run_brief(["macro-economy"])
    fake_llm.structured["BriefJudgement"] = BriefJudgement(
        themes=[ThemeVerdict(theme="Take-up steady", coverage="partly")],
        consistency=Score(score=4, reason="ok"), so_what=Score(score=3, reason="generic"),
        structure=Score(score=4, reason="clear"), readability=Score(score=4, reason="plain"), summary="s")
    rec = runner.run_judge(_key_for_run())
    assert rec.judgement["theme_coverage"] == 50.0 and rec.judgement["so_what"]["score"] == 3
    assert rec.cost_usd > 0
    assert "THEMES:" in fake_llm.calls[-1][1].content and "ACCEPTED FIGURES" in fake_llm.calls[-1][1].content
