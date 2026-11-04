"""Scrub secrets out of tool results and audit records."""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, List, Set

MASK = "[REDACTED]"

_SECRET_ENV_RE = re.compile(r"(TOKEN|PASSWORD|PASSWD|SECRET|API_?KEY|ACCESS_CODE|PRIVATE)", re.I)

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"(?i)(?<=\bbearer )[A-Za-z0-9._~+/\-]{16,}=*"),
]
_KV_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?code|auth[_-]?token)"
    r"(\s*[:=]\s*)([\"']?)([^\s\"',;]{4,})"
)


class Redactor:
    def __init__(self, *, refresh_s: float = 60.0) -> None:
        self._lock = threading.Lock()
        self._literals: List[str] = []
        self._loaded_at = 0.0
        self._refresh_s = refresh_s
        self._extra: Set[str] = set()

    def add_literal(self, value: str) -> None:
        if value and len(value) >= 6:
            with self._lock:
                self._extra.add(value)
                self._loaded_at = 0.0

    def _load(self) -> List[str]:
        vals: Set[str] = set(self._extra)
        for key, val in os.environ.items():
            if _SECRET_ENV_RE.search(key) and val and len(val.strip()) >= 6:
                vals.add(val.strip())
        files: List[Path] = []
        root = os.environ.get("AMY_ROOT")
        if root:
            files.append(Path(root) / ".env")
        sdir = Path(os.environ.get("AMY_SECRETS_DIR") or (Path.home() / ".amy" / "secrets"))
        if sdir.is_dir():
            files.extend(sdir.glob("*.env"))
        for f in files:
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    s = line.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    k, _, v = s.partition("=")
                    v = v.strip().strip('"').strip("'")
                    if v and len(v) >= 6 and (_SECRET_ENV_RE.search(k) or "USER" in k.upper()):
                        vals.add(v)
            except Exception:
                continue
        return sorted(vals, key=len, reverse=True)

    def literals(self) -> List[str]:
        with self._lock:
            if time.time() - self._loaded_at > self._refresh_s:
                self._literals = self._load()
                self._loaded_at = time.time()
            return list(self._literals)

    def contains_secret(self, text: str) -> bool:
        if not text:
            return False
        if any(lit in text for lit in self.literals()):
            return True
        return any(p.search(text) for p in _PATTERNS)

    def text(self, s: str) -> str:
        if not s:
            return s
        for lit in self.literals():
            if lit in s:
                s = s.replace(lit, MASK)
        for p in _PATTERNS:
            s = p.sub(MASK, s)
        return _KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{MASK}", s)

    def value(self, v: Any, _depth: int = 0) -> Any:
        if _depth > 8:
            return v
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, dict):
            return {k: self.value(x, _depth + 1) for k, x in v.items()}
        if isinstance(v, list):
            return [self.value(x, _depth + 1) for x in v]
        if isinstance(v, tuple):
            return tuple(self.value(x, _depth + 1) for x in v)
        return v
