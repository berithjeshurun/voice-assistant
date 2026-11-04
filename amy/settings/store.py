"""Persist Amy settings under HiveSTEAM data or ~/.amy."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from amy.settings.presets import (
    CLEARANCE_LABELS,
    CLEARANCE_ROLES,
    INTEGRATION_CATALOG,
    PERSONA_PRESETS,
    VOICE_STYLES,
    persona_preset,
)

_logger = logging.getLogger(__name__)

PERSONA_BLOCK_START = "\n\nPERSONA PRESET ("
PERSONA_BLOCK_END = "\n[/PERSONA]"


def _settings_path() -> Path:
    home = (os.environ.get("PYHIVE_HOME") or "").strip()
    if home:
        root = Path(home) / "data" / "amy"
    else:
        root = Path.home() / ".amy"
    root.mkdir(parents=True, exist_ok=True)
    return root / "settings.json"


_DEFAULT: Dict[str, Any] = {
    "voice_id": "en_US-amy-medium",
    "voice_style": "natural",
    "persona_preset": "warm",
    "clearance_role": "user",
    "clearance_label": "internal",
    "integrations_enabled": [],
}


class SettingsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = dict(_DEFAULT)
        self._on_change: Optional[Callable[[Dict[str, Any]], None]] = None
        self.load()

    def bind(self, on_change: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self._on_change = on_change

    def load(self) -> Dict[str, Any]:
        path = _settings_path()
        with self._lock:
            if path.is_file():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        self._data = {**_DEFAULT, **raw}
                except Exception:
                    self._data = dict(_DEFAULT)
            return dict(self._data)

    def save(self) -> None:
        path = _settings_path()
        with self._lock:
            path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def get(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def update(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = dict(self._data)
            if "voice_id" in patch and patch["voice_id"] is not None:
                data["voice_id"] = str(patch["voice_id"]).strip()
            if "voice_style" in patch and patch["voice_style"] is not None:
                style = str(patch["voice_style"]).strip().lower()
                if style in VOICE_STYLES:
                    data["voice_style"] = style
            if "persona_preset" in patch and patch["persona_preset"] is not None:
                pid = str(patch["persona_preset"]).strip().lower()
                if any(p["id"] == pid for p in PERSONA_PRESETS):
                    data["persona_preset"] = pid
            if "clearance_role" in patch and patch["clearance_role"] is not None:
                role = str(patch["clearance_role"]).strip().lower()
                if role in CLEARANCE_ROLES:
                    data["clearance_role"] = role
            if "clearance_label" in patch and patch["clearance_label"] is not None:
                lab = str(patch["clearance_label"]).strip().lower()
                if lab in CLEARANCE_LABELS:
                    data["clearance_label"] = lab
            if "integrations_enabled" in patch and isinstance(
                patch["integrations_enabled"], list
            ):
                data["integrations_enabled"] = [
                    str(x).strip() for x in patch["integrations_enabled"] if str(x).strip()
                ]
            self._data = data
        self.save()
        snap = self.get()
        self.apply_runtime(snap)
        if self._on_change:
            try:
                self._on_change(snap)
            except Exception:
                _logger.debug("ignored error", exc_info=True)
        return snap

    def apply_runtime(self, snap: Optional[Dict[str, Any]] = None) -> None:
        """Push voice/persona into env + optional agent prompt."""
        data = snap or self.get()
        voice = str(data.get("voice_id") or "").strip()
        style = str(data.get("voice_style") or "natural").strip()
        if voice:
            os.environ["AMY_TTS_VOICE"] = voice
            # Short alias for Piper (folder name or short token)
            short = voice.split("-")[1] if voice.count("-") >= 1 else voice
            os.environ["PYHIVE_TTS_VOICE"] = short or voice
        os.environ["AMY_TTS_STYLE"] = style
        preset = persona_preset(str(data.get("persona_preset") or "warm"))
        os.environ["AMY_PERSONA_PRESET"] = preset["id"]
        os.environ["AMY_PERSONA_PROMPT"] = preset.get("prompt") or ""

    def persona_prompt_block(self) -> str:
        data = self.get()
        preset = persona_preset(str(data.get("persona_preset") or "warm"))
        return (
            f"{PERSONA_BLOCK_START}{preset['id']}): {preset.get('prompt') or ''}\n"
            f"Clearance role={data.get('clearance_role')} label={data.get('clearance_label')}."
            f"{PERSONA_BLOCK_END}"
        )

    def options(self) -> Dict[str, Any]:
        voices: List[Dict[str, Any]] = []
        styles = list(VOICE_STYLES)
        try:
            from hivesteam.external.service_vce import vce_list

            raw = vce_list()
            data = raw.get("data") if isinstance(raw, dict) else {}
            if isinstance(data, dict):
                voices = list(data.get("tts_voices") or [])
                if data.get("tts_styles"):
                    styles = list(data.get("tts_styles") or styles)
        except Exception:
            _logger.debug("ignored error", exc_info=True)
        return {
            "voice_presets": voices,
            "voice_styles": styles,
            "persona_presets": PERSONA_PRESETS,
            "clearance_roles": CLEARANCE_ROLES,
            "clearance_labels": CLEARANCE_LABELS,
            "integrations": INTEGRATION_CATALOG,
            "settings": self.get(),
            "path": str(_settings_path()),
        }


_store: Optional[SettingsStore] = None
_slock = threading.Lock()


def get_settings_store() -> SettingsStore:
    global _store
    with _slock:
        if _store is None:
            _store = SettingsStore()
            _store.apply_runtime()
        return _store
