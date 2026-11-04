"""The single place Amy reaches into PyHive internals.

PyHive's ``AssistantShell`` keeps its agent, context, bundle and config on private
attributes (``_agent``, ``_ctx``, ``_bundle``, ``_hcfg``). Everything in Amy goes through
:class:`HiveAdapter` instead, so a PyHive upgrade touches one file, and tests can hand
the host a fake shell.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

_logger = logging.getLogger(__name__)


class HiveAdapter:
    def __init__(self, shell: Any) -> None:
        self.shell = shell

    # --- raw parts ---------------------------------------------------------------

    @property
    def bundle(self) -> Dict[str, Any]:
        b = getattr(self.shell, "_bundle", None)
        return b if isinstance(b, dict) else {}

    @property
    def registry(self) -> Any:
        return self.bundle.get("registry")

    @property
    def memory(self) -> Any:
        return self.bundle.get("memory")

    @property
    def agent(self) -> Any:
        return getattr(self.shell, "_agent", None)

    @property
    def ctx(self) -> Any:
        return getattr(self.shell, "_ctx", None)

    @property
    def hive_config(self) -> Any:
        return getattr(self.shell, "_hcfg", None)

    @property
    def assistant_config(self) -> Any:
        hcfg = self.hive_config
        return getattr(hcfg, "assistant", None) if hcfg is not None else None

    @property
    def ambient_config(self) -> Any:
        asst = self.assistant_config
        return getattr(asst, "ambient", None) if asst is not None else None

    @property
    def llm(self) -> Any:
        """The underlying PyHive LLM client (unwrapped from the agent adapter)."""
        agent = self.agent
        if agent is None:
            return None
        wrapped = getattr(agent, "llm", None)
        return getattr(wrapped, "_pyhive_llm", None) or wrapped

    # --- services ------------------------------------------------------------------

    @property
    def bundle_services(self) -> Dict[str, Any]:
        b = getattr(self.shell, "_bundle", None)
        if not isinstance(b, dict):
            return {}
        svc = b.setdefault("services", {})
        return svc if isinstance(svc, dict) else {}

    @property
    def ctx_services(self) -> Optional[Dict[str, Any]]:
        ctx = self.ctx
        svc = getattr(ctx, "services", None) if ctx is not None else None
        return svc if isinstance(svc, dict) else None

    @property
    def emitter(self) -> Any:
        return (self.ctx_services or {}).get("emitter")

    def ensure_ctx(self) -> Dict[str, Any]:
        """Start the shell if its run context is missing; return the context services."""
        if self.ctx is None:
            self.shell.start()
        svc = self.ctx_services
        if svc is None:
            raise RuntimeError("PyHive shell has no run context after start()")
        return svc

    def set_service(self, key: str, value: Any, *, bundle: bool = False) -> None:
        """Publish a service to the agent context (and optionally the shell bundle)."""
        svc = self.ctx_services
        if svc is not None:
            svc[key] = value
        if bundle:
            self.bundle_services[key] = value

    def service(self, key: str, default: Any = None) -> Any:
        svc = self.ctx_services or {}
        if key in svc:
            return svc[key]
        return self.bundle_services.get(key, default)

    # --- system prompt -----------------------------------------------------------------

    @property
    def system_prompt(self) -> str:
        return str(getattr(self.agent, "system_prompt", "") or "") if self.agent else ""

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        if self.agent is not None:
            self.agent.system_prompt = value

    def upsert_prompt_block(self, start: str, end: str, block: str) -> bool:
        """Replace the ``start``…``end`` section with ``block``, or append it.

        Text after the section (e.g. the live ENVIRONMENT block) is preserved.
        """
        if self.agent is None:
            return False
        sp = self.system_prompt
        i = sp.find(start)
        if i < 0:
            self.system_prompt = sp + block
            return True
        j = sp.find(end, i)
        tail = sp[j + len(end):] if j >= 0 else ""
        self.system_prompt = sp[:i] + block + tail
        return True

    def append_prompt_block_once(self, marker: str, block: str) -> bool:
        """Append ``block`` unless ``marker`` is already in the prompt."""
        if self.agent is None:
            return False
        sp = self.system_prompt
        if marker in sp:
            return False
        self.system_prompt = sp + block
        return True

    # --- turns ---------------------------------------------------------------------------

    def turn(self, text: str) -> Any:
        return self.shell.turn(text)

    def disable_hitl(self) -> None:
        """Voice is headless; a config ``hitl: true`` would deny tools on stdin EOF."""
        asst = self.assistant_config
        if asst is not None and getattr(asst, "hitl", False):
            try:
                asst.hitl = False
            except Exception:
                _logger.warning("could not force assistant.hitl off", exc_info=True)
