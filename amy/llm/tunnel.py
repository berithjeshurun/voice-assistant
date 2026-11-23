"""Keeps an OpenSSH local port-forward to a remote Ollama alive (key auth only)."""

from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import List, Optional

from amy.llm.config import SshSpec

_logger = logging.getLogger(__name__)


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class SshTunnel:
    """``ssh -N -L``; BatchMode so it never blocks on a password prompt."""

    def __init__(self, spec: SshSpec, *, ssh_bin: Optional[str] = None, backoff_s: float = 30.0) -> None:
        self.spec = spec
        self.ssh_bin = ssh_bin or shutil.which("ssh") or "ssh"
        self.backoff_s = backoff_s
        self.last_error = ""
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._last_attempt = 0.0
        self._lock = threading.Lock()

    @property
    def local_port(self) -> int:
        return self.spec.local_port

    def command(self) -> List[str]:
        s = self.spec
        target = f"{s.user}@{s.host}" if s.user else s.host
        cmd = [
            self.ssh_bin, "-N",
            "-L", f"127.0.0.1:{s.local_port}:{s.remote_host}:{s.remote_port}",
            "-p", str(s.port),
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=2",
            "-o", "ConnectTimeout=6",
            "-o", "StrictHostKeyChecking=accept-new",
        ]
        if s.identity_file:
            cmd += ["-i", s.identity_file]
        cmd += list(s.extra_args)
        cmd.append(target)
        return cmd

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ensure(self, wait_s: float = 8.0) -> bool:
        """True when the forwarded port answers; (re)starts ssh at most once per backoff."""
        if port_open("127.0.0.1", self.spec.local_port):
            return True
        with self._lock:
            if self.alive():
                return self._wait_port(wait_s)
            now = time.monotonic()
            if self._last_attempt and now - self._last_attempt < self.backoff_s:
                return False
            self._last_attempt = now
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            try:
                self._proc = subprocess.Popen(
                    self.command(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=flags,
                )
            except OSError as e:
                self.last_error = f"cannot start ssh: {e}"
                return False
        if self._wait_port(wait_s):
            self.last_error = ""
            return True
        self._collect_error()
        return False

    def _wait_port(self, wait_s: float) -> bool:
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if port_open("127.0.0.1", self.spec.local_port):
                return True
            if not self.alive():
                return False
            time.sleep(0.2)
        return False

    def _collect_error(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            self.last_error = "ssh connected but the forwarded port never opened"
            return
        err = b""
        try:
            err = proc.stderr.read() if proc.stderr else b""
        except OSError:
            pass
        text = err.decode("utf-8", "replace").strip().splitlines()
        self.last_error = (text[-1] if text else f"ssh exited with {proc.returncode}")[:200]
        _logger.info("ssh tunnel to %s failed: %s", self.spec.host, self.last_error)

    def stop(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
