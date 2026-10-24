#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

K6_VERSION="v2.3.0"

sudo apt-get update
sudo apt-get install -y --no-install-recommends curl ca-certificates tar

case "$(uname -m)" in
  x86_64) K6_ARCH="amd64" ;;
  aarch64) K6_ARCH="arm64" ;;
  *)
    echo "unsupported architecture: $(uname -m)"
    exit 1
    ;;
esac

K6_DIR="k6-${K6_VERSION}-linux-${K6_ARCH}"
K6_ARCHIVE="/tmp/${K6_DIR}.tar.gz"

curl -fsSL "https://github.com/grafana/k6/releases/download/${K6_VERSION}/${K6_DIR}.tar.gz" -o "$K6_ARCHIVE"
tar -xzf "$K6_ARCHIVE" -C /tmp
sudo install -m 0755 "/tmp/${K6_DIR}/k6" /usr/local/bin/k6

python3 -m pip install --user --no-warn-script-location -r requirements.txt

mkdir -p results
k6 version
