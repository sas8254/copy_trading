# Copy Trading — Complete Guide

What this project is, how the pieces fit together, how to use it, and what each
setting does.

> Daily steps on one page: [CHEATSHEET.md](./CHEATSHEET.md).
> Design history: [../PLAN.md](../PLAN.md).

---

## 1. What this project does

It **automatically copies trades** from one Zerodha account (the **master**)
to one or more other Zerodha accounts (the **copies**). Each copy account has its
own **multiplier**. Every 2 seconds the app also **compares positions** and alerts
you if a copy account drifts out of sync.

- An order fills in the master account.
- Within about 2 seconds (or almost instantly via the live feed), the app places the
  same order on each copy account, with quantity `master_qty × multiplier`
  rounded down to whole F&O lots.
- A separate watchdog compares open positions. If a copy doesn't match what the
  multiplier says it should, you get an **alert** (on the website and by email).

Everything is done from the website: accounts, the daily Zerodha login, switching the
master, positions, orders, the live/dry-run switch and alert emails.

---

## 2. The big picture (architecture)

| Container | What it is | Why it exists |
|---|---|---|
| `db` | PostgreSQL | Stores accounts, settings, trades, copy orders, alerts, lot sizes |
| `redis` | Redis | Message queue for Celery **and** the channel layer for live updates |
| `web` | Django served by **Daphne** | REST API, admin, and live-update WebSockets |
| `celery_worker` | Celery worker | Places copy orders, runs retries, syncs lot sizes |
| `celery_beat` | Celery scheduler | Every 2s: poll master orders + reconcile positions. Weekdays 9:00: sync lot sizes |
| `kite_ticker` | Long-running process | Live WebSocket to Zerodha for instant order detection |
| frontend | Vue + Vuetify (Vite) | The website (separate compose stack on :5173) |

The worker and the ticker re-read accounts and settings from the database, so a
login, a master switch or a mode change from the website takes effect without restarts.

---

## 3. The data model

| Model | Meaning |
|---|---|
| **BrokerAccount** | A Zerodha login. `role` = **master** (only one at a time) or **copy**. Holds the Kite API key, the API secret and the daily access token (both **encrypted** in the DB), plus the copy settings `multiplier` and `zero_qty_policy`. |
| **AppSettings** | Single row: the copy **mode** (`off` / `dry_run` / `live`) and the alert email recipients. |
| **Trade** | A filled order seen on the master (deduped by Zerodha order ID). |
| **CopyOrder** | The attempt to copy one Trade to one copy account: status, attempts, error, Zerodha order ID. |
| **Instrument** | Cached lot sizes for F&O contracts (NFO + BFO), used for lot rounding. |
| **Alert** | Something needing attention: mismatch, failed order, zero-qty skip, login needed. Deduped, and emails are rate-limited. |

---

## 4. The lifecycle of one copy trade

Every 2 seconds (during market hours) one **pass** of the copy engine
(`services/sync.py`) runs:

```
1. Read the master's orders from Zerodha (or right away, if the instant feed is on)
        │
        ▼
2. New order after the baseline? → create a Trade
        - "When filled": once the order has filled (or was cancelled after a part-fill)
        - "Mirror": as soon as it is OPEN / TRIGGER PENDING
   Existing order? → update its price / qty / status / filled qty
        │
        ▼
3. Place the copy on each enabled copy account
        qty = round_down_to_lot(master_qty × multiplier), zero-qty policy applies
        - When filled: LIMIT at the master's average fill price; MARKET/SL/SL-M → MARKET
        - Mirror: same type, limit price and trigger as the master
        - Dry run → "simulated", never sent to Zerodha
        │
        ▼
4. Mirror only, while the master's order is open:
        master modified → modify the copy;  master cancelled → cancel the copy
        │
        ▼
5. Final check, once the master's order is done:
        copy still open  → wait the grace period (15s), then cancel the rest
        copy filled less → buy/sell the gap at MARKET ("top-up")
        copy filled more → alert (never auto-exited)
        copy rejected    → alert
```

Meanwhile, every 2s (live mode only), **reconcile** compares master vs copy net
positions × multiplier. Symbols with orders still in progress are skipped
until their final check is done.

**The baseline.** The master's `copy_orders_since` is set to "now" whenever an
account becomes master, logs in to Zerodha, or copying is turned back on after
being off. Orders before that are never copied, so nothing is replayed late.

**Self-healing.** Each pass works from the current state of both accounts, so
if a step fails (network blip), the next pass simply tries again. Passes never
overlap (a database lock), and every copy is recorded once per trade, account and kind.

### When filled vs Mirror

