"""Report writer node (brief mode): render charts + HTML/Markdown report.

Before rendering:

* Failures of the run (failed skills, failed summary) are turned into one
  :class:`~cre_monitor.errors.Incident`, so the report can show a user-friendly
  problem panel with the same reference ID the CLI / UI display and the log records.
* If a **house style** profile is active (``cre-monitor style learn``), topic
  wording is restyled by the style editor (live mode only; a number guard keeps
  every figure unchanged) and the report follows the profile's section order
  and headings. The executive summary was already styled by the synthesis step.
"""

from __future__ import annotations

import logging

from cre_monitor.config import get_settings
from cre_monitor.errors import incident_from_state
from cre_monitor.graph.state import AgentState
from cre_monitor.reporting.render import write_report
from cre_monitor.style import active_profile

logger = logging.getLogger(__name__)


def report_writer(state: AgentState) -> dict:
    """Graph node. Writes ``reports/<date>/`` and returns the file paths (+ incident)."""
    incident = incident_from_state(state)
    findings = state.get("findings") or []
    profile = active_profile(state.get("use_style", True))
    if profile is not None and not get_settings().cre_demo_mode:
        from cre_monitor.style.editor import apply_style

        findings = apply_style(findings, profile)
    paths = write_report(
        run_id=state["run_id"],
        synthesis=state["synthesis"],
        findings=findings,
        deltas=state.get("deltas") or [],
        issues=state.get("validation_issues") or [],
        incident=incident,
        style=profile,
    )
    logger.info("Report written: %s%s", paths, f" (house style: {profile.name})" if profile else "")
    return {"report_paths": {k: str(v) for k, v in paths.items()}, "incident": incident}
