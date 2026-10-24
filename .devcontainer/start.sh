#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p results

LOCK_FILE="$ROOT/results/ui.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "load test studio is already running on http://127.0.0.1:8000"
  exit 0
fi

echo "load test studio: http://127.0.0.1:8000"
exec python3 app.py
