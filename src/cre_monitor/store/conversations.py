"""Index of chat conversations, so past chats can be listed, reopened and resumed.

Two kinds of chat data exist, deliberately kept apart:

* **LangGraph checkpoints** (``data/checkpoints.sqlite``) hold the agent's
  *memory* per ``thread_id`` - the message history Claude sees on the next turn.
  That is what makes a resumed conversation continue with context. It is an
  opaque, LangGraph-managed format.
* **This store** (``data/conversations.sqlite``) holds what the *UI* needs to
  list and redraw a conversation: a title and timestamps per thread, plus each
  turn's question, answer, skills used, data-quality notes and findings (so
  charts can be rebuilt). Simple, documented tables - see docs/DATA_MODEL.md.

Schema::

    conversations(thread_id PK, title, created_at, updated_at)
    turns(thread_id, idx, created_at, question, answer, skills_json,
          reasoning, issues_json, findings_json, PK(thread_id, idx))

Turns are written by :func:`cre_monitor.graph.builder.ask`, so chats started from
the UI *and* the CLI (``cre-monitor chat --thread X``) appear in the list.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel

from cre_monitor.config import get_settings
from cre_monitor.schemas import SkillFinding, ValidationIssue

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    thread_id  TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    thread_id     TEXT NOT NULL,
    idx           INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    question      TEXT NOT NULL,
    answer        TEXT NOT NULL,
    skills_json   TEXT NOT NULL,
    reasoning     TEXT,
    issues_json   TEXT NOT NULL,
    findings_json TEXT NOT NULL,
    PRIMARY KEY (thread_id, idx)
);
CREATE INDEX IF NOT EXISTS ix_conversations_updated ON conversations(updated_at);
"""

#: Max length of an auto-generated title (first question, truncated).
TITLE_MAX = 60


class Conversation(BaseModel):
    """One row of the sidebar list."""

    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0


class Turn(BaseModel):
    """One question/answer exchange, with the details needed to redraw it."""

    idx: int
    created_at: datetime
    question: str
    answer: str
    skills: list[str]
    reasoning: str | None = None
    issues: list[ValidationIssue]
    findings: list[SkillFinding]


def make_title(question: str) -> str:
    """Conversation title from its first question: single line, truncated."""
    text = " ".join(question.split())
    return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1].rstrip() + "…"


class ConversationStore:
    """Thin wrapper around the conversations SQLite file."""

    def __init__(self, path: Path) -> None:
        """Open (and create if needed) the database at ``path``."""
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # Short-lived connection per operation: safe across Streamlit/LangGraph threads.
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- writes -------------------------------------------------------------
    def record_turn(
        self,
        thread_id: str,
        question: str,
        answer: str,
        skills: list[str] | None = None,
        reasoning: str | None = None,
        issues: list[ValidationIssue] | None = None,
        findings: list[SkillFinding] | None = None,
    ) -> int:
        """Append a turn, creating the conversation on its first turn.

        Returns:
            The index (0-based) of the recorded turn.
        """
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversations(thread_id, title, created_at, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET updated_at = excluded.updated_at",
                (thread_id, make_title(question), now, now),
            )
            idx = conn.execute(
                "SELECT COALESCE(MAX(idx) + 1, 0) FROM turns WHERE thread_id = ?", (thread_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    thread_id, idx, now, question, answer,
                    json.dumps(skills or []),
                    reasoning,
                    json.dumps([i.model_dump(mode="json") for i in issues or []]),
                    json.dumps([f.model_dump(mode="json") for f in findings or []]),
                ),
            )
        return idx

    def rename(self, thread_id: str, title: str) -> None:
        """Set a custom title."""
        with self._conn() as conn:
            conn.execute("UPDATE conversations SET title = ? WHERE thread_id = ?", (make_title(title), thread_id))

    def delete(self, thread_id: str) -> None:
        """Remove a conversation and its turns from the index.

        The caller should also delete the LangGraph checkpoint thread (agent
        memory) - see :func:`cre_monitor.graph.builder.delete_conversation`.
        """
        with self._conn() as conn:
            conn.execute("DELETE FROM turns WHERE thread_id = ?", (thread_id,))
            conn.execute("DELETE FROM conversations WHERE thread_id = ?", (thread_id,))

    # -- reads --------------------------------------------------------------
    def list(self, limit: int = 100) -> list[Conversation]:
        """Most recently updated conversations first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM turns t WHERE t.thread_id = c.thread_id) AS turn_count "
                "FROM conversations c ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Conversation(**dict(r)) for r in rows]

    def get(self, thread_id: str) -> Conversation | None:
        """One conversation's metadata, or ``None`` if unknown."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM turns t WHERE t.thread_id = c.thread_id) AS turn_count "
                "FROM conversations c WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return Conversation(**dict(row)) if row else None

    def turns(self, thread_id: str) -> list[Turn]:
        """All turns of a conversation, in order."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM turns WHERE thread_id = ? ORDER BY idx", (thread_id,)).fetchall()
        return [
            Turn(
                idx=r["idx"], created_at=r["created_at"], question=r["question"], answer=r["answer"],
                skills=json.loads(r["skills_json"]), reasoning=r["reasoning"],
                issues=[ValidationIssue(**i) for i in json.loads(r["issues_json"])],
                findings=[SkillFinding(**f) for f in json.loads(r["findings_json"])],
            )
            for r in rows
        ]


def group_by_recency(conversations: list[Conversation], now: datetime | None = None) -> list[tuple[str, list[Conversation]]]:
    """Bucket conversations like modern chat apps: Today, Yesterday, Previous 7 days, Older.

    Input order is preserved within each bucket; empty buckets are omitted.
    """
    now = now or datetime.now()
    today = now.date()
    buckets: dict[str, list[Conversation]] = {"Today": [], "Yesterday": [], "Previous 7 days": [], "Older": []}
    for c in conversations:
        age_days = (today - c.updated_at.date()).days
        label = "Today" if age_days <= 0 else "Yesterday" if age_days == 1 else "Previous 7 days" if age_days <= 7 else "Older"
        buckets[label].append(c)
    return [(label, items) for label, items in buckets.items() if items]


def get_conversation_store() -> ConversationStore:
    """Store at the configured location (``data/conversations.sqlite``)."""
    return ConversationStore(get_settings().conversations_db_path)
