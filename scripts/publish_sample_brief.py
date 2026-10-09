"""Publish a redacted copy of a brief - e.g. a full live run - as a sample in the repo.

Briefs (``reports/``) and data (``data/``) are git-ignored. To share one with the team in git,
content from **licence-restricted sources** must come out first: Knight Frank's terms prohibit
reproduction and use on AI platforms, and CoStar data is licensed. This script re-renders the
brief from its findings JSON with that content removed.

Usage (from the repo root, in the project environment)::

    python scripts/publish_sample_brief.py reports/<date>/findings_<run_id>.json examples/sample-brief

Redaction rules - deliberately conservative (may remove more than strictly necessary):

* figures, citations and "what changed" comparisons whose source / publisher / URL / note names
  a restricted source are dropped;
* every sentence or bullet (topic text, signals, executive summary, validator notes) that names a
  restricted source **or quotes the value of a removed figure** is dropped; a removed headline or
  summary is replaced by a visible "(... removed ...)" note;
* charts are rebuilt from the cleaned findings and from the metric history with restricted rows,
  and rows recorded after the run, removed (on a temporary copy - ``data/`` is never changed).

The research itself is not repeated: no LLM is called. The output's header shows the original run
time. Finally the script checks that no restricted name remains in the published text files.
Review the result before committing - e.g. figures restated in your own words may still need care.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

#: Sources whose content may not be published (case-insensitive).
RESTRICTED = re.compile(r"knight\s*frank|knightfrank|costar|remit\s+consulting", re.I)
SQL_RESTRICTED = ("%knight%frank%", "%knightfrank%", "%costar%", "%remit consulting%")


def _clean_history(src_db: Path, tmp_data: Path, run_id: str) -> None:
    """Copy the metrics DB; drop restricted rows and rows recorded after the run."""
    tmp_data.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_db, tmp_data / "metrics.sqlite")
    run_at = datetime.strptime(run_id[:15], "%Y%m%dT%H%M%S")
    with closing(sqlite3.connect(tmp_data / "metrics.sqlite")) as c:
        before = c.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        # Keep this run's rows and everything recorded before it (run_at is ISO text).
        c.execute("DELETE FROM metrics WHERE run_id != ? AND substr(run_at, 1, 19) > ?",
                  (run_id, run_at.isoformat(timespec="seconds")))
        for col in ("source", "url", "note"):
            clause = " OR ".join(f"lower(coalesce({col}, '')) LIKE ?" for _ in SQL_RESTRICTED)
            c.execute(f"DELETE FROM metrics WHERE {clause}", SQL_RESTRICTED)
        c.commit()
        after = c.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    print(f"Chart history: {before} -> {after} rows")


def main(findings_json: Path, out_dir: Path, metrics_db: Path) -> int:
    data = json.loads(findings_json.read_text(encoding="utf-8"))
    run_id = data["run_id"]
    tmp_data = Path(tempfile.mkdtemp(prefix="cre-sample-"))
    _clean_history(metrics_db, tmp_data, run_id)
    # The research was live; rendering makes no LLM call (no style editor, no synthesis).
    os.environ.update(DATA_DIR=str(tmp_data), CRE_DEMO_MODE="0", REPORT_STYLE="0")

    from cre_monitor.benchmark.scoring import value_in_text
    from cre_monitor.reporting.render import write_report
    from cre_monitor.schemas import ExecutiveSynthesis, MetricDelta, SkillFinding, ValidationIssue

    counts = dict.fromkeys(("figures", "citations", "sentences", "bullets", "signals", "changes", "notes"), 0)

    def restricted(*texts) -> bool:
        return any(RESTRICTED.search(t or "") for t in texts)

    removed_values = [float(m["value"]) for f in data["findings"] for m in f.get("metrics", [])
                      if restricted(m.get("source"), m.get("url"), m.get("note"))]

    def ok(text: str) -> bool:
        return not restricted(text) and not any(value_in_text(v, text) for v in removed_values)

    def prose(text: str, what: str) -> str:
        parts = re.split(r"(?<=[.!?])\s+", text or "")
        kept = [p for p in parts if ok(p)]
        counts["sentences"] += len(parts) - len(kept)
        return " ".join(kept) if kept else f"({what} removed: it quoted licence-restricted sources.)"

    def bullets(items: list[str]) -> list[str]:
        kept = [i for i in items if ok(i)]
        counts["bullets"] += len(items) - len(kept)
        return kept

    def signals(items: list[dict]) -> list[dict]:
        kept = [s for s in items if ok(s.get("title", "")) and ok(s.get("rationale", ""))]
        counts["signals"] += len(items) - len(kept)
        return kept

    findings = []
    for f in data["findings"]:
        metrics = [m for m in f.get("metrics", []) if not restricted(m.get("source"), m.get("url"), m.get("note"))]
        cites = [c for c in f.get("citations", []) if not restricted(c.get("title"), c.get("url"), c.get("publisher"))]
        counts["figures"] += len(f.get("metrics", [])) - len(metrics)
        counts["citations"] += len(f.get("citations", [])) - len(cites)
        findings.append(SkillFinding.model_validate(f | {
            "metrics": metrics, "citations": cites, "headline": prose(f.get("headline", ""), "Headline"),
            "summary": prose(f.get("summary", ""), "Summary"), "insights": bullets(f.get("insights", [])),
            "signals": signals(f.get("signals", [])),
        }))
    syn = data["synthesis"]
    synthesis = ExecutiveSynthesis.model_validate(syn | {
        "executive_summary": prose(syn.get("executive_summary", ""), "Summary"),
        "key_takeaways": bullets(syn.get("key_takeaways", [])), "what_changed": bullets(syn.get("what_changed", [])),
        "watch_list": bullets(syn.get("watch_list", [])), "risks": signals(syn.get("risks", [])),
        "opportunities": signals(syn.get("opportunities", [])),
    })
    deltas = [d for d in data["deltas"] if not restricted(d.get("previous_source"), d.get("current_source"))]
    issues = [i for i in data["issues"] if ok(i.get("message", ""))]
    counts["changes"], counts["notes"] = len(data["deltas"]) - len(deltas), len(data["issues"]) - len(issues)

    write_report(run_id=run_id, synthesis=synthesis, findings=findings,
                 deltas=[MetricDelta.model_validate(d) for d in deltas],
                 issues=[ValidationIssue.model_validate(i) for i in issues],
                 out_dir=out_dir, incident=None, style=None,
                 generated_at=datetime.strptime(run_id[:15], "%Y%m%dT%H%M%S"))
    shutil.rmtree(tmp_data, ignore_errors=True)
    print(f"Removed: {counts}; kept {sum(len(f.metrics) for f in findings)} figures")

    leftovers = [(p.name, len(RESTRICTED.findall(p.read_text(encoding="utf-8", errors="ignore"))))
                 for p in out_dir.rglob("*") if p.is_file() and p.suffix in (".html", ".md", ".json")]
    leftovers = [x for x in leftovers if x[1]]
    print("Restricted mentions left:", leftovers or "none")
    return 1 if leftovers else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    args = [Path(a) for a in sys.argv[1:]]
    sys.exit(main(args[0], args[1], args[2] if len(args) == 3 else Path("data/metrics.sqlite")))
