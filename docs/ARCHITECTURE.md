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

**Safety guard:** after tool setup, `AmbientHost` wraps every registered tool with `amy/guard`
(re-applied after `tools_activate`). Each call is allowed, held for human approval (voice or HUD),
or blocked, then redacted and written to `logs/audit.jsonl`. If wrapping fails, tools with side
effects are removed (fail closed). Pending approvals and guard status ride the normal snapshot
(`approvals`, `guard`).

## Host modules

`amy/host/ambient.py` only orchestrates start-up and wake handling; the work lives in:

| Module | Job |
|--------|-----|
| `tool_surface.py` | product config, home region prompt, tool setup, `install_guard` |
| `turns.py` | `TurnRunner` — one lock for voice and text turns, turn ids, guard begin/end, app shortcuts |
| `conversation.py` | multi-turn voice loop after a wake, stop phrases |
| `voice_setup.py` | voice session, persona/TTS settings, early speak, warm-up |
| `voice_events.py` | maps voice-session events to bus state |
| `speak_pulse.py` | synthetic orb level while TTS plays |
| `background.py` | env awareness, metric alerts, idle supervisor |
| `events.py` | `EventBus` — snapshot state, watchers, history store |
| `browsers.py` | Chromium discovery and "wait for HUD" shared by orb / captions / HUD launchers |

`amy/hive_adapter.py` wraps every pyhive private attribute the product relies on (`_bundle`,
`_ctx`, `_agent`, system prompt blocks). A pyhive upgrade that renames internals breaks one file.

## Turns

All turns (wake word, HUD text, WebSocket) go through `TurnRunner`. It holds a single lock, so
a second request gets `HostBusy` → HTTP 409 / `turn_result {error: "busy"}` instead of racing the
agent. Each turn gets an id (`amy.logs.turn_context`) that appears on every log and audit line.
HTTP turns run in a bounded thread pool with `AMY_TURN_TIMEOUT_S`.

## Live updates

`EventBus` keeps the current `AssistantSnapshot`. WebSocket clients register a watcher (an
`asyncio.Event` set thread-safely from any producer); on change the server diffs the snapshot
and sends only the changed top-level keys:

```text
→ {"type":"snapshot","data":{…full…},"role":"user"}
→ {"type":"patch","data":{"state":"thinking"}}          ≤ 20/s per client, coalesced
← {"type":"turn","text":"…"}  → {"type":"turn_result","ok":true,"reply":"…"}
→ {"type":"error","error":"requires admin role","command":"approve"}
```

The web client (`openAmySocket` in `apps/web/src/api.ts`) merges patches, reconnects with
exponential backoff and stops on close code 4401 (auth). Snapshots are only built when someone
is listening, so a headless host does no serialisation work.

## Auth

`amy/server/auth.py`: the admin token (constant-time compare) or a device token (SHA-256 at
rest) yields a `Principal(name, role)`. `POST /api/session` turns it into an HMAC-signed cookie;
host sessions are bound to a fingerprint of the current admin token, device sessions re-read the
device's role on every request, so rotation and revocation take effect immediately. Cookie
WebSockets must come from the same origin. Failed attempts are throttled per IP. The HUD is
served with a CSP that whitelists the inline bootstrap scripts by hash.

## Storage

Chat history is a SQLite (WAL) table behind the `HistoryStore` protocol (`append` / `recent` /
`search`), pruned to 20 000 rows. The bus loads the last turns on start, so the HUD shows
history across restarts. Swap the store for another backend by implementing the protocol.
