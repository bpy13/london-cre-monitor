"""Merge another installation's data into this one (SQLite to SQLite).

Use case: two colleagues (or a laptop and a Codespace) ran the app separately
and want one combined history - metrics, conversations (with resumable agent
memory) and, optionally, briefs.

Source: a project root (containing ``data/`` and optionally ``reports/``) or a
``data/`` folder itself. Target: this installation (``settings.data_dir`` /
``settings.reports_dir``).

Rules - designed to be **idempotent** (re-merging the same source changes
nothing) and to **never overwrite** existing target data:

* **Metrics** (``metrics.sqlite``): add source rows not already present
  (whole-row match). Source ``seed`` rows are skipped when the target has its own
  seed history, so the starter data isn't duplicated.
* **Conversations** (``conversations.sqlite``), per thread, comparing turns by
  (created_at, question):

  - ``added``    - thread not in target: copied as-is.
  - ``skipped``  - every source turn already in target (already merged).
  - ``extended`` - target's turns are the start of the source's: the missing
    turns are appended (the conversation continued on the source machine).
  - ``renamed``  - same id but a different history: imported under a new id
    ``<id>-<4 hex>``; references to it from merged turns are remapped.

* **Agent memory** (``checkpoints.sqlite``, LangGraph): checkpoint rows of
  added / extended / renamed threads are copied (new id where renamed) with
  INSERT OR IGNORE, so merged conversations can be resumed. Threads that exist
  only in checkpoints (no conversation index) are copied if absent.
* **Briefs** (``reports/``, optional): files missing from the target are copied;
  differing files with the same path are left alone and reported as conflicts.
* **Performance-check runs** (``data/benchmarks/*.json``): missing runs are copied
  (run ids are unique timestamps), like brief files.

All-or-nothing - a real merge runs in phases:

1. **Rehearse**: the full merge runs on in-memory copies of the target (the same
   code as ``dry_run``). Data problems or bugs fail here, before any write.
2. **Lock**: a write lock (``BEGIN IMMEDIATE``) is taken on all three target
   databases. If another process is writing (e.g. the app finishing a chat), the
   merge stops with :class:`MergeError` and nothing has changed. While locked,
   nothing else can write, so no concurrent change can be lost.
3. **Back up** the target databases (SQLite backup API) to
   ``data/backups/pre-merge_<timestamp>/``.
4. **Apply and commit**, then copy brief files.
5. **On any failure after writing started**: all three databases are restored
   from the backup, brief files copied by this run are deleted, and databases
   the merge created are removed - the target is exactly as before.

A single cross-file SQLite transaction is deliberately *not* relied on:
LangGraph keeps ``checkpoints.sqlite`` in WAL mode, where SQLite does not
guarantee atomic commits across attached files.

Other guarantees: the source is opened **read-only**; ``dry_run=True`` only
rehearses (step 1) and reports, writing nothing. Stopping both apps before a
merge is still recommended. This is a SQLite-specific tool; a future move to
Postgres would use its own migration.
"""

from __future__ import annotations

import filecmp
import json
import logging
import shutil
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from cre_monitor.config import get_settings

logger = logging.getLogger(__name__)

DB_FILES = ("metrics.sqlite", "conversations.sqlite", "checkpoints.sqlite")
#: A metric row is identified by all of its columns (whole-row match).
METRIC_COLS = ("run_id", "run_at", "skill", "key", "submarket", "value", "unit",
               "period", "source", "url", "as_of", "note")
_TURN_COLS = ("thread_id", "idx", "created_at", "question", "answer", "skills_json",
              "reasoning", "issues_json", "findings_json", "refs_json", "incident_json")


#: Seconds to wait for another process's write lock before giving up.
LOCK_TIMEOUT_S = 5.0


class MergeError(RuntimeError):
    """A merge that could not complete. ``restored`` tells whether the target
    was rolled back from the pre-merge backup (False = nothing had been written)."""

    def __init__(self, message: str, *, restored: bool, backup: Path | None = None) -> None:
        super().__init__(message)
        self.restored = restored
        self.backup = backup


