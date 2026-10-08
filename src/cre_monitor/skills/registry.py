"""Discover, validate and serve skills defined as ``skills/<name>/SKILL.md``.

What is a skill?
----------------
A skill is a folder containing a ``SKILL.md`` file: YAML frontmatter
(machine-readable metadata) followed by a Markdown body (the expert
instructions given to the LLM). This mirrors the Anthropic "Agent Skills"
format and gives us **progressive disclosure**:

1. The planner only ever sees each skill's ``name`` + ``description`` -
   cheap to include for many skills.
2. Only when a skill is selected is its full Markdown body loaded into the
   system prompt of a dedicated sub-agent, together with *only* the tools
   that skill is allowed to use.

Adding a new research area therefore means adding a folder - no graph code
changes. See ``docs/SKILLS.md`` for the authoring guide.

Frontmatter schema (validated by :class:`SkillMetadata`)::

    name: office-rents              # must equal the folder name
    description: >-                 # what the planner sees; say WHEN to use it
      Prime and Grade A office rents ...
    tools: [web_search, fetch_document, metrics_history]
    metrics: [prime_rent, grade_a_rent]   # keys this skill should return
    sanity_ranges:                  # optional, used by the validator
      prime_rent: [30, 400]
    preferred_domains: [knightfrank.co.uk, cbre.co.uk]
    model_tier: skill               # router | skill | synthesis
    in_brief: true                  # run as part of the scheduled brief?
    order: 10                       # section order in the report
    keywords: [rent, psf, rental]   # demo-mode / fallback routing for chat
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import frontmatter
from pydantic import BaseModel, Field, ValidationError, model_validator

from cre_monitor.config import get_settings
from cre_monitor.catalog import metric_units

logger = logging.getLogger(__name__)


class SkillMetadata(BaseModel):
    """Validated frontmatter of a SKILL.md file."""

    name: str
    description: str = Field(min_length=20)
    tools: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    sanity_ranges: dict[str, tuple[float, float]] = Field(default_factory=dict)
    preferred_domains: list[str] = Field(default_factory=list)
    model_tier: str = "skill"
    in_brief: bool = True
    order: int = 100
    #: Lower-case trigger words. Used to route chat questions when no LLM is
    #: available (demo mode) or if the LLM router fails.
    keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_vocab(self) -> "SkillMetadata":
        # Catch typos early: a misspelt metric key would silently never chart.
        units = metric_units()
        unknown = [m for m in self.metrics if m not in units]
        unknown += [m for m in self.sanity_ranges if m not in units]
        if unknown:
            raise ValueError(f"unknown metric keys {unknown}; add them to the metric catalogue "
                             "(catalog/metrics.yaml or Dashboard > Manage metrics)")
        if self.model_tier not in {"router", "skill", "synthesis"}:
            raise ValueError(f"model_tier must be router|skill|synthesis, got {self.model_tier!r}")
        for key, (lo, hi) in self.sanity_ranges.items():
            if lo > hi:
                raise ValueError(f"sanity range for {key} has min > max")
        return self


class Skill(BaseModel):
    """A loaded skill: metadata + the instruction body + where it lives."""

    meta: SkillMetadata
    instructions: str = Field(description="Markdown body of SKILL.md (the system prompt).")
    path: Path

    @property
    def name(self) -> str:
        return self.meta.name

    def planner_card(self) -> str:
        """One-line summary shown to the planner (progressive disclosure, level 1)."""
        return f"- {self.meta.name}: {self.meta.description.strip()}"


class SkillRegistry:
    """In-memory index of all valid skills found under a directory.

    Invalid skills are logged and skipped rather than crashing the agent, so
    one colleague's half-written skill cannot take down the scheduled brief.
    Use :attr:`errors` (or the ``cre-monitor skills`` CLI command) to see them.
    """

    def __init__(self, skills_dir: Path, available_tools: set[str] | None = None) -> None:
        """Scan ``skills_dir``.

        Args:
            skills_dir: Directory containing one sub-folder per skill.
            available_tools: If given, skills referencing a tool outside this
                set are rejected (prevents silent "tool not found" at runtime).
        """
        self.skills_dir = skills_dir
        self._skills: dict[str, Skill] = {}
        self.errors: dict[str, str] = {}
        self._load(available_tools)

    # -- loading ------------------------------------------------------------
    def _load(self, available_tools: set[str] | None) -> None:
        if not self.skills_dir.exists():
            logger.warning("Skills directory %s does not exist", self.skills_dir)
            return
        for skill_md in sorted(self.skills_dir.glob("*/SKILL.md")):
            folder = skill_md.parent.name
            try:
                post = frontmatter.load(skill_md)
                meta = SkillMetadata.model_validate(post.metadata)
                if meta.name != folder:
                    raise ValueError(f"frontmatter name {meta.name!r} != folder {folder!r}")
                if available_tools is not None:
                    missing = set(meta.tools) - available_tools
                    if missing:
                        raise ValueError(f"unknown tools {sorted(missing)}")
                self._skills[meta.name] = Skill(
                    meta=meta, instructions=post.content.strip(), path=skill_md
                )
            except (ValidationError, ValueError, OSError) as exc:
                self.errors[folder] = str(exc)
                logger.error("Skipping invalid skill %s: %s", folder, exc)

    # -- queries ------------------------------------------------------------
    def get(self, name: str) -> Skill:
        """Return a skill by name. Raises ``KeyError`` if unknown."""
        return self._skills[name]

    def names(self) -> list[str]:
        """All skill names in report order."""
        return [s.name for s in self.all()]

    def all(self) -> list[Skill]:
        """All skills sorted by their ``order`` field, then name."""
        return sorted(self._skills.values(), key=lambda s: (s.meta.order, s.name))

    def research_skills(self) -> list[Skill]:
        """Skills that gather evidence (i.e. that have tools).

        Meta-skills such as ``market-synthesis`` have no tools: they only
        provide instructions to a downstream node and are never fanned out to.
        """
        return [s for s in self.all() if s.meta.tools]

    def brief_skills(self) -> list[Skill]:
        """Research skills that participate in the scheduled full brief."""
        return [s for s in self.research_skills() if s.meta.in_brief]

    def planner_catalog(self) -> str:
        """Text block listing every research skill, for the planner prompt."""
        return "\n".join(s.planner_card() for s in self.research_skills())

    def __contains__(self, name: object) -> bool:
        return name in self._skills

    def __len__(self) -> int:
        return len(self._skills)


@lru_cache(maxsize=1)
def get_registry() -> SkillRegistry:
    """Process-wide registry built from ``settings.skills_dir``.

    Tool names are validated against the tool catalogue so a typo in a
    SKILL.md ``tools`` list is caught at load time.
    """
    from cre_monitor.tools import TOOL_NAMES  # local import avoids a cycle

    return SkillRegistry(get_settings().skills_dir, available_tools=set(TOOL_NAMES))
