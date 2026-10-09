"""Metric and submarket catalogue: the shared vocabulary, stored as data.

The agent records every figure as ``(metric key, submarket, period, source)``.
Both vocabularies used to be Python constants; they now live in two YAML files
so that business users can extend them from the UI without a code change:

* ``catalog/metrics.yaml``    - :class:`MetricDef`: key, plain-English label, unit,
  group, definition, and whether the Dashboard tracks it by default.
* ``catalog/submarkets.yaml`` - :class:`SubmarketDef`: canonical name, aliases
  (mapped to the name by the validator) and kind (office submarket / macro geography).

Who reads it:

=================================  ============================================
Reader                             Uses
=================================  ============================================
``skills.registry``                a skill may only list catalogue metric keys
``graph.nodes.skill_runner``       allowed keys + submarkets in the prompt
``graph.nodes.validator``          unit check, unknown keys, alias mapping
``ui.app`` (Dashboard)             labels, units, definitions, tracked list
=================================  ============================================

Some keys and places are used directly by code (report charts, KPI tiles,
macro data tools); they are listed in :data:`PROTECTED_METRICS` /
:data:`PROTECTED_SUBMARKETS` and cannot be removed.

Edits go through the functions below, which validate, keep a version history
(``catalog/.history/``) and detect concurrent edits (see :mod:`cre_monitor.versioned`).
The files are tracked in git: commit UI changes like any other change.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from cre_monitor.config import get_settings
from cre_monitor.versioned import check_version, file_version, write_text

logger = logging.getLogger(__name__)

#: Metric keys referenced by code - removing them would break a chart, a KPI tile
#: or a data tool. Where: reporting/charts.py (rent/vacancy bars and trends,
#: take-up vs 10y average, pipeline, rates), reporting/render.py (KPI tiles),
#: tools/macro.py (BoE / ONS / Nomis series names).
PROTECTED_METRICS: frozenset[str] = frozenset({
    "prime_rent", "vacancy_rate", "take_up_sqft", "take_up_10y_avg_sqft",
    "pipeline_prelet_sqft", "pipeline_speculative_sqft",
    "bank_rate", "sonia", "gilt_10y_yield", "cpih_yoy", "cpi_yoy",
    "gdp_growth_qoq", "unemployment_rate", "london_employment_rate",
})
#: Places referenced by code (KPI tiles, market-wide charts, macro series).
PROTECTED_SUBMARKETS: frozenset[str] = frozenset({"Central London", "UK", "London"})

#: Display order of metric groups (unknown groups are listed after these).
GROUP_ORDER = ["Rents", "Vacancy & availability", "Leasing", "Supply pipeline", "Investment",
               "Occupier demand", "Macro"]

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,59}$")

_METRICS_HEADER = """# Metric catalogue: every metric the agent may record, with its unit and meaning.
#
# Edited by the UI (Dashboard > Manage metrics) or by hand. Read by:
#   * the skills (allowed metric keys in each SKILL.md `metrics:` list),
#   * the validator (unit check, unknown-key warning),
#   * the research prompt (list of allowed keys),
#   * the Dashboard (labels, units, definitions; `tracked: true` = shown by default).
# Keys used directly by code (report charts, KPI tiles, macro tools) are protected
# in cre_monitor/catalog.py and cannot be removed from the UI.
# See docs/DATA_MODEL.md "Metric catalogue".
"""

_SUBMARKETS_HEADER = """# Submarket catalogue: the canonical place names figures are recorded against.
#
# Edited by the UI (Dashboard > Manage submarkets) or by hand. Skills are told to
# normalise broker naming to these names; the validator also maps `aliases`
# (case-insensitive) to the canonical name, so "Docklands" is stored as "Canary Wharf".
# kind: submarket = office submarket; macro = geography for economic series (UK, London).
# Central London, UK and London are used by code (KPI tiles, macro charts) and are protected.
# See docs/DATA_MODEL.md "Submarket catalogue".
"""


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

class MetricDef(BaseModel):
    """One metric the agent may record."""

    key: str = Field(description="snake_case identifier stored with every figure, e.g. 'prime_rent'.")
    label: str = Field(min_length=2, description="Plain-English name shown in the UI, e.g. 'Prime rent'.")
    unit: str = Field(min_length=1, description="Expected unit, e.g. 'GBP psf pa', '%', 'sq ft'.")
    group: str = Field(default="Other", description="Topic group for the Dashboard, e.g. 'Rents'.")
    definition: str = Field(default="", description="One or two sentences: what exactly is measured.")
    tracked: bool = Field(default=False, description="Shown on the Dashboard by default.")
    added_at: str = Field(default="", description="When it was added through the UI (ISO time); empty = original.")

    @field_validator("key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError("key must be snake_case: lower-case letters, digits and _, 3-60 characters, "
                             "starting with a letter (e.g. 'average_lease_length')")
        return v

    @property
    def protected(self) -> bool:
        return self.key in PROTECTED_METRICS


class SubmarketDef(BaseModel):
    """One canonical place name."""

    name: str = Field(min_length=2, max_length=60)
    kind: Literal["submarket", "macro"] = "submarket"
    aliases: list[str] = Field(default_factory=list, description="Other spellings mapped to this name.")
    description: str = ""

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("aliases")
    @classmethod
    def _clean_aliases(cls, v: list[str]) -> list[str]:
        return [a.strip() for a in v if a and a.strip()]

    @property
    def protected(self) -> bool:
        return self.name in PROTECTED_SUBMARKETS


class Catalog(BaseModel):
    """Both vocabularies, as loaded from disk."""

    metrics: list[MetricDef]
    submarkets: list[SubmarketDef]
    #: Content hash of both files when loaded; pass back to edits to detect conflicts.
    version: str = ""

    # -- metrics ------------------------------------------------------------
    def metric(self, key: str) -> MetricDef | None:
        return next((m for m in self.metrics if m.key == key), None)

    def units(self) -> dict[str, str]:
        """``{key: unit}`` for every metric (what the code used to call METRIC_KEYS)."""
        return {m.key: m.unit for m in self.metrics}

    def label(self, key: str) -> str:
        m = self.metric(key)
        return m.label if m else key.replace("_", " ").capitalize()

    def tracked(self) -> list[MetricDef]:
        return [m for m in self.metrics if m.tracked]

    def groups(self) -> list[str]:
        present = {m.group for m in self.metrics}
        return [g for g in GROUP_ORDER if g in present] + sorted(present - set(GROUP_ORDER))

    # -- submarkets ---------------------------------------------------------
    def submarket_names(self) -> list[str]:
        """Office submarkets (incl. Central London), in catalogue order."""
        return [s.name for s in self.submarkets if s.kind == "submarket"]

    def macro_geographies(self) -> list[str]:
        return [s.name for s in self.submarkets if s.kind == "macro"]

    def all_places(self) -> list[str]:
        return [s.name for s in self.submarkets]

    def canonical_place(self, name: str) -> str | None:
        """Canonical name for ``name`` or one of its aliases (case-insensitive), else None."""
        wanted = name.strip().casefold()
        for s in self.submarkets:
            if wanted == s.name.casefold() or wanted in (a.casefold() for a in s.aliases):
                return s.name
        return None


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def catalog_dir() -> Path:
    return get_settings().catalog_dir


def metrics_path() -> Path:
    return catalog_dir() / "metrics.yaml"


def submarkets_path() -> Path:
    return catalog_dir() / "submarkets.yaml"


def history_dir() -> Path:
    """Version history of UI edits (git-ignored)."""
    return catalog_dir() / ".history"


def _read_yaml(path: Path, field: str) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Catalogue file missing: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get(field) or []


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """The catalogue, cached per process. Edits below clear the cache."""
    return Catalog(
        metrics=[MetricDef.model_validate(m) for m in _read_yaml(metrics_path(), "metrics")],
        submarkets=[SubmarketDef.model_validate(s) for s in _read_yaml(submarkets_path(), "submarkets")],
        version=file_version(metrics_path(), submarkets_path()),
    )


def metric_units() -> dict[str, str]:
    """Shortcut: ``{metric key: unit}``."""
    return get_catalog().units()


def _changed() -> None:
    """Drop caches that embed the vocabulary, so the next run uses the new catalogue."""
    get_catalog.cache_clear()
    # Skill agents bake the allowed keys / submarkets into their system prompt.
    from cre_monitor.graph.nodes.skill_runner import build_skill_agent
    from cre_monitor.skills.registry import get_registry

    build_skill_agent.cache_clear()
    get_registry.cache_clear()  # skills are validated against the metric keys


def _dump(header: str, field: str, items: list[BaseModel]) -> str:
    # Defaults are omitted to keep the file short; fields keep model order (key/name first).
    rows = [i.model_dump(exclude_defaults=True) for i in items]
    return header + yaml.safe_dump({field: rows}, sort_keys=False, allow_unicode=True, width=120)


def _save_metrics(metrics: list[MetricDef]) -> None:
    write_text(metrics_path(), _dump(_METRICS_HEADER, "metrics", metrics), history_dir())
    _changed()


def _save_submarkets(submarkets: list[SubmarketDef]) -> None:
    write_text(submarkets_path(), _dump(_SUBMARKETS_HEADER, "submarkets", submarkets), history_dir())
    _changed()


def _check(expected_version: str | None) -> Catalog:
    check_version(expected_version, metrics_path(), submarkets_path())
    get_catalog.cache_clear()  # always edit the latest content on disk
    return get_catalog()


# --------------------------------------------------------------------------
# Metric edits
# --------------------------------------------------------------------------

def suggest_key(label: str) -> str:
    """snake_case key from a label, e.g. 'Average lease length (years)' -> 'average_lease_length_years'."""
    key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if key and not key[0].isalpha():
        key = "m_" + key
    return key[:60]


def add_metric(metric: MetricDef, *, expected_version: str | None = None) -> MetricDef:
    """Add a metric (tracked or not). Raises ValueError on a duplicate key or label."""
    cat = _check(expected_version)
    if cat.metric(metric.key):
        raise ValueError(f"A metric with key '{metric.key}' already exists ({cat.label(metric.key)}).")
    clash = next((m for m in cat.metrics if m.label.casefold() == metric.label.casefold()), None)
    if clash:
        raise ValueError(f"A metric called '{metric.label}' already exists (key '{clash.key}').")
    metric = metric.model_copy(update={"added_at": metric.added_at or datetime.now().isoformat(timespec="seconds")})
    _save_metrics([*cat.metrics, metric])
    logger.info("Catalogue: metric %s added", metric.key)
    return metric


def set_tracked(key: str, tracked: bool, *, expected_version: str | None = None) -> None:
    """Show (True) or hide (False) a metric on the Dashboard. History is never touched."""
    cat = _check(expected_version)
    if not cat.metric(key):
        raise ValueError(f"Unknown metric '{key}'.")
    _save_metrics([m.model_copy(update={"tracked": tracked}) if m.key == key else m for m in cat.metrics])


def update_metric(key: str, /, *, expected_version: str | None = None, **fields) -> MetricDef:
    """Change a metric's label, unit, group or definition (the key itself never changes)."""
    cat = _check(expected_version)
    old = cat.metric(key)
    if old is None:
        raise ValueError(f"Unknown metric '{key}'.")
    allowed = {"label", "unit", "group", "definition", "tracked"}
    if bad := set(fields) - allowed:
        raise ValueError(f"Cannot change {sorted(bad)}; editable fields: {sorted(allowed)}")
    new = MetricDef.model_validate(old.model_dump() | fields)
    _save_metrics([new if m.key == key else m for m in cat.metrics])
    return new


