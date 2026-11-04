"""Live desktop environment snapshot for Amy (foreground app, clock, home)."""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional
from zoneinfo import ZoneInfo


@dataclass
class EnvSnapshot:
    window_title: str = ""
    process_name: str = ""
    local_time: str = ""
    weekday: str = ""
    home_label: str = ""
    tz: str = ""
    summary: str = ""
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "window_title": self.window_title,
            "process_name": self.process_name,
            "local_time": self.local_time,
            "weekday": self.weekday,
            "home_label": self.home_label,
            "tz": self.tz,
            "summary": self.summary,
            "ts": self.ts,
        }


def _foreground_windows() -> tuple[str, str]:
    """Return (window_title, process_name) for the focused top-level window."""
    if sys.platform != "win32":
        return "", ""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        length = int(user32.GetWindowTextLengthW(hwnd))
        buf = ctypes.create_unicode_buffer(length + 2)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = (buf.value or "").strip()

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_name = ""
        h = kernel32.OpenProcess(0x1000, False, int(pid.value))  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            try:
                size = wintypes.DWORD(260)
                path_buf = ctypes.create_unicode_buffer(260)
                if kernel32.QueryFullProcessImageNameW(h, 0, path_buf, ctypes.byref(size)):
                    path = path_buf.value or ""
                    proc_name = os.path.basename(path).replace(".exe", "").replace(".EXE", "")
            finally:
                kernel32.CloseHandle(h)
        return title[:180], proc_name[:64]
    except Exception:
        return "", ""


def _clock(tz_name: str) -> tuple[str, str, str]:
    tz_name = (tz_name or "").strip() or os.environ.get("AMY_HOME_TZ", "").strip()
    try:
        now = datetime.now(ZoneInfo(tz_name)) if tz_name else datetime.now().astimezone()
        used_tz = tz_name or str(now.tzinfo or "")
    except Exception:
        now = datetime.now().astimezone()
        used_tz = str(now.tzinfo or "")
    return (
        now.strftime("%H:%M"),
        now.strftime("%A"),
        used_tz,
    )


def sample_env(*, home_label: str = "", tz: str = "") -> EnvSnapshot:
    home = (home_label or os.environ.get("AMY_HOME_LABEL", "")).strip()
    title, proc = _foreground_windows()
    # Don't report Amy's own orb/HUD as "the environment"
    low_title = title.lower()
    low_proc = proc.lower()
    if low_proc in ("msedge", "chrome", "python", "amy", "webview2") and (
        "amy" in low_title or "orb" in low_title or low_title in ("", "amy")
    ):
        # Keep last meaningful focus if possible — still report time/home
        title, proc = "", ""
    local_time, weekday, used_tz = _clock(tz)
    bits = []
    if proc or title:
        app = proc or "app"
        bits.append(f"{app}: {title}" if title else app)
    bits.append(f"{weekday} {local_time}")
    if home:
        bits.append(home.split(",")[0].strip())
    summary = " · ".join(bits)
    return EnvSnapshot(
        window_title=title,
        process_name=proc,
        local_time=local_time,
        weekday=weekday,
        home_label=home,
        tz=used_tz,
        summary=summary,
        ts=time.time(),
    )


def format_prompt_block(snap: EnvSnapshot) -> str:
    lines = [
        "\n\nENVIRONMENT (live — trust this over guesses):",
        f"- Local time: {snap.weekday} {snap.local_time}"
        + (f" ({snap.tz})" if snap.tz else ""),
    ]
    if snap.home_label:
        lines.append(f"- Home / locality: {snap.home_label}")
    if snap.process_name or snap.window_title:
        focus = snap.process_name or "window"
        if snap.window_title:
            focus = f"{focus} — {snap.window_title}"
        lines.append(f"- Foreground app/window: {focus}")
        lines.append(
            "- When the user says 'this', 'here', 'on screen', or 'this error', "
            "they usually mean the foreground window above."
        )
    else:
        lines.append("- Foreground app: (unknown — ask if needed)")
    lines.append(
        "- Be concise; use this context silently unless the user asks what you see."
    )
    return "\n".join(lines)


_MARKER_START = "\n\nENVIRONMENT (live"
_MARKER_END = "\n- Be concise; use this context silently unless the user asks what you see."


def apply_to_system_prompt(system_prompt: str, snap: EnvSnapshot) -> str:
    """Replace or append the ENVIRONMENT block in an agent system prompt."""
    sp = system_prompt or ""
    block = format_prompt_block(snap)
    start = sp.find(_MARKER_START)
    if start >= 0:
        end = sp.find(_MARKER_END, start)
        if end >= 0:
            end = end + len(_MARKER_END)
            return sp[:start] + block + sp[end:]
        return sp[:start] + block
    return sp + block


class EnvAwareness:
    """Background sampler that keeps Amy's prompt + HUD env chip fresh."""

    def __init__(
        self,
        *,
        every_s: float = 2.5,
        on_update: Optional[Callable[[EnvSnapshot], None]] = None,
        home_label: str = "",
        tz: str = "",
    ) -> None:
        self.every_s = max(1.0, float(every_s))
        self.on_update = on_update
        self.home_label = home_label
        self.tz = tz
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last = EnvSnapshot()

    @property
    def last(self) -> EnvSnapshot:
        with self._lock:
            return self._last

    def refresh(self) -> EnvSnapshot:
        snap = sample_env(home_label=self.home_label, tz=self.tz)
        with self._lock:
            self._last = snap
        if self.on_update:
            try:
                self.on_update(snap)
            except Exception:
                pass
        return snap

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def _loop() -> None:
            while not self._stop.is_set():
                try:
                    self.refresh()
                except Exception:
                    pass
                self._stop.wait(self.every_s)

        self._thread = threading.Thread(
            target=_loop, name="amy-env-awareness", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
