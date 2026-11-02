"""Smoke Phase 3 AgentSpec registry + hive_delegate registration (no LLM call)."""

from __future__ import annotations

import sys


def main() -> int:
    from amy.hive import get_agent, list_agents, register_hive_delegate_tools
    from amy.hive.delegate import format_delegate_speak
    from amy.tools import AMY_TOOL_ALLOWLIST

    agents = list_agents()
    assert {a.id for a in agents} >= {"scout", "ops", "scribe", "archivist"}, [
        a.id for a in agents
    ]
    scout = get_agent("scout")
    assert scout and "web_search" in scout.tools
    ops = get_agent("Ops")
    assert ops and ops.id == "ops"
    scribe = get_agent("scribe")
    assert scribe and "read_file" in scribe.tools
    arch = get_agent("archivist")
    assert arch and arch.id == "archivist"
    assert "hive_delegate" in AMY_TOOL_ALLOWLIST

    class _FakeReg:
        def __init__(self) -> None:
            self.names = []

        def register(self, fn, *, name=None, description=None, module=None, overwrite=False):
            self.names.append(name or getattr(fn, "__name__", ""))

        def list_tools(self):
            return []

    reg = _FakeReg()
    names = register_hive_delegate_tools(reg, shell=None)
    assert names == ["hive_delegate"], names
    assert "hive_delegate" in reg.names

    speak = format_delegate_speak(
        {"status": "ok", "agent_name": "Scout", "output": "Season two airs in 2026. More fluff."}
    )
    assert "2026" in speak, speak

    from amy.host.events import EventBus
    from amy.protocol.messages import HiveTask

    bus = EventBus()
    bus.upsert_task(
        HiveTask(
            task_id="t-smoke",
            agent_id="scout",
            agent_name="Scout",
            goal="test",
            status="running",
            max_steps=6,
        )
    )
    snap = bus.snapshot()
    assert any(t.task_id == "t-smoke" for t in snap.tasks), snap.tasks
    cancelled = bus.cancel_task("t-smoke")
    assert cancelled and cancelled.status == "cancelled"
    assert bus.is_task_cancelled("t-smoke")

    print(
        f"hive agents={[a.id for a in agents]} tool={names} "
        f"speak={speak!r} tasks={len(bus.snapshot().tasks)}"
    )
    print("smoke_hive PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"smoke_hive FAIL: {e}", file=sys.stderr)
        raise
