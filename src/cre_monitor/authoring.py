"""Claude-assisted authoring for non-technical users (Skills tab, Dashboard > Metrics).

Three helpers, each one structured-output call to the synthesis-tier model:

* :func:`draft_skill`   - write a complete SKILL.md draft from a name and a
  plain-English purpose, following the house template and using only existing
  tools and catalogue metrics.
* :func:`review_skill`  - check a draft for unclear instructions, overlap with
  other skills, metrics the instructions never explain how to find, etc.
* :func:`assess_metric` - can the current workflow collect a requested metric?
  Returns one of three verdicts:

  ==================== ======================================================
  already_collected    it exists in the catalogue -> just track it
  needs_skill_change   an existing skill can collect it with extra guidance
                       (new catalogue entry + skill change, shown for approval)
  not_feasible         the current tools can't reach the data (e.g. paywalled
                       database); explains what a developer would need to add
  ==================== ======================================================

  :func:`apply_assessment` carries out an approved verdict;
  :func:`test_metric` runs the skill once to see whether the figure comes back.

Nothing here writes files without the caller's explicit apply/save step, and
every LLM answer is re-validated in code (unknown tools/metrics/skills are
dropped or downgraded) - the model proposes, the code decides.
In demo mode (no API key) only the deterministic parts work.
"""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from cre_monitor.catalog import MetricDef, add_metric, get_catalog, set_tracked, suggest_key
from cre_monitor.config import get_settings
from cre_monitor.skills.editor import TOOL_LABELS, SkillDraft, attach_metric

logger = logging.getLogger(__name__)


class NeedsLiveMode(RuntimeError):
    """The step needs Claude, but the app is in demo mode."""


def _llm(schema):
    if get_settings().cre_demo_mode:
        raise NeedsLiveMode("This needs Claude (live mode). Demo mode can't assess or draft new content.")
    from cre_monitor.llm import STRUCTURED, get_llm  # read at call time so tests can patch it

    return get_llm("synthesis").with_structured_output(schema, **STRUCTURED)


def _context() -> str:
    """What the model needs to know about the current setup (tools, metrics, skills)."""
    from cre_monitor.skills.registry import get_registry
    from cre_monitor.tools import TOOLS

    cat = get_catalog()
    tools = "\n".join(f"- {n}: {TOOL_LABELS.get(n, '')}. {(t.description or '').splitlines()[0]}"
                      for n, t in TOOLS.items())
    metrics = "\n".join(f"- {m.key} ({m.unit}, {m.group}): {m.definition}" for m in cat.metrics)
    skills = "\n".join(f"- {s.name} [tools: {', '.join(s.meta.tools) or 'none'}; metrics: "
                       f"{', '.join(s.meta.metrics) or 'none'}]: {s.meta.description.strip()}"
                       for s in get_registry().all())
    places = ", ".join(cat.all_places())
    return (f"AVAILABLE TOOLS (the only data access the agent has):\n{tools}\n\n"
            f"METRIC CATALOGUE:\n{metrics}\n\nEXISTING SKILLS:\n{skills}\n\nSUBMARKETS: {places}")


# --------------------------------------------------------------------------
# Skill drafting and review
# --------------------------------------------------------------------------

class RangeItem(BaseModel):
    metric: str
    min: float
    max: float


class _DraftOut(BaseModel):
    """Model output for a skill draft (ranges as a list: tuples don't map well to JSON schema)."""

    description: str = Field(description="2-3 sentences: what it researches and WHEN the router should use it.")
    tools: list[str]
    metrics: list[str] = Field(description="Only keys from the METRIC CATALOGUE.")
    sanity_ranges: list[RangeItem] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list, description="Lower-case trigger words for fallback routing.")
    in_brief: bool = True
    instructions: str = Field(description="Markdown body with sections: Goal, Definitions, Method, "
                                          "Interpreting, Output guidance.")
    missing_metrics: list[str] = Field(default_factory=list,
                                       description="Metrics this skill should record that are NOT in the catalogue.")


DRAFT_PROMPT = """You write SKILL.md files for a London office market research agent used by a long-term
London office investor/developer. A skill = expert instructions for one research topic, run by a
tool-using research sub-agent. Follow the EXAMPLE's structure and level of precision.

Rules:
- Use ONLY tools from AVAILABLE TOOLS and metric keys from the METRIC CATALOGUE. If the topic needs a metric that
  is not in the catalogue, list it in missing_metrics instead.
- Do not duplicate an existing skill; state in the description how this topic differs.
- Instructions: precise definitions (brokers define terms differently), a concrete search method with example
  queries, how to interpret the evidence for a landlord/investor, and output guidance (which metric per
  submarket/period/source).
- Sanity ranges: generous plausible bounds per metric, to catch mis-read numbers.
"""


