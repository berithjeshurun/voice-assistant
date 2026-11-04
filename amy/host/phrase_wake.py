"""Live Vosk phrase wake — catches 'hey chloe' without a custom ONNX model."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from amy.host.live_stt import _vosk_model, configured_stt_model

_logger = logging.getLogger(__name__)


@dataclass
class PhraseWakeEvent:
    phrase: str
    transcript: str
    reason: str = "vosk_phrase"


OnWake = Callable[[PhraseWakeEvent], None]


class PhraseWakeDaemon:
    """
    Continuous mic → Vosk partials. Fires when a wake phrase appears.
    Stops cleanly so live STT can take the mic (no WAV, no OWW required).
    """

    def __init__(
        self,
        *,
        phrases: Optional[List[str]] = None,
        on_wake: Optional[OnWake] = None,
        on_event: Optional[Callable[[str], None]] = None,
        sample_rate: int = 16000,
        cooldown_ms: int = 1500,
        model: str = "",
        enabled: bool = True,
    ) -> None:
        self.phrases = [p.strip().lower() for p in (phrases or ["hey chloe"]) if p.strip()]
        self.on_wake = on_wake
        self.on_event = on_event
        self.sample_rate = int(sample_rate) or 16000
        self.cooldown_ms = max(200, int(cooldown_ms))
        self.model_name = model or configured_stt_model()
        self.enabled = enabled
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_wake = 0.0
        self._paused = threading.Event()
        self._paused.clear()

    def _emit(self, msg: str) -> None:
        if self.on_event:
            try:
                self.on_event(msg)
            except Exception:
                _logger.debug("ignored error", exc_info=True)

    def active_phrases(self) -> List[str]:
        return list(self.phrases)

    def start(self) -> dict:
        if not self.enabled:
            return {"ok": False, "message": "phrase wake disabled"}
        try:
            _vosk_model(self.model_name)
        except Exception as e:
            return {"ok": False, "message": f"vosk wake unavailable: {e}"}
        self._stop.clear()
        self._paused.clear()
        self._thread = threading.Thread(
            target=self._loop, name="amy-phrase-wake", daemon=True
        )
        self._thread.start()
        self._emit(f"phrase_wake listening: {' | '.join(self.phrases)}")
        return {"ok": True, "engine": "vosk_phrase", "phrases": self.phrases}

    def stop(self) -> None:
        self._stop.set()
        self._paused.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.5)
        self._thread = None
        self._emit("phrase_wake stopped")

    def pause(self) -> None:
        """Release mic for live STT without tearing down the thread state."""
        self._paused.set()
        # Brief settle so InputStream can close
        time.sleep(0.15)

    def resume(self) -> None:
        self._paused.clear()

    def trigger_wake(self, *, reason: str = "manual") -> None:
        self._fire(PhraseWakeEvent(phrase=self.phrases[0], transcript="", reason=reason))

    def _fire(self, ev: PhraseWakeEvent) -> None:
        now = time.time()
        if (now - self._last_wake) * 1000 < self.cooldown_ms:
            return
        self._last_wake = now
        self._emit(f"wake_hit phrase={ev.phrase!r} via={ev.reason}")
        if self.on_wake:
            try:
                self.on_wake(ev)
            except Exception as e:
                self._emit(f"wake_error: {e}")

    def _match(self, text: str) -> Optional[str]:
        t = " ".join((text or "").lower().split())
        if not t:
            return None
        for p in self.phrases:
            if t == p or t.startswith(p + " ") or f" {p} " in f" {t} ":
                return p
        return None

    def _loop(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
            from vosk import KaldiRecognizer
        except Exception as e:
            self._emit(f"phrase_wake error: {e}")
            return

        rate = self.sample_rate
        block = max(256, int(rate * 0.08))
        try:
            model = _vosk_model(self.model_name)
        except Exception as e:
            self._emit(f"phrase_wake model: {e}")
            return

        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                continue
            try:
                rec = KaldiRecognizer(model, rate)
                rec.SetWords(True)
                with sd.InputStream(
                    samplerate=rate,
                    channels=1,
                    dtype="float32",
                    blocksize=block,
                ) as stream:
                    self._emit("phrase_wake ambient_listening")
                    while not self._stop.is_set() and not self._paused.is_set():
                        data, _ = stream.read(block)
                        if data is None or len(data) == 0:
                            continue
                        mono = data[:, 0] if getattr(data, "ndim", 1) > 1 else data
                        pcm = (
                            (np.clip(mono, -1.0, 1.0) * 32767.0)
                            .astype("int16")
                            .tobytes()
                        )
                        text = ""
                        if rec.AcceptWaveform(pcm):
                            try:
                                text = (
                                    json.loads(rec.Result() or "{}").get("text") or ""
                                ).strip()
                            except Exception:
                                text = ""
                        else:
                            try:
                                text = (
                                    json.loads(rec.PartialResult() or "{}").get(
                                        "partial"
                                    )
                                    or ""
                                ).strip()
                            except Exception:
                                text = ""
                        hit = self._match(text)
                        if hit:
                            # Pause before callback so mic is free for live STT
                            self._paused.set()
                            self._fire(
                                PhraseWakeEvent(
                                    phrase=hit, transcript=text, reason="vosk_phrase"
                                )
                            )
                            break
            except Exception as e:
                self._emit(f"phrase_wake loop: {e}")
                time.sleep(0.5)


__all__ = ["PhraseWakeDaemon", "PhraseWakeEvent"]
