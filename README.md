# Copy Trading

Copies trades from one Zerodha account (the master) to other Zerodha accounts,
with a per-account quantity multiplier. Everything is managed from the website.

> 📖 **[docs/GUIDE.md](docs/GUIDE.md)**: how it works, setup, every setting.
> 📋 **[docs/CHEATSHEET.md](docs/CHEATSHEET.md)**: the daily steps on one page.

Two ways to run it, each a Docker Compose stack with its own `.env` and `start.sh` / `stop.sh`:

- **Development** on your computer: `backend/` + `frontend/` (code reloads, debug on).
- **Production** on a server: `deploy/` (HTTPS, everything baked into images, backups).

## Stack

| Layer | Tech |
|---|---|
| Backend | Django 6, DRF, django-rest-knox (token auth), psycopg 3, Daphne (ASGI), whitenoise |
| Realtime / async | Channels + channels-redis (WebSockets), Celery + Celery Beat, Redis |
| Broker | Zerodha Kite Connect (REST + Ticker WebSocket) |
| Database | PostgreSQL 16 |
| Frontend | Vue 3, Vite, Vue Router, Pinia, axios, Vuetify 3 |
| Prod server | Caddy 2 (automatic HTTPS) |
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
└── deploy/           # production: HTTPS + full copy-trading stack + backups
    ├── docker-compose.yml       # caddy, web, celery_worker, celery_beat, kite_ticker, db, redis, backup
    ├── Caddyfile                # HTTPS, website, /api + /ws proxy
    ├── Dockerfile               # builds the website into the Caddy image
    ├── .env / .env.example
    ├── start.sh / stop.sh / restore.sh
    └── backups/                 # daily database dumps (gitignored)
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

## Deploying to a server

Everything runs from `deploy/`: Caddy (HTTPS), the website, the API, the copy
engine (Celery worker + beat), the optional Zerodha ticker, Postgres, Redis and
daily backups. Postgres and Redis are not reachable from outside.

**You need:** a small Linux VPS (2 GB RAM is plenty) with Docker, a domain whose
DNS A record points at the server, and ports 80 + 443 open.

1. **Copy the project to the server** (e.g. `git clone`), then:
   ```bash
   cd deploy
   cp .env.example .env    # fill in every <...> value; comments explain each one
   ./start.sh
   ```
   `start.sh` refuses to start while placeholders are left, builds everything,
   runs migrations and creates the website login. Caddy fetches the HTTPS
   certificate on first start.
2. **Kite apps:** set each app's Redirect URL to `https://<your-domain>/kite/callback`.
3. **Website:** add the accounts again (the server has its own database), log in
   to Zerodha, set alert emails.
4. **Dead-man's switch (strongly recommended):** create a free check at
   [healthchecks.io](https://healthchecks.io) (period 1 minute, grace 3 minutes),
   put its ping URL in `HEARTBEAT_URL`, then `docker compose up -d`. If the copy
   engine or the whole server stops, it emails you. `https://<your-domain>/api/health/`
   also returns 503 when the engine is down, for any uptime monitor.
5. **Backups:** a dump lands in `deploy/backups/` at start-up and then daily (kept
   `BACKUP_KEEP_DAYS`). Copy them off the server regularly (e.g. `rsync`/`rclone` from a cron job).
   Restore with `./restore.sh backups/core-<date>.sql.gz`.

Behind Cloudflare Tunnel or another HTTPS proxy? Set `SITE_ADDRESS=:80`. To try
the production stack on your own computer: `SITE_ADDRESS=:80 ./start.sh`, then
open http://localhost (stop it with `./stop.sh`).

**Updating:** `git pull && ./start.sh` (rebuilds, migrates, restarts).

In production, Django admin is not exposed (`/admin` returns 404), debug is off,
logins are rate-limited (`LOGIN_RATE_LIMIT`, default 10/min) and secure cookies
are on.

## Environment files

Each stack has its own `.env` (gitignored) and `.env.example` (committed, with
comments explaining every value): `backend/.env` (development), `frontend/.env`
(development), `deploy/.env` (production). See [docs/GUIDE.md](docs/GUIDE.md) section 7.

## API endpoints

All return/accept JSON and require `Authorization: Token <key>` except health and login.
There is no public sign-up; add users in Django admin.

| Method | Path | Notes |
|---|---|---|
| GET  | `/api/health/` | No auth. 200 if the copy engine ran in the last minute, else 503 |
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
