"""SQLite-backed reminders and timers (survive restarts)."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from amy.reminders.timeparse import Repeat, describe_when

MAX_PENDING = 200
MAX_TEXT = 300

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'reminder',
    due_ts REAL NOT NULL,
    repeat TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_ts REAL NOT NULL,
    fired_count INTEGER NOT NULL DEFAULT 0,
    last_fired_ts REAL,
    source TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders(status, due_ts);
"""


class ReminderLimit(RuntimeError):
    """Too many pending reminders."""


@dataclass
class Reminder:
    id: int
    text: str
    kind: str
    due_ts: float
    repeat: str
    status: str
    created_ts: float
    fired_count: int = 0
    last_fired_ts: Optional[float] = None
    source: str = ""

    @property
    def due(self) -> datetime:
        return datetime.fromtimestamp(self.due_ts).astimezone()

    @property
    def repeat_rule(self) -> Optional[Repeat]:
        return Repeat.from_spec(self.repeat)

    def as_dict(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        d = asdict(self)
        rule = self.repeat_rule
        d["due_iso"] = self.due.isoformat(timespec="minutes")
        d["when"] = describe_when(self.due, now)
        d["repeat_text"] = rule.describe() if rule else ""
        return d


def _clean_text(text: str) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        raise ValueError("reminder text is empty")
    return text[:MAX_TEXT]


class ReminderStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            try:
                self._db.close()
            except sqlite3.ProgrammingError:
                pass

    def _row(self, r: sqlite3.Row) -> Reminder:
        return Reminder(**{k: r[k] for k in r.keys()})

    def add(
        self,
        text: str,
        due: datetime,
        *,
        kind: str = "reminder",
        repeat: Optional[Repeat] = None,
        source: str = "",
    ) -> Reminder:
        clean = _clean_text(text)
        with self._lock:
            (pending,) = self._db.execute(
                "SELECT COUNT(*) FROM reminders WHERE status='pending'"
            ).fetchone()
            if pending >= MAX_PENDING:
                raise ReminderLimit(f"too many pending reminders (max {MAX_PENDING})")
            cur = self._db.execute(
                "INSERT INTO reminders(text, kind, due_ts, repeat, created_ts, source)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (clean, kind, due.timestamp(), repeat.spec() if repeat else "", time.time(), source),
            )
            row = self._db.execute("SELECT * FROM reminders WHERE id=?", (cur.lastrowid,)).fetchone()
        return self._row(row)

    def get(self, rid: int) -> Optional[Reminder]:
        with self._lock:
            row = self._db.execute("SELECT * FROM reminders WHERE id=?", (int(rid),)).fetchone()
        return self._row(row) if row else None

    def pending(self, *, limit: int = 100) -> List[Reminder]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM reminders WHERE status='pending' ORDER BY due_ts LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [self._row(r) for r in rows]

    def due(self, now_ts: float) -> List[Reminder]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM reminders WHERE status='pending' AND due_ts <= ? ORDER BY due_ts",
                (now_ts,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def next_due_ts(self) -> Optional[float]:
        with self._lock:
            row = self._db.execute(
                "SELECT MIN(due_ts) FROM reminders WHERE status='pending'"
            ).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def cancel(self, rid: int) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE reminders SET status='cancelled' WHERE id=? AND status='pending'", (int(rid),)
            )
        return cur.rowcount > 0

    def find(self, query: str) -> List[Reminder]:
        """Pending reminders whose text contains ``query`` (case-insensitive)."""
        q = "%" + str(query or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM reminders WHERE status='pending' AND text LIKE ? ESCAPE '\\'"
                " ORDER BY due_ts",
                (q,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def mark_fired(self, rid: int, *, next_due: Optional[datetime], fired_ts: float) -> None:
        with self._lock:
            if next_due is None:
                self._db.execute(
                    "UPDATE reminders SET status='done', fired_count=fired_count+1, last_fired_ts=?"
                    " WHERE id=?",
                    (fired_ts, int(rid)),
                )
            else:
                self._db.execute(
                    "UPDATE reminders SET due_ts=?, fired_count=fired_count+1, last_fired_ts=?"
                    " WHERE id=?",
                    (next_due.timestamp(), fired_ts, int(rid)),
                )
