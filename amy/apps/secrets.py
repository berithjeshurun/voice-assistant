"""Local secrets for Amy apps — ~/.amy/secrets/<app>.env (never log values)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Optional


def secrets_dir() -> Path:
    root = Path(os.environ.get("AMY_SECRETS_DIR") or (Path.home() / ".amy" / "secrets"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def secrets_path(app_id: str) -> Path:
    safe = re.sub(r"[^a-z0-9_\-]+", "", (app_id or "").strip().lower()) or "app"
    return secrets_dir() / f"{safe}.env"


def state_dir(app_id: str) -> Path:
    safe = re.sub(r"[^a-z0-9_\-]+", "", (app_id or "").strip().lower()) or "app"
    root = Path(os.environ.get("AMY_STATE_DIR") or (Path.home() / ".amy" / "state"))
    path = root / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def load_app_secrets(app_id: str, *, env_prefix: str = "") -> Dict[str, str]:
    """Merge file secrets with process env. Env wins when set."""
    data = load_env_file(secrets_path(app_id))
    prefix = (env_prefix or app_id or "").strip().upper().replace("-", "_")
    if prefix:
        for key, val in list(os.environ.items()):
            if key.startswith(f"AMY_{prefix}_") and val:
                # AMY_SMARTPANELS_USER → SMARTPANELS_USER
                short = key[len("AMY_") :]
                data[short] = val
            if key.startswith(f"{prefix}_") and val:
                data[key] = val
    return data


def secrets_present(app_id: str, required_keys: list[str]) -> bool:
    data = load_app_secrets(app_id)
    return all(str(data.get(k) or "").strip() for k in required_keys)


def write_secrets_template(app_id: str, lines: list[str]) -> Path:
    path = secrets_path(app_id)
    if path.is_file():
        return path
    body = "\n".join(lines).rstrip() + "\n"
    path.write_text(body, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return path


def redact(value: Optional[str]) -> str:
    if not value:
        return ""
    return "***"
