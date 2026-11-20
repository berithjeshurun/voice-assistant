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
        # Common medium.en mishears for "Chloe"
        "julie",
        "julia",
        "jolie",
        "juli",
        "julié",
        "joey",
        "chuly",
        "chuli",
        "flo",
        "flow",
        "cleo",
        "clio",
        "claire",
        "glory",
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


def resolve_mic_device() -> Optional[int]:
    """Pick a real microphone — never speaker-loopback / Stereo Mix."""
    try:
        import sounddevice as sd
    except Exception:
        return None
    forced = (os.environ.get("AMY_MIC_DEVICE") or "").strip()
    devices = list(sd.query_devices())
    if forced.isdigit():
        idx = int(forced)
        if 0 <= idx < len(devices) and int(devices[idx].get("max_input_channels") or 0) > 0:
            return idx
    skip = ("pc speaker", "stereo mix", "what u hear", "loopback", "wave out")
    # Prefer the stable Realtek mic first — "Digital Microphone" often fails under WDM-KS.
    prefer = ("microphone (realtek", "digital microphone", "microphone")
    named: List[tuple[int, str]] = []
    for i, d in enumerate(devices):
        if int(d.get("max_input_channels") or 0) < 1:
            continue
        name = str(d.get("name") or "")
        low = name.lower()
        if any(s in low for s in skip):
            continue
        if "mapper" in low or "primary sound capture" in low:
            continue
        named.append((i, low))
    if forced:
        fl = forced.lower()
        for i, low in named:
            if fl in low:
                return i
    for needle in prefer:
        for i, low in named:
            if needle in low:
                return i
    return named[0][0] if named else None


def _resample_to_16k(pcm: Any, sample_rate: int) -> Any:
    import numpy as np

    x = np.asarray(pcm, dtype="float32").reshape(-1)
    if sample_rate == 16000 or len(x) < 2:
        return x
    try:
        from scipy.signal import resample_poly

        return resample_poly(x, 16000, int(sample_rate)).astype("float32")
    except Exception:
        n = max(1, int(round(len(x) * 16000 / float(sample_rate))))
        idx = np.linspace(0, len(x) - 1, n)
        return np.interp(idx, np.arange(len(x)), x).astype("float32")


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
        self._rms_floor = _env_float("AMY_WAKE_RMS", 0.012)
        self._silence_s = _env_float("AMY_WAKE_SILENCE_S", 0.40)
        self._min_speech_s = _env_float("AMY_WAKE_MIN_SPEECH_S", 0.35)
        self._max_utt_s = _env_float("AMY_WAKE_MAX_S", 3.2)
        self._debug = _env_bool("AMY_WAKE_DEBUG", False)
        self._mic_device = resolve_mic_device()
        self._capture_rate = int(sample_rate) or 16000

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
        self._calibrate_noise_floor()
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

    def _calibrate_noise_floor(self) -> None:
        """Raise the energy gate above ambient noise so Whisper stops inventing phrases."""
        try:
            import sounddevice as sd
        except Exception:
            return
        device = self._mic_device
        rate = self._pick_capture_rate(sd, device)
        self._capture_rate = rate
        block = max(256, int(rate * 0.05))
        samples: List[float] = []
        try:
            with sd.InputStream(
                device=device,
                samplerate=rate,
                channels=1,
                dtype="float32",
                blocksize=block,
                latency="low",
            ) as stream:
                need = int(rate * 0.8)
                got = 0
                while got < need:
                    data, _ = stream.read(block)
                    if data is None or len(data) == 0:
                        break
                    mono = data[:, 0] if getattr(data, "ndim", 1) > 1 else data
                    boosted = np.clip(mono * self.gain, -1.0, 1.0)
                    samples.append(float((boosted**2).mean() ** 0.5))
                    got += len(boosted)
        except Exception as e:
            self._emit(f"wake noise calibrate: {e}")
            return
        if not samples:
            return
        floor = float(sorted(samples)[len(samples) // 2])  # median
        # Speak must clearly beat ambient; keep a usable minimum.
        gated = max(self._rms_floor, floor * 2.8, floor + 0.02)
        self._rms_floor = min(0.08, gated)
        self._emit(f"wake noise_floor={floor:.4f} gate={self._rms_floor:.4f}")

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
        """Wake-only ASR via Amy GPU STT (filtered + tiny.en)."""
        import numpy as np

        audio = _resample_to_16k(pcm, self._capture_rate)
        audio = np.asarray(audio, dtype="float32").reshape(-1)
        try:
            from amy.host.stt import transcribe

            return str(transcribe(audio, sample_rate=16000, purpose="wake").get("text") or "")
        except Exception:
            from pyhive.core.host.live_audio import transcribe_pcm

            return str(transcribe_pcm(audio, sample_rate=16000).get("text") or "").strip()

    def _pick_capture_rate(self, sd: Any, device: Optional[int]) -> int:
        for sr in (16000, 44100, 48000):
            try:
                with sd.InputStream(
                    device=device,
                    samplerate=sr,
                    channels=1,
                    dtype="float32",
                    blocksize=1024,
                    latency="low",
                ):
                    return sr
            except Exception:
                continue
        return 16000

    def _loop(self) -> None:
        try:
            import sounddevice as sd
        except Exception as e:
            self._emit(f"wake loop deps: {e}")
            return

        device = self._mic_device
        rate = self._pick_capture_rate(sd, device)
        self._capture_rate = rate
        block = max(256, int(rate * (self.block_size / float(self.sample_rate or 16000))))
        try:
            name = sd.query_devices(device)["name"] if device is not None else "default"
        except Exception:
            name = str(device)
        self._emit(f"wake mic device={device} name={name!r} rate={rate} gain={self.gain}")

        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                continue
            try:
                with sd.InputStream(
                    device=device,
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
