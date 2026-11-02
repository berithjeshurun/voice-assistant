"""Isolated Chromium/Edge app windows — no extensions, single instance per profile."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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


def spawn_app(
    *,
    url: str,
    profile_name: str,
    rect: Rect,
    title_class: str = "AmyHUD",
    replace_existing: bool = True,
) -> Optional[subprocess.Popen]:
    browser = find_chromium()
    if not browser:
        return None
    if replace_existing:
        kill_profile(profile_name)
    elif profile_alive(profile_name):
        # Already showing — do not open another window.
        return None
    profile = profile_dir(profile_name)
    args = app_args(
        browser, url=url, profile=profile, rect=rect, title_class=title_class
    )
    try:
        return subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None
