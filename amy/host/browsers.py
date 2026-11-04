"""Shared helpers for launching HUD windows: find a Chromium browser, wait for the server."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import List, Optional

_logger = logging.getLogger(__name__)

_POSIX_NAMES = ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")


def _windows_candidates() -> List[Path]:
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    return [
        Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]


def find_chromium(env_vars: Iterable[str] = ("AMY_ORB_BROWSER", "AMY_CHAT_BROWSER")) -> Optional[List[str]]:
    """Command prefix for Edge / Chrome / Chromium; an explicit path in ``env_vars`` wins."""
    for var in env_vars:
        env = os.environ.get(var, "").strip()
        if env and Path(env).is_file():
            return [env]
    if sys.platform != "win32":
        for name in _POSIX_NAMES:
            found = shutil.which(name)
            if found:
                return [found]
        return None
    for c in _windows_candidates():
        if c.is_file():
            return [str(c)]
    found = shutil.which("msedge") or shutil.which("chrome")
    return [found] if found else None


def wait_for_http(
    url: str,
    *,
    timeout: float = 30.0,
    interval: float = 0.3,
    stop: Optional[threading.Event] = None,
) -> bool:
    """Poll the origin of ``url`` until it answers with a non-5xx status."""
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme or 'http'}://{parsed.netloc}/"
    deadline = time.time() + timeout
    while time.time() < deadline and not (stop is not None and stop.is_set()):
        try:
            with urllib.request.urlopen(origin, timeout=2) as resp:
                if resp.status < 500:
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return True
        except (urllib.error.URLError, OSError):
            _logger.debug("waiting for %s", origin)
        time.sleep(interval)
    return False
