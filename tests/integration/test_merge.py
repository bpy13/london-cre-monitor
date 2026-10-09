"""Merging two real installations, all-or-nothing behaviour and the CLI."""

from __future__ import annotations

import sqlite3

import pytest
from typer.testing import CliRunner

from cre_monitor import cli
from cre_monitor.config import get_settings
from cre_monitor.store.merge import merge_installation
from tests.conftest import _clear_caches


@pytest.fixture
def two_installs(tmp_path, monkeypatch):
    """Helpers to act as the *source* installation or the *target* (this one)."""
    target_data, target_reports = get_settings().data_dir, get_settings().reports_dir
    source_root = tmp_path / "other"

    def use(which: str):
        root = (source_root / "data", source_root / "reports") if which == "source" else (target_data, target_reports)
        monkeypatch.setenv("DATA_DIR", str(root[0]))
        monkeypatch.setenv("REPORTS_DIR", str(root[1]))
        _clear_caches()

    return source_root, use


def _ask(question, thread, refs=None):
    from cre_monitor.graph.builder import ask
    return ask(question, thread_id=thread, refs=refs)


def _messages(thread):
    from cre_monitor.graph.builder import get_chat_graph
    return get_chat_graph().get_state({"configurable": {"thread_id": thread}}).values.get("messages") or []


def _rows(db: str, table: str) -> int:
    with sqlite3.connect(get_settings().data_dir / db) as c:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _snapshot() -> dict:
    """Full contents of every target database (and the list of report files)."""
    s = get_settings()
    snap = {"files": sorted(str(p.relative_to(s.reports_dir)) for p in s.reports_dir.rglob("*") if p.is_file())
            if s.reports_dir.exists() else []}
    for name in ("metrics.sqlite", "conversations.sqlite", "checkpoints.sqlite"):
        path = s.data_dir / name
        if not path.exists():
            snap[name] = None
            continue
        with sqlite3.connect(path) as c:
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            snap[name] = {t: sorted(map(repr, c.execute(f"SELECT * FROM {t}"))) for t in tables}
    return snap


@pytest.fixture
def merge_ready(two_installs):
    """Source with a brief + chats; target with its own chat. Returns (source, pre-merge snapshot)."""
    source, use = two_installs
    use("source")
    from cre_monitor.graph.builder import run_brief
    run_brief(["office-rents"])
    _ask("What are prime rents in the West End?", "t-src")
    use("target")
    _ask("Bank Rate?", "t-own")
    return source, _snapshot()


def test_performance_check_runs_are_merged_once(merge_ready):
    from datetime import datetime

    from cre_monitor.benchmark.store import RunRecord, list_runs

    source, _ = merge_ready
    # A performance-check run recorded on the *source* installation.
    run = RunRecord(run_id="20261009T101500-000001", kind="judge", report="ref.md", created_at=datetime(2026, 10, 9))
    (source / "data" / "benchmarks").mkdir(parents=True)
    (source / "data" / "benchmarks" / f"{run.run_id}.json").write_text(run.model_dump_json(), encoding="utf-8")
    assert list_runs() == []

    report = merge_installation(source)
    assert report.benchmark_runs_copied == 1 and [r.run_id for r in list_runs()] == [run.run_id]
    assert merge_installation(source).benchmark_runs_copied == 0   # idempotent


def test_merge_into_empty_target_and_resume(two_installs):
    source, use = two_installs
    use("source")
    from cre_monitor.graph.builder import run_brief
    run_id = run_brief(["office-rents"])["run_id"]
    _ask("What are prime rents in the West End?", "t-src")
    src_metric_rows = _rows("metrics.sqlite", "metrics")

    use("target")
    report = merge_installation(source)
    assert report.conversations["added"] == ["t-src"] and report.turns_added == 1
    assert report.metrics_added == src_metric_rows
    assert report.checkpoint_threads_copied == 1 and report.checkpoint_rows_copied > 0
    assert report.report_files_copied >= 3                                # html, md, json

    from cre_monitor.reporting.briefs import get_brief
    from cre_monitor.store import get_conversation_store
    assert get_brief(run_id) is not None
    assert get_conversation_store().get("t-src").title == "What are prime rents in the West End?"
    assert len(_messages("t-src")) == 2                                   # agent memory came along
    assert len(_ask("And the City?", "t-src")["messages"]) == 4           # ... and resumes


def test_merge_is_idempotent(two_installs):
    source, use = two_installs
    use("source")
    _ask("Bank Rate?", "t1")
    use("target")
    merge_installation(source)
    counts = {t: _rows(db, t) for db, t in [("metrics.sqlite", "metrics"), ("conversations.sqlite", "turns"),
                                            ("checkpoints.sqlite", "checkpoints")]}
    again = merge_installation(source)
    assert again.metrics_added == 0 and again.turns_added == 0 and again.checkpoint_rows_copied == 0
    assert again.conversations["skipped"] == ["t1"] and again.report_files_copied == 0
    assert counts == {t: _rows(db, t) for db, t in [("metrics.sqlite", "metrics"), ("conversations.sqlite", "turns"),
                                                    ("checkpoints.sqlite", "checkpoints")]}