class MergeReport(BaseModel):
    """What a merge did (or would do, for a dry run)."""

    source_data: Path
    source_reports: Path | None = None
    dry_run: bool
    backup: Path | None = None
    metrics_added: int = 0
    metrics_skipped: int = 0
    conversations: dict[str, list[str]] = Field(
        default_factory=lambda: {"added": [], "extended": [], "renamed": [], "skipped": []},
        description="Thread ids per action; renamed entries read 'old -> new'.",
    )
    turns_added: int = 0
    checkpoint_threads_copied: int = 0
    checkpoint_rows_copied: int = 0
    report_files_copied: int = 0
    benchmark_runs_copied: int = 0
    report_conflicts: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        """One-line human summary."""
        c = self.conversations
        return (
            f"metrics +{self.metrics_added} (skipped {self.metrics_skipped}) · conversations "
            f"added {len(c['added'])}, extended {len(c['extended'])}, renamed {len(c['renamed'])}, "
            f"skipped {len(c['skipped'])} (+{self.turns_added} turns) · agent memory "
            f"{self.checkpoint_threads_copied} threads ({self.checkpoint_rows_copied} rows) · "
            f"report files +{self.report_files_copied}"
            + (f", {len(self.report_conflicts)} conflicts" if self.report_conflicts else "")
            + f" · performance checks +{self.benchmark_runs_copied}"
        )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def resolve_source(path: Path) -> tuple[Path, Path | None]:
    """Return (data dir, reports dir or None) for a project root or a data folder."""
    path = path.resolve()
    if (path / "data").is_dir():
        reports = path / "reports"
        return path / "data", reports if reports.is_dir() else None
    if any((path / f).exists() for f in DB_FILES):
        return path, None
    raise ValueError(f"No CRE Monitor data found in {path} (expected data/ or *.sqlite files)")


def _open_source(path: Path) -> sqlite3.Connection | None:
    """Open a source database read-only (None if the file doesn't exist)."""
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _target(path: Path, dry_run: bool, ensure: Callable[[sqlite3.Connection], None]) -> Iterator[sqlite3.Connection]:
    """Target connection: the real file (committed on success, rolled back on error),
    or for a dry run an in-memory copy that is simply discarded."""
    if dry_run:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        if path.exists():
            # closing(): `with sqlite3.connect()` only commits - it does NOT close, and an
            # open handle on Windows blocks later restore/delete of the file.
            with closing(sqlite3.connect(path)) as disk:
                disk.backup(conn)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        ensure(conn)
        yield conn
        if not dry_run:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]


def backup_target(data_dir: Path, now: datetime) -> Path | None:
    """Consistent copies of the target databases (SQLite backup API). None if nothing to back up."""
    existing = [data_dir / f for f in DB_FILES if (data_dir / f).exists()]
    if not existing:
        return None
    dest = data_dir / "backups" / f"pre-merge_{now:%Y%m%d-%H%M%S}"
    dest.mkdir(parents=True, exist_ok=True)
    for src in existing:
        s, d = sqlite3.connect(src), sqlite3.connect(dest / src.name)
        try:
            s.backup(d)
        finally:
            s.close()
            d.close()
    return dest


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def _merge_metrics(src: sqlite3.Connection, dst: sqlite3.Connection, report: MergeReport) -> None:
    cols = ", ".join(METRIC_COLS)
    existing = {tuple(r) for r in dst.execute(f"SELECT {cols} FROM metrics")}
    target_has_seed = any(r[0] == "seed" for r in existing)
    new_rows = []
    for row in src.execute(f"SELECT {cols} FROM metrics"):
        row = tuple(row)
        if row in existing or (row[0] == "seed" and target_has_seed):
            report.metrics_skipped += 1
            continue
        existing.add(row)
        new_rows.append(row)
    dst.executemany(f"INSERT INTO metrics ({cols}) VALUES ({', '.join('?' * len(METRIC_COLS))})", new_rows)
    report.metrics_added = len(new_rows)


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------

def _source_turns(src: sqlite3.Connection) -> dict[str, list[dict]]:
    """All source turns by thread, tolerating older schemas (missing columns -> defaults)."""
    have = set(_columns(src, "turns"))
    defaults = {"refs_json": "[]", "incident_json": None}
    by_thread: dict[str, list[dict]] = {}
    for r in src.execute("SELECT * FROM turns ORDER BY thread_id, idx"):
        row = {c: (r[c] if c in have else defaults.get(c)) for c in _TURN_COLS}
        by_thread.setdefault(row["thread_id"], []).append(row)
    return by_thread


def _fingerprints(turns: list[dict]) -> list[tuple[str, str]]:
    return [(t["created_at"], t["question"]) for t in turns]


