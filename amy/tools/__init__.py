"""Amy product tools — Bambu Lab, slicer, OS, web search (+ host voice)."""

from __future__ import annotations

from typing import Any, Iterable, List, Sequence

from amy.tools.voice_host import VOICE_HOST_ALLOWLIST, ensure_voice_host_tools

# Strict ambient agent catalog — nothing else survives the prune.
AMY_TOOL_ALLOWLIST: Sequence[str] = (
    # OS / browse
    "os_volume",
    "os_mute",
    "os_brightness",
    "os_toggle",
    "os_open_app",
    "browse_url",
    "play_youtube",
    "os_power",
    "os_process_list",
    "os_process_kill",
    # Local shell (when coding pack is assembled)
    "run_powershell",
    "run_shell",
    "list_dir",
    # Bambu Lab
    "bambu_status",
    "bambu_control",
    # Slicer
    "slicer_find",
    "slicer_open",
    # Files
    "read_file",
    # Live facts
    "web_search",
    "web_fetch",
    # Phase 3 — Queen → specialist delegation
    "hive_delegate",
)


def register_amy_tools(registry: Any, *, config: Any = None) -> List[str]:
    """Register Amy-only tools on a Hive registry. Returns registered names."""
    from amy.tools import bambu, files, os_controls, slicer

    registered: List[str] = []
    registered.extend(os_controls.register(registry))
    registered.extend(bambu.register(registry, config=config))
    registered.extend(slicer.register(registry, config=config))
    registered.extend(files.register(registry))
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
            pass
    return sorted(kept)


def setup_amy_tool_surface(registry: Any, *, config: Any = None) -> dict:
    """Register Amy tools, restore voice host tools, prune everything else."""
    added = register_amy_tools(registry, config=config)
    app_tools: List[str] = []
    allow: List[str] = list(AMY_TOOL_ALLOWLIST)
    try:
        from amy.apps.registry_hook import apply_apps_to_registry, merge_allowlist_keep

        app_tools = apply_apps_to_registry(registry, config=config)
        allow = merge_allowlist_keep(allow, config=config)
    except Exception as e:
        print(f"# amy apps register failed: {e}", flush=True)

    voice = ensure_voice_host_tools(registry)
    kept = prune_registry_to_allowlist(registry, allowlist=allow)
    # Prune keeps VOICE_HOST_ALLOWLIST; re-register if steam never loaded them.
    voice2 = ensure_voice_host_tools(registry)
    # Pack tools must survive prune — re-register after prune with same allowlist.
    if app_tools:
        try:
            from amy.apps.registry_hook import apply_apps_to_registry

            app_tools = apply_apps_to_registry(registry, config=config)
            kept = prune_registry_to_allowlist(registry, allowlist=allow)
        except Exception:
            pass
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
        "voice": sorted(set(voice) | set(voice2)),
        "kept": kept,
    }
