#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARGET="${1:-${TARGET:-}}"
if [ -z "$TARGET" ]; then
  echo "usage: $0 https://example.com/"
  exit 1
fi

VUS="${VUS:-500}"
DURATION="${DURATION:-500m}"
RAMP_UP="${RAMP_UP:-5s}"
THINK_TIME="${THINK_TIME:-0}"
USER_AGENT="${USER_AGENT:-loadtest-codespace/1.0}"

mkdir -p results
STAMP="$(date -u +%Y%m%d-%H%M%S)"

exec k6 run \
  --no-color \
  --no-usage-report \
  --summary-export "results/summary-${STAMP}.json" \
  -e "TARGET=${TARGET}" \
  -e "VUS=${VUS}" \
  -e "DURATION=${DURATION}" \
  -e "RAMP_UP=${RAMP_UP}" \
  -e "THINK_TIME=${THINK_TIME}" \
  -e "USER_AGENT=${USER_AGENT}" \
  loadtest.js
