"""Reminders and timers: plain-language scheduling, SQLite storage, spoken announcements."""

from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from amy.reminders.scheduler import ReminderScheduler
from amy.reminders.store import MAX_PENDING, Reminder, ReminderLimit, ReminderStore
from amy.reminders.timeparse import (
    Repeat,
    TimeParseError,
    describe_when,
    parse_duration,
    parse_repeat,
    parse_when,
)

__all__ = [
    "MAX_PENDING",
    "Reminder",
    "ReminderLimit",
    "Reminders",
    "TimeParseError",
    "get_reminders",
    "reminder_message",
    "set_reminders",
]

_logger = logging.getLogger(__name__)
_MAX_TIMER_S = 24 * 3600


_PRONOUNS = {"my": "your", "me": "you", "mine": "yours", "myself": "yourself"}


def second_person(text: str) -> str:
    """"take my medicine" → "take your medicine" (for what Amy says back, not what's stored)."""
    return re.sub(r"\b(my|me|mine|myself)\b", lambda m: _PRONOUNS[m.group(1).lower()], text,
                  flags=re.IGNORECASE)


def reminder_message(r: Reminder, missed: bool = False) -> str:
    """What Amy says when a reminder fires."""
    if r.kind == "timer":
        label = r.text if r.text.lower() != "timer" else ""
        msg = f"Your {label} timer is done." if label else "Your timer is done."
    else:
        msg = f"Reminder: {second_person(r.text)}."
    if missed:
        msg += f" Sorry, this was due at {r.due.strftime('%I:%M %p').lstrip('0')} while I was off."
    return msg


class Reminders:
    """High-level API used by the voice tools, the HUD server and the host."""

    def __init__(
        self,
        store: ReminderStore,
        *,
        on_fire: Optional[Callable[[Reminder, bool], None]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.store = store
        self._listeners: List[Callable[[Reminder, bool], None]] = []
        self._change_listeners: List[Callable[[], None]] = []
        if on_fire is not None:
            self._listeners.append(on_fire)
        kw: Dict[str, Any] = {"clock": clock} if clock else {}
        self.scheduler = ReminderScheduler(store, self._fire, **kw)

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.scheduler.clock()).astimezone()

    def on_fire(self, fn: Callable[[Reminder, bool], None]) -> None:
        self._listeners.append(fn)

    def on_change(self, fn: Callable[[], None]) -> None:
        """Called after anything is added, cancelled or fired."""
        self._change_listeners.append(fn)

    def _changed(self) -> None:
        self.scheduler.poke()
        for fn in list(self._change_listeners):
            try:
                fn()
            except Exception:
                _logger.debug("reminder change listener failed", exc_info=True)

    def _fire(self, r: Reminder, missed: bool) -> None:
        try:
            for fn in list(self._listeners):
                fn(r, missed)
        finally:
            self._changed()

    def upcoming(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Compact items for the live HUD snapshot."""
        return [
            {"id": r.id, "text": r.text, "kind": r.kind, "due_ts": r.due_ts,
             "repeat_text": r.repeat_rule.describe() if r.repeat_rule else ""}
            for r in self.store.pending(limit=limit)
        ]

    def start(self) -> Reminders:
        self.scheduler.start()
        return self

    def stop(self) -> None:
        self.scheduler.stop()
        if get_reminders_if_set() is self:
            set_reminders(None)
        self.store.close()

    # --- commands ------------------------------------------------------------------------

    def add(self, text: str, when: str, repeat: str = "", *, source: str = "") -> Dict[str, Any]:
        now = self._now()
        rule: Optional[Repeat] = parse_repeat(repeat) if repeat else None
        if rule is None:
            try:
                rule = parse_repeat(when) if "every" in when.lower() or "daily" in when.lower() else None
            except TimeParseError:
                rule = None
        due = parse_when(when, now, conventional=rule is not None)
        if rule is not None and rule.kind == "weekdays":
            while due.weekday() >= 5:
                due = due + timedelta(days=1)
        elif rule is not None and rule.kind == "weekly" and rule.weekday is not None:
            while due.weekday() != rule.weekday:
                due = due + timedelta(days=1)
        r = self.store.add(text, due, repeat=rule, source=source)
        self._changed()
        out = r.as_dict(now)
        tail = f", {rule.describe()}" if rule else ""
        out["message"] = f"Okay, I'll remind you to {second_person(r.text)} {describe_when(due, now)}{tail}."
        return out

    def timer(self, duration: str, label: str = "", *, source: str = "") -> Dict[str, Any]:
        now = self._now()
        dur = parse_duration(duration)
        if dur is None:
            raise TimeParseError(f"couldn't understand the timer length: {duration!r}")
        secs = dur.total_seconds()
        if secs < 1 or secs > _MAX_TIMER_S:
            raise TimeParseError("timers can run from 1 second to 24 hours")
        r = self.store.add(label.strip() or "timer", now + dur, kind="timer", source=source)
        self._changed()
        out = r.as_dict(now)
        out["message"] = f"Timer set for {_speak_duration(secs)}."
        return out

    def list(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        now = self._now()
        return [r.as_dict(now) for r in self.store.pending(limit=limit)]

    def cancel(self, ref: str | int) -> Dict[str, Any]:
        """Cancel by id, or by matching text ("the dentist one")."""
        target: Optional[Reminder] = None
        s = str(ref).strip().lstrip("#")
        if s.isdigit():
            target = self.store.get(int(s))
            if target is not None and target.status != "pending":
                target = None
        else:
            matches = self.store.find(s)
            if len(matches) > 1:
                return {
                    "ok": False,
                    "error": "more than one reminder matches; say which one",
                    "matches": [m.as_dict(self._now()) for m in matches[:5]],
                }
            target = matches[0] if matches else None
        if target is None or not self.store.cancel(target.id):
            return {"ok": False, "error": f"no pending reminder matches {ref!r}"}
        self._changed()
        if target.kind == "timer":
            what = "timer" if target.text == "timer" else f"{target.text} timer"
        else:
            what = f"reminder to {second_person(target.text)}"
        return {"ok": True, "id": target.id, "message": f"Cancelled the {what}."}


def _speak_duration(secs: float) -> str:
    secs = int(round(secs))
    parts = []
    for unit, size in (("hour", 3600), ("minute", 60), ("second", 1)):
        n, secs = divmod(secs, size)
        if n:
            parts.append(f"{n} {unit}{'s' if n != 1 else ''}")
    return " and ".join(parts) or "0 seconds"


_instance: Optional[Reminders] = None
_instance_lock = threading.Lock()


def default_path() -> Path:
    from amy.server.auth import amy_state_dir

    return Path(os.environ.get("AMY_REMINDERS_DB") or (amy_state_dir() / "reminders.db"))


def get_reminders() -> Reminders:
    """Process-wide reminders set by the host via ``set_reminders``.

    Raises ``RuntimeError`` when the host service never started — voice tools
    must not invent a silent, unscheduled instance that never fires.
    """
    with _instance_lock:
        if _instance is None:
            raise RuntimeError("Reminders are not available right now")
        return _instance


def get_reminders_if_set() -> Optional[Reminders]:
    return _instance


def set_reminders(r: Optional[Reminders]) -> None:
    global _instance
    with _instance_lock:
        _instance = r
