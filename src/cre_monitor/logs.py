"""Logging setup shared by the CLI and the Streamlit UI.

Everything is logged at INFO to ``data/logs/<name>_<date>.log`` (one file per
entry point per day). Incident records (see :mod:`cre_monitor.errors`) land in
the same file, so engineers can trace a user's reference with e.g.
``grep ERR-20261008-1530-7F3A data/logs/*.log``.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from cre_monitor.config import get_settings

#: Third-party libraries that are chatty at INFO.
_NOISY = ("httpx", "httpcore", "anthropic", "trafilatura", "kaleido", "choreographer", "watchdog")


def setup_logging(log_name: str, console_level: int = logging.INFO) -> Path:
    """Log INFO to ``data/logs/<log_name>_<date>.log`` and ``console_level`` to the console.

    Idempotent: calling it again with the same target (e.g. on every Streamlit
    re-run) leaves the existing handlers in place instead of duplicating them.

    Args:
        log_name: File prefix, e.g. ``"brief"``, ``"chat"``, ``"ui"``.
        console_level: Console verbosity; interactive commands use WARNING so
            answers are not buried in log lines.

    Returns:
        The log file path.
    """
    log_dir = get_settings().data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{log_name}_{date.today().isoformat()}.log"

    root = logging.getLogger()
    already = any(
        isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_file.resolve() for h in root.handlers
    )
    if not already:
        console = logging.StreamHandler()
        console.setLevel(console_level)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            handlers=[console, logging.FileHandler(log_file, encoding="utf-8")],
            force=True,
        )
        for noisy in _NOISY:
            logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file
