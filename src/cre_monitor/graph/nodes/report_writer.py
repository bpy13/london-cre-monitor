"""Report writer node (brief mode): render charts + HTML/Markdown report.

Failures of the run (failed skills, failed summary) are turned into one
:class:`~cre_monitor.errors.Incident` *here*, before rendering, so the report
can show a user-friendly problem panel with the same reference ID that the
CLI / UI display and the log records.
"""

from __future__ import annotations

import logging

from cre_monitor.errors import incident_from_state
from cre_monitor.graph.state import AgentState
from cre_monitor.reporting.render import write_report

logger = logging.getLogger(__name__)


def report_writer(state: AgentState) -> dict:
    """Graph node. Writes ``reports/<date>/`` and returns the file paths (+ incident)."""
    incident = incident_from_state(state)
    paths = write_report(
        run_id=state["run_id"],
        synthesis=state["synthesis"],
        findings=state.get("findings") or [],
        deltas=state.get("deltas") or [],
        issues=state.get("validation_issues") or [],
        incident=incident,
    )
    logger.info("Report written: %s", paths)
    return {"report_paths": {k: str(v) for k, v in paths.items()}, "incident": incident}