def test_conversation_continued_on_source_is_extended(two_installs):
    source, use = two_installs
    use("source")
    _ask("Bank Rate?", "t1")
    use("target")
    merge_installation(source)
    use("source")
    _ask("And gilt yields?", "t1")                                         # conversation continues on the source
    use("target")
    report = merge_installation(source)
    from cre_monitor.store import get_conversation_store
    assert report.conversations["extended"] == ["t1"] and report.turns_added == 1
    assert [t.question for t in get_conversation_store().turns("t1")] == ["Bank Rate?", "And gilt yields?"]
    assert len(_messages("t1")) == 4                                      # memory includes the new turn


def test_same_id_different_history_is_renamed_and_refs_remapped(two_installs):
    source, use = two_installs
    use("source")
    _ask("What are prime rents in the West End?", "shared")
    _ask("How has that changed?", "follow", refs=["shared"])
    use("target")
    _ask("Bank Rate?", "shared")                                          # unrelated chat, same id
    report = merge_installation(source)

    from cre_monitor.store import get_conversation_store
    store = get_conversation_store()
    (entry,) = report.conversations["renamed"]
    new_id = entry.split(" -> ")[1]
    assert new_id.startswith("shared-") and store.get(new_id).title == "What are prime rents in the West End?"
    assert store.get("shared").title == "Bank Rate?"                      # target's chat untouched
    assert store.turns("follow")[0].refs == [new_id]                      # reference follows the rename
    assert len(_messages(new_id)) == 2 and len(_messages("shared")) == 2  # memories kept apart


def test_seed_history_not_duplicated(two_installs):
    source, use = two_installs
    use("source")
    _ask("Bank Rate?", "t1")                                              # seeds the source store
    use("target")
    _ask("Prime rents?", "t2")                                            # seeds the target store
    seed_before = sqlite3.connect(get_settings().metrics_db_path).execute(
        "SELECT COUNT(*) FROM metrics WHERE run_id='seed'").fetchone()[0]
    merge_installation(source)
    seed_after = sqlite3.connect(get_settings().metrics_db_path).execute(
        "SELECT COUNT(*) FROM metrics WHERE run_id='seed'").fetchone()[0]
    assert seed_before == seed_after > 0


def test_dry_run_writes_nothing_but_reports_exactly(two_installs):
    source, use = two_installs
    use("source")
    from cre_monitor.graph.builder import run_brief
    run_brief(["office-rents"])
    _ask("Bank Rate?", "t1")
    use("target")
    data_dir = get_settings().data_dir
    before = sorted(p.name for p in data_dir.rglob("*")) if data_dir.exists() else []

    dry = merge_installation(source, dry_run=True)
    after = sorted(p.name for p in data_dir.rglob("*")) if data_dir.exists() else []
    assert before == after and dry.backup is None                         # nothing written, no backup
    assert not list(get_settings().reports_dir.glob("*/brief_*.html"))

    real = merge_installation(source)
    for field in ("metrics_added", "turns_added", "checkpoint_rows_copied", "report_files_copied"):
        assert getattr(dry, field) == getattr(real, field), field


def test_backup_is_created_before_merge(two_installs):
    source, use = two_installs
    use("source")
    _ask("Bank Rate?", "t1")
    use("target")
    _ask("Prime rents?", "t2")
    report = merge_installation(source)
    assert report.backup is not None
    assert sorted(p.name for p in report.backup.iterdir()) == ["checkpoints.sqlite", "conversations.sqlite",
                                                               "metrics.sqlite"]
    with sqlite3.connect(report.backup / "conversations.sqlite") as c:   # pre-merge state preserved
        assert [r[0] for r in c.execute("SELECT thread_id FROM conversations")] == ["t2"]


def test_invalid_sources(tmp_path):
    with pytest.raises(ValueError, match="No CRE Monitor data"):
        merge_installation(tmp_path / "empty")
    get_settings().data_dir.mkdir(parents=True, exist_ok=True)
    (get_settings().data_dir / "metrics.sqlite").touch()
    with pytest.raises(ValueError, match="own data folder"):
        merge_installation(get_settings().data_dir)


def test_old_schema_source_merges(tmp_path):
    old = tmp_path / "old" / "data"
    old.mkdir(parents=True)
    with sqlite3.connect(old / "conversations.sqlite") as c:            # schema before refs/incidents existed
        c.executescript(
            "CREATE TABLE conversations (thread_id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT);"
            "CREATE TABLE turns (thread_id TEXT, idx INTEGER, created_at TEXT, question TEXT, answer TEXT,"
            " skills_json TEXT, reasoning TEXT, issues_json TEXT, findings_json TEXT);"
            "INSERT INTO conversations VALUES ('legacy', 'Old chat', '2026-10-01T09:00:00', '2026-10-01T09:00:00');"
            "INSERT INTO turns VALUES ('legacy', 0, '2026-10-01T09:00:00', 'q', 'a', '[]', NULL, '[]', '[]');"
        )
    report = merge_installation(tmp_path / "old")
    from cre_monitor.store import get_conversation_store
    assert report.conversations["added"] == ["legacy"]
    assert get_conversation_store().turns("legacy")[0].refs == []


