"""Chart data selection rules (like-for-like sources) and chart assembly."""

from __future__ import annotations

import pandas as pd

from cre_monitor.graph.nodes.skill_runner import demo_finding
from cre_monitor.reporting.charts import build_charts, latest_by_submarket, metrics_frame, pick_series, trend_chart
from cre_monitor.store import get_store


def rows(*items):
    return pd.DataFrame([dict(submarket=s, period=p, value=v, source=src, key="vacancy_rate") for s, p, v, src in items])


def test_pick_series_prefers_single_source_with_history():
    d = rows(("Central London", "2025-Q3", 8.6, "AY"), ("Central London", "2026-Q1", 8.4, "BNP"),
             ("Central London", "2026-Q2", 6.3, "AY"), ("Central London", "2026-Q2", 8.6, "JLL"))
    picked, mixed = pick_series(d)
    assert not mixed
    assert picked["source"].unique().tolist() == ["AY"]
    assert picked["value"].tolist() == [8.6, 6.3]


def test_pick_series_falls_back_to_mixed_and_flags_it():
    d = rows(("West End", "2026-Q1", 175.0, "BNP"), ("West End", "2026-Q2", 190.0, "JLL"))
    picked, mixed = pick_series(d)
    assert mixed and len(picked) == 2


def test_latest_by_submarket_uses_consistent_source():
    df = metrics_frame([demo_finding("vacancy-availability")])
    latest = latest_by_submarket(df, "vacancy_rate")
    # Avison Young covers both Central London and Midtown -> use it for both bars, not JLL.
    assert set(latest["source"]) == {"Avison Young"}
    assert latest.set_index("submarket").loc["Central London", "value"] == 6.3


def test_mixed_trend_is_labelled():
    fig = trend_chart(rows(("West End", "2026-Q1", 175.0, "BNP"), ("West End", "2026-Q2", 190.0, "JLL")), "Prime rent trend", "£")
    assert "mixed sources" in fig.layout.title.text
    assert fig.data[0].line.dash == "dash"


def test_build_charts_with_history():
    store = get_store()
    store.seed_from_fixture()
    findings = [demo_finding(n) for n in ("office-rents", "vacancy-availability", "leasing-take-up", "supply-pipeline")]
    store.record("run", findings)
    charts = build_charts(findings, store)
    assert {"prime_rent_by_submarket", "vacancy_by_submarket", "vacancy_trend", "take_up", "rates", "pipeline"} <= set(charts)