def skills_using_metric(key: str) -> list[str]:
    """Names of skills that list ``key`` in ``metrics`` or ``sanity_ranges``."""
    from cre_monitor.skills.registry import get_registry

    return [s.name for s in get_registry().all() if key in s.meta.metrics or key in s.meta.sanity_ranges]


def remove_metric(key: str, *, expected_version: str | None = None) -> None:
    """Delete a metric from the catalogue. Its recorded history stays in the database.

    Raises:
        ValueError: The metric is protected, unknown, or still listed by a skill
            (detach it first with ``skills.editor.detach_metric``).
    """
    cat = _check(expected_version)
    if cat.metric(key) is None:
        raise ValueError(f"Unknown metric '{key}'.")
    if key in PROTECTED_METRICS:
        raise ValueError(f"'{key}' is used by the report charts or data tools and cannot be removed. "
                         "You can stop tracking it on the Dashboard instead.")
    if users := skills_using_metric(key):
        raise ValueError(f"'{key}' is still collected by skill(s) {', '.join(users)}; remove it from them first.")
    _save_metrics([m for m in cat.metrics if m.key != key])
    logger.info("Catalogue: metric %s removed", key)


# --------------------------------------------------------------------------
# Submarket edits
# --------------------------------------------------------------------------

def add_submarket(submarket: SubmarketDef, *, expected_version: str | None = None) -> SubmarketDef:
    """Add a place. Its name and aliases must not clash with any existing name or alias.

    If the new name is currently an *alias* of another submarket (e.g. adding
    "Mayfair" while it maps to "West End"), the error says so: remove the alias
    from that submarket first, otherwise figures would be filed in two places.
    """
    cat = _check(expected_version)
    for spelling in [submarket.name, *submarket.aliases]:
        if (owner := cat.canonical_place(spelling)) is not None:
            what = "name" if owner.casefold() == spelling.casefold() else f"an alias of '{owner}'"
            raise ValueError(f"'{spelling}' is already {what}. Choose another name, or edit '{owner}' first.")
    _save_submarkets([*cat.submarkets, submarket])
    logger.info("Catalogue: submarket %s added", submarket.name)
    return submarket


