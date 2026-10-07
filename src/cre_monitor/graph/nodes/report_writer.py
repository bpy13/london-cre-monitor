"""Report writer node (brief mode): render charts + HTML/Markdown report."""

from __future__ import annotations

import logging

from cre_monitor.graph.state import AgentState
from cre_monitor.reporting.render import write_report

logger = logging.getLogger(__name__)


def report_writer(state: AgentState) -> dict:
    """Graph node. Writes ``reports/<date>/`` and returns the file paths."""
    paths = write_report(
        run_id=state["run_id"],
        synthesis=state["synthesis"],
        findings=state.get("findings") or [],
        deltas=state.get("deltas") or [],
        issues=state.get("validation_issues") or [],
    )
    logger.info("Report written: %s", paths)
    return {"report_paths": {k: str(v) for k, v in paths.items()}}
