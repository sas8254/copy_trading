# Copy Trading

Copies trades from one Zerodha account (the master) to other Zerodha accounts,
with a per-account quantity multiplier. Everything is managed from the website.

> 📖 **[docs/GUIDE.md](docs/GUIDE.md)**: how it works, setup, every setting.
> 📋 **[docs/CHEATSHEET.md](docs/CHEATSHEET.md)**: the daily steps on one page.

Each part (backend, frontend, prod-nginx) is an independent Docker Compose stack with its own `.env`, `Dockerfile`, and `start.sh` / `stop.sh`.

## Stack

| Layer | Tech |
|---|---|
| Backend | Django 6, DRF, django-rest-knox (token auth), psycopg 3, Daphne (ASGI), whitenoise |
| Realtime / async | Channels + channels-redis (WebSockets), Celery + Celery Beat, Redis |
| Broker | Zerodha Kite Connect (REST + Ticker WebSocket) |
| Database | PostgreSQL 16 |
| Frontend | Vue 3, Vite, Vue Router, Pinia, axios, Vuetify 3 |
| Prod server | Nginx 1.27 (alpine) |
| Containers | Docker / Docker Compose |
| Backend base image | Ubuntu 24.04 |

Default Django `User` model. Knox tokens stored in browser `localStorage`.

## Project layout

```
my_project/
├── backend/          # Django (dev: runserver, port 8000)
│   ├── core/         # Django project (settings.py, urls.py, ...)
│   ├── accounts/     # website login (login/logout/me)
│   ├── copytrading/  # copy-trading app (models, API, services, Celery tasks)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── .env / .env.example
│   └── start.sh / stop.sh
├── frontend/         # Vue + Vite (dev: vite, port 5173)
│   ├── src/
│   │   ├── api/client.js          # axios + token interceptor
│   │   ├── stores/auth.js         # Pinia auth store
│   │   ├── router/index.js        # routes + guards
│   │   ├── plugins/vuetify.js
│   │   └── views/                 # Home, Accounts, Positions, Orders, Settings, Login
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── vite.config.js
│   ├── .env / .env.example
│   └── start.sh / stop.sh
└── nginx/            # prod-like (port 80, nginx + gunicorn + db)
    ├── Dockerfile               # multi-stage: builds frontend + nginx image
    ├── nginx.conf
    ├── docker-compose.yml
    ├── .env / .env.example
    └── start.sh / stop.sh
```

## Prerequisites

- **Docker Desktop** (with Docker Compose v2)
- **Git Bash** or **WSL** on Windows (for running `*.sh` scripts)
- **Node.js 20+** *(only needed if you want to run Vite directly on host instead of in Docker, or to scaffold from scratch)*
- **Python 3.12+** *(only needed for one-off `manage.py` commands outside Docker)*

## First-time setup

```bash
git clone <your-repo-url> my_project
cd my_project

# Backend env
cp backend/.env.example backend/.env
# Generate a fresh secret key:
python -c "import secrets; print(secrets.token_urlsafe(50))"
# Paste it into DJANGO_SECRET_KEY in backend/.env

# Frontend env
cp frontend/.env.example frontend/.env

# (Optional, only if you want to run the prod-like stack)
cp nginx/.env.example nginx/.env
# Generate another fresh secret key for prod:
python -c "import secrets; print(secrets.token_urlsafe(50))"
# Paste into DJANGO_SECRET_KEY in nginx/.env
```

## Running — development

Two stacks, run in two terminals.

```bash
# Terminal 1: backend + db
cd backend
./start.sh
# http://localhost:8000/api/health/
# http://localhost:8000/admin/

# Terminal 2: frontend
cd frontend
./start.sh
# http://localhost:5173/
```

`start.sh` handles `docker compose up --build`, runs migrations, and creates the superuser from `DJANGO_SUPERUSER_*` if it doesn't already exist.

To stop:

```bash
./stop.sh           # preserves data
./stop.sh --wipe    # destroys postgres volume
```

## Running — production-like (local)

Stop the dev stacks first (port conflicts on Postgres). Then:

```bash
cd nginx
./start.sh
```

This builds a single self-contained stack:

- **db** — Postgres (separate volume from dev)
- **web** — Django via gunicorn (no source mount; baked into image)
- **nginx** — serves built Vue SPA + reverse-proxies `/api/`, `/admin/`, `/static/` to gunicorn

Access:

- App: http://localhost/
- API: http://localhost/api/health/
- Admin: http://localhost/admin/

The frontend bundle is rebuilt on `--build` from the current state of `frontend/`. Nothing is shared with the dev stacks at runtime.

## Environment files

Each stack has its own `.env` (gitignored) and `.env.example` (committed).

| Var | Used by | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | backend, nginx | Use distinct values per env |
| `DJANGO_DEBUG` | backend, nginx | `True` in dev, `False` in prod |
| `DJANGO_ALLOWED_HOSTS` | backend, nginx | Comma-separated |
| `DJANGO_CORS_ALLOWED_ORIGINS` | backend | Frontend origin(s) for dev (`http://localhost:5173`); empty in prod |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | backend, nginx | Required in prod for admin login over HTTP/HTTPS |
| `POSTGRES_*` | backend, nginx | DB name/user/password/host/port |
| `DJANGO_SUPERUSER_*` | backend, nginx | Used by `start.sh` to bootstrap admin |
| `VITE_API_BASE_URL` | frontend | Dev: `http://localhost:8000/api`. Overridden to `/api` in the prod build |

