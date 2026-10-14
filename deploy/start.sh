#!/usr/bin/env bash
# Build and start the production stack, then make sure the website login exists.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "ERROR: deploy/.env is missing. Copy .env.example to .env and fill it in." >&2
    exit 1
fi
if grep -qE '=<[^>]*>' .env; then
    echo "ERROR: deploy/.env still has <placeholder> values:" >&2
    grep -nE '=<[^>]*>' .env | sed 's/=.*/=.../' >&2
    exit 1
fi
for var in DJANGO_SECRET_KEY POSTGRES_PASSWORD FIELD_ENCRYPTION_KEY SITE_ADDRESS DJANGO_SUPERUSER_PASSWORD; do
    if ! grep -qE "^${var}=.+" .env; then
        echo "ERROR: ${var} is empty in deploy/.env" >&2
        exit 1
    fi
done
mkdir -p backups

echo ">> Building and starting..."
docker compose up --build -d

echo ">> Ensuring the website login exists..."
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
    print(f"Created login: {username}")
else:
    print("Login already exists.")
PY

site=$(grep -E '^SITE_ADDRESS=' .env | cut -d= -f2-)
echo ""
echo ">> Up. Website: ${site/#:80/http://localhost}"
echo "   Health:  <website>/api/health/  (503 until the copy engine has run once)"
echo "   Logs:    docker compose logs -f celery_worker"
