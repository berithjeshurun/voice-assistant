"""After the wake word: keep listening and answering until the user goes quiet or says stop."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional

from amy.host.events import EventBus
from amy.protocol.messages import AssistantState

_logger = logging.getLogger(__name__)


def _post_speak_gap() -> None:
    """Let TTS finish / room settle before the next listen."""
    try:
        gap = float(os.environ.get("AMY_POST_SPEAK_GAP_S") or 0.55)
    except Exception:
        gap = 0.55
    if gap > 0:
        time.sleep(max(0.15, min(2.0, gap)))

WAKE_ALIASES = ("hey chloe", "hi chloe", "okay chloe", "ok chloe", "chloe")
STOP_PHRASES = frozenset(
    {"bye", "goodbye", "stop", "amy stop", "chloe stop", "chloe, stop", "chloe, stop.",
     "that's all", "thats all", "never mind", "nevermind", "cancel"}
)

# Follow-ups made only of these words are room chatter / Whisper fragments, not requests.
_FILLER = frozenset({
    "yeah", "yes", "yep", "yup", "no", "nope", "nah", "ok", "okay", "cool", "right", "sure",
    "fine", "alright", "hmm", "huh", "uh", "um", "oh", "ah", "mhm", "wow", "nice", "great",
    "good", "so", "well", "is", "and", "but", "or", "like", "the", "a", "it", "that", "this",
    "what", "hey", "hi", "hello", "thanks", "thank", "you", "i", "we", "me", "look", "see",
    "wait", "hold", "on", "go", "ahead", "just", "maybe", "really", "exactly", "anyway",
})
_ANSWER_WORDS = frozenset({"yes", "yeah", "yep", "yup", "no", "nope", "nah", "ok", "okay",
                           "sure", "fine", "alright", "go", "ahead"})


def _env_s(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def _words(text: str) -> list[str]:
    return "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in (text or "").lower()).split()


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
    t = (text or "").lower().strip()
    return t in STOP_PHRASES or " ".join(_words(t)) in STOP_PHRASES


def is_followup_request(text: str, last_reply: Any = "") -> bool:
    """A follow-up worth a turn: not just filler, unless it answers Amy's question."""
    words = _words(text)
    if not words:
        return False
    if any(w not in _FILLER for w in words):
        return True
    asked = str(last_reply or "").rstrip().endswith("?")
    return asked and any(w in _ANSWER_WORDS for w in words)


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
        max_session_s: Optional[float] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.bus = bus
        self.listen_max_s = listen_max_s
        self.idle_s = idle_s
        self.refresh_env = refresh_env
        self.max_turns = max_turns
        # No new turn starts this long after the wake word; say the wake word again.
        self.max_session_s = (
            max_session_s if max_session_s is not None else _env_s("AMY_CONVO_MAX_S", 180.0)
        )
        self.clock = clock

    def run(self, vs: Any, pending_transcript: str = "") -> Optional[str]:
        from amy.host.amy_wake import match_wake_phrase, strip_wake_from_transcript

        started = self.clock()
        first = ""
        pending = (pending_transcript or "").strip()
        if pending:
            if match_wake_phrase(pending, list(WAKE_ALIASES)):
                first = strip_wake_from_transcript(pending)
            self.bus.set_caption(pending[:420], role="user")

        if not first:
            first = self._listen_first(vs, match_wake_phrase, strip_wake_from_transcript)
            if not first or is_stop(first):
                return None

        self.refresh_env()
        self.bus.set_state(AssistantState.thinking, detail=first[:80])
        self.bus.set_caption(first[:420], role="user")
        last = self._turn(vs, first, None)
        _post_speak_gap()
        deadline = self.clock() + self.idle_s
        for _ in range(self.max_turns):
            if self._expired(started):
                break
            # Interrupted while speaking: take the new command now.
            if getattr(vs, "consume_barge", None) and vs.consume_barge():
                cancel = getattr(vs, "_cancel", None)
                if cancel is not None:
                    cancel.clear()
                self.bus.set_state(AssistantState.listening, detail="barge")
                text = vs.listen_live(max_seconds=self.listen_max_s)
                if not text:
                    continue
                if is_stop(text):
                    break
                if not self._accept(text, last, started):
                    continue
                deadline = self.clock() + self.idle_s
                last = self._turn(vs, text, last)
                _post_speak_gap()
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
            if not self._accept(text, last, started):
                if self.clock() >= deadline:
                    break
                continue
            deadline = self.clock() + self.idle_s
            last = self._turn(vs, text, last)
            _post_speak_gap()
        return str(last) if last else None

    def _listen_first(self, vs: Any, match_wake: Callable, strip_wake: Callable) -> str:
        """Bare wake word: the request is the next utterance (one retry if it was only the name)."""
        for _ in range(2):
            text = (vs.listen_live(max_seconds=self.listen_max_s) or "").strip()
            if not text:
                return ""
            ask = strip_wake(text) if match_wake(text, list(WAKE_ALIASES)) else text
            if ask:
                return ask
        return ""

    def _expired(self, started: float) -> bool:
        if self.max_session_s > 0 and self.clock() - started >= self.max_session_s:
            _logger.info("conversation ended: %.0fs session limit", self.max_session_s)
            return True
        return False

    def _accept(self, text: str, last: Any, started: float) -> bool:
        if self._expired(started):
            return False
        if is_followup_request(text, last):
            return True
        _logger.info("conversation ignored follow-up %r", text[:80])
        return False

    def _turn(self, vs: Any, text: str, last: Any) -> Any:
        self.bus.set_caption(text[:420], role="user")
        ans = vs.turn_from_text(text) or last
        _logger.info("amy> %s", ans)
        self.bus.record_turn(text, str(ans or ""))
        return ans
