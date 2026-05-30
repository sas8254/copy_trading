# Copy Trading — Complete Guide

A detailed explanation of what this project is, how every piece fits together,
how to operate it, and what each setting controls.

> Quick daily commands? See [CHEATSHEET.md](./CHEATSHEET.md).
> Design history / decisions? See [../PLAN.md](../PLAN.md).

---

## 1. What this project does

It **automatically mirrors trades** from one Zerodha account (the **master**)
onto one or more other Zerodha accounts (the **copies**), scaled by a per-account
**multiplier**, and it **watches positions every 2 seconds** to email you if a
copy account ever drifts out of sync.

Concretely:

- You place an order on `mom_zerodha` (master).
- Within ~2 seconds (or instantly via the live WebSocket), the system places a
  matching order on `my_zerodha` (copy), with quantity
  `master_qty × multiplier`, rounded to a valid F&O lot.
- A separate watchdog continuously compares the two accounts' open positions. If
  they don't match what the multiplier says they should, it raises an **alert**
  (email + dashboard) so you can intervene.

---

## 2. The big picture (architecture)

The backend runs as **7 Docker containers**:

| Container | What it is | Why it exists |
|---|---|---|
| `db` | PostgreSQL | Stores accounts, trades, copy orders, alerts, instruments |
| `redis` | Redis | Message queue for Celery **and** the channel layer for WebSockets |
| `web` | Django served by **Daphne** | REST API, admin, and **WebSockets** (Daphne is ASGI — gunicorn can't do WebSockets) |
| `celery_worker` | Celery worker | Does the work: places copy orders, runs retries |
| `celery_beat` | Celery scheduler | Fires two jobs every 2s: poll master orders + reconcile positions |
| `kite_ticker` | Long-running process | Holds a live WebSocket to Zerodha for instant order detection |
| (frontend) | Vue/Vite dev server | The browser dashboard (separate compose stack on :5173) |

**Why so many pieces?** A web request can't run forever, but copy trading needs
background loops and long-lived connections:

- **Celery Beat** is the clock (fires tasks on a schedule).
- **Celery Worker** is the muscle (executes tasks + order placement with retries).
- **Redis** is the conveyor belt between them.
- **Daphne + Channels** push live updates to the browser.
- **kite_ticker** keeps one always-on socket to the broker.

---

## 3. The data model

All in the `copytrading` Django app, editable at `/admin/`:

| Model | Meaning |
|---|---|
| **BrokerAccount** | A Zerodha login. `role` = **master** or **copy**, plus `api_key`, `api_secret`, daily `access_token`. |
| **CopyMapping** | "Copy from *this master* to *this copy*, with *this multiplier*." Holds the zero-qty policy. |
| **Trade** | A completed order observed on the master (deduped by broker order id). |
| **CopyOrder** | The attempt to mirror one Trade onto one copy account. Tracks status, attempts, error, broker order id. |
| **Instrument** | Cached lot/tick sizes for F&O contracts, synced from Zerodha. Needed for lot rounding. |
| **PositionSnapshot** | A position recorded when a mismatch is detected (evidence). |
| **Alert** | Something needing attention: mismatch, failed order, zero-qty skip, expired token. Deduped + email-rate-limited. |

---

## 4. The lifecycle of one copy trade

```
1. Order COMPLETES on mom_zerodha
        │
        ├─ (fast path) kite_ticker WebSocket receives an "order" message  ──┐
        └─ (fallback)  celery_beat poll_master_orders runs every 2s        ──┤
                                                                            ▼
2. detect.process_order(): is it new? after the startup baseline?  → create a Trade
        │
        ▼
3. dispatch_trade(): for each active CopyMapping on this master:
        - qty = round_down_to_lot(master_qty × multiplier)
        - if qty == 0 → apply zero-qty policy (skip + alert)
        - create a CopyOrder, enqueue place_copy_order
        │
        ▼
4. place_copy_order():
        - DRY-RUN (default) → record as "simulated", touch nothing
        - LIVE → place real order on my_zerodha, mirroring master's type/price
              - transient failure (network/5xx) → retry with backoff (2,4,8s…)
              - terminal failure (margin/RMS)   → mark "failed" + email alert
              - success → store broker order id, status "placed"

Meanwhile, every 2s independently:
   reconcile(): compare master vs copy net positions × multiplier
        - match    → auto-resolve any open mismatch alert
        - mismatch → raise/refresh an alert (email + dashboard)
```

Two design choices baked in:

- **The startup baseline.** When the system first starts watching a master, it
  records "now" and ignores all pre-existing orders — otherwise it would replay
  your entire order history on boot. So positions already open when you start are
  **not** auto-copied; they show as mismatches for you to handle. Only orders
  placed *after* startup get copied. (Clear `BrokerAccount.copy_orders_since` to
  re-baseline.)
- **Detection and reconciliation are separate.** Detection copies new trades
  fast. Reconciliation is a safety net that catches anything detection missed (a
  missed order, a manual trade on the copy, a partial fill) and alerts you — it
  never places orders itself.

---

## 5. First-time setup

### Prerequisites
- Docker Desktop running.
- A Zerodha **Kite Connect** app (api_key + api_secret from developers.kite.trade).
- The **streaming/WebSocket add-on** activated on the **master** account only
  (paid Kite Connect feature; copy accounts need REST only).

### Steps
1. **Start the stack:**
   ```bash
   cd backend
   docker compose up -d
   ```
2. **Create accounts** at `/admin/copytrading/brokeraccount/`:
   - One role **master** (e.g. `mom_zerodha`) with `api_key` + `api_secret`.
   - One role **copy** (e.g. `my_zerodha`) with its `api_key` + `api_secret`.
3. **Create a CopyMapping** (`/admin/copytrading/copymapping/`): master → copy,
   `multiplier` (start with `1`), and a zero-qty policy.
4. **Log in both accounts:**
   ```bash
   docker compose exec web python manage.py kite_login --account "mom_zerodha"
   # open the URL, log in, copy ?request_token=XXXX from the redirect
   docker compose exec web python manage.py kite_login --account "mom_zerodha" --request-token XXXX
   # repeat for my_zerodha
   ```
5. **Sync lot sizes** (daily, F&O):
   ```bash
   docker compose exec web python manage.py kite_sync_instruments --account "mom_zerodha"
   ```
6. **Check readiness:**
   ```bash
   docker compose exec web python manage.py preflight
   ```
   Fix anything marked `[FAIL]` until it says **GO**.
7. **Watch it live:** `http://localhost:5173/dashboard` (SPA login) or
   `http://localhost:8000/dashboard/`.

It stays in **dry-run** until you flip `COPYTRADING_LIVE_ORDERS=True`.

---

## 6. Daily use

Tokens expire ~6 AM IST. Each trading morning run one of:

```bash
cd backend
bash morning.sh        # macOS/Linux/Git-Bash
```
```powershell
cd backend
.\morning.ps1          # Windows PowerShell
```

These log in both accounts, sync instruments, restart ticker + workers, and run
preflight.

### Going live (real money)
1. `docker compose exec web python manage.py preflight` → must be **GO**.
2. Set `COPYTRADING_LIVE_ORDERS=True` in `backend/.env`.
3. `docker compose up -d && docker compose restart celery_worker`.
4. **Start small** — low multiplier, one cheap instrument.

---

## 7. Every setting explained

### `backend/.env` — Django core
| Setting | What it does |
|---|---|
| `DJANGO_SECRET_KEY` | Crypto key for sessions/CSRF. Secret, unique per env. |
| `DJANGO_DEBUG` | `True` in dev (verbose errors); `False` in production. |
| `DJANGO_ALLOWED_HOSTS` | Hostnames Django will serve (comma-separated). |
| `DJANGO_CORS_ALLOWED_ORIGINS` | Browser origins allowed to call the API. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origins trusted for form/admin POSTs. |
| `POSTGRES_*` | DB name/user/password/host/port. |
| `DJANGO_SUPERUSER_*` | Used by `start.sh` to bootstrap the admin user. |

### Redis / Celery / Channels
| Setting | What it does |
|---|---|
| `REDIS_URL` | Redis location; also the Channels (WebSocket) backend. |
| `CELERY_BROKER_URL` | Queue Celery reads jobs from. |
| `CELERY_RESULT_BACKEND` | Where Celery stores task results. |
| `CELERY_TIMEZONE` | `Asia/Kolkata` — schedules/market logic think in IST. |

### Email (alerts)
| Setting | What it does |
|---|---|
| `EMAIL_BACKEND` | Blank → prints emails to logs (dev). `...smtp.EmailBackend` → real sending. |
| `EMAIL_HOST` / `EMAIL_PORT` | SMTP server, e.g. `smtp.gmail.com` / `587`. |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | SMTP login. Gmail needs an **App Password**. |
| `EMAIL_USE_TLS` | `True` for port 587 (STARTTLS). |
| `DEFAULT_FROM_EMAIL` | "From" address on alert emails. |
| `ALERT_EMAIL_TO` | Comma-separated alert recipients. Empty = no emails. |

### Zerodha
| Setting | What it does |
|---|---|
| `KITE_API_KEY` / `KITE_API_SECRET` | Optional fallback defaults; real creds live per-account in the admin. |

### Copy-trading runtime (the important ones)
| Setting | Default | What it does |
|---|---|---|
| **`COPYTRADING_LIVE_ORDERS`** | `False` | Master safety switch. `False` = dry-run (copies `simulated`, nothing sent). `True` = real orders. |
| **`COPYTRADING_FORCE_MARKET_OPEN`** | `False` | Bypass the IST market-hours guard. `True` for off-hours testing. Keep `False` normally. |
| **`COPYTRADING_COPY_MAX_RETRIES`** | `3` | Retries for a copy order on *transient* failures. Margin/RMS = terminal, never retried. |
| **`COPYTRADING_ALERT_EMAIL_COOLDOWN`** | `900` | Min seconds between re-emailing the same unresolved alert (dashboard still updates every tick). |

### `frontend/.env`
| Setting | What it does |
|---|---|
| `VITE_API_BASE_URL` | Where the SPA sends API calls. |
| `VITE_WS_BASE_URL` | Optional dashboard WebSocket override; else derived from the API URL. |

### Per-account settings (admin, not `.env`)
| Field | What it does |
|---|---|
| **BrokerAccount.role** | `master` (source) or `copy` (receiver). |
| **BrokerAccount.active** | Unchecked → account skipped entirely. |
| **BrokerAccount.copy_orders_since** | Startup baseline; orders before it aren't copied. Clear to re-baseline. |
| **CopyMapping.multiplier** | Copy qty = `master_qty × multiplier`, rounded down to a lot. |
| **CopyMapping.zero_qty_policy** | When rounding gives 0 lots: `skip_alert` (default), `skip_silent`, or `round_up` (force 1 lot). |
| **CopyMapping.active** | Turn one master→copy link on/off. |

---

## 8. Management commands

Run with `docker compose exec web python manage.py <command>`.

| Command | Purpose |
|---|---|
| `kite_login --account X [--request-token T]` | Daily token refresh. |
| `kite_positions --account X` | Print live positions (read-only). |
| `kite_sync_instruments --account X [--exchange NFO]` | Cache lot sizes (daily). |
| `kite_ticker` | Live order feed (runs as its own container). |
| `preflight` | Go-live checklist (GO / NO-GO). |
| `send_test_email [--to ...]` | Verify SMTP. |
| `reconcile_selftest` | Tests mismatch→alert→resolve with fake data (rolled back). |
| `dispatch_selftest` | Tests dispatch (dry-run/live/fail/zero-qty) with fake data. |

---

## 9. The two dashboards

| URL | Auth | Use |
|---|---|---|
| `http://localhost:5173/dashboard` | SPA login | Vue dashboard: accounts, mappings, alerts (resolvable), copy orders, live event log. |
| `http://localhost:8000/dashboard/` | none | Lightweight Django page for a quick glance. |

Both subscribe to the same live feed (`ws/dashboard/`): every reconcile result,
alert, copy order, and ticker event is pushed instantly.

---

## 10. Safety model

1. **Dry-run by default** — nothing trades for real until you flip one flag.
2. **Startup baseline** — never replays history; only new trades copy.
3. **Transient vs terminal errors** — retries only what might succeed; margin
   rejections fail fast and alert you.
4. **Market-hours guard** — loops idle outside 09:15–15:30 IST.
5. **Reconciliation watchdog** — even if copying silently fails, the 2s position
   check emails you to intervene.
6. **Idempotency** — one CopyOrder per (trade, mapping); no double-firing.
7. **preflight** — a deliberate gate before the one irreversible action.

---

## 11. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `token_expired` alerts | Token missing/expired — run `kite_login` (and restart `kite_ticker`). |
| Mismatch shows `lot 1` for an F&O symbol | Instruments not synced — run `kite_sync_instruments`. |
| No copies happening | `COPYTRADING_LIVE_ORDERS=False` (dry-run), or market closed, or the order pre-dates the baseline. |
| Ticker `403 Forbidden` | Streaming add-on not active on the master, token stale, or >3 concurrent sockets. REST poll still works. |
| No alert emails | `ALERT_EMAIL_TO` empty, or `EMAIL_BACKEND` still console. Test with `send_test_email`. |
| Loops hammering Kite on a weekend | `COPYTRADING_FORCE_MARKET_OPEN=True` left on — set it `False`. |
| Code changes not taking effect in workers | Celery doesn't hot-reload: `docker compose restart celery_worker celery_beat kite_ticker`. |