| | When filled (default) | Mirror |
|---|---|---|
| Copy placed | After the master's order fills | As soon as the master's order is open |
| Copy's price | Master's fill price (LIMIT) or MARKET | Same limit price / trigger as the master |
| Master modifies | n/a | Copy modified the same way |
| Master cancels | Nothing to do (unless part-filled) | Copy cancelled |
| Best for | Simplicity | Same entry price, working stop-losses |
| Risk | Slightly worse price in fast markets | Copy can fill when the master doesn't → alert |

## 5. First-time setup

### Prerequisites
- Docker Desktop running.
- A **Kite Connect** app for each Zerodha account (developers.kite.trade). Each
  app gives an API key and an API secret.
- The **streaming add-on** on the master's app for the instant path (copy
  accounts don't need it; without it, copying falls back to 2s polling).

### Steps
1. **Start everything** (see the main README): `backend/start.sh` and `frontend/start.sh`.
2. Open **http://localhost:5173** and sign in with the superuser from
   `backend/.env` (`DJANGO_SUPERUSER_*`).
3. In each Kite Connect app on developers.kite.trade, set the **Redirect URL** to
   `http://localhost:5173/kite/callback`. The Accounts page shows the exact URL.
4. **Accounts → Add account** for the master: name, API key and API secret. The
   first account automatically becomes the master.
5. **Add account** for each copy account, with its multiplier (start with `1`).
6. Click **Login to Zerodha** on each account.
7. **Home** shows a readiness checklist. Fix anything red.
8. Copying starts in **Dry run**. Watch a few simulated copies on **Orders**, then
   switch to **Live** on **Settings**.

---

## 6. Daily use

Zerodha logins expire around 6 AM IST. Each trading morning:

1. Open the website. Home shows "Log in to Zerodha" if any account needs it.
2. On **Accounts**, click **Login to Zerodha** on each account.

That's all. Lot sizes sync automatically after the master logs in, and nothing needs
restarting.

> If you're already logged in to kite.zerodha.com as a different user, Zerodha may
> log you in as that user. Log out there first. If an account has a Zerodha user
> ID set, the app rejects a login as the wrong user.

### Going live (real money)
1. Home's checklist is all green.
2. **Settings → Copying → Live** and confirm.
3. **Start small**: a low multiplier and one cheap instrument.

**Emergency stop:** **Settings → Copying → Off**. This takes effect immediately, even
for copies that are already queued.

---

## 7. Every setting explained

### On the website
| Where | Setting | What it does |
|---|---|---|
| Settings | **Copying** | `Off` = copy nothing. `Dry run` = record simulated copies only. `Live` = real orders. |
| Settings | **Copy style** | *When filled* (copy after the master fills) or *Mirror* (copy when placed, follow changes/cancel). See section 4. |
| Settings | **Instant copy feed** | Off (default) = master orders checked every 2s. On = Zerodha's live WebSocket; needs the paid streaming add-on. |
| Settings | **Alert emails** | Who receives alerts. Use **Send test email** to check SMTP. |
| Accounts | **Make master** | Moves the master role; the old master becomes a copy account. |
| Accounts | **Multiplier** | Copy qty = `master_qty × multiplier`, rounded down to whole lots. |
| Accounts | **If quantity rounds to 0 lots** | Skip + alert (default), skip silently, or round up to 1 lot. |
| Accounts | **Enabled** | Disabled accounts are ignored completely. |
| Accounts | **Zerodha user ID** | Optional. Guards against logging in as the wrong user. |

