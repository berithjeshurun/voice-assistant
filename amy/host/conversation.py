"""After the wake word: keep listening and answering until the user goes quiet or says stop."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from amy.host.events import EventBus
from amy.protocol.messages import AssistantState

_logger = logging.getLogger(__name__)

WAKE_ALIASES = ("hey chloe", "hi chloe", "okay chloe", "ok chloe", "chloe")
STOP_PHRASES = frozenset(
    {"bye", "goodbye", "stop", "amy stop", "chloe stop", "chloe, stop", "chloe, stop."}
)


def wake_phrases(primary: str) -> list[str]:
    """The configured phrase first, then the built-in aliases, without duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for p in (primary.lower().strip(), *WAKE_ALIASES):
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def is_stop(text: str) -> bool:
    return (text or "").lower().strip() in STOP_PHRASES


class Conversation:
    """Runs one wake-initiated conversation on a PyHive ``VoiceSession``."""

    def __init__(
        self,
        bus: EventBus,
        *,
        listen_max_s: float,
        idle_s: float,
        refresh_env: Callable[[], None],
        max_turns: int = 10,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.bus = bus
        self.listen_max_s = listen_max_s
        self.idle_s = idle_s
        self.refresh_env = refresh_env
        self.max_turns = max_turns
        self.clock = clock

    def run(self, vs: Any, pending_transcript: str = "") -> Optional[str]:
        from amy.host.amy_wake import match_wake_phrase, strip_wake_from_transcript

        first = ""
        pending = (pending_transcript or "").strip()
        if pending:
            if match_wake_phrase(pending, list(WAKE_ALIASES)):
                first = strip_wake_from_transcript(pending)
            self.bus.set_caption(pending[:420], role="user")

        if not first:
            last = vs.conversation_after_wake(
                listen_seconds=self.listen_max_s,
                idle_seconds=self.idle_s,
                max_turns=12,
            )
            if last:
                self.bus.record_turn("(voice)", str(last))
                _logger.info("amy> %s", last)
            return str(last) if last else None

        # The wake transcript already carried the request: answer it, then keep listening.
        self.refresh_env()
        self.bus.set_state(AssistantState.thinking, detail=first[:80])
        self.bus.set_caption(first[:420], role="user")
        last = self._turn(vs, first, None)
        deadline = self.clock() + self.idle_s
        for _ in range(self.max_turns):
            # Interrupted while speaking: take the new command now.
            if getattr(vs, "consume_barge", None) and vs.consume_barge():
                cancel = getattr(vs, "_cancel", None)
                if cancel is not None:
                    cancel.clear()
                self.bus.set_state(AssistantState.listening, detail="barge")
                text = vs.listen_live(max_seconds=self.listen_max_s)
                if not text:
                    continue
                deadline = self.clock() + self.idle_s
                if is_stop(text):
                    break
                last = self._turn(vs, text, last)
                continue
            remain = max(1.5, deadline - self.clock())
            text = vs.listen_live(max_seconds=min(self.listen_max_s, remain))
            if not text:
                if self.clock() >= deadline:
                    break
                continue
            if is_stop(text):
                try:
                    vs.speak("Okay.", playback="ffplay")
                except Exception:
                    _logger.debug("goodbye speak failed", exc_info=True)
                break
            deadline = self.clock() + self.idle_s
            last = self._turn(vs, text, last)
        return str(last) if last else None

    def _turn(self, vs: Any, text: str, last: Any) -> Any:
        self.bus.set_caption(text[:420], role="user")
        ans = vs.turn_from_text(text) or last
        _logger.info("amy> %s", ans)
        self.bus.record_turn(text, str(ans or ""))
        return ans
