#!/usr/bin/env bash
# Stop the production stack. Data, certificates and backups are kept.
set -euo pipefail
cd "$(dirname "$0")"
docker compose down
