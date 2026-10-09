"""Data export zip from a populated installation (incl. CLI)."""

from __future__ import annotations

import json
import zipfile
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from typer.testing import CliRunner

from cre_monitor import cli
from cre_monitor.config import get_settings
from cre_monitor.errors import make_incident
from cre_monitor.export import export_data
from cre_monitor.graph.builder import ask, run_brief
from cre_monitor.store import get_conversation_store, get_store


SECRET = "sk-ant-THIS-MUST-NEVER-BE-EXPORTED"


@pytest.fixture
def populated(monkeypatch):
    """A brief, a conversation with a reference, and a turn with an error incident."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)   # demo mode stays on (CRE_DEMO_MODE=1)
    get_settings.cache_clear()
    run_id = run_brief(["office-rents"])["run_id"]
    ask("What are prime rents in the West End?", thread_id="conv-a")
    ask("How has that changed?", thread_id="conv-b", refs=["conv-a"])
    incident = make_incident([("answer", "Error code: 403 - forbidden")], total=True, thread_id="conv-c")
    get_conversation_store().record_turn("conv-c", "Bank Rate?", "I couldn't complete this request.", incident=incident)
    return {"run_id": run_id, "incident_id": incident.id}


def _open(result):
    zf = zipfile.ZipFile(result.path)
    root = zf.namelist()[0].split("/")[0]
    return zf, root


def test_export_structure_and_contents(populated):
    result = export_data(now=datetime(2026, 10, 8, 15, 0, 0))
    assert result.path.name == "cre-export_20261008-150000.zip"
    zf, root = _open(result)
    names = set(zf.namelist())
    for f in ("README.md", "manifest.json", "cre-export.xlsx", "metrics.csv", "briefs_index.csv", "conversations.json"):
        assert f"{root}/{f}" in names, f

    # Metrics: every stored row, with sources.
    metrics = pd.read_csv(zf.open(f"{root}/metrics.csv"), encoding="utf-8-sig")
    assert len(metrics) == len(get_store().frame()) == result.counts["metric_rows"]
    assert {"key", "submarket", "period", "value", "source", "url"} <= set(metrics.columns)

    # Briefs: files copied under briefs/<date>/ and indexed.
    run_id = populated["run_id"]
    index = pd.read_csv(zf.open(f"{root}/briefs_index.csv"), encoding="utf-8-sig")
    assert index["brief_id"].tolist() == [run_id]
    for col in ("html", "markdown", "findings_json"):
        assert f"{root}/{index[col][0]}" in names

    # Conversations: readable transcripts + structured JSON.
    convs = json.loads(zf.read(f"{root}/conversations.json"))
    assert {c["thread_id"] for c in convs} == {"conv-a", "conv-b", "conv-c"}
    conv_b = next(c for c in convs if c["thread_id"] == "conv-b")
    assert conv_b["turns"][0]["references"] == ["conv-a"]
    transcripts = {n: zf.read(n).decode() for n in names if n.startswith(f"{root}/conversations/") and n.endswith(".md")}
    assert len(transcripts) == 3
    assert any("Referenced: What are prime rents in the West End?" in t for t in transcripts.values())
    assert any(populated["incident_id"] in t for t in transcripts.values())

    # Excel workbook: three sheets with matching row counts.
    sheets = pd.read_excel(zf.open(f"{root}/cre-export.xlsx"), sheet_name=None)
    assert set(sheets) == {"Metrics", "Briefs", "Conversations"}
    assert len(sheets["Metrics"]) == len(metrics) and len(sheets["Conversations"]) == result.counts["turns"]
    assert populated["incident_id"] in sheets["Conversations"]["error_reference"].fillna("").tolist()

    manifest = json.loads(zf.read(f"{root}/manifest.json"))
    assert manifest["counts"] == result.counts and manifest["filters"]["since"] is None


def test_export_never_contains_secrets(populated):
    zf, _ = _open(export_data(include_logs=True))
    for name in zf.namelist():
        if not name.endswith("/"):
            assert SECRET.encode() not in zf.read(name), name


def test_since_filter_excludes_older_data(populated):
    tomorrow = date.today() + timedelta(days=1)
    result = export_data(since=tomorrow)
    assert result.counts == {"metric_rows": 0, "briefs": 0, "conversations": 0, "turns": 0,
                             "performance_checks": 0, "log_files": 0}

    today = export_data(since=date.today())
    frame = get_store().frame()
    assert today.counts["metric_rows"] == (frame["run_id"] != "seed").sum()   # seed history only in full exports
    assert today.counts["briefs"] == 1 and today.counts["conversations"] == 3


def test_logs_only_when_requested(populated):
    log_dir = get_settings().data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "ui_2026-10-08.log").write_text("Incident ERR-TEST", encoding="utf-8")
    assert export_data().counts["log_files"] == 0
    with_logs = export_data(include_logs=True)
    zf, root = _open(with_logs)
    assert with_logs.counts["log_files"] == 1 and f"{root}/logs/ui_2026-10-08.log" in zf.namelist()


def test_export_on_empty_installation():
    result = export_data()
    assert result.counts["briefs"] == 0 and result.counts["conversations"] == 0
    assert result.counts["performance_checks"] == 0
    assert result.path.exists()


def test_export_includes_performance_checks(populated):
    from cre_monitor.benchmark.runner import run_judge
    from cre_monitor.style import save_example
    from tests.support.samples import REPORT, run_key

    save_example("ref.md", REPORT.encode())
    run = run_judge(run_key())                                     # demo mode: free statistics only
    result = export_data()
    assert result.counts["performance_checks"] == 1
    zf, root = _open(result)
    assert f"{root}/performance_checks/{run.run_id}.json" in zf.namelist()
    summary = zf.read(f"{root}/performance_checks.csv").decode("utf-8-sig")
    assert run.run_id in summary and "judge" in summary


def test_cli_export(populated):
    runner = CliRunner()
    assert runner.invoke(cli.app, ["export", "--since", "08/10/2026"]).exit_code == 2
    result = runner.invoke(cli.app, ["export"])
    assert result.exit_code == 0 and "Exported" in result.output
    assert list(get_settings().exports_dir.glob("cre-export_*.zip"))
