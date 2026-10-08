"""Dashboard selection, formatting and chart functions (reporting/dashboard.py)."""

from __future__ import annotations

import pandas as pd

from cre_monitor.catalog import get_catalog
from cre_monitor.reporting import dashboard as dash


def _series(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["submarket", "period", "value", "unit", "source"])


VACANCY = _series([
    ("Central London", "2025-Q3", 9.0, "%", "Avison Young"),
    ("Central London", "2026-Q1", 8.4, "%", "BNP"),
    ("Central London", "2026-Q2", 7.9, "%", "Avison Young"),
    ("Central London", "2026-Q2", 6.3, "%", "Savills"),
    ("City", "2026-Q2", 8.8, "%", "Savills"),
    ("West End", "2025-Q3", 5.0, "%", "Avison Young"),
    ("West End", "2026-Q2", 4.6, "%", "Savills"),
    ("Central London", "2026-H1", 8.0, "%", "Avison Young"),
])


def test_values_are_formatted_by_unit():
    assert dash.format_value(190, "GBP psf pa") == "£190.00 psf"
    assert dash.format_value(6.3, "%") == "6.3%" and dash.format_value(3.75, "%") == "3.75%"
    assert dash.format_value(2_600_000, "sq ft") == "2.60m sq ft"
    assert dash.format_value(450_000, "sq ft") == "450k sq ft"
    assert dash.format_value(1.2e9, "GBP") == "£1.20bn" and dash.format_value(350e6, "GBP") == "£350m"
    assert dash.format_value(9, "months") == "9 months" and dash.format_value(None, "%") == "–"
    assert dash.format_change(6.3, 6.0, "%") == "+0.30pp" and dash.format_change(110, 100, "sq ft") == "+10.0%"


def test_line_follows_one_source_and_one_period_length():
    df = dash.prepare(VACANCY)
    ln = dash.line_for(df, "Central London")
    assert ln.source == "Avison Young" and not ln.mixed and ln.freq == "Q"
    assert list(ln.rows["period"]) == ["2025-Q3", "2026-Q2"]          # the H1 figure is not joined in
    assert ln.left_out == 3
    # West End has no source with 2 points -> stitched, flagged as mixed.
    we = dash.line_for(df, "West End")
    assert we.mixed and list(we.rows["source"]) == ["Avison Young", "Savills"]
    # A chosen source is respected.
    assert dash.line_for(df, "Central London", "Savills").rows["value"].tolist() == [6.3]


def test_latest_by_place_and_headline():
    df = dash.prepare(VACANCY)
    latest = dash.latest_by_place(df).set_index("submarket")
    assert latest.loc["Central London", "period"] == "2026-Q2"
    assert latest.loc["Central London", "source"] in {"Avison Young", "Savills"}   # best-covered first
    h = dash.headline(df)
    assert h.place == "Central London" and h.period == "2026-Q2"
    assert h.previous_period in {"2025-Q3", None}                    # same source + same length only
    h_av = dash.headline(df, source="Avison Young")
    assert (h_av.value, h_av.previous, h_av.previous_period) == (7.9, 9.0, "2025-Q3")


def test_trend_figure_overlays_up_to_four_then_small_multiples():
    rows = []
    for place in ["Central London", "City", "West End", "Canary Wharf", "Midtown", "Paddington"]:
        rows += [(place, "2026-Q1", 100.0, "GBP psf pa", "JLL"), (place, "2026-Q2", 110.0, "GBP psf pa", "JLL")]
    df = dash.prepare(_series(rows))
    metric = get_catalog().metric("prime_rent")
    fig4, lines4 = dash.trend_figure(df, ["Central London", "City", "West End", "Canary Wharf"], metric)
    assert len(lines4) == 4 and fig4.layout.xaxis.type != "category"   # real date axis
    fig6, lines6 = dash.trend_figure(df, sorted(df["submarket"].unique()), metric)
    assert len(lines6) == 6 and "one panel per submarket" in fig6.layout.title.text
    colors = dash.place_colors(["City", "Paddington", "Victoria"])
    assert colors["City"] == "#eb6834" and len(set(colors.values())) == 3   # new places get unused colours
    assert dash.snapshot_chart(dash.latest_by_place(df), metric) is not None
