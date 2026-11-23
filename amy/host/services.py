"""Host services that sit beside the agent: model routing and reminders."""

from __future__ import annotations

import logging
from typing import Callable, Optional

from amy.host.announcer import Announcer
from amy.host.events import EventBus
from amy.llm import Backend, LlmRouter, start_routing, switch_message
from amy.reminders import Reminder, Reminders, default_path, reminder_message, set_reminders
from amy.reminders.store import ReminderStore

_logger = logging.getLogger(__name__)


def llm_status(router: LlmRouter) -> dict:
    s = router.status()
    return {
        "active": s["active"] or "",
        "label": s["label"],
        "model": s["model"],
        "fallback": s["fallback"],
        "available": s["active"] is not None,
    }


def start_model_routing(
    bus: EventBus,
    amy_cfg: dict,
    announcer: Callable[[], Optional[Announcer]],
    log: Callable[[str], None],
) -> Optional[LlmRouter]:
    """Start ``amy.llm_routing`` (if configured); HUD + voice hear about every switch."""
    holder: dict = {}

    def _on_switch(old: Optional[Backend], new: Optional[Backend]) -> None:
        router = holder.get("router")
        if router is None:
            return
        bus.set_llm(llm_status(router))
        primary = router.backends[0] if router.backends else None
        msg = switch_message(old, new, primary)
        log(f"model: {msg}")
        a = announcer()
        if a is not None and old is not None:
            a.announce(msg, title=f"Model: {new.display if new else 'none'}", kind="model")

    try:
        # Register the switch hook before start() so the first probe selection
        # updates the HUD (spoken announcements still wait until old is set).
        router = start_routing(amy_cfg, on_switch=_on_switch)
    except Exception as e:
        log(f"model routing failed: {e}")
        _logger.error("model routing failed", exc_info=True)
        return None
    if router is None:
        return None
    holder["router"] = router
    bus.set_llm(llm_status(router))
    st = router.status()
    for b in st["backends"]:
        log(f"model backend {b['name']}: {'ok' if b['healthy'] else 'down — ' + b['error']}")
    log(f"model routing on {router.base_url} → {st['label']}")
    return router


def start_reminders(bus: EventBus, announcer: Announcer, log: Callable[[str], None]) -> Reminders:
    """A fresh service per host start; the voice tools reach it via ``get_reminders()``."""
    rem = Reminders(ReminderStore(default_path()))
    set_reminders(rem)

    def _fire(r: Reminder, missed: bool) -> None:
        title = "Timer done" if r.kind == "timer" else f"Reminder: {r.text}"
        announcer.announce(reminder_message(r, missed), title=title, kind="reminder")

    rem.on_fire(_fire)
    rem.on_change(lambda: bus.set_reminders(rem.upcoming()))
    rem.start()
    bus.set_reminders(rem.upcoming())
    log(f"reminders on ({len(rem.upcoming(limit=200))} pending)")
    return rem
