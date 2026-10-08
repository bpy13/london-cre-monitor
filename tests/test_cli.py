"""CLI behaviour that doesn't need a running server (subprocess calls are captured)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cre_monitor import cli
from cre_monitor.config import get_settings

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
