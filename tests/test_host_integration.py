"""AmbientHost end-to-end on a fake PyHive: start-up wiring, turns, guard, voice, busy."""

from __future__ import annotations

import json
import os
import threading

import pytest

from tests import fake_pyhive

HIVE_YAML = """
amy:
  home:
    city: Hyderabad
    country: India
    timezone: Asia/Kolkata
  guard:
    enabled: true
    mode: standard
    approval_timeout_s: 1
    voice_confirm: false
"""


@pytest.fixture
def world(tmp_path, monkeypatch):
    saved_env = dict(os.environ)
    cfg = tmp_path / "hive.yaml"
    cfg.write_text(HIVE_YAML, encoding="utf-8")
    monkeypatch.setenv("HIVE_CONFIG", str(cfg))
    monkeypatch.setenv("PYHIVE_HOME", str(tmp_path / "pyhive"))
    monkeypatch.setenv("AMY_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("AMY_TOKEN", "tok-secret-123456")
    w = fake_pyhive.install(monkeypatch)

    import amy.host.ambient as ambient

    class _Env:
        def refresh(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(ambient, "start_env_awareness", lambda *a, **kw: _Env())
    yield w

    import amy.tools.catalog as catalog
    from amy.guard import set_guard
    from amy.logs import set_redactor

    catalog._catalog = None
    set_guard(None)
    set_redactor(None)
    os.environ.clear()
    os.environ.update(saved_env)


@pytest.fixture
def host(world, tmp_path):
    from amy.host.ambient import AmbientHost
    from amy.host.events import EventBus

    logs: list[str] = []
    h = AmbientHost(bus=EventBus(), cwd=tmp_path, on_log=logs.append)
    h.logs = logs  # type: ignore[attr-defined]
    h.start()
    yield h
    h.stop()


def _audit(tmp_path):
    p = tmp_path / "audit.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_start_wires_everything(host, world):
    hive = host.hive
    assert host.started and host.voice_ok and host.wake_ok
    # guard wraps every registered tool and is published on the bus
    assert host.guard is not None
    reg = hive.registry
    names = {t.name for t in reg.list_tools()}
    assert "tools_catalog" in names and "hive_delegate" in names
    assert all(getattr(t.fn, "__amy_guarded__", False) for t in reg.list_tools())
    # product config reached the agent prompt and services
    assert "HOME REGION: Hyderabad, India (Asia/Kolkata)" in hive.system_prompt
    assert "PERSONA PRESET (" in hive.system_prompt
    assert hive.service("amy_home_label") == "Hyderabad, India"
    # headless voice: config hitl is forced off, early speak is published
    assert hive.assistant_config.hitl is False
    assert callable(hive.service("voice_early_speak"))
    assert hive.llm.warmed
    assert world.wake.kw["phrases"][0] == "hey chloe"
    assert host.bus.snapshot().state.value == "idle"
    assert host.bus.snapshot().tools


def test_text_turn_records_history_and_cards(host, world):
    def agent(shell, text):
        return "Sunny, 31° in Hyderabad. https://weather.example/today", {"tools_used": ["web_search"]}

    world.agent_script = agent
    reply = host.turn_text("weather?")
    assert "Sunny" in reply
    hist = host.bus.history()
    assert [m.role for m in hist[-2:]] == ["user", "assistant"]
    chips = {c.label for c in host.bus.snapshot().activity}
    assert "web_search" in chips


def test_guard_blocks_unapproved_high_risk_tool(host, world, tmp_path):
    def agent(shell, text):
        out = shell._bundle["registry"].call("os_power", action="shutdown", delay_seconds=0)
        return json.dumps(out), {}

    world.agent_script = agent
    reply = host.turn_text("shut the pc down")
    assert "blocked" in reply.lower() or "safety" in reply.lower()
    assert not [c for c in world.tool_calls if c[0] == "os_power"]
    outcomes = [r for r in _audit(tmp_path) if r.get("tool") == "os_power"]
    assert outcomes and outcomes[-1]["outcome"] in ("denied", "blocked", "timeout")
    assert outcomes[-1].get("turn")


def test_allowed_tool_runs_and_secret_is_redacted(host, world, tmp_path):
    def agent(shell, text):
        shell._bundle["registry"].call("os_volume", level=30)
        return "ok", {}

    world.agent_script = agent
    host.turn_text("volume 30 and my token is tok-secret-123456")
    assert ("os_volume", {"level": 30}) in world.tool_calls
    blob = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "tok-secret-123456" not in blob


def test_text_turn_while_busy_raises(host, world):
    from amy.errors import HostBusy

    gate, entered = threading.Event(), threading.Event()

    def agent(shell, text):
        entered.set()
        gate.wait(5)
        return "done", {}

    world.agent_script = agent
    t = threading.Thread(target=host.turn_text, args=("long job",))
    t.start()
    assert entered.wait(5)
    with pytest.raises(HostBusy):
        host.turn_text("second")
    gate.set()
    t.join(5)
    assert host.turn_text("third").startswith("done")


def test_wake_conversation_until_stop(host, world):
    world.heard.extend(["what time is it", "goodbye"])
    world.agent_script = lambda shell, text: (f"answer to {text}", {})
    world.wake.kw["on_wake"](type("Ev", (), {"transcript": "hey chloe turn on the lights"})())
    for _ in range(200):
        if world.wake.resumed:
            break
        threading.Event().wait(0.02)
    assert world.wake.paused == 1 and world.wake.resumed == 1
    assert world.turns == ["turn on the lights", "what time is it"]
    assert "Okay." in world.spoken
    assert host.bus.snapshot().state.value == "idle"


def test_persona_swap_keeps_later_prompt_blocks(host):
    hive = host.hive
    hive.system_prompt = hive.system_prompt + "\n\n[ENV] app=code"
    assert host.apply_persona("\n\nPERSONA PRESET (calm): be calm\n[/PERSONA]")
    sp = hive.system_prompt
    assert "PERSONA PRESET (calm)" in sp and sp.count("PERSONA PRESET (") == 1
    assert sp.endswith("[ENV] app=code")


def test_barge_in_stops_pending_approvals(host):
    host.barge_in()
    assert host.guard.broker.pending() == []
    assert host._vs.barge is True


def _wait(cond, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        if cond():
            return True
        threading.Event().wait(0.02)
    return False


def test_reminder_tools_are_guarded_and_timers_are_spoken(host, world):
    reg = host.hive.registry
    for name in ("reminder_add", "reminder_list", "reminder_cancel", "timer_start"):
        assert getattr(reg.get_tool(name).fn, "__amy_guarded__", False)
    host.reminders.timer("1 second", "tea")
    assert host.bus.snapshot().reminders[0].kind == "timer"
    assert _wait(lambda: "Your tea timer is done." in world.spoken)
    assert _wait(lambda: host.bus.snapshot().reminders == [])
    assert any(c.kind == "reminder" for c in host.bus.snapshot().activity)


def test_reminder_waits_for_conversation_to_finish(host, world):
    host._wake_busy.acquire()  # mid-conversation
    try:
        host.reminders.timer("1 second")
        threading.Event().wait(1.6)
        assert "Your timer is done." not in world.spoken
    finally:
        host._wake_busy.release()
    assert _wait(lambda: "Your timer is done." in world.spoken)


def test_model_routing_picks_backend_and_announces_failover(world, tmp_path, monkeypatch):
    from amy.host.ambient import AmbientHost
    from amy.host.events import EventBus
    from tests.test_llm_router import FakeOllama, free_port

    remote = FakeOllama("remote", ["hermes:70b"]).start()
    local = FakeOllama("local", ["qwen3.5:4b"]).start()
    cfg = tmp_path / "hive.yaml"
    cfg.write_text(
        HIVE_YAML
        + f"""
  llm_routing:
    port: {free_port()}
    probe_interval_s: 3600
    probe_timeout_s: 1
    backends:
      - name: remote
        label: Hermes (remote)
        model: hermes:70b
        base_url: {remote.url}
      - name: local
        label: qwen (local)
        model: qwen3.5:4b
        base_url: {local.url}
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("PYHIVE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("AMY_LLM_ROUTED", raising=False)
    h = AmbientHost(bus=EventBus(), cwd=tmp_path, on_log=lambda m: None)
    try:
        h.start()
        router = h.router
        assert router is not None
        assert os.environ["PYHIVE_LLM_BASE_URL"] == router.base_url
        assert world.shell.kw["model"] == "hermes:70b"
        llm = h.bus.snapshot().llm
        assert llm.active == "remote" and not llm.fallback

        remote.stop()
        router.probe_all()
        llm = h.bus.snapshot().llm
        assert llm.active == "local" and llm.fallback
        assert _wait(lambda: "Lost Hermes (remote); switching to qwen (local)." in world.spoken)
    finally:
        h.stop()
        remote.stop()
        local.stop()
