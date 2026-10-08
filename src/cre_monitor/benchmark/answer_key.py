"""Answer keys: the figures a reference report states, as the "right answers" for a performance check.

Built by AI, moderated by an analyst:

1. :func:`build_key` - one structured call (skill tier) reads the report text and
   lists every figure it states that maps onto the metric catalogue: key,
   submarket, **period**, value, unit, publisher, citation. It also lists the
   report's 5-8 key themes (used by the brief judge).
2. :func:`compute_signals` - quantitative checks the analyst moderates with:

   ================  =========================================================
   in_document       the value really appears in the report text (any format)
   confidence        the AI's own confidence (0-1)
   catalogue_match   known metric key, matching unit, known submarket
   period_ok         the period label parses ("2026-Q1", "2026-H1", ...)
   ================  =========================================================

   An entry is **safe** when all four pass (confidence >= 0.8);
   :meth:`AnswerKey.accept_safe` accepts those in one click.
3. Only ``accepted`` entries are scored. Keys are saved as JSON in
   ``style/benchmark/<report file>.json`` (numbers, links and short themes only -
   no copied report text), with version history, so the team can commit and
   share one moderated key.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from cre_monitor.benchmark.scoring import value_in_text
from cre_monitor.catalog import get_catalog
from cre_monitor.config import get_settings
from cre_monitor.periods import parse_period
from cre_monitor.versioned import write_text

logger = logging.getLogger(__name__)

#: Confidence needed (with all other signals passing) for "Accept all safe".
SAFE_CONFIDENCE = 0.8
#: Characters of report text sent to the model (~12k tokens).
MAX_REPORT_CHARS = 45_000

Status = Literal["pending", "accepted", "rejected"]


class KeyEntry(BaseModel):
    """One figure stated in a reference report."""

    id: str = ""
    key: str
    submarket: str
    period: str
    value: float
    unit: str
    source: str = Field(description="Publisher of the figure (the report's publisher unless it cites another).")
    citation: str = Field(default="", description="URL or reference the report gives for the figure.")
    confidence: float = Field(default=0.5, ge=0, le=1)
    note: str = ""
    status: Status = "pending"
    # Moderation signals (computed by compute_signals, never trusted from the model).
    in_document: bool = False
    catalogue_match: bool = False
    period_ok: bool = False

    @property
    def safe(self) -> bool:
        return self.in_document and self.catalogue_match and self.period_ok and self.confidence >= SAFE_CONFIDENCE

    def make_id(self) -> str:
        raw = f"{self.key}|{self.submarket}|{self.period}|{self.source}".casefold()
        return hashlib.sha1(raw.encode()).hexdigest()[:8]


class AnswerKey(BaseModel):
    """All figures and themes extracted from one reference report."""

    report: str = Field(description="File name in style/reports/.")
    title: str = ""
    publisher: str = ""
    period: str = Field(default="", description="Main period the report covers, e.g. 2026-Q1.")
    built_at: str = ""
    themes: list[str] = Field(default_factory=list)
    entries: list[KeyEntry] = Field(default_factory=list)

    def accepted(self) -> list[KeyEntry]:
        return [e for e in self.entries if e.status == "accepted"]

    def stats(self) -> dict[str, int]:
        return {"total": len(self.entries), "accepted": len(self.accepted()),
                "rejected": sum(e.status == "rejected" for e in self.entries),
                "pending": sum(e.status == "pending" for e in self.entries),
                "safe": sum(e.safe for e in self.entries),
                "in_document": sum(e.in_document for e in self.entries)}

    def accept_safe(self) -> int:
        """Accept every pending entry whose signals all pass. Returns how many."""
        n = 0
        for e in self.entries:
            if e.status == "pending" and e.safe:
                e.status = "accepted"
                n += 1
        return n


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------

def compute_signals(key: AnswerKey, report_text: str | None) -> AnswerKey:
    """(Re)compute every entry's moderation signals and normalise names. Returns the key.

    ``report_text`` None (report file missing) leaves ``in_document`` as it was.
    """
    cat = get_catalog()
    units = cat.units()
    for e in key.entries:
        e.submarket = cat.canonical_place(e.submarket) or e.submarket
        e.catalogue_match = e.key in units and e.unit == units[e.key] and e.submarket in cat.all_places()
        e.period_ok = parse_period(e.period) is not None
        if report_text is not None:
            e.in_document = value_in_text(e.value, report_text)
        e.id = e.id or e.make_id()
    return key


def apply_edits(key: AnswerKey, edits: list[dict], report_text_: str | None) -> int:
    """Apply analyst moderation (status / value / period / submarket per entry id); recompute signals.

    Args:
        edits: ``[{"id": ..., "status": ..., "value": ..., "period": ..., "submarket": ...}, ...]``;
            missing fields are left unchanged.
        report_text_: The report text, to re-check ``in_document`` for edited values.

    Returns:
        Number of entries changed.
    """
    by_id = {e.id: e for e in key.entries}
    changed = 0
    for row in edits:
        e = by_id.get(row.get("id"))
        if e is None:
            continue
        before = e.model_dump()
        if row.get("status") not in (None, "pending", "accepted", "rejected"):
            raise ValueError(f"Unknown status {row['status']!r} (use pending, accepted or rejected).")
        for field in ("status", "value", "period", "submarket"):
            if row.get(field) is not None and row[field] == row[field]:  # skip None / NaN
                setattr(e, field, float(row[field]) if field == "value" else row[field])
        changed += e.model_dump() != before
    compute_signals(key, report_text_)
    return changed


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def keys_dir() -> Path:
    return get_settings().style_dir / "benchmark"


def key_path(report: str) -> Path:
    return keys_dir() / f"{Path(report).name}.json"


def load_key(report: str) -> AnswerKey | None:
    path = key_path(report)
    if not path.exists():
        return None
    return AnswerKey.model_validate_json(path.read_text(encoding="utf-8"))


def save_key(key: AnswerKey) -> Path:
    """Write the key (previous version kept in style/benchmark/.history/)."""
    path = key_path(key.report)
    write_text(path, key.model_dump_json(indent=2), keys_dir() / ".history")
    return path


def report_text(report: str) -> str | None:
    """Plain text of a library report, or None if the file is gone."""
    from cre_monitor.style.profile import examples_dir, read_example

    path = examples_dir() / Path(report).name
    return read_example(path) if path.exists() else None


# --------------------------------------------------------------------------
# AI extraction
# --------------------------------------------------------------------------

class _EntryOut(BaseModel):
    key: str
    submarket: str
    period: str
    value: float
    unit: str
    source: str
    citation: str = ""
    confidence: float = Field(ge=0, le=1)
    note: str = ""


class _KeyOut(BaseModel):
    title: str
    publisher: str
    period: str = Field(description="Main period covered, e.g. 2026-Q1.")
    themes: list[str] = Field(description="5-8 key messages of the report, one short sentence each, own words.")
    entries: list[_EntryOut]


KEY_PROMPT = """You build an answer key from a London office market report: every hard figure it states that maps
onto the METRIC CATALOGUE below. This key is later used to test whether a research agent can find the same figures.