### `backend/.env` (server-level, rarely changed)
| Setting | What it does |
|---|---|
| `DJANGO_SECRET_KEY` | Crypto key for sessions/CSRF. Secret, unique per environment. |
| `DJANGO_DEBUG` | `True` in dev; `False` in production. |
| `DJANGO_ALLOWED_HOSTS` / `DJANGO_CORS_ALLOWED_ORIGINS` / `DJANGO_CSRF_TRUSTED_ORIGINS` | Which hosts/origins may use the backend. |
| `POSTGRES_*` | Database connection. |
| `DJANGO_SUPERUSER_*` | Website login created by `start.sh`. |
| `REDIS_URL`, `CELERY_*` | Queue / live-update plumbing. `CELERY_TIMEZONE=Asia/Kolkata`. |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | SMTP for alert emails. Gmail needs an **App Password**. Leave `EMAIL_BACKEND` unset to print emails to the logs instead. |
| `FIELD_ENCRYPTION_KEY` | Encrypts API secrets and tokens in the DB. Blank = derived from `DJANGO_SECRET_KEY`. If it changes, re-enter API secrets and log in again. |
| `COPYTRADING_FILL_GRACE_SECONDS` | After the master fills, how long a copy may keep waiting at its own price before the rest is bought at market (default 15). |
| `COPYTRADING_COPY_MAX_RETRIES` | Retries on *transient* failures (default 3). Margin/RMS errors are never retried. |
| `COPYTRADING_ALERT_EMAIL_COOLDOWN` | Minimum seconds between re-emails of the same open alert (default 900). |
| `HEARTBEAT_URL` | Dead-man's switch: pinged about once a minute while the copy engine runs (e.g. a healthchecks.io check), which alerts you if the pings stop. |
| `ENGINE_STALE_SECONDS` | `/api/health/` and Home report the engine as down after this many seconds without a pass (default 60). |
| `LOGIN_RATE_LIMIT` | Website login attempts allowed per IP (default `10/min`). |
| `FRONTEND_URL` | The website's address (Zerodha login redirects that hit the backend are forwarded here). |
| `COPYTRADING_FORCE_MARKET_OPEN` | **Testing only.** Runs the loops outside 9:15–15:30 IST. |

### `frontend/.env`
| Setting | What it does |
|---|---|
| `VITE_API_BASE_URL` | Where the website sends API calls. |
| `VITE_WS_BASE_URL` | Optional live-update WebSocket override; otherwise derived from the API URL. |

---

## 8. Website pages

| Page | What's there |
|---|---|
| **Home** | Copy mode, market open/closed, readiness checklist (incl. "copy engine running"), open alerts, recent orders. Updates live. |
| **Accounts** | Add/edit/disable/delete accounts, Zerodha login, make master. |
| **Positions** | Master's positions with P&L, and for each copy account: master qty → expected → actual, with mismatches highlighted. Auto-refreshes every 10s. |
| **Orders** | Every master order the app saw (status, filled/qty), with each copy's live state: open, filled, part-filled, cancelled, top-up, how often it was modified, and errors. |
| **Settings** | Copy mode and alert emails. |

Django admin (`http://localhost:8000/admin/`) is still available as a backup.

---

## 9. Management commands (optional)

Run with `docker compose exec web python manage.py <command>` from `backend/`.

| Command | Purpose |
|---|---|
| `test copytrading` | Automated tests with a fake broker. No real orders. |
| `kite_login --account X [--request-token T]` | Terminal fallback for the website's Zerodha login. |
| `kite_sync_instruments [--account X] [--exchange NFO]` | Re-sync lot sizes by hand (normally automatic). |
| `kite_ticker` | Live order feed (runs as its own container). |

---

## 10. Safety model

1. **Dry run by default**: nothing trades for real until you choose Live (with a
   confirmation).
2. **Instant off switch**: Off stops even copies that are already queued.
3. **Baseline**: never replays old orders, including after a late login or after
   turning copying back on.
4. **Transient vs terminal errors**: only errors that might succeed are retried; margin
   rejections fail fast and alert you.
5. **Market-hours guard**: the loops idle outside 09:15–15:30 IST.
6. **Reconciliation watchdog**: in live mode, a position check every 2s alerts you
   if anything drifts.
7. **Idempotency**: one copy (plus at most one top-up) per trade and copy account, so nothing fires twice.
   Extra quantity on a copy is never auto-exited; you decide.
8. **Watched from outside**: a heartbeat to a dead-man's switch and `/api/health/`
   catch a stopped engine or server; a weekday 8:45 AM reminder email if any
   account still needs its Zerodha login.
9. **Locked down**: every API call and the live feed need a login; there is no public
   sign-up; broker secrets are encrypted and never sent back to the browser.

---

## 11. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "Login needed" alert | Zerodha login expired. Accounts → Login to Zerodha. |
| Zerodha says the redirect URL doesn't match | Set the Kite app's Redirect URL to the one shown on the Accounts page. |
| Logged in as the wrong Zerodha user | Log out at kite.zerodha.com, then log in again from Accounts. |
| Mismatch shows `lot 1` for an F&O symbol | Lot sizes not synced yet; they sync after the master logs in. Or run `kite_sync_instruments`. |
| No copies happening | Mode is Off or Dry run, the market is closed, or the order filled before the baseline. |
| "Instant copy feed refused (403)" | Streaming add-on inactive on the master's app or a stale token. Copying still works via 2s polling. |
| No alert emails | Add recipients on Settings and set `EMAIL_*` in `backend/.env`; use **Send test email**. |
| Backend code changes not taking effect | Celery doesn't hot-reload: `docker compose restart celery_worker celery_beat kite_ticker`. |
