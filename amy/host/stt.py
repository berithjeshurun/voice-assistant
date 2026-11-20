"""Amy STT — GPU-first distil-whisper + audio cleanup.

Uses faster-whisper on CUDA (nvidia-* pip wheels supply cublas/cudnn when the
toolkit isn't installed system-wide). Dual models: tiny wake + distil converse.
"""

from __future__ import annotations

import logging
import os
import site
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

_logger = logging.getLogger(__name__)

_MODELS: Dict[str, Any] = {}
_LOCK = threading.Lock()
_PATCHED = False
_CUDA_READY: Optional[bool] = None

_WAKE_PROMPT = "Hey Chloe. Hi Chloe. Okay Chloe."
_TALK_PROMPT = (
    "Hey Chloe. Conversation with Amy, a voice assistant. "
    "Names: Chloe, Amy. Short spoken English."
)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except Exception:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def ensure_cuda_dlls() -> list[str]:
    """Put nvidia-* wheel bin dirs on PATH so ctranslate2 can load cublas."""
    added: list[str] = []
    roots: list[Path] = []
    for sp in list(site.getsitepackages()) + [site.getusersitepackages()]:
        if not sp:
            continue
        p = Path(sp) / "nvidia"
        if p.is_dir():
            roots.append(p)
    for root in roots:
        for bin_dir in root.rglob("bin"):
            if not any(bin_dir.glob("*.dll")):
                continue
            path = str(bin_dir.resolve())
            if path.lower() not in (os.environ.get("PATH") or "").lower():
                os.environ["PATH"] = path + os.pathsep + (os.environ.get("PATH") or "")
            try:
                os.add_dll_directory(path)  # type: ignore[attr-defined]
            except (AttributeError, FileNotFoundError, OSError):
                pass
            added.append(path)
    return added


def converse_model_name() -> str:
    return _env("AMY_STT_MODEL") or _env("PYHIVE_WHISPER_MODEL") or "distil-small.en"


def wake_model_name() -> str:
    # Keep wake on GPU too — tiny.en is instant on RTX.
    return _env("AMY_WAKE_STT_MODEL") or "tiny.en"


def _high_pass(x: np.ndarray, sample_rate: int, cutoff_hz: float = 85.0) -> np.ndarray:
    """1-pole high-pass: y[n] = a * (y[n-1] + x[n] - x[n-1])."""
    rc = 1.0 / (2.0 * np.pi * cutoff_hz)
    dt = 1.0 / float(sample_rate)
    alpha = rc / (rc + dt)
    try:
        from scipy.signal import lfilter

        return lfilter([alpha, -alpha], [1.0, -alpha], x).astype(np.float32)
    except ImportError:
        pass
    y = np.empty_like(x)
    prev_x = 0.0
    prev_y = 0.0
    for i, v in enumerate(x):
        prev_y = alpha * (prev_y + float(v) - prev_x)
        prev_x = float(v)
        y[i] = prev_y
    return y


def preprocess_pcm(
    audio: Any,
    *,
    sample_rate: int = 16000,
    target_rms: float = 0.09,
) -> np.ndarray:
    """High-pass, noise gate, soft normalize — fewer Whisper hallucinations."""
    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(x) < 16:
        return x

    x = x - float(np.mean(x))
    x = _high_pass(x, sample_rate or 16000)

    hop = max(80, int(sample_rate * 0.02))
    if len(x) >= hop * 4:
        frames = len(x) // hop
        body = x[: frames * hop].reshape(frames, hop)
        energies = np.sqrt(np.mean(body**2, axis=1)) + 1e-9
        floor = float(np.percentile(energies, 20))
        gate = max(0.004, floor * 1.8)
        body[energies < gate] *= 0.12

    peak = float(np.max(np.abs(x)) or 0.0)
    rms = float(np.sqrt(np.mean(x**2)) + 1e-9)
    if peak > 0.01 and rms > 0.004:
        gain = min(6.0, max(0.7, target_rms / rms))
        if peak * gain > 0.95:
            gain = 0.95 / peak
        x = x * gain

    return np.clip(x, -1.0, 1.0).astype(np.float32)


def _device_compute() -> Tuple[str, str]:
    """GPU-first. Only fall back to CPU if CUDA load fails later."""
    forced = _env("AMY_STT_DEVICE").lower()
    if forced == "cpu":
        return "cpu", _env("AMY_STT_COMPUTE") or "int8"
    # Default / cuda: prefer GPU
    compute = _env("AMY_STT_COMPUTE") or "float16"
    return "cuda", compute


def cuda_available() -> bool:
    global _CUDA_READY
    if _CUDA_READY is not None:
        return _CUDA_READY
    ensure_cuda_dlls()
    try:
        import ctranslate2 as ct2

        _CUDA_READY = ct2.get_cuda_device_count() > 0
    except Exception:
        _CUDA_READY = False
    return bool(_CUDA_READY)


