"""Windows chrome helpers — frameless DWM rounded corners for Amy windows."""

from __future__ import annotations

import sys
import threading
import time
from typing import Optional


# DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3  # ~7px on Win11


def apply_dwm_corners(hwnd: int, *, preference: int = DWMWCP_ROUNDSMALL) -> bool:
    """Ask DWM for small rounded corners on a frameless HWND (Win11+)."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        dwmapi = ctypes.windll.dwmapi
        val = wintypes.DWORD(int(preference))
        hr = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(int(hwnd)),
            33,  # DWMWA_WINDOW_CORNER_PREFERENCE
            ctypes.byref(val),
            ctypes.sizeof(val),
        )
        return int(hr) == 0
    except Exception:
        return False


def find_hwnd_by_title(title_substr: str) -> Optional[int]:
    if sys.platform != "win32":
        return None
    needle = (title_substr or "").strip().lower()
    if not needle:
        return None
    found: list[int] = []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lp):  # type: ignore[misc]
            if not user32.IsWindowVisible(hwnd):
                return True
            length = int(user32.GetWindowTextLengthW(hwnd))
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 2)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = (buf.value or "").lower()
            if needle in title:
                found.append(int(hwnd))
            return True

        user32.EnumWindows(_enum, 0)
    except Exception:
        return None
    return found[0] if found else None


def style_amy_window(
    title_hint: str = "Amy",
    *,
    preference: int = DWMWCP_ROUNDSMALL,
    retries: int = 8,
    delay_s: float = 0.25,
) -> bool:
    """Best-effort: find Amy window and apply DWM small rounds."""

    def _run() -> None:
        for _ in range(max(1, retries)):
            hwnd = find_hwnd_by_title(title_hint)
            if hwnd and apply_dwm_corners(hwnd, preference=preference):
                return
            time.sleep(delay_s)

    threading.Thread(target=_run, name="amy-dwm-corners", daemon=True).start()
    return True
