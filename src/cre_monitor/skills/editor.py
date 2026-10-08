"""Create, edit, delete and restore skills - the backend of the UI's 🧩 Skills tab.

A skill is ``skills/<name>/SKILL.md`` (see :mod:`cre_monitor.skills.registry`).
This module lets non-developers change skills safely:

* :class:`SkillDraft` is an editable form of a skill (frontmatter fields + the
  instructions). :func:`validate_draft` runs the *same* checks the registry
  applies at startup (plus a few friendlier ones), so a draft that validates
  here will load.
* :func:`save_skill` writes the file, keeping the previous version in
  ``skills/.history/<name>/`` and refusing to overwrite someone else's newer
  save (:class:`~cre_monitor.versioned.ConflictError`).
* :func:`delete_skill` is a soft delete into ``skills/.trash/``;
  :func:`restore_skill` brings it back. ``market-synthesis`` is protected (the
  summary step depends on it).
* :func:`attach_metric` / :func:`detach_metric` add or remove a metric across
  skills (used by Dashboard > Metrics).

Every change clears the caches that hold skills, so the next brief or chat
question uses the new version. Files are tracked in git: UI changes show up
as uncommitted changes for the team to review and commit (:func:`git_changes`).

LLM helpers (draft a skill from a description, review a draft) are in
:mod:`cre_monitor.authoring`.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import frontmatter
import yaml
from pydantic import BaseModel, Field, ValidationError

from cre_monitor.config import PROJECT_ROOT, get_settings
from cre_monitor.versioned import check_version, file_version, list_versions, write_text

logger = logging.getLogger(__name__)

#: Skills the app depends on by name (graph/nodes/synthesis.py loads market-synthesis).
PROTECTED_SKILLS: frozenset[str] = frozenset({"market-synthesis"})

#: Plain-English names of the research tools for the UI. Adding a *new* tool is a
#: developer task (see tools/__init__.py); the UI only lets users choose from these.
TOOL_LABELS: dict[str, str] = {
    "web_search": "Web search - broker research, trade press, news",
    "fetch_document": "Read a web page or PDF in full",
    "rss_news": "News feeds - trade press and official releases",
    "boe_series": "Bank of England rates (Bank Rate, SONIA, gilts)",
    "ons_series": "ONS / Nomis economic statistics (inflation, GDP, jobs)",
    "metrics_history": "Our own recorded history of a metric",
}

_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
#: Minimum length of the instructions body (a real skill explains goal, definitions, method).
MIN_INSTRUCTIONS = 80


class SkillDraft(BaseModel):
    """Editable form of a skill: every frontmatter field plus the instructions body."""

    name: str = Field(description="Folder name, lower-case words joined by hyphens, e.g. 'lease-events'.")
    description: str = Field(description="What it researches and WHEN to use it (the only text the router sees).")
    tools: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    sanity_ranges: dict[str, tuple[float, float]] = Field(default_factory=dict)
    preferred_domains: list[str] = Field(default_factory=list)
    model_tier: str = "skill"
    in_brief: bool = True
    order: int = 100
    keywords: list[str] = Field(default_factory=list)
    instructions: str = Field(default="", description="Markdown body: goal, definitions, method, output guidance.")

    @classmethod
    def from_file(cls, path: Path) -> "SkillDraft":
        post = frontmatter.load(path)
        return cls.model_validate({**post.metadata, "instructions": post.content.strip()})

    def frontmatter_dict(self) -> dict:
        """Frontmatter in the conventional field order; empty optional fields are left out."""
        d = self.model_dump(exclude={"instructions"})
        d["sanity_ranges"] = {k: [float(lo), float(hi)] for k, (lo, hi) in self.sanity_ranges.items()}
        optional_empty = {k for k in ("metrics", "sanity_ranges", "preferred_domains", "keywords") if not d[k]}
        return {k: v for k, v in d.items() if k not in optional_empty}

    def to_markdown(self) -> str:
        meta = yaml.safe_dump(self.frontmatter_dict(), sort_keys=False, allow_unicode=True, width=100)
        return f"---\n{meta}---\n\n{self.instructions.strip()}\n"


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

def skills_dir() -> Path:
    return get_settings().skills_dir


def skill_path(name: str) -> Path:
    return skills_dir() / name / "SKILL.md"


def history_dir(name: str) -> Path:
    return skills_dir() / ".history" / name


def trash_dir() -> Path:
    return skills_dir() / ".trash"


def _changed() -> None:
    """Rebuild everything that holds skills, so the next run uses the new files."""
    from cre_monitor.graph.nodes.skill_runner import build_skill_agent
    from cre_monitor.skills.registry import get_registry

    get_registry.cache_clear()
    build_skill_agent.cache_clear()


# --------------------------------------------------------------------------
# Read / validate / save
# --------------------------------------------------------------------------

def load_draft(name: str) -> tuple[SkillDraft, str]:
    """``(draft, version)`` of an existing skill; pass ``version`` back to :func:`save_skill`."""
    path = skill_path(name)
    if not path.exists():
        raise ValueError(f"Unknown skill '{name}'.")
    return SkillDraft.from_file(path), file_version(path)


def _friendly(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "skill"
        out.append(f"{where}: {err['msg'].removeprefix('Value error, ')}")
    return out


def validate_draft(draft: SkillDraft, *, is_new: bool) -> list[str]:
    """Problems that would stop the skill from loading or working, in plain English (empty = OK)."""
    from cre_monitor.skills.registry import SkillMetadata
    from cre_monitor.tools import TOOL_NAMES

    problems: list[str] = []
    if not (3 <= len(draft.name) <= 40 and _NAME_RE.match(draft.name)):
        problems.append("Name: use 3-40 lower-case letters/digits, words joined by hyphens (e.g. 'lease-events').")
    elif is_new and skill_path(draft.name).exists():
        problems.append(f"Name: a skill called '{draft.name}' already exists.")
    try:
        SkillMetadata.model_validate(draft.frontmatter_dict())
    except ValidationError as exc:
        problems += _friendly(exc)
    if unknown := sorted(set(draft.tools) - set(TOOL_NAMES)):
        problems.append(f"Tools: unknown {unknown}. New data sources need a developer (see docs/SKILLS.md).")
    if not draft.tools and draft.name not in PROTECTED_SKILLS:
        problems.append("Tools: choose at least one tool - a skill without tools never runs research.")
    if len(draft.instructions.strip()) < MIN_INSTRUCTIONS:
        problems.append(f"Instructions: too short - explain the goal, definitions and method "
                        f"(at least {MIN_INSTRUCTIONS} characters).")
    if missing := sorted(set(draft.sanity_ranges) - set(draft.metrics)):
        problems.append(f"Plausible ranges: {missing} not in this skill's metrics - add the metric or remove the range.")
    return problems


def save_skill(draft: SkillDraft, *, is_new: bool = False, expected_version: str | None = None) -> Path:
    """Validate and write ``skills/<name>/SKILL.md`` (previous version kept in history).

    Raises:
        ValueError: The draft has problems (message lists them all).
        ConflictError: The file changed since ``expected_version`` was read.
    """
    if problems := validate_draft(draft, is_new=is_new):
        raise ValueError("\n".join(problems))
    path = skill_path(draft.name)
    if not is_new:
        if not path.exists():
            raise ValueError(f"Unknown skill '{draft.name}'.")
        check_version(expected_version, path)
    write_text(path, draft.to_markdown(), history_dir(draft.name))
    _changed()
    logger.info("Skill %s %s via editor", draft.name, "created" if is_new else "saved")
    return path


# --------------------------------------------------------------------------
# Delete / restore / history
# --------------------------------------------------------------------------

def orphaned_metrics(name: str) -> list[str]:
    """Metrics that only skill ``name`` collects (nobody would collect them after deleting it)."""
    from cre_monitor.skills.registry import get_registry

    reg = get_registry()
    if name not in reg:
        return []
    others = {m for s in reg.all() if s.name != name for m in s.meta.metrics}
    return [m for m in reg.get(name).meta.metrics if m not in others]


def delete_skill(name: str) -> Path:
    """Move the skill's folder to ``skills/.trash/<name>__<timestamp>`` (restorable)."""
    if name in PROTECTED_SKILLS:
        raise ValueError(f"'{name}' is used by the summary step and cannot be deleted (you can edit it).")
    # Check the name format before touching the filesystem (no "../" tricks).
    if not _NAME_RE.match(name) or not (skills_dir() / name / "SKILL.md").exists():
        raise ValueError(f"Unknown skill '{name}'.")
    folder = skills_dir() / name
    target = trash_dir() / f"{name}__{datetime.now():%Y%m%d-%H%M%S-%f}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(target))
    _changed()
    logger.info("Skill %s moved to %s", name, target)
    return target


