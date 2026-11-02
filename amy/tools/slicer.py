"""3D slicer integration — find and open Bambu Studio / Orca / PrusaSlicer."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def apply_config(config: Any = None) -> None:
    raw = None
    if config is None:
        return
    if isinstance(config, dict):
        raw = config.get("slicer") or (config.get("amy") or {}).get("slicer")
    else:
        raw = getattr(config, "slicer", None)
        if raw is None:
            amy = getattr(config, "amy", None)
            raw = getattr(amy, "slicer", None) if amy is not None else None
    if raw is None:
        return
    preferred = None
    if isinstance(raw, dict):
        preferred = raw.get("preferred") or raw.get("path")
    else:
        preferred = getattr(raw, "preferred", None) or getattr(raw, "path", None)
    if preferred:
        os.environ["AMY_SLICER_PATH"] = str(preferred)


_CANDIDATES = [
    # Bambu Studio
    r"%LOCALAPPDATA%\Programs\Bambu Studio\bambu-studio.exe",
    r"%ProgramFiles%\Bambu Studio\bambu-studio.exe",
    r"%ProgramFiles%\BambuLab\Bambu Studio\bambu-studio.exe",
    # Orca Slicer
    r"%LOCALAPPDATA%\Programs\OrcaSlicer\orca-slicer.exe",
    r"%ProgramFiles%\OrcaSlicer\orca-slicer.exe",
    # PrusaSlicer
    r"%ProgramFiles%\Prusa3D\PrusaSlicer\prusa-slicer.exe",
    r"%LOCALAPPDATA%\Programs\PrusaSlicer\prusa-slicer.exe",
]


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


def _discover() -> List[Dict[str, str]]:
    found: List[Dict[str, str]] = []
    seen = set()
    preferred = os.environ.get("AMY_SLICER_PATH", "").strip()
    paths = ([preferred] if preferred else []) + list(_CANDIDATES)
    for raw in paths:
        path = _expand(raw)
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            name = path.stem.lower()
            kind = (
                "bambu"
                if "bambu" in name
                else "orca"
                if "orca" in name
                else "prusa"
                if "prusa" in name
                else "slicer"
            )
            found.append({"name": path.stem, "kind": kind, "path": str(path)})
    return found


def slicer_find() -> Dict[str, Any]:
    """List installed slicers Amy can launch (Bambu Studio, Orca, Prusa)."""
    found = _discover()
    return {
        "ok": bool(found),
        "slicers": found,
        "message": (
            f"Found {len(found)} slicer(s)."
            if found
            else "No slicer found — install Bambu Studio or OrcaSlicer."
        ),
    }


def slicer_open(
    path: str = "",
    slicer: str = "",
) -> Dict[str, Any]:
    """Open a model (.stl/.3mf/.obj) in a slicer, or launch the slicer alone."""
    found = _discover()
    if not found:
        return {
            "ok": False,
            "error": "No slicer installed",
            "hint": "Install Bambu Studio or set amy.slicer.path in hive.yaml",
        }

    want = (slicer or "").strip().lower()
    chosen = found[0]
    if want:
        for item in found:
            if want in item["kind"] or want in item["name"].lower():
                chosen = item
                break

    exe = chosen["path"]
    model = (path or "").strip()
    args = [exe]
    if model:
        model_path = Path(os.path.expandvars(os.path.expanduser(model)))
        if not model_path.exists():
            return {"ok": False, "error": f"Model not found: {model}"}
        args.append(str(model_path.resolve()))

    try:
        if sys.platform == "win32":
            subprocess.Popen(args, shell=False)
        else:
            subprocess.Popen(args)
        return {
            "ok": True,
            "slicer": chosen["name"],
            "kind": chosen["kind"],
            "exe": exe,
            "model": model or None,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "exe": exe}


def register(registry: Any, *, config: Any = None) -> List[str]:
    apply_config(config)
    specs = [
        (slicer_find, "List installed 3D slicers (Bambu Studio, Orca, Prusa)."),
        (
            slicer_open,
            "Open a .stl/.3mf/.obj in a slicer, or launch the slicer app.",
        ),
    ]
    out: List[str] = []
    for fn, desc in specs:
        try:
            registry.register(
                fn,
                name=fn.__name__,
                description=desc,
                module="amy_slicer",
                overwrite=True,
            )
            out.append(fn.__name__)
        except Exception:
            continue
    return out
