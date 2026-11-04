"""Rate-limited alert bus — notify the brain without spam."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

_logger = logging.getLogger(__name__)


@dataclass
class Alert:
    id: str
    kind: str  # suspicious | metric | update | vision | local_app
    title: str
    detail: str = ""
    severity: int = 1  # 1..5
    dedupe_key: str = ""
    ts: float = field(default_factory=time.time)
    acknowledged: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AlertBus:
    def __init__(
        self,
        *,
        cooldown_s: float = 120.0,
        max_per_hour: int = 12,
        keep: int = 40,
        on_emit: Optional[Callable[[Alert], None]] = None,
    ) -> None:
        self.cooldown_s = max(5.0, float(cooldown_s))
        self.max_per_hour = max(1, int(max_per_hour))
        self.keep = max(5, int(keep))
        self.on_emit = on_emit
        self._lock = threading.Lock()
        self._items: List[Alert] = []
        self._last_key: Dict[str, float] = {}
        self._hour_ts: List[float] = []
        self._seq = 0

    def post(
        self,
        *,
        kind: str,
        title: str,
        detail: str = "",
        severity: int = 1,
        dedupe_key: str = "",
    ) -> Optional[Alert]:
        kind = (kind or "info").strip() or "info"
        title = (title or "").strip()[:120]
        if not title:
            return None
        key = (dedupe_key or f"{kind}:{title}").strip().lower()
        now = time.time()
        with self._lock:
            last = self._last_key.get(key, 0.0)
            if now - last < self.cooldown_s:
                return None
            self._hour_ts = [t for t in self._hour_ts if now - t < 3600.0]
            if len(self._hour_ts) >= self.max_per_hour:
                return None
            self._seq += 1
            alert = Alert(
                id=f"a{self._seq}",
                kind=kind,
                title=title,
                detail=(detail or "").strip()[:240],
                severity=max(1, min(5, int(severity))),
                dedupe_key=key,
                ts=now,
            )
            self._last_key[key] = now
            self._hour_ts.append(now)
            self._items.insert(0, alert)
            self._items = self._items[: self.keep]
        if self.on_emit:
            try:
                self.on_emit(alert)
            except Exception:
                _logger.debug("ignored error", exc_info=True)
        # High severity → optional Scout glance (best-effort, never blocks).
        if alert.severity >= 4:
            try:
                self._nudge_hive(alert)
            except Exception:
                _logger.debug("ignored error", exc_info=True)
        return alert

    def _nudge_hive(self, alert: Alert) -> None:
        # Lazy: ambient may bind a callback later via services; keep soft.
        cb = getattr(self, "on_hive_nudge", None)
        if callable(cb):
            cb(alert)

    def list(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        lim = max(1, min(100, int(limit)))
        with self._lock:
            return [a.as_dict() for a in self._items[:lim]]

    def ack(self, alert_id: str) -> bool:
        with self._lock:
            for a in self._items:
                if a.id == alert_id:
                    a.acknowledged = True
                    return True
        return False


_bus: Optional[AlertBus] = None
_bus_lock = threading.Lock()


def get_alert_bus() -> AlertBus:
    global _bus
    with _bus_lock:
        if _bus is None:
            _bus = AlertBus()
        return _bus
