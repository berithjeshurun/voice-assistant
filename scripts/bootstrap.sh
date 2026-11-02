#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/_env.sh"

A="${HIVE_ARSENAL:-}"
if [[ -z "$A" || ! -d "$A" ]]; then
  echo "Arsenal missing: set HIVE_ARSENAL to New_VLibs/v4" >&2
  exit 1
fi

echo "Installing libraries from $A ..."
python -m pip install \
  -e "$A/pyhive" \
  -e "$A/hivedb" \
  -e "$A/hiveworkers" \
  -e "$A/hivesteam" \
  -e "$A/hivepersona" \
  -e "$A/hivescreen" \
  -e "$A/hivepulse" \
  -e "$A/hivesense" \
  -e "$A/hivecraft" \
  -e "$A/hiveknow" \
  -e "$A/hivetrace"

python -m pip install -e "$A/pyhive[ambient]" -e "$A/pyhive[react-ui]" -e "$A/pyhive[coding]" || true
python -m pip install -e "$AMY_ROOT"

if [[ -f "$AMY_ROOT/apps/web/package.json" ]]; then
  echo "Building web HUD ..."
  (cd "$AMY_ROOT/apps/web" && npm install && npm run build)
fi

python -c "import amy, pyhive; print('amy', amy.__version__, pyhive.__file__)"
echo "Done. Run: ./scripts/run.sh   LAN: ./scripts/run.sh --lan"
