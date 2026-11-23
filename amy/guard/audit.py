"""Append-only JSONL audit trail of every agent tool call."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, TextIO

from amy.logs import current_turn_id

_logger = logging.getLogger(__name__)

_MAX_BYTES = 5 * 1024 * 1024


def _clip(v: Any, n: int = 600) -> Any:
    if isinstance(v, str):
        return v if len(v) <= n else v[:n] + "…"
    if isinstance(v, dict):
        return {str(k): _clip(x, n) for k, x in list(v.items())[:40]}
    if isinstance(v, (list, tuple)):
        return [_clip(x, n) for x in list(v)[:40]]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return _clip(repr(v), n)


class AuditLog:
    """Keeps the file open between writes: reopening per call costs ~1 ms on Windows
    (antivirus rescans), which dominated the guard's per-call overhead."""

    def __init__(self, path: Optional[Path] = None) -> None:
        root = Path(os.environ.get("AMY_ROOT") or Path.cwd())
        self.path = Path(path or os.environ.get("AMY_AUDIT_LOG") or root / "logs" / "audit.jsonl")
        self._lock = threading.Lock()
        self._fh: Optional[TextIO] = None
        self._size = 0

    def _open(self) -> TextIO:
        if self._fh is None or self._fh.closed:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a", encoding="utf-8")
            self._size = self._fh.tell()
        return self._fh

    def _rotate(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        rotated = self.path.with_suffix(".jsonl.1")
        if rotated.exists():
            rotated.unlink()
        self.path.rename(rotated)

    def write(self, record: Dict[str, Any]) -> None:
        rec = {"ts": round(time.time(), 3), **_clip(record)}
        tid = current_turn_id()
        if tid:
            rec.setdefault("turn", tid)
        line = json.dumps(rec, ensure_ascii=False, default=str) + "\n"
        with self._lock:
            try:
                fh = self._open()
                if self._size > _MAX_BYTES:
                    self._rotate()
                    fh = self._open()
                fh.write(line)
                fh.flush()
                self._size += len(line.encode("utf-8"))
            except OSError as e:
                self._fh = None
                _logger.error("audit write failed: %s", e)

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
