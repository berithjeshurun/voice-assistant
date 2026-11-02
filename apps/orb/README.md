# Amy orb

Persistent desktop companion presence. **Presentation only** — no tools, no keys.

## What runs by default

`.\scripts\run.ps1` / `python -m amy serve` launches a **Crystalized Ball** companion ([React Bits](https://www.reactbits.dev/animations/crystalized-ball)):

1. Web orb at `/?view=orb` via Edge/Chrome `--app` mode (or pywebview if installed)
2. Tiny Tk placeholder only if no Chromium-family browser is found

State → preset mapping lives in `apps/web/src/components/AmyOrb.tsx` (idle frost, listening aurora, thinking plasma, speaking solar, …).

Disable with `--no-orb` / `-NoOrb`.

## Legacy Bevy

```bash
cd apps/orb
cargo build --release
AMY_ORB=bevy python -m amy serve
```

## Protocol (stdin NDJSON)

Crystalized mode follows AmyServer over WebSocket; Bevy still accepts:

```json
{"type":"set_state","state":"listening"}
{"type":"open_hud"}
```

Stdout: `{"type":"renderer_ready","name":"Amy","mode":"…"}`