def draft_skill(name: str, purpose: str) -> tuple[SkillDraft, list[str]]:
    """Draft a full skill for ``purpose``. Returns ``(draft, notes for the user)``.

    Unknown tools/metrics proposed by the model are removed and reported in the notes.
    """
    from cre_monitor.skills.registry import get_registry
    from cre_monitor.tools import TOOL_NAMES

    example = get_registry().get("office-rents").path.read_text(encoding="utf-8")
    out: _DraftOut = _llm(_DraftOut).invoke([
        SystemMessage(DRAFT_PROMPT + "\n\n" + _context() + "\n\nEXAMPLE SKILL.md:\n" + example),
        HumanMessage(f"Skill name: {name}\nWhat it should research: {purpose}"),
    ])
    units = get_catalog().units()
    notes = []
    tools = [t for t in out.tools if t in TOOL_NAMES]
    if dropped := sorted(set(out.tools) - set(tools)):
        notes.append(f"Removed unknown tools {dropped}.")
    metrics = [m for m in out.metrics if m in units]
    if dropped := sorted(set(out.metrics) - set(metrics)):
        notes.append(f"Removed metrics not in the catalogue: {dropped}.")
    if out.missing_metrics:
        notes.append("Suggested new metrics (add them in Dashboard > Metrics first, then to this skill): "
                     + "; ".join(out.missing_metrics))
    ranges = {r.metric: (min(r.min, r.max), max(r.min, r.max)) for r in out.sanity_ranges if r.metric in metrics}
    draft = SkillDraft(name=name, description=out.description, tools=tools, metrics=metrics, sanity_ranges=ranges,
                       preferred_domains=out.preferred_domains, keywords=[k.lower() for k in out.keywords],
                       in_brief=out.in_brief, instructions=out.instructions, order=200)
    return draft, notes


class SkillReview(BaseModel):
    """Claude's review of a skill draft."""

    ok: bool = Field(description="True if the skill can be used as is (minor suggestions allowed).")
    summary: str = Field(description="One or two sentences.")
    issues: list[str] = Field(default_factory=list, description="Problems that should be fixed before saving.")
    suggestions: list[str] = Field(default_factory=list, description="Optional improvements.")


REVIEW_PROMPT = """You review SKILL.md drafts for a London office market research agent. Check:
1. Is the description clear about WHEN to use the skill, and distinct from existing skills?
2. Do the instructions define terms precisely and give a concrete method (queries, which sources)?
3. Does every listed metric have guidance on how to find and record it? Are units and periods clear?
4. Can the listed tools actually reach the data (e.g. paywalled databases are out of reach)?
5. Are the plausible ranges sensible?
Be concise and specific. Mark ok=false only for real problems."""


def review_skill(draft: SkillDraft) -> SkillReview:
    """Ask Claude to review a draft (nothing is saved)."""
    return _llm(SkillReview).invoke([
        SystemMessage(REVIEW_PROMPT + "\n\n" + _context()),
        HumanMessage("DRAFT SKILL.md:\n" + draft.to_markdown()),
    ])


# --------------------------------------------------------------------------
# Metric feasibility
# --------------------------------------------------------------------------

Verdict = Literal["already_collected", "needs_skill_change", "not_feasible"]


class MetricAssessment(BaseModel):
    """Can the current workflow collect a requested metric, and what would change?"""

    verdict: Verdict
    reasoning: str = Field(description="2-4 sentences explaining the verdict for a non-technical user.")
    existing_key: str = Field(default="", description="already_collected: the catalogue key that matches.")
    key: str = Field(default="", description="New snake_case key (needs_skill_change).")
    label: str = Field(default="", description="Plain-English name, e.g. 'Average lease length'.")
    unit: str = Field(default="", description="e.g. 'years', '%', 'GBP psf pa', 'sq ft'.")
    group: str = Field(default="", description="Rents, Vacancy & availability, Leasing, Supply pipeline, "
                                               "Investment, Occupier demand or Macro.")
    definition: str = Field(default="", description="Precise one-sentence definition.")
    target_skill: str = Field(default="", description="needs_skill_change: the existing skill best placed to collect it.")
    sanity_min: float | None = None
    sanity_max: float | None = None
    guidance: str = Field(default="", description="needs_skill_change: Markdown for the skill: where the figure is "
                                                  "published, example search queries, how to record it.")
    preferred_domains: list[str] = Field(default_factory=list)
    likely_sources: list[str] = Field(default_factory=list, description="Publishers that report it, with frequency.")
    developer_changes: str = Field(default="", description="not_feasible: what a developer would need to add "
                                                           "(e.g. a licensed data feed as a new tool).")


