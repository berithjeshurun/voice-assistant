"""A minimal stand-in for the PyHive packages AmbientHost imports.

``install(monkeypatch)`` registers fake modules in ``sys.modules`` and returns a
``World`` object for scripting and inspecting the run. Every tool registered on the
fake registry is replaced by a recording stub, so no real OS action can ever run.
"""

from __future__ import annotations

import inspect
import sys
import types
from collections import deque
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Deque, Dict, List, Optional


@dataclass
class World:
    tool_calls: List[tuple] = field(default_factory=list)
    turns: List[str] = field(default_factory=list)
    spoken: List[str] = field(default_factory=list)
    heard: Deque[str] = field(default_factory=deque)
    # what the fake agent does on each turn: fn(shell, text) -> (assistant_text, meta)
    agent_script: Optional[Callable[[Any, str], tuple]] = None
    shell: Any = None
    voice: Any = None
    wake: Any = None


class FakeTool:
    def __init__(self, name: str, fn: Callable[..., Any]) -> None:
        self.name = name
        self.fn = fn


class FakeRegistry:
    def __init__(self, world: World) -> None:
        self.world = world
        self._tools: Dict[str, FakeTool] = {}

    def register(self, fn, name=None, description="", module="", overwrite=False):
        name = name or fn.__name__
        if name in self._tools and not overwrite:
            raise ValueError(f"{name} exists")
        self._tools[name] = FakeTool(name, self._stub(name, fn))

    def _stub(self, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        if getattr(fn, "__amy_guarded__", False) or getattr(fn, "_is_stub", False):
            return fn  # guard re-registering an already stubbed function
        world = self.world

        def stub(*args, **kwargs):
            world.tool_calls.append((name, kwargs))
            return {"ok": True, "tool": name}

        stub.__name__ = getattr(fn, "__name__", name)
        stub.__doc__ = fn.__doc__
        stub._is_stub = True  # type: ignore[attr-defined]
        try:
            stub.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            pass
        return stub

    def unregister(self, name):
        self._tools.pop(name, None)

    def list_tools(self):
        return list(self._tools.values())

    def get_tool(self, name):
        return self._tools[name]

    def call(self, tool_name, **kw):
        return self._tools[tool_name].fn(**kw)


@dataclass
class DualReply:
    text: str = ""
    speak: str = ""
    parsed: bool = False


def parse_dual_reply(raw: str) -> DualReply:
    return DualReply(text=raw or "", speak=raw or "", parsed=False)


class FakeLLM:
    def __init__(self) -> None:
        self.warmed = False

    def warmup(self, prompt: str = "") -> None:
        self.warmed = True


class AssistantShell:
    world: World  # set by install()

    def __init__(self, **kw: Any) -> None:
        self.kw = kw
        self._bundle = {"registry": FakeRegistry(self.world), "memory": None, "services": {}}
        self._agent = SimpleNamespace(system_prompt="BASE PROMPT", llm=FakeLLM(), model_spec="fake")
        self._ctx = None
        self._hcfg = SimpleNamespace(
            assistant=SimpleNamespace(
                hitl=True,
                progressive_ack=True,
                ack_timeout_ms=300,
                speak_strip_markdown=True,
                speak_max_chars=420,
                speak_max_sentences=4,
                ambient=SimpleNamespace(
                    wake_phrase="hey chloe",
                    listen_seconds=6,
                    cooldown_ms=800,
                    idle_interval_s=3600,
                    allow_act=False,
                    screen_act=False,
                ),
            )
        )
        self.world.shell = self

    def start(self) -> AssistantShell:
        if self._ctx is None:
            self._ctx = SimpleNamespace(services={"emitter": None})
        return self

    def turn(self, text: str) -> Any:
        self.world.turns.append(text)
        script = self.world.agent_script
        assistant, meta = script(self, text) if script else (f"echo: {text}", {})
        return SimpleNamespace(assistant=assistant, speak="", meta=meta)


class VoiceSession:
    world: World

    def __init__(self, **kw: Any) -> None:
        self.kw = kw
        self.runner = kw["agent_runner"]
        self.barge = False
        self._cancel = SimpleNamespace(clear=lambda: None)
        self.world.voice = self

    def turn_from_text(self, text: str) -> str:
        self.kw["before_agent"](text, "")
        out = self.runner(text)
        return getattr(out, "speak", None) or getattr(out, "text", None) or str(out)

    def speak(self, text: str, playback: str = "ffplay") -> None:
        self.world.spoken.append(text)

    def listen_live(self, max_seconds: float = 6.0) -> str:
        return self.world.heard.popleft() if self.world.heard else ""

    def conversation_after_wake(self, **kw: Any) -> str:
        text = self.listen_live()
        return self.turn_from_text(text) if text else ""

    def consume_barge(self) -> bool:
        b, self.barge = self.barge, False
        return b

    def barge_in(self) -> None:
        self.barge = True

    def mark_early_spoke(self, line: str) -> None:
        pass

    def _tts(self, text: str, *, playback: str = "ffplay") -> None:
        self.world.spoken.append(text)

    def _tts_backend(self) -> str:
        return "piper"

    def _call_tool(self, name: str, **kw: Any) -> None:
        self.world.spoken.append(kw.get("text", ""))


class FakeWakeDaemon:
    world: World

    def __init__(self, **kw: Any) -> None:
        self.kw = kw
        self.paused = 0
        self.resumed = 0
        self.stopped = False
        self.world.wake = self

    def start(self) -> dict:
        return {"ok": True}

    def pause(self) -> None:
        self.paused += 1

    def resume(self) -> None:
        self.resumed += 1

    def stop(self) -> None:
        self.stopped = True

    def trigger_wake(self, reason: str = "") -> None:
        self.kw["on_wake"](SimpleNamespace(transcript=""))


class _Noop:
    def __init__(self, *a: Any, **kw: Any) -> None:
        self.kw = kw

    def cycle(self) -> None:
        pass


def _module(name: str, **attrs: Any) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    return m


def install(monkeypatch: Any) -> World:
    world = World()
    for cls in (AssistantShell, VoiceSession, FakeWakeDaemon):
        monkeypatch.setattr(cls, "world", world, raising=False)

    sensors = {n: _Noop for n in (
        "CalendarSoonSensor", "FileDropSensor", "GoalWatchSensor",
        "HaStateSensor", "HeartbeatSensor", "ScreenSensor",
    )}
    mods = {
        "pyhive": _module("pyhive"),
        "pyhive.core": _module("pyhive.core"),
        "pyhive.core.host": _module(
            "pyhive.core.host",
            AssistantShell=AssistantShell,
            VoiceSession=VoiceSession,
            voice_available=lambda: {"ok": True},
        ),
        "pyhive.core.host.live_audio": _module("pyhive.core.host.live_audio", preload_stt=lambda: "fake-stt"),
        "pyhive.core.host.dual_reply": _module(
            "pyhive.core.host.dual_reply", DualReply=DualReply, parse_dual_reply=parse_dual_reply
        ),
        "pyhive.core.hive_config": _module(
            "pyhive.core.hive_config", configured_model_spec=lambda **kw: "fake-model"
        ),
        "pyhive.core.autonomy": _module("pyhive.core.autonomy", AutonomyEngine=_Noop),
        "pyhive.core.goals": _module("pyhive.core.goals", GoalManager=_Noop),
        "pyhive.core.idle": _module("pyhive.core.idle", IdleSupervisor=_Noop),
        "pyhive.core.idle.sensors": _module("pyhive.core.idle.sensors", **sensors),
        "pyhive.core.initiative": _module("pyhive.core.initiative", InitiativeEngine=_Noop),
        "pyhive.core.presence": _module("pyhive.core.presence", PresenceEngine=_Noop),
        "amy.host.amy_wake": _module(
            "amy.host.amy_wake",
            AmyWakeDaemon=FakeWakeDaemon,
            match_wake_phrase=lambda text, phrases: any(p in text.lower() for p in phrases),
            strip_wake_from_transcript=lambda text: text.lower().split("chloe", 1)[-1].strip(" ,."),
        ),
    }
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return world
