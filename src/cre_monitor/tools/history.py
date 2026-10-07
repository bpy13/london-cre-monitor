"""``metrics_history`` tool: let a skill see what the agent reported before.

Giving skills access to their own history lets them describe *trends*
("third consecutive quarter of rental growth") instead of single snapshots,
and sanity-check new numbers against previous ones.
"""

from __future__ import annotations

from langchain_core.tools import tool

from cre_monitor.store import get_store


@tool
def metrics_history(key: str, submarket: str | None = None) -> str:
    """Look up previously recorded values of a market metric (our own database).

    Args:
        key: Metric key, e.g. "prime_rent", "vacancy_rate", "take_up_sqft".
        submarket: Optional submarket, e.g. "City", "West End", "Central London".
    """
    df = get_store().series(key, submarket)
    if df.empty:
        return f"No history recorded for {key}" + (f" in {submarket}" if submarket else "") + "."
    lines = [
        f"{r.submarket} {r.period}: {r.value:g} {r.unit} ({r.source})"
        for r in df.tail(24).itertuples()
    ]
    return f"History of {key}:\n" + "\n".join(lines)
