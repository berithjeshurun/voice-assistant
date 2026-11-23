from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from amy.reminders.timeparse import (
    Repeat,
    TimeParseError,
    describe_when,
    next_occurrence,
    parse_duration,
    parse_repeat,
    parse_when,
)

# Wednesday 11 Nov 2026, 10:00 local
NOW = datetime(2026, 11, 11, 10, 0).astimezone()


def at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    return (NOW + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)


@pytest.mark.parametrize(
    "text,seconds",
    [
        ("10 minutes", 600),
        ("10m", 600),
        ("1 hour 30 minutes", 5400),
        ("an hour and a half", 5400),
        ("1 and a half hours", 5400),
        ("half an hour", 1800),
        ("quarter of an hour", 900),
        ("90 seconds", 90),
        ("two hours", 7200),
        ("a minute", 60),
        ("2h 15m", 8100),
    ],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == timedelta(seconds=seconds)


@pytest.mark.parametrize("text", ["at 6 am", "6 am", "tomorrow", "soon", ""])
def test_parse_duration_ignores_non_durations(text):
    assert parse_duration(text) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("in 10 minutes", NOW + timedelta(minutes=10)),
        ("in an hour", NOW + timedelta(hours=1)),
        ("20 min", NOW + timedelta(minutes=20)),
        ("at 6pm", at(0, 18)),
        ("at 6:30 pm", at(0, 18, 30)),
        ("6.45pm", at(0, 18, 45)),
        ("at 18:30", at(0, 18, 30)),
        ("at 9am", at(1, 9)),  # 9 am already passed today
        ("at 6", at(0, 18)),  # ambiguous → next one (6 pm)
        ("at 11", at(0, 11)),  # ambiguous → 11 am still ahead
        ("at 6:30", at(0, 18, 30)),
        ("noon", at(0, 12)),
        ("midnight", at(1, 0)),
        ("tomorrow", at(1, 9)),
        ("tomorrow at 7", at(1, 7)),
        ("tomorrow at 5", at(1, 17)),
        ("tomorrow at 8pm", at(1, 20)),
        ("tomorrow morning", at(1, 9)),
        ("tonight", at(0, 20)),
        ("tonight at 9", at(0, 21)),
        ("this evening", at(0, 19)),
        ("in the morning", at(1, 9)),
        ("on friday at 5pm", at(2, 17)),
        ("friday", at(2, 9)),
        ("next wednesday at 10am", at(7, 10)),
        ("wednesday at 3pm", at(0, 15)),  # today, still ahead
        ("wednesday at 9am", at(7, 9)),  # today, already passed → next week
        ("day after tomorrow at 9am", at(2, 9)),
        ("2026-12-25 08:00", datetime(2026, 12, 25, 8, 0).astimezone()),
    ],
)
def test_parse_when(text, expected):
    assert parse_when(text, NOW) == expected


@pytest.mark.parametrize("text", ["", "whenever", "2020-01-01 10:00", "at 25:00"])
def test_parse_when_rejects(text):
    with pytest.raises(TimeParseError):
        parse_when(text, NOW)


def test_parse_when_always_future():
    for text in ("at 10", "at 10am", "at 9:59"):
        assert parse_when(text, NOW) > NOW


@pytest.mark.parametrize(
    "text,spec",
    [
        ("daily", "daily"),
        ("every day", "daily"),
        ("every weekday", "weekdays"),
        ("weekdays", "weekdays"),
        ("every monday", "weekly:0"),
        ("fridays", "weekly:4"),
        ("weekly", "weekly"),
        ("hourly", "interval:3600"),
        ("every 2 hours", "interval:7200"),
        ("every 30 minutes", "interval:1800"),
        ("every 24 hours", "daily"),
    ],
)
def test_parse_repeat(text, spec):
    rule = parse_repeat(text)
    assert rule is not None and rule.spec() == spec
    assert Repeat.from_spec(spec) == rule


def test_parse_repeat_none_and_errors():
    assert parse_repeat("") is None
    assert parse_repeat("once") is None
    with pytest.raises(TimeParseError):
        parse_repeat("every 10 seconds")
    with pytest.raises(TimeParseError):
        parse_repeat("sometimes")


def test_next_occurrence():
    due = at(0, 9)  # 9 am today (already passed)
    assert next_occurrence(due, Repeat("daily"), NOW) == at(1, 9)
    assert next_occurrence(at(2, 9), Repeat("weekdays"), at(2, 9, 1)) == at(5, 9)  # Fri → Mon
    assert next_occurrence(at(0, 9), Repeat("weekly"), NOW) == at(7, 9)
    # interval reminders skip the ones missed while Amy was off
    nxt = next_occurrence(NOW - timedelta(hours=5, minutes=10), Repeat("interval", seconds=3600), NOW)
    assert NOW < nxt <= NOW + timedelta(hours=1)


def test_describe_when():
    assert describe_when(NOW + timedelta(minutes=10), NOW) == "in 10 minutes"
    assert describe_when(NOW + timedelta(seconds=30), NOW) == "in 30 seconds"
    assert describe_when(NOW + timedelta(seconds=59), NOW) == "in 1 minute"
    assert describe_when(at(0, 18, 30), NOW) == "at 6:30 PM"
    assert describe_when(at(1, 9), NOW) == "tomorrow at 9 AM"
    assert describe_when(at(2, 17), NOW) == "on Friday at 5 PM"
    assert Repeat("weekly", weekday=0).describe() == "every Monday"
    assert Repeat("interval", seconds=7200).describe() == "every 2 hours"
