"""Server: roles, sessions, device tokens, live-update protocol, busy handling, history."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from amy.errors import HostBusy
from amy.guard import Guard, GuardConfig
from amy.guard.audit import AuditLog
from amy.host.events import EventBus, snapshot_patch
from amy.protocol.messages import AssistantState
from amy.server.app import create_app
from amy.server.auth import Authenticator, DeviceRegistry, Principal, SessionSigner
from amy.storage import SqliteHistory

ADMIN = "admin-tok-123"


class StubHost:
    def __init__(self, tmp_path, bus=None):
        self.bus = bus or EventBus()
        self.guard = Guard(
            GuardConfig(read_roots=[tmp_path], approval_timeout_s=5),
            bus=self.bus,
            audit=AuditLog(tmp_path / "audit.jsonl"),
            on_log=lambda m: None,
        )
        self.voice_ok = True
        self.wake_ok = True
        self._started = True
        self.busy = False
        self.turns: list[str] = []
        self.persona = ""

    def turn_text(self, text):
        if self.busy:
            raise HostBusy("busy")
        self.turns.append(text)
        self.bus.record_turn(text, f"echo {text}")
        return f"echo {text}"

    def trigger_wake(self, reason=""):
        pass

    def barge_in(self):
        pass

    def set_ui_state(self, state, detail=""):
        self.bus.set_state(state, detail=detail)

    def apply_persona(self, block):
        self.persona = block
        return True


@pytest.fixture
def env(tmp_path):
    devices = DeviceRegistry(tmp_path / "devices.json")
    host = StubHost(tmp_path)
    client = TestClient(create_app(host, token=ADMIN, devices=devices))
    return host, client, devices


def H(tok):
    return {"X-Amy-Token": tok}


def test_device_roles_are_enforced(env):
    host, c, devices = env
    viewer = devices.add("tablet", role="viewer")
    user = devices.add("phone", role="user")

    assert c.get("/api/snapshot", headers=H(viewer)).status_code == 200
    assert c.post("/api/turn", json={"text": "hi"}, headers=H(viewer)).status_code == 403
    assert c.post("/api/turn", json={"text": "hi"}, headers=H(user)).json()["reply"] == "echo hi"
    # users may lock down but not lift it; approvals and config are admin-only
    assert c.post("/api/guard/lockdown", json={"on": True}, headers=H(user)).status_code == 200
    assert c.post("/api/guard/lockdown", json={"on": False}, headers=H(user)).status_code == 403
    assert c.post("/api/guard/lockdown", json={"on": False}, headers=H(ADMIN)).status_code == 200
    assert c.post("/api/approve", json={"id": "x", "approve": True}, headers=H(user)).status_code == 403
    assert c.get("/api/config", headers=H(user)).status_code == 403
    assert c.get("/api/whoami", headers=H(user)).json() == {"ok": True, "name": "phone", "role": "user"}


def test_revoked_device_loses_access(env):
    _, c, devices = env
    tok = devices.add("old-phone", role="user")
    assert c.get("/api/snapshot", headers=H(tok)).status_code == 200
    devices.remove("old-phone")
    assert c.get("/api/snapshot", headers=H(tok)).status_code == 401


def test_device_tokens_are_stored_hashed(tmp_path):
    reg = DeviceRegistry(tmp_path / "d.json")
    tok = reg.add("phone", role="user")
    assert tok not in (tmp_path / "d.json").read_text()
    assert DeviceRegistry(tmp_path / "d.json").match(tok) == Principal("phone", "user")
    with pytest.raises(ValueError):
        reg.add("host-evil", role="admin")


def test_session_cookie_replaces_token(env):
    _, c, devices = env
    tok = devices.add("phone", role="user")
    r = c.post("/api/session", headers=H(tok))
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    # no token from here on
    assert c.get("/api/whoami").json()["role"] == "user"
    devices.remove("phone")
    assert c.get("/api/whoami").status_code == 401


def test_host_session_ends_when_admin_token_rotates(tmp_path):
    signer = SessionSigner(b"k" * 32)
    a1 = Authenticator("token-one", signer=signer)
    cookie = signer.issue(a1.from_token("token-one"))
    assert a1.from_session(cookie).role == "admin"
    a2 = Authenticator("token-two", signer=signer)
    assert a2.from_session(cookie) is None


def test_tampered_or_expired_session_rejected():
    signer = SessionSigner(b"k" * 32, ttl_s=-1)
    expired = signer.issue(Principal("phone", "user"))
    assert signer.verify(expired) is None
    good = SessionSigner(b"k" * 32).issue(Principal("phone", "user"))
    body, sig = good.split(".")
    assert SessionSigner(b"k" * 32).verify(body + "." + sig[::-1]) is None
    assert SessionSigner(b"x" * 32).verify(good) is None


def test_busy_turn_returns_409(env):
    host, c, _ = env
    host.busy = True
    r = c.post("/api/turn", json={"text": "hi"}, headers=H(ADMIN))
    assert r.status_code == 409 and r.json()["error"] == "busy"


def test_turn_text_length_is_bounded(env):
    _, c, _ = env
    assert c.post("/api/turn", json={"text": "x" * 9000}, headers=H(ADMIN)).status_code == 422


def test_security_headers_include_csp(env):
    _, c, _ = env
    r = c.get("/api/snapshot", headers=H(ADMIN))
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "server" not in {k.lower() for k in r.headers} or "uvicorn" not in r.headers.get("server", "")


def test_websocket_snapshot_then_patches(env):
    host, c, _ = env
    with c.websocket_connect(f"/ws?token={ADMIN}") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot" and first["role"] == "admin"
        assert first["data"]["state"] == "idle"
        host.bus.set_caption("hello there", role="speak")
        msg = ws.receive_json()
        assert msg["type"] == "patch"
        assert msg["data"] == {"caption": "hello there", "caption_role": "speak"}


def test_websocket_coalesces_bursts(env):
    host, c, _ = env
    with c.websocket_connect(f"/ws?token={ADMIN}") as ws:
        ws.receive_json()
        for i in range(200):
            host.bus.set_state(AssistantState.speaking, audio_level=i / 200)
        host.bus.set_state(AssistantState.speaking, audio_level=0.0, detail="done")
        seen, last = 0, None
        deadline = time.time() + 3
        while time.time() < deadline:
            msg = ws.receive_json()
            seen += 1
            last = msg["data"]
            if last.get("detail") == "done" or last.get("audio_level") == 0.0 and seen > 1:
                break
        assert seen < 50  # 200 updates arrive as a handful of patches
        assert last is not None


def test_websocket_viewer_cannot_send_turns(env):
    host, c, devices = env
    tok = devices.add("tablet", role="viewer")
    with c.websocket_connect(f"/ws?token={tok}") as ws:
        ws.receive_json()
        ws.send_json({"type": "turn", "text": "hi"})
        msg = ws.receive_json()
        assert msg["type"] == "error" and "user" in msg["error"]
    assert host.turns == []


def test_websocket_turn_result(env):
    host, c, _ = env
    with c.websocket_connect(f"/ws?token={ADMIN}") as ws:
        ws.receive_json()
        ws.send_json({"type": "turn", "text": "ping"})
        for _ in range(20):
            msg = ws.receive_json()
            if msg["type"] == "turn_result":
                assert msg["ok"] and msg["reply"] == "echo ping"
                break
        else:
            pytest.fail("no turn_result")


def test_websocket_rejects_bad_token(env):
    _, c, _ = env
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws?token=nope") as ws:
            ws.receive_json()


def test_settings_push_persona_through_host(env):
    host, c, _ = env
    r = c.post("/api/settings", json={"persona_preset": "warm"}, headers=H(ADMIN))
    assert r.json()["ok"]
    assert "PERSONA PRESET (" in host.persona


def test_history_store_roundtrip_and_search(tmp_path):
    store = SqliteHistory(tmp_path / "h.db")
    bus = EventBus(history_store=store)
    bus.record_turn("what's the weather", "sunny")
    bus.record_turn("open notepad", "done")
    again = EventBus(history_store=SqliteHistory(tmp_path / "h.db"))
    assert [m.text for m in again.history()] == ["what's the weather", "sunny", "open notepad", "done"]
    assert [m.text for m in store.search("weather")] == ["what's the weather"]
    assert store.search("100%_") == []


def test_history_prunes_to_cap(tmp_path):
    from amy.protocol.messages import ChatMessage

    store = SqliteHistory(tmp_path / "h.db", max_rows=50)
    for i in range(400):
        store.append(ChatMessage(role="user", text=str(i), ts=i))
    assert store.count() <= 250
    assert store.recent(1)[0].text == "399"


def test_history_endpoint(tmp_path):
    host = StubHost(tmp_path, bus=EventBus(history_store=SqliteHistory(tmp_path / "h.db")))
    c = TestClient(create_app(host, token=ADMIN))
    host.bus.record_turn("remind me about the dentist", "ok")
    r = c.get("/api/history?q=dentist", headers=H(ADMIN)).json()
    assert [m["text"] for m in r["history"]] == ["remind me about the dentist"]


def test_snapshot_patch():
    assert snapshot_patch(None, {"a": 1}) == {"a": 1}
    assert snapshot_patch({"a": 1, "b": [1]}, {"a": 1, "b": [1, 2]}) == {"b": [1, 2]}


def test_doctor_endpoint_admin_only(env):
    _, c, devices = env
    tok = devices.add("phone", role="user")
    assert c.get("/api/doctor", headers=H(tok)).status_code == 403
    rep = c.get("/api/doctor", headers=H(ADMIN)).json()
    names = {ch["name"] for ch in rep["checks"]}
    assert {"host", "voice", "safety guard", "python"} <= names
