"""Screen placement for Amy companion windows (orb left, captions right, dock bottom)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def size(self) -> str:
        return f"{self.w},{self.h}"

    @property
    def position(self) -> str:
        return f"{self.x},{self.y}"


def screen_size() -> Tuple[int, int]:
    env_w = os.environ.get("AMY_SCREEN_W", "").strip()
    env_h = os.environ.get("AMY_SCREEN_H", "").strip()
    if env_w.isdigit() and env_h.isdigit():
        return int(env_w), int(env_h)
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


def orb_rect() -> Rect:
    """Compact companion orb — previous footprint, room for a larger crystal."""
    _sw, sh = screen_size()
    # Prior ship size was 360×400; nudge slightly so the orb can breathe.
    w, h = 400, 440
    env_w = os.environ.get("AMY_ORB_W", "").strip()
    env_h = os.environ.get("AMY_ORB_H", "").strip()
    if env_w.isdigit() and env_h.isdigit():
        w, h = int(env_w), int(env_h)
    margin = 28
    y = max(48, (sh - h) // 5)
    return Rect(x=margin, y=y, w=w, h=h)


def captions_rect() -> Rect:
    """Captions HUD panel — right side (activity strip lives inside this window)."""
    sw, sh = screen_size()
    w = min(480, max(400, sw // 4))
    margin = 18
    top = 28
    bottom_gap = 28
    h = max(560, sh - top - bottom_gap)
    x = max(margin, sw - w - margin)
    return Rect(x=x, y=top, w=w, h=h)


def dock_rect() -> Rect:
    """Full-width activity strip along the bottom of the screen."""
    sw, sh = screen_size()
    margin = 16
    h = 72
    w = max(640, sw - margin * 2)
    return Rect(x=margin, y=max(0, sh - h - margin), w=w, h=h)


def hud_rect() -> Rect:
    """Main Amy control-plane HUD (desktop webview app)."""
    sw, sh = screen_size()
    w = min(1080, max(860, int(sw * 0.55)))
    h = min(820, max(640, int(sh * 0.75)))
    env_w = os.environ.get("AMY_HUD_W", "").strip()
    env_h = os.environ.get("AMY_HUD_H", "").strip()
    if env_w.isdigit() and env_h.isdigit():
        w, h = int(env_w), int(env_h)
    x = max(40, (sw - w) // 2)
    y = max(36, (sh - h) // 8)
    return Rect(x=x, y=y, w=w, h=h)
