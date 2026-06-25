"""SQLite-backed persistence for chat sessions, turns, and per-user agent memory.

Phase 3 introduces durable chat history so the dashboard can offer a browsable,
resumable conversation list (VS-Code-chat style) and carry lightweight memory
across conversations.  This is a deliberate deviation from the original stateless
stance (constitution Principle VI, amended) and is intentionally local-only: a
single SQLite file under ``data/`` (configurable via ``WEARABLE_CHAT_DB``).

Three tables::

    sessions(id, user_id, title, kind, nudge_id, analysis_date,
             created_at, updated_at)
    turns(id, session_id, role, content, ts)
    memory(id, user_id, kind, content, source_session_id, created_at)

``kind`` on a session is ``"nudge"`` (spawned from a nudge) or ``"free"`` (a chat
the user started manually).  ``kind`` on a memory row is ``"fact"`` (durable
user-stated fact/preference) or ``"summary"`` (one-line recap of a past chat).
Recurring data patterns are computed deterministically on demand and are *not*
stored here (see :mod:`wearable_insights.memory`).
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import CHAT_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    title         TEXT NOT NULL,
    kind          TEXT NOT NULL,
    nudge_id      TEXT,
    analysis_date TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    ts         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    kind              TEXT NOT NULL,
    content           TEXT NOT NULL,
    source_session_id TEXT,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);
CREATE INDEX IF NOT EXISTS idx_memory_user ON memory(user_id, kind, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or CHAT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Create tables if they don't exist.  Safe to call on every startup."""
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


# ── Sessions ──────────────────────────────────────────────────────────────────


def create_session(
    user_id: str,
    *,
    title: str,
    kind: str = "free",
    nudge_id: str | None = None,
    analysis_date: str | None = None,
    db_path: Path | None = None,
) -> str:
    """Insert a new chat session and return its generated id."""
    session_id = uuid.uuid4().hex
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions "
            "(id, user_id, title, kind, nudge_id, analysis_date, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, user_id, title, kind, nudge_id, analysis_date, now, now),
        )
    return session_id


def find_session_by_nudge(
    user_id: str, nudge_id: str, db_path: Path | None = None
) -> dict | None:
    """Return an existing session for this (user, nudge) pair, or None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND nudge_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id, nudge_id),
        ).fetchone()
    return dict(row) if row else None


def list_sessions(user_id: str, db_path: Path | None = None) -> list[dict]:
    """All sessions for a user, most-recently-updated first."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str, db_path: Path | None = None) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def rename_session(session_id: str, title: str, db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), session_id),
        )


def delete_session(session_id: str, db_path: Path | None = None) -> None:
    """Delete a session and its turns (memory rows are kept)."""
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# ── Turns ─────────────────────────────────────────────────────────────────────


def add_turn(
    session_id: str, role: str, content: str, db_path: Path | None = None
) -> None:
    """Append one message to a session and bump the session's updated_at."""
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO turns (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (session_id, role, content, now),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
        )


def get_turns(session_id: str, db_path: Path | None = None) -> list[dict]:
    """Ordered turns for a session as ``{"role", "content"}`` dicts."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT role, content FROM turns WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ── Memory ────────────────────────────────────────────────────────────────────


def add_memory(
    user_id: str,
    kind: str,
    content: str,
    *,
    source_session_id: str | None = None,
    db_path: Path | None = None,
) -> None:
    """Insert a memory row, skipping exact-duplicate content of the same kind."""
    content = content.strip()
    if not content:
        return
    with _connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM memory WHERE user_id = ? AND kind = ? AND content = ? LIMIT 1",
            (user_id, kind, content),
        ).fetchone()
        if exists:
            return
        conn.execute(
            "INSERT INTO memory (user_id, kind, content, source_session_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, kind, content, source_session_id, _now()),
        )


def get_memory(
    user_id: str, kind: str | None = None, db_path: Path | None = None
) -> list[dict]:
    """Memory rows for a user, newest first; optionally filtered by kind."""
    query = "SELECT kind, content, created_at FROM memory WHERE user_id = ?"
    params: list = [user_id]
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    query += " ORDER BY created_at DESC"
    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]
