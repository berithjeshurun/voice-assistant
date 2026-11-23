"""Reminders: storage, scheduling, voice tools, guard rules, HUD endpoints, announcements."""

from __future__ import annotations

import threading
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from amy.guard import GuardConfig
from amy.guard.policy import READ_ONLY_TOOLS, evaluate
from amy.host.announcer import Announcer
from amy.host.events import EventBus
from amy.reminders import (
    MAX_PENDING,
    ReminderLimit,
    Reminders,
    TimeParseError,
    reminder_message,
    second_person,
    set_reminders,
)
from amy.reminders.store import ReminderStore
from amy.server.app import create_app
from amy.server.auth import DeviceRegistry
from amy.tools import reminders_tools
from amy.tools.catalog import CORE_ALLOWLIST
from tests.test_server_auth import ADMIN, H, StubHost

# Wednesday 11 Nov 2026, 10:00 local
T0 = datetime(2026, 11, 11, 10, 0).astimezone().timestamp()


class Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def rem(tmp_path):
    clock = Clock()
    fired: list = []
    r = Reminders(ReminderStore(tmp_path / "r.db"), on_fire=lambda x, missed: fired.append((x, missed)),
                  clock=clock)
    r.clock, r.fired = clock, fired  # type: ignore[attr-defined]
    set_reminders(r)
    yield r
    set_reminders(None)
    r.store.close()


def test_add_list_and_message(rem):
    out = rem.add("call mom", "at 6pm")
    assert out["message"] == "Okay, I'll remind you to call mom at 6 PM."
    out = rem.add("stand up", "in 30 minutes", "every 2 hours")
    assert out["message"].endswith("in 30 minutes, every 2 hours.")
    items = rem.list()
    assert [i["text"] for i in items] == ["stand up", "call mom"]
    assert items[0]["repeat_text"] == "every 2 hours"


def test_repeat_can_be_part_of_when(rem):
    out = rem.add("water the plants", "every day at 8am")
    assert out["repeat_text"] == "every day"


def test_repeating_reminder_reads_hours_conventionally(rem):
    # the model dropped "am": "every weekday at 9" means 9 am, not tonight at 9 pm
    out = rem.add("check email", "every weekday at 9", "every weekday")
    due = datetime.fromtimestamp(out["due_ts"])
    assert (due.hour, due.weekday()) == (9, 3)  # Thursday 9 am (Wednesday's has passed)
    assert out["message"] == "Okay, I'll remind you to check email tomorrow at 9 AM, every weekday."
    weekly = rem.add("team call", "at 5", "every friday")
    due = datetime.fromtimestamp(weekly["due_ts"])
    assert (due.hour, due.weekday()) == (17, 4)


def test_fires_once_and_marks_done(rem):
    rem.add("call mom", "in 10 minutes")
    assert rem.scheduler.run_due() == []
    rem.clock.t += 601
    fired = rem.scheduler.run_due()
    assert [f.text for f in fired] == ["call mom"]
    assert rem.fired[0][1] is False  # not missed
    assert rem.list() == []
    rem.clock.t += 3600
    assert rem.scheduler.run_due() == []


def test_repeating_reminder_reschedules(rem):
    rem.add("stretch", "in 1 hour", "hourly")
    for _ in range(3):
        rem.clock.t += 3601
        assert len(rem.scheduler.run_due()) == 1
    assert len(rem.list()) == 1
    assert rem.store.get(1).fired_count == 3


def test_missed_while_off_fires_once_with_note(rem):
    rem.add("take pills", "at 11am", "daily")
    rem.clock.t += 3 * 24 * 3600  # Amy was off for three days
    fired = rem.scheduler.run_due()
    assert len(fired) == 1 and rem.fired[0][1] is True
    assert "while I was off" in reminder_message(fired[0], True)
    nxt = rem.list()[0]
    assert nxt["due_ts"] > rem.clock.t  # next occurrence is in the future, not a backlog


