"""Windows master volume / mute via pycaw (Core Audio)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def available() -> bool:
    try:
        from pycaw.pycaw import AudioUtilities  # noqa: F401

        return True
    except Exception:
        return False


def _speakers():
    from pycaw.pycaw import AudioUtilities

    spk = AudioUtilities.GetSpeakers()
    if spk is None:
        raise RuntimeError("No default speakers device")
    return spk


def get_volume() -> int:
    spk = _speakers()
    return int(round(float(spk.volume_percent)))


def set_volume(level: int) -> int:
    lvl = max(0, min(100, int(level)))
    spk = _speakers()
    spk.volume_percent = float(lvl)
    return get_volume()


def get_mute() -> bool:
    spk = _speakers()
    return bool(spk.EndpointVolume.GetMute())


def set_mute(muted: bool) -> bool:
    spk = _speakers()
    spk.EndpointVolume.SetMute(1 if muted else 0, None)
    return get_mute()


def toggle_mute() -> bool:
    return set_mute(not get_mute())


def volume_control(
    *, level: Optional[int] = None, delta: Optional[int] = None
) -> Dict[str, Any]:
    if level is None and delta is None:
        return {"ok": False, "error": "Pass level or delta"}
    try:
        if level is not None:
            now = set_volume(level)
            return {"ok": True, "output": f"volume={now}"}
        cur = get_volume()
        now = set_volume(cur + int(delta or 0))
        return {"ok": True, "output": f"volume={now}; delta={int(delta or 0)}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def mute_control(muted: Optional[bool] = None) -> Dict[str, Any]:
    try:
        if muted is None:
            now = toggle_mute()
        else:
            now = set_mute(bool(muted))
        return {"ok": True, "output": "muted=on" if now else "muted=off"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
