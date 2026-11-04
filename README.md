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
- **Audit** — every call, decision and approval → `logs/audit.jsonl` (secrets redacted).

Configure under `amy.guard` in `config/hive.yaml` (`mode: strict` asks for every medium-risk call
and requires the word "confirm" by voice; `tools:` overrides any tool to `allow` / `confirm` / `deny`).
On start, check the log line `guard mode=… wrapped=N removed=[…]`.

HUD API: `POST /api/approve {id, approve}`, `GET /api/guard`, `POST /api/guard/lockdown {on}` (token required).

## Tests

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests
```

Guard, policy and server tests run without the Hive libraries.

## Layout

- `amy/` — product host (AmbientHost, AmyServer, Hive specialists)
- `amy/guard/` — safety policy, approvals, redaction, audit
- `apps/web` — React HUD (build with `npm run build` in `apps/web`)
- `apps/desktop` — Tauri launcher
- `apps/orb` — optional Bevy orb (`AMY_ORB=bevy`); default orb is Crystalized Ball in `apps/web`
- `config/hive.yaml` — profiles, model endpoint, `amy.guard` safety settings
- `tests/` — pytest suite

See `docs/ARCHITECTURE.md` and `PRO-PLAN.md`.