def test_timer(rem):
    out = rem.timer("10 minutes", "pasta")
    assert out["message"] == "Timer set for 10 minutes."
    rem.clock.t += 600
    (r,) = rem.scheduler.run_due()
    assert reminder_message(r) == "Your pasta timer is done."
    with pytest.raises(TimeParseError):
        rem.timer("forever")
    with pytest.raises(TimeParseError):
        rem.timer("2 days")


def test_cancel_by_id_and_text(rem):
    a = rem.add("dentist appointment", "tomorrow at 9")
    rem.add("call mom", "at 6pm")
    rem.add("call dad", "at 7pm")
    assert rem.cancel(a["id"])["ok"]
    assert not rem.cancel(a["id"])["ok"]  # already cancelled
    ambiguous = rem.cancel("call")
    assert not ambiguous["ok"] and len(ambiguous["matches"]) == 2
    assert rem.cancel("dad")["message"] == "Cancelled the reminder to call dad."
    assert [i["text"] for i in rem.list()] == ["call mom"]


def test_bad_input_and_limits(rem):
    with pytest.raises(TimeParseError):
        rem.add("x", "whenever")
    with pytest.raises(ValueError):
        rem.add("   ", "in 5 minutes")
    long = rem.add("y" * 1000, "in 5 minutes")
    assert len(long["text"]) == 300
    for i in range(MAX_PENDING - 1):
        rem.store.add(f"r{i}", datetime.fromtimestamp(T0 + 3600 + i).astimezone())
    with pytest.raises(ReminderLimit):
        rem.add("one too many", "in 5 minutes")


def test_spoken_text_is_second_person(rem):
    out = rem.add("take my medicine", "at 6pm")
    assert out["message"] == "Okay, I'll remind you to take your medicine at 6 PM."
    assert rem.store.get(out["id"]).text == "take my medicine"  # stored as said
    rem.clock.t = out["due_ts"]
    (r,) = rem.scheduler.run_due()
    assert reminder_message(r) == "Reminder: take your medicine."
    t = rem.timer("5 minutes", "pasta")
    assert f"#{t['id']} pasta timer in 5 minutes" in reminders_tools.reminder_list()["message"]
    assert rem.cancel(t["id"])["message"] == "Cancelled the pasta timer."
    assert second_person("remind me to email my boss") == "remind you to email your boss"
    assert second_person("Myself and mine") == "yourself and yours"


def test_like_search_is_escaped(rem):
    rem.add("100% done", "at 6pm")
    rem.add("other", "at 7pm")
    assert [r.text for r in rem.store.find("%")] == ["100% done"]


def test_change_listener_and_upcoming(rem):
    seen = []
    rem.on_change(lambda: seen.append(len(rem.upcoming())))
    rem.add("a", "in 5 minutes")
    rem.timer("1 minute")
    rem.clock.t += 61
    rem.scheduler.run_due()
    assert seen == [1, 2, 1]
    assert rem.upcoming()[0]["kind"] == "reminder"


def test_scheduler_thread_fires_on_time(tmp_path):
    fired = threading.Event()
    r = Reminders(ReminderStore(tmp_path / "t.db"), on_fire=lambda x, m: fired.set())
    r.start()
    try:
        r.timer("1 second")
        assert fired.wait(5), "timer did not fire"
    finally:
        r.stop()
        r.store.close()


# --- voice tools + guard -----------------------------------------------------------------

def test_voice_tools(rem):
    out = reminders_tools.reminder_add("feed the cat", "in 20 minutes")
    assert out["ok"] and "feed the cat in 20 minutes" in out["message"]
    assert reminders_tools.timer_start("5 minutes")["ok"]
    listed = reminders_tools.reminder_list()
    assert "feed the cat" in listed["message"] and "timer" in listed["message"]
    bad = reminders_tools.reminder_add("x", "sometime")
    assert bad == {"ok": False, "error": "couldn't find a time in 'sometime'"}
    assert reminders_tools.reminder_cancel("cat")["ok"]


def test_voice_tools_fail_when_service_missing():
    set_reminders(None)
    out = reminders_tools.reminder_add("x", "in 5 minutes")
    assert out["ok"] is False and "not available" in out["error"]
    assert reminders_tools.reminder_list()["ok"] is False