def _merge_conversations(src: sqlite3.Connection, dst: sqlite3.Connection, report: MergeReport) -> dict[str, str]:
    """Merge the conversation index.

    Returns:
        ``{source thread id: target thread id}`` for every thread whose agent
        memory should be copied (added / extended / renamed).
    """
    src_convs = {r["thread_id"]: dict(r) for r in src.execute("SELECT * FROM conversations")}
    src_turns = _source_turns(src)
    dst_convs = {r["thread_id"] for r in dst.execute("SELECT thread_id FROM conversations")}
    dst_turns: dict[str, list[dict]] = {}
    for r in dst.execute("SELECT thread_id, idx, created_at, question FROM turns ORDER BY thread_id, idx"):
        dst_turns.setdefault(r["thread_id"], []).append(dict(r))

    # 1) Decide an action per source thread (before writing, so references can be remapped).
    plan: dict[str, tuple[str, str]] = {}
    taken = set(dst_convs) | set(src_convs)
    for tid in src_convs:
        s_fp, d_fp = _fingerprints(src_turns.get(tid, [])), _fingerprints(dst_turns.get(tid, []))
        if tid not in dst_convs:
            plan[tid] = ("added", tid)
        elif set(s_fp) <= set(d_fp):
            plan[tid] = ("skipped", tid)
        elif s_fp[: len(d_fp)] == d_fp:
            plan[tid] = ("extended", tid)
        else:
            new_id = f"{tid}-{uuid.uuid4().hex[:4]}"
            while new_id in taken:
                new_id = f"{tid}-{uuid.uuid4().hex[:4]}"
            taken.add(new_id)
            plan[tid] = ("renamed", new_id)
    id_map = {s: t for s, (_, t) in plan.items()}

    # 2) Apply.
    insert_turn = f"INSERT INTO turns ({', '.join(_TURN_COLS)}) VALUES ({', '.join('?' * len(_TURN_COLS))})"
    for tid, (action, new_id) in plan.items():
        report.conversations[action].append(f"{tid} -> {new_id}" if action == "renamed" else tid)
        if action == "skipped":
            continue
        conv, turns = src_convs[tid], src_turns.get(tid, [])
        if action == "extended":
            start = len(dst_turns[tid])
            turns = turns[start:]
            dst.execute("UPDATE conversations SET updated_at = MAX(updated_at, ?) WHERE thread_id = ?",
                        (conv["updated_at"], tid))
        else:
            start = 0
            dst.execute("INSERT INTO conversations (thread_id, title, created_at, updated_at) VALUES (?,?,?,?)",
                        (new_id, conv["title"], conv["created_at"], conv["updated_at"]))
        for i, t in enumerate(turns):
            refs = [id_map.get(r, r) for r in json.loads(t["refs_json"] or "[]")]
            incident = t["incident_json"]
            if incident and new_id != tid:  # keep the incident's thread pointer accurate
                data = json.loads(incident)
                data["thread_id"] = new_id
                incident = json.dumps(data)
            dst.execute(insert_turn, (new_id, start + i, t["created_at"], t["question"], t["answer"],
                                      t["skills_json"], t["reasoning"], t["issues_json"], t["findings_json"],
                                      json.dumps(refs), incident))
        report.turns_added += len(turns)
    return {s: t for s, (action, t) in plan.items() if action != "skipped"}


# --------------------------------------------------------------------------
# Agent memory (LangGraph checkpoints)
# --------------------------------------------------------------------------

def _merge_checkpoints(src: sqlite3.Connection, dst: sqlite3.Connection, thread_map: dict[str, str],
                       report: MergeReport) -> None:
    """Copy LangGraph checkpoint rows (every table with a thread_id column) for the mapped threads."""
    dst_tables = set(_tables(dst))
    tables = [t for t in _tables(src) if t in dst_tables and "thread_id" in _columns(src, t)]
    dst_threads = {r[0] for t in tables for r in dst.execute(f"SELECT DISTINCT thread_id FROM {t}")}
    src_threads = {r[0] for t in tables for r in src.execute(f"SELECT DISTINCT thread_id FROM {t}")}

    # Indexed conversations follow the conversation plan; memory-only threads are copied if absent.
    mapping = {s: t for s, t in thread_map.items() if s in src_threads}
    for tid in src_threads - set(thread_map) - dst_threads:
        mapping[tid] = tid
    report.checkpoint_threads_copied = len(mapping)

    for table in tables:
        dst_cols = set(_columns(dst, table))
        cols = [c for c in _columns(src, table) if c in dst_cols]
        ti = cols.index("thread_id")
        sql = f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        for s_tid, d_tid in mapping.items():
            rows = [list(r) for r in src.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE thread_id = ?", (s_tid,))]
            for r in rows:
                r[ti] = d_tid
            before = dst.total_changes
            dst.executemany(sql, rows)
            report.checkpoint_rows_copied += dst.total_changes - before


def _ensure_checkpoints(conn: sqlite3.Connection) -> None:
    from langgraph.checkpoint.sqlite import SqliteSaver

    SqliteSaver(conn).setup()


# --------------------------------------------------------------------------
# Briefs (report files)
# --------------------------------------------------------------------------

def _copy_missing_files(src_root: Path, dst_root: Path, report: MergeReport, dry_run: bool,
                        copied: list[Path] | None, label: str = "") -> int:
    """Copy files missing from ``dst_root``; differing same-path files are reported as conflicts.

    Each copied path is recorded in ``copied`` (for rollback). Returns the number of files
    copied (or that would be, for a dry run).
    """
    n = 0
    for src_file in src_root.rglob("*"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src_root)
        target = dst_root / rel
        if target.exists():
            if not filecmp.cmp(src_file, target, shallow=False):
                report.report_conflicts.append(f"{label}{rel}")
            continue
        n += 1
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, target)
            if copied is not None:
                copied.append(target)
    return n