## API endpoints

All return/accept JSON and require `Authorization: Token <key>` except health and login.
There is no public sign-up; add users in Django admin.

| Method | Path | Notes |
|---|---|---|
| GET  | `/api/health/` | Liveness check (no auth) |
| POST | `/api/auth/login/` | `{username, password}` → `{token, expiry}` (no auth) |
| POST | `/api/auth/logout/`, `/api/auth/logoutall/` | Invalidate this / all tokens |
| GET  | `/api/auth/me/` | Current user |
| GET  | `/api/copytrading/overview/` | Home page: mode, checklist, alerts, recent orders |
| GET/POST | `/api/copytrading/accounts/` | List / add accounts |
| GET/PATCH/DELETE | `/api/copytrading/accounts/<id>/` | One account (API secret is write-only) |
| POST | `/api/copytrading/accounts/<id>/make-master/` | Make this the master |
| GET  | `/api/copytrading/accounts/<id>/login-url/` | Zerodha login URL |
| POST | `/api/copytrading/accounts/<id>/login/` | `{request_token}` → stores the day's access token |
| GET  | `/api/copytrading/positions/` | Live positions: master + per-copy comparison |
| GET  | `/api/copytrading/orders/?limit=` | Master orders with their copy orders |
| GET/PATCH | `/api/copytrading/settings/` | `{mode: off\|dry_run\|live, alert_emails}` |
| POST | `/api/copytrading/settings/test-email/` | Send a test alert email |
| GET  | `/api/copytrading/alerts/?resolved=` | Alerts |
| POST | `/api/copytrading/alerts/<id>/resolve/`, `/api/copytrading/alerts/resolve-all/` | Dismiss alerts |
| WS   | `/ws/dashboard/?token=<key>` | Live event feed |
| —    | `/admin/` | Django admin (backup) |

## Adding a new Django app

```bash
cd backend
docker compose exec web python manage.py startapp myapp
```

Then in `core/settings.py` add `"myapp"` to `INSTALLED_APPS`, wire its URLs in `core/urls.py`, write models, and:

```bash
docker compose exec web python manage.py makemigrations myapp
docker compose exec web python manage.py migrate
```

## Adding a new frontend page

1. Create `frontend/src/views/MyView.vue`
2. Add a route in `frontend/src/router/index.js` (set `meta: { requiresAuth: true }` to gate it)
3. Add a nav link in `frontend/src/App.vue` if needed

The axios client already attaches the auth token — just `import api from '@/api/client'` and call `api.get('/some/path/')`.

## Common Docker commands

Run inside any stack's directory.

```bash
docker compose ps                                      # status
docker compose logs -f web                             # tail backend logs
docker compose logs -f                                 # tail all services
docker compose exec web python manage.py shell         # Django shell
docker compose exec db psql -U core -d core            # psql
docker compose down -v                                 # stop + nuke volumes
docker compose build --no-cache                        # force fresh image build
```

## Authentication flow (frontend)

1. User submits Login form → POST `/api/auth/login/`
2. Knox returns `{token, expiry}` → stored in `localStorage` and Pinia store
3. axios request interceptor attaches `Authorization: Token <key>` to every subsequent request
4. axios response interceptor catches 401 → clears token, redirects to `/login`
5. Vue Router guard redirects unauthed users from protected routes to `/login?next=<path>`

Token TTL is 10 hours with `AUTO_REFRESH=True` (each request resets the clock). Configurable in `backend/core/settings.py` under `REST_KNOX`.

## Copy Trading

### Extra services (backend stack)

Beyond `db` + `web`, the backend compose runs:

| Service | Role |
|---|---|
| `redis` | Celery broker/result backend + Channels layer |
| `web` | **Daphne** (ASGI): serves HTTP **and** WebSockets |
| `celery_worker` | Places copy orders, retries, syncs lot sizes |
| `celery_beat` | Every 2s: order poll + reconciliation. Weekdays 9:00 IST: lot-size sync |
| `kite_ticker` | Live Zerodha order WebSocket (instant copy trigger) |

### Data flow

```
master orders ──┬─ Kite Ticker WS (kite_ticker)  ─┐  instant
                └─ REST poll (celery_beat, 2s)    ─┴─▶ Trade ─▶ dispatch ─▶ copy order(s)
                                                          (×multiplier, lot-rounded, retry)
positions ───────── reconcile (celery_beat, 2s) ──▶ mismatch ─▶ Alert (email + website)
all events ──────── Channels ─▶ ws/dashboard/ ────▶ website (live)
```

### Using it

1. Start both stacks (above) and open http://localhost:5173.
2. **Accounts**: add the master and the copy accounts (Kite Connect API key +
   secret). Set each Kite app's Redirect URL to `http://localhost:5173/kite/callback`.
3. Every trading morning: **Login to Zerodha** on each account.
4. **Settings**: switch copying from **Dry run** to **Live** when ready.

See [docs/GUIDE.md](docs/GUIDE.md) for details.
