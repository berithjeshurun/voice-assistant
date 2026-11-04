# Amy

Always-on personal assistant — voice-first host with a LAN HUD and companion orb.

```text
G:\Amy\              product host (Python) + HUD apps
H:\New_VLibs\v4\     Hive libraries (import / pip -e)  [optional path]
G:\HiveSTEAM\        runtime (persona, wake, VCE)       [optional path]
```

Paths above are common on this machine; `scripts/_env.*` also accepts portable defaults via env / `.env`.

## Surfaces

| Surface | How |
|---------|-----|
| Voice on host | Wake **hey chloe** → listen → speak |
| Phone / laptop | Open the printed LAN link in a browser |
| Desktop launcher | Tauri app `apps/desktop` — tray opens HUD on demand |
| Orb | Always-on-top Crystalized Ball (`/?view=orb`); captions overlay while speaking |

## Run

```powershell
cd G:\Amy
.\scripts\bootstrap.ps1   # once
.\scripts\run.ps1         # host + orb (no captions window)
.\scripts\run.ps1 -Lan    # LAN HUD for phones
```

```bash
./scripts/bootstrap.sh
./scripts/run.sh
./scripts/run.sh --lan
```

Or: `python -m amy serve --lan`

Wake: **hey chloe**. Hard stop: **Chloe, stop.**

Full HUD is on demand (launcher tray / double-click orb). Legacy captions window: `AMY_CHAT_WINDOW=1` or `--chat-window`.

## Health check

```powershell
python -m amy doctor            # Python, PYHIVE_HOME, config, guard, STT, mic, ffplay, HUD build, LLM endpoint
python -m amy doctor --offline  # skip the LLM probe
python -m amy doctor --json
```

The same report (plus live host state) is at `GET /api/doctor` for admin devices.

## Devices, roles and HTTPS

The admin token printed at start-up has full control. Give phones and tablets their own
token instead, so you can limit and revoke them:

```powershell
python -m amy devices add kitchen-tablet --role viewer   # prints the token once
python -m amy devices list
python -m amy devices remove kitchen-tablet              # its sessions end immediately
```

| Role | Can |
|------|-----|
| `viewer` | watch state, history, guard status |
| `user` | + send turns, wake / barge, enter lockdown |
| `admin` | + approve guarded actions, leave lockdown, change settings / config / integrations |

Tokens are stored hashed (`~/.amy/devices.json`). Opening a `?token=` link trades it for an
HttpOnly, SameSite=Strict session cookie and removes the token from the address bar.
Rotating the admin token signs out every admin session.

For LAN use, serve over HTTPS so tokens and audio never cross Wi-Fi in clear text:

```powershell
python -m amy cert --host 192.168.1.20   # self-signed cert in ~/.amy/tls (needs .[tls])
python -m amy serve --lan                # HTTPS on port+1 for the LAN, HTTP stays on 127.0.0.1
```

Bring your own cert with `AMY_TLS_CERT` / `AMY_TLS_KEY`; change the HTTPS port with `AMY_HTTPS_PORT`.

## Logs and history

| What | Where | Knobs |
|------|-------|-------|
| App log (JSON lines, turn ids, secrets redacted) | `logs/amy.jsonl`, rotated 5 × 5 MB | `AMY_LOG_LEVEL`, `--log-level`, `AMY_LOG_DIR`, `AMY_LOG_FILE=0` |
| Guard audit | `logs/audit.jsonl` | `AMY_AUDIT_LOG` |
| Chat history (SQLite, survives restarts, searchable) | `~/.amy/history.db` | `AMY_HISTORY=0`, `AMY_HISTORY_DB` |

Every log and audit line from one request carries the same `turn` id. History search:
`GET /api/history?q=weather&limit=50`.

Other server limits: `AMY_TURN_TIMEOUT_S` (default 300), `AMY_MAX_CLIENTS` live sockets (32),
`AMY_SESSION_HOURS` (168). One turn runs at a time across voice and HUD; a second one gets
HTTP 409 and the HUD says Amy is busy.

## Safety guard

The model is treated as untrusted (Amy may run an uncensored model). Prompts are advice;
`amy/guard` is enforcement. Every agent tool call — including Hive specialists and packs
activated via `tools_activate` — passes a policy gate first:

