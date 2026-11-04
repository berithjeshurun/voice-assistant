"""Authentication for the HUD server: admin token, per-device tokens with roles, sessions.

Roles (each includes the one before it):

* ``viewer`` — read state, history and metrics; receive live updates.
* ``user``   — also chat, wake, barge in, cancel tasks, turn lockdown *on*.
* ``admin``  — also approve guarded actions, lift lockdown, change settings / config.

Device tokens are stored as SHA-256 digests in ``~/.amy/devices.json``; the plain token is
shown once when the device is added. Browsers trade a token for an HttpOnly session cookie
so the token does not linger in URLs, history or screenshots.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, List, Optional

ROLES = ("viewer", "user", "admin")
SESSION_COOKIE = "amy_session"

_AUTH_FAIL_WINDOW_S = 300.0
_AUTH_FAIL_MAX = 20


def _rank(role: str) -> int:
    try:
        return ROLES.index(role)
    except ValueError:
        return -1


@dataclass(frozen=True)
class Principal:
    name: str
    role: str

    def can(self, need: str) -> bool:
        return _rank(self.role) >= _rank(need) >= 0


def amy_state_dir() -> Path:
    return Path(os.environ.get("AMY_STATE_DIR") or Path.home() / ".amy")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _restrict(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class AuthThrottle:
    """Lock out a client IP after repeated bad credentials."""

    def __init__(self, *, window_s: float = _AUTH_FAIL_WINDOW_S, max_fails: int = _AUTH_FAIL_MAX):
        self._lock = threading.Lock()
        self._fails: Dict[str, Deque[float]] = defaultdict(deque)
        self.window_s = window_s
        self.max_fails = max_fails

    def _prune(self, ip: str, now: float) -> Deque[float]:
        q = self._fails[ip]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if not q:
            self._fails.pop(ip, None)
            q = self._fails[ip]
        return q

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._prune(ip, time.time())) >= self.max_fails

    def fail(self, ip: str) -> None:
        with self._lock:
            now = time.time()
            self._prune(ip, now).append(now)


class DeviceRegistry:
    """Named device tokens with roles, persisted as digests."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or amy_state_dir() / "devices.json")
        self._lock = threading.Lock()
        self._devices: Dict[str, Dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        devices = raw.get("devices") if isinstance(raw, dict) else None
        self._devices = {
            str(name): {"digest": str(d.get("digest", "")), "role": str(d.get("role", "viewer"))}
            for name, d in (devices or {}).items()
            if isinstance(d, dict) and d.get("digest") and d.get("role") in ROLES
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"devices": self._devices}, indent=2), encoding="utf-8")
        _restrict(tmp)
        tmp.replace(self.path)

    def add(self, name: str, role: str = "user") -> str:
        name = name.strip()
        if not name or len(name) > 40 or "|" in name or name.lower().startswith("host"):
            raise ValueError("device name must be 1-40 characters, no '|', not starting with 'host'")
        if role not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._devices[name] = {"digest": _digest(token), "role": role}
            self._save()
        return token

    def remove(self, name: str) -> bool:
        with self._lock:
            if self._devices.pop(name, None) is None:
                return False
            self._save()
            return True

    def list(self) -> List[Dict[str, str]]:
        with self._lock:
            return [{"name": n, "role": d["role"]} for n, d in sorted(self._devices.items())]

    def match(self, token: str) -> Optional[Principal]:
        dig = _digest(token)
        with self._lock:
            items = list(self._devices.items())
        found: Optional[Principal] = None
        for name, d in items:
            # compare against every entry so timing does not reveal position
            if hmac.compare_digest(dig, d["digest"]):
                found = Principal(name=name, role=d["role"])
        return found


class SessionSigner:
    """Stateless HMAC-signed session values (``name|role|expiry``)."""

    def __init__(self, key: Optional[bytes] = None, *, ttl_s: Optional[float] = None) -> None:
        self.key = key or self._load_key()
        hours = float(os.environ.get("AMY_SESSION_HOURS") or 168)
        self.ttl_s = ttl_s if ttl_s is not None else hours * 3600

    @staticmethod
    def _load_key() -> bytes:
        path = amy_state_dir() / "session.key"
        try:
            key = path.read_bytes()
            if len(key) >= 32:
                return key
        except OSError:
            pass
        key = secrets.token_bytes(32)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(key)
            _restrict(path)
        except OSError:
            pass  # sessions then simply end when the process restarts
        return key

    def _sig(self, body: bytes) -> str:
        return base64.urlsafe_b64encode(hmac.new(self.key, body, hashlib.sha256).digest()).decode()

    def issue(self, p: Principal) -> str:
        exp = int(time.time() + self.ttl_s)
        body = f"{p.name}|{p.role}|{exp}".encode()
        return base64.urlsafe_b64encode(body).decode() + "." + self._sig(body)

    def verify(self, value: str) -> Optional[Principal]:
        try:
            b64, sig = value.split(".", 1)
            body = base64.urlsafe_b64decode(b64.encode())
        except (ValueError, TypeError):
            return None
        if not hmac.compare_digest(sig, self._sig(body)):
            return None
        try:
            name, role, exp = body.decode().rsplit("|", 2)
            if int(exp) < time.time() or role not in ROLES:
                return None
        except ValueError:
            return None
        return Principal(name=name, role=role)


class Authenticator:
    def __init__(
        self,
        admin_token: str,
        *,
        devices: Optional[DeviceRegistry] = None,
        signer: Optional[SessionSigner] = None,
        throttle: Optional[AuthThrottle] = None,
    ) -> None:
        self.admin_token = admin_token
        self.devices = devices
        self.signer = signer or SessionSigner()
        self.throttle = throttle or AuthThrottle()

    @property
    def _host_name(self) -> str:
        return "host:" + _digest(self.admin_token)[:12]

    def from_token(self, token: Optional[str]) -> Optional[Principal]:
        if not token:
            return None
        if self.admin_token and hmac.compare_digest(token, self.admin_token):
            return Principal(name=self._host_name, role="admin")
        if self.devices is not None:
            return self.devices.match(token)
        return None

    def from_session(self, value: Optional[str]) -> Optional[Principal]:
        if not value:
            return None
        p = self.signer.verify(value)
        if p is None:
            return None
        if p.name.startswith("host:"):
            # sessions from an earlier admin token end when the token rotates
            ok = bool(self.admin_token) and hmac.compare_digest(p.name, self._host_name)
            return p if ok and p.role == "admin" else None
        # removing a device or changing its role takes effect even on a live cookie
        current = {d["name"]: d["role"] for d in self.devices.list()} if self.devices else {}
        role = current.get(p.name)
        if role is None:
            return None
        return Principal(name=p.name, role=role)
