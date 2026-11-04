"""Webservice integrations — API keys in Amy secrets (never returned raw)."""

from __future__ import annotations

from typing import Any, Dict, List

from amy.apps.secrets import load_app_secrets, redact, secrets_path, write_secrets_template
from amy.settings.presets import INTEGRATION_CATALOG


def list_integrations() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for item in INTEGRATION_CATALOG:
        iid = item["id"]
        secrets = load_app_secrets(iid)
        keys = list(item.get("keys") or [])
        configured = {k: bool(str(secrets.get(k) or "").strip()) for k in keys}
        rows.append(
            {
                "id": iid,
                "name": item.get("name"),
                "kind": item.get("kind"),
                "docs": item.get("docs"),
                "pack": item.get("pack"),
                "keys": keys,
                "configured": configured,
                "ready": all(configured.values()) if keys else False,
                "secrets_file": str(secrets_path(iid)),
            }
        )
    return {"ok": True, "integrations": rows}


def set_integration_secrets(integration_id: str, values: Dict[str, str]) -> Dict[str, Any]:
    """Write/update secrets for an integration. Values are never echoed back."""
    meta = next((x for x in INTEGRATION_CATALOG if x["id"] == integration_id), None)
    if not meta:
        return {"ok": False, "error": f"unknown integration {integration_id!r}"}
    allowed = set(meta.get("keys") or [])
    path = secrets_path(integration_id)
    existing = {}
    if path.is_file():
        from amy.apps.secrets import load_env_file

        existing = load_env_file(path)
    for k, v in (values or {}).items():
        key = str(k).strip()
        if key not in allowed:
            continue
        val = str(v or "").strip()
        if val:
            existing[key] = val
    lines = [f"# Amy integration secrets — {integration_id}", "# Never commit."]
    for k in meta.get("keys") or []:
        lines.append(f"{k}={existing.get(k, '')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    try:
        import os

        os.chmod(path, 0o600)
    except Exception:
        pass
    # Mirror into process env for immediate use (without logging).
    import os

    for k, v in existing.items():
        if v:
            os.environ[k] = v
            os.environ[f"AMY_{integration_id.upper().replace('-', '_')}_{k}"] = v
    return {
        "ok": True,
        "id": integration_id,
        "configured": {k: bool(existing.get(k)) for k in allowed},
        "redacted": {k: redact(existing.get(k)) for k in allowed},
    }


def ensure_templates() -> None:
    for item in INTEGRATION_CATALOG:
        keys = list(item.get("keys") or [])
        lines = [f"# Amy integration — {item['id']}", "# Fill values; never commit."]
        for k in keys:
            lines.append(f"{k}=")
        write_secrets_template(item["id"], lines)