def list_trash() -> list[tuple[str, str, str]]:
    """Deleted skills, newest first: ``(trash_id, skill name, deleted at)``."""
    if not trash_dir().exists():
        return []
    out = []
    for p in sorted(trash_dir().iterdir(), reverse=True):
        if p.is_dir() and "__" in p.name:
            name, stamp = p.name.split("__", 1)
            try:
                when = datetime.strptime(stamp, "%Y%m%d-%H%M%S-%f").strftime("%Y-%m-%d %H:%M")
            except ValueError:
                when = stamp
            out.append((p.name, name, when))
    return sorted(out, key=lambda t: t[0].split("__", 1)[1], reverse=True)


def restore_skill(trash_id: str) -> str:
    """Bring a deleted skill back. Refused if a skill with that name exists again."""
    src = trash_dir() / Path(trash_id).name  # base name only: never leave the trash folder
    if not src.is_dir() or "__" not in src.name:
        raise ValueError(f"Nothing to restore called '{trash_id}'.")
    name = src.name.split("__", 1)[0]
    if (skills_dir() / name).exists():
        raise ValueError(f"A skill called '{name}' exists already; delete or rename it first.")
    shutil.move(str(src), str(skills_dir() / name))
    _changed()
    return name


def versions(name: str) -> list[Path]:
    """Earlier saved versions of a skill, newest first."""
    return list_versions(history_dir(name), "SKILL.md")