def test_report_conflicts_keep_target_file(two_installs):
    source, _ = two_installs
    (source / "reports" / "2026-10-08").mkdir(parents=True)
    (source / "data").mkdir(parents=True)
    (source / "data" / "metrics.sqlite").touch()
    (source / "reports" / "2026-10-08" / "note.txt").write_text("source", encoding="utf-8")
    target_file = get_settings().reports_dir / "2026-10-08" / "note.txt"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("target", encoding="utf-8")
    report = merge_installation(source)
    assert report.report_conflicts == ["2026-10-08\\note.txt"] or report.report_conflicts == ["2026-10-08/note.txt"]
    assert target_file.read_text(encoding="utf-8") == "target"


def test_failure_during_commit_restores_everything(merge_ready, monkeypatch):
    """Worst case: metrics already committed when the next commit fails."""
    import cre_monitor.store.merge as merge
    source, before = merge_ready
    real_commit, calls = merge._commit, []

    def flaky_commit(conn):
        calls.append(conn)
        if len(calls) == 2:
            raise sqlite3.OperationalError("disk I/O error (simulated)")
        real_commit(conn)

    monkeypatch.setattr(merge, "_commit", flaky_commit)
    with pytest.raises(merge.MergeError, match="restored") as err:
        merge_installation(source)
    assert err.value.restored and err.value.backup is not None
    assert _snapshot() == before                                          # byte-for-byte as before
    assert len(_messages("t-own")) == 2                                   # own chat still resumable


def test_failure_while_copying_briefs_restores_and_removes_copies(merge_ready, monkeypatch):
    import cre_monitor.store.merge as merge
    source, before = merge_ready
    real_copy, copies = merge.shutil.copy2, []

    def flaky_copy(src, dst):
        if copies:
            raise OSError("No space left on device (simulated)")
        copies.append(dst)
        return real_copy(src, dst)

    monkeypatch.setattr(merge.shutil, "copy2", flaky_copy)
    with pytest.raises(merge.MergeError) as err:
        merge_installation(source)
    assert err.value.restored
    assert _snapshot() == before                                          # DBs restored AND copied brief removed


def test_failure_while_preparing_changes_nothing(merge_ready, monkeypatch):
    import cre_monitor.store.merge as merge
    source, before = merge_ready

    def broken(*args, **kwargs):
        raise KeyError("unexpected data (simulated)")

    monkeypatch.setattr(merge, "_merge_conversations", broken)
    with pytest.raises(merge.MergeError, match="nothing was changed") as err:
        merge_installation(source)
    assert not err.value.restored
    assert _snapshot() == before
    assert not (get_settings().data_dir / "backups").exists()             # failed before even backing up


def test_data_in_use_is_detected_and_nothing_changes(merge_ready, monkeypatch):
    import cre_monitor.store.merge as merge
    source, before = merge_ready
    monkeypatch.setattr(merge, "LOCK_TIMEOUT_S", 0.2)
    other = sqlite3.connect(get_settings().conversations_db_path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")                                      # e.g. the app mid-write
    try:
        with pytest.raises(merge.MergeError, match="in use") as err:
            merge_installation(source)
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert not err.value.restored
    assert _snapshot() == before


def test_failure_on_fresh_target_leaves_no_files(two_installs, monkeypatch):
    import cre_monitor.store.merge as merge
    source, use = two_installs
    use("source")
    _ask("Bank Rate?", "t1")
    use("target")                                                          # target has no databases yet
    monkeypatch.setattr(merge, "_commit", lambda conn: (_ for _ in ()).throw(sqlite3.OperationalError("simulated")))
    with pytest.raises(merge.MergeError):
        merge_installation(source)
    assert not list(get_settings().data_dir.glob("*.sqlite*"))           # created databases removed


def test_cli_reports_failed_merge(merge_ready, monkeypatch):
    import cre_monitor.store.merge as merge
    source, before = merge_ready
    monkeypatch.setattr(merge, "_commit", lambda conn: (_ for _ in ()).throw(sqlite3.OperationalError("simulated")))
    result = CliRunner().invoke(cli.app, ["merge", str(source), "--yes"])
    assert result.exit_code == 1
    assert "Merge failed" in result.output and "restored" in result.output and "ERR-" in result.output
    assert _snapshot() == before


def test_cli_merge(two_installs):
    source, use = two_installs
    use("source")
    _ask("Bank Rate?", "t1")
    use("target")
    runner = CliRunner()
    dry = runner.invoke(cli.app, ["merge", str(source), "--dry-run"])
    assert dry.exit_code == 0 and "Dry run" in dry.output
    from cre_monitor.store import get_conversation_store
    assert get_conversation_store().get("t1") is None                      # dry run changed nothing
    declined = runner.invoke(cli.app, ["merge", str(source)], input="n\n")
    assert "Preview" in declined.output and get_conversation_store().get("t1") is None
    applied = runner.invoke(cli.app, ["merge", str(source), "--yes"])
    assert applied.exit_code == 0 and "Merged" in applied.output
    assert get_conversation_store().get("t1") is not None
