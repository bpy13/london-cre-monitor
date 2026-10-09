"""Regression: period labels were compared as text in the brief's charts and KPI tiles.

As text, "2026-H1" sorts before "2026-Q1" although H1 ends three months later, and
"2026-Q1" beat "2026-H1" as the "latest" figure. The Dashboard and "what changed"
were fixed first (tests/regression/test_fixed_bugs.py); these tests cover the brief.
"""

from __future__ import annotations

import pandas as pd

from cre_monitor.reporting.charts import latest_by_submarket, pick_series, trend_chart
from cre_monitor.reporting.render import build_kpis
from cre_monitor.schemas import Metric, SkillFinding


def _metric(period: str, value: float, source: str = "JLL", submarket: str = "West End") -> Metric:
    return Metric(key="prime_rent", submarket=submarket, value=value, unit="GBP psf pa", period=period, source=source)


def test_kpi_tile_uses_the_latest_period_across_all_findings():
    older = SkillFinding(skill="office-rents", headline="h", summary="s", metrics=[_metric("2026-Q1", 180)])
    newer = SkillFinding(skill="submarket-dynamics", headline="h", summary="s", metrics=[_metric("2026-H1", 190)])
    odd = SkillFinding(skill="news-events", headline="h", summary="s", metrics=[_metric("recently", 999)])
    tile = next(t for t in build_kpis([older, newer, odd], []) if t["label"] == "Prime rent - West End")
    assert tile["period"] == "2026-H1" and tile["value"] == "£190.00 psf"


def test_report_charts_order_periods_in_time_and_never_mix_period_lengths():
    rows = pd.DataFrame([
        ("West End", "2026-Q2", 192.0, "GBP psf pa", "JLL"), ("West End", "2026-Q1", 185.0, "GBP psf pa", "JLL"),
        ("West End", "2025-Q4", 180.0, "GBP psf pa", "JLL"), ("West End", "2026-H1", 999.0, "GBP psf pa", "JLL"),
    ], columns=["submarket", "period", "value", "unit", "source"])
    line, mixed = pick_series(rows)
    assert list(line["period"]) == ["2025-Q4", "2026-Q1", "2026-Q2"] and not mixed   # H1 not joined in
    fig = trend_chart(rows, "Prime rent trend", "£", ["West End"])
    assert list(fig.layout.xaxis.categoryarray) == ["2025-Q4", "2026-Q1", "2026-Q2"]

    df = pd.DataFrame([dict(key="prime_rent", submarket="City", value=v, period=p, source="JLL")
                       for p, v in (("2026-Q1", 95.0), ("2026-H1", 97.0))])
    assert latest_by_submarket(df, "prime_rent")["period"].tolist() == ["2026-H1"]
