---
name: smartpanels
description: Log into Smart Panel and open the dashboard. Prefer HTTP login; fall back to Playwright when needed. Credentials live only in ~/.amy/secrets/smartpanels.env (or AMY_SMARTPANELS_* env). Never speak passwords or emails aloud.
---

# SmartPanels

## When to use
- User asks to log into SmartPanel / Smart Panel
- User asks to open SmartPanel / the dashboard
- Status checks for SmartPanels session

## Tools
- `smartpanels_status` — secrets present? session valid?
- `smartpanels_login` — HTTP first, then Playwright; persists session under `~/.amy/state/smartpanels/`
- `smartpanels_open` — ensure logged in, open dashboard (browser or URL + session OK)
- `smartpanels_logout` — clear local session state
- `smartpanels_rooms` — list rooms + lights/fans
- `smartpanels_set_room` — `room='Meeting Room', on=true|false` (or lights=/fans=/power=)

## Safety
- Level L2 (auto when secrets are present)
- Room on/off only — no destructive admin actions
- Never echo password, email, or tokens in captions/TTS
- Audit: `smartpanels_login ok via=http|browser` / `smartpanels_set_room ok` without credentials

## Voice phrases
- "log into SmartPanel" / "open SmartPanel"
- "turn on the meeting room" / "turn off meeting room lights"
