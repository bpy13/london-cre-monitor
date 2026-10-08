"""CLI commands that are not covered with their feature (ui, style, bench)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cre_monitor import cli
from cre_monitor.benchmark import answer_key as ak
from cre_monitor.config import get_settings
from cre_monitor.style import save_example
from cre_monitor.style.profile import learn_profile
from tests.support.samples import REPORT, run_key


def test_cli_bench_commands_in_demo_mode():
    from typer.testing import CliRunner

    from cre_monitor import cli
    from cre_monitor.graph.builder import run_brief

    runner_ = CliRunner()
    save_example("ref.md", REPORT.encode())
    assert "No performance-check runs yet" in runner_.invoke(cli.app, ["bench", "history"]).output
    res = runner_.invoke(cli.app, ["bench", "key", "ref.md"])
    assert res.exit_code == 1 and "needs Claude" in res.output
    assert "No answer key" in runner_.invoke(cli.app, ["bench", "run", "ref.md"]).output
    ak.save_key(run_key())
    run_brief(["office-rents"])
    res = runner_.invoke(cli.app, ["bench", "judge", "ref.md"])
    assert res.exit_code == 0 and "Flesch" in res.output and "needs Claude" in res.output
    assert "judge" in runner_.invoke(cli.app, ["bench", "history", "ref.md"]).output


runner = CliRunner()


@pytest.fixture
def captured_run(monkeypatch):
    """Replace subprocess.run in the CLI so `cre-monitor ui` doesn't start Streamlit."""
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.subprocess, "run", lambda args, **kw: calls.append(args))
    return calls


def _toolbar_mode(args: list[str]) -> str:
    return args[args.index("--client.toolbarMode") + 1]


def test_ui_hides_developer_toolbar_by_default(captured_run):
    result = runner.invoke(cli.app, ["ui"])
    assert result.exit_code == 0, result.output
    assert _toolbar_mode(captured_run[0]) == "viewer"


def test_ui_debug_flag_enables_developer_toolbar(captured_run):
    result = runner.invoke(cli.app, ["ui", "--debug", "--port", "8600"])
    assert result.exit_code == 0, result.output
    args = captured_run[0]
    assert _toolbar_mode(args) == "developer"
    assert args[args.index("--server.port") + 1] == "8600"
    assert "debug mode" in result.output.lower()


def test_ui_debug_env_setting(captured_run, monkeypatch):
    monkeypatch.setenv("CRE_UI_DEBUG", "1")
    get_settings.cache_clear()
    runner.invoke(cli.app, ["ui"])
    assert _toolbar_mode(captured_run[0]) == "developer"


def test_cli_style_learn_show_clear(examples):
    runner = CliRunner()
    learned = runner.invoke(cli.app, ["style", "learn", "--heuristic"])
    assert learned.exit_code == 0 and "Learned" in learned.output
    assert "Key themes" in runner.invoke(cli.app, ["style", "show"]).output
    assert "Profile removed" in runner.invoke(cli.app, ["style", "clear"]).output
    assert "No house style" in runner.invoke(cli.app, ["style", "show"]).output


def test_cli_brief_no_style(examples):
    learn_profile()
    result = CliRunner().invoke(cli.app, ["brief", "--skills", "office-rents", "--no-style"])
    assert result.exit_code == 0
    html = max(get_settings().reports_dir.rglob("brief_*.html"), key=lambda p: p.stat().st_mtime_ns).read_text(encoding="utf-8")
    assert "<h2>Executive summary</h2>" in html and "Key themes" not in html
