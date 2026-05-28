#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "ERROR: frontend/.env is missing. Copy .env.example to .env." >&2
    exit 1
fi

echo ">> Bringing up frontend..."
docker compose up --build -d

echo ""
echo ">> Frontend is up:  http://localhost:5173/"
