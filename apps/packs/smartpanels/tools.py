"""Register smartpanels_* tools on the Hive registry."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def smartpanels_status() -> Dict[str, Any]:
    """Check SmartPanels secrets and session (never returns credentials)."""
    import client

    return client.status()


def smartpanels_login(prefer_browser: bool = False) -> Dict[str, Any]:
    """Log into Smart Panel. HTTP first; Playwright on failure. Never echoes secrets."""
    import client

    out = client.login(prefer_browser=bool(prefer_browser))
    return {k: v for k, v in out.items() if k not in ("password", "email", "user", "cookies")}


def smartpanels_open(ensure_login: bool = True) -> Dict[str, Any]:
    """Ensure logged in and open the Smart Panel dashboard in a browser."""
    import client

    out = client.open_dashboard(ensure_login=bool(ensure_login))
    return {k: v for k, v in out.items() if k not in ("password", "email", "user", "cookies")}


def smartpanels_logout() -> Dict[str, Any]:
    """Clear local SmartPanels session state."""
    import client

    return client.logout()


def smartpanels_rooms() -> Dict[str, Any]:
    """List Smart Panel rooms with lights/fans state (no credentials)."""
    import client

    return client.list_rooms()


def smartpanels_set_room(
    room: str,
    on: Optional[bool] = None,
    lights: Optional[bool] = None,
    fans: Optional[bool] = None,
    power: Optional[bool] = None,
) -> Dict[str, Any]:
    """Turn a Smart Panel room on/off. room='Meeting Room'. Prefer on=True for full room power."""
    import client

    return client.set_room(room, on=on, lights=lights, fans=fans, power=power)


def register(registry: Any) -> List[str]:
    specs = [
        (
            smartpanels_status,
            "Check whether SmartPanels secrets and session are ready (no credentials returned).",
        ),
        (
            smartpanels_login,
            "Log into Smart Panel (HTTP first, Playwright fallback). Requires ~/.amy/secrets/smartpanels.env.",
        ),
        (
            smartpanels_open,
            "Open Smart Panel dashboard (logs in first if needed). Never speak passwords.",
        ),
        (
            smartpanels_logout,
            "Clear local SmartPanels session / storage state.",
        ),
        (
            smartpanels_rooms,
            "List Smart Panel rooms (Meeting Room, Director, Workspaces…) with lights/fans state.",
        ),
        (
            smartpanels_set_room,
            "Control a Smart Panel room: room='Meeting Room', on=true/false "
            "(or lights=/fans=/power=). Use for 'turn on the meeting room'.",
        ),
    ]
    out: List[str] = []
    for fn, desc in specs:
        name = fn.__name__
        try:
            registry.register(
                fn, name=name, description=desc, module="amy_smartpanels", overwrite=True
            )
            out.append(name)
        except Exception:
            pass
    return out
