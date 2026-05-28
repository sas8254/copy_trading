# Core — Django + Vue Boilerplate

A small-scale starter for full-stack apps. Each part (backend, frontend, prod-nginx) is an independent Docker Compose stack with its own `.env`, `Dockerfile`, and `start.sh` / `stop.sh`.

## Stack

| Layer | Tech |
|---|---|
| Backend | Django 6, DRF, django-rest-knox (token auth), psycopg 3, gunicorn, whitenoise |
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
│   ├── accounts/     # auth app (register/login/logout/me)
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
│   │   └── views/                 # LoginView, RegisterView, ProfileView
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

All return/accept JSON. Knox tokens are passed as `Authorization: Token <key>`.

| Method | Path | Auth | Body | Notes |
|---|---|---|---|---|
| GET  | `/api/health/` | none | — | Liveness check |
| POST | `/api/auth/register/` | none | `{username, email, password, [first_name, last_name]}` | Returns user object |
| POST | `/api/auth/login/` | none | `{username, password}` | Returns `{token, expiry}` |
| POST | `/api/auth/logout/` | token | — | Invalidates the token used |
| POST | `/api/auth/logoutall/` | token | — | Invalidates all tokens for the user |
| GET  | `/api/auth/me/` | token | — | Current user |
| —    | `/admin/` | session | — | Django admin |

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

## Troubleshooting

**`ModuleNotFoundError` after editing `requirements.txt`** — rebuild the backend image:
```bash
cd backend && docker compose up --build -d
```

**Vite shows blank page in browser** — check the container logs:
```bash
cd frontend && docker compose logs -f web
```
If file edits aren't triggering reloads, ensure `usePolling: true` is set in `vite.config.js` (it is by default in this template — required for Windows host → Linux container bind mounts).

**CORS errors in dev** — `frontend/.env` `VITE_API_BASE_URL` and `backend/.env` `DJANGO_CORS_ALLOWED_ORIGINS` must agree on the frontend origin (`http://localhost:5173`).

**"CSRF verification failed" on admin login (prod stack)** — `DJANGO_CSRF_TRUSTED_ORIGINS` in `nginx/.env` must include the URL you typed in your browser (e.g. `http://localhost`).

**Port already in use** — another stack is running. Stop it with `./stop.sh`. Dev backend uses 5432/8000, dev frontend uses 5173, prod uses 80.

**Postgres "role does not exist" after editing `POSTGRES_USER`** — the credentials are baked in on first start. Either reset:
```bash
./stop.sh --wipe
./start.sh
```
or `ALTER USER` from inside `psql`.

**Need a fresh DB** — `./stop.sh --wipe && ./start.sh`. Destructive.

## Future additions

When you outgrow this scope:

- **WebSockets** — add `channels` + `daphne` to backend, expose via Nginx
- **Celery + Redis** — add a `redis` service and a `worker` service running `celery -A core worker`
- **HTTPS** — uncomment the TLS server block in `nginx/nginx.conf`, mount certs from `nginx/certs/` (Let's Encrypt + certbot in prod)
- **Non-root user in containers** — add `useradd` + `USER app` to the backend Dockerfile
- **Locked dependencies** — `pip-tools` for backend (compile `requirements.in` → `requirements.txt`)
- **CI** — GitHub Actions running `pytest`, `eslint`, `docker build`
