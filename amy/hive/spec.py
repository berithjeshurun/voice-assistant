"""AgentSpec — specialist role shape for Amy Hive (Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class AgentSpec:
    """Typed specialist profile: prompt, tools, budget, permission ceiling."""

    id: str
    name: str
    system_prompt: str
    tools: Tuple[str, ...] = ()
    max_steps: int = 6
    permission_level: str = "L1"  # L0–L3 (PRO-PLAN §3.5)
    wall_seconds: float = 90.0
    description: str = ""
    tags: Tuple[str, ...] = field(default_factory=tuple)

    def tool_set(self) -> frozenset[str]:
        return frozenset(str(t).strip() for t in self.tools if str(t).strip())
