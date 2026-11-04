from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from amy.guard import Guard, GuardConfig
from amy.guard.audit import AuditLog
from amy.host.events import EventBus
from amy.server.app import create_app


class StubHost:
    def __init__(self, tmp_path):
        self.bus = EventBus()
        self.guard = Guard(GuardConfig(read_roots=[tmp_path], approval_timeout_s=5), bus=self.bus,
                           audit=AuditLog(tmp_path / "audit.jsonl"), on_log=lambda m: None)
        self.voice_ok = False
        self.wake_ok = False


def _client(tmp_path):
    host = StubHost(tmp_path)
    return host, TestClient(create_app(host, token="tok-123"))


def test_headers_and_auth(tmp_path):
    _, c = _client(tmp_path)
    r = c.get("/api/guard?token=tok-123")
    assert r.status_code == 200 and r.json()["mode"] == "standard"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "access-control-allow-origin" not in c.get(
        "/api/guard?token=tok-123", headers={"Origin": "http://evil"}).headers


def test_bad_token_throttled(tmp_path):
    _, c = _client(tmp_path)
    for _ in range(20):
        assert c.get("/api/guard?token=nope").status_code == 401
    assert c.get("/api/guard?token=tok-123").status_code == 429


def test_approve_endpoint(tmp_path):
    host, c = _client(tmp_path)
    result = {}

    def ask():
        ap = host.guard.broker.request(tool="os_power", summary="shut down", reason="r",
                                       risk="high", timeout_s=5, use_voice=False)
        result["ok"] = ap.approved

    t = threading.Thread(target=ask)
    t.start()
    for _ in range(100):
        pending = c.get("/api/snapshot?token=tok-123").json()["approvals"]
        if pending:
            break
        time.sleep(0.02)
    assert c.post("/api/approve", json={"id": "missing", "approve": True},
                  headers={"X-Amy-Token": "tok-123"}).json()["ok"] is False
    r = c.post("/api/approve", json={"id": pending[0]["id"], "approve": True},
               headers={"X-Amy-Token": "tok-123"})
    assert r.json()["ok"] is True
    t.join(3)
    assert result["ok"] is True


def test_lockdown_endpoint(tmp_path):
    host, c = _client(tmp_path)
    r = c.post("/api/guard/lockdown", json={"on": True}, headers={"X-Amy-Token": "tok-123"})
    assert r.json()["lockdown"] is True
    assert host.guard.cfg.lockdown
    assert c.get("/api/snapshot?token=tok-123").json()["guard"]["lockdown"] is True
