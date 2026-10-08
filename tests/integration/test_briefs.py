"""Deleting briefs: files, charts, metrics history and the CLI."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cre_monitor import cli
from cre_monitor.config import get_settings
from cre_monitor.graph.builder import run_brief
from cre_monitor.reporting.briefs import delete_brief, get_brief, list_briefs
from cre_monitor.store import get_store


def _brief_with_charts() -> str:
    """Run a demo brief and add a per-run chart folder (PNG export is off in tests)."""
    state = run_brief(["office-rents"])
    run_id = state["run_id"]
    charts = get_brief(run_id).date_dir / "charts" / run_id
    charts.mkdir(parents=True)
    (charts / "prime_rent_by_submarket.png").write_bytes(b"png")
    return run_id


def test_delete_one_of_two_same_day_briefs_keeps_the_other():
    first, second = _brief_with_charts(), _brief_with_charts()
    date_dir = get_brief(first).date_dir

    removed = delete_brief(first)
    assert get_brief(first) is None and get_brief(second) is not None
    assert not (date_dir / "charts" / first).exists() and (date_dir / "charts" / second).exists()
    assert not list(date_dir.glob(f"*{first}*"))                          # html, md, json all gone
    assert len(removed) == 4

    delete_brief(second)                                                 # last brief of the day
    assert not date_dir.exists()                                         # empty folder cleaned up


def test_legacy_shared_charts_removed_only_with_last_brief():
    first, second = _brief_with_charts(), _brief_with_charts()
    shared = get_brief(first).date_dir / "charts" / "legacy.png"         # pre-fix layout
    shared.write_bytes(b"png")

    delete_brief(first)
    assert shared.exists()                                               # still used by the other brief
    delete_brief(second)
    assert not shared.exists()


@pytest.mark.parametrize("bad", ["../../etc", "20261008T121732-zzzzzz", "", "x"])
def test_invalid_ids_are_rejected(bad):
    with pytest.raises(ValueError, match="Invalid brief id"):
        delete_brief(bad)


def test_unknown_id_is_rejected():
    with pytest.raises(ValueError, match="No brief"):
        delete_brief("20200101T000000-abcdef")


def test_with_metrics_removes_only_that_runs_history():
    run_id = _brief_with_charts()
    frame = get_store().frame()
    assert (frame["run_id"] == run_id).any() and (frame["run_id"] == "seed").any()

    delete_brief(run_id, with_metrics=True)
    frame = get_store().frame()
    assert not (frame["run_id"] == run_id).any()
    assert (frame["run_id"] == "seed").any()                             # seed history untouched


def test_default_delete_keeps_metrics_history():
    run_id = _brief_with_charts()
    delete_brief(run_id)
    assert (get_store().frame()["run_id"] == run_id).any()


def test_seed_history_cannot_be_deleted():
    with pytest.raises(ValueError, match="seed"):
        get_store().delete_run("seed")


def test_cli_list_and_delete():
    runner = CliRunner()
    run_id = _brief_with_charts()
    assert run_id in runner.invoke(cli.app, ["briefs", "list"]).output

    result = runner.invoke(cli.app, ["briefs", "delete", run_id, "--yes"])
    assert result.exit_code == 0 and "Deleted" in result.output
    assert get_brief(run_id) is None
    assert runner.invoke(cli.app, ["briefs", "delete", run_id, "--yes"]).exit_code == 1   # already gone


def test_cli_delete_asks_for_confirmation():
    run_id = _brief_with_charts()
    result = CliRunner().invoke(cli.app, ["briefs", "delete", run_id], input="n\n")
    assert get_brief(run_id) is not None and result.exit_code == 0
    assert get_settings().reports_dir in list_briefs()[0].html.parents
