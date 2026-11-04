"""Versioned Amy client/server protocol (HUD, phone, orb)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from amy.branding import ASSISTANT_NAME, PROTOCOL_VERSION


class AssistantState(str, Enum):
    idle = "idle"
    listening = "listening"
    thinking = "thinking"
    speaking = "speaking"
    needs_approval = "needs_approval"
    error = "error"


class HudCard(BaseModel):
    """Rich HUD card (web search hit, etc.)."""

    kind: str = "web"
    title: str = ""
    url: str = ""
    snippet: str = ""


class ActivityChip(BaseModel):
    """Live dock chip — tool use, weather, capability, status."""

    kind: str = "info"  # tool | weather | capability | status | info | agent | hive
    label: str = ""
    detail: str = ""


class HiveTask(BaseModel):
    """Phase 3 task board entry (Queen → specialist)."""

    task_id: str
    agent_id: str = ""
    agent_name: str = ""
    goal: str = ""
    status: str = "running"  # running | ok | partial | failed | cancelled
    permission_level: str = "L1"
    max_steps: int = 6
    wall_seconds: float = 90.0
    ms: int = 0
    output: str = ""
    parent_id: Optional[str] = None
    cancel_requested: bool = False


class ApprovalRequest(BaseModel):
    """A guarded tool call waiting for a human yes/no."""

    id: str
    tool: str = ""
    summary: str = ""
    reason: str = ""
    risk: str = "medium"
    expires_at: float = 0.0


class GuardStatus(BaseModel):
    enabled: bool = True
    mode: str = "standard"
    lockdown: bool = False


class AssistantSnapshot(BaseModel):
    protocol_version: int = PROTOCOL_VERSION
    name: str = ASSISTANT_NAME
    state: AssistantState = AssistantState.idle
    audio_level: float = 0.0
    last_user: str = ""
    last_assistant: str = ""
    detail: str = ""
    caption: str = ""
    caption_role: str = ""  # ack | speak | user | status | ""
    cards: List[HudCard] = Field(default_factory=list)
    activity: List[ActivityChip] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    tasks: List[HiveTask] = Field(default_factory=list)
    approvals: List[ApprovalRequest] = Field(default_factory=list)
    guard: GuardStatus = Field(default_factory=GuardStatus)


class ChatMessage(BaseModel):
    role: str
    text: str
    ts: float = 0.0


class TurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    source: str = "web"


class TurnResponse(BaseModel):
    ok: bool = True
    reply: str = ""
    speak: str = ""
    state: AssistantState = AssistantState.idle
    error: Optional[str] = None


class ClientCommand(BaseModel):
    type: str
    state: Optional[AssistantState] = None
    text: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class HealthInfo(BaseModel):
    ok: bool = True
    name: str = ASSISTANT_NAME
    state: AssistantState = AssistantState.idle
    voice: bool = False
    wake: bool = False
    bind: str = ""
    lan: bool = False
    history: List[ChatMessage] = Field(default_factory=list)


class ApprovalAnswer(BaseModel):
    id: str = Field(min_length=1)
    approve: bool = False


class LockdownRequest(BaseModel):
    on: bool = True
