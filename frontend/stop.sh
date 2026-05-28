#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo ">> Stopping frontend..."
docker compose down
