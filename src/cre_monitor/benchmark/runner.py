"""Run a performance check: targeted skill runs scored against an answer key, or a brief judgement.

**Figure run** (:func:`run_figures`)

1. :func:`plan_run` groups the key's accepted figures by the skill that collects
   each metric (skills that don't collect any of them are not run, which keeps a
   run cheap). Figures no skill collects are reported as "not collectable".
2. Each skill gets a **period-pinned** task listing the figures to find
   (:func:`benchmark_task`) - never the expected values. With ``hints`` the task
   also names the report's publisher and citation as leads to follow up.
3. Skills run exactly as in production (same prompts, tools, step budget); their
   findings pass the production validator. The transcript is kept for the
   grounding check and the token count.
4. Scoring (:mod:`.scoring`), citation check (:mod:`.citations`), cost estimate;
   the record is saved (:mod:`.store`).

**Brief judgement** (:func:`run_judge`): readability of a chosen existing brief vs
the reference report, citation check of the brief's figures (both free), and the
Claude rubric (:mod:`.judge`, live mode).

Cost: estimated up front (:func:`estimate_usd`) and recorded afterwards from
token usage; a warning is added when a run exceeds ``BENCHMARK_TARGET_USD``.
``BENCHMARK_MAX_USD`` is an optional cap (off by default): when set, no further
skill is *started* once it is reached - a running skill is never interrupted.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from langchain_core.messages import AIMessage, ToolMessage

from cre_monitor.benchmark.answer_key import AnswerKey, KeyEntry, report_text
from cre_monitor.benchmark.citations import check_citations
from cre_monitor.benchmark.scoring import readability, score_figures
from cre_monitor.benchmark.store import RunRecord, new_run_id, save_run
from cre_monitor.catalog import get_catalog
from cre_monitor.config import get_settings
from cre_monitor.schemas import Metric

logger = logging.getLogger(__name__)

#: Typical tokens for one skill run (input incl. tool results, output incl. thinking) -
#: a rough planning figure for the up-front estimate; actual usage is recorded.
TYPICAL_SKILL_TOKENS = (45_000, 6_000)


# --------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------

def price(model: str) -> tuple[float, float]:
    """USD per million (input, output) tokens for ``model`` (estimate; see config.model_prices)."""
    s = get_settings()
    return s.model_prices.get(model) or s.model_prices.get(s.model_skill) or (3.0, 15.0)


def usd(tokens_in: int, tokens_out: int, model: str) -> float:
    p_in, p_out = price(model)
    return round((tokens_in * p_in + tokens_out * p_out) / 1e6, 4)


def usage_of(messages: list) -> tuple[int, int]:
    """Total (input, output) tokens reported on the AI messages of a transcript."""
    t_in = t_out = 0
    for m in messages:
        meta = getattr(m, "usage_metadata", None) if isinstance(m, AIMessage) else None
        if meta:
            t_in += int(meta.get("input_tokens", 0))
            t_out += int(meta.get("output_tokens", 0))
    return t_in, t_out


def estimate_usd(n_skills: int) -> float:
    """Up-front estimate for a figure run with ``n_skills`` skills."""
    return round(n_skills * usd(*TYPICAL_SKILL_TOKENS, get_settings().model_skill), 2)


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

@dataclass
class RunPlan:
    period: str
    groups: dict[str, list[KeyEntry]] = field(default_factory=dict)   # skill -> entries
    not_collectable: list[KeyEntry] = field(default_factory=list)

    @property
    def estimate_usd(self) -> float:
        return estimate_usd(len(self.groups))


def plan_run(key: AnswerKey) -> RunPlan:
    """Assign each accepted entry to the research skill that collects its metric.

    When several skills collect a metric, the one covering most of the key's
    metrics wins, so as few skills as possible run.
    """
    from cre_monitor.skills.registry import get_registry

    research = get_registry().research_skills()
    entries = key.accepted()
    wanted = {e.key for e in entries}
    coverage = {s.name: len(wanted & set(s.meta.metrics)) for s in research}
    plan = RunPlan(period=key.period)
    for e in entries:
        collectors = [s.name for s in research if e.key in s.meta.metrics]
        if not collectors:
            plan.not_collectable.append(e)
            continue
        best = max(collectors, key=lambda n: (coverage[n], -collectors.index(n)))
        plan.groups.setdefault(best, []).append(e)
    return plan


def benchmark_task(entries: list[KeyEntry], period: str, *, hints: bool, publisher: str = "") -> str:
    """The question a skill receives: which figures to find, for which period (never the values)."""
    cat = get_catalog()
    lines = []
    for e in entries:
        line = f"- {cat.label(e.key)} (`{e.key}`, {e.unit}) for {e.submarket}, period {e.period}"
        if hints:
            lead = e.citation or e.source
            line += f" - reported by {e.source}" + (f"; lead: {lead}" if lead and lead != e.source else "")
        lines.append(line)
    intro = (f"Performance check task. Find these specific figures for {period or 'the stated periods'} "
             "(not the latest quarter, unless it is the same):")
    tail = ("Record each one as a metric with exactly that key, submarket and period, plus its source and URL. "
            "Prefer the publisher named above where given; if you use another source, record that source.")
    if hints and publisher:
        tail += f" The reference report is by {publisher}."
    return "\n".join([intro, *lines, tail])


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------

def _clean_score(obj) -> dict:
    d = asdict(obj)
    d.pop("results", None)
    return d


def run_figures(key: AnswerKey, *, hints: bool = True, max_usd: float | None = None) -> RunRecord:
    """Run the planned skills and score their figures against the key (live mode).

    Args:
        key: A moderated answer key (only ``accepted`` entries are used).
        hints: Give the agent the report's publisher/citation per figure as leads.
        max_usd: Optional cap; defaults to ``BENCHMARK_MAX_USD`` (None = no cap).
    """
    from cre_monitor.authoring import NeedsLiveMode
    from cre_monitor.graph.nodes.skill_runner import run_skill
    from cre_monitor.graph.nodes.validator import validate

    s = get_settings()
    if s.cre_demo_mode:
        raise NeedsLiveMode("A performance run needs live mode (demo mode replays canned findings).")
    if not key.accepted():
        raise ValueError("Accept at least one answer-key entry first.")
    max_usd = s.benchmark_max_usd if max_usd is None else max_usd
    plan = plan_run(key)
    started = time.monotonic()
    record = RunRecord(run_id=new_run_id(), kind="figures", report=key.report, created_at=datetime.now(),
                       period=key.period, hints=hints)
    metrics: list[Metric] = []
    tool_texts: list[str] = []
    for skill, entries in plan.groups.items():
        if max_usd is not None and record.cost_usd >= max_usd:
            record.skipped_skills.append(skill)
            continue
        trace: list = []
        finding = run_skill(skill, benchmark_task(entries, key.period, hints=hints, publisher=key.publisher),
                            trace=trace)
        record.skills.append(skill)
        if finding.error:
            record.warnings.append(f"{skill} failed: {finding.error[:200]}")
        cleaned, _ = validate([finding])               # same checks as production (incl. alias mapping)
        metrics += cleaned[0].metrics
        tool_texts += [str(m.content) for m in trace if isinstance(m, ToolMessage)]
        t_in, t_out = usage_of(trace)
        record.tokens_in += t_in
        record.tokens_out += t_out
        record.cost_usd = round(record.cost_usd + usd(t_in, t_out, s.model_skill), 4)

    fig = score_figures(key.accepted(), metrics, tool_texts, units=get_catalog().units(),
                        tol_pp=s.benchmark_tol_pp, tol_rel=s.benchmark_tol_rel)
    cit, cit_results = check_citations(metrics)
    record.figure, record.entries = _clean_score(fig), [asdict(r) for r in fig.results]
    record.citation, record.citations = asdict(cit), [asdict(r) for r in cit_results]
    record.duration_s = round(time.monotonic() - started, 1)
    if plan.not_collectable:
        record.warnings.append(f"{len(plan.not_collectable)} accepted figure(s) are not collected by any skill "
                               "(add the metric to a skill to include them); counted as missing.")
    if record.skipped_skills:
        record.warnings.append(f"Cap of ${max_usd:.2f} reached: skipped {', '.join(record.skipped_skills)}.")
    _cost_warning(record)
    save_run(record)
    logger.info("Performance run %s on %s: coverage %s%%, accuracy %s%%, est. $%.2f", record.run_id, key.report,
                fig.coverage, fig.accuracy, record.cost_usd)
    return record


def _cost_warning(record: RunRecord) -> None:
    target = get_settings().benchmark_target_usd
    if record.cost_usd > target:
        record.warnings.append(f"Estimated cost ${record.cost_usd:.2f} is above the ${target:.2f} target.")


def _brief_texts(brief_run_id: str | None):
    """(brief, markdown, metrics) for a brief id, or the latest brief."""
    from cre_monitor.reporting.briefs import get_brief, list_briefs

    brief = get_brief(brief_run_id) if brief_run_id else next(iter(list_briefs()), None)
    if brief is None:
        raise ValueError("No brief to judge yet - run a brief first.")
    md_path = brief.date_dir / f"brief_{brief.run_id}.md"
    markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    findings_path = brief.date_dir / f"findings_{brief.run_id}.json"
    metrics: list[Metric] = []
    if findings_path.exists():
        data = json.loads(findings_path.read_text(encoding="utf-8"))
        metrics = [Metric.model_validate(m) for f in data.get("findings", []) for m in f.get("metrics", [])]
    return brief, markdown, metrics


def run_judge(key: AnswerKey, brief_run_id: str | None = None) -> RunRecord:
    """Judge a brief against the reference: free statistics always, the Claude rubric in live mode."""
    from cre_monitor.authoring import NeedsLiveMode
    from cre_monitor.benchmark.judge import MAX_BRIEF_CHARS, judge_brief

    started = time.monotonic()
    brief, markdown, metrics = _brief_texts(brief_run_id)
    record = RunRecord(run_id=new_run_id(), kind="judge", report=key.report, created_at=datetime.now(),
                       period=key.period, brief_run_id=brief.run_id)
    record.readability_brief = asdict(readability(markdown))
    if (ref := report_text(key.report)) is not None:
        record.readability_reference = asdict(readability(ref))
    cit, cit_results = check_citations(metrics)
    record.citation, record.citations = asdict(cit), [asdict(r) for r in cit_results]
    try:
        judgement = judge_brief(key, markdown)
        record.judgement = judgement.model_dump() | {"theme_coverage": judgement.theme_coverage}
        # Estimate: ~4 characters per token in, ~1.5k tokens out (the rubric).
        t_in = (min(len(markdown), MAX_BRIEF_CHARS) + 3000) // 4
        record.tokens_in, record.tokens_out = t_in, 1500
        record.cost_usd = usd(t_in, 1500, get_settings().model_skill)
    except NeedsLiveMode as exc:
        record.warnings.append(f"{exc} Readability and the citation check were still computed.")
    record.duration_s = round(time.monotonic() - started, 1)
    _cost_warning(record)
    save_run(record)
    return record
