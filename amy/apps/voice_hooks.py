"""Amy-side voice shortcuts for enabled apps (never speak secrets)."""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

from pyhive.core.host.dual_reply import DualReply


def _normalize_sp_transcript(text: str) -> str:
    """Fix common STT misspellings for Smart Panel / rooms."""
    t = (text or "").strip()
    # smartpannel / smart panel / smartpanels
    t = re.sub(r"\bsmart\s*pann?els?\b", "smart panel", t, flags=re.I)
    t = re.sub(r"\bmeetin(?:g)?\s*rooms?\b", "meeting room", t, flags=re.I)
    t = re.sub(r"\bhard\s*ware\s*rooms?\b", "hardware room", t, flags=re.I)
    return t


_SMARTPANEL_OPEN_RE = re.compile(
    r"\b("
    r"log\s*in(?:to)?\s+(?:to\s+)?smart\s*panels?"
    r"|sign\s*in(?:to)?\s+(?:to\s+)?smart\s*panels?"
    r"|open\s+smart\s*panels?"
    r"|launch\s+smart\s*panels?"
    r"|smart\s*panels?\s+(?:login|log\s*in|open|dashboard)"
    r")\b",
    re.I,
)

# "turn on the meeting room" / "switch off meeting room lights" / "meeting room on"
_ROOM_CTRL_RE = re.compile(
    r"\b(?:"
    r"(?:turn|switch|power|set)\s+(?P<verb_on>on|off)\s+(?:the\s+)?(?P<room1>.+?)"
    r"|(?P<room2>meeting(?:\s+room)?|director|hardware(?:\s+room)?|workspace\s*[1-4]|workspace\s+(?:one|two|three|four))"
    r"\s+(?P<verb_trail>on|off)"
    r")\b",
    re.I,
)

_ROOM_ONLY_HINT = re.compile(
    r"\b(meeting\s*room|smart\s*panels?|director(?:'s)?\s+room|hardware\s*room|workspace\s*[1-4])\b",
    re.I,
)

_LIGHTS_RE = re.compile(r"\blights?\b", re.I)
_FANS_RE = re.compile(r"\bfans?\b", re.I)


def _safe_speak(text: str) -> str:
    """Refuse to speak anything that looks like credentials."""
    s = (text or "").strip()
    if not s:
        return "Done."
    lower = s.lower()
    if "password" in lower or "smartpanels_password" in lower:
        return "Smart Panel action finished."
    # Drop PRESENT banners if they leaked in
    s = re.sub(r"\[PRESENT[^\]]*\]\s*", "", s, flags=re.I).strip()
    return s[:220] or "Done."


def _load_sp_client():
    import importlib.util
    import sys

    from amy.apps.loader import get_pack

    pack = get_pack("smartpanels")
    if not pack:
        return None, "SmartPanels pack is not installed."
    pack_dir = str(pack["path"])
    if pack_dir not in sys.path:
        sys.path.insert(0, pack_dir)
    client_path = pack["path"] / "client.py"
    spec = importlib.util.spec_from_file_location(
        "amy_pack_smartpanels_client", client_path
    )
    if spec is None or spec.loader is None:
        return None, "SmartPanels client failed to load."
    mod = importlib.util.module_from_spec(spec)
    sys.modules["amy_pack_smartpanels_client"] = mod
    spec.loader.exec_module(mod)
    return mod, None


