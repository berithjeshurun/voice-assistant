"""Live host metrics — RAM, disk, network, CPU (best-effort, no mock)."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

_last_net: Optional[Dict[str, float]] = None
_last_net_ts: float = 0.0


def sample_system() -> Dict[str, Any]:
    """Return a JSON-safe metrics snapshot. Missing fields stay null."""
    out: Dict[str, Any] = {
        "ok": True,
        "ts": time.time(),
        "cpu_percent": None,
        "ram": None,
        "disk": None,
        "net": None,
        "error": None,
    }
    try:
        import psutil  # type: ignore
    except Exception as e:
        out["ok"] = False
        out["error"] = f"psutil unavailable: {e}"
        return out

    try:
        out["cpu_percent"] = float(psutil.cpu_percent(interval=0.05))
    except Exception:
        pass

    try:
        vm = psutil.virtual_memory()
        out["ram"] = {
            "total_gb": round(vm.total / (1024**3), 2),
            "used_gb": round(vm.used / (1024**3), 2),
            "percent": float(vm.percent),
            "available_gb": round(vm.available / (1024**3), 2),
        }
    except Exception:
        pass

    try:
        root = os.environ.get("SystemDrive", "C:") + "\\"
        if os.name != "nt":
            root = "/"
        du = psutil.disk_usage(root)
        out["disk"] = {
            "path": root,
            "total_gb": round(du.total / (1024**3), 2),
            "used_gb": round(du.used / (1024**3), 2),
            "percent": float(du.percent),
            "free_gb": round(du.free / (1024**3), 2),
        }
    except Exception:
        pass

    global _last_net, _last_net_ts
    try:
        n = psutil.net_io_counters()
        now = time.time()
        sent = float(n.bytes_sent)
        recv = float(n.bytes_recv)
        up_bps = 0.0
        down_bps = 0.0
        if _last_net and _last_net_ts > 0:
            dt = max(0.05, now - _last_net_ts)
            up_bps = max(0.0, (sent - _last_net["sent"]) / dt)
            down_bps = max(0.0, (recv - _last_net["recv"]) / dt)
        _last_net = {"sent": sent, "recv": recv}
        _last_net_ts = now
        out["net"] = {
            "bytes_sent": int(sent),
            "bytes_recv": int(recv),
            "up_mbps": round((up_bps * 8) / 1_000_000, 3),
            "down_mbps": round((down_bps * 8) / 1_000_000, 3),
        }
    except Exception:
        pass

    return out
