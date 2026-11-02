"""Wire enabled Amy app packs into the Hive tool registry / ambient allowlist."""

from __future__ import annotations

from typing import Any, List, Sequence, Set


def apply_apps_to_registry(registry: Any, config: Any = None) -> List[str]:
    """Register pack tools onto *registry*. Returns tool names added."""
    from amy.apps.loader import load_enabled_packs

    summary = load_enabled_packs(registry, config=config)
    names: List[str] = []
    for tool_list in (summary.get("registered") or {}).values():
        names.extend(tool_list)
    return names


def merge_allowlist_keep(
    keep: Sequence[str] | Set[str],
    config: Any = None,
) -> List[str]:
    """Extend ambient allowlist keep-set with enabled pack tool names."""
    from amy.apps.loader import pack_tool_names

    out: List[str] = list(keep) if not isinstance(keep, list) else list(keep)
    seen = set(out)
    for name in pack_tool_names(config):
        if name not in seen:
            out.append(name)
            seen.add(name)
    return out
