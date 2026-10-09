"""List and delete generated market briefs.

A brief produced by ``report_writer`` consists of these files::

    reports/<date>/brief_<run_id>.html
    reports/<date>/brief_<run_id>.md
    reports/<date>/findings_<run_id>.json
    reports/<date>/charts/<run_id>/*.png      # per-run charts (current layout)

Briefs written before per-run chart folders existed share ``reports/<date>/charts/*.png``;
those shared PNGs are only removed when the *last* brief of that day is deleted.

Deleting a brief can optionally also remove its figures from the metrics history
(``MetricsStore.delete_run``). That is off by default because it changes "what
changed" deltas and Dashboard trends.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from cre_monitor.config import get_settings

logger = logging.getLogger(__name__)

#: Run ids look like ``20261008T121732-700292`` (see the planner). Validating them
#: guarantees a delete can never escape the reports folder (no path traversal).
RUN_ID_RE = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{6}$")


class Brief(BaseModel):
    """One generated brief on disk."""

    run_id: str
    date_dir: Path
    html: Path
    created_at: datetime

    @property
    def label(self) -> str:
        """Human-readable label for lists, e.g. ``08 Oct 2026 12:17 · 20261008T121732-700292``."""
        return f"{self.created_at:%d %b %Y %H:%M} · {self.run_id}"

    def files(self) -> list[Path]:
        """All files and folders belonging to this brief that currently exist."""
        candidates = [
            self.html,
            self.date_dir / f"brief_{self.run_id}.md",
            self.date_dir / f"findings_{self.run_id}.json",
            self.date_dir / "charts" / self.run_id,
        ]
        return [p for p in candidates if p.exists()]


def _created_at(run_id: str, fallback: Path) -> datetime:
    try:
        return datetime.strptime(run_id[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return datetime.fromtimestamp(fallback.stat().st_mtime)


def list_briefs(reports_dir: Path | None = None) -> list[Brief]:
    """All briefs, newest first."""
    reports_dir = reports_dir or get_settings().reports_dir
    briefs = []
    for html in reports_dir.glob("*/brief_*.html"):
        run_id = html.stem.removeprefix("brief_")
        briefs.append(Brief(run_id=run_id, date_dir=html.parent, html=html, created_at=_created_at(run_id, html)))
    return sorted(briefs, key=lambda b: b.created_at, reverse=True)


def sample_brief() -> Brief | None:
    """The sample brief committed to the repo (``examples/sample-brief/``), if present.

    Shown read-only in the UI's Briefs tab only while an installation has no briefs of
    its own, so a fresh clone has something to look at. It is never listed by
    :func:`list_briefs`, so export, delete and the performance check never touch it.
    """
    folder = get_settings().sample_brief_dir
    html = next(iter(sorted(folder.glob("brief_*.html"))), None) if folder.is_dir() else None
    if html is None:
        return None
    run_id = html.stem.removeprefix("brief_")
    return Brief(run_id=run_id, date_dir=folder, html=html, created_at=_created_at(run_id, html))


def get_brief(run_id: str, reports_dir: Path | None = None) -> Brief | None:
    """Find a brief by run id (``None`` if unknown or the id is malformed)."""
    if not RUN_ID_RE.match(run_id):
        return None
    return next((b for b in list_briefs(reports_dir) if b.run_id == run_id), None)


def delete_brief(run_id: str, *, with_metrics: bool = False, reports_dir: Path | None = None) -> list[Path]:
    """Delete a brief's files (and optionally its metrics history rows).

    Args:
        run_id: The brief's run id.
        with_metrics: Also remove this run's rows from ``data/metrics.sqlite``.
        reports_dir: Override the reports folder (tests).

    Returns:
        The paths that were removed.

    Raises:
        ValueError: If the run id is malformed or no such brief exists.
    """
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"Invalid brief id {run_id!r}")
    brief = get_brief(run_id, reports_dir)
    if brief is None:
        raise ValueError(f"No brief with id {run_id!r}")

    removed: list[Path] = []
    for path in brief.files():
        shutil.rmtree(path) if path.is_dir() else path.unlink()
        removed.append(path)

    # Legacy shared charts and empty folders: clean up only once no brief remains that day.
    if not list(brief.date_dir.glob("brief_*.html")):
        charts = brief.date_dir / "charts"
        if charts.exists():
            for png in charts.glob("*.png"):
                png.unlink()
                removed.append(png)
            if not any(charts.iterdir()):
                charts.rmdir()
        if brief.date_dir.exists() and not any(brief.date_dir.iterdir()):
            brief.date_dir.rmdir()
            removed.append(brief.date_dir)

    rows = 0
    if with_metrics:
        from cre_monitor.store import get_store

        rows = get_store().delete_run(run_id)
    logger.info("Deleted brief %s (%d paths, %d metric rows)", run_id, len(removed), rows)
    return removed
