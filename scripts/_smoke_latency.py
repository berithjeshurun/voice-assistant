"""Smoke: early-speak peek + VoiceSession latency emit (no mic).

Usage (from G:\\Amy with Hive env):
  python scripts/_smoke_latency.py
"""

from __future__ import annotations

import sys
import time


def _check_peek() -> None:
    from pyhive.core.host.dual_reply import peek_early_speak

    partial = '{"text": "x", "speak": "It is three'
    assert peek_early_speak(partial) is None, "incomplete speak should wait"
    fullish = '{"text": "It is three PM.", "speak": "It is three PM."}'
    got = peek_early_speak(fullish)
    assert got and "three" in got.lower(), got
    mid = '{"text": "x", "speak": "It is three PM. More later.'
    got2 = peek_early_speak(mid)
    assert got2 == "It is three PM.", got2
    tools = '{"tool_calls":[{"function":{"name":"web_search"}}]}'
    assert peek_early_speak(tools) is None
    plain = "Hello there. More detail follows."
    assert peek_early_speak(plain) == "Hello there."
    print("peek_early_speak ok")


def _check_latency_emit() -> None:
    from pyhive.core.host.voice_session import VoiceSession

    events = []

    def on_event(ev) -> None:
        events.append(ev)

    vs = VoiceSession(
        agent_runner=lambda _t: (
            time.sleep(0.02)
            or '{"text":"The time is noon.","speak":"It is noon."}'
        ),
        enabled=True,
        on_event=on_event,
        progressive_ack=False,
    )
    # Force speak path without hardware: patch speak to mark audio only
    def _fake_speak(text: str, *, playback: str = "ffplay"):
        vs._note_speak_call(kind="tts")
        vs._note_first_audio(kind="tts")
        vs._emit("spoken", (text or "")[:200], ok=True)
        return {"ok": True, "data": {"played": False, "playback": "none"}}

    vs.speak = _fake_speak  # type: ignore[method-assign]
    # Bypass shortcut/greeting classifiers for a stable agent path
    vs._try_pure_ack_reply = lambda _t: ""  # type: ignore[method-assign]
    vs._try_identity_reply = lambda _t: ""  # type: ignore[method-assign]
    vs._is_wake_only_transcript = lambda _t: False  # type: ignore[method-assign]
    vs._is_pure_greeting = lambda _t: False  # type: ignore[method-assign]
    vs._try_os_control_shortcut = lambda _t: ""  # type: ignore[method-assign]
    vs._try_youtube_shortcut = lambda _t: ""  # type: ignore[method-assign]
    vs._try_power_shortcut = lambda _t: ""  # type: ignore[method-assign]
    vs._try_weather_shortcut = lambda _t: ""  # type: ignore[method-assign]
    t0 = time.time()
    out = vs.turn_from_text("what time is it for latency smoke")
    assert out, out
    lat = [e for e in events if getattr(e, "type", "") == "latency"]
    assert lat, f"no latency event; types={[getattr(e,'type',None) for e in events]}"
    meta = lat[-1].meta or {}
    assert meta.get("ttfw_ms") is not None, meta
    assert meta.get("agent_ms") is not None and int(meta["agent_ms"]) >= 15, meta
    print(
        f"latency emit ok ttfw_ms={meta.get('ttfw_ms')} "
        f"agent_ms={meta.get('agent_ms')} elapsed_ms={int((time.time()-t0)*1000)}"
    )


def _check_strip_early() -> None:
    from pyhive.core.host.voice_session import VoiceSession

    vs = VoiceSession(enabled=False, progressive_ack=False)
    vs.early_spoke_text = "Hello there."
    rest = vs._strip_early_spoke_prefix("Hello there. More follows.")
    assert rest.lower().startswith("more"), rest
    print("strip_early_spoke ok")


def main() -> int:
    _check_peek()
    _check_strip_early()
    _check_latency_emit()
    print("smoke_latency PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"smoke_latency FAIL: {e}", file=sys.stderr)
        raise
