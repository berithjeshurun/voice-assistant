"""Plain-language times for reminders: "in 10 minutes", "at 6pm", "tomorrow at 9", "every weekday".

The model passes the user's words through; small local models are bad at date arithmetic.
All datetimes are timezone-aware in the machine's local zone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50,
    "sixty": 60, "ninety": 90, "couple": 2, "few": 3,
}
_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
}
_PART_OF_DAY = {"morning": 9, "noon": 12, "afternoon": 15, "evening": 19, "tonight": 20, "night": 21}

def _alt(words) -> str:
    return "|".join(sorted(map(re.escape, words), key=len, reverse=True))


# Digits may take abbreviated units ("10m", "2h"); spelled numbers need a full unit word,
# otherwise "6 am" would read as "a" + "m".
_LONG_UNITS = [u for u in _UNIT_SECONDS if len(u) > 1]
_HALF = r"(?:\s+and\s+a\s+half)?"
_DURATION_RE = re.compile(
    rf"\b(\d+(?:\.\d+)?)\s*(?:and\s+a\s+half\s+)?({_alt(_UNIT_SECONDS)})\b{_HALF}"
    rf"|\b({_alt(_WORD_NUMBERS)})\s+(?:and\s+a\s+half\s+)?({_alt(_LONG_UNITS)})\b{_HALF}",
    re.I,
)
_CLOCK_RE = re.compile(
    r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?=\s|$|[,.!?])", re.I
)
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[ t](\d{1,2}):(\d{2}))?", re.I)


class TimeParseError(ValueError):
    """The text did not contain a time we understand."""


def _num(tok: str) -> float:
    tok = tok.lower()
    return float(_WORD_NUMBERS[tok]) if tok in _WORD_NUMBERS else float(tok)


def parse_duration(text: str) -> Optional[timedelta]:
    """Sum every "<number> <unit>" in ``text`` ("1 hour 30 minutes", "half an hour")."""
    t = text.lower()
    total = 0.0
    found = False
    if re.search(r"\bhalf\s+(an?\s+)?hour\b", t):
        total += 1800
        found = True
        t = re.sub(r"\bhalf\s+(an?\s+)?hour\b", " ", t)
    if re.search(r"\bquarter\s+(of\s+)?an?\s+hour\b", t):
        total += 900
        found = True
        t = re.sub(r"\bquarter\s+(of\s+)?an?\s+hour\b", " ", t)
    for m in _DURATION_RE.finditer(t):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        half = 0.5 if "and a half" in m.group(0) else 0.0
        total += (_num(num) + half) * _UNIT_SECONDS[unit.lower()]
        found = True
    return timedelta(seconds=total) if found and total > 0 else None


def _part_of_day(t: str) -> Optional[int]:
    return next((h for w, h in _PART_OF_DAY.items() if re.search(rf"\b{w}\b", t)), None)


def _clock(text: str) -> Optional[tuple[int, int, bool]]:
    """(hour, minute, ambiguous) — ambiguous means no am/pm and the hour could be either."""
    t = text.lower()
    if re.search(r"\bnoon\b|\bmidday\b", t):
        return 12, 0, False
    if re.search(r"\bmidnight\b", t):
        return 0, 0, False
    for m in _CLOCK_RE.finditer(t):
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        ampm = (m.group(3) or "").replace(".", "")
        if minute > 59 or hour > 23:
            continue
        # a bare number is only a time after "at"/"by", or with minutes or am/pm
        before = t[: m.start()].rstrip()
        if not ampm and m.group(2) is None and not before.endswith(("at", "by", "@")):
            continue
        if ampm:
            if hour > 12:
                continue
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            return hour, minute, False
        part = _part_of_day(t)
        if part is not None and 1 <= hour < 12:
            return (hour + 12 if part >= 15 else hour), minute, False
        return hour, minute, 1 <= hour < 12
    return None


def parse_when(text: str, now: Optional[datetime] = None, *, conventional: bool = False) -> datetime:
    """Resolve ``text`` to a future local datetime, or raise :class:`TimeParseError`.

    An hour without am/pm normally means whichever comes next ("at 6" at noon → 6 pm).
    ``conventional`` (used for repeating reminders) reads 7–11 as morning and 1–6 as
    afternoon instead, since "every weekday at 9" means 9 am.
    """
    now = (now or datetime.now()).astimezone()
    raw = (text or "").strip()
    t = raw.lower()
    if not t:
        raise TimeParseError("no time given")

    iso = _ISO_RE.search(t)
    if iso:
        y, mo, d = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        hh, mm = int(iso.group(4) or 9), int(iso.group(5) or 0)
        try:
            when = now.replace(year=y, month=mo, day=d, hour=hh, minute=mm, second=0, microsecond=0)
        except ValueError as e:
            raise TimeParseError(str(e)) from e
        if when <= now:
            raise TimeParseError("that time has already passed")
        return when

    dur = parse_duration(t)
    if dur is not None and (
        re.match(r"^\s*(in|after|for)\b", t)
        or (not _clock(t) and not re.search(r"\b(at|tomorrow|today|tonight|on)\b", t))
    ):
        return (now + dur).replace(microsecond=0)

    day = now
    explicit_day = False
    weekday_is_today = False
    if re.search(r"\bday after tomorrow\b", t):
        day, explicit_day = now + timedelta(days=2), True
    elif re.search(r"\b(tomorrow|tmrw|tmr)\b", t):
        day, explicit_day = now + timedelta(days=1), True
    elif re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", t):
        explicit_day = True
    else:
        for name, idx in _WEEKDAYS.items():
            if re.search(rf"\b{name}\b", t):
                ahead = (idx - now.weekday()) % 7
                if re.search(rf"\bnext\s+{name}\b", t):
                    ahead = ahead or 7
                weekday_is_today = ahead == 0
                day, explicit_day = now + timedelta(days=ahead), True
                break

    clock = _clock(t)
    if clock is None:
        part = _part_of_day(t)
        if part is not None:
            clock = (part, 0, False)
        elif explicit_day and day.date() != now.date():
            clock = (9, 0, False)
        else:
            raise TimeParseError(f"couldn't find a time in {raw!r}")

    hour, minute, ambiguous = clock
    base = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if ambiguous:
        if day.date() == now.date() and not conventional:
            # "at 6:30" → whichever of 6:30 am / pm comes next
            for cand in (base, base + timedelta(hours=12), base + timedelta(days=1)):
                if cand > now:
                    return cand
        # 1–6 means afternoon/evening, 7–11 morning
        base = base + timedelta(hours=12) if hour <= 6 else base
        if base <= now:
            base += timedelta(days=7 if weekday_is_today else 1)
        return base
    if base <= now:
        if weekday_is_today:
            return base + timedelta(days=7)
        if explicit_day and day.date() != now.date():
            raise TimeParseError("that time has already passed")
        base += timedelta(days=1)
    return base


@dataclass(frozen=True)
class Repeat:
    """How a reminder recurs. ``kind`` is interval | daily | weekdays | weekly."""

    kind: str
    seconds: int = 0
    weekday: Optional[int] = None

    def spec(self) -> str:
        if self.kind == "interval":
            return f"interval:{self.seconds}"
        if self.kind == "weekly" and self.weekday is not None:
            return f"weekly:{self.weekday}"
        return self.kind

    @classmethod
    def from_spec(cls, spec: str) -> Optional[Repeat]:
        spec = (spec or "").strip()
        if not spec:
            return None
        kind, _, arg = spec.partition(":")
        if kind == "interval":
            return cls("interval", seconds=int(arg))
        if kind == "weekly":
            return cls("weekly", weekday=int(arg) if arg else None)
        if kind in ("daily", "weekdays"):
            return cls(kind)
        raise ValueError(f"bad repeat spec {spec!r}")

    def describe(self) -> str:
        if self.kind == "interval":
            s = self.seconds
            if s % 3600 == 0:
                n = s // 3600
                return "every hour" if n == 1 else f"every {n} hours"
            n = s // 60
            return "every minute" if n == 1 else f"every {n} minutes"
        if self.kind == "weekly" and self.weekday is not None:
            name = [k for k, v in _WEEKDAYS.items() if v == self.weekday and len(k) > 3][0]
            return f"every {name.capitalize()}"
        return {"daily": "every day", "weekdays": "every weekday", "weekly": "every week"}[self.kind]


_MIN_INTERVAL_S = 60


def parse_repeat(text: str) -> Optional[Repeat]:
    """"daily", "every weekday", "every 2 hours", "every monday" → :class:`Repeat`."""
    t = (text or "").strip().lower()
    if not t or t in ("no", "none", "once", "never", "false"):
        return None
    if re.search(r"\b(weekdays?|every weekday|work ?days?|mon(day)?\s*(-|to|through)\s*fri(day)?)\b", t):
        return Repeat("weekdays")
    if re.search(r"\b(daily|every ?day|each day|every morning|every evening|every night)\b", t):
        return Repeat("daily")
    for name, idx in _WEEKDAYS.items():
        if re.search(rf"\b(every|each)\s+{name}s?\b|\b{name}s\b", t):
            return Repeat("weekly", weekday=idx)
    if re.search(r"\b(weekly|every week|each week)\b", t):
        return Repeat("weekly")
    if re.search(r"\b(hourly|every hour|each hour)\b", t):
        return Repeat("interval", seconds=3600)
    if re.search(r"\b(every|each)\b", t):
        dur = parse_duration(t)
        if dur is not None:
            secs = int(dur.total_seconds())
            if secs < _MIN_INTERVAL_S:
                raise TimeParseError("reminders can't repeat more often than once a minute")
            if secs % 86400 == 0 and secs // 86400 == 1:
                return Repeat("daily")
            if secs % 604800 == 0 and secs // 604800 == 1:
                return Repeat("weekly")
            return Repeat("interval", seconds=secs)
    raise TimeParseError(f"couldn't understand how often: {text!r}")


def next_occurrence(due: datetime, repeat: Repeat, now: Optional[datetime] = None) -> datetime:
    """The first occurrence of ``repeat`` after both ``due`` and ``now`` (skips missed ones)."""
    now = (now or datetime.now()).astimezone()
    nxt = due
    for _ in range(100_000):
        if repeat.kind == "interval":
            step = timedelta(seconds=max(repeat.seconds, _MIN_INTERVAL_S))
            if nxt <= now:
                # jump straight past ``now`` instead of looping per interval
                missed = int((now - nxt) / step) + 1
                nxt = nxt + step * missed
            else:
                nxt = nxt + step
        elif repeat.kind == "daily":
            nxt = nxt + timedelta(days=1)
        elif repeat.kind == "weekly":
            nxt = nxt + timedelta(days=7)
        elif repeat.kind == "weekdays":
            nxt = nxt + timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt = nxt + timedelta(days=1)
        if nxt > now and nxt > due:
            return nxt
    raise ValueError("no next occurrence")


def describe_when(when: datetime, now: Optional[datetime] = None) -> str:
    """Speakable time: "at 6:30 PM", "tomorrow at 9 AM", "on Friday at 5 PM", "in 10 minutes"."""
    now = (now or datetime.now()).astimezone()
    delta = (when - now).total_seconds()
    if 0 <= delta < 3600:
        if delta < 45:
            secs = max(1, round(delta))
            return f"in {secs} second{'s' if secs != 1 else ''}"
        mins = max(1, round(delta / 60))
        return f"in {mins} minute{'s' if mins != 1 else ''}"
    clock = when.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")
    days = (when.date() - now.date()).days
    if days == 0:
        return f"at {clock}"
    if days == 1:
        return f"tomorrow at {clock}"
    if days < 7:
        return f"on {when.strftime('%A')} at {clock}"
    return f"on {when.strftime('%a %d %b')} at {clock}"
