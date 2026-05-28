#!/usr/bin/env bash
# Bring up the prod-like stack: db + gunicorn + nginx (with built frontend baked in).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "ERROR: nginx/.env is missing. Copy .env.example to .env and edit." >&2
    exit 1
fi

echo ">> Building and starting prod stack..."
docker compose up --build -d

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
echo ">> Prod stack is up:"
echo "   App:    http://localhost/"
echo "   API:    http://localhost/api/health/"
echo "   Admin:  http://localhost/admin/"
