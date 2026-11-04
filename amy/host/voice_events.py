"""Translate PyHive ``VoiceSession`` events into HUD bus state."""

from __future__ import annotations

import logging
from typing import Any, Callable

from amy.host.events import EventBus
from amy.host.speak_pulse import SpeakPulse
from amy.protocol.messages import AssistantState

_logger = logging.getLogger(__name__)

_PLACEHOLDERS = frozenset({"(listening)", "…", "..."})
_STATE_MAP = (
    ("listening", AssistantState.listening, "listening"),
    ("thinking", AssistantState.thinking, "working"),
    ("idle", AssistantState.idle, "ready"),
)


class VoiceEventMapper:
    def __init__(self, bus: EventBus, pulse: SpeakPulse, log: Callable[[str], None]) -> None:
        self.bus = bus
        self.pulse = pulse
        self.log = log

    def __call__(self, ev: Any) -> None:
        try:
            self.handle(ev)
        except Exception:
            _logger.warning("voice event handling failed", exc_info=True)

    def handle(self, ev: Any) -> None:
        et = str(getattr(ev, "type", "") or "").lower()
        st = str(getattr(getattr(ev, "state", None), "value", "") or "").lower()
        full = (getattr(ev, "text", "") or "").strip()
        meta = getattr(ev, "meta", None) or {}
        bus = self.bus

        if et == "latency":
            self.log(
                f"latency ttfw_ms={meta.get('ttfw_ms')} ack_ms={meta.get('ack_ms')} "
                f"agent_ms={meta.get('agent_ms')} tts_ms={meta.get('tts_ms')} "
                f"first={meta.get('first_audio_kind') or ''}"
            )
            return
        _logger.debug("voice %s state=%s %s", et, st, full[:80])

        if et == "ack":
            if full:
                bus.set_caption(full[:420], role="ack")
            bus.set_state(AssistantState.thinking, detail="bridging reply")
            bus.note_activity("ack", kind="status", detail="bridging reply")
            return
        if et == "reply":
            if full:
                bus.set_caption(full[:420], role="speak")
            return
        if et == "transcript" and full and full not in _PLACEHOLDERS:
            bus.set_caption(full[:420], role="user")
            bus.set_state(AssistantState.listening, detail="transcript", audio_level=0.25)
            return
        if et == "partial" and full and full not in _PLACEHOLDERS:
            bus.set_caption(full[:420], role="user")
            return
        if "speaking" in et or "speaking" in st:
            if full:
                bus.set_caption(full[:420], role="speak")
            bus.set_state(AssistantState.speaking, detail="tts", audio_level=0.55)
            self.pulse.start(full)
            return
        if et in ("spoken", "speak_error") or "spoken" in et:
            self.pulse.stop()
            bus.set_state(AssistantState.idle, detail=et, audio_level=0.0)
            return
        for key, mapped, detail in _STATE_MAP:
            if key in st or key in et:
                self.pulse.stop()
                bus.set_state(
                    mapped,
                    detail=detail,
                    audio_level=0.2 if mapped == AssistantState.listening else 0.0,
                )
                return
