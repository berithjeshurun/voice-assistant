# Amy architecture

Amy is a **voice host + LAN HUD**, not a chat REPL.

Hive voice was rewritten for live conversation (not fixed WAV dumps):

```text
Wake (Whisper + fuzzy “amy/any”) → live VAD → faster-whisper `medium.en` → AssistantShell → TTS (+ orb audio_level pulse). While TTS plays, a mic energy watcher can barge-in (kill ffplay, take a new command).
        ↕ continuous turns until bye / idle
```

| Layer | Path |
|-------|------|
| Product host | `G:\Amy\amy` (AmbientHost, AmyServer) |
| Config / identity | `G:\Amy\config`, `identity`, `prompts` |
| Web HUD | `G:\Amy\apps\web` |
| Desktop shell | `G:\Amy\apps\desktop` (Tauri) |
| Orb | Persistent companion — React Bits Crystalized Ball (`/?view=orb`); Bevy opt-in via `AMY_ORB=bevy` |
| Libraries | `H:\New_VLibs\v4` (pip editable — not vendored) |
| Runtime | `G:\HiveSTEAM` |

**Entry:** `scripts/run.ps1` / `run.sh` → `python -m amy serve` with `HIVE_CONFIG=…/config/hive.yaml`.

**Hive-server mode:** `--lan` binds for LAN; phones open `http://<host>:8787/?token=…`.

**Brand:** Amy everywhere. No Jarvis product naming.

**Clients are thin:** Tauri / Bevy / browser talk HTTP+WebSocket; tools and memory stay in the Python host.
