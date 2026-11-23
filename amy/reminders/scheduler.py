"""Fires due reminders on a background thread."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, List, Optional

from amy.reminders.store import Reminder, ReminderStore
from amy.reminders.timeparse import next_occurrence

_logger = logging.getLogger(__name__)

# A reminder this late was missed (Amy was off); it fires once with a "missed" note.
MISSED_AFTER_S = 120.0
_IDLE_WAIT_S = 60.0


class ReminderScheduler:
    def __init__(
        self,
        store: ReminderStore,
        on_fire: Callable[[Reminder, bool], None],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.on_fire = on_fire
        self.clock = clock
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> ReminderScheduler:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="amy-reminders", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def poke(self) -> None:
        """Re-check the schedule now (call after adding or cancelling)."""
        self._wake.set()

    def run_due(self) -> List[Reminder]:
        """Fire everything due at ``clock()``; returns what fired."""
        now_ts = self.clock()
        fired: List[Reminder] = []
        for r in self.store.due(now_ts):
            missed = now_ts - r.due_ts > MISSED_AFTER_S
            rule = r.repeat_rule
            nxt: Optional[datetime] = None
            if rule is not None:
                nxt = next_occurrence(r.due, rule, datetime.fromtimestamp(now_ts).astimezone())
            # mark first so a crashing callback can't make it fire forever
            self.store.mark_fired(r.id, next_due=nxt, fired_ts=now_ts)
            try:
                self.on_fire(r, missed)
            except Exception:
                _logger.warning("reminder %s announce failed", r.id, exc_info=True)
            fired.append(r)
        return fired

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_due()
                nxt = self.store.next_due_ts()
            except Exception:
                _logger.error("reminder loop failed", exc_info=True)
                nxt = None
            wait = _IDLE_WAIT_S if nxt is None else max(0.05, min(_IDLE_WAIT_S, nxt - self.clock()))
            self._wake.wait(wait)
            self._wake.clear()
