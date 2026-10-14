# Copy Trading

Automatically copies trades from one Zerodha account (the **master**) to other
Zerodha accounts (the **copies**), each with its own quantity multiplier, and
alerts you if anything goes out of sync. Everything is managed from a website.

## Documentation

| Document | For |
|---|---|
| 📖 [docs/GUIDE.md](docs/GUIDE.md) | **Using the app**: setup, daily routine, pages, copy modes and styles with examples, alerts, settings, troubleshooting, FAQ |
| 📋 [docs/CHEATSHEET.md](docs/CHEATSHEET.md) | The daily steps and quick fixes on one page |
| 🚀 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Running it on a server with HTTPS (Let's Encrypt), monitoring, updates |
| 🛠️ [docs/DEVELOPER.md](docs/DEVELOPER.md) | Code layout, copy engine internals, data model, REST/WebSocket API with examples, tests |
| 🗒️ [PLAN.md](PLAN.md) | Original design notes (historical) |

## Features

- **Website for everything:** accounts, one-click daily Zerodha login, choose
  the master, live positions and P&L, order history, settings.
- **Three modes:** Off · Dry run (simulate) · Live (real orders).
- **Two copy styles:** *When filled* (copy after the master's order fills) or
  *Mirror* (copy when placed at the same price, follow modifications and cancels).
- **Quantity:** `master × multiplier`, rounded down to whole F&O lots (synced
  from Zerodha daily).
- **Keeps accounts in sync:** final check with market top-ups after a 15 s grace
  period, position comparison every 2 s, alerts on the website and by email.
- **Safe by default:** dry run, instant Off, no replay of old orders, nothing
  placed twice, extras never auto-sold.
- **Monitoring:** "copy engine running" check, `/api/health/`, external
  heartbeat (healthchecks.io), 8:45 AM login reminder.
- **Secure:** login required everywhere, no public sign-up, login rate limit
  (10/min), encrypted broker secrets; on a server: HTTPS, admin not public.

## Quick start (your computer)

Needs **Docker Desktop** and **Git Bash** (Windows).

```bash
cp backend/.env.example backend/.env      # set DJANGO_SECRET_KEY, passwords, email
cp frontend/.env.example frontend/.env

cd backend && ./start.sh                  # database, API, copy engine
cd ../frontend && ./start.sh              # website
```

Open **http://localhost:5173**, sign in with `DJANGO_SUPERUSER_USERNAME` /
`DJANGO_SUPERUSER_PASSWORD` from `backend/.env`, then follow
[GUIDE.md → First-time setup](docs/GUIDE.md#4-first-time-setup).

Stop with `./stop.sh` in each folder (`./stop.sh --wipe` in `backend/` also
deletes the database).

## Server

```bash
cd deploy
cp .env.example .env      # fill in every <...>
./start.sh
```
Full walkthrough: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Project layout

```
backend/    Django API, copy engine (Celery), live updates (Channels). Dev stack.
frontend/   Vue 3 + Vuetify website. Dev stack (Vite).
deploy/     Production stack: Caddy (HTTPS) + everything baked into images.
docs/       Guides.
```

| Layer | Tech |
|---|---|
| Backend | Django 6, DRF, Knox, Celery + Beat, Channels, Daphne, PostgreSQL 16, Redis |
| Broker | Zerodha Kite Connect |
| Frontend | Vue 3, Vite, Pinia, Vuetify 4 |
| Production | Docker Compose, Caddy 2 (automatic Let's Encrypt) |

## Environment files

| File | Used by | Template |
|---|---|---|
| `backend/.env` | Development backend | `backend/.env.example` |
| `frontend/.env` | Development website | `frontend/.env.example` |
| `deploy/.env` | Production | `deploy/.env.example` |

Every setting is explained in [GUIDE.md section 12](docs/GUIDE.md#12-every-setting-explained).
`.env` files are gitignored. Keep them private and keep `FIELD_ENCRYPTION_KEY` safe.
