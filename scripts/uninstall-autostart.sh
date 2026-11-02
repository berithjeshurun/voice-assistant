#!/usr/bin/env bash
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/amy.desktop"
echo "Removed Amy autostart (if present)."
