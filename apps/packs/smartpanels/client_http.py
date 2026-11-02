"""SmartPanels HTTP/API client — POST /api/auth/login."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


STORAGE_KEY = "smart_panel_session"
DEFAULT_BASE = "https://smartpanel.ssevsoftsols.co.in"


def _session_path(state: Path) -> Path:
    return state / "session.json"


def load_session(state: Path) -> Dict[str, Any]:
    path = _session_path(state)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_session(state: Path, data: Dict[str, Any]) -> None:
    state.mkdir(parents=True, exist_ok=True)
    _session_path(state).write_text(json.dumps(data, indent=2), encoding="utf-8")


def clear_session(state: Path) -> None:
    path = _session_path(state)
    if path.is_file():
        path.unlink()


def session_looks_valid(data: Dict[str, Any]) -> bool:
    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict):
        return False
    return bool(user.get("id") and user.get("username") and user.get("name"))


def login(
    *,
    email: str,
    password: str,
    base_url: str,
    state: Path,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    base = (base_url or DEFAULT_BASE).rstrip("/")
    url = f"{base}/api/auth/login"
    body = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Amy-SmartPanels/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            cookies = resp.headers.get_all("Set-Cookie") if hasattr(resp.headers, "get_all") else None
            if cookies is None:
                sc = resp.headers.get("Set-Cookie")
                cookies = [sc] if sc else []
            status = getattr(resp, "status", 200) or 200
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
        status = int(getattr(e, "code", 0) or 0)
        cookies = []
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {}
        return {
            "ok": False,
            "via": "http",
            "status": status,
            "error": str(payload.get("error") or raw or f"HTTP {status}")[:200],
        }
    except Exception as e:
        return {"ok": False, "via": "http", "error": str(e)[:200]}

    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    user = payload.get("user") if isinstance(payload, dict) else None
    if status >= 400 or not isinstance(user, dict):
        return {
            "ok": False,
            "via": "http",
            "status": status,
            "error": str(
                (payload or {}).get("error") if isinstance(payload, dict) else "login failed"
            )[:200],
        }

    data = {
        "via": "http",
        "base_url": base,
        "user": {
            "id": user.get("id"),
            "username": user.get("username"),
            "name": user.get("name"),
            # keep full user blob for localStorage inject (no password)
            **{k: v for k, v in user.items() if k not in ("password", "token_secret")},
        },
        "storage_key": STORAGE_KEY,
        "cookies": cookies or [],
    }
    save_session(state, data)
    return {"ok": True, "via": "http", "user_name": str(user.get("name") or user.get("username") or "")}


def probe_dashboard(*, base_url: str, state: Path, timeout: float = 15.0) -> Dict[str, Any]:
    """Best-effort: session file valid + base reachable."""
    sess = load_session(state)
    valid = session_looks_valid(sess)
    base = (base_url or sess.get("base_url") or DEFAULT_BASE).rstrip("/")
    reachable = False
    status = 0
    try:
        req = urllib.request.Request(
            f"{base}/",
            headers={"User-Agent": "Amy-SmartPanels/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200) or 200
            reachable = status < 500
    except Exception:
        reachable = False
    return {
        "ok": valid and reachable,
        "session_valid": valid,
        "reachable": reachable,
        "status": status,
        "base_url": base,
        "user_name": (sess.get("user") or {}).get("name") if valid else "",
    }


def _request_json(
    *,
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Amy-SmartPanels/1.0",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = getattr(resp, "status", 200) or 200
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
        status = int(getattr(e, "code", 0) or 0)
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {"error": raw[:200] or f"HTTP {status}"}
        return {"ok": False, "status": status, "data": data, "error": str(data.get("error") or f"HTTP {status}")[:200]}
    except Exception as e:
        return {"ok": False, "status": 0, "data": {}, "error": str(e)[:200]}
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}
    if status >= 400:
        return {
            "ok": False,
            "status": status,
            "data": data if isinstance(data, dict) else {},
            "error": str((data or {}).get("error") if isinstance(data, dict) else raw)[:200],
        }
    return {"ok": True, "status": status, "data": data if isinstance(data, dict) else {}}


def list_rooms(*, base_url: str, timeout: float = 15.0) -> Dict[str, Any]:
    base = (base_url or DEFAULT_BASE).rstrip("/")
    out = _request_json(method="GET", url=f"{base}/api/rooms", timeout=timeout)
    if not out.get("ok"):
        return out
    rooms = (out.get("data") or {}).get("rooms") or []
    slim = []
    for r in rooms:
        if not isinstance(r, dict):
            continue
        slim.append(
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "lightsOn": bool(r.get("lightsOn")),
                "fansOn": bool(r.get("fansOn")),
                "boards": [
                    {
                        "id": b.get("id"),
                        "name": b.get("name"),
                        "online": bool(b.get("online")),
                        "poweredOn": bool(b.get("poweredOn")),
                    }
                    for b in (r.get("boards") or [])
                    if isinstance(b, dict)
                ],
            }
        )
    return {"ok": True, "rooms": slim}


def find_room(rooms: list, query: str) -> Optional[Dict[str, Any]]:
    q = re.sub(r"\s+", " ", (query or "").strip().lower())
    if not q:
        return None
    # normalize speech: "meeting room" / "the meeting" / "meetingroom"
    q = q.replace("the ", "").strip()
    aliases = {
        "meeting": "meeting room",
        "meeting room": "meeting room",
        "conference": "meeting room",
        "director": "director",
        "hardware": "hardware room",
        "hardware room": "hardware room",
        "workspace 1": "workspace1",
        "workspace one": "workspace1",
        "workspace 2": "workspace2",
        "workspace two": "workspace2",
        "workspace 3": "workspace3",
        "workspace three": "workspace3",
        "workspace 4": "workspace4",
        "workspace four": "workspace4",
    }
    qn = aliases.get(q, q)
    exact = None
    partial = None
    for r in rooms:
        name = str(r.get("name") or "").strip()
        nl = name.lower().replace(" ", "")
        ql = qn.lower().replace(" ", "")
        if name.lower() == qn.lower() or nl == ql:
            exact = r
            break
        if ql in nl or nl in ql or qn.lower() in name.lower():
            partial = partial or r
    return exact or partial


def patch_room(
    *,
    base_url: str,
    room_id: str,
    lights_on: Optional[bool] = None,
    fans_on: Optional[bool] = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    base = (base_url or DEFAULT_BASE).rstrip("/")
    payload: Dict[str, Any] = {}
    if lights_on is not None:
        payload["lightsOn"] = bool(lights_on)
    if fans_on is not None:
        payload["fansOn"] = bool(fans_on)
    if not payload:
        return {"ok": False, "error": "nothing to change"}
    out = _request_json(
        method="PATCH",
        url=f"{base}/api/rooms/{room_id}",
        payload=payload,
        timeout=timeout,
    )
    if not out.get("ok"):
        return out
    room = (out.get("data") or {}).get("room") or {}
    return {
        "ok": True,
        "room": {
            "id": room.get("id"),
            "name": room.get("name"),
            "lightsOn": bool(room.get("lightsOn")),
            "fansOn": bool(room.get("fansOn")),
        },
    }


def patch_board(
    *,
    base_url: str,
    board_id: str,
    powered_on: bool,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    base = (base_url or DEFAULT_BASE).rstrip("/")
    out = _request_json(
        method="PATCH",
        url=f"{base}/api/boards/{board_id}",
        payload={"poweredOn": bool(powered_on)},
        timeout=timeout,
    )
    if not out.get("ok"):
        return out
    board = (out.get("data") or {}).get("board") or {}
    return {
        "ok": True,
        "board": {
            "id": board.get("id"),
            "name": board.get("name"),
            "poweredOn": bool(powered_on),
            "online": bool(board.get("online")),
        },
    }
