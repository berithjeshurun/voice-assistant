"""Guard settings from ``amy.guard`` in hive.yaml (+ AMY_LOCKDOWN env)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_TOOL_CAPS: Dict[str, int] = {
    "os_power": 1,
    "os_process_kill": 3,
    "run_powershell": 6,
    "run_shell": 6,
    "bambu_control": 2,
    "smartpanels_set_room": 6,
    "hive_delegate": 3,
    "browse_url": 4,
    "os_open_app": 4,
    "play_youtube": 2,
    "slicer_open": 2,
}


@dataclass
class GuardConfig:
    enabled: bool = True
    mode: str = "standard"  # standard | strict
    lockdown: bool = False
    approval_timeout_s: float = 25.0
    voice_confirm: bool = True
    allow_shell: bool = True
    read_roots: List[Path] = field(default_factory=list)
    fetch_allow_private: bool = False
    max_tool_calls_per_turn: int = 16
    max_tool_calls_per_minute: int = 40
    max_denials_per_turn: int = 3
    tool_caps: Dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_TOOL_CAPS))
    tool_overrides: Dict[str, str] = field(default_factory=dict)
    # Upper bound for any ``timeout``-style argument a tool accepts (shell, fetch, …).
    exec_timeout_s: float = 60.0
    # Tool output longer than this is truncated before the model sees it.
    max_result_chars: int = 24_000

    @property
    def strict(self) -> bool:
        return self.mode == "strict"


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def load_guard_config(raw_yaml: Optional[Dict[str, Any]] = None) -> GuardConfig:
    if raw_yaml is None:
        raw_yaml = {}
        cfg_path = os.environ.get("HIVE_CONFIG") or ""
        if cfg_path and Path(cfg_path).is_file():
            try:
                import yaml

                raw_yaml = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8")) or {}
            except Exception as e:
                logging.getLogger(__name__).error(
                    "guard config read failed (%s); using strict defaults", e
                )
                return GuardConfig(mode="strict")
    g = ((raw_yaml.get("amy") or {}).get("guard") or {}) if isinstance(raw_yaml, dict) else {}

    cfg = GuardConfig()
    cfg.enabled = bool(g.get("enabled", True))
    mode = str(g.get("mode") or "standard").strip().lower()
    cfg.mode = mode if mode in ("standard", "strict") else "strict"
    cfg.lockdown = bool(g.get("lockdown", False)) or _truthy(os.environ.get("AMY_LOCKDOWN", ""))
    cfg.approval_timeout_s = float(g.get("approval_timeout_s") or 25)
    cfg.voice_confirm = bool(g.get("voice_confirm", True))
    cfg.allow_shell = bool(g.get("allow_shell", True))
    cfg.fetch_allow_private = bool(g.get("fetch_allow_private", False))
    cfg.max_tool_calls_per_turn = int(g.get("max_tool_calls_per_turn") or 16)
    cfg.max_tool_calls_per_minute = int(g.get("max_tool_calls_per_minute") or 40)
    cfg.max_denials_per_turn = int(g.get("max_denials_per_turn") or 3)
    cfg.exec_timeout_s = float(g.get("exec_timeout_s") or 60)
    cfg.max_result_chars = int(g.get("max_result_chars") or 24_000)

    root = Path(os.environ.get("AMY_ROOT") or Path.cwd()).resolve()
    roots = [root]
    for r in g.get("read_roots") or []:
        try:
            roots.append(Path(os.path.expandvars(os.path.expanduser(str(r)))).resolve())
        except Exception:
            continue
    cfg.read_roots = roots

    for name, cap in (g.get("tool_caps") or {}).items():
        try:
            cfg.tool_caps[str(name)] = int(cap)
        except Exception:
            continue
    for name, verdict in (g.get("tools") or {}).items():
        v = str(verdict).strip().lower()
        if v in ("allow", "confirm", "deny"):
            cfg.tool_overrides[str(name)] = v
    return cfg
