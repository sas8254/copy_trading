#!/usr/bin/env bash
# Stop the stack. Pass --wipe to also drop the postgres volume (DESTROYS DATA).
set -euo pipefail

cd "$(dirname "$0")"

if [ "${1:-}" = "--wipe" ]; then
    echo ">> Stopping and REMOVING DATA VOLUMES..."
    docker compose down -v
else
    echo ">> Stopping containers (data preserved)..."
    docker compose down
fi