def restore_version(name: str, version: Path, *, expected_version: str | None = None) -> None:
    """Make an earlier version current again (the current one goes into history first)."""
    version = history_dir(name) / Path(version).name  # never read outside this skill's history
    if not version.exists():
        raise ValueError("That version no longer exists.")
    draft = SkillDraft.from_file(version)
    save_skill(draft, is_new=False, expected_version=expected_version)


# --------------------------------------------------------------------------
# Metric links across skills (used by Dashboard > Metrics)
# --------------------------------------------------------------------------

def attach_metric(skill: str, key: str, *, sanity_range: tuple[float, float] | None = None,
                  guidance: str = "", domains: list[str] | None = None) -> None:
    """Make ``skill`` collect metric ``key``, optionally with a range, method guidance and sources.

    ``guidance`` is appended to the instructions under "## Additional metrics", so
    the research agent knows where to find and how to record the new figure.
    """
    draft, version = load_draft(skill)
    if key not in draft.metrics:
        draft.metrics.append(key)
    if sanity_range:
        draft.sanity_ranges[key] = (float(sanity_range[0]), float(sanity_range[1]))
    for d in domains or []:
        if d and d not in draft.preferred_domains:
            draft.preferred_domains.append(d)
    if guidance.strip():
        heading = "## Additional metrics"
        if heading not in draft.instructions:
            draft.instructions = draft.instructions.rstrip() + f"\n\n{heading}\n"
        draft.instructions = draft.instructions.rstrip() + f"\n\n### `{key}`\n{guidance.strip()}\n"
    save_skill(draft, expected_version=version)


def detach_metric(key: str) -> list[str]:
    """Remove metric ``key`` from every skill's metrics and ranges. Returns the skills changed.

    The instructions text is left as it is (it may still mention the metric);
    without the key in ``metrics`` the validator flags any figure reported for it.
    """
    changed = []
    for path in sorted(skills_dir().glob("*/SKILL.md")):
        draft, version = load_draft(path.parent.name)
        if key in draft.metrics or key in draft.sanity_ranges:
            draft.metrics = [m for m in draft.metrics if m != key]
            draft.sanity_ranges.pop(key, None)
            save_skill(draft, expected_version=version)
            changed.append(draft.name)
    return changed


# --------------------------------------------------------------------------
# Git status (UI hint: "changed, not yet committed")
# --------------------------------------------------------------------------

def git_changes() -> list[str]:
    """Uncommitted changes under skills/ and catalog/ as ``"M skills/x/SKILL.md"`` lines.

    Empty if git is unavailable or the folders are outside the repo (e.g. in tests).
    """
    s = get_settings()
    paths = [p for p in (s.skills_dir, s.catalog_dir) if p.resolve().is_relative_to(PROJECT_ROOT)]
    if not paths:
        return []
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", *map(str, paths)], cwd=PROJECT_ROOT,
                             capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]
