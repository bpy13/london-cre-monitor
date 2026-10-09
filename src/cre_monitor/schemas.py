"""Typed data contracts shared by skills, graph nodes, storage and reporting.

Every skill - whatever its topic - must return a :class:`SkillFinding`. Using
one uniform shape is what lets us add skills without touching downstream
code: the validator, the metrics store, the charts and the report all
operate on ``SkillFinding`` objects only.

Naming conventions for :class:`Metric` (important for charts and history):

* ``key`` is a snake_case identifier from the metric catalogue
  (``catalog/metrics.yaml``, e.g. ``prime_rent``, ``vacancy_rate``). Skills
  declare which keys they produce in their SKILL.md frontmatter.
* ``submarket`` is a name from the submarket catalogue
  (``catalog/submarkets.yaml``): ``"Central London"`` for market-wide figures,
  ``"UK"`` / ``"London"`` for macro series.
* ``period`` is the period the figure *describes* (``"2026-Q2"``,
  ``"2026-08"``); ``as_of`` is when it was *published*.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, field_validator

# --------------------------------------------------------------------------
# Controlled vocabularies
# --------------------------------------------------------------------------
# Metric keys (with units) and submarket names live in the editable catalogue
# (catalog/metrics.yaml, catalog/submarkets.yaml), read via cre_monitor.catalog:
# get_catalog().units(), .submarket_names(), .macro_geographies().


class SignalType(str, Enum):
    """Whether a signal is bad news or good news for a London office landlord /
    investor."""

    RISK = "risk"
    OPPORTUNITY = "opportunity"


class Severity(str, Enum):
    """How material a signal is. Used to sort the risk/opportunity matrix."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------


class Citation(BaseModel):
    """A source document backing a metric or insight."""

    title: str = Field(description="Human-readable title of the source.")
    url: str = Field(description="Link to the source. Use '' if offline/unknown.")
    publisher: str = Field(default="", description="E.g. 'Knight Frank', 'Bank of England'.")
    published: date | None = Field(default=None, description="Publication date if known.")


class Metric(BaseModel):
    """One numeric data point, e.g. *prime West End rent = £175 psf in 2026-Q1*."""

    # The allowed keys / places are listed in the research prompt (they are editable,
    # so they can't be baked into this schema at import time).
    key: str = Field(description="Metric key from the list in your instructions, e.g. 'prime_rent'.")
    submarket: str = Field(description="Submarket or geography from the list in your instructions.")
    value: float = Field(description="Numeric value only - no units or symbols.")
    unit: str = Field(description="Unit, e.g. 'GBP psf pa', '%', 'sq ft', 'months'.")
    period: str = Field(description="Period described, e.g. '2026-Q2' or '2026-08'.")
    source: str = Field(description="Publisher of the figure, e.g. 'Knight Frank'.")
    url: str = Field(default="", description="Link to the source document.")
    as_of: date | None = Field(default=None, description="Publication date of the source.")
    note: str = Field(default="", description="Definition caveats, e.g. 'availability incl. under-offer'.")

    @field_validator("key")
    @classmethod
    def _normalise_key(cls, v: str) -> str:
        # Be forgiving with LLM output ("Prime Rent" -> "prime_rent"); the
        # validator node still flags keys that are not in the catalogue.
        return v.strip().lower().replace(" ", "_").replace("-", "_")


class Signal(BaseModel):
    """A forward-looking risk or opportunity derived from the evidence."""

    type: SignalType
    severity: Severity
    title: str = Field(description="Short label, e.g. 'Grade A supply shortage in the City'.")
    rationale: str = Field(description="1-3 sentences linking evidence to implication.")
    submarket: str = Field(default="Central London")


# --------------------------------------------------------------------------
# Skill output
# --------------------------------------------------------------------------


class SkillFinding(BaseModel):
    """The single output contract every skill must satisfy."""

    skill: str = Field(description="Name of the skill that produced this finding.")
    headline: str = Field(description="One-sentence takeaway for an executive.")
    summary: str = Field(description="2-5 sentence narrative of the evidence and trend.")
    metrics: list[Metric] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list, description="Bullet-point observations.")
    signals: list[Signal] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="0-1 self-assessed confidence given source quality and recency.",
    )
    error: str | None = Field(
        default=None,
        description="Populated (and other fields left minimal) when the skill failed.",
    )


class ValidationIssue(BaseModel):
    """A data-quality problem detected by the deterministic validator node."""

    level: str = Field(description="'warning' or 'error'.")
    skill: str
    message: str
    metric_key: str | None = None
    submarket: str | None = None


class MetricDelta(BaseModel):
    """Change of a metric versus the previous agent run (from the metrics store)."""

    key: str
    submarket: str
    previous: float
    current: float
    previous_period: str
    current_period: str
    unit: str
    previous_source: str = ""
    current_source: str = ""

    @property
    def same_source(self) -> bool:
        """True if both values come from the same publisher.

        Cross-source changes mix definitional differences with real market
        movement (e.g. BNP vs Avison Young vacancy), so they are labelled.
        """
        return self.previous_source == self.current_source

    @property
    def is_material(self) -> bool:
        """Big enough to mention: >=0.1pp for % metrics, >=0.5% otherwise.

        Filters noise such as SONIA moving 3.733 -> 3.732.
        """
        if self.unit == "%":
            return abs(self.change) >= 0.1
        pct = self.pct_change
        return pct is None or abs(pct) >= 0.5

    @property
    def change(self) -> float:
        """Absolute change (current - previous)."""
        return self.current - self.previous

    @property
    def pct_change(self) -> float | None:
        """Relative change in %, or ``None`` if previous value is zero."""
        return None if self.previous == 0 else 100.0 * self.change / self.previous

    def describe(self) -> str:
        """One-liner, e.g. ``'City vacancy rate: 10.1 -> 9.4 % (2026-Q1 -> 2026-Q2)'``.

        For non-% units the relative change is appended; for % metrics the
        absolute change (percentage points) is what matters.
        """
        def fmt(v: float) -> str:
            return f"{v:,.0f}" if abs(v) >= 10_000 else f"{v:,.4g}"

        pct = f", {self.pct_change:+.1f}%" if self.pct_change is not None and self.unit != "%" else ""
        caveat = (
            "" if self.same_source
            else f" [different sources: {self.previous_source} -> {self.current_source}; partly definitional]"
        )
        return (
            f"{self.submarket} {self.key.replace('_', ' ')}: {fmt(self.previous)} -> {fmt(self.current)} "
            f"{self.unit} ({self.previous_period} -> {self.current_period}{pct}){caveat}"
        )


class SkillSelection(BaseModel):
    """Structured output of the planner LLM in chat mode."""

    skills: list[str] = Field(description="Names of skills needed to answer the question.")
    reasoning: str = Field(description="One sentence on why these skills were chosen.")


class ExecutiveSynthesis(BaseModel):
    """Structured output of the synthesis node (brief mode)."""

    title: str = Field(description="Report title, e.g. 'London Office Market Brief - October 2026'.")
    executive_summary: str = Field(description="3-6 sentence overview for senior management.")
    key_takeaways: list[str] = Field(description="3-7 bullets, most important first.")
    risks: list[Signal] = Field(default_factory=list)
    opportunities: list[Signal] = Field(default_factory=list)
    what_changed: list[str] = Field(
        default_factory=list, description="Material changes since the previous brief."
    )
    watch_list: list[str] = Field(
        default_factory=list, description="Upcoming events/data releases to monitor."
    )
