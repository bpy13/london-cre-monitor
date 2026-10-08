"""Dashboard: period parsing, data selection, formatting, charts, and the UI sub-tabs."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from cre_monitor.catalog import get_catalog
from cre_monitor.periods import parse_period, period_sort_key, same_frequency
from cre_monitor.reporting import dashboard as dash

APP = str(Path(__file__).resolve().parents[1] / "src" / "cre_monitor" / "ui" / "app.py")


def _series(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["submarket", "period", "value", "unit", "source"])


# --------------------------------------------------------------------------- periods

def test_period_parsing_and_true_time_order():
    q = parse_period("2026-Q2")
    assert (q.start, q.end, q.freq) == (date(2026, 4, 1), date(2026, 6, 30), "Q")
    assert parse_period("Q2 2026").end == q.end and parse_period("2026-H1").freq == "H"
    assert parse_period("2026-08").end == date(2026, 8, 31) and parse_period("2027").freq == "Y"
    assert parse_period("week ending 2026-09-25").start == date(2026, 9, 19)
    assert parse_period("sometime soon") is None
    # As text "2026-H1" < "2026-Q1"; in time Q1 (ends March) comes before H1 (ends June).
    labels = ["2026-H1", "2026-Q2", "2025-Q3", "2026-Q1", "odd"]
    assert sorted(labels, key=period_sort_key) == ["2025-Q3", "2026-Q1", "2026-H1", "2026-Q2", "odd"]
    assert same_frequency("2026-Q1", "2025-Q4") and not same_frequency("2026-H1", "2026-Q2")


def test_deltas_never_compare_different_period_lengths(tmp_path):
    from cre_monitor.schemas import Metric, SkillFinding
    from cre_monitor.store.metrics import MetricsStore

    store = MetricsStore(tmp_path / "m.sqlite")

    def finding(period, value):
        return SkillFinding(skill="s", headline="h", summary="s", metrics=[Metric(
            key="investment_volume_gbp", submarket="Central London", value=value, unit="GBP", period=period,
            source="JLL")])

    store.record("r1", [finding("2026-H1", 6e9)])
    assert store.deltas([finding("2026-Q3", 2e9)], exclude_run_id="r2") == []        # H vs Q: no "fall"
    store.record("r2", [finding("2026-Q2", 3e9)])
    (delta,) = store.deltas([finding("2026-Q3", 2e9)], exclude_run_id="r3")
    assert delta.previous_period == "2026-Q2"


# --------------------------------------------------------------------------- formatting

def test_values_are_formatted_by_unit():
    assert dash.format_value(190, "GBP psf pa") == "£190.00 psf"
    assert dash.format_value(6.3, "%") == "6.3%" and dash.format_value(3.75, "%") == "3.75%"
    assert dash.format_value(2_600_000, "sq ft") == "2.60m sq ft"
    assert dash.format_value(450_000, "sq ft") == "450k sq ft"
    assert dash.format_value(1.2e9, "GBP") == "£1.20bn" and dash.format_value(350e6, "GBP") == "£350m"
    assert dash.format_value(9, "months") == "9 months" and dash.format_value(None, "%") == "–"
    assert dash.format_change(6.3, 6.0, "%") == "+0.30pp" and dash.format_change(110, 100, "sq ft") == "+10.0%"


# --------------------------------------------------------------------------- selection

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


# --------------------------------------------------------------------------- UI

def test_dashboard_overview_shows_tracked_cards_and_detail():
    from cre_monitor.schemas import Metric, SkillFinding
    from cre_monitor.store import get_store

    places = ["Central London", "City", "West End", "Canary Wharf", "Midtown", "Paddington"]
    get_store().seed_from_fixture()
    get_store().record("t1", [SkillFinding(skill="office-rents", headline="h", summary="s", metrics=[
        Metric(key="prime_rent", submarket=p, value=100.0 + i, unit="GBP psf pa", period="2026-Q2", source="JLL")
        for i, p in enumerate(places)])])
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    labels = [m.label for m in at.metric]
    assert {"Prime rent", "Vacancy rate", "Bank Rate", "10-year gilt yield"} <= set(labels)
    assert at.selectbox(key="dash-metric").value == "prime_rent"
    places = at.multiselect(key="dash-places-prime_rent")
    assert len(places.value) > 4                                       # no 4-submarket cap any more
    at.selectbox(key="dash-metric").set_value("bank_rate").run()
    assert not at.exception, at.exception


def test_untracking_a_metric_hides_its_card_and_saves_the_catalogue():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.checkbox(key="track-prime_yield").uncheck().run()
    assert not at.exception, at.exception
    assert not get_catalog().metric("prime_yield").tracked
    assert "Prime yield" not in [m.label for m in at.metric]
    assert any("no longer tracked" in s.value for s in at.success)
    at.checkbox(key="track-rent_free_months").check().run()
    assert "Rent-free period" in [m.label for m in at.metric]


def test_add_and_remove_submarket_from_ui():
    at = AppTest.from_file(APP, default_timeout=60).run()
    next(t for t in at.text_input if t.label == "Name").input("Victoria")
    next(t for t in at.text_input if t.label.startswith("Aliases (optional")).input("SW1")
    next(b for b in at.button if b.label == "Add submarket").click().run()
    assert not at.exception, at.exception
    assert get_catalog().canonical_place("sw1") == "Victoria"
    at.button(key="rm-sm-Victoria").click().run()
    assert "Victoria" not in get_catalog().all_places()
    assert at.button(key="rm-sm-Paddington") and not [b for b in at.button if b.key == "rm-sm-Central London"]
