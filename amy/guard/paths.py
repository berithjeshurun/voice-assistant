"""Filesystem confinement for agent file access."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List, Tuple

_SENSITIVE_NAMES = {
    ".env", ".git-credentials", ".netrc", ".pypirc", ".npmrc", "id_rsa",
    "id_ed25519", "id_ecdsa", "known_hosts", "authorized_keys", "credentials",
    "login data", "cookies", "web data", "local state", "key3.db", "key4.db",
    "logins.json", "wallet.dat", "session.json", "storage_state.json",
}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".kdbx", ".ppk", ".ovpn"}


def _home() -> Path:
    return Path.home().resolve()


def sensitive_roots() -> List[Path]:
    home = _home()
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    windir = Path(os.environ.get("WINDIR") or r"C:\Windows")
    return [
        home / ".ssh",
        home / ".amy",
        home / ".aws",
        home / ".azure",
        home / ".kube",
        home / ".gnupg",
        home / ".docker",
        home / ".config" / "gh",
        local / "Google" / "Chrome" / "User Data",
        local / "Microsoft" / "Edge" / "User Data",
        local / "BraveSoftware",
        roaming / "Mozilla" / "Firefox" / "Profiles",
        local / "Microsoft" / "Credentials",
        roaming / "Microsoft" / "Credentials",
        roaming / "Microsoft" / "Protect",
        local / "Microsoft" / "Vault",
        windir / "System32" / "config",
    ]


def resolve(path: str, base: Path) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser((path or "").strip())))
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def is_sensitive(p: Path) -> bool:
    name = p.name.lower()
    if name in _SENSITIVE_NAMES or name.startswith(".env"):
        return True
    if p.suffix.lower() in _SENSITIVE_SUFFIXES:
        return True
    for root in sensitive_roots():
        try:
            if p.is_relative_to(root.resolve()):
                return True
        except Exception:
            continue
    return False


def check_path(path: str, roots: Iterable[Path]) -> Tuple[str, str]:
    """``deny`` for secrets or anything outside *roots*; else ``allow``."""
    roots = [Path(r).resolve() for r in roots]
    raw = (path or "").strip()
    if not raw:
        return "allow", "default location"
    if raw.startswith(("\\\\", "//")):
        return "deny", "network share paths are not allowed"
    after_drive = raw[2:] if re.match(r"^[a-z]:", raw, re.I) else raw
    if ":" in after_drive:
        return "deny", "alternate data streams and device paths are not allowed"
    try:
        p = resolve(path, roots[0] if roots else Path.cwd())
    except Exception as e:
        return "deny", f"bad path: {e}"
    if is_sensitive(p):
        return "deny", "path holds secrets or credentials"
    if not any(p == r or p.is_relative_to(r) for r in roots):
        return "deny", "path is outside the allowed folders"
    return "allow", "inside allowed folders"
