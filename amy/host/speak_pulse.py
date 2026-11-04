"""Drive the orb's audio level while TTS plays, so the particles surge with speech."""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Optional

from amy.host.events import EventBus
from amy.protocol.messages import AssistantState

_logger = logging.getLogger(__name__)


def pulse_level(elapsed: float, duration: float) -> float:
    """Spectrum-ish envelope (bass / mid / treble mix) with fade in and out, in [0.14, 1]."""
    progress = elapsed / duration if duration > 0 else 1.0
    bass = 0.55 + 0.45 * math.sin(elapsed * 7.2)
    mid = 0.4 + 0.6 * abs(math.sin(elapsed * 14.8 + 0.7))
    treble = 0.3 + 0.7 * abs(math.sin(elapsed * 26.5 + 1.9))
    base = 0.25 * bass + 0.4 * mid + 0.35 * treble
    if progress < 0.08:
        base *= progress / 0.08
    elif progress > 0.85:
        base *= max(0.0, (1.0 - progress) / 0.15)
    return max(0.14, min(1.0, base))


def speech_duration(text: str) -> float:
    """~140 wpm ≈ 2.3 words/s; clamp so short acks still pulse briefly."""
    words = max(1, len((text or "").split()))
    return min(45.0, max(0.9, words / 2.3))


class SpeakPulse:
    def __init__(self, bus: EventBus, *, tick_s: float = 0.05) -> None:
        self.bus = bus
        self.tick_s = tick_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self, text: str = "") -> None:
        self.stop(reset_level=False)
        duration = speech_duration(text)
        stop = threading.Event()

        def _run() -> None:
            t0 = time.time()
            while not stop.is_set():
                elapsed = time.time() - t0
                if elapsed >= duration:
                    break
                try:
                    self.bus.set_state(
                        AssistantState.speaking,
                        detail="tts_pulse",
                        audio_level=pulse_level(elapsed, duration),
                    )
                except Exception:
                    _logger.debug("pulse update failed", exc_info=True)
                    break
                stop.wait(self.tick_s)
            if not stop.is_set():
                try:
                    self.bus.set_state(AssistantState.speaking, detail="tts_tail", audio_level=0.15)
                except Exception:
                    _logger.debug("pulse tail failed", exc_info=True)

        t = threading.Thread(target=_run, name="amy-speak-pulse", daemon=True)
        with self._lock:
            self._stop, self._thread = stop, t
        t.start()

    def stop(self, *, reset_level: bool = True) -> None:
        with self._lock:
            self._stop.set()
            t, self._thread = self._thread, None
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=0.4)
        if reset_level:
            try:
                self.bus.set_state(self.bus.snapshot().state, audio_level=0.0)
            except Exception:
                _logger.debug("pulse reset failed", exc_info=True)
