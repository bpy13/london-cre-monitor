"""Synthesis node (brief mode): turn all findings into an executive view.

Uses the strongest model with the ``market-synthesis`` meta-skill as its
system prompt. In demo mode a deterministic, rule-based synthesis is built
from the findings instead, so the report pipeline works without an LLM.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage

from cre_monitor.config import get_settings
from cre_monitor.graph.nodes.skill_runner import finding_to_json
from cre_monitor.graph.state import AgentState
from cre_monitor.llm import STRUCTURED, get_llm
from cre_monitor.schemas import ExecutiveSynthesis, MetricDelta, Severity, Signal, SignalType, SkillFinding, ValidationIssue
from cre_monitor.skills import get_registry

logger = logging.getLogger(__name__)

SYNTHESIS_SKILL = "market-synthesis"
_SEVERITY_RANK = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}


def _sorted_signals(findings: list[SkillFinding], kind: SignalType) -> list[Signal]:
    signals = [s for f in findings for s in f.signals if s.type == kind]
    return sorted(signals, key=lambda s: _SEVERITY_RANK[s.severity])


def rule_based_synthesis(findings: list[SkillFinding], deltas: list[MetricDelta], issues: list[ValidationIssue]) -> ExecutiveSynthesis:
    """Deterministic synthesis used in demo mode (and as LLM fallback)."""
    ok = [f for f in findings if not f.error]
    risks = _sorted_signals(ok, SignalType.RISK)
    opps = _sorted_signals(ok, SignalType.OPPORTUNITY)
    high_risks = [r.title for r in risks if r.severity == Severity.HIGH]
    summary = " ".join(f.headline for f in ok[:4])
    if high_risks:
        summary += f" Key risks to monitor: {'; '.join(high_risks[:3])}."
    return ExecutiveSynthesis(
        title=f"London Office Market Brief - {date.today():%B %Y}",
        executive_summary=summary or "No findings were produced in this run.",
        key_takeaways=[f.headline for f in ok][:7],
        risks=risks[:6],
        opportunities=opps[:6],
        # Material moves only; like-for-like (same-source) changes listed first.
        what_changed=[d.describe() for d in sorted(
            (d for d in deltas if d.is_material), key=lambda d: not d.same_source)][:10],
        watch_list=[
            "Next Bank of England MPC decision and updated rate path",
            "Q3 2026 broker quarterly figures (take-up, vacancy, prime rents)",
            "MEES EPC 'B' 2030 trajectory and any government consultation updates",
        ],
    )


def llm_synthesis(findings: list[SkillFinding], deltas: list[MetricDelta], issues: list[ValidationIssue]) -> ExecutiveSynthesis:
    """Synthesis by the synthesis-tier LLM guided by the market-synthesis skill."""
    skill = get_registry().get(SYNTHESIS_SKILL)
    payload = {
        "today": date.today().isoformat(),
        "findings": [json.loads(finding_to_json(f)) for f in findings],
        # describe() labels cross-source changes so the LLM can caveat them.
        "changes_vs_previous_periods": [d.describe() for d in deltas if d.is_material],
        "data_quality_issues": [i.message for i in issues],
    }
    model = get_llm(skill.meta.model_tier).with_structured_output(ExecutiveSynthesis, **STRUCTURED)
    return model.invoke(
        [SystemMessage(skill.instructions), HumanMessage(json.dumps(payload, ensure_ascii=False, default=str))]
    )


def synthesis(state: AgentState) -> dict:
    """Graph node."""
    findings = state.get("findings") or []
    deltas = state.get("deltas") or []
    issues = state.get("validation_issues") or []
    if get_settings().cre_demo_mode:
        return {"synthesis": rule_based_synthesis(findings, deltas, issues)}
    try:
        return {"synthesis": llm_synthesis(findings, deltas, issues)}
    except Exception as exc:  # noqa: BLE001 - a report with a basic summary beats no report
        logger.exception("LLM synthesis failed; using rule-based fallback")
        result = rule_based_synthesis(findings, deltas, issues)
        result.watch_list.append(f"(Synthesis LLM failed: {exc})")
        return {"synthesis": result}
