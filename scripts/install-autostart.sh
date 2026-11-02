#!/usr/bin/env bash
# Best-effort user autostart (Linux desktop .desktop file).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
mkdir -p "$DIR"
cat > "$DIR/amy.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Amy
Exec=$ROOT/scripts/run.sh
X-GNOME-Autostart-enabled=true
EOF
echo "Wrote $DIR/amy.desktop"
