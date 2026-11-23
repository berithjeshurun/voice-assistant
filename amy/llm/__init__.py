"""Model routing: prefer a strong remote model, fall back to a local one automatically."""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from amy.llm.config import Backend, RoutingConfig, SshSpec, load_routing
from amy.llm.router import LlmRouter

__all__ = [
    "Backend",
    "LlmRouter",
    "RoutingConfig",
    "SshSpec",
    "get_router",
    "load_routing",
    "start_routing",
    "switch_message",
]

_logger = logging.getLogger(__name__)
_router: Optional[LlmRouter] = None


def get_router() -> Optional[LlmRouter]:
    return _router


def switch_message(old: Optional[Backend], new: Optional[Backend], primary: Optional[Backend]) -> str:
    if new is None:
        return "I can't reach any language model right now."
    if old is None:
        return f"Using {new.display}."
    if primary is not None and new.name == primary.name:
        return f"{new.display} is back; switching to it."
    return f"Lost {old.display}; switching to {new.display}."


def start_routing(
    amy_cfg: Any,
    *,
    on_switch: Optional[Callable[[Optional[Backend], Optional[Backend]], None]] = None,
) -> Optional[LlmRouter]:
    """Start the router when ``amy.llm_routing`` is configured and point PyHive at it.

    Sets ``PYHIVE_LLM_BASE_URL`` so the PyHive client talks to the router; an explicit
    ``PYHIVE_LLM_BASE_URL`` from the environment wins and disables routing.
    """
    global _router
    cfg = load_routing(amy_cfg)
    if cfg is None:
        return None
    if os.environ.get("PYHIVE_LLM_BASE_URL") and not os.environ.get("AMY_LLM_ROUTED"):
        _logger.info("PYHIVE_LLM_BASE_URL is set; model routing disabled")
        return None
    router = LlmRouter(cfg)
    if on_switch is not None:
        router.on_switch(on_switch)
    router.start()
    os.environ["PYHIVE_LLM_BASE_URL"] = router.base_url
    os.environ["AMY_LLM_ROUTED"] = "1"
    _router = router
    return router
