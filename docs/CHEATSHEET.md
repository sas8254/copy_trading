# Copy Trading — Cheat Sheet

One-page daily reference. Full details in [GUIDE.md](./GUIDE.md).
All commands run from `backend/`. Prefix with: `docker compose exec web python manage.py`

---

## Every morning (tokens expire ~6 AM IST)

```powershell
.\morning.ps1            # Windows  — login both accounts, sync, restart, preflight
```

```bash
bash morning.sh          # macOS/Linux/Git-Bash
```

### …or manually

```bash
# 1. Login MASTER
docker compose exec web python manage.py kite_login --account "mom_zerodha"                       # prints URL
docker compose exec web python manage.py kite_login --account "mom_zerodha" --request-token XXXX  # store token
# 2. Login COPY
docker compose exec web python manage.py kite_login --account "my_zerodha"
docker compose exec web python manage.py kite_login --account "my_zerodha" --request-token YYYY
# 3. Sync lot sizes + restart + check
docker compose exec webpython manage.py kite_sync_instruments --account "mom_zerodha"
docker compose restart kite_ticker celery_worker celery_beat
docker compose exec webpython manage.py preflight
```

---

## Stack control

```bash
docker compose exec web docker compose up -d                      # start everything
docker compose exec web docker compose ps                         # status of all containers
docker compose exec web docker compose restart celery_worker celery_beat kite_ticker   # reload code into workers
docker compose exec web docker compose down                       # stop (keeps data)
docker compose exec web docker compose logs -f celery_worker      # watch the copy/reconcile loop
docker compose exec web docker compose logs -f kite_ticker        # watch the live order feed
```

---

## Dashboards

| URL                              | Notes                      |
| -------------------------------- | -------------------------- |
| http://localhost:5173/dashboard  | Vue SPA (needs login)      |
| http://localhost:8000/dashboard/ | Quick view (no login)      |
| http://localhost:8000/admin/     | Accounts, mappings, alerts |

---

## Checks & tests (safe, no real orders)

```bash
docker compose exec web python manage.py preflight             # GO / NO-GO readiness
docker compose exec web python manage.py kite_positions --account "mom_zerodha"   # live positions
docker compose exec web python manage.py send_test_email       # verify SMTP
docker compose exec web python manage.py reconcile_selftest    # mismatch→alert→resolve (fake data)
docker compose exec web python manage.py dispatch_selftest     # dispatch pipeline (fake data)
```

---

## Go live (real orders) — be deliberate

```bash
docker compose exec web python manage.py preflight                 # must say GO
# set COPYTRADING_LIVE_ORDERS=True in backend/.env, then:
docker compose up -d && docker compose restart celery_worker
```

Start with a **small multiplier** and **one cheap instrument**.
Back to safe: set `COPYTRADING_LIVE_ORDERS=False`, `docker compose up -d`, restart worker.

---

## Key `.env` flags

| Flag                               | Default | Meaning                                        |
| ---------------------------------- | ------- | ---------------------------------------------- |
| `COPYTRADING_LIVE_ORDERS`          | `False` | `True` = real orders; else dry-run (simulated) |
| `COPYTRADING_FORCE_MARKET_OPEN`    | `False` | `True` = run loops off-hours (testing only)    |
| `COPYTRADING_COPY_MAX_RETRIES`     | `3`     | Transient-failure retries per copy order       |
| `COPYTRADING_ALERT_EMAIL_COOLDOWN` | `900`   | Min seconds between re-emails of one alert     |
| `ALERT_EMAIL_TO`                   | —       | Alert recipients (comma-separated)             |

---

## Quick fixes

| Problem                 | Fix                                                                                   |
| ----------------------- | ------------------------------------------------------------------------------------- |
| `token_expired`         | `kite_login` again, then restart `kite_ticker`                                        |
| F&O qty wrong / `lot 1` | `kite_sync_instruments`                                                               |
| Nothing copying         | Check `LIVE_ORDERS`, market hours, and baseline (orders before startup aren't copied) |
| Ticker 403              | Master streaming add-on inactive / token stale — REST poll still copies               |
| No emails               | Set `ALERT_EMAIL_TO` + real `EMAIL_BACKEND`; test with `send_test_email`              |
| Edits not applied       | `docker compose restart celery_worker celery_beat kite_ticker`                        |
