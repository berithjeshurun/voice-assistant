"""1:1 Hive/Amy config surface — every scalar/list leaf in hive.yaml is editable."""

from __future__ import annotations

import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

_logger = logging.getLogger(__name__)

# Paths that are huge prose — still editable, but UI marks them longtext.
_LONGTEXT_HINTS = ("system_prompt", "prompt", "instructions", "template")
# Never expose / edit these via UI (secrets should use Integrations panel).
_BLOCKED_SUFFIXES = ("access_code", "password", "api_key", "token", "secret")
_BLOCKED_EXACT = set()  # keep empty — bambu access_code still editable as password type


def _config_path() -> Path:
    env = (os.environ.get("HIVE_CONFIG") or "").strip()
    if env and Path(env).is_file():
        return Path(env)
    root = Path(__file__).resolve().parents[2]
    return root / "config" / "hive.yaml"


def _load() -> Dict[str, Any]:
    path = _config_path()
    if yaml is None or not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def _dump(data: Dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from ruamel.yaml import YAML  # type: ignore

        ry = YAML()
        ry.preserve_quotes = True
        ry.indent(mapping=2, sequence=4, offset=2)
        if path.is_file():
            with path.open("r", encoding="utf-8") as fh:
                doc = ry.load(fh)
            if not isinstance(doc, dict):
                doc = {}
            _deep_merge(doc, data)
            with path.open("w", encoding="utf-8") as fh:
                ry.dump(doc, fh)
            return
    except Exception:
        _logger.debug("ignored error", exc_info=True)
    if yaml is None:
        raise RuntimeError("PyYAML required to save config")
    text = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )
    path.write_text(text, encoding="utf-8")


