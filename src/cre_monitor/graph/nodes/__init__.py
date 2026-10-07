"""Graph nodes - one module per node. See ``graph/builder.py`` for wiring."""

from cre_monitor.graph.nodes.chat_answer import chat_answer
from cre_monitor.graph.nodes.persist import persist, route_after_persist
from cre_monitor.graph.nodes.planner import fan_out, planner
from cre_monitor.graph.nodes.report_writer import report_writer
from cre_monitor.graph.nodes.skill_runner import skill_runner
from cre_monitor.graph.nodes.synthesis import synthesis
from cre_monitor.graph.nodes.validator import validator

__all__ = [
    "chat_answer", "fan_out", "persist", "planner", "report_writer",
    "route_after_persist", "skill_runner", "synthesis", "validator",
]
