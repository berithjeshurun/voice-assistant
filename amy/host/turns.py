"""One agent turn: guard lifecycle, app shortcuts, PyHive turn, HUD cards and activity."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Iterable, Optional

from amy.errors import HostBusy
from amy.hive_adapter import HiveAdapter
from amy.host.events import EventBus
from amy.logs import current_turn_id, turn_context
from amy.protocol.messages import AssistantState

_logger = logging.getLogger(__name__)


def tool_names_from_meta(meta: dict) -> Iterable[tuple[str, str]]:
    """(name, detail) for each tool PyHive reports in a turn's meta, whatever the shape."""
    for raw in meta.get("tools_used") or meta.get("last_tools") or meta.get("tool_calls") or []:
        if isinstance(raw, str):
            if raw:
                yield raw, ""
        elif isinstance(raw, dict):
            name = str(raw.get("name") or raw.get("tool") or raw.get("fn") or "")
            if name:
                yield name, str(raw.get("summary") or raw.get("status") or "")


class TurnRunner:
    """``agent_runner`` for PyHive's VoiceSession, shared by voice and HUD text turns.

    Only one agent turn runs at a time. Voice turns wait for the lock; HUD text turns
    fail fast with :class:`HostBusy` (see :meth:`busy`) so the phone can say so.
    """

    def __init__(
        self,
        hive: HiveAdapter,
        bus: EventBus,
        *,
        guard: Callable[[], Any],
        source: Callable[[], str],
        hive_config: Any = None,
        lock_timeout_s: float = 600.0,
    ) -> None:
        self.hive = hive
        self.bus = bus
        self._guard = guard
        self._source = source
        self.hive_config = hive_config
        self.lock_timeout_s = lock_timeout_s
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def before_agent(self, text: str, ack_text: str) -> None:
        svc = self.hive.ensure_ctx()
        svc["voice_ack_done"] = True
        svc["voice_ack_text"] = ack_text or ""
        self.bus.set_state(AssistantState.thinking, detail="bridging reply")
        self.bus.note_activity("ack", kind="status", detail="bridging reply")
        if (text or "").strip():
            self.bus.set_caption(text.strip()[:220], role="user")
        if (ack_text or "").strip():
            self.bus.set_caption(ack_text.strip(), role="ack")

    def __call__(self, text: str) -> Any:
        if not self._lock.acquire(timeout=self.lock_timeout_s):
            raise HostBusy("another turn is still running")
        try:
            with turn_context(current_turn_id() or None) as tid:
                guard = self._guard()
                if guard is not None:
                    guard.begin_turn(self._source())
                _logger.info("turn start source=%s text=%r", self._source(), (text or "")[:120])
                try:
                    return self._run(text)
                finally:
                    if guard is not None:
                        guard.end_turn()
                    _logger.debug("turn end %s", tid)
        finally:
            self._lock.release()

    def _run(self, text: str) -> Any:
        from pyhive.core.host.dual_reply import DualReply, parse_dual_reply

        from amy.host.hud_cards import cards_from_turn

        bus = self.bus
        bus.set_state(AssistantState.thinking, detail=(text or "working")[:80])
        bus.clear_cards()
        bus.note_activity("working", kind="status", detail=(text or "")[:80] or "running tools")

        app_hit = self._app_shortcut(text)
        if app_hit is not None:
            return app_hit

        turn = self.hive.turn(text)
        meta = turn.meta or {}
        reply_text = (turn.assistant or "").strip()
        cards = cards_from_turn(reply_text, meta=meta)
        if cards:
            bus.set_cards(cards)
            first = cards[0]
            weatherish = any(
                "weather" in ((c.title or "") + (c.snippet or "")).lower()
                or "°" in ((c.title or "") + (c.snippet or ""))
                for c in cards
            )
            if weatherish:
                bus.note_activity(
                    first.title[:48] or "weather", kind="weather", detail=(first.snippet or "")[:80]
                )
            else:
                bus.note_activity(
                    f"{len(cards)} results", kind="info", detail=(first.title or "")[:80]
                )
        for name, detail in tool_names_from_meta(meta):
            bus.note_tool(name, detail)

        if meta.get("dual_parsed") and (turn.speak or "").strip():
            bus.set_caption((turn.speak or "").strip(), role="speak")
            return DualReply(text=turn.assistant or "", speak=turn.speak or "", parsed=True)
        dual = parse_dual_reply(meta.get("raw_reply") or turn.assistant or "")
        line = (dual.speak or dual.text or "").strip()
        if line:
            bus.set_caption(line[:420], role="speak")
        return dual

    def _app_shortcut(self, text: str) -> Optional[Any]:
        """Amy app voice shortcuts (SmartPanels login/open) run before the agent."""
        try:
            from amy.apps.voice_hooks import try_app_voice_shortcut

            hit = try_app_voice_shortcut(text, config=self.hive_config)
        except Exception:
            _logger.warning("app voice hook failed", exc_info=True)
            return None
        if hit is not None:
            speak = (hit.speak or hit.text or "").strip()
            if speak:
                self.bus.set_caption(speak[:420], role="speak")
                self.bus.note_activity("SmartPanel", kind="capability", detail=speak[:80])
        return hit
