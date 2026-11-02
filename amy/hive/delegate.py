"""Run a specialist AgentSpec as a nested one-shot PyHiveAgent."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from amy.hive.registry import get_agent, list_agents
from amy.hive.spec import AgentSpec
from amy.protocol.messages import HiveTask


def _child_registry(parent: Any, tools: tuple[str, ...]) -> Any:
    from pyhive.core.runtime.registry import PyHiveRegistry

    child = PyHiveRegistry()
    for name in tools:
        try:
            tool = parent.get_tool(name)
        except Exception:
            continue
        try:
            child.register(tool, overwrite=True, module="hive_specialist")
        except Exception:
            pass
    return child


def run_specialist(
    shell: Any,
    agent_id: str,
    goal: str,
    *,
    on_log: Optional[Any] = None,
    bus: Any = None,
    parent_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Delegate ``goal`` to a registered specialist; return Task/Result-shaped dict."""
    t0 = time.time()
    tid = (task_id or "").strip() or str(uuid.uuid4())
    goal = (goal or "").strip()
    if not goal:
        return {
            "status": "failed",
            "output": "Empty goal.",
            "agent_id": agent_id,
            "task_id": tid,
            "ms": 0,
        }

    spec = get_agent(agent_id)
    if spec is None:
        known = ", ".join(sorted(a.id for a in list_agents()))
        return {
            "status": "failed",
            "output": f"Unknown agent {agent_id!r}. Known: {known}",
            "agent_id": agent_id,
            "task_id": tid,
            "ms": 0,
        }

    log = on_log or (lambda _m: None)
    log(f"hive_delegate → {spec.id} task={tid[:8]} goal={goal[:80]}")

    if bus is not None:
        try:
            bus.upsert_task(
                HiveTask(
                    task_id=tid,
                    agent_id=spec.id,
                    agent_name=spec.name,
                    goal=goal[:400],
                    status="running",
                    permission_level=spec.permission_level,
                    max_steps=int(spec.max_steps),
                    wall_seconds=float(spec.wall_seconds),
                    parent_id=parent_id,
                )
            )
            bus.note_activity(
                f"{spec.name}",
                kind="hive",
                detail=goal[:80],
            )
        except Exception as e:
            log(f"task board start: {e}")

    if bus is not None and getattr(bus, "is_task_cancelled", None):
        try:
            if bus.is_task_cancelled(tid):
                return _finish(
                    bus,
                    tid,
                    spec,
                    status="cancelled",
                    output="Cancelled before start.",
                    t0=t0,
                    tools=[],
                    log=log,
                )
        except Exception:
            pass

    parent_reg = (getattr(shell, "_bundle", None) or {}).get("registry")
    if parent_reg is None:
        return _finish(
            bus,
            tid,
            spec,
            status="failed",
            output="No tool registry on shell.",
            t0=t0,
            tools=[],
            log=log,
        )

    parent_agent = getattr(shell, "_agent", None)
    llm = None
    if parent_agent is not None:
        llm = (
            getattr(getattr(parent_agent, "llm", None), "_pyhive_llm", None)
            or getattr(parent_agent, "llm", None)
        )
    if llm is None:
        return _finish(
            bus,
            tid,
            spec,
            status="failed",
            output="No LLM on shell agent.",
            t0=t0,
            tools=[],
            log=log,
        )

    child_reg = _child_registry(parent_reg, tuple(spec.tools))
    available = [
        getattr(t, "name", "")
        for t in child_reg.list_tools()
        if getattr(t, "name", "")
    ]
    # Tool-backed specialists must have at least one tool; LLM-only specs may omit tools.
    if spec.tools and not available:
        return _finish(
            bus,
            tid,
            spec,
            status="failed",
            output=f"No tools available for {spec.id} (wanted {list(spec.tools)}).",
            t0=t0,
            tools=[],
            log=log,
        )

    from pyhive.contracts import AgentMode
    from pyhive.core.runtime.workflows import PyHiveAgent

    agent = PyHiveAgent(
        name=f"amy-{spec.id}",
        registry=child_reg,
        llm_callable=llm,
        system_prompt=spec.system_prompt,
        max_steps=int(spec.max_steps),
        verbose=False,
        use_selector=bool(available),
        shortlist_top_k=min(8, max(2, len(available) or 2)),
        mode=AgentMode.REACT,
        use_workers=False,
        plan_fanout=False,
        plan_first=False,
        hard_verify=False,
        wall_seconds=float(spec.wall_seconds),
        model_spec=str(getattr(parent_agent, "model_spec", "") or ""),
        hive_config=getattr(shell, "_hcfg", None),
    )

    ctx = getattr(shell, "_ctx", None)
    try:
        raw = agent.run(goal, ctx) if ctx is not None else agent.run(goal)
        out = str(raw or "").strip()
        status = "ok" if out and not out.lower().startswith("error:") else "partial"
        if not out:
            out = "No result."
            status = "failed"
    except Exception as e:
        out = f"Specialist error: {e}"
        status = "failed"

    if bus is not None and getattr(bus, "is_task_cancelled", None):
        try:
            if bus.is_task_cancelled(tid):
                status = "cancelled"
                out = out or "Cancelled."
        except Exception:
            pass

    return _finish(
        bus,
        tid,
        spec,
        status=status,
        output=out,
        t0=t0,
        tools=available,
        log=log,
    )


