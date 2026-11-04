"""Local person/image recognition store — voice + HUD reachable.

Full ML training is later; this pass stores enrollments and does a simple
image-hash match so the pipeline is real (no mock people).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

_logger = logging.getLogger(__name__)


def _root() -> Path:
    p = Path.home() / ".amy" / "vision"
    p.mkdir(parents=True, exist_ok=True)
    (p / "people").mkdir(parents=True, exist_ok=True)
    return p


def _phash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class VisionService:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or _root()
        self._lock = threading.Lock()
        self._last: Dict[str, Any] = {}
        self._index_path = self.root / "index.json"
        self._index = self._load()

    def _load(self) -> Dict[str, Any]:
        if self._index_path.is_file():
            try:
                return json.loads(self._index_path.read_text(encoding="utf-8"))
            except Exception:
                _logger.debug("ignored error", exc_info=True)
        return {"people": {}, "updated": 0.0}

    def _save(self) -> None:
        self._index["updated"] = time.time()
        self._index_path.write_text(
            json.dumps(self._index, indent=2), encoding="utf-8"
        )

    def status(self) -> Dict[str, Any]:
        with self._lock:
            people = self._index.get("people") or {}
            return {
                "ok": True,
                "people_count": len(people),
                "people": sorted(people.keys()),
                "last": dict(self._last) if self._last else None,
                "store": str(self.root),
            }

    def list_people(self) -> Dict[str, Any]:
        with self._lock:
            people = self._index.get("people") or {}
            rows = []
            for name, meta in people.items():
                rows.append(
                    {
                        "name": name,
                        "samples": int(meta.get("samples") or 0),
                        "updated": meta.get("updated"),
                    }
                )
            return {"ok": True, "people": rows}

    def enroll(
        self,
        name: str,
        *,
        image_path: str = "",
        image_bytes: Optional[bytes] = None,
        from_camera: bool = False,
    ) -> Dict[str, Any]:
        person = (name or "").strip()
        if not person:
            return {"ok": False, "error": "name required"}
        data = image_bytes
        src = "bytes"
        if from_camera and data is None:
            shot = self._capture_camera()
            if not shot.get("ok"):
                return shot
            data = shot.get("bytes")
            src = "camera"
        if data is None and image_path:
            try:
                data = Path(image_path).read_bytes()
                src = image_path
            except Exception as e:
                return {"ok": False, "error": str(e)}
        if not data:
            return {
                "ok": False,
                "error": "Provide image_path, image bytes, or from_camera=true",
            }
        digest = _phash(data)
        safe = "".join(c for c in person.lower() if c.isalnum() or c in "-_")[:48] or "person"
        folder = self.root / "people" / safe
        folder.mkdir(parents=True, exist_ok=True)
        sample = folder / f"{int(time.time())}_{digest[:10]}.bin"
        sample.write_bytes(data)
        with self._lock:
            people = self._index.setdefault("people", {})
            meta = people.get(person) or {"hashes": [], "samples": 0}
            hashes = list(meta.get("hashes") or [])
            if digest not in hashes:
                hashes.append(digest)
            meta["hashes"] = hashes[-32:]
            meta["samples"] = int(meta.get("samples") or 0) + 1
            meta["updated"] = time.time()
            meta["last_source"] = src
            people[person] = meta
            self._save()
            self._last = {
                "event": "enroll",
                "name": person,
                "ts": time.time(),
                "source": src,
            }
        return {"ok": True, "name": person, "samples": meta["samples"], "source": src}

    def recognize(
        self,
        *,
        image_path: str = "",
        image_bytes: Optional[bytes] = None,
        from_camera: bool = False,
    ) -> Dict[str, Any]:
        data = image_bytes
        src = "bytes"
        if from_camera and data is None:
            shot = self._capture_camera()
            if not shot.get("ok"):
                return shot
            data = shot.get("bytes")
            src = "camera"
        if data is None and image_path:
            try:
                data = Path(image_path).read_bytes()
                src = image_path
            except Exception as e:
                return {"ok": False, "error": str(e)}
        if not data:
            return {"ok": False, "error": "No image to recognize"}
        digest = _phash(data)
        match = None
        with self._lock:
            for name, meta in (self._index.get("people") or {}).items():
                hashes = meta.get("hashes") or []
                if digest in hashes:
                    match = name
                    break
            self._last = {
                "event": "recognize",
                "name": match,
                "matched": bool(match),
                "ts": time.time(),
                "source": src,
            }
        return {
            "ok": True,
            "matched": bool(match),
            "name": match,
            "source": src,
            "note": "Exact perceptual hash match (foundation). Deeper embeddings later.",
        }

    def _capture_camera(self) -> Dict[str, Any]:
        """Best-effort webcam grab via OpenCV if installed."""
        try:
            import cv2  # type: ignore
        except Exception as e:
            return {
                "ok": False,
                "error": f"Camera capture needs opencv-python ({e}). Pass image_path instead.",
            }
        cam = cv2.VideoCapture(0)
        try:
            if not cam.isOpened():
                return {"ok": False, "error": "No camera available"}
            ok, frame = cam.read()
            if not ok or frame is None:
                return {"ok": False, "error": "Camera frame failed"}
            ok2, buf = cv2.imencode(".jpg", frame)
            if not ok2:
                return {"ok": False, "error": "Encode failed"}
            return {"ok": True, "bytes": bytes(buf)}
        finally:
            cam.release()


_svc: Optional[VisionService] = None
_lock = threading.Lock()


def get_vision_service() -> VisionService:
    global _svc
    with _lock:
        if _svc is None:
            _svc = VisionService()
        return _svc
