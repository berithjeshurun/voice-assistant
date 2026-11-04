"""Persistent Amy captions + bottom dock windows (Tauri / Chromium / webview)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from amy.branding import DEFAULT_SERVER_PORT
from amy.host.events import EventBus
from amy.host.placement import captions_rect, dock_rect


class ChatBridge:
    """Opens captions (right) and activity dock (bottom) with the orb."""

    def __init__(
        self,
        bus: EventBus,
        *,
        token: str = "",
        host: str = "127.0.0.1",
        port: int = DEFAULT_SERVER_PORT,
        enabled: bool = True,
    ) -> None:
        self.bus = bus
        self.token = token
        self.host = host
        self.port = int(port)
        # Production default: no separate captions window (orb + on-demand HUD).
        self.enabled = enabled and (
            os.environ.get("AMY_CHAT_WINDOW", "0").strip().lower()
            in ("1", "true", "on", "yes")
        )
        # Separate bottom Edge window was noisy — activity lives inside captions HUD.
        # Set AMY_DOCK=1 to restore the standalone strip.
        self._dock_enabled = (
            os.environ.get("AMY_DOCK", "0").strip().lower()
            in ("1", "true", "on", "yes")
        )
        self._proc: Optional[subprocess.Popen] = None
        self._dock_proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._watch: Optional[threading.Thread] = None
        self._mode = "none"
        self._dock_mode = "none"

    def _url(self, view: str = "chat") -> str:
        q = {"view": view}
        if self.token:
            q["token"] = self.token
        return f"http://{self.host}:{self.port}/?{urllib.parse.urlencode(q)}"

    def start(self) -> bool:
        if not self.enabled:
            return False
        url = self._url("chat")
        # Short wait — caller should already have the HUD up.
        if not self._wait(url, timeout=8.0):
            print("# amy captions: HUD not reachable", flush=True)
            return False
        ok = self._spawn_captions(url)
        dock_ok = False
        if self._dock_enabled:
            dock_ok = self._spawn_dock(self._url("dock"))
        print(
            f"# amy windows captions={'ok' if ok else 'fail'} "
            f"mode={self._mode} dock={'ok' if dock_ok else 'skip'} "
            f"dock_mode={self._dock_mode}",
            flush=True,
        )
        if ok:
            self._watch = threading.Thread(
                target=self._reaper, name="amy-chat-watch", daemon=True
            )
            self._watch.start()
        return ok

    def stop(self) -> None:
        self._stop.set()
        for attr in ("_proc", "_dock_proc"):
            proc = getattr(self, attr, None)
            setattr(self, attr, None)
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def _wait(self, url: str, timeout: float = 45.0) -> bool:
        parsed = urllib.parse.urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        deadline = time.time() + timeout
        while time.time() < deadline and not self._stop.is_set():
            try:
                with urllib.request.urlopen(origin + "/", timeout=2) as resp:
                    if resp.status < 500:
                        return True
            except Exception:
                pass
            time.sleep(0.35)
        return False

    def _tauri_bin(self) -> Optional[str]:
        root = Path(__file__).resolve().parents[2]
        for c in (
            root
            / "apps"
            / "desktop"
            / "src-tauri"
            / "target"
            / "release"
            / "amy-desktop.exe",
            root
            / "apps"
            / "desktop"
            / "src-tauri"
            / "target"
            / "release"
            / "amy-desktop",
            shutil.which("amy-desktop"),
        ):
            if c and Path(c).is_file():
                return str(c)
        return None

    def _spawn_captions(self, url: str) -> bool:
        r = captions_rect()
        tauri = self._tauri_bin()
        if tauri:
            env = os.environ.copy()
            env["AMY_CHAT_URL"] = url
            env["AMY_TOKEN"] = self.token
            env["AMY_CHAT_X"] = str(r.x)
            env["AMY_CHAT_Y"] = str(r.y)
            env["AMY_CHAT_W"] = str(r.w)
            env["AMY_CHAT_H"] = str(r.h)
            if self._dock_enabled:
                d = dock_rect()
                env["AMY_DOCK_URL"] = self._url("dock")
                env["AMY_DOCK_X"] = str(d.x)
                env["AMY_DOCK_Y"] = str(d.y)
                env["AMY_DOCK_W"] = str(d.w)
                env["AMY_DOCK_H"] = str(d.h)
            try:
                self._proc = subprocess.Popen(
                    [tauri, "--chat-url", url],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._mode = "tauri"
                # Tauri owns dock window when env is set
                self._dock_mode = "tauri" if self._dock_enabled else "none"
                return True
            except Exception:
                pass

        # pywebview requires the main thread — Amy host already owns that for
        # the HUD server, so captions always use locked-down Chromium/Edge.
        from amy.host.chromium_app import spawn_app

        proc = spawn_app(
            url=url,
            profile_name="captions",
            rect=r,
            title_class="AmyCaptions",
            replace_existing=True,
        )
        if proc is not None:
            self._proc = proc
            self._mode = "chromium"
            return True

        # Never webbrowser.open() — that dumps into the user's real Edge with extensions.
        print("# amy captions: no chromium available for HUD", flush=True)
        return False

    def _spawn_dock(self, url: str) -> bool:
        if self._dock_mode == "tauri":
            return True
        r = dock_rect()
        from amy.host.chromium_app import spawn_app

        proc = spawn_app(url=url, profile_name="dock", rect=r, title_class="AmyDock")
        if proc is not None:
            self._dock_proc = proc
            self._dock_mode = "chromium"
            return True
        return False

    @staticmethod
    def _chromium() -> Optional[list[str]]:
        env = os.environ.get("AMY_CHAT_BROWSER", "").strip()
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
            Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ):
            if c.is_file():
                return [str(c)]
        return None

    def _reaper(self) -> None:
        while not self._stop.wait(2.5):
            proc = self._proc
            if proc is not None and proc.poll() is not None and self._mode in (
                "chromium",
                "tauri",
            ):
                if not self._stop.is_set():
                    self._spawn_captions(self._url("chat"))
            dock = self._dock_proc
            if (
                dock is not None
                and dock.poll() is not None
                and self._dock_mode == "chromium"
                and not self._stop.is_set()
            ):
                self._spawn_dock(self._url("dock"))
