"""Voice tools for Amy update channels."""

from __future__ import annotations

from typing import Any, Dict, List

from amy.updates.checker import get_update_checker
from amy.workers.alerts import get_alert_bus


def updates_status() -> Dict[str, Any]:
    """Cached update channel status (no network if cooldown active)."""
    return get_update_checker().status()


def updates_check(force: bool = False) -> Dict[str, Any]:
    """Check GitHub releases for app/ui/driver/firmware update channels."""
    result = get_update_checker().check(force=bool(force))
    newer = [c for c in (result.get("channels") or []) if c.get("newer")]
    if newer:
        top = newer[0]
        get_alert_bus().post(
            kind="update",
            title=f"Update available: {top.get('tag')}",
            detail=f"{top.get('channel')} · {top.get('repo')}",
            severity=2,
            dedupe_key=f"update:{top.get('repo')}:{top.get('tag')}",
        )
    return result


def register(registry: Any) -> List[str]:
    specs = [
        (updates_status, "Show last update check / channels (cached)."),
        (updates_check, "Check GitHub for labeled updates (app/ui/driver/firmware)."),
    ]
    out: List[str] = []
    for fn, desc in specs:
        try:
            registry.register(
                fn, name=fn.__name__, description=desc, module="amy_updates", overwrite=True
            )
            out.append(fn.__name__)
        except Exception:
            continue
    return out