def _parse_room_control(text: str) -> Optional[Tuple[str, bool, Optional[bool], Optional[bool]]]:
    """Return (room_query, on, lights_only_or_None, fans_only_or_None) or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    # Must look like room/smartpanel control, not calendar "meeting"
    if not _ROOM_ONLY_HINT.search(raw) and not re.search(
        r"\b(?:lights?|fans?)\b", raw, re.I
    ):
        # allow "turn on the meeting" without "room"
        if not re.search(r"\bmeeting\b", raw, re.I):
            return None
        if re.search(r"\b(schedule|calendar|appointment|invite)\b", raw, re.I):
            return None

    m = _ROOM_CTRL_RE.search(raw)
    if not m:
        # "can you turn on the meeting room" — verb may be before room with filler
        m2 = re.search(
            r"\b(?:turn|switch|power)\s+(on|off)\b.*?\b(meeting(?:\s+room)?|director|hardware(?:\s+room)?|workspace\s*[1-4])\b",
            raw,
            re.I,
        )
        if not m2:
            return None
        on = m2.group(1).lower() == "on"
        room = m2.group(2)
    else:
        if m.group("verb_on"):
            on = m.group("verb_on").lower() == "on"
            room = (m.group("room1") or "").strip()
            # strip trailing "lights/fans/please"
            room = re.sub(
                r"\b(lights?|fans?|please|for me|now)\b.*$",
                "",
                room,
                flags=re.I,
            ).strip()
        else:
            on = m.group("verb_trail").lower() == "on"
            room = (m.group("room2") or "").strip()

    if not room:
        return None
    # Drop leading articles
    room = re.sub(r"^(the|a|an)\s+", "", room, flags=re.I).strip()
    if not room:
        return None

    lights: Optional[bool] = None
    fans: Optional[bool] = None
    if _LIGHTS_RE.search(raw) and not _FANS_RE.search(raw):
        lights = on
    elif _FANS_RE.search(raw) and not _LIGHTS_RE.search(raw):
        fans = on
    # else full room via on=
    return room, on, lights, fans


def try_smartpanels_shortcut(text: str, *, config: Any = None) -> Optional[DualReply]:
    """SmartPanels open/login or room on/off — when pack enabled."""
    raw = _normalize_sp_transcript(text or "")
    if not raw:
        return None

    from amy.apps.loader import enabled_pack_ids

    if "smartpanels" not in {x.lower() for x in enabled_pack_ids(config)}:
        return None

    open_hit = bool(_SMARTPANEL_OPEN_RE.search(raw))
    ctrl = _parse_room_control(raw)
    if not open_hit and ctrl is None:
        return None

    try:
        sp_client, err = _load_sp_client()
        if sp_client is None:
            line = err or "SmartPanels unavailable."
            return DualReply(text=line, speak=line, parsed=True)

        if ctrl is not None:
            room, on, lights, fans = ctrl
            if lights is not None or fans is not None:
                out = sp_client.set_room(
                    room,
                    lights=lights,
                    fans=fans,
                    power=on,
                )
            else:
                out = sp_client.set_room(room, on=on)

            if out.get("ok"):
                rname = (out.get("room") or {}).get("name") or room
                state = "on" if on else "off"
                if lights is not None and fans is None:
                    line = f"Turning {rname} lights {state}."
                elif fans is not None and lights is None:
                    line = f"Turning {rname} fans {state}."
                else:
                    line = f"Turning {rname} {state}."
                offline = out.get("offline_boards") or []
                if offline:
                    names = ", ".join(str(x) for x in offline[:3])
                    line = (
                        f"{line} Warning: {names} is offline, "
                        "so some devices may not respond."
                    )
                return DualReply(text=line, speak=_safe_speak(line), parsed=True)
            err = str(out.get("error") or "control failed")
            if "password" in err.lower():
                err = "control failed"
            line = f"Couldn't control that room: {err}."
            return DualReply(text=line, speak=_safe_speak(line), parsed=True)

        # open / login path
        st = sp_client.status()
        if not st.get("secrets_present"):
            line = (
                "Smart Panel secrets are missing. "
                "Add them with amy apps install smartpanels, then edit the secrets file."
            )
            return DualReply(text=line, speak=_safe_speak(line), parsed=True)

        opened = sp_client.open_dashboard(ensure_login=True)
        if opened.get("ok"):
            name = opened.get("user_name") or ""
            if name and "@" not in str(name):
                line = f"Opening Smart Panel for {name}."
            else:
                line = "Opening Smart Panel."
            return DualReply(text=line, speak=_safe_speak(line), parsed=True)

        err = str(opened.get("error") or "could not open")
        if "password" in err.lower() or "secret" in err.lower():
            err = "login failed"
        line = f"Smart Panel failed: {err}."
        return DualReply(text=line, speak=_safe_speak(line), parsed=True)
    except Exception as e:
        line = "Smart Panel shortcut hit an error."
        return DualReply(text=f"{line} ({e})", speak=line, parsed=True)


def try_app_voice_shortcut(text: str, *, config: Any = None) -> Optional[DualReply]:
    """Try all Amy app voice shortcuts. Returns DualReply or None."""
    hit = try_smartpanels_shortcut(text, config=config)
    if hit is not None:
        return hit
    return None
