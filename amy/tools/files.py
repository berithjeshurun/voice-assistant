"""Workspace file tools for Amy (read-only for now)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List


def _workspace() -> Path:
    root = (
        os.environ.get("AMY_ROOT")
        or os.environ.get("PYHIVE_CWD")
        or os.getcwd()
    )
    return Path(root).resolve()


def _safe(path: str) -> Path:
    root = _workspace()
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    resolved = p.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes workspace: {path}")
    return resolved


def read_file(path: str, offset: int = 1, limit: int = 400) -> Dict[str, Any]:
    """Read a text file under the Amy workspace (1-indexed offset, line limit)."""
    try:
        p = _safe(path)
        if not p.is_file():
            return {"ok": False, "error": f"not a file: {path}"}
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(offset)) - 1
        end = start + max(1, int(limit))
        chunk = lines[start:end]
        numbered = [f"{i + start + 1}|{line}" for i, line in enumerate(chunk)]
        return {
            "ok": True,
            "path": str(p.relative_to(_workspace())).replace("\\", "/"),
            "total_lines": len(lines),
            "content": "\n".join(numbered),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def register(registry: Any) -> List[str]:
    out: List[str] = []
    try:
        registry.register(
            read_file,
            name="read_file",
            description="Read a text file under the Amy workspace (offset + limit).",
            module="amy_files",
            overwrite=True,
        )
        out.append("read_file")
    except Exception:
        pass
    return out
