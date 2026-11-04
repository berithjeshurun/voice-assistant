"""In-process event fan-out for HUD / WebSocket clients."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Union

from amy.protocol.messages import (
    ActivityChip,
    ApprovalRequest,
    AssistantSnapshot,
    AssistantState,
    ChatMessage,
    GuardStatus,
    HiveTask,
    HudCard,
)


class EventBus:
    def __init__(self, *, history_limit: int = 100) -> None:
        self._lock = threading.RLock()
        self._state = AssistantState.idle
        self._audio_level = 0.0
        self._last_user = ""
        self._last_assistant = ""
        self._detail = ""
        self._caption = ""
        self._caption_role = ""
        self._cards: List[HudCard] = []
        self._activity: Deque[ActivityChip] = deque(maxlen=12)
        self._tools: List[str] = []
        self._tasks: Dict[str, HiveTask] = {}
        self._task_order: Deque[str] = deque(maxlen=24)
        self._history: Deque[ChatMessage] = deque(maxlen=history_limit)
        self._approvals: List[ApprovalRequest] = []
        self._guard = GuardStatus()
        self._state_before_approval: Optional[AssistantState] = None
        self._listeners: Set[Callable[[AssistantSnapshot], None]] = set()
        self._async_queues: List[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def snapshot(self) -> AssistantSnapshot:
        with self._lock:
            tasks = [
                self._tasks[tid]
                for tid in list(self._task_order)
                if tid in self._tasks
            ]
            return AssistantSnapshot(
                state=self._state,
                audio_level=self._audio_level,
                last_user=self._last_user,
                last_assistant=self._last_assistant,
                detail=self._detail,
                caption=self._caption,
                caption_role=self._caption_role,
                cards=list(self._cards),
                activity=list(self._activity),
                tools=list(self._tools),
                tasks=list(reversed(tasks))[:12],
                approvals=list(self._approvals),
                guard=self._guard,
            )

    def history(self) -> List[ChatMessage]:
        with self._lock:
            return list(self._history)

    def set_state(
        self,
        state: AssistantState,
        *,
        detail: str = "",
        audio_level: Optional[float] = None,
    ) -> None:
        with self._lock:
            self._state = state
            if detail:
                self._detail = detail
            if audio_level is not None:
                self._audio_level = float(audio_level)
        self._emit(self.snapshot())

    def set_caption(self, text: str, *, role: str = "speak") -> None:
        with self._lock:
            self._caption = (text or "").strip()
            self._caption_role = (role or "").strip() if self._caption else ""
        self._emit(self.snapshot())

    def clear_caption(self) -> None:
        with self._lock:
            self._caption = ""
            self._caption_role = ""
        self._emit(self.snapshot())

    def set_cards(self, cards: List[Union[HudCard, Dict[str, Any]]]) -> None:
        normalized: List[HudCard] = []
        for c in cards or []:
            if isinstance(c, HudCard):
                normalized.append(c)
            elif isinstance(c, dict):
                try:
                    normalized.append(HudCard.model_validate(c))
                except Exception:
                    continue
        with self._lock:
            self._cards = normalized[:12]
        self._emit(self.snapshot())

    def clear_cards(self) -> None:
        with self._lock:
            self._cards = []
        self._emit(self.snapshot())

    def set_tools(self, tools: List[str]) -> None:
        cleaned = [str(t).strip() for t in (tools or []) if str(t).strip()]
        with self._lock:
            self._tools = cleaned
        self._emit(self.snapshot())

    def set_approvals(self, items: List[Union[ApprovalRequest, Dict[str, Any]]]) -> None:
        normalized: List[ApprovalRequest] = []
        for a in items or []:
            try:
                normalized.append(
                    a if isinstance(a, ApprovalRequest) else ApprovalRequest.model_validate(a)
                )
            except Exception:
                continue
        with self._lock:
            self._approvals = normalized
            if normalized:
                if self._state != AssistantState.needs_approval:
                    self._state_before_approval = self._state
                self._state = AssistantState.needs_approval
                self._detail = "approval"
                first = normalized[0]
                self._caption = f"Approval needed: {first.summary}"
                self._caption_role = "status"
            elif self._state == AssistantState.needs_approval:
                self._state = self._state_before_approval or AssistantState.thinking
                self._state_before_approval = None
        self._emit(self.snapshot())

    def set_guard(self, status: Union[GuardStatus, Dict[str, Any]]) -> None:
        if isinstance(status, dict):
            status = GuardStatus.model_validate(status)
        with self._lock:
            self._guard = status
        self._emit(self.snapshot())

    def note_activity(
        self,
        label: str,
        *,
        kind: str = "info",
        detail: str = "",
    ) -> None:
        chip = ActivityChip(
            kind=(kind or "info").strip() or "info",
            label=(label or "").strip()[:64],
            detail=(detail or "").strip()[:120],
        )
        if not chip.label:
            return
        with self._lock:
            kept = [
                c
                for c in self._activity
                if not (c.kind == chip.kind and c.label == chip.label)
            ]
            self._activity.clear()
            self._activity.append(chip)
            for c in kept:
                if len(self._activity) >= self._activity.maxlen:
                    break
                self._activity.append(c)
        self._emit(self.snapshot())

    def note_tool(self, name: str, summary: str = "") -> None:
        label = (name or "").strip()
        if not label:
            return
        self.note_activity(label, kind="tool", detail=summary)

    def upsert_task(self, task: Union[HiveTask, Dict[str, Any]]) -> HiveTask:
        if isinstance(task, dict):
            task = HiveTask.model_validate(task)
        with self._lock:
            tid = task.task_id
            self._tasks[tid] = task
            if tid in self._task_order:
                kept = [x for x in self._task_order if x != tid]
                self._task_order.clear()
                self._task_order.extend(kept)
            self._task_order.append(tid)
            while len(self._tasks) > 24 and self._task_order:
                old = self._task_order.popleft()
                if old != tid and old in self._tasks:
                    del self._tasks[old]
        self._emit(self.snapshot())
        return task

    def get_task(self, task_id: str) -> Optional[HiveTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> Optional[HiveTask]:
        """Request cancel; running tasks flip to cancelled when delegate notices."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.status == "running":
                task = task.model_copy(
                    update={"cancel_requested": True, "status": "cancelled"}
                )
                self._tasks[task_id] = task
            else:
                task = task.model_copy(update={"cancel_requested": True})
                self._tasks[task_id] = task
        self.note_activity(
            f"cancel:{task.agent_id or task_id[:8]}",
            kind="hive",
            detail=(task.goal or "")[:80],
        )
        self._emit(self.snapshot())
        return task

    def is_task_cancelled(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            return bool(task.cancel_requested) or task.status == "cancelled"

    def record_turn(self, user: str, assistant: str) -> None:
        now = time.time()
        with self._lock:
            self._last_user = user
            self._last_assistant = assistant
            self._history.append(ChatMessage(role="user", text=user, ts=now))
            self._history.append(
                ChatMessage(role="assistant", text=assistant, ts=now)
            )
            self._state = AssistantState.idle
            if (assistant or "").strip():
                self._caption = assistant.strip()[:420]
                self._caption_role = "speak"
        self._emit(self.snapshot())

    def subscribe(self, fn: Callable[[AssistantSnapshot], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.add(fn)

        def _unsub() -> None:
            with self._lock:
                self._listeners.discard(fn)

        return _unsub

    def add_async_queue(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._async_queues.append(q)

    def remove_async_queue(self, q: asyncio.Queue) -> None:
        with self._lock:
            if q in self._async_queues:
                self._async_queues.remove(q)

    def _emit(self, snap: AssistantSnapshot) -> None:
        with self._lock:
            listeners = list(self._listeners)
            queues = list(self._async_queues)
        for fn in listeners:
            try:
                fn(snap)
            except Exception:
                pass
        loop = self._loop
        for q in queues:
            try:
                if loop and loop.is_running():
                    loop.call_soon_threadsafe(q.put_nowait, snap)
                else:
                    q.put_nowait(snap)
            except Exception:
                pass

    def log(self, msg: str) -> None:
        print(f"# amy {msg}", flush=True)
