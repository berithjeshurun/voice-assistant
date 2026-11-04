"""Bambu Lab printer integration (LAN status + basic control)."""

from __future__ import annotations

import json
import os
import socket
from typing import Any, Dict, List


def apply_config(config: Any = None) -> None:
    """Push hive.yaml ``amy.bambu`` / ``bambu`` fields into env for tools."""
    raw = None
    if config is None:
        return
    if isinstance(config, dict):
        raw = config.get("bambu") or (config.get("amy") or {}).get("bambu")
    else:
        raw = getattr(config, "bambu", None)
        if raw is None:
            amy = getattr(config, "amy", None)
            raw = getattr(amy, "bambu", None) if amy is not None else None
        if raw is None:
            data = getattr(config, "_raw", None) or getattr(config, "raw", None)
            if isinstance(data, dict):
                raw = data.get("bambu") or (data.get("amy") or {}).get("bambu")
    if raw is None:
        return
    mapping = {
        "host": "AMY_BAMBU_HOST",
        "serial": "AMY_BAMBU_SERIAL",
        "access_code": "AMY_BAMBU_ACCESS_CODE",
        "mqtt_port": "AMY_BAMBU_MQTT_PORT",
    }
    for key, env in mapping.items():
        if isinstance(raw, dict):
            val = raw.get(key)
        else:
            val = getattr(raw, key, None)
        if val not in (None, ""):
            os.environ[env] = str(val)


def _settings() -> Dict[str, Any]:
    return {
        "host": os.environ.get("AMY_BAMBU_HOST", "").strip(),
        "serial": os.environ.get("AMY_BAMBU_SERIAL", "").strip(),
        "access_code": os.environ.get("AMY_BAMBU_ACCESS_CODE", "").strip(),
        "mqtt_port": int(os.environ.get("AMY_BAMBU_MQTT_PORT", "8883") or 8883),
    }


def _tcp_probe(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _mqtt_publish(
    *,
    host: str,
    port: int,
    serial: str,
    access_code: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        import paho.mqtt.publish as publish  # type: ignore
    except Exception:
        return {
            "ok": False,
            "error": "paho-mqtt not installed — pip install paho-mqtt for live control",
            "payload": payload,
        }
    topic = f"device/{serial}/request"
    try:
        publish.single(
            topic,
            payload=json.dumps(payload),
            hostname=host,
            port=int(port),
            auth={"username": "bblp", "password": access_code},
            tls={"insecure": True},
            qos=1,
        )
        return {"ok": True, "topic": topic, "sent": payload}
    except Exception as e:
        try:
            publish.single(
                topic,
                payload=json.dumps(payload),
                hostname=host,
                port=1883,
                auth={"username": "bblp", "password": access_code},
                qos=1,
            )
            return {"ok": True, "topic": topic, "sent": payload, "port": 1883}
        except Exception as e2:
            return {"ok": False, "error": f"{e}; {e2}", "topic": topic}


def bambu_status(
    host: str = "",
    serial: str = "",
    access_code: str = "",
) -> Dict[str, Any]:
    """Check Bambu Lab printer reachability on LAN (host from config if omitted)."""
    cfg = _settings()
    h = (host or cfg["host"]).strip()
    s = (serial or cfg["serial"]).strip()
    code = (access_code or cfg["access_code"]).strip()
    port = int(cfg["mqtt_port"])
    if not h:
        return {
            "ok": False,
            "error": "No printer host — set amy.bambu.host in hive.yaml or AMY_BAMBU_HOST",
            "hint": "Bambu LAN IP from printer screen / Bambu Studio device list",
        }
    mqtt_up = _tcp_probe(h, port) or _tcp_probe(h, 1883)
    cam_up = _tcp_probe(h, 322) or _tcp_probe(h, 6000)
    return {
        "ok": bool(mqtt_up or cam_up),
        "host": h,
        "serial": s or None,
        "mqtt_reachable": mqtt_up,
        "camera_or_ftps_reachable": cam_up,
        "configured": bool(h and s and code),
        "message": (
            "Printer answers on LAN."
            if mqtt_up or cam_up
            else "Host not reachable — check power, Wi‑Fi, and IP."
        ),
    }


def bambu_control(
    action: str,
    host: str = "",
    serial: str = "",
    access_code: str = "",
) -> Dict[str, Any]:
    """Control printer: pause | resume | stop | home | light_on | light_off."""
    act = (action or "").strip().lower().replace("-", "_").replace(" ", "_")
    cfg = _settings()
    h = (host or cfg["host"]).strip()
    s = (serial or cfg["serial"]).strip()
    # The configured access code is only ever sent to the configured printer.
    if h == cfg["host"]:
        code = (access_code or cfg["access_code"]).strip()
    else:
        code = (access_code or "").strip()
    port = int(cfg["mqtt_port"])
    if not h or not s or not code:
        return {
            "ok": False,
            "error": "Need host, serial, and access_code (hive.yaml amy.bambu or env)",
        }

    commands: Dict[str, Dict[str, Any]] = {
        "pause": {"print": {"command": "pause", "param": ""}},
        "resume": {"print": {"command": "resume", "param": ""}},
        "stop": {"print": {"command": "stop", "param": ""}},
        "cancel": {"print": {"command": "stop", "param": ""}},
        "home": {"print": {"command": "gcode_line", "param": "G28\n"}},
        "light_on": {
            "system": {
                "command": "ledctrl",
                "led_node": "chamber_light",
                "led_mode": "on",
            }
        },
        "light_off": {
            "system": {
                "command": "ledctrl",
                "led_node": "chamber_light",
                "led_mode": "off",
            }
        },
    }
    payload = commands.get(act)
    if payload is None:
        return {
            "ok": False,
            "error": f"Unknown action {action!r}",
            "supported": list(commands.keys()),
        }
    result = _mqtt_publish(
        host=h, port=port, serial=s, access_code=code, payload=payload
    )
    result["action"] = act
    result["host"] = h
    return result


def register(registry: Any, *, config: Any = None) -> List[str]:
    apply_config(config)
    specs = [
        (bambu_status, "Check Bambu Lab printer LAN reachability / config."),
        (
            bambu_control,
            "Control Bambu Lab printer: pause, resume, stop, home, light_on, light_off.",
        ),
    ]
    out: List[str] = []
    for fn, desc in specs:
        try:
            registry.register(
                fn,
                name=fn.__name__,
                description=desc,
                module="amy_bambu",
                overwrite=True,
            )
            out.append(fn.__name__)
        except Exception:
            continue
    return out