def _merge_reports(src_reports: Path, dst_reports: Path, report: MergeReport, dry_run: bool,
                   copied: list[Path] | None = None) -> None:
    """Copy missing brief files (see :func:`_copy_missing_files`)."""
    report.report_files_copied += _copy_missing_files(src_reports, dst_reports, report, dry_run, copied)


def _merge_benchmarks(src_data: Path, dst_data: Path, report: MergeReport, dry_run: bool,
                      copied: list[Path] | None = None) -> None:
    """Copy performance-check runs (``data/benchmarks/<run_id>.json``; ids are unique per run)."""
    src = src_data / "benchmarks"
    if src.is_dir():
        report.benchmark_runs_copied += _copy_missing_files(src, dst_data / "benchmarks", report, dry_run, copied,
                                                            label="data/benchmarks/")


# --------------------------------------------------------------------------
# Transaction helpers (all-or-nothing)
# --------------------------------------------------------------------------

def _lock(path: Path) -> sqlite3.Connection:
    """Open the target in manual-transaction mode and take its write lock.

    Raises:
        MergeError: Another process is writing (lock not obtained in time).
    """
    conn = sqlite3.connect(path, timeout=LOCK_TIMEOUT_S, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        conn.close()
        raise MergeError(
            f"{path.name} is in use by another process (is the app running?). Stop it and try again. ({exc})",
            restored=False,
        ) from exc
    return conn


def _commit(conn: sqlite3.Connection) -> None:
    """Commit one target database (a separate function so tests can inject failures)."""
    conn.execute("COMMIT")


def _restore(backup: Path | None, data_dir: Path, created: list[Path], copied: list[Path]) -> None:
    """Put the target back exactly as it was before the merge."""
    if backup is not None:
        for saved in backup.glob("*.sqlite"):
            src, dst = sqlite3.connect(saved), sqlite3.connect(data_dir / saved.name)
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()
    for path in created:  # databases that didn't exist before this merge
        for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
            p.unlink(missing_ok=True)
    for path in copied:
        path.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def merge_installation(
    source: Path,
    *,
    include_reports: bool = True,
    dry_run: bool = False,
    backup: bool = True,
    now: datetime | None = None,
) -> MergeReport:
    """Merge another installation's data (and briefs) into this one - all or nothing.

    Args:
        source: Project root of the other installation, or its ``data/`` folder.
        include_reports: Also merge brief files when the source has ``reports/``.
        dry_run: Rehearse on in-memory copies and report; write nothing.
        backup: Back up the target first. Needed for automatic restore, so
            disabling it also disables rollback across databases (not recommended).
        now: Timestamp override (tests).

    Raises:
        ValueError: Source has no data, or is this installation's own data folder.
        MergeError: The merge could not complete; ``restored`` says whether the
            target was rolled back (True) or never touched (False).
    """
    s = get_settings()
    now = now or datetime.now()
    src_data, src_reports = resolve_source(source)
    if src_data == s.data_dir.resolve():
        raise ValueError("The source is this installation's own data folder")
    src_reports = src_reports if include_reports else None

    sources = [_open_source(src_data / f) for f in DB_FILES]
    try:
        # 1) Rehearse on in-memory copies (this *is* the dry run).
        try:
            rehearsal = _run(sources, s, src_data, src_reports, dry_run=True)
        except Exception as exc:
            raise MergeError(f"Merge failed while preparing - nothing was changed. ({exc})", restored=False) from exc
        if dry_run:
            logger.info("Merge dry run from %s: %s", src_data, rehearsal.summary())
            return rehearsal
        # 2-5) Lock, back up, apply, commit - restoring on any failure.
        report = _apply(sources, s, src_data, src_reports, backup=backup, now=now)
    finally:
        for conn in sources:
            if conn is not None:
                conn.close()
    logger.info("Merge from %s: %s", src_data, report.summary())
    return report


def _run(sources, s, src_data: Path, src_reports: Path | None, *, dry_run: bool) -> MergeReport:
    """Rehearsal: the merge against in-memory copies of the target."""
    from cre_monitor.store.conversations import ensure_schema as ensure_conversations
    from cre_monitor.store.metrics import ensure_schema as ensure_metrics

    m_src, c_src, k_src = sources
    report = MergeReport(source_data=src_data, source_reports=src_reports, dry_run=True)
    thread_map: dict[str, str] = {}
    if m_src is not None and "metrics" in _tables(m_src):
        with _target(s.metrics_db_path, True, ensure_metrics) as dst:
            _merge_metrics(m_src, dst, report)
    if c_src is not None and "conversations" in _tables(c_src):
        with _target(s.conversations_db_path, True, ensure_conversations) as dst:
            thread_map = _merge_conversations(c_src, dst, report)
    if k_src is not None:
        with _target(s.checkpoint_db_path, True, _ensure_checkpoints) as dst:
            _merge_checkpoints(k_src, dst, thread_map, report)
    if src_reports is not None:
        _merge_reports(src_reports, s.reports_dir, report, dry_run=True)
    _merge_benchmarks(src_data, s.data_dir, report, dry_run=True)
    return report


def _apply(sources, s, src_data: Path, src_reports: Path | None, *, backup: bool, now: datetime) -> MergeReport:
    """The real merge: lock all targets, back up, apply, commit; restore on failure."""
    from cre_monitor.store.conversations import ensure_schema as ensure_conversations
    from cre_monitor.store.metrics import ensure_schema as ensure_metrics

    m_src, c_src, k_src = sources
    report = MergeReport(source_data=src_data, source_reports=src_reports, dry_run=False)
    s.data_dir.mkdir(parents=True, exist_ok=True)
    targets = [  # (source conn, target path, schema setup) for databases the source actually has
        (src, path, ensure) for src, path, ensure, table in [
            (m_src, s.metrics_db_path, ensure_metrics, "metrics"),
            (c_src, s.conversations_db_path, ensure_conversations, "conversations"),
            (k_src, s.checkpoint_db_path, _ensure_checkpoints, None),
        ] if src is not None and (table is None or table in _tables(src))
    ]

    created = [path for _, path, _ in targets if not path.exists()]
    for _, path, ensure in targets:  # schema setup commits on its own, so do it before locking
        with closing(sqlite3.connect(path)) as conn:
            ensure(conn)
            conn.commit()

    locks: dict[Path, sqlite3.Connection] = {}
    copied: list[Path] = []
    writing = False
    try:
        for _, path, _ in targets:
            locks[path] = _lock(path)          # MergeError here = nothing written
        if backup:
            report.backup = backup_target(s.data_dir, now)
        writing = True
        thread_map: dict[str, str] = {}
        if s.metrics_db_path in locks:
            _merge_metrics(m_src, locks[s.metrics_db_path], report)
        if s.conversations_db_path in locks:
            thread_map = _merge_conversations(c_src, locks[s.conversations_db_path], report)
        if s.checkpoint_db_path in locks:
            _merge_checkpoints(k_src, locks[s.checkpoint_db_path], thread_map, report)
        for conn in locks.values():
            _commit(conn)
        if src_reports is not None:
            _merge_reports(src_reports, s.reports_dir, report, dry_run=False, copied=copied)
        _merge_benchmarks(src_data, s.data_dir, report, dry_run=False, copied=copied)
        return report
    except Exception as exc:
        for conn in locks.values():
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()
        locks.clear()
        if not writing:
            _restore(None, s.data_dir, created, copied)
            if isinstance(exc, MergeError):
                raise
            raise MergeError(f"Merge failed before writing - nothing was changed. ({exc})", restored=False) from exc
        if report.backup is None:
            raise MergeError(f"Merge failed and no backup was taken (--no-backup); data may be partially merged. ({exc})",
                             restored=False) from exc
        _restore(report.backup, s.data_dir, created, copied)
        raise MergeError(f"Merge failed - your data was restored to its pre-merge state from {report.backup}. ({exc})",
                         restored=True, backup=report.backup) from exc
    finally:
        for conn in locks.values():
            conn.close()