def get_model(name: str) -> Any:
    key = (name or "").strip() or "distil-small.en"
    with _LOCK:
        if key in _MODELS:
            return _MODELS[key]
        ensure_cuda_dlls()
        from faster_whisper import WhisperModel

        device, compute = _device_compute()
        threads = max(2, _env_int("AMY_STT_THREADS", max(4, (os.cpu_count() or 8) // 2)))
        try:
            model = WhisperModel(
                key,
                device=device,
                compute_type=compute,
                cpu_threads=threads,
                num_workers=1,
            )
        except Exception as e:
            if device != "cpu":
                _logger.warning("STT GPU load failed (%s); retrying CPU", e)
                model = WhisperModel(
                    key,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=threads,
                    num_workers=1,
                )
                device, compute = "cpu", "int8"
            else:
                raise
        _MODELS[key] = model
        _logger.info("stt model=%s device=%s compute=%s", key, device, compute)
        return model


def _clean(text: str) -> str:
    t = " ".join((text or "").split()).strip()
    if not t:
        return ""
    low = t.lower().strip(" .,!?;:\"'")
    junk = {
        "",
        ".",
        "..",
        "...",
        "thanks for watching",
        "thank you for watching",
        "thank you",
        "thanks",
        "subscribe",
        "you",
        "the",
        "a",
        "um",
        "uh",
        "hmm",
        "mm",
        "mhm",
        "i'm sorry",
        "i am sorry",
    }
    if low in junk or len(low) < 2:
        return ""
    return t


def transcribe(
    audio: Any,
    *,
    sample_rate: int = 16000,
    purpose: str = "talk",
    beam_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Transcribe with filtering. purpose: wake | barge | talk."""
    t0 = time.time()
    pcm = preprocess_pcm(audio, sample_rate=sample_rate)
    peak = float(np.max(np.abs(pcm)) or 0.0)
    rms = float(np.sqrt(np.mean(pcm**2)) + 1e-12) if len(pcm) else 0.0
    if len(pcm) < int(sample_rate * 0.18) or peak < 0.012 or rms < 0.0035:
        return {
            "ok": False,
            "text": "",
            "error": "silence",
            "backend": "amy_stt",
            "asr_seconds": time.time() - t0,
            "peak": peak,
            "rms": rms,
        }

    if purpose == "wake":
        model_name = wake_model_name()
        beam = beam_size or _env_int("AMY_WAKE_BEAM", 1)
        prompt = _WAKE_PROMPT
        vad = False
    elif purpose == "barge":
        model_name = wake_model_name()
        beam = 1
        prompt = "Hey Chloe, wait, hold on, stop."
        vad = False
    else:
        model_name = converse_model_name()
        beam = beam_size or _env_int("AMY_STT_BEAM", 2)
        prompt = _TALK_PROMPT
        vad = _env_bool("AMY_STT_VAD", True)

    model = get_model(model_name)
    segments, info = model.transcribe(
        pcm,
        language="en",
        beam_size=max(1, beam),
        best_of=max(1, beam),
        vad_filter=vad,
        vad_parameters=(
            {"min_silence_duration_ms": 280, "speech_pad_ms": 160} if vad else None
        ),
        condition_on_previous_text=False,
        without_timestamps=True,
        initial_prompt=prompt,
        temperature=0.0,
        compression_ratio_threshold=2.4,
        log_prob_threshold=-0.9,
        no_speech_threshold=0.55 if purpose == "talk" else 0.5,
    )
    parts = []
    for s in segments:
        chunk = _clean(s.text or "")
        if not chunk:
            continue
        avg = getattr(s, "avg_logprob", None)
        if avg is not None and float(avg) < -1.05:
            continue
        no_speech = getattr(s, "no_speech_prob", None)
        if no_speech is not None and float(no_speech) > 0.72:
            continue
        parts.append(chunk)
    text = _clean(" ".join(parts))
    return {
        "ok": bool(text),
        "text": text,
        "error": "" if text else "no speech",
        "backend": f"amy_stt:{model_name}",
        "asr_seconds": time.time() - t0,
        "peak": peak,
        "rms": rms,
        "language_probability": float(getattr(info, "language_probability", 0) or 0),
    }


def preload() -> str:
    ensure_cuda_dlls()
    _high_pass(np.zeros(32, dtype=np.float32), 16000)
    talk = converse_model_name()
    wake = wake_model_name()
    get_model(talk)
    if wake != talk:
        try:
            get_model(wake)
        except Exception as e:
            _logger.warning("wake STT preload failed (%s); using talk model", e)
            return f"amy_stt:{talk}(gpu-first)"
    device, compute = _device_compute()
    return f"amy_stt:{talk}+{wake} device={device}/{compute}"


def install_stt_patch() -> str:
    """Route PyHive live_audio STT through Amy's GPU-first filtered pipeline."""
    global _PATCHED
    import pyhive.core.host.live_audio as la

    tag = preload()

    def _transcribe_pcm(audio: Any, *, sample_rate: int = 16000) -> Dict[str, Any]:
        return transcribe(audio, sample_rate=sample_rate, purpose="talk")

    def _get_whisper(model_size: str) -> Any:
        return get_model(model_size or converse_model_name())

    la.transcribe_pcm = _transcribe_pcm  # type: ignore[assignment]
    la._get_whisper = _get_whisper  # type: ignore[assignment]
    la.whisper_model_name = converse_model_name  # type: ignore[assignment]
    la.preload_stt = preload  # type: ignore[assignment]
    _PATCHED = True
    return tag
