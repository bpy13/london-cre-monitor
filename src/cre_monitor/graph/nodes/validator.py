"""Validator node: deterministic data-quality checks on skill findings.

LLMs occasionally mis-read tables, mix up units or quote stale numbers.
Business users will make decisions from this output, so every finding
passes through plain-Python checks before it is stored or reported:

=====================  =======  ==============================================
Check                  Level    Action
=====================  =======  ==============================================
skill failed           warning  reported; nothing else to check
submarket alias        -        renamed to the catalogue name (e.g. Docklands)
unknown metric key     warning  kept (may be a useful new metric)
unexpected unit        warning  kept
non-canonical submkt   warning  kept
outside sanity range   error    **metric removed** (likely mis-read)
no source URL          warning  kept, flagged as unverifiable
stale (old as_of)      warning  kept, flagged
cross-source conflict  warning  both kept, flagged for analyst review
=====================  =======  ==============================================

Sanity ranges come from each skill's SKILL.md frontmatter, so domain experts
can tune them without touching code. Metric units, submarket names and aliases
come from the catalogue (:mod:`cre_monitor.catalog`).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

from cre_monitor.config import get_settings
from cre_monitor.graph.state import AgentState, Replace
from cre_monitor.catalog import get_catalog
from cre_monitor.schemas import Metric, SkillFinding, ValidationIssue
from cre_monitor.skills import get_registry

logger = logging.getLogger(__name__)


def _sanity_ranges() -> dict[str, tuple[float, float]]:
    """Merge sanity ranges declared across all skills (later skills win on clashes)."""
    ranges: dict[str, tuple[float, float]] = {}
    for skill in get_registry().all():
        ranges.update(skill.meta.sanity_ranges)
    return ranges


def normalise_place(m: Metric) -> Metric:
    """Map a submarket alias or case variant to its catalogue name ("Docklands" -> "Canary Wharf").

    Unknown places are left as they are (``check_metric`` then warns about them).
    """
    canonical = get_catalog().canonical_place(m.submarket)
    if canonical is None or canonical == m.submarket:
        return m
    return m.model_copy(update={"submarket": canonical})


def check_metric(skill: str, m: Metric, ranges: dict[str, tuple[float, float]], today: date) -> tuple[bool, list[ValidationIssue]]:
    """Validate a single metric.

    Returns:
        ``(keep, issues)`` - ``keep`` is False if the metric must be dropped.
    """
    s = get_settings()
    issues: list[ValidationIssue] = []

    def issue(level: str, msg: str) -> None:
        issues.append(ValidationIssue(level=level, skill=skill, message=msg, metric_key=m.key, submarket=m.submarket))

    units = get_catalog().units()
    if m.key not in units:
        issue("warning", f"Unknown metric key '{m.key}'.")
    elif m.unit != units[m.key]:
        issue("warning", f"{m.key} reported in '{m.unit}', expected '{units[m.key]}'.")
    if m.submarket not in get_catalog().all_places():
        issue("warning", f"Non-canonical submarket '{m.submarket}'.")
    if m.key in ranges:
        lo, hi = ranges[m.key]
        if not lo <= m.value <= hi:
            issue("error", f"{m.key}={m.value:g} for {m.submarket} outside plausible range [{lo:g}, {hi:g}]; dropped.")
            return False, issues
    if not m.url:
        issue("warning", f"{m.key} ({m.submarket}) from '{m.source}' has no source URL.")
    if m.as_of and m.as_of < today - timedelta(days=s.stale_after_days):
        issue("warning", f"{m.key} ({m.submarket}) is stale: published {m.as_of.isoformat()}.")
    return True, issues


def find_conflicts(findings: list[SkillFinding]) -> list[ValidationIssue]:
    """Flag the same metric/submarket/period reported differently by different sources."""
    s = get_settings()
    groups: dict[tuple[str, str, str], list[tuple[str, Metric]]] = defaultdict(list)
    for f in findings:
        for m in f.metrics:
            groups[(m.key, m.submarket, m.period)].append((f.skill, m))

    issues = []
    for (key, submarket, period), items in groups.items():
        by_source = {m.source: (skill, m) for skill, m in items}
        if len(by_source) < 2:
            continue
        values = [m.value for _, m in by_source.values()]
        lo, hi = min(values), max(values)
        if get_catalog().units().get(key) == "%":
            conflict = hi - lo > s.conflict_tolerance_pct_points
        else:
            conflict = lo > 0 and 100 * (hi - lo) / lo > s.conflict_tolerance_rent_pct
        if conflict:
            detail = "; ".join(f"{src}: {m.value:g}" for src, (_, m) in by_source.items())
            issues.append(
                ValidationIssue(
                    level="warning", skill=items[0][0], metric_key=key, submarket=submarket,
                    message=f"Sources disagree on {key} for {submarket} {period} ({detail}). "
                            "Likely definitional differences - check before quoting.",
                )
            )
    return issues


def validate(findings: list[SkillFinding], today: date | None = None) -> tuple[list[SkillFinding], list[ValidationIssue]]:
    """Pure function behind the node - easy to unit test.

    Returns:
        ``(cleaned_findings, issues)``.
    """
    today = today or date.today()
    ranges = _sanity_ranges()
    cleaned: list[SkillFinding] = []
    issues: list[ValidationIssue] = []
    for f in findings:
        if f.error:
            issues.append(ValidationIssue(level="warning", skill=f.skill, message=f"Skill failed: {f.error}"))
            cleaned.append(f)
            continue
        kept = []
        for m in f.metrics:
            m = normalise_place(m)
            keep, metric_issues = check_metric(f.skill, m, ranges, today)
            issues.extend(metric_issues)
            if keep:
                kept.append(m)
        if not f.citations and f.metrics:
            issues.append(ValidationIssue(level="warning", skill=f.skill, message="Finding has no citations."))
        cleaned.append(f.model_copy(update={"metrics": kept}))
    issues.extend(find_conflicts(cleaned))
    return cleaned, issues


def validator(state: AgentState) -> dict:
    """Graph node."""
    cleaned, issues = validate(state.get("findings") or [])
    errors = sum(i.level == "error" for i in issues)
    logger.info("Validation: %d issues (%d errors)", len(issues), errors)
    return {"findings": Replace(cleaned), "validation_issues": issues}
