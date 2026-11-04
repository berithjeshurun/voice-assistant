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

## Layout

- `amy/` — product host (AmbientHost, AmyServer, Hive specialists)
- `apps/web` — React HUD (build with `npm run build` in `apps/web`)
- `apps/desktop` — Tauri launcher
- `apps/orb` — optional Bevy orb (`AMY_ORB=bevy`); default orb is Crystalized Ball in `apps/web`
- `config/hive.yaml` — profiles + model endpoint

See `docs/ARCHITECTURE.md` and `PRO-PLAN.md`.
