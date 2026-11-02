# Amy

Always-on personal assistant. **Not a chatbot. Not Jarvis.**

```text
G:\Amy\              product host (Python) + HUD apps
H:\New_VLibs\v4\     Hive libraries (import / pip -e)
G:\HiveSTEAM\        runtime (persona, wake, VCE)
```

## Surfaces

| Surface | How |
|---------|-----|
| Voice on host | Wake **hey amy** → listen → speak |
| Phone / laptop | Open the printed LAN link in a browser |
| Desktop HUD | Tauri app `apps/desktop` (title **Amy**) |
| Orb | Persistent Crystalized Ball companion ([React Bits](https://www.reactbits.dev/animations/crystalized-ball)) |

## Run

```powershell
cd G:\Amy
.\scripts\bootstrap.ps1   # once
.\scripts\run.ps1         # host + local HUD server
.\scripts\run.ps1 -Lan    # central hive server — phones on Wi‑Fi
```

```bash
./scripts/bootstrap.sh
./scripts/run.sh
./scripts/run.sh --lan
```

Or: `python -m amy serve --lan`

Say **hey amy** on the host mic. Hard stop: **Amy, stop.**

## Layout

- `amy/` — product host (AmbientHost, AmyServer, protocol)
- `apps/web` — React HUD (served at `/`)
- `apps/desktop` — Tauri shell
- `apps/orb` — optional Bevy orb (`AMY_ORB=bevy`); default orb is Crystalized Ball in `apps/web`
- `config/hive.yaml` — Hive profile (brain stays in libraries)

See `docs/ARCHITECTURE.md` and `PRO-PLAN.md`.
