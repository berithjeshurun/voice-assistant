"""Amy ambient host — thin product wrapper over the PyHive live voice stack.

``start()`` is a readable sequence of steps; the work lives in focused modules:

* :mod:`amy.host.tool_surface` — product config, tools, hive delegate, safety guard
* :mod:`amy.host.turns`        — one agent turn (serialized across voice and HUD)
* :mod:`amy.host.voice_setup`  — VoiceSession, persona / TTS settings, warmup
* :mod:`amy.host.voice_events` — voice events → HUD state
* :mod:`amy.host.conversation` — wake → listen / answer loop
* :mod:`amy.host.background`   — env awareness, alerts, metrics, idle supervisor
* :mod:`amy.host.speak_pulse`  — orb audio level while speaking
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from amy.branding import ASSISTANT_NAME, DEFAULT_WAKE_PHRASE
from amy.errors import HostBusy, HostNotStarted
from amy.hive_adapter import HiveAdapter
from amy.host.background import (
    attach_alert_bus,
    start_env_awareness,
    start_idle_supervisor,
    start_metric_watch,
    stop_quietly,
)
from amy.host.conversation import Conversation, wake_phrases
from amy.host.events import EventBus
from amy.host.speak_pulse import SpeakPulse
from amy.host.tool_surface import apply_product_config, install_guard, setup_tools
from amy.host.turns import TurnRunner
from amy.host.voice_events import VoiceEventMapper
from amy.host.voice_setup import (
    apply_voice_settings,
    build_voice_session,
    install_early_speak,
    warmup,
)
from amy.logs import turn_context
from amy.protocol.messages import AssistantState

_logger = logging.getLogger(__name__)

# Product defaults for the PyHive live path (env still wins).
_PRODUCT_ENV = {
    "PYHIVE_STT_BACKEND": "faster_whisper",
    "PYHIVE_WHISPER_MODEL": "medium.en",
    "PYHIVE_DISABLE_SKILL_INJECT": "1",
    "PYHIVE_SILENCE_S": "0.55",
    "PYHIVE_MIC_GAIN": "1.4",
    "PYHIVE_ENERGY_THRESH": "0.018",
    "AMY_WAKE_OWW": "0",
    # Voice is headless — never block on stdin [y/N]; the Amy guard does approvals.
    "PYHIVE_APPROVE": "1",
}


class AmbientHost:
    """Owns wake + conversation; STT/TTS/agent live in PyHive."""

    def __init__(
        self,
        *,
        bus: Optional[EventBus] = None,
        profile: str = "ambient",
        cwd: Optional[Path] = None,
        model: Optional[str] = None,
        wake_phrase: Optional[str] = None,
        force_voice: bool = False,
        max_steps: int = 14,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.bus = bus or EventBus()
        self.profile = profile
        self.cwd = Path(cwd or os.getcwd()).resolve()
        self.model = model
        self.wake_phrase = (
            wake_phrase or os.environ.get("AMY_WAKE_PHRASE") or DEFAULT_WAKE_PHRASE
        )
        self.force_voice = force_voice
        self.max_steps = max_steps
        self._log = on_log or self.bus.log

        self._shell: Any = None
        self._hive: Optional[HiveAdapter] = None
        self._vs: Any = None
        self._daemon: Any = None
        self._runner: Optional[TurnRunner] = None
        self._idle_stop = threading.Event()
        self._idle_thread: Optional[threading.Thread] = None
        self._wake_busy = threading.Lock()
        self._started = False
        self._voice_ok = False
        self._wake_ok = False
        self._listen_max_s = 8.0
        self._convo_idle_s = 20.0
        self._pending_wake_transcript = ""
        self._pulse = SpeakPulse(self.bus)
        self._env: Any = None
        self._home_label = ""
        self._home_tz = ""
        self._guard: Any = None
        self._turn_source = "voice"

    # --- public state ----------------------------------------------------------------

    @property
    def voice_ok(self) -> bool:
        return self._voice_ok

    @property
    def wake_ok(self) -> bool:
        return self._wake_ok

    @property
    def started(self) -> bool:
        return self._started

    @property
    def shell(self) -> Any:
        return self._shell

    @property
    def hive(self) -> Optional[HiveAdapter]:
        return self._hive

    @property
    def guard(self) -> Any:
        return self._guard

    # --- start-up ----------------------------------------------------------------------

    def start(self) -> AmbientHost:
        if self._started:
            return self
        for k, v in _PRODUCT_ENV.items():
            os.environ.setdefault(k, v)
        os.environ["PYHIVE_HITL"] = "0"

        from pyhive.core.hive_config import configured_model_spec
        from pyhive.core.host import AssistantShell, voice_available

        self._preload_stt()
        model = self.model or configured_model_spec(
            explicit=None, profile=self.profile, prefer_profile=True
        )
        self._probe_voice(voice_available)

        shell = AssistantShell(
            cwd=self.cwd,
            profile=self.profile,
            mode="ask",
            model=model,
            max_steps=self.max_steps,
            hitl=False,
        ).start()
        self._shell = shell
        hive = self._hive = HiveAdapter(shell)

        try:
            home = apply_product_config(hive, self.bus, self._log)
            self._home_label, self._home_tz = home.label, home.tz
        except Exception as e:
            self._log(f"product config: {e}")
            _logger.warning("product config failed", exc_info=True)
        try:
            setup_tools(hive, self.bus, self._log)
        except Exception as e:
            self._log(f"tools restrict: {e}")
            _logger.error("tool setup failed", exc_info=True)

        approver = self._voice_approve if (self.force_voice or self._voice_ok) else None
        self._guard = install_guard(hive, self.bus, self._log, voice_approver=approver)

        hive.disable_hitl()
        amb = hive.ambient_config
        self.wake_phrase = str(
            self.wake_phrase or getattr(amb, "wake_phrase", None) or DEFAULT_WAKE_PHRASE
        )
        listen = float((getattr(amb, "listen_seconds", None) if amb else None) or 8)
        self._listen_max_s = max(4.0, listen)

        self._runner = TurnRunner(
            hive,
            self.bus,
            guard=lambda: self._guard,
            source=lambda: self._turn_source,
            hive_config=hive.hive_config,
        )
        vs = self._vs = build_voice_session(
            hive,
            runner=self._runner,
            on_event=VoiceEventMapper(self.bus, self._pulse, self._log),
            enabled=self._voice_ok or self.force_voice,
        )
        try:
            apply_voice_settings(hive, vs, self._log)
        except Exception as e:
            self._log(f"settings apply: {e}")
            _logger.warning("settings apply failed", exc_info=True)
        install_early_speak(hive, vs, self.bus, self._pulse)
        warmup(hive, vs, self.bus, self._log, tts=self._voice_ok or self.force_voice)

        self._start_background(hive, amb)
        self._start_wake(amb)

        stt_tag = (
            f"{os.environ.get('PYHIVE_STT_BACKEND', 'faster_whisper')}:"
            f"{os.environ.get('PYHIVE_WHISPER_MODEL', 'medium.en')}"
        )
        self._log(
            f"ambient ready name={ASSISTANT_NAME} profile={self.profile} "
            f"model={model} stt={stt_tag} voice_ok={self._voice_ok}"
        )
        self.bus.set_state(AssistantState.idle, detail="ready")
        self._started = True
        return self

    def _preload_stt(self) -> None:
        from pyhive.core.host.live_audio import preload_stt

        model_name = (
            os.environ.get("PYHIVE_WHISPER_MODEL")
            or os.environ.get("AMY_WHISPER_MODEL")
            or "medium.en"
        )
        self._log(f"stt loading {model_name} (first run may download ~1.5GB from HuggingFace — wait)")
        self.bus.set_state(AssistantState.thinking, detail=f"stt:{model_name}")
        self.bus.note_activity("speech model", kind="status", detail=f"loading {model_name}")
        try:
            self._log(f"stt ready {preload_stt()}")
        except Exception as e:
            self._log(f"stt preload failed ({e}); falling back to small.en")
            os.environ["PYHIVE_WHISPER_MODEL"] = "small.en"
            os.environ["AMY_WHISPER_MODEL"] = "small.en"
            try:
                self._log(f"stt ready {preload_stt()} (fallback)")
            except Exception as e2:
                self._log(f"stt preload: {e2}")
                _logger.error("speech-to-text unavailable", exc_info=True)

    def _probe_voice(self, voice_available: Callable[[], dict]) -> None:
        probe = voice_available()
        self._voice_ok = bool(probe.get("ok"))
        if not self._voice_ok:
            self._log(probe.get("message") or "voice unavailable")
            if not self.force_voice:
                self._log("hint: pass --force for text-only ambient")

    def _start_background(self, hive: HiveAdapter, amb: Any) -> None:
        try:
            self._env = start_env_awareness(
                hive, self.bus, home_label=self._home_label, home_tz=self._home_tz
            )
            self._log("env awareness on")
        except Exception as e:
            self._log(f"env awareness: {e}")
        try:
            attach_alert_bus(self.bus)
            self._log("alert bus on")
        except Exception as e:
            self._log(f"alert bus: {e}")
        start_metric_watch(self._idle_stop)
        self._idle_thread = start_idle_supervisor(
            hive, self._idle_stop, ambient_cfg=amb, log=self._log
        )

    def _start_wake(self, amb: Any) -> None:
        from amy.host.amy_wake import AmyWakeDaemon

        cooldown = int((getattr(amb, "cooldown_ms", None) if amb else None) or 800)

        def _on_wake(ev: Any) -> None:
            if not self._wake_busy.acquire(blocking=False):
                return
            self._pending_wake_transcript = getattr(ev, "transcript", "") or ""
            threading.Thread(target=self._handle_wake, name="amy-convo", daemon=True).start()

        daemon = AmyWakeDaemon(
            phrases=wake_phrases(self.wake_phrase),
            on_wake=_on_wake,
            on_event=self._log,
            cooldown_ms=max(cooldown, 1600),
            gain=float(os.environ.get("AMY_MIC_GAIN") or os.environ.get("PYHIVE_MIC_GAIN") or 1.4),
            enabled=True,
        )
        started = daemon.start()
        self._daemon = daemon
        self._wake_ok = bool(started.get("ok"))
        if self._wake_ok:
            self._log("WAKE: whisper hey chloe / chloe | Ctrl+Shift+A — then keep talking")
        else:
            self._log(started.get("message") or "wake failed")

    # --- voice approvals ----------------------------------------------------------------

    def _voice_approve(self, summary: str) -> Optional[bool]:
        """Ask the person at the mic to confirm a guarded action."""
        from amy.guard import parse_yes_no

        vs = self._vs
        if vs is None:
            return None
        strict = bool(self._guard and self._guard.cfg.strict)
        word = "confirm" if strict else "yes"
        prompt = f"I need your OK first. {summary}. Say {word} to go ahead, or no to cancel."
        try:
            self.bus.set_state(AssistantState.speaking, detail="approval")
            vs.speak(prompt, playback="ffplay")
            self.bus.set_state(AssistantState.needs_approval, detail="approval")
            heard = vs.listen_live(max_seconds=6.0) or ""
        except Exception as e:
            self._log(f"voice approval: {e}")
            return None
        if heard:
            self.bus.set_caption(heard[:200], role="user")
        return parse_yes_no(heard, strict=strict)

    # --- conversation ----------------------------------------------------------------------

    def _refresh_env(self) -> None:
        if self._env is not None:
            try:
                self._env.refresh()
            except Exception:
                _logger.debug("env refresh failed", exc_info=True)

    def _handle_wake(self) -> None:
        """Pause wake → conversation (live STT) → resume."""
        from amy.host.amy_wake import AmyWakeDaemon

        d = self._daemon
        try:
            self.bus.set_state(AssistantState.listening, detail="convo")
            self._log(f"wake → hive conversation name={ASSISTANT_NAME}")
            if isinstance(d, AmyWakeDaemon):
                d.pause()
            if self._vs is None:
                self.bus.set_state(AssistantState.error, detail="no voice session")
                return
            pending, self._pending_wake_transcript = self._pending_wake_transcript, ""
            with turn_context():
                Conversation(
                    self.bus,
                    listen_max_s=self._listen_max_s,
                    idle_s=self._convo_idle_s,
                    refresh_env=self._refresh_env,
                ).run(self._vs, pending)
        except Exception as e:
            self._log(f"wake_turn: {e}")
            _logger.error("conversation failed", exc_info=True)
            self.bus.set_state(AssistantState.error, detail=str(e))
        finally:
            self._pulse.stop()
            try:
                if isinstance(d, AmyWakeDaemon):
                    d.resume()
            except Exception as e:
                self._log(f"wake resume: {e}")
            self.bus.set_state(AssistantState.idle, detail="convo_end", audio_level=0.0)
            try:
                self._wake_busy.release()
            except RuntimeError:
                pass

    def turn_text(self, text: str) -> str:
        """One typed turn from the HUD / console. Raises :class:`HostBusy` mid-turn."""
        text = (text or "").strip()
        if not text:
            return ""
        if not self._started or self._vs is None:
            raise HostNotStarted("AmbientHost not started")
        if self._runner is not None and self._runner.busy:
            raise HostBusy("Amy is still working on the previous request")
        self._refresh_env()
        self.bus.set_state(AssistantState.thinking, detail="text")
        self.bus.set_caption(text[:420], role="user")
        self.bus.clear_cards()
        self._turn_source = "text"
        try:
            with turn_context():
                reply = str(self._vs.turn_from_text(text) or "")
            from amy.host.hud_cards import cards_from_turn

            cards = cards_from_turn(reply)
            if cards:
                self.bus.set_cards(cards)
            self.bus.record_turn(text, reply)
            return reply
        except Exception as e:
            self.bus.set_state(AssistantState.error, detail=str(e))
            raise
        finally:
            self._turn_source = "voice"

    # --- controls ------------------------------------------------------------------------------

    def apply_persona(self, block: str) -> bool:
        """Swap the live agent's persona block (Settings → persona preset)."""
        from amy.settings.store import PERSONA_BLOCK_END, PERSONA_BLOCK_START

        if self._hive is None or not block:
            return False
        return self._hive.upsert_prompt_block(PERSONA_BLOCK_START, PERSONA_BLOCK_END, block)

    def trigger_wake(self, reason: str = "api") -> None:
        if not self._started or self._daemon is None:
            self._log(f"wake ignored (host still starting): {reason}")
            return
        self._daemon.trigger_wake(reason=reason)

    def barge_in(self) -> None:
        self._pulse.stop()
        if self._guard is not None:
            self._guard.hard_stop()
        if self._vs is not None:
            self._vs.barge_in()

    def set_ui_state(self, state: AssistantState, *, detail: str = "") -> None:
        if state != AssistantState.speaking:
            self._pulse.stop()
        self.bus.set_state(state, detail=detail or "ui")

    def stop(self) -> None:
        self._idle_stop.set()
        stop_quietly(self._env, "env awareness")
        self._pulse.stop()
        stop_quietly(self._daemon, "wake daemon")
        self._started = False
        self.bus.set_state(AssistantState.idle, detail="stopped")
        self._log("stopped")

    def run_forever(self, *, console: bool = False) -> int:
        self.start()
        if not console:
            self._log("headless — Ctrl+C to stop")
            stop = threading.Event()

            def _sig(*_a: object) -> None:
                stop.set()

            import signal

            signal.signal(signal.SIGINT, _sig)
            try:
                signal.signal(signal.SIGTERM, _sig)
            except (ValueError, OSError):
                pass
            try:
                while not stop.wait(0.5):
                    pass
            finally:
                self.stop()
            return 0

        self._log("console — /wake /stop /exit")
        try:
            while True:
                try:
                    line = input("you> ").strip()
                except (EOFError, KeyboardInterrupt):
                    self._log("")
                    break
                if not line or line in {"/exit", "/quit", ":q"}:
                    break
                if line in {"/wake"}:
                    self.trigger_wake(reason="console")
                    continue
                if line in {"/stop", "/barge"}:
                    self.barge_in()
                    continue
                try:
                    ans = self.turn_text(line)
                except HostBusy as e:
                    ans = f"({e})"
                print(f"amy> {ans}", flush=True)
        finally:
            self.stop()
        return 0
