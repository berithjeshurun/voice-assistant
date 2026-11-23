"""Proactive announcements (reminders, model switches) that wait for a quiet moment."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from amy.host.events import EventBus
from amy.protocol.messages import AssistantState

_logger = logging.getLogger(__name__)


@dataclass
class Announcement:
    text: str
    title: str = ""
    kind: str = "info"
    speak: bool = True
    created: float = 0.0


class Announcer:
    """Shows each announcement on the HUD at once and speaks it when Amy is not busy."""

    def __init__(
        self,
        bus: EventBus,
        *,
        speak: Optional[Callable[[str], None]] = None,
        is_busy: Callable[[], bool] = lambda: False,
        max_wait_s: float = 180.0,
        poll_s: float = 1.0,
    ) -> None:
        self.bus = bus
        self.speak = speak
        self.is_busy = is_busy
        self.max_wait_s = max_wait_s
        self.poll_s = poll_s
        self._q: queue.Queue[Optional[Announcement]] = queue.Queue(maxsize=50)
        self._thread: Optional[threading.Thread] = None
        self.spoken: list[str] = []

    def start(self) -> Announcer:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="amy-announce", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def announce(self, text: str, *, title: str = "", kind: str = "info", speak: bool = True) -> None:
        a = Announcement(text=text, title=title or text, kind=kind, speak=speak, created=time.time())
        try:
            self.bus.note_activity(a.title[:48], kind=kind, detail=text[:80])
        except Exception:
            _logger.debug("announce activity failed", exc_info=True)
        try:
            from amy.workers.alerts import get_alert_bus

            get_alert_bus().post(kind=kind, title=a.title, detail=text, severity=2,
                                 dedupe_key=f"{kind}:{text}:{int(a.created)}")
        except Exception:
            _logger.debug("announce alert failed", exc_info=True)
        try:
            self._q.put_nowait(a)
        except queue.Full:
            _logger.warning("announcement queue full; dropped %r", text[:60])

    def _loop(self) -> None:
        while True:
            a = self._q.get()
            if a is None:
                return
            if not a.speak or self.speak is None:
                continue
            deadline = a.created + self.max_wait_s
            while self.is_busy() and time.time() < deadline:
                time.sleep(self.poll_s)
            if self.is_busy():
                _logger.info("announcement not spoken (Amy stayed busy): %s", a.text[:80])
                continue
            try:
                self.bus.set_caption(a.text[:420], role="status")
                self.bus.set_state(AssistantState.speaking, detail="announce")
                self.speak(a.text)
                self.spoken.append(a.text)
            except Exception:
                _logger.warning("announcement speech failed", exc_info=True)
            finally:
                self.bus.set_state(AssistantState.idle, detail="ready")