def _finish(
    bus: Any,
    tid: str,
    spec: AgentSpec,
    *,
    status: str,
    output: str,
    t0: float,
    tools: list,
    log: Any,
) -> Dict[str, Any]:
    ms = int((time.time() - t0) * 1000)
    log(f"hive_delegate ← {spec.id} task={tid[:8]} status={status} ms={ms}")
    if bus is not None:
        try:
            existing = bus.get_task(tid) if hasattr(bus, "get_task") else None
            cancel_req = bool(getattr(existing, "cancel_requested", False))
            if cancel_req and status not in ("cancelled",):
                status = "cancelled"
            bus.upsert_task(
                HiveTask(
                    task_id=tid,
                    agent_id=spec.id,
                    agent_name=spec.name,
                    goal=(getattr(existing, "goal", None) or "")[:400],
                    status=status,
                    permission_level=spec.permission_level,
                    max_steps=int(spec.max_steps),
                    wall_seconds=float(spec.wall_seconds),
                    ms=ms,
                    output=(output or "")[:2000],
                    parent_id=getattr(existing, "parent_id", None),
                    cancel_requested=cancel_req or status == "cancelled",
                )
            )
            bus.note_activity(
                f"{spec.name}:{status}",
                kind="hive",
                detail=(output or "")[:80],
            )
        except Exception as e:
            log(f"task board end: {e}")
    return {
        "status": status,
        "output": output,
        "agent_id": spec.id,
        "agent_name": spec.name,
        "permission_level": spec.permission_level,
        "tools": tools,
        "ms": ms,
        "task_id": tid,
        "evidence": [{"type": "agent", "ref": spec.id}],
    }


def format_delegate_speak(result: Dict[str, Any]) -> str:
    """Short spoken/display line from a specialist result."""
    status = str(result.get("status") or "")
    out = str(result.get("output") or "").strip()
    name = str(result.get("agent_name") or result.get("agent_id") or "specialist")
    if status == "cancelled":
        return f"{name} was cancelled."
    if status == "failed":
        return f"{name} failed: {out[:200]}"
    parts = []
    buf = ""
    for ch in out:
        buf += ch
        if ch in ".!?\n" and len(buf) >= 12:
            parts.append(buf.strip())
            buf = ""
            if len(parts) >= 2:
                break
    if buf.strip() and len(parts) < 2:
        parts.append(buf.strip())
    spoken = " ".join(parts) if parts else out
    if len(spoken) > 360:
        spoken = spoken[:357].rstrip() + "…"
    return spoken
