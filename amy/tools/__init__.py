"""Amy product tools — Bambu Lab, slicer, OS, web search (+ host voice)."""

from __future__ import annotations

import logging
from typing import Any, Iterable, List, Sequence

from amy.tools.catalog import CORE_ALLOWLIST, get_tool_catalog
from amy.tools.voice_host import VOICE_HOST_ALLOWLIST, ensure_voice_host_tools

_logger = logging.getLogger(__name__)

# Default ambient surface — specialized packs activate via tools_activate.
AMY_TOOL_ALLOWLIST: Sequence[str] = tuple(CORE_ALLOWLIST)


def register_amy_tools(registry: Any, *, config: Any = None) -> List[str]:
    """Register Amy-only tools on a Hive registry. Returns registered names."""
    from amy.tools import (
        bambu,
        catalog,
        files,
        local_apps,
        os_controls,
        slicer,
        updates_tools,
        vision_tools,
        win_registry,
    )

    if isinstance(config, dict):
        local_apps.apply_config(config)
        packs = (config.get("tool_packs") or {}) if isinstance(config.get("tool_packs"), dict) else None
        if packs:
            get_tool_catalog(packs)
        upd = config.get("updates") if isinstance(config.get("updates"), dict) else None
        if upd:
            from amy.updates.checker import get_update_checker

            get_update_checker(upd)

    registered: List[str] = []
    registered.extend(catalog.register(registry))
    registered.extend(os_controls.register(registry))
    registered.extend(win_registry.register(registry))
    registered.extend(bambu.register(registry, config=config))
    registered.extend(slicer.register(registry, config=config))
    registered.extend(files.register(registry))
    registered.extend(local_apps.register(registry))
    registered.extend(vision_tools.register(registry))
    registered.extend(updates_tools.register(registry))
    get_tool_catalog().bind(registry, on_change=None)
    return registered


def prune_registry_to_allowlist(
    registry: Any,
    allowlist: Iterable[str] = AMY_TOOL_ALLOWLIST,
    *,
    also_keep: Iterable[str] = VOICE_HOST_ALLOWLIST,
) -> List[str]:
    """Unregister every tool not in the agent allowlist or host voice keep-set."""
    keep = {str(n).strip() for n in allowlist if str(n).strip()}
    keep.update(str(n).strip() for n in also_keep if str(n).strip())
    kept: List[str] = []
    for tool in list(registry.list_tools()):
        name = getattr(tool, "name", "") or ""
        if name in keep:
            kept.append(name)
            continue
        try:
            registry.unregister(name)
        except Exception:
            _logger.debug("ignored error", exc_info=True)
    return sorted(kept)


def _reregister_pack_tools(registry: Any, *, config: Any = None) -> None:
    """Re-register pack tools after prune so activate can bring them back."""
    from amy.tools import local_apps, updates_tools, vision_tools

    local_apps.register(registry)
    vision_tools.register(registry)
    updates_tools.register(registry)


def setup_amy_tool_surface(registry: Any, *, config: Any = None) -> dict:
    """Register Amy tools, restore voice host tools, prune to active catalog."""
    added = register_amy_tools(registry, config=config)
    app_tools: List[str] = []
    cat = get_tool_catalog()
    allow: List[str] = cat.allowlist()
    try:
        from amy.apps.registry_hook import apply_apps_to_registry, merge_allowlist_keep

        app_tools = apply_apps_to_registry(registry, config=config)
        allow = merge_allowlist_keep(allow, config=config)
        with cat._lock:
            cat._active.update(allow)
        allow = cat.allowlist()
    except Exception as e:
        _logger.warning("amy apps register failed: %s", e)

    def _on_change(_names: List[str]) -> None:
        register_amy_tools(registry, config=config)
        try:
            from amy.apps.registry_hook import apply_apps_to_registry

            apply_apps_to_registry(registry, config=config)
        except Exception:
            _logger.debug("ignored error", exc_info=True)
        # hive_delegate stays bound by AmbientHost (needs shell) — do not rebind bare.
        ensure_voice_host_tools(registry)
        # Keep hive_delegate if AmbientHost already registered it.
        allow = set(cat.allowlist())
        allow.add("hive_delegate")
        prune_registry_to_allowlist(registry, allowlist=allow)

    cat.bind(registry, on_change=_on_change)

    voice = ensure_voice_host_tools(registry)
    kept = prune_registry_to_allowlist(registry, allowlist=allow)
    voice2 = ensure_voice_host_tools(registry)
    # Keep pack implementations registered-but-pruned? We prune away inactive.
    # Activate re-registers via on_change.
    if app_tools:
        try:
            from amy.apps.registry_hook import apply_apps_to_registry

            app_tools = apply_apps_to_registry(registry, config=config)
            kept = prune_registry_to_allowlist(registry, allowlist=cat.allowlist())
        except Exception:
            _logger.debug("ignored error", exc_info=True)
    kept = sorted(
        {
            getattr(t, "name", "")
            for t in registry.list_tools()
            if getattr(t, "name", "")
        }
    )
    return {
        "amy": added,
        "apps": app_tools,
        "hive": ["hive_delegate"] if "hive_delegate" in kept else [],
        "voice": sorted(set(voice) | set(voice2)),
        "kept": kept,
    }
