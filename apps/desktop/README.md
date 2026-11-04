# Amy desktop launcher (Tauri)

Cross-platform tray launcher for **Amy**. Intelligence stays in the Python host.

## Role

- Start / point at the Amy host HUD (`http://127.0.0.1:8787`)
- Tray: **Open Amy HUD** (on demand), **Open orb**, Quit
- Does **not** auto-open a captions window (production is orb-first)

## Prerequisites

- Rust toolchain + [Tauri v2](https://v2.tauri.app/start/prerequisites/) for your OS
- Amy host running: `.\scripts\run.ps1` or `./scripts/run.sh`

## Dev

```bash
cd apps/desktop
npm install
npm run tauri dev
```

## Build installers

```bash
cd apps/desktop
npm run tauri build
```

Outputs under `src-tauri/target/release/bundle/` (`.msi` / `.dmg` / AppImage depending on OS).

## Env

| Variable | Purpose |
|----------|---------|
| `AMY_TOKEN` | HUD auth token |
| `AMY_HOST` / `AMY_PORT` | Host bind (default `127.0.0.1:8787`) |
| `AMY_HUD_URL` | Override full HUD URL |
| `AMY_ORB_URL` | Override orb URL |
