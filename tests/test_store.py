"""Metrics store: history, de-duplication and period-on-period deltas."""

from __future__ import annotations

from cre_monitor.schemas import Metric, SkillFinding
from cre_monitor.store.metrics import MetricsStore


def f(*metrics: Metric) -> SkillFinding:
    return SkillFinding(skill="office-rents", headline="h", summary="s", metrics=list(metrics))


def m(value: float, period: str, submarket: str = "City", key: str = "prime_rent") -> Metric:
    return Metric(key=key, submarket=submarket, value=value, unit="GBP psf pa", period=period, source="KF")


def test_series_latest_run_wins_for_same_period(tmp_path):
    store = MetricsStore(tmp_path / "m.sqlite")
    store.record("run1", [f(m(90.0, "2026-Q1"))])
    store.record("run2", [f(m(92.5, "2026-Q1"), m(95.0, "2026-Q2"))])  # Q1 revised
    s = store.series("prime_rent", "City")
    assert s["period"].tolist() == ["2026-Q1", "2026-Q2"]
    assert s["value"].tolist() == [92.5, 95.0]


def test_deltas_compare_with_previous_period_only(tmp_path):
    store = MetricsStore(tmp_path / "m.sqlite")
    store.record("old", [f(m(90.0, "2026-Q1"), m(170.0, "2026-Q1", "West End"))])
    current = [f(m(95.0, "2026-Q2"), m(170.0, "2026-Q1", "West End"))]  # West End: same period -> no delta
    deltas = store.deltas(current, exclude_run_id="new")
    assert len(deltas) == 1
    d = deltas[0]
    assert (d.submarket, d.previous, d.current, d.previous_period) == ("City", 90.0, 95.0, "2026-Q1")
    assert round(d.pct_change, 2) == 5.56
    assert "City prime rent: 90 -> 95" in d.describe()


def test_deltas_prefer_same_source_and_label_cross_source(tmp_path):
    store = MetricsStore(tmp_path / "m.sqlite")
    vac = lambda v, p, src: Metric(key="vacancy_rate", submarket="Central London", value=v, unit="%", period=p, source=src)  # noqa: E731
    store.record("old", [f(vac(8.4, "2026-Q1", "BNP"), vac(6.3, "2025-Q4", "Avison Young"))])

    # Avison Young has its own (older) history -> compare like with like, not with BNP's later Q1.
    (d,) = store.deltas([f(vac(6.3, "2026-Q2", "Avison Young"))], exclude_run_id="new")
    assert d.same_source and d.previous_source == "Avison Young" and d.previous_period == "2025-Q4"
    assert not d.is_material  # 6.3 -> 6.3

    # JLL has no history -> falls back to another source, clearly labelled.
    (d,) = store.deltas([f(vac(8.6, "2026-Q2", "JLL"))], exclude_run_id="new")
    assert not d.same_source
    assert "different sources: BNP -> JLL" in d.describe()


def test_large_values_are_formatted_readably(tmp_path):
    store = MetricsStore(tmp_path / "m.sqlite")
    t = lambda v, p: Metric(key="take_up_sqft", submarket="Central London", value=v, unit="sq ft", period=p, source="AY")  # noqa: E731
    store.record("old", [f(t(2_500_000, "2026-Q1"))])
    (d,) = store.deltas([f(t(2_600_000, "2026-Q2"))], exclude_run_id="new")
    assert "2,500,000 -> 2,600,000 sq ft" in d.describe()


def test_seed_fixture_loads(tmp_path):
    store = MetricsStore(tmp_path / "m.sqlite")
    assert store.is_empty()
    assert store.seed_from_fixture() > 20
    assert not store.series("prime_rent", "West End").empty
