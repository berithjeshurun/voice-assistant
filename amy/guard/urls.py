"""URL checks — scheme allowlist and private-network (SSRF) blocking."""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Tuple
from urllib.parse import urlsplit

_PRIVATE_SUFFIXES = (".local", ".lan", ".internal", ".home", ".localdomain", ".corp")


def _ip_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def host_is_private(host: str, *, resolve: bool = True) -> bool:
    h = (host or "").strip().strip("[]").lower()
    if not h:
        return True
    if h == "localhost" or h.endswith(".localhost") or h.endswith(_PRIVATE_SUFFIXES):
        return True
    if "." not in h and ":" not in h and not h.isdigit():
        return True  # single-label intranet name
    if _ip_private(h):
        return True
    if not resolve:
        return False
    try:
        infos = socket.getaddrinfo(h, None)
    except Exception:
        return False
    return any(_ip_private(info[4][0]) for info in infos)


_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*:(?!\d)", re.I)


def normalize(url: str) -> str:
    u = (url or "").strip()
    # "host:8080/x" is a bare host with a port; "javascript:x" is an explicit scheme.
    if u and "://" not in u and not _SCHEME_RE.match(u):
        u = "https://" + u
    return u


def check_url(url: str, *, purpose: str, allow_private: bool = False) -> Tuple[str, str]:
    """purpose: ``browse`` (opens in the user's browser) or ``fetch`` (Amy downloads it)."""
    u = normalize(url)
    if not u:
        return "allow", "no url"
    if purpose == "browse" and u.lower().startswith("ms-settings:"):
        return "allow", "Windows settings page"
    try:
        parts = urlsplit(u)
    except Exception:
        return "deny", "unparseable url"
    if parts.scheme.lower() not in ("http", "https"):
        return "deny", f"scheme {parts.scheme or '?'}: is not allowed"
    if parts.username or parts.password:
        return "deny", "credentials embedded in url"
    if not allow_private and host_is_private(parts.hostname or ""):
        if purpose == "fetch":
            return "deny", "private/local network address"
        return "confirm", "opens a private/local network address"
    return "allow", "public web address"
