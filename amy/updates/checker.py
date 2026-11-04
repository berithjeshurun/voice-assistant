"""GitHub-backed update channels (app / ui / driver / firmware / other)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from amy.branding import PROTOCOL_VERSION

DEFAULT_REPO = "berithjeshurun/voice-assistant"
CHANNEL_RE = re.compile(r"channel\s*[:=]\s*(app|ui|driver|firmware|other)", re.I)
TAG_CHANNEL_RE = re.compile(
    r"(?P<ch>app|ui|driver|firmware)[-_/]?(?P<ver>v?\d[\w.\-]*)",
    re.I,
)


def _local_version() -> str:
    env = (os.environ.get("AMY_VERSION") or "").strip()
    if env:
        return env
    try:
        root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        # Prefer git describe when available
        import subprocess

        out = subprocess.run(
            ["git", "-C", root, "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        tag = (out.stdout or "").strip()
        if tag:
            return tag
    except Exception:
        pass
    return f"protocol-{PROTOCOL_VERSION}"


def _guess_channel(tag: str, body: str) -> str:
    m = CHANNEL_RE.search(body or "")
    if m:
        return m.group(1).lower()
    m2 = TAG_CHANNEL_RE.search(tag or "")
    if m2:
        return m2.group("ch").lower()
    low = (tag or "").lower()
    for ch in ("driver", "firmware", "ui", "app"):
        if ch in low:
            return ch
    return "app"


class UpdateChecker:
    def __init__(
        self,
        *,
        repo: str = DEFAULT_REPO,
        watch: Optional[List[Dict[str, str]]] = None,
        cooldown_s: float = 900.0,
    ) -> None:
        self.repo = (repo or DEFAULT_REPO).strip()
        self.watch = list(watch or [])
        self.cooldown_s = max(60.0, float(cooldown_s))
        self._lock = threading.Lock()
        self._cache: Dict[str, Any] = {
            "ok": True,
            "local_version": _local_version(),
            "checked_at": 0.0,
            "channels": [],
            "error": None,
        }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            snap = dict(self._cache)
            snap["channels"] = list(self._cache.get("channels") or [])
            return snap

    def check(self, *, force: bool = False) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            last = float(self._cache.get("checked_at") or 0.0)
            if not force and last and (now - last) < self.cooldown_s:
                return self.status()

        channels: List[Dict[str, Any]] = []
        err: Optional[str] = None
        try:
            channels.extend(self._fetch_repo_releases(self.repo))
            for item in self.watch:
                if not isinstance(item, dict):
                    continue
                repo = str(item.get("repo") or "").strip()
                if not repo:
                    continue
                label = str(item.get("channel") or item.get("label") or "other")
                for ch in self._fetch_repo_releases(repo):
                    ch["channel"] = label if label else ch.get("channel")
                    channels.append(ch)
        except Exception as e:
            err = str(e)

        local = _local_version()
        for ch in channels:
            ch["newer"] = bool(ch.get("tag") and ch.get("tag") != local)

        payload = {
            "ok": err is None,
            "local_version": local,
            "checked_at": time.time(),
            "channels": channels[:24],
            "error": err,
            "repo": self.repo,
        }
        with self._lock:
            self._cache = payload
        return dict(payload)

    def _fetch_repo_releases(self, repo: str) -> List[Dict[str, Any]]:
        url = f"https://api.github.com/repos/{repo}/releases?per_page=8"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Amy-UpdateChecker",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return self._fetch_tags(repo)
            raise
        if not isinstance(data, list):
            return []
        out: List[Dict[str, Any]] = []
        for rel in data:
            if not isinstance(rel, dict) or rel.get("draft"):
                continue
            tag = str(rel.get("tag_name") or "")
            body = str(rel.get("body") or "")
            out.append(
                {
                    "repo": repo,
                    "tag": tag,
                    "name": str(rel.get("name") or tag),
                    "channel": _guess_channel(tag, body),
                    "url": str(rel.get("html_url") or ""),
                    "published_at": str(rel.get("published_at") or ""),
                    "prerelease": bool(rel.get("prerelease")),
                }
            )
        return out

    def _fetch_tags(self, repo: str) -> List[Dict[str, Any]]:
        url = f"https://api.github.com/repos/{repo}/tags?per_page=5"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Amy-UpdateChecker",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if not isinstance(data, list):
            return []
        out: List[Dict[str, Any]] = []
        for tag in data:
            if not isinstance(tag, dict):
                continue
            name = str(tag.get("name") or "")
            out.append(
                {
                    "repo": repo,
                    "tag": name,
                    "name": name,
                    "channel": _guess_channel(name, ""),
                    "url": f"https://github.com/{repo}/releases/tag/{name}",
                    "published_at": "",
                    "prerelease": False,
                }
            )
        return out


_checker: Optional[UpdateChecker] = None
_lock = threading.Lock()


def get_update_checker(config: Optional[Dict[str, Any]] = None) -> UpdateChecker:
    global _checker
    with _lock:
        if _checker is None:
            cfg = config or {}
            _checker = UpdateChecker(
                repo=str(cfg.get("repo") or DEFAULT_REPO),
                watch=list(cfg.get("watch") or []),
                cooldown_s=float(cfg.get("cooldown_s") or 900),
            )
        return _checker
