"""Amy wake: mic → energy gate → Whisper STT → fuzzy phrase match + PTT.

No Vosk. Conversational STT and wake spotting both use faster-whisper.
Wake name: Chloe (mishear-tolerant).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

import numpy as np

_logger = logging.getLogger(__name__)


@dataclass
class AmyWakeEvent:
    phrase: str
    transcript: str = ""
    reason: str = "wake"


OnWake = Callable[[AmyWakeEvent], None]

# Whisper often mishears "Chloe" — treat these as the wake-name token.
_WAKE_NAME_TOKENS = frozenset(
    {
        "chloe",
        "chlo",
        "clo",
        "cloe",
        "kloe",
        "khloe",
        "chlow",
        "chloey",
        "chloee",
        "heychloe",
        "hichloe",
        "okaychloe",
    }
)
_WAKE_PREFIXES = frozenset({"hey", "hi", "okay", "ok", "yo", "hello"})
_DEFAULT_PHRASES = ["hey chloe", "hi chloe", "okay chloe", "ok chloe", "chloe"]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except Exception:
        return default


def _norm_tokens(text: str) -> List[str]:
    raw = "".join(
        ch if ch.isalnum() or ch.isspace() else " " for ch in (text or "").lower()
    )
    return [t for t in raw.split() if t]


def match_wake_phrase(text: str, phrases: Sequence[str]) -> Optional[str]:
    """Match configured wake phrases with Chloe mishear tolerance."""
    toks = _norm_tokens(text)
    if not toks:
        return None
    joined = " ".join(toks)

    for p in phrases:
        pl = (p or "").strip().lower()
        if not pl:
            continue
        if joined == pl or joined.startswith(pl + " ") or f" {pl} " in f" {joined} ":
            return pl

    if len(toks) == 1 and toks[0] in _WAKE_NAME_TOKENS:
        return "chloe"
    if len(toks) >= 2 and toks[0] in _WAKE_PREFIXES:
        if toks[1] in _WAKE_NAME_TOKENS:
            return f"{toks[0]} chloe"
        if toks[1].startswith("chlo") or toks[1] in _WAKE_NAME_TOKENS:
            return f"{toks[0]} chloe"
    if toks[0] in _WAKE_PREFIXES:
        for t in toks[1:4]:
            if t in _WAKE_NAME_TOKENS:
                return f"{toks[0]} chloe"
    return None


def strip_wake_from_transcript(text: str) -> str:
    """Remove wake prefix + name; return remaining ask (may be empty)."""
    toks = _norm_tokens(text)
    if not toks:
        return ""
    if not match_wake_phrase(text, _DEFAULT_PHRASES):
        return " ".join(toks)
    i = 0
    if toks[0] in _WAKE_PREFIXES:
        i = 1
    if i < len(toks) and toks[i] in _WAKE_NAME_TOKENS:
        i += 1
    elif i == 0 and toks[0] in _WAKE_NAME_TOKENS:
        i = 1
    return " ".join(toks[i:]).strip()


class AmyWakeDaemon:
    """Exclusive mic loop: energy VAD → Whisper → wake phrase."""

    def __init__(
        self,
        *,
        phrases: Optional[List[str]] = None,
        on_wake: Optional[OnWake] = None,
        on_event: Optional[Callable[[str], None]] = None,
        sample_rate: int = 16000,
        cooldown_ms: int = 1800,
        block_size: int = 1280,
        gain: float = 1.4,
        enabled: bool = True,
    ) -> None:
        self.phrases = [
            p.strip().lower()
            for p in (phrases or list(_DEFAULT_PHRASES))
            if p.strip()
        ]
        self.on_wake = on_wake
        self.on_event = on_event
        self.sample_rate = int(sample_rate) or 16000
        self.cooldown_ms = max(500, int(cooldown_ms))
        self.block_size = int(block_size)
        self.gain = max(0.5, float(gain))
        self.enabled = enabled
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ptt_thread: Any = None
        self._last_wake = 0.0
        self._rms_floor = _env_float("AMY_WAKE_RMS", 0.018)
        self._silence_s = _env_float("AMY_WAKE_SILENCE_S", 0.40)
        self._min_speech_s = _env_float("AMY_WAKE_MIN_SPEECH_S", 0.35)
        self._max_utt_s = _env_float("AMY_WAKE_MAX_S", 3.2)
        self._debug = _env_bool("AMY_WAKE_DEBUG", False)

    def _emit(self, msg: str) -> None:
        if self.on_event:
            try:
                self.on_event(msg)
            except Exception:
                _logger.debug("ignored error", exc_info=True)

    def active_phrases(self) -> List[str]:
        return list(self.phrases) + ["Ctrl+Shift+A (push-to-talk)"]

    def start(self) -> dict:
        if not self.enabled:
            return {"ok": False, "message": "wake disabled"}
        if self._thread and self._thread.is_alive():
            return {"ok": True, "already": True, "phrases": self.phrases}
        self._stop.clear()
        self._paused.clear()
        try:
            from pyhive.core.host.live_audio import preload_stt

            tag = preload_stt()
            self._emit(f"wake stt ready {tag} (whisper, no vosk)")
        except Exception as e:
            self._emit(f"wake whisper preload: {e}")
            return {"ok": False, "message": f"whisper wake unavailable: {e}"}

        self._thread = threading.Thread(
            target=self._loop, name="amy-wake", daemon=True
        )
        self._thread.start()
        self._start_ptt()
        self._emit(
            "wake listening engines=whisper"
            + f" rms>={self._rms_floor:.3f}"
            + " say: "
            + " | ".join(self.phrases[:5])
            + " | or Ctrl+Shift+A"
        )
        return {
            "ok": True,
            "engines": ["whisper"],
            "phrases": self.phrases,
            "oww": False,
        }

    def stop(self) -> None:
        self._stop.set()
        self._paused.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.5)
        self._thread = None
        self._emit("wake stopped")

    def pause(self) -> None:
        self._paused.set()
        time.sleep(0.15)

    def resume(self) -> None:
        self._paused.clear()

    def trigger_wake(self, *, reason: str = "manual") -> None:
        self._fire(
            AmyWakeEvent(
                phrase=self.phrases[0] if self.phrases else "chloe", reason=reason
            )
        )

    def _fire(self, ev: AmyWakeEvent) -> None:
        now = time.time()
        if (now - self._last_wake) * 1000 < self.cooldown_ms:
            return
        self._last_wake = now
        self._paused.set()
        self._emit(
            f"wake_hit phrase={ev.phrase!r} via={ev.reason} text={ev.transcript!r}"
        )
        if self.on_wake:
            try:
                self.on_wake(ev)
            except Exception as e:
                self._emit(f"wake_error: {e}")

    def _start_ptt(self) -> None:
        try:
            from pynput import keyboard
        except Exception:
            self._emit("ptt skipped — pip install pynput  (then Ctrl+Shift+A works)")
            return
        try:
            h = keyboard.GlobalHotKeys(
                {"<ctrl>+<shift>+a": lambda: self.trigger_wake(reason="ptt")}
            )
            h.start()
            self._ptt_thread = h
            self._emit("ptt ready: press Ctrl+Shift+A to talk")
        except Exception as e:
            self._emit(f"ptt error: {e}")

    def _asr(self, pcm: Any) -> str:
        from pyhive.core.host.live_audio import transcribe_pcm

        out = transcribe_pcm(pcm, sample_rate=self.sample_rate)
        return str(out.get("text") or "").strip()

    def _loop(self) -> None:
        try:
            import sounddevice as sd
        except Exception as e:
            self._emit(f"wake loop deps: {e}")
            return

        rate = self.sample_rate
        block = self.block_size
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                continue
            try:
                with sd.InputStream(
                    samplerate=rate,
                    channels=1,
                    dtype="float32",
                    blocksize=block,
                    latency="low",
                ) as stream:
                    self._emit("wake ambient_listening (whisper)")
                    chunks: List[np.ndarray] = []
                    heard = False
                    speech_s = 0.0
                    silence_s = 0.0
                    while not self._stop.is_set() and not self._paused.is_set():
                        data, _ = stream.read(block)
                        if data is None or len(data) == 0:
                            continue
                        mono = data[:, 0] if getattr(data, "ndim", 1) > 1 else data
                        boosted = np.clip(mono * self.gain, -1.0, 1.0).astype(
                            "float32"
                        )
                        rms = (
                            float((boosted**2).mean() ** 0.5) if len(boosted) else 0.0
                        )
                        chunk_s = len(boosted) / float(rate)

                        if rms >= self._rms_floor:
                            heard = True
                            speech_s += chunk_s
                            silence_s = 0.0
                            chunks.append(boosted.copy())
                        elif heard:
                            silence_s += chunk_s
                            chunks.append(boosted.copy())

                        too_long = speech_s >= self._max_utt_s
                        ended = (
                            heard
                            and speech_s >= self._min_speech_s
                            and silence_s >= self._silence_s
                        )
                        if not (ended or too_long):
                            if sum(len(c) for c in chunks) > rate * (
                                self._max_utt_s + 1.0
                            ):
                                chunks = chunks[
                                    -int(rate * self._max_utt_s / block) :
                                ]
                            continue

                        audio = np.concatenate(chunks) if chunks else None
                        chunks = []
                        heard = False
                        speech_s = 0.0
                        silence_s = 0.0
                        if audio is None or len(audio) < int(rate * 0.25):
                            continue

                        try:
                            text = self._asr(audio)
                        except Exception as e:
                            self._emit(f"wake asr: {e}")
                            continue
                        if not text:
                            continue
                        peak = float(np.max(np.abs(audio)) or 0.0)
                        self._emit(f"wake hearing peak={peak:.3f} text={text!r}")

                        hit = match_wake_phrase(text, self.phrases)
                        if hit:
                            self._fire(
                                AmyWakeEvent(
                                    phrase=hit,
                                    transcript=text,
                                    reason="whisper",
                                )
                            )
                            break
            except Exception as e:
                self._emit(f"wake loop: {e}")
                time.sleep(0.4)


__all__ = [
    "AmyWakeDaemon",
    "AmyWakeEvent",
    "match_wake_phrase",
    "strip_wake_from_transcript",
]
