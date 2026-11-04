"""Queen-only hive_delegate tool — spawn Scout/Ops/Scribe/Archivist specialists."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from amy.hive.delegate import format_delegate_speak, run_specialist
from amy.hive.registry import list_agents

_logger = logging.getLogger(__name__)

HIVE_DELEGATE_TOOL = "hive_delegate"


def register_hive_delegate_tools(
    registry: Any,
    *,
    shell: Any = None,
    bus: Any = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_activity: Optional[Callable[[str, str], None]] = None,
) -> List[str]:
    """Register ``hive_delegate`` on the Queen registry. Returns tool names."""

    def hive_delegate(agent: str, goal: str) -> Dict[str, Any]:
        """Delegate a goal to a Hive specialist (scout, ops, scribe, archivist).

        Use scout for research, ops for OS actions, scribe for drafts,
        archivist for workspace notes. Pass agent id and a clear goal.
        """
        aid = (agent or "").strip().lower()
        if on_activity:
            try:
                on_activity(aid or "hive", (goal or "")[:80])
            except Exception:
                _logger.debug("ignored error", exc_info=True)
        sh = shell
        if sh is None:
            return {
                "ok": False,
                "status": "failed",
                "error": "hive_delegate: no shell bound",
            }
        result = run_specialist(sh, aid, goal, on_log=on_log, bus=bus)
        speak = format_delegate_speak(result)
        ok = result.get("status") in ("ok", "partial")
        return {
            "ok": ok,
            "status": result.get("status"),
            "agent_id": result.get("agent_id"),
            "agent_name": result.get("agent_name"),
            "task_id": result.get("task_id"),
            "output": result.get("output"),
            "speak": speak,
            "ms": result.get("ms"),
            "tools": result.get("tools"),
            "budget": {
                "max_steps": next(
                    (a.max_steps for a in list_agents() if a.id == result.get("agent_id")),
                    None,
                ),
                "ms": result.get("ms"),
            },
        }

    known = ", ".join(f"{a.id} ({a.name})" for a in list_agents())
    hive_delegate.__doc__ = (
        "Delegate work to a Hive specialist agent. "
        f"Known agents: {known}. "
        "Args: agent (id like 'scout', 'ops', 'scribe', 'archivist'), goal."
    )

    try:
        registry.register(
            hive_delegate,
            name=HIVE_DELEGATE_TOOL,
            description=(
                "Delegate a goal to a Hive specialist. "
                f"Agents: {known}. "
                "Example: agent='scout', goal='summarize Black Clover season 2 air date'."
            ),
            module="amy_hive",
            overwrite=True,
        )
        return [HIVE_DELEGATE_TOOL]
    except Exception:
        return []
