"""Validator rules (deterministic data-quality checks), one metric/finding at a time."""

from __future__ import annotations

from datetime import date

from cre_monitor.graph.nodes.validator import validate
from cre_monitor.schemas import Citation, Metric, SkillFinding


TODAY = date(2026, 10, 7)


def metric(**overrides) -> Metric:
    base = dict(key="vacancy_rate", submarket="City", value=9.0, unit="%", period="2026-Q2",
                source="Knight Frank", url="https://example.com/kf.pdf", as_of=date(2026, 7, 15))
    return Metric(**(base | overrides))


def finding(*metrics: Metric, skill: str = "vacancy-availability") -> SkillFinding:
    return SkillFinding(skill=skill, headline="h", summary="s", metrics=list(metrics),
                        citations=[Citation(title="KF", url="https://example.com/kf.pdf")])


def messages(issues) -> str:
    return " | ".join(i.message for i in issues)


def test_clean_metric_passes():
    cleaned, issues = validate([finding(metric())], today=TODAY)
    assert issues == []
    assert len(cleaned[0].metrics) == 1


def test_out_of_range_metric_is_dropped_with_error():
    cleaned, issues = validate([finding(metric(value=85.0))], today=TODAY)  # 85% vacancy is a misread
    assert cleaned[0].metrics == []
    assert any(i.level == "error" and "outside plausible range" in i.message for i in issues)


def test_unit_mismatch_unknown_key_and_submarket_warn():
    _, issues = validate(
        [finding(metric(unit="percent"), metric(key="mystery_metric", unit="x"), metric(submarket="Atlantis"))],
        today=TODAY,
    )
    text = messages(issues)
    assert "expected '%'" in text
    assert "Unknown metric key" in text
    assert "Non-canonical submarket 'Atlantis'" in text


def test_submarket_aliases_are_mapped_to_catalogue_names():
    cleaned, issues = validate([finding(metric(submarket="Docklands"), metric(submarket="city of london",
                                                                              source="JLL"))], today=TODAY)
    assert [m.submarket for m in cleaned[0].metrics] == ["Canary Wharf", "City"]
    assert not any("Non-canonical" in i.message for i in issues)


def test_missing_url_and_stale_data_warn():
    _, issues = validate([finding(metric(url="", as_of=date(2025, 1, 10)))], today=TODAY)
    text = messages(issues)
    assert "no source URL" in text
    assert "stale" in text


def test_conflicting_sources_are_flagged_but_both_kept():
    a = metric(value=8.4, source="Knight Frank")
    b = metric(value=10.9, source="CBRE")  # 2.5pp apart > 1.5pp tolerance
    cleaned, issues = validate([finding(a, b)], today=TODAY)
    assert len(cleaned[0].metrics) == 2
    assert any("Sources disagree" in i.message for i in issues)


def test_small_differences_are_not_conflicts():
    _, issues = validate([finding(metric(value=8.4), metric(value=8.9, source="CBRE"))], today=TODAY)
    assert not any("Sources disagree" in i.message for i in issues)


def test_failed_skill_is_reported():
    failed = SkillFinding(skill="news-events", headline="x", summary="x", error="Timeout")
    _, issues = validate([failed], today=TODAY)
    assert issues[0].message == "Skill failed: Timeout"