ASSESS_PROMPT = """You assess whether a London office market research agent can collect a metric a user asks for.
The agent can ONLY use the AVAILABLE TOOLS below (public web search, reading public web pages/PDFs, news feeds,
Bank of England and ONS/Nomis statistics, its own history). It cannot log in to paid databases (CoStar, MSCI,
Radius Data Exchange, etc.).

Decide:
- already_collected: an existing catalogue metric already measures this (set existing_key).
- needs_skill_change: the figure is published regularly in public sources the tools can reach (e.g. broker
  quarterly reports, ONS); pick the existing skill whose topic fits best (target_skill), and fill key, label,
  unit, group, definition, plausible range and guidance (Markdown the skill will follow).
- not_feasible: only available behind paywalls / not published / too irregular; explain developer_changes.
Be realistic about public availability and say how often it is published."""


def match_existing(request: str) -> MetricDef | None:
    """Catalogue metric whose key or label matches the request exactly (case-insensitive), if any."""
    cat = get_catalog()
    text = request.strip().casefold()
    return next((m for m in cat.metrics if text in (m.key.casefold(), m.label.casefold())
                 or suggest_key(request) == m.key), None)


def assess_metric(request: str) -> MetricAssessment:
    """Assess a metric request (see module docstring). Exact catalogue matches need no LLM."""
    if existing := match_existing(request):
        return MetricAssessment(verdict="already_collected", existing_key=existing.key, label=existing.label,
                                unit=existing.unit, reasoning=f"'{existing.label}' is already in the catalogue.")
    a: MetricAssessment = _llm(MetricAssessment).invoke([
        SystemMessage(ASSESS_PROMPT + "\n\n" + _context()),
        HumanMessage(f"Requested metric: {request}"),
    ])
    return _check_assessment(a)


def _check_assessment(a: MetricAssessment) -> MetricAssessment:
    """Re-validate the model's answer against the real catalogue and skills."""
    from cre_monitor.skills.registry import get_registry

    cat = get_catalog()
    if a.verdict == "already_collected":
        if cat.metric(a.existing_key) is None:
            return a.model_copy(update={"verdict": "not_feasible", "reasoning": a.reasoning +
                                        " (The suggested existing metric was not found in the catalogue.)"})
        return a
    if a.verdict == "needs_skill_change":
        key = a.key if a.key and cat.metric(a.key) is None else suggest_key(a.label or a.key)
        if cat.metric(key) is not None:
            return a.model_copy(update={"verdict": "already_collected", "existing_key": key})
        research = {s.name for s in get_registry().research_skills()}
        if a.target_skill not in research or not a.unit or not a.label:
            return a.model_copy(update={"verdict": "not_feasible", "reasoning": a.reasoning +
                                        " (The proposal was incomplete - no valid skill, label or unit.)"})
        return a.model_copy(update={"key": key})
    return a


def apply_assessment(a: MetricAssessment) -> str:
    """Carry out an approved assessment. Returns a confirmation message.

    * already_collected  -> start tracking the existing metric;
    * needs_skill_change -> add the catalogue entry (tracked) and update the target skill.
    """
    if a.verdict == "already_collected":
        set_tracked(a.existing_key, True)
        return f"'{get_catalog().label(a.existing_key)}' is now tracked on the Dashboard."
    if a.verdict != "needs_skill_change":
        raise ValueError("This metric can't be collected with the current tools; nothing was changed.")
    add_metric(MetricDef(key=a.key, label=a.label, unit=a.unit, group=a.group or "Other",
                         definition=a.definition, tracked=True))
    rng = (a.sanity_min, a.sanity_max) if a.sanity_min is not None and a.sanity_max is not None else None
    try:
        attach_metric(a.target_skill, a.key, sanity_range=rng, guidance=a.guidance, domains=a.preferred_domains)
    except Exception:
        # Keep catalogue and skills consistent: undo the catalogue entry if the skill change failed.
        from cre_monitor.catalog import remove_metric

        remove_metric(a.key)
        raise
    return (f"Added '{a.label}' and asked skill '{a.target_skill}' to collect it. It appears on the Dashboard "
            "after the next brief (or test it now).")


def test_metric(a: MetricAssessment):
    """Run the target skill once (live) and report whether the metric came back.

    Returns:
        ``(found, finding)`` - found is True if at least one figure for the key was returned.
    """
    if get_settings().cre_demo_mode:
        raise NeedsLiveMode("Testing needs live mode (demo mode only replays canned findings).")
    from cre_monitor.catalog import skills_using_metric
    from cre_monitor.graph.nodes.skill_runner import run_skill

    key = a.existing_key or a.key
    skill = a.target_skill or next(iter(skills_using_metric(key)), "")
    if not skill:
        raise ValueError(f"No skill collects '{key}' yet, so there is nothing to test.")
    label = get_catalog().label(key)
    finding = run_skill(skill, f"Find the latest '{label}' ({key}) for central London and its submarkets. "
                               "Record it as a metric with source and URL.")
    return any(m.key == key for m in finding.metrics), finding
