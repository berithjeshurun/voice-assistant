"""Discover and register Amy app packs under apps/packs/."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_MANIFEST_CACHE: Dict[str, Dict[str, Any]] = {}


def amy_root() -> Path:
    return Path(__file__).resolve().parents[2]


def packs_root() -> Path:
    env = os.environ.get("AMY_PACKS_ROOT", "").strip()
    if env:
        return Path(env)
    return amy_root() / "apps" / "packs"


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def discover_packs() -> List[Dict[str, Any]]:
    root = packs_root()
    if not root.is_dir():
        return []
    found: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        man = child / "manifest.yaml"
        if not man.is_file():
            continue
        data = _read_yaml(man)
        pack_id = str(data.get("id") or child.name).strip()
        entry = {
            "id": pack_id,
            "name": str(data.get("name") or pack_id),
            "path": child,
            "manifest": data,
            "skill": child / "SKILL.md",
            "tools_module": child / "tools.py",
        }
        found.append(entry)
        _MANIFEST_CACHE[pack_id] = entry
    return found


def list_packs() -> List[Dict[str, Any]]:
    return discover_packs()


def get_pack(pack_id: str) -> Optional[Dict[str, Any]]:
    pid = (pack_id or "").strip().lower()
    if not pid:
        return None
    if pid in _MANIFEST_CACHE:
        return _MANIFEST_CACHE[pid]
    for p in discover_packs():
        if p["id"].lower() == pid:
            return p
    return None


def enabled_pack_ids(config: Any = None) -> List[str]:
    """Packs enabled via hive.yaml amy.apps.enabled or AMY_APPS env."""
    env = os.environ.get("AMY_APPS", "").strip()
    if env:
        return [x.strip() for x in env.split(",") if x.strip()]

    raw: Any = config
    if raw is None:
        cfg_path = os.environ.get("HIVE_CONFIG") or ""
        if cfg_path and Path(cfg_path).is_file():
            raw = _read_yaml(Path(cfg_path))
    if isinstance(raw, dict):
        amy = raw.get("amy") or {}
        apps = amy.get("apps") or {}
        enabled = apps.get("enabled") or []
        if isinstance(enabled, str):
            return [enabled.strip()] if enabled.strip() else []
        if isinstance(enabled, (list, tuple)):
            return [str(x).strip() for x in enabled if str(x).strip()]
    return []


def install_pack(pack_id: str) -> Dict[str, Any]:
    """Ensure pack exists, secrets template written, marked installed."""
    pack = get_pack(pack_id)
    if not pack:
        return {"ok": False, "error": f"unknown pack {pack_id!r}"}
    man = pack.get("manifest") or {}
    secrets_schema = man.get("secrets") or {}
    keys = list(secrets_schema.get("keys") or [])
    example_lines = list(secrets_schema.get("example_lines") or [])
    from amy.apps.secrets import secrets_path, write_secrets_template

    if example_lines:
        write_secrets_template(pack["id"], example_lines)
    else:
        lines = [f"# Amy app secrets — {pack['id']}", "# Fill values; never commit."]
        for k in keys:
            lines.append(f"{k}=")
        write_secrets_template(pack["id"], lines)

    # Stamp enabled in a local install marker (config still authoritative for ambient)
    stamp = Path.home() / ".amy" / "apps" / "installed.txt"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if stamp.is_file():
        existing = {ln.strip() for ln in stamp.read_text(encoding="utf-8").splitlines() if ln.strip()}
    existing.add(pack["id"])
    stamp.write_text("\n".join(sorted(existing)) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "id": pack["id"],
        "secrets": str(secrets_path(pack["id"])),
        "path": str(pack["path"]),
    }


def _load_tools_module(pack: Dict[str, Any]) -> Any:
    tools_path: Path = pack["tools_module"]
    if not tools_path.is_file():
        return None
    mod_name = f"amy_pack_{pack['id']}_tools"
    # Ensure pack dir on path for sibling imports
    pack_dir = str(pack["path"])
    if pack_dir not in sys.path:
        sys.path.insert(0, pack_dir)
    spec = importlib.util.spec_from_file_location(mod_name, tools_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def register_pack_tools(registry: Any, pack_id: str) -> List[str]:
    pack = get_pack(pack_id)
    if not pack or registry is None:
        return []
    mod = _load_tools_module(pack)
    if mod is None:
        return []
    register = getattr(mod, "register", None)
    if not callable(register):
        return []
    try:
        names = register(registry) or []
        return [str(n) for n in names]
    except Exception as e:
        print(f"# amy apps register {pack_id} failed: {e}", flush=True)
        return []


def load_enabled_packs(
    registry: Any,
    *,
    config: Any = None,
) -> Dict[str, Any]:
    """Register tools for every enabled pack. Returns summary."""
    enabled = enabled_pack_ids(config)
    registered: Dict[str, List[str]] = {}
    for pid in enabled:
        names = register_pack_tools(registry, pid)
        if names:
            registered[pid] = names
    return {"enabled": enabled, "registered": registered}


def pack_tool_names(config: Any = None) -> List[str]:
    """Tool names declared by enabled packs (for allowlist keep)."""
    names: List[str] = []
    for pid in enabled_pack_ids(config):
        pack = get_pack(pid)
        if not pack:
            continue
        man = pack.get("manifest") or {}
        for t in man.get("tools") or []:
            n = str(t).strip()
            if n and n not in names:
                names.append(n)
    return names