| Verdict | Examples |
|---------|----------|
| **Runs** | volume, brightness, known apps, web search, workspace reads, read-only shell (`ipconfig`, `Get-Process`) |
| **Asks you** | shutdown / restart (min 60 s delay), sleep, Wi-Fi off, printer motion, HKCU registry writes, camera, state-changing shell |
| **Never runs** | recursive delete / format, Defender or firewall off, new users / scheduled tasks, encoded or download-and-run commands, secret files (`.ssh`, `.env`, browser stores), `file:` / `javascript:` / `ms-msdt:` links, LAN / localhost fetches, protected processes |

- **Approvals** — spoken ("say yes or no") during voice turns, or **Approve / Deny** in the HUD. No answer in 25 s = denied. *Chloe, stop* / barge-in cancels pending approvals.
- **Lockdown** — HUD **Lock** button, `AMY_LOCKDOWN=1`, or `lockdown: true`: only read-only tools run.
- **Untrusted content** — after a web page or search result is read, risky actions need approval for the rest of the turn.
- **Secrets** — stored passwords / tokens are scrubbed from tool output; calls carrying them are blocked.
- **Limits** — per-turn and per-minute tool caps; three blocked calls lock the rest of the turn.
  Tool timeouts are clamped to `exec_timeout_s` (60 s) and results truncated to `max_result_chars` (24 000).
- **Shell after untrusted content** — once a web page has been read in a turn, every shell command needs approval.
- **Evasion-resistant** — Unicode look-alike dashes/quotes, abbreviated PowerShell flags, numeric IPs
  (`2130706433`, `0x7f000001`, `127.1`), UNC paths and NTFS streams are normalised before matching.
- **Audit** — every call, decision and approval → `logs/audit.jsonl` (secrets redacted).

Configure under `amy.guard` in `config/hive.yaml` (`mode: strict` asks for every medium-risk call
and requires the word "confirm" by voice; `tools:` overrides any tool to `allow` / `confirm` / `deny`;
`exec_timeout_s`, `max_result_chars`). On start, check the log line `guard mode=… wrapped=N removed=[…]`.

`tests/test_redteam.py` holds ~100 attack strings (encoded commands, LOLBins, persistence, exfiltration,
SSRF, path tricks, prompt injection). Add to it whenever you find a bypass.

HUD API: `POST /api/approve {id, approve}` (admin), `GET /api/guard`, `POST /api/guard/lockdown {on}`.

## Tests

```powershell
python -m pip install -e ".[dev]"
pre-commit install                 # ruff + secret / .env checks on every commit
ruff check amy tests scripts
mypy
python -m pytest

cd apps/web
npm ci
npm run typecheck
npm test                           # Vitest + Testing Library
npm run build
```

Everything runs without the Hive libraries: `tests/fake_pyhive.py` stands in for pyhive so
the host start-up, guard wiring, wake conversation and barge-in are covered end to end.
CI (`.github/workflows/ci.yml`) runs all of the above on every push and pull request.

The HUD's TypeScript types in `apps/web/src/generated/protocol.ts` are generated from
`amy/protocol/messages.py`. After changing a model run `python scripts/gen_protocol_ts.py`;
CI fails if the file is stale.

## Layout

- `amy/` — product host (AmbientHost, AmyServer, Hive specialists)
- `amy/host/` — `ambient.py` orchestrates; `tool_surface`, `turns`, `conversation`,
  `voice_setup`, `voice_events`, `speak_pulse`, `background`, `events` (event bus)
- `amy/hive_adapter.py` — the only place that touches pyhive internals
- `amy/server/` — FastAPI app, auth (roles, devices, sessions), TLS
- `amy/storage/` — SQLite chat history
- `amy/guard/` — safety policy, approvals, redaction, audit
- `apps/web` — React HUD (build with `npm run build` in `apps/web`)
- `apps/desktop` — Tauri launcher
- `apps/orb` — optional Bevy orb (`AMY_ORB=bevy`); default orb is Crystalized Ball in `apps/web`
- `config/hive.yaml` — profiles, model endpoint, `amy.guard` safety settings
- `tests/` — pytest suite

See `docs/ARCHITECTURE.md` and `PRO-PLAN.md`.
