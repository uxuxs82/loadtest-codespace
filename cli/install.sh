#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${LOADTEST_BIN_DIR:-${PREFIX:-$HOME/.local}/bin}"

mkdir -p "$TARGET"
install -m 0755 "$DIR/k6.py" "$TARGET/k6"
echo "установлено: $TARGET/k6"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh не найден. установи github cli и выполни gh auth login"
fi

case ":$PATH:" in
  *":$TARGET:"*) ;;
  *) echo "добавь $TARGET в PATH" ;;
esac
