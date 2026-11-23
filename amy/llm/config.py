"""``amy.llm_routing`` settings from config/hive.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SshSpec:
    host: str
    user: str = ""
    port: int = 22
    remote_host: str = "127.0.0.1"
    remote_port: int = 11434
    local_port: int = 11435
    identity_file: str = ""
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class Backend:
    name: str
    model: str
    base_url: str  # server root, e.g. http://127.0.0.1:11434 (no /v1)
    label: str = ""
    ssh: Optional[SshSpec] = None

    @property
    def display(self) -> str:
        return self.label or f"{self.model} ({self.name})"

    @property
    def host_port(self) -> tuple[str, int]:
        u = urlsplit(self.base_url)
        return u.hostname or "127.0.0.1", u.port or (443 if u.scheme == "https" else 80)


@dataclass
class RoutingConfig:
    backends: List[Backend]
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 11500
    probe_interval_s: float = 15.0
    probe_timeout_s: float = 3.0
    recover_after: int = 2
    request_timeout_s: float = 600.0
    extra: Dict[str, Any] = field(default_factory=dict)


def _root(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


def _ssh(raw: Any) -> Optional[SshSpec]:
    if not isinstance(raw, dict) or not raw.get("host"):
        return None
    return SshSpec(
        host=str(raw["host"]),
        user=str(raw.get("user") or ""),
        port=int(raw.get("port") or 22),
        remote_host=str(raw.get("remote_host") or "127.0.0.1"),
        remote_port=int(raw.get("remote_port") or 11434),
        local_port=int(raw.get("local_port") or 11435),
        identity_file=str(raw.get("identity_file") or ""),
        extra_args=tuple(str(a) for a in (raw.get("extra_args") or [])),
    )


def load_routing(amy_cfg: Any) -> Optional[RoutingConfig]:
    """Parse ``amy.llm_routing``; ``None`` when absent, disabled or without backends."""
    raw = (amy_cfg or {}).get("llm_routing") if isinstance(amy_cfg, dict) else None
    if not isinstance(raw, dict) or not raw.get("enabled", True):
        return None
    backends: List[Backend] = []
    seen: set[str] = set()
    for i, b in enumerate(raw.get("backends") or []):
        if not isinstance(b, dict) or not b.get("model"):
            continue
        if b.get("enabled") is False:
            continue
        name = str(b.get("name") or f"backend{i + 1}")
        if name in seen:
            raise ValueError(f"duplicate llm_routing backend name {name!r}")
        seen.add(name)
        ssh = _ssh(b.get("ssh"))
        base = _root(str(b.get("base_url") or ""))
        if not base:
            base = f"http://127.0.0.1:{ssh.local_port}" if ssh else "http://127.0.0.1:11434"
        backends.append(Backend(name=name, model=str(b["model"]), base_url=base,
                                label=str(b.get("label") or ""), ssh=ssh))
    if not backends:
        return None
    return RoutingConfig(
        backends=backends,
        host=str(raw.get("host") or "127.0.0.1"),
        port=int(raw.get("port") or 11500),
        probe_interval_s=float(raw.get("probe_interval_s") or 15),
        probe_timeout_s=float(raw.get("probe_timeout_s") or 3),
        recover_after=max(1, int(raw.get("recover_after") or 2)),
        request_timeout_s=float(raw.get("request_timeout_s") or 600),
    )
