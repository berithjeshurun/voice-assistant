"""Persistent Amy orb sidecar — Crystalized Ball web companion (React Bits).

Bevy binary is opt-in via ``AMY_ORB=bevy`` for legacy experiments.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from amy.branding import DEFAULT_SERVER_PORT
from amy.host.events import EventBus
from amy.protocol.messages import AssistantSnapshot


class OrbBridge:
    """Keeps a companion orb alive for the life of the Amy host."""

    def __init__(
        self,
        bus: EventBus,
        *,
        binary: Optional[Path] = None,
        token: str = "",
        host: str = "127.0.0.1",
        port: int = DEFAULT_SERVER_PORT,
        enabled: bool = True,
    ) -> None:
        self.bus = bus
        self.token = token
        self.host = host
        self.port = int(port)
        self.enabled = enabled
        prefer = (os.environ.get("AMY_ORB") or "crystalized").strip().lower()
        self.binary = binary if prefer == "bevy" else None
        if prefer == "bevy":
            self.binary = binary or self._discover_bevy()
        self._proc: Optional[subprocess.Popen] = None
        self._unsub = None
        self._stop = threading.Event()
        self._watch: Optional[threading.Thread] = None
        self._mode = "none"

    @staticmethod
    def _discover_bevy() -> Optional[Path]:
        which = shutil.which("amy-orb")
        if which:
            return Path(which)
        root = Path(__file__).resolve().parents[2]
        for c in (
            root / "apps" / "orb" / "target" / "release" / "amy-orb",
            root / "apps" / "orb" / "target" / "release" / "amy-orb.exe",
            root / "apps" / "orb" / "target" / "debug" / "amy-orb",
            root / "apps" / "orb" / "target" / "debug" / "amy-orb.exe",
        ):
            if c.is_file():
                return c
        return None

    def start(self) -> bool:
        if not self.enabled:
            return False
        ok = self._spawn()
        if not ok:
            return False

        def _on_snap(snap: AssistantSnapshot) -> None:
            self.send_state(snap.state.value)

        self._unsub = self.bus.subscribe(_on_snap)
        self._watch = threading.Thread(
            target=self._reaper, name="amy-orb-watch", daemon=True
        )
        self._watch.start()
        return True

    def _spawn(self) -> bool:
        env = os.environ.copy()
        if self.token:
            env["AMY_TOKEN"] = self.token

        # Avoid stacking sidecars if one is already alive.
        old = self._proc
        if old is not None and old.poll() is None:
            return True

        if self.binary and self.binary.is_file():
            cmd = [str(self.binary)]
            self._mode = "bevy"
        else:
            cmd = [
                sys.executable,
                "-m",
                "amy.orb.window",
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--token",
                self.token or "",
            ]
            self._mode = "crystalized"

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                env=env,
            )
        except Exception as e:
            print(f"# amy orb spawn failed: {e}", flush=True)
            self._proc = None
            return False
        print(f"# amy orb started mode={self._mode}", flush=True)
        return True

    def _reaper(self) -> None:
        """Restart orb only when both the sidecar and Edge orb window are gone."""
        while not self._stop.is_set():
            proc = self._proc
            if proc is None:
                self._stop.wait(1.0)
                continue
            code = proc.poll()
            if code is None:
                self._stop.wait(1.0)
                continue
            if self._stop.is_set():
                break
            # Sidecar exited but Edge may still be showing the orb — don't duplicate.
            try:
                from amy.host.chromium_app import profile_alive

                if self._mode == "crystalized" and profile_alive("orb"):
                    self._stop.wait(2.0)
                    continue
            except Exception:
                pass
            print("# amy orb exited — restarting in 1.5s", flush=True)
            self._stop.wait(1.5)
            if self._stop.is_set():
                break
            self._spawn()

    def send_state(self, state: str) -> None:
        proc = self._proc
        if proc and proc.stdin and self._mode == "bevy":
            try:
                proc.stdin.write(f'{{"type":"set_state","state":"{state}"}}\n')
                proc.stdin.flush()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._unsub:
            try:
                self._unsub()
            except Exception:
                pass
            self._unsub = None
        proc = self._proc
        self._proc = None
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
