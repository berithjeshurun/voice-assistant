#!/usr/bin/env bash
# Amy product entry — always-on host + HUD server + persistent companion orb.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/_env.sh"

LAN=0
CONSOLE=0
FORCE=0
ORB=1
BIND="127.0.0.1"
PORT=8787
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lan) LAN=1 ;;
    --console) CONSOLE=1 ;;
    --force) FORCE=1 ;;
    --no-orb) ORB=0 ;;
    --orb) ORB=1 ;;
    --bind) BIND="$2"; shift ;;
    --port) PORT="$2"; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

echo "Amy voice host"
echo "  HIVE_CONFIG=$HIVE_CONFIG"
echo "  PYHIVE_HOME=$PYHIVE_HOME"
echo "  wake: hey chloe"
echo "  orb: persistent companion"

ARGS=(serve --bind "$BIND" --port "$PORT")
[[ "$LAN" -eq 1 ]] && ARGS+=(--lan)
[[ "$CONSOLE" -eq 1 ]] && ARGS+=(--console)
[[ "$FORCE" -eq 1 ]] && ARGS+=(--force)
[[ "$ORB" -eq 0 ]] && ARGS+=(--no-orb)

exec python -m amy "${ARGS[@]}"
