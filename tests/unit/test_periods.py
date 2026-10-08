"""Period labels -> dates and frequency; true time ordering."""

from __future__ import annotations

from datetime import date

from cre_monitor.periods import parse_period, period_sort_key, same_frequency


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
