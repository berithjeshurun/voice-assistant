"""Phrase-gated barge-in — Amy gets to speak; interrupt needs a cue word."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional

import numpy as np

from amy.host.amy_wake import match_wake_phrase, resolve_mic_device

_logger = logging.getLogger(__name__)

# Natural interrupt cues (plus Chloe wake aliases via match_wake_phrase).
_BARGE_CUES = frozenset(
    {
        "wait",
        "hold",
        "hang",
        "stop",
        "enough",
        "quiet",
        "pause",
        "excuse",
        "actually",
        "amy",
        "chloe",
        "julie",
        "julia",
        "jolie",
        "cancel",
        "nevermind",
    }
)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except Exception:
        return default


def _env_bool(name: str, default: bool = True) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def looks_like_barge(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if match_wake_phrase(raw, ["hey chloe", "hi chloe", "okay chloe", "ok chloe", "chloe"]):
        return True
    cleaned = "".join(ch if ch.isalnum() else " " for ch in raw.lower())
    toks = [t for t in cleaned.split() if t]
    if not toks:
        return False
    if toks[:2] == ["never", "mind"]:
        return True
    return any(t in _BARGE_CUES for t in toks[:2])


def install_phrase_barge(vs: Any, log: Optional[Callable[[str], None]] = None) -> None:
    """Replace energy-only barge watch with grace + optional cue-word gate."""

    def _log(msg: str) -> None:
        if log:
            try:
                log(msg)
            except Exception:
                _logger.debug("barge log failed", exc_info=True)

    need_word = _env_bool("AMY_BARGE_NEED_WORD", True)
    grace_s = max(0.4, _env_float("AMY_BARGE_GRACE_S", 1.0))
    need_s = max(0.18, _env_float("AMY_BARGE_NEED_S", 0.28))
    thresh = max(0.05, _env_float("AMY_BARGE_RMS", 0.08))
    gain = max(1.0, _env_float("AMY_MIC_GAIN", _env_float("PYHIVE_MIC_GAIN", 4.0)))

    orig_stop = getattr(vs, "_stop_barge_watch", None)

    def _start_barge_watch() -> None:
        if callable(orig_stop):
            try:
                orig_stop()
            except Exception:
                _logger.debug("barge stop failed", exc_info=True)
        vs._barge_watch_stop = threading.Event()
        vs._barge_tripped = False
        watch_stop: threading.Event = vs._barge_watch_stop

        def _watch() -> None:
            try:
                import sounddevice as sd
            except Exception:
                return
            device = resolve_mic_device()
            rate = 16000
            block = 480
            speech_s = 0.0
            t0 = time.time()
            try:
                with sd.InputStream(
                    device=device,
                    samplerate=rate,
                    channels=1,
                    dtype="float32",
                    blocksize=block,
                    latency="low",
                ) as stream:
                    buf: list[np.ndarray] = []
                    while not watch_stop.is_set() and getattr(vs, "_speaking", False):
                        if getattr(vs, "_cancel", threading.Event()).is_set():
                            break
                        data, _ = stream.read(block)
                        if data is None or len(data) == 0:
                            continue
                        if time.time() - t0 < grace_s:
                            continue
                        mono = data[:, 0] if getattr(data, "ndim", 1) > 1 else data
                        mono = np.clip(mono * gain, -1.0, 1.0).astype("float32")
                        rms = float((mono**2).mean() ** 0.5) if len(mono) else 0.0
                        if rms >= thresh:
                            speech_s += block / float(rate)
                            buf.append(mono.copy())
                            if speech_s < need_s:
                                continue
                            if not need_word:
                                vs.barge_in()
                                _log("barge energy")
                                break
                            # Capture a bit more, then require a cue word.
                            extra = 0.0
                            while extra < 0.55 and not watch_stop.is_set():
                                data2, _ = stream.read(block)
                                if data2 is None or len(data2) == 0:
                                    break
                                m2 = data2[:, 0] if getattr(data2, "ndim", 1) > 1 else data2
                                m2 = np.clip(m2 * gain, -1.0, 1.0).astype("float32")
                                buf.append(m2.copy())
                                extra += block / float(rate)
                            audio = np.concatenate(buf) if buf else None
                            buf = []
                            speech_s = 0.0
                            if audio is None or len(audio) < int(rate * 0.25):
                                continue
                            text = _quick_asr(audio, rate)
                            if looks_like_barge(text):
                                _log(f"barge cue text={text!r}")
                                vs.barge_in()
                                break
                            _log(f"barge ignored text={text!r}")
                        else:
                            speech_s = max(0.0, speech_s - (block / float(rate)) * 0.6)
                            if speech_s <= 0:
                                buf = []
            except Exception:
                _logger.debug("phrase barge watch failed", exc_info=True)

        t = threading.Thread(target=_watch, name="amy-barge-watch", daemon=True)
        vs._barge_watch_thread = t
        t.start()

    vs._start_barge_watch = _start_barge_watch  # type: ignore[method-assign]
    _log(
        f"barge phrase-gate on grace={grace_s:.2f}s rms>={thresh:.3f} "
        f"need_word={need_word}"
    )


def _quick_asr(pcm: np.ndarray, sample_rate: int) -> str:
    try:
        from amy.host.stt import transcribe

        return str(
            transcribe(pcm, sample_rate=sample_rate, purpose="barge").get("text") or ""
        )
    except Exception:
        _logger.debug("barge asr failed", exc_info=True)
        return ""
