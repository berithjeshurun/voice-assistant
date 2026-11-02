"""Amy ambient host — thin product wrapper over rewritten Hive live voice."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from amy.branding import ASSISTANT_NAME, DEFAULT_WAKE_PHRASE
from amy.host.events import EventBus
from amy.protocol.messages import AssistantState


class AmbientHost:
    """Owns wake + conversation; STT/TTS/agent live in PyHive (rewritten live path)."""

    def __init__(
        self,
        *,
        bus: Optional[EventBus] = None,
        profile: str = "ambient",
        cwd: Optional[Path] = None,
        model: Optional[str] = None,
        wake_phrase: Optional[str] = None,
        force_voice: bool = False,
        max_steps: int = 14,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.bus = bus or EventBus()
        self.profile = profile
        self.cwd = Path(cwd or os.getcwd()).resolve()
        self.model = model
        self.wake_phrase = (
            wake_phrase
            or os.environ.get("AMY_WAKE_PHRASE")
            or DEFAULT_WAKE_PHRASE
        )
        self.force_voice = force_voice
        self.max_steps = max_steps
        self._log = on_log or self.bus.log

        self._shell: Any = None
        self._vs: Any = None
        self._daemon: Any = None
        self._idle_stop = threading.Event()
        self._idle_thread: Optional[threading.Thread] = None
        self._wake_busy = threading.Lock()
        self._started = False
        self._voice_ok = False
        self._wake_ok = False
        self._listen_max_s = 8.0
        self._convo_idle_s = 20.0
        self._pending_wake_transcript = ""
        self._speak_pulse_stop = threading.Event()
        self._speak_pulse_thread: Optional[threading.Thread] = None

    @property
    def voice_ok(self) -> bool:
        return self._voice_ok

    @property
    def wake_ok(self) -> bool:
        return self._wake_ok

    @property
    def shell(self) -> Any:
        return self._shell

    def start(self) -> "AmbientHost":
        if self._started:
            return self

        # Product defaults for the rewritten Hive live path
        os.environ.setdefault("PYHIVE_STT_BACKEND", "faster_whisper")
        os.environ.setdefault("PYHIVE_WHISPER_MODEL", "medium.en")
        os.environ.setdefault("PYHIVE_DISABLE_SKILL_INJECT", "1")
        os.environ.setdefault("PYHIVE_SILENCE_S", "0.55")
        os.environ.setdefault("PYHIVE_MIC_GAIN", "1.4")
        os.environ.setdefault("PYHIVE_ENERGY_THRESH", "0.018")
        os.environ.setdefault("AMY_WAKE_OWW", "0")

        from pyhive.core.autonomy import AutonomyEngine
        from pyhive.core.goals import GoalManager
        from pyhive.core.host import (
            AssistantShell,
            VoiceSession,
            voice_available,
        )
        from pyhive.core.host.live_audio import preload_stt
        from pyhive.core.hive_config import configured_model_spec
        from pyhive.core.idle import IdleSupervisor
        from pyhive.core.initiative import InitiativeEngine

        try:
            model_name = (
                os.environ.get("PYHIVE_WHISPER_MODEL")
                or os.environ.get("AMY_WHISPER_MODEL")
                or "medium.en"
            )
            self._log(
                f"stt loading {model_name} "
                "(first run may download ~1.5GB from HuggingFace — wait)"
            )
            self.bus.set_state(
                AssistantState.thinking,
                detail=f"stt:{model_name}",
            )
            tag = preload_stt()
            self._log(f"stt ready {tag}")
        except Exception as e:
            self._log(f"stt preload failed ({e}); falling back to small.en")
            try:
                os.environ["PYHIVE_WHISPER_MODEL"] = "small.en"
                os.environ["AMY_WHISPER_MODEL"] = "small.en"
                tag = preload_stt()
                self._log(f"stt ready {tag} (fallback)")
            except Exception as e2:
                self._log(f"stt preload: {e2}")

        model = self.model or configured_model_spec(
            explicit=None, profile=self.profile, prefer_profile=True
        )

        vprobe = voice_available()
        self._voice_ok = bool(vprobe.get("ok"))
        if not self._voice_ok:
            self._log(vprobe.get("message") or "voice unavailable")
            if not self.force_voice:
                self._log("hint: pass --force for text-only ambient")

        # Voice is always-on / headless — never block on stdin [y/N] confirms.
        # Web search etc. must auto-run; HITL prompts were denying tools on EOF
        # and the model then wandered into local read_file nonsense.
        os.environ.setdefault("PYHIVE_APPROVE", "1")
        os.environ["PYHIVE_HITL"] = "0"

        shell = AssistantShell(
            cwd=self.cwd,
            profile=self.profile,
            mode="ask",
            model=model,
            max_steps=self.max_steps,
            hitl=False,
        ).start()
        self._shell = shell

        # Product tool surface: OS / Bambu / slicer for the agent; keep STT/TTS host tools.
        try:
            from amy.tools import setup_amy_tool_surface
            from amy.tools.bambu import apply_config as apply_bambu_cfg
            from amy.tools.slicer import apply_config as apply_slicer_cfg

            hcfg_early = getattr(shell, "_hcfg", None)
            apply_bambu_cfg(hcfg_early)
            apply_slicer_cfg(hcfg_early)
            try:
                import yaml
                from pathlib import Path as _P

                cfg_path = os.environ.get("HIVE_CONFIG") or ""
                if cfg_path and _P(cfg_path).is_file():
                    raw_yaml = yaml.safe_load(_P(cfg_path).read_text(encoding="utf-8")) or {}
                    amy_cfg = raw_yaml.get("amy") or {}
                    apply_bambu_cfg(amy_cfg)
                    apply_slicer_cfg(amy_cfg)
                    home = amy_cfg.get("home") or {}
                    if isinstance(home, dict) and home:
                        label = str(
                            home.get("label")
                            or ", ".join(
                                str(home.get(k) or "").strip()
                                for k in ("city", "region", "country")
                                if str(home.get(k) or "").strip()
                            )
                        ).strip()
                        tz = str(home.get("timezone") or "").strip()
                        if label:
                            os.environ["AMY_HOME_LABEL"] = label
                            if tz:
                                os.environ["AMY_HOME_TZ"] = tz
                            city = str(home.get("city") or "").strip()
                            if city:
                                os.environ["AMY_HOME_CITY"] = city
                            if shell._agent is not None:
                                extra = (
                                    f"\n\nHOME REGION: {label}"
                                    + (f" ({tz})" if tz else "")
                                    + ". For weather / local asks without a city, "
                                    "use THIS region — never invent Delhi or another city. "
                                    "Prefer one focused query like "
                                    f"'current weather {label} today'."
                                )
                                sp = getattr(shell._agent, "system_prompt", "") or ""
                                if "HOME REGION:" not in sp:
                                    shell._agent.system_prompt = sp + extra
                            try:
                                if shell._ctx is not None:
                                    shell._ctx.services["amy_home"] = dict(home)
                                    shell._ctx.services["amy_home_label"] = label
                            except Exception:
                                pass
                            self.bus.note_activity(
                                label.split(",")[0].strip() or "home",
                                kind="weather",
                                detail=label,
                            )
                            self._log(f"home region={label}")
            except Exception:
                pass

            reg = (shell._bundle or {}).get("registry")
            if reg is not None:
                info = setup_amy_tool_surface(reg, config=hcfg_early)
                # Phase 3: Queen-only hive_delegate (Scout / Ops) after prune
                try:
                    from amy.hive import register_hive_delegate_tools
                    from amy.tools import prune_registry_to_allowlist, AMY_TOOL_ALLOWLIST
                    from amy.apps.registry_hook import merge_allowlist_keep

                    def _hive_activity(agent_id: str, detail: str) -> None:
                        self.bus.note_activity(
                            f"hive:{agent_id}",
                            kind="agent",
                            detail=detail,
                        )

                    hive_tools = register_hive_delegate_tools(
                        reg,
                        shell=shell,
                        bus=self.bus,
                        on_log=self._log,
                        on_activity=_hive_activity,
                    )
                    allow = merge_allowlist_keep(
                        list(AMY_TOOL_ALLOWLIST), config=hcfg_early
                    )
                    prune_registry_to_allowlist(reg, allowlist=allow)
                    # Re-register after prune so hive_delegate survives
                    hive_tools = register_hive_delegate_tools(
                        reg,
                        shell=shell,
                        bus=self.bus,
                        on_log=self._log,
                        on_activity=_hive_activity,
                    )
                    info["hive"] = hive_tools
                    self._log(f"hive tools={hive_tools}")
                except Exception as e:
                    self._log(f"hive register: {e}")
                kept = list(info.get("kept") or [])
                try:
                    kept = sorted(
                        {
                            getattr(t, "name", "")
                            for t in reg.list_tools()
                            if getattr(t, "name", "")
                        }
                    )
                    info["kept"] = kept
                except Exception:
                    pass
                self._log(
                    f"tools amy={info.get('amy')} apps={info.get('apps')} "
                    f"hive={info.get('hive')} voice={info.get('voice')} kept={kept}"
                )
                try:
                    from amy.apps.registry_hook import merge_allowlist_keep
                    from amy.tools import AMY_TOOL_ALLOWLIST

                    tool_names = merge_allowlist_keep(
                        list(AMY_TOOL_ALLOWLIST), config=hcfg_early
                    )
                    self.bus.set_tools(tool_names)
                    self.bus.note_activity(
                        "ready",
                        kind="status",
                        detail=f"{len(tool_names)} tools",
                    )
                except Exception:
                    if kept:
                        self.bus.set_tools(kept)
        except Exception as e:
            self._log(f"tools restrict: {e}")

        hcfg = getattr(shell, "_hcfg", None)
        asst = getattr(hcfg, "assistant", None) if hcfg is not None else None
        # Config may still say hitl:true — force voice product off
        if asst is not None and getattr(asst, "hitl", False):
            try:
                asst.hitl = False
            except Exception:
                pass
        amb = getattr(asst, "ambient", None) if asst is not None else None

        wake_phrase = str(
            self.wake_phrase
            or (getattr(amb, "wake_phrase", None) if amb else None)
            or DEFAULT_WAKE_PHRASE
        )
        self.wake_phrase = wake_phrase
        cooldown = int((getattr(amb, "cooldown_ms", None) if amb else None) or 800)
        idle_interval = float(
            (getattr(amb, "idle_interval_s", None) if amb else None) or 5
        )
        allow_act = bool(getattr(amb, "allow_act", False) if amb else False)
        screen_act = bool(getattr(amb, "screen_act", False) if amb else False)
        listen_seconds = float(
            (getattr(amb, "listen_seconds", None) if amb else None) or 8
        )
        self._listen_max_s = max(4.0, listen_seconds)
        progressive = bool(getattr(asst, "progressive_ack", True)) if asst else True
        ack_ms = int(getattr(asst, "ack_timeout_ms", 400) or 400) if asst else 400

        def _before_agent(_text: str, ack_text: str) -> None:
            if shell._ctx is None:
                shell.start()
            assert shell._ctx is not None
            shell._ctx.services["voice_ack_done"] = True
            shell._ctx.services["voice_ack_text"] = ack_text or ""
            self.bus.set_state(AssistantState.thinking, detail="ack")
            if (ack_text or "").strip():
                self.bus.set_caption(ack_text.strip(), role="ack")
            if (_text or "").strip():
                # Show what the user asked while we work
                self.bus.set_caption(_text.strip()[:220], role="user")
                if ack_text:
                    self.bus.set_caption(ack_text.strip(), role="ack")

        def _runner(text: str):
            from amy.host.hud_cards import cards_from_turn
            from pyhive.core.host.dual_reply import DualReply, parse_dual_reply

            self.bus.set_state(AssistantState.thinking, detail="agent")
            self.bus.clear_cards()
            self.bus.note_activity("working", kind="status", detail=(text or "")[:80])

            # Amy app voice shortcuts (SmartPanels login/open) — before agent.
            try:
                from amy.apps.voice_hooks import try_app_voice_shortcut

                app_hit = try_app_voice_shortcut(text, config=hcfg)
                if app_hit is not None:
                    speak = (app_hit.speak or app_hit.text or "").strip()
                    if speak:
                        self.bus.set_caption(speak[:420], role="speak")
                        self.bus.note_activity(
                            "SmartPanel",
                            kind="capability",
                            detail=speak[:80],
                        )
                    return app_hit
            except Exception as e:
                self._log(f"app voice hook: {e}")

            turn = shell.turn(text)
            meta = turn.meta or {}
            reply_text = (turn.assistant or "").strip()
            cards = cards_from_turn(reply_text, meta=meta)
            if cards:
                self.bus.set_cards(cards)
                weatherish = any(
                    "weather" in ((c.title or "") + (c.snippet or "")).lower()
                    or "°" in ((c.title or "") + (c.snippet or ""))
                    for c in cards
                )
                if weatherish:
                    self.bus.note_activity(
                        cards[0].title[:48] or "weather",
                        kind="weather",
                        detail=(cards[0].snippet or "")[:80],
                    )
                else:
                    self.bus.note_activity(
                        f"{len(cards)} results",
                        kind="info",
                        detail=(cards[0].title or "")[:80],
                    )
            for raw_tool in (
                meta.get("tools_used")
                or meta.get("last_tools")
                or meta.get("tool_calls")
                or []
            ):
                name = ""
                detail = ""
                if isinstance(raw_tool, str):
                    name = raw_tool
                elif isinstance(raw_tool, dict):
                    name = str(
                        raw_tool.get("name")
                        or raw_tool.get("tool")
                        or raw_tool.get("fn")
                        or ""
                    )
                    detail = str(raw_tool.get("summary") or raw_tool.get("status") or "")
                if name:
                    self.bus.note_tool(name, detail)
            if meta.get("dual_parsed") and (turn.speak or "").strip():
                speak = (turn.speak or "").strip()
                if speak:
                    self.bus.set_caption(speak, role="speak")
                return DualReply(
                    text=turn.assistant or "",
                    speak=turn.speak or "",
                    parsed=True,
                )
            dual = parse_dual_reply(meta.get("raw_reply") or turn.assistant or "")
            if (dual.speak or dual.text or "").strip():
                self.bus.set_caption(
                    (dual.speak or dual.text or "").strip()[:420], role="speak"
                )
            return dual

        def _voice_event(ev) -> None:
            et = getattr(ev, "type", "") or ""
            st = getattr(getattr(ev, "state", None), "value", "") or ""
            full = (getattr(ev, "text", "") or "").strip()
            text = full[:80]
            meta = getattr(ev, "meta", None) or {}
            et_l = str(et).lower()
            st_l = str(st).lower()
            if et_l == "latency":
                ttfw = meta.get("ttfw_ms")
                ack_ms = meta.get("ack_ms")
                agent_ms = meta.get("agent_ms")
                tts_ms = meta.get("tts_ms")
                kind = meta.get("first_audio_kind") or ""
                self._log(
                    f"latency ttfw_ms={ttfw} ack_ms={ack_ms} "
                    f"agent_ms={agent_ms} tts_ms={tts_ms} first={kind}"
                )
                return
            self._log(f"voice {et} state={st} {text}")
            if et_l in ("ack",) or "ack" == et_l:
                if full:
                    self.bus.set_caption(full[:420], role="ack")
                self.bus.set_state(AssistantState.thinking, detail="ack")
                return
            if et_l in ("reply",):
                if full:
                    self.bus.set_caption(full[:420], role="speak")
                return
            if et_l in ("transcript",) and full and full not in ("(listening)", "…", "..."):
                self.bus.set_caption(full[:420], role="user")
                self.bus.set_state(AssistantState.listening, detail="transcript", audio_level=0.25)
                return
            if et_l in ("partial",) and full and full not in ("(listening)", "…", "..."):
                self.bus.set_caption(full[:420], role="user")
                return
            if "speaking" in et_l or "speaking" in st_l:
                if full:
                    self.bus.set_caption(full[:420], role="speak")
                self.bus.set_state(AssistantState.speaking, detail="tts", audio_level=0.55)
                self._start_speak_pulse(full or text)
                return
            if et_l in ("spoken", "speak_error") or "spoken" in et_l:
                self._stop_speak_pulse()
                self.bus.set_state(AssistantState.idle, detail=et_l, audio_level=0.0)
                return
            mapping = {
                "listening": AssistantState.listening,
                "thinking": AssistantState.thinking,
                "idle": AssistantState.idle,
            }
            for key, mapped in mapping.items():
                if key in st_l or key in et_l:
                    if mapped != AssistantState.speaking:
                        self._stop_speak_pulse()
                    self.bus.set_state(
                        mapped,
                        audio_level=0.0 if mapped != AssistantState.listening else 0.2,
                    )
                    break

        _svc_amb = (shell._bundle or {}).get("services") or {}
        vs = VoiceSession(
            agent_runner=_runner,
            registry=(shell._bundle or {}).get("registry"),
            enabled=self._voice_ok or self.force_voice,
            on_event=_voice_event,
            progressive_ack=progressive,
            ack_timeout_ms=ack_ms,
            speak_strip_markdown=(
                bool(getattr(asst, "speak_strip_markdown", True)) if asst else True
            ),
            speak_max_chars=int(getattr(asst, "speak_max_chars", 420) or 420)
            if asst
            else 420,
            speak_max_sentences=int(getattr(asst, "speak_max_sentences", 4) or 4)
            if asst
            else 4,
            ack_llm=(
                (
                    getattr(getattr(shell._agent, "llm", None), "_pyhive_llm", None)
                    or getattr(shell._agent, "llm", None)
                )
                if shell._agent
                else None
            ),
            memory=(shell._bundle or {}).get("memory"),
            emitter=((shell._ctx.services or {}).get("emitter") if shell._ctx else None),
            before_agent=_before_agent,
            speaker_registry=_svc_amb.get("speaker_registry"),
            persona_engine=_svc_amb.get("persona_engine"),
            require_persona_voice=False,
            require_admin_voice=False,
            require_persona_face=False,
            require_persona_palm=False,
        )
        self._vs = vs

        # Early-speak: first streamed sentence → TTS while agent continues
        def _early_speak(sentence: str) -> None:
            line = (sentence or "").strip()
            if not line or vs is None:
                return
            try:
                vs.mark_early_spoke(line)
                self.bus.set_caption(line[:420], role="speak")
                self.bus.set_state(
                    AssistantState.speaking, detail="early", audio_level=0.5
                )
                self._start_speak_pulse(line)
                vs.speak(line, playback="ffplay")
            except Exception as e:
                self._log(f"early_speak: {e}")

        if shell._ctx is not None:
            shell._ctx.services["voice_early_speak"] = _early_speak
        try:
            (shell._bundle.setdefault("services", {}))[
                "voice_early_speak"
            ] = _early_speak
        except Exception:
            pass

        # Warm LLM weights + Piper so first real turn is not cold-load
        try:
            llm = None
            if shell._agent is not None:
                llm = (
                    getattr(getattr(shell._agent, "llm", None), "_pyhive_llm", None)
                    or getattr(shell._agent, "llm", None)
                )
            if llm is not None and hasattr(llm, "warmup"):
                self._log("warmup llm…")
                llm.warmup(prompt="ok")
                self._log("warmup llm ok")
        except Exception as e:
            self._log(f"warmup llm: {e}")
        try:
            if self._voice_ok or self.force_voice:
                self._log("warmup tts…")
                vs.speak("Ready.", playback="none")
                self._log("warmup tts ok")
        except Exception as e:
            self._log(f"warmup tts: {e}")

        goals = GoalManager()
        auto = AutonomyEngine(
            registry=(shell._bundle or {}).get("registry"),
            goals=goals,
        )

        def _idle_thread() -> None:
            from pyhive.core.idle.sensors import (
                CalendarSoonSensor,
                FileDropSensor,
                GoalWatchSensor,
                HaStateSensor,
                HeartbeatSensor,
                ScreenSensor,
            )
            from pyhive.core.presence import PresenceEngine

            screen_every = (
                float(getattr(amb, "screen_every_s", None) or 90.0) if amb else 90.0
            )
            sensors = [
                HeartbeatSensor(),
                GoalWatchSensor(goals=goals),
                FileDropSensor(),
                CalendarSoonSensor(within_minutes=30),
                HaStateSensor(),
                ScreenSensor(every_s=screen_every, ocr=True),
            ]
            pe = (shell._bundle.get("services") or {}).get("presence_engine")
            if pe is None:
                pe = PresenceEngine(
                    agent_memory=(shell._bundle or {}).get("memory"),
                    user_id="default",
                )
                (shell._bundle.setdefault("services", {}))["presence_engine"] = pe
            if shell._ctx is not None:
                shell._ctx.services["presence_engine"] = pe
                # Idle may use presence; do NOT inject psyche blocks into voice turns
                shell._ctx.services["presence_enrichment"] = False
            initiative = InitiativeEngine(allow_act=bool(allow_act or screen_act))
            sup = IdleSupervisor(
                goals=goals,
                sensors=sensors,
                initiative=initiative,
                autonomy=auto,
                presence=pe,
                interval_s=idle_interval,
                allow_act=bool(allow_act or screen_act),
                act_runner=None,
                on_notify=lambda ev: self._log(
                    f"idle {getattr(ev.action, 'value', ev.action)} {ev.kind}"
                ),
            )
            while not self._idle_stop.is_set():
                try:
                    sup.cycle()
                except Exception as e:
                    self._log(f"idle error: {e}")
                self._idle_stop.wait(idle_interval)

        self._idle_thread = threading.Thread(
            target=_idle_thread, name="amy-ambient-idle", daemon=True
        )
        self._idle_thread.start()

        from amy.host.amy_wake import AmyWakeDaemon

        wake_phrases = [
            wake_phrase.lower().strip(),
            "hey chloe",
            "hi chloe",
            "okay chloe",
            "ok chloe",
            "chloe",
        ]
        seen: set[str] = set()
        wake_phrases = [p for p in wake_phrases if p and not (p in seen or seen.add(p))]

        def _on_wake(ev) -> None:
            if not self._wake_busy.acquire(blocking=False):
                return
            self._pending_wake_transcript = getattr(ev, "transcript", "") or ""
            threading.Thread(
                target=self._handle_wake,
                name="amy-convo",
                daemon=True,
            ).start()

        daemon = AmyWakeDaemon(
            phrases=wake_phrases,
            on_wake=_on_wake,
            on_event=lambda msg: self._log(msg),
            cooldown_ms=max(cooldown, 1600),
            gain=float(
                os.environ.get("AMY_MIC_GAIN")
                or os.environ.get("PYHIVE_MIC_GAIN")
                or 1.4
            ),
            enabled=True,
        )
        started = daemon.start()
        self._daemon = daemon
        self._wake_ok = bool(started.get("ok"))
        if self._wake_ok:
            self._log("WAKE: whisper hey chloe / chloe | Ctrl+Shift+A — then keep talking")
        else:
            self._log(started.get("message") or "wake failed")

        stt_tag = (
            f"{os.environ.get('PYHIVE_STT_BACKEND', 'faster_whisper')}:"
            f"{os.environ.get('PYHIVE_WHISPER_MODEL', 'medium.en')}"
        )
        self._log(
            f"ambient ready name={ASSISTANT_NAME} profile={self.profile} "
            f"model={model} stt={stt_tag} voice_ok={self._voice_ok}"
        )
        self.bus.set_state(AssistantState.idle, detail="ready")
        self._started = True
        return self

    def _handle_wake(self) -> None:
        """Pause wake → Hive conversation_after_wake (live STT) → resume."""
        from amy.host.amy_wake import AmyWakeDaemon

        try:
            self.bus.set_state(AssistantState.listening, detail="convo")
            self._log(f"wake → hive conversation name={ASSISTANT_NAME}")
            d = self._daemon
            if isinstance(d, AmyWakeDaemon):
                d.pause()
            vs = self._vs
            if vs is None:
                self.bus.set_state(AssistantState.error, detail="no voice session")
                return

            pending = (self._pending_wake_transcript or "").strip()
            self._pending_wake_transcript = ""
            first = ""
            if pending:
                from amy.host.amy_wake import match_wake_phrase, strip_wake_from_transcript

                if match_wake_phrase(
                    pending,
                    ["hey chloe", "hi chloe", "okay chloe", "ok chloe", "chloe"],
                ):
                    first = strip_wake_from_transcript(pending)
                self.bus.set_caption(pending[:420], role="user")

            if first:
                # Already have the ask from wake transcript — one turn, then live loop
                self.bus.set_state(AssistantState.thinking, detail=first[:80])
                self.bus.set_caption(first[:420], role="user")
                ans = vs.turn_from_text(first)
                self._log(f"amy> {ans}")
                self.bus.record_turn(first, str(ans or ""))
                last = ans
                idle_deadline = time.time() + self._convo_idle_s
                for _ in range(10):
                    # Interrupt while Amy was speaking → take the new command now.
                    if getattr(vs, "consume_barge", None) and vs.consume_barge():
                        try:
                            vs._cancel.clear()
                        except Exception:
                            pass
                        self.bus.set_state(
                            AssistantState.listening, detail="barge"
                        )
                        text = vs.listen_live(max_seconds=self._listen_max_s)
                        if not text:
                            continue
                        idle_deadline = time.time() + self._convo_idle_s
                        if text.lower().strip() in {
                            "bye",
                            "goodbye",
                            "stop",
                            "amy stop",
                        }:
                            break
                        self.bus.set_caption(text[:420], role="user")
                        last = vs.turn_from_text(text) or last
                        self._log(f"amy> {last}")
                        self.bus.record_turn(text, str(last or ""))
                        continue
                    remain = max(1.5, idle_deadline - time.time())
                    text = vs.listen_live(
                        max_seconds=min(self._listen_max_s, remain)
                    )
                    if not text:
                        if time.time() >= idle_deadline:
                            break
                        continue
                    if text.lower().strip() in {
                        "bye",
                        "goodbye",
                        "stop",
                        "amy stop",
                    }:
                        try:
                            vs.speak("Okay.", playback="ffplay")
                        except Exception:
                            pass
                        break
                    idle_deadline = time.time() + self._convo_idle_s
                    self.bus.set_caption(text[:420], role="user")
                    last = vs.turn_from_text(text) or last
                    self._log(f"amy> {last}")
                    self.bus.record_turn(text, str(last or ""))
            else:
                last = vs.conversation_after_wake(
                    listen_seconds=self._listen_max_s,
                    idle_seconds=self._convo_idle_s,
                    max_turns=12,
                )
                if last:
                    self.bus.record_turn("(voice)", str(last))
                    self._log(f"amy> {last}")
        except Exception as e:
            self._log(f"wake_turn: {e}")
            self.bus.set_state(AssistantState.error, detail=str(e))
        finally:
            self._stop_speak_pulse()
            try:
                d = self._daemon
                if isinstance(d, AmyWakeDaemon):
                    d.resume()
            except Exception as e:
                self._log(f"wake resume: {e}")
            self.bus.set_state(AssistantState.idle, detail="convo_end", audio_level=0.0)
            try:
                self._wake_busy.release()
            except Exception:
                pass

    def _start_speak_pulse(self, text: str = "") -> None:
        """Drive orb audio_level while TTS plays (particles surge with speech)."""
        self._stop_speak_pulse()
        words = max(1, len((text or "").split()))
        # ~140 wpm ≈ 2.3 wps; clamp so short acks still pulse briefly
        duration = min(45.0, max(0.9, words / 2.3))
        self._speak_pulse_stop = threading.Event()
        stop = self._speak_pulse_stop

        def _run() -> None:
            t0 = time.time()
            import math

            while not stop.is_set():
                elapsed = time.time() - t0
                if elapsed >= duration:
                    break
                # Spectrum-ish envelope: bass / mid / treble mix → single level for HUD
                progress = elapsed / duration
                bass = 0.55 + 0.45 * math.sin(elapsed * 7.2)
                mid = 0.4 + 0.6 * abs(math.sin(elapsed * 14.8 + 0.7))
                treble = 0.3 + 0.7 * abs(math.sin(elapsed * 26.5 + 1.9))
                base = 0.25 * bass + 0.4 * mid + 0.35 * treble
                if progress < 0.08:
                    base *= progress / 0.08
                elif progress > 0.85:
                    base *= max(0.0, (1.0 - progress) / 0.15)
                level = max(0.14, min(1.0, base))
                try:
                    self.bus.set_state(
                        AssistantState.speaking,
                        detail="tts_pulse",
                        audio_level=level,
                    )
                except Exception:
                    break
                stop.wait(0.05)
            if not stop.is_set():
                try:
                    self.bus.set_state(
                        AssistantState.speaking,
                        detail="tts_tail",
                        audio_level=0.15,
                    )
                except Exception:
                    pass

        self._speak_pulse_thread = threading.Thread(
            target=_run, name="amy-speak-pulse", daemon=True
        )
        self._speak_pulse_thread.start()

    def _stop_speak_pulse(self) -> None:
        self._speak_pulse_stop.set()
        t = self._speak_pulse_thread
        self._speak_pulse_thread = None
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=0.4)
        try:
            self.bus.set_state(self.bus.snapshot().state, audio_level=0.0)
        except Exception:
            pass

    def turn_text(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        if not self._started or self._vs is None:
            raise RuntimeError("AmbientHost not started")
        self.bus.set_state(AssistantState.thinking, detail="text")
        self.bus.set_caption(text[:420], role="user")
        self.bus.clear_cards()
        try:
            ans = self._vs.turn_from_text(text)
            reply = str(ans or "")
            from amy.host.hud_cards import cards_from_turn

            cards = cards_from_turn(reply)
            if cards:
                self.bus.set_cards(cards)
            self.bus.record_turn(text, reply)
            return reply
        except Exception as e:
            self.bus.set_state(AssistantState.error, detail=str(e))
            raise

    def trigger_wake(self, reason: str = "api") -> None:
        if not self._started or self._daemon is None:
            self._log(f"wake ignored (host still starting): {reason}")
            return
        self._daemon.trigger_wake(reason=reason)

    def barge_in(self) -> None:
        self._stop_speak_pulse()
        if self._vs is not None:
            self._vs.barge_in()

    def set_ui_state(self, state: AssistantState, *, detail: str = "") -> None:
        if state != AssistantState.speaking:
            self._stop_speak_pulse()
        self.bus.set_state(state, detail=detail or "ui")

    def stop(self) -> None:
        self._idle_stop.set()
        self._stop_speak_pulse()
        try:
            if self._daemon is not None:
                self._daemon.stop()
        except Exception:
            pass
        self._started = False
        self.bus.set_state(AssistantState.idle, detail="stopped")
        self._log("stopped")

    def run_forever(self, *, console: bool = False) -> int:
        self.start()
        if not console:
            self._log("headless — Ctrl+C to stop")
            stop = threading.Event()

            def _sig(*_a: object) -> None:
                stop.set()

            import signal

            signal.signal(signal.SIGINT, _sig)
            try:
                signal.signal(signal.SIGTERM, _sig)
            except Exception:
                pass
            try:
                while not stop.wait(0.5):
                    pass
            finally:
                self.stop()
            return 0

        self._log("console — /wake /stop /exit")
        try:
            while True:
                try:
                    line = input("you> ").strip()
                except (EOFError, KeyboardInterrupt):
                    self._log("")
                    break
                if not line or line in {"/exit", "/quit", ":q"}:
                    break
                if line in {"/wake"}:
                    self.trigger_wake(reason="console")
                    continue
                if line in {"/stop", "/barge"}:
                    self.barge_in()
                    continue
                ans = self.turn_text(line)
                print(f"amy> {ans}", flush=True)
        finally:
            self.stop()
        return 0
