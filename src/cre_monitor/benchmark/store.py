"""Performance-check run history: one JSON file per run in ``data/benchmarks/``.

Kept so runs can be compared over time (e.g. before/after a skill or prompt
change). ``data/`` is git-ignored; export it with ``cre-monitor export`` if needed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from cre_monitor.config import get_settings


class RunRecord(BaseModel):
    """One performance-check run (figure run or brief judgement)."""

    run_id: str
    kind: Literal["figures", "judge"]
    report: str
    created_at: datetime
    period: str = ""
    hints: bool = False                     # figures: the agent got the report's citations as leads
    skills: list[str] = Field(default_factory=list)
    skipped_skills: list[str] = Field(default_factory=list)
    brief_run_id: str = ""                  # judge: which brief was rated
    cost_usd: float = 0.0                   # ESTIMATE from token usage x price table
    tokens_in: int = 0
    tokens_out: int = 0
    duration_s: float = 0.0
    figure: dict = Field(default_factory=dict)       # FigureScore minus per-entry results
    entries: list[dict] = Field(default_factory=list)  # per-entry results (expected vs found)
    citation: dict = Field(default_factory=dict)     # CitationScore
    citations: list[dict] = Field(default_factory=list)
    readability_brief: dict = Field(default_factory=dict)
    readability_reference: dict = Field(default_factory=dict)
    judgement: dict | None = None
    warnings: list[str] = Field(default_factory=list)


def runs_dir() -> Path:
    return get_settings().data_dir / "benchmarks"


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S-%f")


def save_run(record: RunRecord) -> Path:
    runs_dir().mkdir(parents=True, exist_ok=True)
    path = runs_dir() / f"{record.run_id}.json"
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return path


def list_runs(report: str | None = None, kind: str | None = None) -> list[RunRecord]:
    """Saved runs, newest first (optionally for one report / kind)."""
    if not runs_dir().exists():
        return []
    runs = [RunRecord.model_validate_json(p.read_text(encoding="utf-8")) for p in runs_dir().glob("*.json")]
    runs = [r for r in runs if (report is None or r.report == report) and (kind is None or r.kind == kind)]
    return sorted(runs, key=lambda r: r.created_at, reverse=True)
