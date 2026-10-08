"""Export the app's data as one portable zip, for business users, analysis and backup.

Contents of ``exports/cre-export_<YYYYMMDD-HHMMSS>.zip``::

    cre-export_<stamp>/
      README.md                     what each file is (for whoever receives the zip)
      manifest.json                 export time, app version, filters, counts
      cre-export.xlsx               Excel workbook: Metrics, Briefs, Conversations sheets
      metrics.csv                   full metric history, one row per figure (with sources)
      briefs/<date>/...             each brief's HTML, Markdown, findings JSON and charts
      briefs_index.csv              brief id, created, file paths inside the export
      conversations/<title>_<id>.md readable transcript per conversation
      conversations.json            the same in structured form (incl. findings, errors)
      logs/*.log                    only with include_logs=True (for engineers)

Design notes:

* Data is read **through the store classes** (``MetricsStore``,
  ``ConversationStore``, ``list_briefs``), never the SQLite files directly, so
  the export keeps working if the storage backend changes (e.g. to Postgres).
* LangGraph checkpoints (agent memory) are not exported: an internal format with
  no value outside the app. Conversations are exported from the index instead.
* No secrets are included: API keys live only in settings/env, never in the data.
* ``since`` filters by date: metrics by run date (the seeded history is only
  included in unfiltered exports), briefs by creation date, conversations by
  last activity (all turns of an included conversation are exported).
"""

from __future__ import annotations

import csv
import json
import logging
import re
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from cre_monitor import __version__
from cre_monitor.config import get_settings

logger = logging.getLogger(__name__)

#: Column order for metrics.csv / the Metrics sheet (most useful first).
METRIC_COLUMNS = ["key", "submarket", "period", "value", "unit", "source", "url", "as_of", "note",
                  "skill", "run_id", "run_at"]
#: Excel's hard limit per cell is 32,767 characters.
EXCEL_CELL_MAX = 32_000

README = """# London CRE Market Monitor - data export

Exported {exported_at} (app version {version}){filter_note}.

| File | Contents |
|---|---|
| `cre-export.xlsx` | Excel workbook with three sheets: **Metrics** (every recorded figure), **Briefs** (index), **Conversations** (one row per question/answer) |
| `metrics.csv` | Full metric history, one row per figure: metric key, submarket, period, value, unit, source, source URL, publication date, notes, and the run it came from |
| `briefs/` | Each market brief as HTML (open in a browser; charts are interactive), Markdown and the structured `findings_<id>.json` |
| `briefs_index.csv` | List of the exported briefs with their files |
| `conversations/` | One readable Markdown transcript per chat conversation |
| `conversations.json` | Conversations in structured form, including research findings, referenced conversations and error references |
| `manifest.json` | Export metadata and counts |
{logs_row}
**Please note:** figures come from the cited third-party sources (brokers, Bank of England,
ONS, news). Brokers define metrics differently, so compare like with like. This export is
for internal use; check licensing before sharing broker-derived figures externally.
"""


class ExportResult(BaseModel):
    """What was exported, and where."""

    path: Path
    counts: dict[str, int]


