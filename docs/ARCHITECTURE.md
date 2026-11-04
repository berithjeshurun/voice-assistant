# Amy architecture

Amy is a **voice host + companion orb + on-demand HUD**, not a chat REPL.

```text
Wake (Whisper + fuzzy “chloe”) → live VAD → faster-whisper → AssistantShell → TTS
        (+ orb audio_level / caption overlay). Barge-in cancels playback.
        Continuous turns until bye / idle.
```

| Layer | Path |
|-------|------|
| Product host | `amy/` (AmbientHost, AmyServer, Hive specialists) |
| Config / identity | `config/`, `identity/`, `prompts/` |
| Web HUD | `apps/web` (build → `dist/`, served by host) |
| Desktop launcher | `apps/desktop` (Tauri tray — HUD on demand) |
| Orb | Crystalized Ball `/?view=orb` (always-on-top); Bevy opt-in `AMY_ORB=bevy` |
| Libraries | Hive packages via pip editable (not vendored) |
| Runtime | `$PYHIVE_HOME` |

**Entry:** `scripts/run.ps1` / `run.sh` → `python -m amy serve`.

**LAN:** `--lan` → phones open `http://<host>:8787/?token=…`.

**Default companions:** orb only. Captions window is opt-in (`AMY_CHAT_WINDOW=1`). Full HUD opens from the launcher or by double-clicking the orb.

**Clients are thin:** Tauri / browser talk HTTP+WebSocket; tools and memory stay in the Python host.
