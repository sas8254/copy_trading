#!/usr/bin/env bash
# Restore the database from a backup made by the `backup` service.
#   ./restore.sh backups/core-2026-10-14_0930.sql.gz
# REPLACES all current data. The copy engine is stopped during the restore.
set -euo pipefail
cd "$(dirname "$0")"

file="${1:-}"
if [ -z "$file" ] || [ ! -f "$file" ]; then
    echo "Usage: ./restore.sh backups/core-YYYY-MM-DD_HHMM.sql.gz" >&2
    exit 1
fi
read -r -p "This replaces ALL current data with $file. Type 'restore' to continue: " answer
[ "$answer" = "restore" ] || { echo "Cancelled."; exit 1; }

docker compose stop web celery_worker celery_beat kite_ticker
docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
gunzip -c "$file" | docker compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose up -d
echo "Restored from $file."