def _slug(text: str, max_len: int = 50) -> str:
    """File-system-safe name from a title."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug[:max_len].rstrip("-") or "conversation"


def _export_metrics(base: Path, since: date | None) -> pd.DataFrame:
    from cre_monitor.store import get_store

    df = get_store().frame()
    if df.empty:
        df = pd.DataFrame(columns=METRIC_COLUMNS)
    if since is not None:
        df = df[pd.to_datetime(df["run_at"]).dt.date >= since]
    df = df[METRIC_COLUMNS].sort_values(["key", "submarket", "period", "run_at"]).reset_index(drop=True)
    # utf-8-sig adds a BOM so Excel opens accented text and "£" correctly.
    df.to_csv(base / "metrics.csv", index=False, encoding="utf-8-sig")
    return df


def _export_briefs(base: Path, since: date | None) -> list[dict]:
    from cre_monitor.reporting.briefs import list_briefs

    rows = []
    for brief in list_briefs():
        if since is not None and brief.created_at.date() < since:
            continue
        dest = base / "briefs" / brief.date_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for path in brief.files():
            target = dest / path.relative_to(brief.date_dir)
            if path.is_dir():
                shutil.copytree(path, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        # Briefs from before per-run chart folders reference shared charts/*.png.
        for png in (brief.date_dir / "charts").glob("*.png"):
            (dest / "charts").mkdir(exist_ok=True)
            shutil.copy2(png, dest / "charts" / png.name)
        rel = f"briefs/{brief.date_dir.name}"
        rows.append({
            "brief_id": brief.run_id,
            "created_at": brief.created_at.isoformat(timespec="seconds"),
            "html": f"{rel}/brief_{brief.run_id}.html",
            "markdown": f"{rel}/brief_{brief.run_id}.md",
            "findings_json": f"{rel}/findings_{brief.run_id}.json",
        })
    with (base / "briefs_index.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=["brief_id", "created_at", "html", "markdown", "findings_json"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _transcript(conv, turns, titles: dict[str, str]) -> str:
    """Readable Markdown transcript of one conversation."""
    lines = [
        f"# {conv.title}",
        "",
        f"_Conversation `{conv.thread_id}` · started {conv.created_at:%Y-%m-%d %H:%M} · "
        f"last active {conv.updated_at:%Y-%m-%d %H:%M} · {len(turns)} question(s)_",
    ]
    for t in turns:
        lines += ["", f"## Q{t.idx + 1} · {t.created_at:%Y-%m-%d %H:%M}", "", f"**Question:** {t.question}", "",
                  "**Answer:**", "", t.answer or "_(no answer)_"]
        meta = []
        if t.skills:
            meta.append(f"Skills used: {', '.join(t.skills)}")
        if t.refs:
            meta.append("Referenced: " + "; ".join(f"{titles.get(r, '(deleted conversation)')} (`{r}`)" for r in t.refs))
        if t.incident:
            meta.append(f"⚠ Problem: {t.incident.category.title} - reference `{t.incident.id}`")
        if meta:
            lines += [""] + [f"> {m}" for m in meta]
    return "\n".join(lines) + "\n"


def _export_conversations(base: Path, since: date | None) -> tuple[list[dict], list[dict]]:
    """Write transcripts + conversations.json. Returns (json conversations, flat turn rows)."""
    from cre_monitor.store import get_conversation_store

    store = get_conversation_store()
    every = store.list(limit=1_000_000)
    titles = {c.thread_id: c.title for c in every}
    out_dir = base / "conversations"
    out_dir.mkdir()
    conversations, turn_rows = [], []
    for conv in every:
        if since is not None and conv.updated_at.date() < since:
            continue
        turns = store.turns(conv.thread_id)
        (out_dir / f"{_slug(conv.title)}_{conv.thread_id}.md").write_text(
            _transcript(conv, turns, titles), encoding="utf-8")
        conversations.append({
            "thread_id": conv.thread_id, "title": conv.title,
            "created_at": conv.created_at.isoformat(), "updated_at": conv.updated_at.isoformat(),
            "turns": [
                {
                    "idx": t.idx, "created_at": t.created_at.isoformat(), "question": t.question,
                    "answer": t.answer, "skills": t.skills, "reasoning": t.reasoning, "references": t.refs,
                    "incident": t.incident.model_dump(mode="json") if t.incident else None,
                    "data_quality_issues": [i.model_dump(mode="json") for i in t.issues],
                    "findings": [f.model_dump(mode="json") for f in t.findings],
                }
                for t in turns
            ],
        })
        for t in turns:
            turn_rows.append({
                "thread_id": conv.thread_id, "title": conv.title, "question_no": t.idx + 1,
                "asked_at": t.created_at.isoformat(timespec="seconds"), "question": t.question,
                "answer": (t.answer or "")[:EXCEL_CELL_MAX], "skills": ", ".join(t.skills),
                "references": ", ".join(t.refs), "error_reference": t.incident.id if t.incident else "",
            })
    (base / "conversations.json").write_text(json.dumps(conversations, indent=2, ensure_ascii=False), encoding="utf-8")
    return conversations, turn_rows


def export_data(
    out_dir: Path | None = None,
    since: date | None = None,
    include_logs: bool = False,
    now: datetime | None = None,
) -> ExportResult:
    """Build the export zip.

    Args:
        out_dir: Where to write the zip (default: ``settings.exports_dir``).
        since: Only include data from this date on (see module docstring).
        include_logs: Also include ``data/logs/*.log`` (for engineers).
        now: Timestamp override (tests).

    Returns:
        The zip path and per-section counts.
    """
    s = get_settings()
    now = now or datetime.now()
    out_dir = out_dir or s.exports_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"cre-export_{now:%Y%m%d-%H%M%S}"

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / name
        base.mkdir()
        metrics = _export_metrics(base, since)
        briefs = _export_briefs(base, since)
        conversations, turn_rows = _export_conversations(base, since)

        logs = []
        if include_logs:
            (base / "logs").mkdir()
            for log in (s.data_dir / "logs").glob("*.log"):
                shutil.copy2(log, base / "logs" / log.name)
                logs.append(log.name)

        with pd.ExcelWriter(base / "cre-export.xlsx", engine="openpyxl") as xl:
            metrics.to_excel(xl, sheet_name="Metrics", index=False)
            pd.DataFrame(briefs, columns=["brief_id", "created_at", "html", "markdown", "findings_json"]).to_excel(
                xl, sheet_name="Briefs", index=False)
            pd.DataFrame(turn_rows, columns=["thread_id", "title", "question_no", "asked_at", "question", "answer",
                                             "skills", "references", "error_reference"]).to_excel(
                xl, sheet_name="Conversations", index=False)

        counts = {
            "metric_rows": len(metrics), "briefs": len(briefs), "conversations": len(conversations),
            "turns": len(turn_rows), "log_files": len(logs),
        }
        (base / "manifest.json").write_text(json.dumps({
            "exported_at": now.isoformat(timespec="seconds"), "app_version": __version__,
            "filters": {"since": since.isoformat() if since else None, "include_logs": include_logs},
            "counts": counts,
        }, indent=2), encoding="utf-8")
        (base / "README.md").write_text(README.format(
            exported_at=f"{now:%d %B %Y %H:%M}", version=__version__,
            filter_note=f", data since {since:%d %B %Y}" if since else "",
            logs_row="| `logs/` | Application logs, for engineers (error references `ERR-...` are searchable here) |\n"
            if include_logs else "",
        ), encoding="utf-8")

        zip_path = Path(shutil.make_archive(str(out_dir / name), "zip", root_dir=tmp, base_dir=name))
    logger.info("Exported data to %s %s", zip_path, counts)
    return ExportResult(path=zip_path, counts=counts)
