"""SQLite store of every metric the agent has ever reported.

Why this exists: a single agent run only sees the *latest* broker reports.
To spot **market shifts** we need memory across runs - "City vacancy was
10.1% last quarter and is 9.4% now". Every run appends its metrics here; the
``persist`` graph node then computes :class:`~cre_monitor.schemas.MetricDelta`
objects and the report charts read time series back out.

Schema (one table, append-only - never update rows, so history is auditable)::

    metrics(run_id, run_at, skill, key, submarket, value, unit,
            period, source, url, as_of, note)

``run_id = 'seed'`` marks historical rows loaded from
``fixtures/history.json`` so charts have a trend line from day one.

SQLite was chosen because it is zero-ops and good enough for a PoC; the
class interface is small so it can be swapped for Postgres later.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pandas as pd

from cre_monitor.config import get_settings
from cre_monitor.schemas import Metric, MetricDelta, SkillFinding

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    run_id    TEXT NOT NULL,
    run_at    TEXT NOT NULL,
    skill     TEXT NOT NULL,
    key       TEXT NOT NULL,
    submarket TEXT NOT NULL,
    value     REAL NOT NULL,
    unit      TEXT,
    period    TEXT NOT NULL,
    source    TEXT,
    url       TEXT,
    as_of     TEXT,
    note      TEXT
);
CREATE INDEX IF NOT EXISTS ix_metrics_key ON metrics(key, submarket, period);
"""


class MetricsStore:
    """Thin wrapper around a SQLite file holding metric history."""

    def __init__(self, path: Path) -> None:
        """Open (and create if needed) the database at ``path``."""
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # A short-lived connection per operation keeps us safe across the
        # threads LangGraph / Streamlit may use (sqlite3 objects are not
        # shareable between threads by default).
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- writes -------------------------------------------------------------
    def record(self, run_id: str, findings: list[SkillFinding], run_at: datetime | None = None) -> int:
        """Append all metrics from ``findings`` under ``run_id``.

        Returns:
            Number of rows inserted.
        """
        run_at_s = (run_at or datetime.now()).isoformat(timespec="seconds")
        rows = [
            (run_id, run_at_s, f.skill, m.key, m.submarket, m.value, m.unit, m.period,
             m.source, m.url, m.as_of.isoformat() if m.as_of else None, m.note)
            for f in findings
            for m in f.metrics
        ]
        with self._conn() as conn:
            conn.executemany("INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def is_empty(self) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 0

    def seed_from_fixture(self, path: Path | None = None) -> int:
        """Load historical quarterly figures (``fixtures/history.json``).

        Each entry is a :class:`Metric`-shaped dict. Rows are stored under
        ``run_id='seed'`` and a fixed timestamp so they always sort first.
        """
        path = path or get_settings().fixtures_dir / "history.json"
        metrics = [Metric(**m) for m in json.loads(path.read_text(encoding="utf-8"))]
        finding = SkillFinding(skill="seed", headline="seed", summary="seed", metrics=metrics)
        n = self.record("seed", [finding], run_at=datetime(2000, 1, 1))
        logger.info("Seeded metrics store with %d historical rows", n)
        return n

    # -- reads --------------------------------------------------------------
    def frame(self) -> pd.DataFrame:
        """Entire table as a DataFrame (fine at PoC scale)."""
        with self._conn() as conn:
            return pd.read_sql_query("SELECT * FROM metrics", conn)

    def series(self, key: str, submarket: str | None = None) -> pd.DataFrame:
        """Time series for ``key`` (optionally one submarket).

        One row per (submarket, period, **source**): different brokers are kept
        apart because their definitions differ - callers such as
        :func:`cre_monitor.reporting.charts.trend_chart` decide how to combine
        them. When the same source was recorded by several runs, the most
        recent run wins (later runs see revised data).

        Returns:
            DataFrame with columns ``submarket, period, value, unit, source``
            sorted by period.
        """
        q = "SELECT * FROM metrics WHERE key = ?"
        params: list = [key]
        if submarket:
            q += " AND submarket = ?"
            params.append(submarket)
        with self._conn() as conn:
            df = pd.read_sql_query(q, conn, params=params)
        if df.empty:
            return df
        df = df.sort_values("run_at").drop_duplicates(["submarket", "period", "source"], keep="last")
        return df.sort_values("period")[["submarket", "period", "value", "unit", "source"]].reset_index(drop=True)

    def deltas(self, current: list[SkillFinding], exclude_run_id: str) -> list[MetricDelta]:
        """Compare this run's metrics against the latest *earlier period* on record.

        Rules:

        * Only genuine period-on-period changes count (e.g. 2026-Q1 -> 2026-Q2).
          Same-period differences are source disagreements or revisions; those
          are the validator's job, not a "market shift".
        * **Same-source comparisons are preferred.** Brokers define vacancy,
          take-up etc. differently, so "BNP 8.4% -> Avison Young 6.3%" is not
          a 2.1pp fall. A cross-source delta is only used when no same-source
          history exists, and it is labelled (``MetricDelta.same_source``).
        * One delta per (key, submarket).

        Args:
            current: Findings from the run in progress.
            exclude_run_id: The current run's id (its rows may already be stored).
        """
        hist = self.frame()
        hist = hist[hist["run_id"] != exclude_run_id]
        best: dict[tuple[str, str], MetricDelta] = {}
        for f in current:
            for m in f.metrics:
                prior = hist[(hist["key"] == m.key) & (hist["submarket"] == m.submarket) & (hist["period"] < m.period)]
                if prior.empty:
                    continue
                same = prior[prior["source"] == m.source]
                prev = (same if not same.empty else prior).sort_values(["period", "run_at"]).iloc[-1]
                delta = MetricDelta(
                    key=m.key, submarket=m.submarket, previous=float(prev["value"]),
                    current=m.value, previous_period=str(prev["period"]),
                    current_period=m.period, unit=m.unit,
                    previous_source=str(prev["source"] or ""), current_source=m.source,
                )
                k = (m.key, m.submarket)
                # Keep the first delta found, but upgrade to a same-source one if it appears later.
                if k not in best or (delta.same_source and not best[k].same_source):
                    best[k] = delta
        return list(best.values())


def get_store() -> MetricsStore:
    """Store at the configured location (``data/metrics.sqlite``)."""
    return MetricsStore(get_settings().metrics_db_path)
