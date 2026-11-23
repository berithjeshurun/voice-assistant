"""Model router: health, failover mid-request, recovery hysteresis, streaming, tunnels, doctor."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from amy.llm import LlmRouter, load_routing, start_routing, switch_message
from amy.llm.config import Backend, RoutingConfig, SshSpec
from amy.llm.router import rewrite_model
from amy.llm.tunnel import SshTunnel


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeOllama:
    """Tiny Ollama look-alike: /api/tags, /v1/chat/completions (optionally streamed)."""

    def __init__(self, name: str, models: list[str], port: int | None = None) -> None:
        self.name, self.models = name, models
        self.port = port or free_port()
        self.seen: list[dict] = []
        self.fail_status: int | None = None
        self._srv: ThreadingHTTPServer | None = None

    def start(self) -> FakeOllama:
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._json(200, {"models": [{"name": m} for m in fake.models]})
                else:
                    self._json(404, {"error": "nope"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                fake.seen.append(body)
                if fake.fail_status:
                    self._json(fake.fail_status, {"error": f"{fake.name} failing"})
                    return
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for word in ("hello", " from", f" {fake.name}"):
                        self.wfile.write(f"data: {json.dumps({'delta': word})}\n\n".encode())
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                    return
                self._json(200, {"model": body.get("model"), "reply": f"hi from {fake.name}"})

        self._srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        self._srv.daemon_threads = True
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def pair():
    remote = FakeOllama("remote", ["hermes:70b"]).start()
    local = FakeOllama("local", ["qwen3.5:4b"]).start()
    cfg = RoutingConfig(
        backends=[
            Backend("remote", "hermes:70b", remote.url, label="Hermes (remote)"),
            Backend("local", "qwen3.5:4b", local.url, label="qwen (local)"),
        ],
        port=free_port(),
        probe_interval_s=3600,  # tests drive probes by hand
        probe_timeout_s=1,
        recover_after=2,
    )
    router = LlmRouter(cfg)
    switches: list[tuple] = []
    router.on_switch(lambda old, new: switches.append((old and old.name, new and new.name)))
    router.start()
    yield router, remote, local, switches
    router.stop()
    remote.stop()
    local.stop()


def chat(router: LlmRouter, stream: bool = False, model: str = "whatever"):
    req = urllib.request.Request(
        router.base_url + "/chat/completions",
        data=json.dumps({"model": model, "stream": stream, "messages": []}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.headers.get("X-Amy-Backend"), r.read()


def test_prefers_primary_and_rewrites_model(pair):
    router, remote, local, switches = pair
    backend, body = chat(router)
    assert backend == "remote"
    assert json.loads(body) == {"model": "hermes:70b", "reply": "hi from remote"}
    assert remote.seen[-1]["model"] == "hermes:70b" and local.seen == []
    assert switches == [(None, "remote")]
    st = router.status()
    assert st["active"] == "remote" and not st["fallback"] and st["backends"][0]["requests"] == 1


def test_fails_over_mid_request_when_primary_dies(pair):
    router, remote, local, switches = pair
    remote.stop()  # router still thinks remote is healthy
    backend, body = chat(router)
    assert backend == "local"
    assert json.loads(body)["model"] == "qwen3.5:4b"
    assert switches[-1] == ("remote", "local")
    st = router.status()
    assert st["fallback"] and not st["backends"][0]["healthy"]


def test_failover_from_dead_local_port_is_fast(pair):
    import time

    router, remote, local, switches = pair
    remote.stop()
    t0 = time.perf_counter()
    assert chat(router)[0] == "local"
    assert time.perf_counter() - t0 < 1.5  # Windows would otherwise wait ~2 s to refuse
    assert router.connect_timeout(Backend("lan", "m", "http://192.168.1.9:11434")) > 1


def test_switches_back_only_after_stable_recovery(pair):
    router, remote, local, switches = pair
    port = remote.port
    remote.stop()
    router.probe_all()
    assert router.active().name == "local"
    revived = FakeOllama("remote", ["hermes:70b"], port=port).start()
    try:
        router.probe_all()  # one good probe is not enough
        assert router.active().name == "local"
        router.probe_all()
        assert router.active().name == "remote"
        assert switches == [(None, "remote"), ("remote", "local"), ("local", "remote")]
    finally:
        revived.stop()


def test_model_missing_or_server_error_tries_next(pair):
    router, remote, local, _ = pair
    remote.fail_status = 404
    backend, _ = chat(router)
    assert backend == "local"
    remote.fail_status = None


def test_last_backend_error_is_passed_through(pair):
    router, remote, local, _ = pair
    remote.stop()
    local.fail_status = 500
    with pytest.raises(urllib.error.HTTPError) as e:
        chat(router)
    assert e.value.code == 500
    assert b"local failing" in e.value.read()


def test_all_down_returns_503(pair):
    router, remote, local, switches = pair
    remote.stop()
    local.stop()
    with pytest.raises(urllib.error.HTTPError) as e:
        chat(router)
    assert e.value.code == 503
    assert router.active() is None and switches[-1][1] is None


def test_streaming_passthrough(pair):
    router, *_ = pair
    backend, body = chat(router, stream=True)
    assert backend == "remote"
    assert body.decode().count("data:") == 4 and "[DONE]" in body.decode()


def test_probe_requires_model_to_be_installed(pair):
    router, remote, local, _ = pair
    remote.models = ["something-else"]
    router.probe_all()
    st = router.status()
    assert st["active"] == "local"
    assert "not installed" in st["backends"][0]["error"]


def test_pin_overrides_and_unpins(pair):
    router, *_ = pair
    router.pin("local")
    assert chat(router)[0] == "local"
    router.pin(None)
    assert router.active().name == "remote"
    with pytest.raises(KeyError):
        router.pin("nope")


def test_rewrite_model_leaves_other_bodies_alone():
    assert rewrite_model(b"", "m") == b""
    assert rewrite_model(b"not json", "m") == b"not json"
    assert rewrite_model(b'{"prompt": "x"}', "m") == b'{"prompt": "x"}'
    assert json.loads(rewrite_model(b'{"model": "a", "x": 1}', "m")) == {"model": "m", "x": 1}


def test_status_endpoint_on_router(pair):
    router, *_ = pair
    with urllib.request.urlopen(f"http://127.0.0.1:{router.port}/__amy/status", timeout=5) as r:
        assert json.loads(r.read())["active"] == "remote"


def test_switch_messages():
    a, b = Backend("a", "m1", "u", label="Hermes"), Backend("b", "m2", "u", label="qwen")
    assert switch_message(a, b, a) == "Lost Hermes; switching to qwen."
    assert switch_message(b, a, a) == "Hermes is back; switching to it."
    assert switch_message(a, None, a) == "I can't reach any language model right now."


# --- config + start-up ---------------------------------------------------------------------

def test_load_routing_config():
    cfg = load_routing({"llm_routing": {"backends": [
        {"name": "hermes", "model": "h", "ssh": {"host": "10.0.0.5", "user": "me", "local_port": 12000}},
        {"name": "local", "model": "q", "base_url": "http://127.0.0.1:11434/v1/"},
    ]}})
    assert cfg is not None
    assert cfg.backends[0].base_url == "http://127.0.0.1:12000"
    assert cfg.backends[1].base_url == "http://127.0.0.1:11434"
    assert load_routing({}) is None
    assert load_routing({"llm_routing": {"enabled": False, "backends": [{"model": "x"}]}}) is None
    skipped = load_routing({"llm_routing": {"backends": [
        {"name": "remote", "enabled": False, "model": "big", "ssh": {"host": "10.0.0.1"}},
        {"name": "local", "model": "small", "base_url": "http://127.0.0.1:11434"},
    ]}})
    assert skipped is not None and [b.name for b in skipped.backends] == ["local"]
    with pytest.raises(ValueError):
        load_routing({"llm_routing": {"backends": [{"name": "a", "model": "x"}, {"name": "a", "model": "y"}]}})


def test_start_routing_points_pyhive_at_router(monkeypatch):
    local = FakeOllama("local", ["qwen3.5:4b"]).start()
    monkeypatch.delenv("PYHIVE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("AMY_LLM_ROUTED", raising=False)
    router = start_routing({"llm_routing": {"port": free_port(), "backends": [
        {"name": "local", "model": "qwen3.5:4b", "base_url": local.url}]}})
    try:
        assert router is not None
        import os

        assert os.environ["PYHIVE_LLM_BASE_URL"] == router.base_url
        assert chat(router)[0] == "local"
    finally:
        if router:
            router.stop()
        local.stop()


def test_explicit_base_url_disables_routing(monkeypatch):
    monkeypatch.setenv("PYHIVE_LLM_BASE_URL", "http://elsewhere:1/v1")
    monkeypatch.delenv("AMY_LLM_ROUTED", raising=False)
    assert start_routing({"llm_routing": {"backends": [{"model": "x"}]}}) is None


# --- ssh tunnel ------------------------------------------------------------------------------

def test_tunnel_command_is_key_only_and_safe():
    t = SshTunnel(SshSpec(host="10.0.0.5", user="me", local_port=12000, identity_file="C:/k"), ssh_bin="ssh")
    cmd = t.command()
    assert cmd[:2] == ["ssh", "-N"]
    assert "127.0.0.1:12000:127.0.0.1:11434" in cmd
    assert "BatchMode=yes" in cmd and "ExitOnForwardFailure=yes" in cmd
    assert cmd[-1] == "me@10.0.0.5" and "-i" in cmd


def test_tunnel_reuses_an_open_port_without_spawning():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    try:
        t = SshTunnel(SshSpec(host="x", local_port=port), ssh_bin="definitely-not-ssh")
        assert t.ensure() is True and not t.alive()
    finally:
        srv.close()


def test_tunnel_failure_is_reported_and_backed_off():
    t = SshTunnel(SshSpec(host="x", local_port=free_port()), ssh_bin="definitely-not-ssh-binary")
    assert t.ensure(wait_s=0.5) is False
    assert "cannot start ssh" in t.last_error
    assert t.ensure(wait_s=0.5) is False  # within backoff: no new attempt


def test_router_marks_backend_down_when_tunnel_fails():
    local = FakeOllama("local", ["q"]).start()
    cfg = RoutingConfig(
        backends=[
            Backend("remote", "h", "http://127.0.0.1:1", ssh=SshSpec(host="x", local_port=free_port())),
            Backend("local", "q", local.url),
        ],
        port=free_port(), probe_interval_s=3600, probe_timeout_s=1,
    )
    router = LlmRouter(cfg, tunnels={"remote": SshTunnel(cfg.backends[0].ssh, ssh_bin="no-such-ssh")})
    try:
        router.start(serve=False)
        st = router.status()
        assert st["active"] == "local"
        assert "cannot start ssh" in st["backends"][0]["error"]
    finally:
        router.stop()
        local.stop()


def test_doctor_reports_each_backend(monkeypatch):
    from amy import doctor

    local = FakeOllama("local", ["qwen3.5:4b"]).start()
    try:
        checks = doctor._routing_checks({"amy": {"llm_routing": {"backends": [
            {"name": "hermes", "model": "h", "ssh": {"host": "x", "local_port": free_port()}},
            {"name": "local", "model": "qwen3.5:4b", "base_url": local.url},
        ]}}}, timeout=1)
        by = {c.name: c for c in checks}
        assert by["model 1: hermes"].status == doctor.WARN and "tunnel not open" in by["model 1: hermes"].detail
        assert by["model 2: local"].status == doctor.OK
        assert "model routing" not in by
    finally:
        local.stop()
