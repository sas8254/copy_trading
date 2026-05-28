#!/usr/bin/env bash
# Build (if needed), start the stack, run migrations, ensure superuser exists.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "ERROR: backend/.env is missing. Copy .env.example to .env and edit." >&2
    exit 1
fi

echo ">> Bringing up containers..."
docker compose up --build -d

echo ">> Applying migrations..."
docker compose exec -T web python manage.py migrate --noinput

echo ">> Ensuring superuser exists..."
docker compose exec -T web python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
if username and not User.objects.filter(username=username).exists():
    User.objects.create_superuser(
        username=username,
        email=os.environ.get("DJANGO_SUPERUSER_EMAIL", ""),
        password=os.environ["DJANGO_SUPERUSER_PASSWORD"],
    )
    print(f"Created superuser: {username}")
else:
    print("Superuser already exists or DJANGO_SUPERUSER_USERNAME not set; skipping.")
PY

echo ""
echo ">> Backend is up:  http://localhost:8000/api/health/"
echo ">> Admin:          http://localhost:8000/admin/"
