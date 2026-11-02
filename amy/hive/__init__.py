"""Phase 3 — Amy Hive: specialist AgentSpec registry + Queen delegation."""

from __future__ import annotations

from amy.hive.delegate import run_specialist
from amy.hive.registry import get_agent, list_agents
from amy.hive.spec import AgentSpec
from amy.hive.tools import register_hive_delegate_tools

__all__ = [
    "AgentSpec",
    "get_agent",
    "list_agents",
    "run_specialist",
    "register_hive_delegate_tools",
]
