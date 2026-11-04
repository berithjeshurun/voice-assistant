"""Goal-scoped tool packs — browse catalog, activate without polluting core."""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Sequence, Set

_logger = logging.getLogger(__name__)

# Pack definitions: category → tool names (registered elsewhere).
DEFAULT_PACKS: Dict[str, List[str]] = {
    "core": [
        "tools_catalog",
        "tools_activate",
        "os_active_window",
        "hive_delegate",
    ],
    "os": [
        "os_volume",
        "os_mute",
        "os_brightness",
        "os_toggle",
        "os_open_app",
        "os_list_apps",
        "os_power",
        "os_process_list",
        "os_process_kill",
        "os_active_window",
    ],
    "registry": [
        "reg_query",
        "reg_list",
        "reg_set",
        "reg_delete",
        "reg_search",
        "reg_analyze_app",
    ],
    "web": [
        "browse_url",
        "play_youtube",
        "web_search",
        "web_fetch",
    ],
    "files": [
        "read_file",
        "list_dir",
        "run_shell",
        "run_powershell",
    ],
    "local_apps": [
        "local_app_list",
        "local_app_status",
        "local_app_open",
        "local_app_http",
    ],
    "vision": [
        "vision_status",
        "vision_list_people",
        "vision_enroll",
        "vision_recognize",
    ],
    "updates": [
        "updates_check",
        "updates_status",
    ],
    "bambu": [
        "bambu_status",
        "bambu_control",
        "slicer_find",
        "slicer_open",
    ],
    "hive": [
        "hive_delegate",
    ],
}

# Slim ambient default — packs activate on demand.
CORE_ALLOWLIST: Sequence[str] = tuple(
    dict.fromkeys(
        [
            *DEFAULT_PACKS["core"],
            *DEFAULT_PACKS["os"],  # day-to-day OS still available
            *DEFAULT_PACKS["registry"],  # Windows registry query/set/analyze
            *DEFAULT_PACKS["web"][:2],  # browse + youtube; search via pack
            "web_search",
            "web_fetch",
            "read_file",
            "list_dir",
            "bambu_status",
            "bambu_control",
            "slicer_find",
            "slicer_open",
        ]
    )
)


class ToolCatalog:
    def __init__(self, packs: Optional[Dict[str, List[str]]] = None) -> None:
        self.packs: Dict[str, List[str]] = {
            k: list(v) for k, v in (packs or DEFAULT_PACKS).items()
        }
        self._active: Set[str] = set(CORE_ALLOWLIST)
        self._lock = threading.Lock()
        self._registry: Any = None
        self._on_change: Any = None

    def bind(self, registry: Any, *, on_change: Any = None) -> None:
        self._registry = registry
        self._on_change = on_change

    def catalog(self, category: str = "") -> Dict[str, Any]:
        cat = (category or "").strip().lower()
        with self._lock:
            if cat:
                tools = self.packs.get(cat) or []
                return {
                    "ok": True,
                    "category": cat,
                    "tools": tools,
                    "active": sorted(t for t in tools if t in self._active),
                }
            return {
                "ok": True,
                "categories": {
                    k: {"tools": v, "count": len(v)} for k, v in sorted(self.packs.items())
                },
                "active_packs": sorted(
                    k
                    for k, tools in self.packs.items()
                    if tools and all(t in self._active for t in tools[:1]) and any(
                        t in self._active for t in tools
                    )
                ),
                "active_tools": sorted(self._active),
            }

    def allowlist(self) -> List[str]:
        with self._lock:
            return sorted(self._active)

    def activate(self, pack: str, *, goal: str = "") -> Dict[str, Any]:
        name = (pack or "").strip().lower()
        if not name:
            return {"ok": False, "error": "pack required"}
        tools = self.packs.get(name)
        if not tools:
            return {
                "ok": False,
                "error": f"unknown pack {name!r}",
                "known": sorted(self.packs.keys()),
            }
        with self._lock:
            before = set(self._active)
            self._active.update(tools)
            added = sorted(self._active - before)
        self._reprune()
        return {
            "ok": True,
            "pack": name,
            "goal": (goal or "").strip()[:120],
            "added": added,
            "active_tools": self.allowlist(),
        }

    def deactivate(self, pack: str) -> Dict[str, Any]:
        name = (pack or "").strip().lower()
        tools = self.packs.get(name) or []
        core = set(DEFAULT_PACKS.get("core") or [])
        with self._lock:
            for t in tools:
                if t not in core:
                    self._active.discard(t)
        self._reprune()
        return {"ok": True, "pack": name, "active_tools": self.allowlist()}

    def _reprune(self) -> None:
        if self._registry is None:
            return
        try:
            from amy.tools import prune_registry_to_allowlist

            prune_registry_to_allowlist(self._registry, allowlist=self.allowlist())
        except Exception:
            _logger.debug("ignored error", exc_info=True)
        if self._on_change:
            try:
                self._on_change(self.allowlist())
            except Exception:
                _logger.debug("ignored error", exc_info=True)


_catalog: Optional[ToolCatalog] = None
_clock = threading.Lock()


def get_tool_catalog(packs: Optional[Dict[str, List[str]]] = None) -> ToolCatalog:
    global _catalog
    with _clock:
        if _catalog is None:
            _catalog = ToolCatalog(packs=packs)
        elif packs:
            for k, v in packs.items():
                _catalog.packs[k] = list(v)
        return _catalog


def tools_catalog(category: str = "") -> Dict[str, Any]:
    """List tool packs / tools. Use before activating a specialized pack."""
    return get_tool_catalog().catalog(category)


def tools_activate(pack: str = "", goal: str = "") -> Dict[str, Any]:
    """Activate a tool pack for this session (e.g. vision, updates, local_apps)."""
    return get_tool_catalog().activate(pack, goal=goal)


def register(registry: Any) -> List[str]:
    out: List[str] = []
    for fn, desc in (
        (tools_catalog, "Browse Amy tool packs/categories without loading them all."),
        (
            tools_activate,
            "Activate a tool pack by name for the current goal (vision, updates, local_apps, files, …).",
        ),
    ):
        try:
            registry.register(
                fn, name=fn.__name__, description=desc, module="amy_catalog", overwrite=True
            )
            out.append(fn.__name__)
        except Exception:
            continue
    get_tool_catalog().bind(registry)
    return out