def update_submarket(name: str, *, aliases: list[str] | None = None, description: str | None = None,
                     expected_version: str | None = None) -> SubmarketDef:
    """Change a place's aliases or description (renaming is not supported: history is keyed by name)."""
    cat = _check(expected_version)
    old = next((s for s in cat.submarkets if s.name == name), None)
    if old is None:
        raise ValueError(f"Unknown submarket '{name}'.")
    new = old.model_copy(update={k: v for k, v in {"aliases": aliases, "description": description}.items()
                                 if v is not None})
    new = SubmarketDef.model_validate(new.model_dump())
    others = [s for s in cat.submarkets if s.name != name]
    for alias in new.aliases:
        owner = Catalog(metrics=[], submarkets=others).canonical_place(alias)
        if owner is not None:
            raise ValueError(f"Alias '{alias}' already belongs to '{owner}'.")
    _save_submarkets([new if s.name == name else s for s in cat.submarkets])
    return new


def remove_submarket(name: str, *, expected_version: str | None = None) -> None:
    """Delete a place. Recorded figures for it stay in the database (and on the Dashboard)."""
    cat = _check(expected_version)
    if name in PROTECTED_SUBMARKETS:
        raise ValueError(f"'{name}' is used by the report and macro charts and cannot be removed.")
    if not any(s.name == name for s in cat.submarkets):
        raise ValueError(f"Unknown submarket '{name}'.")
    _save_submarkets([s for s in cat.submarkets if s.name != name])
    logger.info("Catalogue: submarket %s removed", name)
