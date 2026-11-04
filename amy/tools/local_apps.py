"""Control registered local servers / web apps (localhost allowlist)."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

_APPS: List[Dict[str, Any]] = []


def apply_config(cfg: Any) -> None:
    global _APPS
    apps: List[Dict[str, Any]] = []
    if isinstance(cfg, dict):
        raw = cfg.get("local_apps") or cfg.get("apps_list") or []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("id") and item.get("base_url"):
                    apps.append(dict(item))
    _APPS = apps


def _apps() -> List[Dict[str, Any]]:
    return list(_APPS)


def _find(app_id: str) -> Optional[Dict[str, Any]]:
    needle = (app_id or "").strip().lower()
    for a in _APPS:
        if str(a.get("id") or "").lower() == needle or str(a.get("name") or "").lower() == needle:
            return a
    return None


def _ok(**payload: Any) -> Dict[str, Any]:
    return {"ok": True, **payload}


def _err(message: str, **payload: Any) -> Dict[str, Any]:
    return {"ok": False, "error": message, **payload}


def local_app_list() -> Dict[str, Any]:
    """List registered local web apps / servers from Amy config."""
    rows = [
        {
            "id": a.get("id"),
            "name": a.get("name") or a.get("id"),
            "base_url": a.get("base_url"),
            "health_path": a.get("health_path") or "/",
        }
        for a in _apps()
    ]
    return _ok(count=len(rows), apps=rows)


def local_app_status(app_id: str = "") -> Dict[str, Any]:
    """HTTP health check for a registered local app."""
    app = _find(app_id)
    if not app:
        return _err("unknown app_id", known=[a.get("id") for a in _apps()])
    base = str(app.get("base_url") or "").rstrip("/")
    health = str(app.get("health_path") or "/")
    if not health.startswith("/"):
        health = "/" + health
    url = base + health
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            code = int(resp.status)
            return _ok(app_id=app.get("id"), url=url, status=code, healthy=code < 500)
    except Exception as e:
        return _ok(app_id=app.get("id"), url=url, healthy=False, error=str(e))


def local_app_open(app_id: str = "", path: str = "/") -> Dict[str, Any]:
    """Open a local app in an Amy webview window (not the system browser)."""
    app = _find(app_id)
    if not app:
        return _err("unknown app_id", known=[a.get("id") for a in _apps()])
    base = str(app.get("base_url") or "").rstrip("/")
    p = path or "/"
    if not p.startswith("/"):
        p = "/" + p
    url = base + p
    host = os.environ.get("AMY_HOST", "127.0.0.1")
    port = int(os.environ.get("AMY_PORT") or "8787")
    token = os.environ.get("AMY_TOKEN", "")
    # Open dedicated webview pointed at the local app URL.
    try:
        from amy.host.hud_window import open_hud_subprocess

        # Reuse HUD process entry with absolute URL override via --url
        import sys

        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "amy.host.hud_window",
                "--host",
                host,
                "--port",
                str(port),
                "--token",
                token,
                "--url",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _ok(app_id=app.get("id"), url=url, opened="webview")
    except Exception as e:
        return _err(str(e), url=url)


def local_app_http(
    app_id: str = "",
    method: str = "GET",
    path: str = "/",
    body: str = "",
) -> Dict[str, Any]:
    """GET/POST an allowlisted local app path (localhost only)."""
    app = _find(app_id)
    if not app:
        return _err("unknown app_id")
    base = str(app.get("base_url") or "")
    parsed = urllib.parse.urlparse(base)
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        return _err("Refusing non-localhost base_url")
    p = path or "/"
    if not p.startswith("/"):
        p = "/" + p
    url = base.rstrip("/") + p
    method_u = (method or "GET").upper()
    data = None
    headers = {}
    if body and method_u in ("POST", "PUT", "PATCH"):
        data = body.encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(url, data=data, method=method_u, headers=headers)
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed_json = json.loads(raw)
            except Exception:
                parsed_json = None
            return _ok(
                status=int(resp.status),
                body=raw[:4000],
                json=parsed_json,
                url=url,
            )
    except urllib.error.HTTPError as e:
        return _err(f"HTTP {e.code}", status=e.code, url=url)
    except Exception as e:
        return _err(str(e), url=url)


def register(registry: Any) -> List[str]:
    specs = [
        (local_app_list, "List registered local servers/web apps."),
        (local_app_status, "Health-check a local app by id."),
        (local_app_open, "Open a local app in Amy webview (not browser)."),
        (local_app_http, "HTTP GET/POST to a localhost allowlisted app path."),
    ]
    out: List[str] = []
    for fn, desc in specs:
        try:
            registry.register(
                fn, name=fn.__name__, description=desc, module="amy_local_apps", overwrite=True
            )
            out.append(fn.__name__)
        except Exception:
            continue
    return out
