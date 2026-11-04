"""Chat history in SQLite (WAL) — survives restarts, searchable, bounded."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from amy.protocol.messages import ChatMessage

_logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts   REAL    NOT NULL,
    role TEXT    NOT NULL,
    text TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_ts ON messages(ts);
"""


class SqliteHistory:
    """Thread-safe append-only message log with a size cap."""

    def __init__(self, path: Path, *, max_rows: int = 20_000) -> None:
        self.path = Path(path)
        self.max_rows = max_rows
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._writes = 0

    def append(self, msg: ChatMessage) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages(ts, role, text) VALUES (?, ?, ?)",
                (float(msg.ts), msg.role, msg.text),
            )
            self._writes += 1
            if self._writes % 200 == 0:
                self._prune_locked()

    def recent(self, limit: int = 100) -> List[ChatMessage]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, role, text FROM messages ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [ChatMessage(ts=ts, role=role, text=text) for ts, role, text in reversed(rows)]

    def search(self, query: str, limit: int = 50) -> List[ChatMessage]:
        q = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, role, text FROM messages WHERE text LIKE ? ESCAPE '\\' "
                "ORDER BY id DESC LIMIT ?",
                (q, int(limit)),
            ).fetchall()
        return [ChatMessage(ts=ts, role=role, text=text) for ts, role, text in rows]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages")

    def _prune_locked(self) -> None:
        self._conn.execute(
            "DELETE FROM messages WHERE id <= (SELECT MAX(id) FROM messages) - ?",
            (self.max_rows,),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def open_history() -> Optional[SqliteHistory]:
    """The default store (``AMY_HISTORY_DB`` or ``~/.amy/history.db``); None when disabled."""
    if (os.environ.get("AMY_HISTORY") or "1").lower() in ("0", "false", "off", "no"):
        return None
    from amy.server.auth import amy_state_dir

    path = Path(os.environ.get("AMY_HISTORY_DB") or amy_state_dir() / "history.db")
    try:
        return SqliteHistory(path)
    except (sqlite3.Error, OSError):
        _logger.warning("chat history disabled: cannot open %s", path, exc_info=True)
        return None
