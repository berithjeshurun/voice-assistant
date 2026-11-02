# Amy Apps

Installable packs under `apps/packs/<id>/` — SKILL.md + tools + local secrets.

## Layout

```
apps/packs/<id>/
  SKILL.md          # when-to-use, voice phrases, safety
  manifest.yaml     # id, tools, secrets schema, base_url
  tools.py          # def register(registry) -> list[str]
  client_*.py       # pack implementation
  secrets.example.env
```

Amy loader: `amy/apps/loader.py` discovers packs, registers tools when enabled, reads secrets from `~/.amy/secrets/<id>.env`.

## Enable

In `config/hive.yaml`:

```yaml
amy:
  apps:
    enabled: [smartpanels]
```

Or env: `AMY_APPS=smartpanels`.

## CLI

```bash
python -m amy apps list
python -m amy apps install smartpanels
python -m amy apps status smartpanels
```

Install writes a secrets template if missing. Fill credentials in the file (or `AMY_SMARTPANELS_USER` / `AMY_SMARTPANELS_PASSWORD`). Never put secrets in git; never speak them via voice.

## SmartPanels (first pack)

- HTTP: `POST /api/auth/login` with `{email, password}` → session in `~/.amy/state/smartpanels/session.json`
- Rooms: `GET /api/rooms`, control via `PATCH /api/rooms/{id}` `{lightsOn,fansOn}` and `PATCH /api/boards/{id}` `{poweredOn}`
- Playwright fallback for login/UI; open injects `smart_panel_session` into localStorage
- Tools: `smartpanels_status|login|open|logout|rooms|set_room`
- Voice: “open SmartPanel”, “turn on the meeting room”

Optional: `pip install playwright` then `playwright install msedge` (or chromium).

## Add a new pack

1. Copy `apps/packs/smartpanels/` → `apps/packs/<id>/`
2. Edit `manifest.yaml`, `SKILL.md`, clients, `tools.py`
3. Add id to `amy.apps.enabled`
4. `python -m amy apps install <id>` and fill secrets
