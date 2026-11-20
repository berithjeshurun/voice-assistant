"""Wake conversation loop: session cap, chatter filter, stop words, bare-wake first listen."""

from __future__ import annotations

from collections import deque
from typing import Any, List

import pytest

from amy.host.conversation import Conversation, is_followup_request, is_stop
from amy.host.events import EventBus


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class FakeVoice:
    """Each heard item is (text, seconds of listening); each turn costs ``turn_s``."""

    def __init__(self, clock: FakeClock, heard: List[Any], turn_s: float = 5.0) -> None:
        self.clock = clock
        self.heard = deque(heard)
        self.turn_s = turn_s
        self.turns: List[str] = []
        self.spoken: List[str] = []

    def listen_live(self, max_seconds: float = 8.0) -> str:
        if not self.heard:
            self.clock.t += max_seconds
            return ""
        text, secs = self.heard.popleft()
        self.clock.t += secs
        return text

    def turn_from_text(self, text: str) -> str:
        self.turns.append(text)
        self.clock.t += self.turn_s
        return f"answer to {text}"

    def speak(self, text: str, playback: str = "ffplay") -> None:
        self.spoken.append(text)

    def consume_barge(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def _no_gap(monkeypatch):
    monkeypatch.setenv("AMY_POST_SPEAK_GAP_S", "0")
    monkeypatch.setattr("amy.host.conversation.time.sleep", lambda s: None)


def _convo(clock: FakeClock, **kw: Any) -> Conversation:
    kw.setdefault("max_session_s", 180.0)
    return Conversation(EventBus(), listen_max_s=8.0, idle_s=20.0,
                        refresh_env=lambda: None, clock=clock, **kw)


def test_filler_follow_ups_are_ignored():
    clock = FakeClock()
    vs = FakeVoice(clock, [("Yeah.", 1), ("is.", 1), ("Cool.", 1), ("what's the weather", 2), ("bye", 1)])
    _convo(clock).run(vs, "hey chloe open notepad")
    assert vs.turns == ["open notepad", "what's the weather"]
    assert vs.spoken == ["Okay."]


def test_yes_counts_when_amy_asked_a_question():
    assert not is_followup_request("Yeah.", "Done.")
    assert is_followup_request("Yeah.", "Should I open it?")
    assert is_followup_request("louder", "Done.")
    assert is_followup_request("We need a remote box", "")
    assert not is_followup_request("", "?")


def test_session_cap_stops_room_chatter_loop():
    """The 52-minute incident: long turns + people talking nearby kept one wake alive."""
    clock = FakeClock()
    chatter = [(f"I mean we need to talk about thing {i}", 3) for i in range(20)]
    vs = FakeVoice(clock, chatter, turn_s=120.0)
    _convo(clock, max_turns=12).run(vs, "okay chloe what's up")
    assert len(vs.turns) <= 2
    assert clock.t - 1000.0 < 400


def test_bare_wake_listens_then_retries_name_only():
    clock = FakeClock()
    vs = FakeVoice(clock, [("Chloe.", 1), ("set a timer for five minutes", 2), ("", 0)])
    _convo(clock).run(vs, "")
    assert vs.turns == ["set a timer for five minutes"]


def test_bare_wake_silence_runs_nothing():
    clock = FakeClock()
    vs = FakeVoice(clock, [])
    assert _convo(clock).run(vs, "") is None
    assert vs.turns == []


def test_stop_phrases_normalised():
    assert is_stop("Never mind.")
    assert is_stop("Chloe, stop.")
    assert not is_stop("stop the music in the kitchen")
