#!/usr/bin/env bash
# Amy host env (cross-platform).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export AMY_ROOT="$ROOT"
export HIVE_CONFIG="${HIVE_CONFIG:-$ROOT/config/hive.yaml}"
export PYHIVE_ASSISTANT_NAME="${PYHIVE_ASSISTANT_NAME:-Amy}"
export AMY_WAKE_PHRASE="${AMY_WAKE_PHRASE:-hey chloe}"

if [[ -z "${PYHIVE_HOME:-}" ]]; then
  if [[ -d "/mnt/g/HiveSTEAM" ]]; then
    export PYHIVE_HOME="/mnt/g/HiveSTEAM"
  elif [[ -d "G:/HiveSTEAM" ]]; then
    export PYHIVE_HOME="G:/HiveSTEAM"
  else
    export PYHIVE_HOME="${HOME}/.pyhive"
  fi
fi

if [[ -z "${HIVE_ARSENAL:-}" ]]; then
  if [[ -d "/mnt/h/New_VLibs/v4" ]]; then
    export HIVE_ARSENAL="/mnt/h/New_VLibs/v4"
  elif [[ -d "H:/New_VLibs/v4" ]]; then
    export HIVE_ARSENAL="H:/New_VLibs/v4"
  fi
fi

ENV_FILE="$ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(echo "$line" | xargs || true)"
    [[ -z "$line" ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    val="${val%\"}"; val="${val#\"}"
    if [[ -z "${!key:-}" ]]; then
      export "$key=$val"
    fi
  done < "$ENV_FILE"
fi

cd "$ROOT"
mkdir -p "$PYHIVE_HOME"
