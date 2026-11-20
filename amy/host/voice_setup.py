"""Build and tune PyHive's VoiceSession for Amy: persona, TTS voice, early speak, warmup."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

from amy.hive_adapter import HiveAdapter
from amy.host.events import EventBus
from amy.host.speak_pulse import SpeakPulse
from amy.protocol.messages import AssistantState

_logger = logging.getLogger(__name__)

Log = Callable[[str], None]


def build_voice_session(
    hive: HiveAdapter,
    *,
    runner: Any,
    on_event: Callable[[Any], None],
    enabled: bool,
) -> Any:
    from pyhive.core.host import VoiceSession

    asst = hive.assistant_config
    svc = hive.bundle_services

    def _a(name: str, default: Any) -> Any:
        return getattr(asst, name, default) if asst is not None else default

    return VoiceSession(
        agent_runner=runner,
        registry=hive.registry,
        enabled=enabled,
        on_event=on_event,
        progressive_ack=bool(_a("progressive_ack", True)),
        ack_timeout_ms=int(_a("ack_timeout_ms", 400) or 400),
        speak_strip_markdown=bool(_a("speak_strip_markdown", True)),
        speak_max_chars=int(_a("speak_max_chars", 420) or 420),
        speak_max_sentences=int(_a("speak_max_sentences", 4) or 4),
        ack_llm=hive.llm,
        memory=hive.memory,
        emitter=hive.emitter,
        before_agent=runner.before_agent,
        speaker_registry=svc.get("speaker_registry"),
        persona_engine=svc.get("persona_engine"),
        require_persona_voice=False,
        require_admin_voice=False,
        require_persona_face=False,
        require_persona_palm=False,
    )


def apply_voice_settings(hive: HiveAdapter, vs: Any, log: Log) -> None:
    """Amy settings (persona preset, TTS voice / style) into the agent and TTS calls."""
    from amy.settings.store import PERSONA_BLOCK_END, PERSONA_BLOCK_START, get_settings_store

    store = get_settings_store()
    store.apply_runtime()
    block = store.persona_prompt_block()
    if block:
        hive.upsert_prompt_block(PERSONA_BLOCK_START, PERSONA_BLOCK_END, block)
    snap = store.get()
    voice_id = str(snap.get("voice_id") or "").strip()
    style = str(snap.get("voice_style") or "natural").strip()
    if voice_id or style:
        studio = _StudioBreaker(log)

        def _piper(text: str, playback: str, voice: str = "") -> Any:
            kw: dict = {"text": text, "playback": playback}
            if voice:
                kw["voice"] = voice
            if style:
                kw["style"] = style
            return vs._call_tool("vce_tts", **kw)

        def _tts_with_settings(text: str, *, playback: str = "ffplay") -> Any:
            backend = vs._tts_backend()
            if backend in ("voicestudio", "voice_studio"):
                if studio.open():
                    kw: dict = {"text": text, "playback": playback, "timeout": studio.timeout_s}
                    if voice_id:
                        kw["voice"] = voice_id
                    t0 = time.monotonic()
                    try:
                        out = vs._call_tool("voicestudio_tts", **kw)
                    except Exception as e:
                        out = {"status": "error", "error": str(e)}
                    ok = isinstance(out, dict) and out.get("status") == "success"
                    studio.record(ok, time.monotonic() - t0)
                    if ok:
                        return out
                # Studio voice names are not Piper voices; use Piper's default.
                return _piper(text, playback)
            return _piper(text, playback, voice_id)

        vs._tts = _tts_with_settings
    log(f"settings voice={voice_id or '-'} style={style} persona={snap.get('persona_preset')}")


class _StudioBreaker:
    """Skip VoiceStudio for a while after it fails or is too slow to talk with."""

    def __init__(self, log: Log) -> None:
        self.log = log
        self.timeout_s = _env_float("AMY_TTS_TIMEOUT_S", 15.0)
        self.slow_s = _env_float("AMY_TTS_SLOW_S", 8.0)
        self.cooldown_s = _env_float("AMY_TTS_COOLDOWN_S", 300.0)
        self._skip_until = 0.0

    def open(self) -> bool:
        return time.monotonic() >= self._skip_until

    def record(self, ok: bool, took_s: float) -> None:
        if ok and took_s < self.slow_s:
            return
        self._skip_until = time.monotonic() + self.cooldown_s
        why = f"slow ({took_s:.1f}s)" if ok else f"failed after {took_s:.1f}s"
        self.log(f"tts voicestudio {why}; using Piper for {self.cooldown_s:.0f}s")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def install_early_speak(hive: HiveAdapter, vs: Any, bus: EventBus, pulse: SpeakPulse) -> None:
    """Speak the first streamed sentence while the agent keeps working."""

    def _early_speak(sentence: str) -> None:
        line = (sentence or "").strip()
        if not line:
            return
        try:
            vs.mark_early_spoke(line)
            bus.set_caption(line[:420], role="speak")
            bus.set_state(AssistantState.speaking, detail="early", audio_level=0.5)
            pulse.start(line)
            vs.speak(line, playback="ffplay")
        except Exception:
            _logger.warning("early speak failed", exc_info=True)

    hive.set_service("voice_early_speak", _early_speak, bundle=True)


def warmup(hive: HiveAdapter, vs: Any, bus: EventBus, log: Log, *, tts: bool) -> None:
    """Load LLM weights and the TTS voice now so the first real turn is not a cold start."""
    llm = hive.llm
    if llm is not None and hasattr(llm, "warmup"):
        try:
            log("warmup llm…")
            llm.warmup(prompt="ok")
            log("warmup llm ok")
        except Exception as e:
            log(f"warmup llm: {e}")
    if tts:
        try:
            log("warmup tts…")
            vs.speak("Ready.", playback="none")
            bus.clear_caption()
            log("warmup tts ok")
        except Exception as e:
            log(f"warmup tts: {e}")
