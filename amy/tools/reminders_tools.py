"""Voice tools: reminders and timers."""

from __future__ import annotations

from typing import Any, Dict, List

from amy.reminders import ReminderLimit, TimeParseError, get_reminders

TOOL_NAMES = ("reminder_add", "reminder_list", "reminder_cancel", "timer_start")


def _fail(msg: str) -> Dict[str, Any]:
    return {"ok": False, "error": msg}


def reminder_add(text: str, when: str, repeat: str = "") -> Dict[str, Any]:
    """Set a reminder. Pass the user's own words for `when` — do not convert them —
    e.g. "in 20 minutes", "at 6pm", "tomorrow at 9", "on Friday at 5", "tonight".
    `repeat` is optional: "daily", "every weekday", "every Monday", "every 2 hours".
    `text` is what to remind about, e.g. "call mom"."""
    try:
        out = get_reminders().add(text, when, repeat, source="voice")
    except (TimeParseError, ReminderLimit, ValueError, RuntimeError) as e:
        return _fail(str(e))
    return {"ok": True, **out}


def timer_start(duration: str, label: str = "") -> Dict[str, Any]:
    """Start a countdown timer. `duration` in the user's words, e.g. "10 minutes",
    "1 hour 30 minutes", "90 seconds". Optional `label`, e.g. "pasta"."""
    try:
        out = get_reminders().timer(duration, label, source="voice")
    except (TimeParseError, ReminderLimit, ValueError, RuntimeError) as e:
        return _fail(str(e))
    return {"ok": True, **out}


def reminder_list() -> Dict[str, Any]:
    """List upcoming reminders and running timers."""
    try:
        items = get_reminders().list(limit=20)
    except RuntimeError as e:
        return _fail(str(e))
    if not items:
        return {"ok": True, "reminders": [], "message": "You have no reminders."}
    def label(r: Dict[str, Any]) -> str:
        if r["kind"] != "timer":
            return str(r["text"])
        return "timer" if r["text"] == "timer" else f"{r['text']} timer"

    lines = [
        f"#{r['id']} {label(r)} {r['when']}"
        + (f" ({r['repeat_text']})" if r["repeat_text"] else "")
        for r in items
    ]
    return {"ok": True, "reminders": items, "message": "; ".join(lines)}


def reminder_cancel(reminder: str) -> Dict[str, Any]:
    """Cancel a reminder or timer by its number (e.g. "3") or words from it (e.g. "dentist")."""
    try:
        return get_reminders().cancel(reminder)
    except RuntimeError as e:
        return _fail(str(e))


def register(registry: Any) -> List[str]:
    out: List[str] = []
    for fn in (reminder_add, timer_start, reminder_list, reminder_cancel):
        try:
            registry.register(
                fn,
                name=fn.__name__,
                description=(fn.__doc__ or "").split("\n")[0],
                module="amy_reminders",
                overwrite=True,
            )
            out.append(fn.__name__)
        except Exception:
            continue
    return out
