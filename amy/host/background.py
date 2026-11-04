"""Background services: environment awareness, alerts, metric watch, idle supervisor."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Optional

from amy.hive_adapter import HiveAdapter
from amy.host.events import EventBus

_logger = logging.getLogger(__name__)

_PRESSURE_PCT = 92


def start_env_awareness(
    hive: HiveAdapter,
    bus: EventBus,
    *,
    home_label: str = "",
    home_tz: str = "",
    every_s: float = 2.5,
) -> Any:
    """Keep the foreground app + clock in the agent prompt and on the HUD env chip."""
    from amy.host.env_context import EnvAwareness, apply_to_system_prompt

    def _on_env(snap: Any) -> None:
        try:
            if hive.agent is not None:
                hive.system_prompt = apply_to_system_prompt(hive.system_prompt, snap)
            hive.set_service("amy_env", snap.as_dict())
            detail = snap.summary
            if snap.process_name or snap.window_title:
                detail = f"{snap.process_name or 'app'}" + (
                    f" — {snap.window_title}" if snap.window_title else ""
                )
                if len(detail) > 72:
                    detail = detail[:69] + "…"
            bus.note_activity("env", kind="env", detail=detail or snap.summary)
        except Exception:
            _logger.debug("env update failed", exc_info=True)

    env = EnvAwareness(
        every_s=every_s,
        on_update=_on_env,
        home_label=home_label or os.environ.get("AMY_HOME_LABEL", ""),
        tz=home_tz or os.environ.get("AMY_HOME_TZ", ""),
    )
    env.start()
    env.refresh()
    return env


def attach_alert_bus(bus: EventBus) -> None:
    """Show alerts on the activity strip (the alert bus rate-limits itself)."""
    from amy.workers.alerts import get_alert_bus

    def _on_alert(alert: Any) -> None:
        try:
            bus.note_activity(
                alert.title[:48], kind="alert", detail=(alert.detail or alert.kind)[:80]
            )
        except Exception:
            _logger.debug("alert display failed", exc_info=True)

    get_alert_bus().on_emit = _on_alert


def metric_alerts(sample: dict) -> list[dict]:
    """Alerts for sustained RAM / disk pressure in one ``sample_system()`` result."""
    out: list[dict] = []
    ram = (sample.get("ram") or {}).get("percent")
    disk = (sample.get("disk") or {}).get("percent")
    if isinstance(ram, (int, float)) and ram >= _PRESSURE_PCT:
        out.append(
            {
                "kind": "metric",
                "title": f"RAM high ({ram:.0f}%)",
                "detail": "Host memory pressure",
                "severity": 3,
                "dedupe_key": "metric:ram",
            }
        )
    if isinstance(disk, (int, float)) and disk >= _PRESSURE_PCT:
        out.append(
            {
                "kind": "metric",
                "title": f"Disk high ({disk:.0f}%)",
                "detail": (sample.get("disk") or {}).get("path") or "",
                "severity": 3,
                "dedupe_key": "metric:disk",
            }
        )
    return out


def start_metric_watch(stop: threading.Event, *, every_s: float = 60.0) -> threading.Thread:
    def _run() -> None:
        from amy.system.metrics import sample_system
        from amy.workers.alerts import get_alert_bus

        while not stop.is_set():
            try:
                ab = get_alert_bus()
                for alert in metric_alerts(sample_system()):
                    ab.post(**alert)
            except Exception:
                _logger.debug("metric watch failed", exc_info=True)
            stop.wait(every_s)

    t = threading.Thread(target=_run, name="amy-metric-watch", daemon=True)
    t.start()
    return t


def start_idle_supervisor(
    hive: HiveAdapter,
    stop: threading.Event,
    *,
    ambient_cfg: Any,
    log: Callable[[str], None],
) -> threading.Thread:
    """PyHive idle loop: heartbeat, goals, file drops, calendar, HA, screen sensors."""
    from pyhive.core.autonomy import AutonomyEngine
    from pyhive.core.goals import GoalManager
    from pyhive.core.idle import IdleSupervisor
    from pyhive.core.initiative import InitiativeEngine

    amb = ambient_cfg
    interval = float((getattr(amb, "idle_interval_s", None) if amb else None) or 5)
    allow_act = bool(getattr(amb, "allow_act", False) if amb else False)
    screen_act = bool(getattr(amb, "screen_act", False) if amb else False)
    screen_every = float(getattr(amb, "screen_every_s", None) or 90.0) if amb else 90.0

    goals = GoalManager()
    auto = AutonomyEngine(registry=hive.registry, goals=goals)

    def _run() -> None:
        from pyhive.core.idle.sensors import (
            CalendarSoonSensor,
            FileDropSensor,
            GoalWatchSensor,
            HaStateSensor,
            HeartbeatSensor,
            ScreenSensor,
        )
        from pyhive.core.presence import PresenceEngine

        sensors = [
            HeartbeatSensor(),
            GoalWatchSensor(goals=goals),
            FileDropSensor(),
            CalendarSoonSensor(within_minutes=30),
            HaStateSensor(),
            ScreenSensor(every_s=screen_every, ocr=True),
        ]
        pe = hive.bundle_services.get("presence_engine")
        if pe is None:
            pe = PresenceEngine(agent_memory=hive.memory, user_id="default")
            hive.bundle_services["presence_engine"] = pe
        hive.set_service("presence_engine", pe)
        # Idle may use presence; never inject psyche blocks into voice turns.
        hive.set_service("presence_enrichment", False)
        sup = IdleSupervisor(
            goals=goals,
            sensors=sensors,
            initiative=InitiativeEngine(allow_act=bool(allow_act or screen_act)),
            autonomy=auto,
            presence=pe,
            interval_s=interval,
            allow_act=bool(allow_act or screen_act),
            act_runner=None,
            on_notify=lambda ev: log(f"idle {getattr(ev.action, 'value', ev.action)} {ev.kind}"),
        )
        while not stop.is_set():
            try:
                sup.cycle()
            except Exception as e:
                log(f"idle error: {e}")
                _logger.debug("idle cycle failed", exc_info=True)
            stop.wait(interval)

    t = threading.Thread(target=_run, name="amy-ambient-idle", daemon=True)
    t.start()
    return t


def stop_quietly(obj: Optional[Any], what: str) -> None:
    if obj is None:
        return
    try:
        obj.stop()
    except Exception:
        _logger.debug("stopping %s failed", what, exc_info=True)
