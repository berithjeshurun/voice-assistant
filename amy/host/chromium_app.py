"""Isolated Chromium/Edge app windows — no extensions, single instance per profile."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Sequence, Set

from amy.host.placement import Rect


def find_chromium() -> Optional[List[str]]:
    env = (
        os.environ.get("AMY_ORB_BROWSER", "").strip()
        or os.environ.get("AMY_CHAT_BROWSER", "").strip()
    )
    if env and Path(env).is_file():
        return [env]
    if sys.platform != "win32":
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            w = shutil.which(name)
            if w:
                return [w]
        return None
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    for c in (
        Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ):
        if c.is_file():
            return [str(c)]
    which = shutil.which("msedge") or shutil.which("chrome")
    return [which] if which else None


def profile_dir(name: str) -> Path:
    """Fresh isolated profile (v2) so old extension-tainted dirs are ignored."""
    root = Path(os.environ.get("AMY_PROFILE_ROOT") or (Path.home() / ".amy" / "profiles"))
    path = root / f"{name}-v2"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _norm(p: Path | str) -> str:
    return str(Path(p)).replace("/", "\\").lower()


def pids_for_profile(profile_name: str) -> Set[int]:
    """PIDs of Edge/Chrome processes using this Amy profile."""
    needle = _norm(profile_dir(profile_name))
    found: Set[int] = set()
    if sys.platform != "win32":
        return found
    try:
        # Prefer CIM via PowerShell — reliable CommandLine on Windows.
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" "
            "| ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }"
        )
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            if "|" not in line:
                continue
            pid_s, cmd = line.split("|", 1)
            if needle in (cmd or "").replace("/", "\\").lower():
                try:
                    found.add(int(pid_s.strip()))
                except ValueError:
                    pass
    except Exception:
        pass
    return found


def kill_profile(profile_name: str) -> int:
    """Terminate any leftover Edge/Chrome windows for this Amy profile."""
    pids = pids_for_profile(profile_name)
    n = 0
    for pid in pids:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                os.kill(pid, 9)
            n += 1
        except Exception:
            pass
    if n:
        time.sleep(0.35)
    return n


def profile_alive(profile_name: str) -> bool:
    return bool(pids_for_profile(profile_name))


def wait_for_profile_exit(profile_name: str, *, poll_s: float = 1.0) -> None:
    """Block until no browser process remains for this profile."""
    # Edge often exits the launcher PID immediately; wait on the profile instead.
    while profile_alive(profile_name):
        time.sleep(poll_s)


def app_args(
    browser: Sequence[str],
    *,
    url: str,
    profile: Path,
    rect: Rect,
    title_class: str = "AmyHUD",
) -> List[str]:
    """Build a locked-down --app= launch (no extensions / NTP / sidebar)."""
    return [
        *browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        f"--window-size={rect.size}",
        f"--window-position={rect.position}",
        f"--class={title_class}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-component-extensions-with-background-pages",
        "--disable-default-apps",
        "--disable-sync",
        "--disable-background-networking",
        "--disable-client-side-phishing-detection",
        "--disable-hang-monitor",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-domain-reliability",
        "--disable-features="
        "TranslateUI,InterestFeedContentSuggestions,"
        "msEdgeSidebar,msEdgeCollections,msEdgeShoppingCopilot,"
        "EdgeSidebar,FlashDeprecationWarning",
        "--bwsi",
    ]


def _orb_hwnds(profile_name: str) -> List[int]:
    """Visible top-level HWNDs for this Amy browser profile (Windows)."""
    if sys.platform != "win32":
        return []
    pids = pids_for_profile(profile_name)
    if not pids:
        return []
    found: List[int] = []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):  # type: ignore[misc]
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) in pids:
                found.append(int(hwnd))
            return True

        user32.EnumWindows(_enum, 0)
    except Exception:
        return []
    return found


def style_orb_windows(
    profile_name: str,
    *,
    alpha: int = 230,
    frameless: bool = True,
    topmost: bool = True,
) -> int:
    """Frameless + layered (real window alpha) + optional TOPMOST for orb windows."""
    if sys.platform != "win32":
        return 0
    hwnds = _orb_hwnds(profile_name)
    if not hwnds:
        return 0
    try:
        import ctypes

        user32 = ctypes.windll.user32
        GWL_STYLE = -16
        GWL_EXSTYLE = -20
        WS_POPUP = 0x80000000
        WS_VISIBLE = 0x10000000
        WS_CLIPSIBLINGS = 0x04000000
        WS_CLIPCHILDREN = 0x02000000
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        WS_SYSMENU = 0x00080000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000
        WS_BORDER = 0x00800000
        WS_DLGFRAME = 0x00400000
        WS_EX_LAYERED = 0x00080000
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        LWA_ALPHA = 0x02
        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        SWP_SHOWWINDOW = 0x0040
        alpha = max(40, min(255, int(alpha)))
        n = 0
        for hwnd in hwnds:
            if frameless:
                # Force popup / headerless — strips caption, - □ X, and resize frame.
                style = user32.GetWindowLongW(hwnd, GWL_STYLE)
                style &= ~(
                    WS_CAPTION
                    | WS_THICKFRAME
                    | WS_SYSMENU
                    | WS_MINIMIZEBOX
                    | WS_MAXIMIZEBOX
                    | WS_BORDER
                    | WS_DLGFRAME
                )
                style |= WS_POPUP | WS_VISIBLE | WS_CLIPSIBLINGS | WS_CLIPCHILDREN
                user32.SetWindowLongW(hwnd, GWL_STYLE, style)
                ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
                ex &= ~WS_EX_APPWINDOW
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
            else:
                ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ex |= WS_EX_LAYERED
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
            # Entire-window alpha (Win32 layered) — not CSS opacity.
            user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
            if topmost:
                user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
            else:
                user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0, flags | SWP_NOZORDER
                )
            n += 1
        return n
    except Exception:
        return 0


def pin_topmost_windows(profile_name: str, *, title_hint: str = "Amy") -> int:
    """Best-effort HWND_TOPMOST + frameless layered chrome for Amy orb windows."""
    _ = title_hint
    return style_orb_windows(profile_name, alpha=_env_alpha("engaged"), frameless=True, topmost=True)


def _env_alpha(mode: str) -> int:
    key = {
        "idle": "AMY_ORB_ALPHA_IDLE",
        "busy": "AMY_ORB_ALPHA_BUSY",
        "engaged": "AMY_ORB_ALPHA_ENGAGED",
    }.get(mode, "AMY_ORB_ALPHA_ENGAGED")
    defaults = {"idle": 150, "busy": 110, "engaged": 245}
    raw = (os.environ.get(key) or "").strip()
    if raw.isdigit():
        return max(40, min(255, int(raw)))
    return defaults.get(mode, 230)


def follow_orb_window_alpha(
    profile_name: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    token: str = "",
    stop: Optional[threading.Event] = None,
) -> None:
    """Poll Amy snapshot and set *window* layered alpha (not CSS dullness)."""
    if sys.platform != "win32":
        return
    import json
    import urllib.error
    import urllib.request

    stop = stop or threading.Event()
    tok = token or os.environ.get("AMY_TOKEN", "")
    last = -1
    ticks = 0
    while not stop.is_set():
        alpha = _env_alpha("idle")
        try:
            url = f"http://{host}:{int(port)}/api/snapshot"
            req = urllib.request.Request(url)
            if tok:
                req.add_header("X-Amy-Token", tok)
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            st = str(data.get("state") or "idle").lower()
            if st in ("speaking", "listening", "thinking", "needs_approval"):
                alpha = _env_alpha("engaged")
            elif st == "error":
                alpha = _env_alpha("engaged")
            else:
                alpha = _env_alpha("idle")
        except Exception:
            pass
        ticks += 1
        # Re-apply frameless periodically — Chromium can restore the title bar.
        if alpha != last or ticks % 4 == 1:
            style_orb_windows(
                profile_name, alpha=alpha, frameless=True, topmost=True
            )
            last = alpha
        stop.wait(0.7)


def spawn_app(
    *,
    url: str,
    profile_name: str,
    rect: Rect,
    title_class: str = "AmyHUD",
    replace_existing: bool = True,
    always_on_top: bool = False,
) -> Optional[subprocess.Popen]:
    browser = find_chromium()
    if not browser:
        return None
    if replace_existing:
        kill_profile(profile_name)
    elif profile_alive(profile_name):
        # Already showing — do not open another window.
        if always_on_top:
            pin_topmost_windows(profile_name, title_hint=title_class)
        return None
    profile = profile_dir(profile_name)
    args = app_args(
        browser, url=url, profile=profile, rect=rect, title_class=title_class
    )
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None
    if always_on_top:

        def _pin() -> None:
            for delay in (0.5, 1.0, 1.8, 3.0):
                time.sleep(delay)
                if style_orb_windows(
                    profile_name,
                    alpha=_env_alpha("engaged"),
                    frameless=True,
                    topmost=True,
                ):
                    break
            # Keep window alpha in sync with Amy state (real layered alpha).
            if profile_name.lower().startswith("orb"):
                follow_orb_window_alpha(
                    profile_name,
                    host=os.environ.get("AMY_HOST", "127.0.0.1"),
                    port=int(os.environ.get("AMY_PORT") or "8787"),
                    token=os.environ.get("AMY_TOKEN", ""),
                )

        threading.Thread(target=_pin, name=f"amy-topmost-{profile_name}", daemon=True).start()
    return proc