Rules:
- Only figures the report actually states. Never compute or infer figures.
- key/unit: exactly as in the catalogue (convert '2.5m sq ft' to 2500000 with unit 'sq ft'; percentages as numbers).
- submarket: one of the SUBMARKETS (use 'Central London' for market-wide figures).
- period: the period the figure describes, formatted 2026-Q1, 2026-H1, 2026-08 or 2026.
- source: the publisher of the figure (the report's publisher, unless the report attributes it to someone else);
  citation: the URL or reference the report gives, if any.
- confidence: how sure you are that key, submarket, period and value are all right (lower it for ambiguous wording,
  e.g. availability vs vacancy, or take-up incl./excl. pre-lets).
- themes: the report's main messages in your own words (no quotes).
"""


def build_key(report: str) -> AnswerKey:
    """Extract an answer key from a library report with Claude (live mode). Not saved yet.

    Raises:
        NeedsLiveMode: demo mode.
        ValueError: report missing or has no readable text.
    """
    from cre_monitor.authoring import NeedsLiveMode

    if get_settings().cre_demo_mode:
        raise NeedsLiveMode("Building an answer key needs Claude (live mode).")
    text = report_text(report)
    if not text or not text.strip():
        raise ValueError(f"'{report}' is missing or has no readable text (scanned PDF?).")
    from cre_monitor.llm import STRUCTURED, get_llm  # read at call time so tests can patch it

    cat = get_catalog()
    catalogue = "\n".join(f"- {m.key} ({m.unit}): {m.label}. {m.definition}" for m in cat.metrics)
    out: _KeyOut = get_llm("skill").with_structured_output(_KeyOut, **STRUCTURED).invoke([
        SystemMessage(f"{KEY_PROMPT}\nMETRIC CATALOGUE:\n{catalogue}\n\nSUBMARKETS: {', '.join(cat.all_places())}"),
        HumanMessage(f"REPORT ({report}):\n{text[:MAX_REPORT_CHARS]}"),
    ])
    key = AnswerKey(report=Path(report).name, title=out.title, publisher=out.publisher, period=out.period,
                    built_at=datetime.now().isoformat(timespec="seconds"), themes=out.themes,
                    entries=[KeyEntry(**e.model_dump()) for e in out.entries])
    compute_signals(key, text)
    # Drop exact duplicates (same id) the model may list twice.
    seen, unique = set(), []
    for e in key.entries:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)
    key.entries = unique
    logger.info("Answer key for %s: %d entries (%d safe)", report, len(unique), key.stats()["safe"])
    return key
