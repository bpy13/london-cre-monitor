"""Safe edits of repo files from the UI: version history + edit-conflict detection.

Used by the metric/submarket catalogue (:mod:`cre_monitor.catalog`) and the skill
editor (:mod:`cre_monitor.skills.editor`). Those files are tracked in git and the
team commits them as usual; this module adds two safety nets for edits made
through the web UI, where several people may work at once:

* **History.** Before a file is overwritten (or deleted), its current content is
  copied to a ``.history/`` folder next to it (git-ignored, last
  :data:`MAX_VERSIONS` kept), so any UI change can be restored.
* **Conflicts.** Callers read a file's :func:`file_version` when they show it
  and pass it back as ``expected_version`` when saving. If someone else saved in
  between, :class:`ConflictError` is raised instead of silently overwriting.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path

#: Versions kept per file in ``.history/``.
MAX_VERSIONS = 50


class ConflictError(RuntimeError):
    """The file changed since the caller read it (someone else saved first)."""


def file_version(*paths: Path) -> str:
    """Short content hash of one or more files (a missing file counts as empty)."""
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes() if p.exists() else b"")
        h.update(b"\0")
    return h.hexdigest()[:16]


def _stamp() -> str:
    # Microseconds keep two saves in the same second apart.
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def backup(path: Path, history_dir: Path) -> Path | None:
    """Copy ``path`` into ``history_dir`` as ``<timestamp>__<name>``; prune old copies.

    Returns:
        The backup path, or None if ``path`` does not exist.
    """
    if not path.exists():
        return None
    history_dir.mkdir(parents=True, exist_ok=True)
    target = history_dir / f"{_stamp()}__{path.name}"
    shutil.copy2(path, target)
    for old in list_versions(history_dir, path.name)[MAX_VERSIONS:]:
        old.unlink(missing_ok=True)
    return target


def list_versions(history_dir: Path, name: str) -> list[Path]:
    """Saved versions of file ``name`` in ``history_dir``, newest first."""
    if not history_dir.exists():
        return []
    return sorted(history_dir.glob(f"*__{name}"), reverse=True)


def version_label(version: Path) -> str:
    """Human-readable time of a history entry, e.g. ``2026-10-09 14:03:12``."""
    stamp = version.name.split("__", 1)[0]
    try:
        return datetime.strptime(stamp, "%Y%m%d-%H%M%S-%f").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return stamp


def check_version(expected_version: str | None, *paths: Path) -> None:
    """Raise :class:`ConflictError` if the files no longer match ``expected_version``."""
    if expected_version is not None and file_version(*paths) != expected_version:
        names = ", ".join(p.name for p in paths)
        raise ConflictError(f"{names} changed since you opened it (someone else saved). "
                            "Reload to see the latest version, then re-apply your change.")


def write_text(path: Path, text: str, history_dir: Path) -> None:
    """Back up the current file, then write ``text`` atomically (temp file + rename)."""
    backup(path, history_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same volume: readers never see a half-written file
