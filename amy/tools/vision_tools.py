"""Voice-reachable vision / person recognition tools."""

from __future__ import annotations

from typing import Any, Dict, List

from amy.vision.service import get_vision_service


def vision_status() -> Dict[str, Any]:
    """Status of Amy vision store (enrolled people, last event)."""
    return get_vision_service().status()


def vision_list_people() -> Dict[str, Any]:
    """List enrolled people in the local vision store."""
    return get_vision_service().list_people()


def vision_enroll(name: str = "", image_path: str = "", from_camera: bool = False) -> Dict[str, Any]:
    """Enroll a person from camera or image_path into Amy's local vision store."""
    return get_vision_service().enroll(
        name, image_path=image_path, from_camera=bool(from_camera)
    )


def vision_recognize(image_path: str = "", from_camera: bool = False) -> Dict[str, Any]:
    """Recognize a person from camera or image_path against enrolled hashes."""
    return get_vision_service().recognize(
        image_path=image_path, from_camera=bool(from_camera)
    )


def register(registry: Any) -> List[str]:
    specs = [
        (vision_status, "Vision store status — people count and last event."),
        (vision_list_people, "List enrolled people."),
        (vision_enroll, "Enroll person by name from camera or image_path."),
        (vision_recognize, "Recognize person from camera or image_path."),
    ]
    out: List[str] = []
    for fn, desc in specs:
        try:
            registry.register(
                fn, name=fn.__name__, description=desc, module="amy_vision", overwrite=True
            )
            out.append(fn.__name__)
        except Exception:
            continue
    return out
