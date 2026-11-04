"""Amy STT shim — delegates to rewritten Hive live_audio."""

from __future__ import annotations

from typing import Any, Callable, Optional

from pyhive.core.host.live_audio import (
    listen_utterance,
    live_audio_backend,
    preload_stt,
    vosk_model_name,
    whisper_model_name,
)

PartialCb = Callable[[str], None]


def configured_stt_backend() -> str:
    return live_audio_backend()


def configured_stt_model() -> str:
    be = live_audio_backend()
    if be in ("faster_whisper", "whisper", "fw", "auto"):
        return whisper_model_name()
    return vosk_model_name()


class LiveListenResult:
    def __init__(self, **kwargs: Any) -> None:
        self.ok = bool(kwargs.get("ok"))
        self.text = str(kwargs.get("text") or "")
        self.partial = str(kwargs.get("partial") or "")
        self.seconds = float(kwargs.get("seconds") or 0)
        self.error = str(kwargs.get("error") or "")
        self.model = str(kwargs.get("model") or "")
        self.backend = str(kwargs.get("backend") or "")


def live_listen(
    *,
    sample_rate: int = 16000,
    model: str = "",
    max_seconds: float = 8.0,
    min_speech_seconds: float = 0.15,
    silence_seconds: float = 0.38,
    energy_threshold: float = 0.005,
    block_ms: int = 30,
    gain: float = 2.5,
    on_partial: Optional[PartialCb] = None,
) -> LiveListenResult:
    out = listen_utterance(
        sample_rate=sample_rate,
        max_seconds=max_seconds,
        silence_seconds=silence_seconds,
        on_partial=on_partial,
    )
    return LiveListenResult(
        ok=out.get("ok"),
        text=out.get("text"),
        seconds=out.get("seconds"),
        error=out.get("error"),
        backend=out.get("backend"),
        model=model or configured_stt_model(),
    )


# Re-export for amy_wake (vosk model loader)
def _vosk_model(name: str = "vosk-sm") -> Any:
    from pyhive.core.host.live_audio import _get_vosk

    return _get_vosk(name)


__all__ = [
    "LiveListenResult",
    "live_listen",
    "configured_stt_model",
    "configured_stt_backend",
    "preload_stt",
    "_vosk_model",
]
