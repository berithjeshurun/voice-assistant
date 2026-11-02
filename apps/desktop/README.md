# Amy desktop (Tauri)

Cross-platform shell titled **Amy** with system tray.

## Prerequisites

- Rust toolchain
- Tauri v2 prerequisites for your OS
- Amy host running (`python -m amy serve` or `.\scripts\run.ps1`)

## Dev

```bash
cd apps/desktop
npm install
npm run tauri dev
```

The window loads `apps/desktop/ui` (launcher). Point it at the host HUD URL that includes `?token=…`.

## Note

Intelligence stays in the Python Amy host. This app is UI only — not a Jarvis rename.
