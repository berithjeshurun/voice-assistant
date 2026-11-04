"""Amy safety guard — policy gate in front of every agent tool call.

The model is treated as untrusted: system prompts are advice, this layer is
enforcement. Settings live under ``amy.guard`` in config/hive.yaml.
"""

from amy.guard.approvals import ApprovalBroker, parse_yes_no
from amy.guard.config import GuardConfig, load_guard_config
from amy.guard.runtime import Guard, get_guard, set_guard

__all__ = [
    "ApprovalBroker",
    "Guard",
    "GuardConfig",
    "get_guard",
    "load_guard_config",
    "parse_yes_no",
    "set_guard",
]