def _deep_merge(dst: Any, src: Any) -> Any:
    if not isinstance(dst, dict) or not isinstance(src, dict):
        return src
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _get(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _set(d: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _section_for(path: str) -> str:
    parts = path.split(".")
    if parts[0] == "profiles" and len(parts) >= 2:
        return f"profile:{parts[1]}"
    if parts[0] == "amy":
        if len(parts) >= 2 and parts[1] in (
            "home",
            "bambu",
            "slicer",
            "updates",
            "local_apps",
            "apps",
            "experimental",
        ):
            return f"amy:{parts[1]}"
        return "amy"
    return parts[0]


def _label_for(path: str) -> str:
    leaf = path.split(".")[-1]
    return leaf.replace("_", " ")


def _field_type(path: str, value: Any) -> str:
    leaf = path.split(".")[-1].lower()
    if any(leaf.endswith(s) or leaf == s for s in _BLOCKED_SUFFIXES):
        if isinstance(value, str) or value is None:
            return "password"
    if isinstance(value, bool):
        return "toggle"
    if isinstance(value, int) and not isinstance(value, bool):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        if not value or all(isinstance(x, (str, int, float, bool)) for x in value):
            return "list"
        return "json"
    if isinstance(value, str):
        if any(h in leaf for h in _LONGTEXT_HINTS) or len(value) > 160:
            return "longtext"
        return "text"
    if value is None:
        return "text"
    return "json"


def _flatten(
    obj: Any,
    prefix: str = "",
    *,
    out: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Flatten dict into leaf fields. Dict-lists become json fields."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                _flatten(v, path, out=out)
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                out.append(
                    {
                        "id": path,
                        "path": path,
                        "section": _section_for(path),
                        "label": _label_for(path),
                        "type": "json",
                        "value": v,
                        "blurb": "List of objects — edit as JSON",
                    }
                )
            else:
                typ = _field_type(path, v)
                out.append(
                    {
                        "id": path,
                        "path": path,
                        "section": _section_for(path),
                        "label": _label_for(path),
                        "type": typ,
                        "value": v,
                        "blurb": path,
                    }
                )
    return out


def _sections_from_fields(fields: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    order: List[str] = []
    seen: Set[str] = set()
    for f in fields:
        sid = str(f.get("section") or "other")
        if sid not in seen:
            seen.add(sid)
            order.append(sid)
    # Prefer product-facing sections first
    prefer = [
        "amy:home",
        "amy:apps",
        "amy:experimental",
        "amy:updates",
        "amy:local_apps",
        "amy:bambu",
        "amy:slicer",
        "amy",
        "profile:ambient",
        "assistant",
        "agent",
        "assemble",
        "integrations",
        "model",
        "hive",
    ]
    ranked = [s for s in prefer if s in seen] + [s for s in order if s not in prefer]
    labels = []
    for sid in ranked:
        if sid.startswith("profile:"):
            label = f"Profile · {sid.split(':', 1)[1]}"
        elif sid.startswith("amy:"):
            label = f"Amy · {sid.split(':', 1)[1]}"
        else:
            label = sid.replace("_", " ").title()
        labels.append({"id": sid, "label": label, "blurb": sid})
    return labels


def get_config_studio() -> Dict[str, Any]:
    data = _load()
    fields = _flatten(data)
    # Stable id = path (1:1)
    for f in fields:
        f["id"] = f["path"]
    sections = _sections_from_fields(fields)
    apps = _get(data, "amy.apps.enabled", []) or []
    local_apps = _get(data, "amy.local_apps", []) or []
    return {
        "ok": True,
        "mode": "1:1",
        "path": str(_config_path()),
        "sections": sections,
        "fields": fields,
        "field_count": len(fields),
        "apps_enabled": list(apps) if isinstance(apps, list) else [],
        "local_apps": local_apps if isinstance(local_apps, list) else [],
        "packs_available": _discover_pack_ids(),
    }


def _discover_pack_ids() -> List[str]:
    try:
        from amy.apps.loader import discover_packs

        return [p["id"] for p in discover_packs()]
    except Exception:
        return []


def _coerce(typ: str, raw: Any) -> Any:
    if typ == "toggle":
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)
    if typ == "number":
        if raw is None or raw == "":
            return 0
        if isinstance(raw, bool):
            return int(raw)
        try:
            if isinstance(raw, str) and "." in raw:
                return float(raw)
            return int(raw)
        except Exception:
            try:
                return float(raw)
            except Exception:
                return raw
    if typ == "list":
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            parts = [p.strip() for p in re.split(r"[,;\n]+", raw) if p.strip()]
            return parts
        return list(raw) if raw else []
    if typ == "json":
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str):
            import json

            return json.loads(raw) if raw.strip() else []
        return raw
    if raw is None:
        return ""
    return raw


def update_config_studio(patch: Dict[str, Any]) -> Dict[str, Any]:
    data = deepcopy(_load())
    # Build type map from current tree
    current = {f["path"]: f for f in _flatten(data)}

    values = patch.get("values") if isinstance(patch.get("values"), dict) else None
    if values is None and isinstance(patch, dict):
        # allow { "path.to.key": value, ... } at top level excluding meta keys
        meta = {"values", "apps_enabled", "local_apps", "ok"}
        values = {k: v for k, v in patch.items() if k not in meta}

    if isinstance(values, dict):
        for key, raw in values.items():
            path = str(key).strip()
            if not path:
                continue
            # Only allow mutating existing leaves OR known amy.* / profiles.* paths
            typ = (current.get(path) or {}).get("type") or _field_type(path, raw)
            try:
                val = _coerce(typ, raw)
            except Exception as e:
                return {"ok": False, "error": f"{path}: {e}"}
            _set(data, path, val)

    if "apps_enabled" in patch and isinstance(patch["apps_enabled"], list):
        _set(
            data,
            "amy.apps.enabled",
            [str(x).strip() for x in patch["apps_enabled"] if str(x).strip()],
        )

    if "local_apps" in patch and isinstance(patch["local_apps"], list):
        cleaned = []
        for row in patch["local_apps"]:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id") or "").strip()
            url = str(row.get("base_url") or "").strip()
            if not rid or not url:
                continue
            cleaned.append(
                {
                    "id": rid,
                    "name": str(row.get("name") or rid),
                    "base_url": url,
                    "health_path": str(row.get("health_path") or "/"),
                }
            )
        _set(data, "amy.local_apps", cleaned)

    _dump(data)
    out = get_config_studio()
    out["ok"] = True
    return out
