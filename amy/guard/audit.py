"""Append-only JSONL audit trail of every agent tool call."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

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
    def __init__(self, path: Optional[Path] = None) -> None:
        root = Path(os.environ.get("AMY_ROOT") or Path.cwd())
        self.path = Path(path or os.environ.get("AMY_AUDIT_LOG") or root / "logs" / "audit.jsonl")
        self._lock = threading.Lock()

    def write(self, record: Dict[str, Any]) -> None:
        rec = {"ts": round(time.time(), 3), **_clip(record)}
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.is_file() and self.path.stat().st_size > _MAX_BYTES:
                    rotated = self.path.with_suffix(".jsonl.1")
                    if rotated.exists():
                        rotated.unlink()
                    self.path.rename(rotated)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as e:
                print(f"# amy audit write failed: {e}", flush=True)