def test_tools_are_core_and_low_risk():
    cfg = GuardConfig()
    for name in reminders_tools.TOOL_NAMES:
        assert name in CORE_ALLOWLIST
        d = evaluate(name, {"text": "x", "when": "in 5 minutes", "duration": "5m", "reminder": "1"}, cfg)
        assert d.action == "allow" and d.risk == "low"
    assert "reminder_list" in READ_ONLY_TOOLS
    # lockdown still allows listing but not creating
    locked = GuardConfig(lockdown=True)
    assert evaluate("reminder_list", {}, locked).action == "allow"
    assert evaluate("reminder_add", {"text": "x", "when": "in 5m"}, locked).action == "deny"


# --- HUD endpoints -----------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, rem):
    devices = DeviceRegistry(tmp_path / "devices.json")
    host = StubHost(tmp_path)
    host.reminders = rem
    return TestClient(create_app(host, token=ADMIN, devices=devices)), devices


def test_reminder_endpoints(api):
    c, devices = api
    viewer, user = devices.add("tv", role="viewer"), devices.add("phone", role="user")
    r = c.post("/api/reminders", json={"text": "call mom", "when": "at 6pm"}, headers=H(user))
    assert r.status_code == 200 and r.json()["reminder"]["text"] == "call mom"
    assert c.post("/api/reminders", json={"timer": "10 minutes", "text": "tea"}, headers=H(user)).status_code == 200
    assert c.post("/api/reminders", json={"text": "x", "when": "at 6pm"}, headers=H(viewer)).status_code == 403
    assert c.post("/api/reminders", json={"text": "x", "when": "someday"}, headers=H(user)).status_code == 400
    assert c.post("/api/reminders", json={"text": "", "when": ""}, headers=H(user)).status_code == 400

    listed = c.get("/api/reminders", headers=H(viewer)).json()["reminders"]
    assert {i["text"] for i in listed} == {"call mom", "tea"}
    rid = listed[0]["id"]
    assert c.delete(f"/api/reminders/{rid}", headers=H(viewer)).status_code == 403
    assert c.delete(f"/api/reminders/{rid}", headers=H(user)).status_code == 200
    assert c.delete(f"/api/reminders/{rid}", headers=H(user)).status_code == 404


def test_reminders_endpoint_without_service(tmp_path):
    c = TestClient(create_app(StubHost(tmp_path), token=ADMIN))
    assert c.get("/api/reminders", headers=H(ADMIN)).status_code == 503


# --- announcements -------------------------------------------------------------------------

def test_announcer_waits_until_idle_then_speaks():
    bus = EventBus()
    spoken: list[str] = []
    busy = threading.Event()
    busy.set()
    a = Announcer(bus, speak=spoken.append, is_busy=busy.is_set, poll_s=0.02).start()
    try:
        a.announce("Reminder: call mom.", title="Reminder: call mom", kind="reminder")
        snap = bus.snapshot()
        assert snap.activity[0].kind == "reminder"  # shown on the HUD immediately
        time.sleep(0.15)
        assert spoken == []  # not while Amy is mid-turn
        busy.clear()
        deadline = time.time() + 2
        while not spoken and time.time() < deadline:
            time.sleep(0.02)
        assert spoken == ["Reminder: call mom."]
        assert bus.snapshot().caption == "Reminder: call mom."
    finally:
        a.stop()


def test_announcer_gives_up_if_never_idle():
    spoken: list[str] = []
    a = Announcer(EventBus(), speak=spoken.append, is_busy=lambda: True, max_wait_s=0.1, poll_s=0.02).start()
    try:
        a.announce("hello")
        time.sleep(0.4)
        assert spoken == []
    finally:
        a.stop()


def test_bus_carries_reminders(rem):
    bus = EventBus()
    rem.on_change(lambda: bus.set_reminders(rem.upcoming()))
    rem.add("call mom", "at 6pm", "daily")
    (item,) = bus.snapshot().reminders
    assert item.text == "call mom" and item.repeat_text == "every day"
