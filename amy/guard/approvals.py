"""Human-in-the-loop approvals — answered by voice or from any HUD."""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

_logger = logging.getLogger(__name__)

VoiceApprover = Callable[[str], Optional[bool]]

_YES = {"yes", "yeah", "yep", "yup", "confirm", "confirmed", "approve", "approved",
        "proceed", "affirmative", "sure", "ok", "okay"}
_YES_PHRASES = ("do it", "go ahead", "go for it")
_NO = {"no", "nope", "nah", "cancel", "stop", "deny", "denied", "abort", "dont",
       "don't", "wait", "negative", "never"}


def parse_yes_no(text: str, *, strict: bool = False) -> Optional[bool]:
    """``True``/``False`` for a clear answer, ``None`` when ambiguous."""
    s = (text or "").lower()
    toks = set(re.findall(r"[a-z']+", s))
    no = bool(toks & _NO)
    if strict:
        yes = "confirm" in toks or "confirmed" in toks
    else:
        yes = bool(toks & _YES) or any(p in s for p in _YES_PHRASES)
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None


@dataclass
class Approval:
    id: str
    tool: str
    summary: str
    reason: str
    risk: str
    created_at: float
    expires_at: float
    event: threading.Event = field(default_factory=threading.Event)
    approved: Optional[bool] = None
    via: str = ""


class ApprovalBroker:
    def __init__(self, *, on_change: Optional[Callable[[List[Approval]], None]] = None) -> None:
        self._lock = threading.Lock()
        self._pending: Dict[str, Approval] = {}
        self._on_change = on_change
        self.voice_approver: Optional[VoiceApprover] = None

    def pending(self) -> List[Approval]:
        with self._lock:
            return sorted(self._pending.values(), key=lambda a: a.created_at)

    def _changed(self) -> None:
        if self._on_change:
            try:
                self._on_change(self.pending())
            except Exception:
                _logger.debug("ignored error", exc_info=True)

    def request(
        self,
        *,
        tool: str,
        summary: str,
        reason: str,
        risk: str,
        timeout_s: float,
        use_voice: bool,
    ) -> Approval:
        """Block until a human answers or the timeout passes (timeout = deny)."""
        now = time.time()
        ap = Approval(
            id=uuid.uuid4().hex[:12],
            tool=tool,
            summary=summary[:240],
            reason=reason[:160],
            risk=risk,
            created_at=now,
            expires_at=now + timeout_s,
        )
        with self._lock:
            self._pending[ap.id] = ap
        self._changed()

        if use_voice and self.voice_approver is not None:
            approver = self.voice_approver

            def _ask() -> None:
                try:
                    ans = approver(ap.summary)
                except Exception:
                    ans = None
                if ans is not None:
                    self.resolve(ap.id, ans, via="voice")

            threading.Thread(target=_ask, name="amy-approval-voice", daemon=True).start()

        ap.event.wait(timeout=max(1.0, timeout_s))
        with self._lock:
            self._pending.pop(ap.id, None)
            if ap.approved is None:
                ap.approved = False
                ap.via = "timeout"
            ap.event.set()
        self._changed()
        return ap

    def resolve(self, approval_id: str, approved: bool, *, via: str = "hud") -> bool:
        with self._lock:
            ap = self._pending.get(approval_id)
            if ap is None or ap.approved is not None:
                return False
            ap.approved = bool(approved)
            ap.via = via
            ap.event.set()
        return True

    def deny_all(self, *, via: str = "stop") -> int:
        with self._lock:
            items = [a for a in self._pending.values() if a.approved is None]
            for a in items:
                a.approved = False
                a.via = via
                a.event.set()
        return len(items)
