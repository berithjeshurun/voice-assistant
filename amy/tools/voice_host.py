"""Host-only voice tools (STT/TTS) — never pruned from the Amy allowlist."""

from __future__ import annotations

import logging
from typing import Any, List, Sequence

_logger = logging.getLogger(__name__)

# Kept even when agent tools are restricted to OS / Bambu / slicer.
VOICE_HOST_ALLOWLIST: Sequence[str] = (
    "vce_tts",
    "vce_stt",
    "vce_tts_play",
    "vce_status",
    "vce_list",
    "voicestudio_tts",
    "voicestudio_status",
    "voicestudio_voices",
    "openwhispr_transcribe",
)


def ensure_voice_host_tools(registry: Any) -> List[str]:
    """Register Piper/VCE (+ VoiceStudio if present) so speak/listen work."""
    added: List[str] = []
    specs: list[tuple[Any, str, str]] = []
    try:
        from hivesteam.external import service_vce as vce

        for name in ("vce_tts", "vce_stt", "vce_tts_play", "vce_status", "vce_list"):
            fn = getattr(vce, name, None)
            if callable(fn):
                specs.append((fn, name, "amy_voice"))
    except Exception:
        _logger.debug("ignored error", exc_info=True)
    try:
        from hivesteam.external import service_voicestudio as vs

        for name in ("voicestudio_tts", "voicestudio_status", "voicestudio_voices"):
            fn = getattr(vs, name, None)
            if callable(fn):
                specs.append((fn, name, "amy_voice"))
    except Exception:
        _logger.debug("ignored error", exc_info=True)

    for fn, name, module in specs:
        try:
            existing = getattr(registry, "_tools", {}) or {}
            if name in existing:
                continue
            registry.register(
                fn,
                name=name,
                description=(fn.__doc__ or name).strip().split("\n")[0][:200],
                module=module,
                overwrite=False,
            )
            added.append(name)
        except Exception:
            try:
                registry.register(
                    fn, name=name, description=name, module=module, overwrite=True
                )
                added.append(name)
            except Exception:
                continue
    return added
