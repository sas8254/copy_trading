# Copy Trading — Developer Guide

How the code is organised, how the copy engine works internally, the data model,
the REST/WebSocket API (with examples), tests, and how to extend it.

> Using the app: [GUIDE.md](./GUIDE.md) · Server: [DEPLOYMENT.md](./DEPLOYMENT.md)

---

## Contents

1. [Tech stack](#1-tech-stack)
2. [Running in development](#2-running-in-development)
3. [Repository layout](#3-repository-layout)
4. [Backend modules](#4-backend-modules)
5. [Data model](#5-data-model)
6. [The copy engine in detail](#6-the-copy-engine-in-detail)
7. [Scheduled and background tasks](#7-scheduled-and-background-tasks)
8. [Broker adapter](#8-broker-adapter)
9. [REST API reference (with examples)](#9-rest-api-reference-with-examples)
10. [Live events (WebSocket)](#10-live-events-websocket)
11. [Frontend](#11-frontend)
12. [Security implementation](#12-security-implementation)
13. [Tests](#13-tests)
14. [Management commands](#14-management-commands)
15. [Common development tasks](#15-common-development-tasks)
16. [Design decisions](#16-design-decisions)

---

## 1. Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, Django 6, Django REST Framework, django-rest-knox (token auth), psycopg 3 |
| Async / realtime | Celery 5 + Celery Beat, Redis 7, Django Channels 4 + channels-redis, Daphne (ASGI) |
| Broker | Zerodha Kite Connect (`kiteconnect` REST client, installed `--no-deps`), `websocket-client` for the ticker |
| Crypto | `cryptography` (Fernet) for encrypted fields |
| Database | PostgreSQL 16 |
| Frontend | Vue 3, Vite, Vue Router, Pinia, axios, Vuetify 4, Material Design Icons |
| Prod web server | Caddy 2 (automatic HTTPS) |
| Containers | Docker / Docker Compose; backend image on Ubuntu 24.04 |

---

## 2. Running in development

```bash
cp backend/.env.example backend/.env      # set DJANGO_SECRET_KEY etc.
cp frontend/.env.example frontend/.env

cd backend && ./start.sh                  # db, redis, web, celery_worker, celery_beat, kite_ticker
cd ../frontend && ./start.sh              # Vite dev server
```

| URL | What |
|---|---|
| http://localhost:5173 | Website (hot reload) |
| http://localhost:8000/api/ | API |
| http://localhost:8000/admin/ | Django admin |
| ws://localhost:8000/ws/dashboard/?token=... | Live events |

The backend code is bind-mounted into the containers. **Daphne (`web`) and Celery
don't auto-reload**: after backend changes run
`docker compose restart web celery_worker celery_beat kite_ticker`.

Postgres (5432) and Redis (6379) are published on `127.0.0.1` only.

Useful:
```bash
docker compose exec web python manage.py shell
docker compose exec web python manage.py test copytrading
docker compose exec db psql -U core -d core
docker compose logs -f celery_worker
```

To run the engine outside market hours, set `COPYTRADING_FORCE_MARKET_OPEN=True`
in `backend/.env` and `docker compose up -d`. **Set it back afterwards.**

---

## 3. Repository layout

```
copy_trading/
├── backend/
│   ├── core/                     Django project: settings, urls, asgi (HTTP + WS), celery app
│   ├── accounts/                 Website login: login (rate-limited), logout, me, health
│   ├── copytrading/
│   │   ├── models.py             Data model (section 5)
│   │   ├── fields.py             EncryptedTextField (Fernet)
│   │   ├── market.py             Market hours, 6 AM token-reset helper
│   │   ├── instruments.py        Lot-size lookup + round_to_lot
│   │   ├── heartbeat.py          Engine liveness (Redis timestamp) + external ping
│   │   ├── services/
│   │   │   ├── sync.py           THE COPY ENGINE: ingest master orders, follow, settle
│   │   │   ├── dispatch.py       Create/place copy orders, quantity rules, order params
│   │   │   ├── reconcile.py      2 s position comparison → mismatch alerts
│   │   │   ├── positions.py      Fetch + compare positions (shared by API and reconcile)
│   │   │   ├── accounts.py       Make master, Zerodha login, instrument sync
│   │   │   └── alerts.py         raise_alert (dedupe + email cooldown), broadcast, test email
│   │   ├── brokers/
│   │   │   ├── base.py           BrokerClient interface, OrderRequest, Position, BrokerError
│   │   │   ├── zerodha.py        Kite Connect implementation + error classification
│   │   │   └── factory.py        get_client(account)
│   │   ├── tasks.py              Celery tasks (section 7)
│   │   ├── api.py, serializers.py, urls.py   REST API
│   │   ├── consumers.py, routing.py          WebSocket live events
│   │   ├── admin.py              Django admin (backup UI)
│   │   ├── management/commands/  kite_login, kite_sync_instruments, kite_ticker
│   │   ├── migrations/
│   │   └── tests.py              52 tests with a stateful fake Zerodha
│   ├── Dockerfile, docker-compose.yml, requirements.txt, start.sh, stop.sh, .env.example
├── frontend/
│   └── src/
│       ├── api/client.js         axios + token header + 401 → /login
│       ├── api/copytrading.js    API functions, error messages, WS URL
│       ├── composables/useLiveEvents.js   WS subscription with reconnect + debounce
│       ├── stores/auth.js        Pinia: token, login/logout
│       ├── router/index.js       Routes + auth guard
│       ├── utils/format.js       Modes, styles, copy-state labels, number/time formatting
│       ├── utils/kite.js         Start Zerodha login, redirect URL, callback account id
│       ├── components/AccountDialog.vue
│       └── views/                Home, Accounts, Positions, Orders, Settings, Login, KiteCallback
├── deploy/                       Production stack (DEPLOYMENT.md)
└── docs/                         GUIDE, DEPLOYMENT, DEVELOPER, CHEATSHEET
```

---

## 4. Backend modules

| Module | Key functions |
|---|---|
| `services/sync.py` | `run_cycle()` (entry point, advisory lock), `ingest_master()`, `ingest_order()`, `refresh_copy_orders()`, `advance()`, `_follow()` (mirror), `settle()` (final check), `_cancel()` |
| `services/dispatch.py` | `copy_accounts()`, `copy_quantity()`, `create_copy_order()`, `dispatch_trade()`, `order_request()`, `place_copy_order()`, `alert_failed()` |
| `services/reconcile.py` | `reconcile()` |
| `services/positions.py` | `master_account()`, `fetch()`, `compare()` |
| `services/accounts.py` | `make_master()`, `reset_baseline()`, `kite_login_url()`, `complete_kite_login()`, `sync_instruments()` |
| `services/alerts.py` | `raise_alert(kind, message, account=, dedup_key=, email=)`, `broadcast(payload)`, `send_test_email()` |
| `market.py` | `is_market_open()`, `last_token_reset()` |
| `instruments.py` | `lot_size_for(symbol, exchange)`, `round_to_lot(qty, lot)` |
| `heartbeat.py` | `beat()`, `seconds_since_last_run()`, `engine_alive()` |

---

## 5. Data model

### `AppSettings` (singleton, pk=1; `AppSettings.load()`)
| Field | Type | Default | Meaning |
|---|---|---|---|
| `mode` | `off` / `dry_run` / `live` | `dry_run` | Global copy mode |
| `copy_style` | `on_fill` / `mirror` | `on_fill` | Applied to new trades |
| `alert_emails` | text | "" | Comma-separated recipients (`alert_email_list` property) |
| `instant_feed` | bool | False | Enables `kite_ticker` |

### `BrokerAccount`
| Field | Notes |
|---|---|
| `label`, `broker` (`zerodha`), `role` (`master`/`copy`) | **At most one master** (partial unique constraint `single_master`) |
| `client_id` | Zerodha user ID; guards wrong-user logins |
| `api_key`, `api_secret` (encrypted), `access_token` (encrypted), `token_updated_at` | `token_valid` = token obtained after the latest 6 AM IST |
| `active` | Disabled = ignored |
| `multiplier` (Decimal), `zero_qty_policy` (`skip_alert`/`skip_silent`/`round_up`) | Copy settings |
| `copy_orders_since` | Master baseline |

### `Trade` (a master order)
| Field | Notes |
|---|---|
| `account`, `broker_order_id` | Unique together (when non-empty) |
| `tradingsymbol`, `exchange`, `instrument_token`, `side`, `product`, `order_type`, `variety` | |
| `quantity`, `filled_quantity`, `price` (limit), `average_price`, `trigger_price`, `status` | Updated every pass |
| `copy_style` | Frozen at creation |
| `placed_at`, `observed_at`, `completed_at` | `completed_at` = first seen in a terminal status (grace period starts here) |
| `finalized` | True once every copy account has been settled |

### `CopyOrder`
| Field | Notes |
|---|---|
| `trade`, `account`, `kind` (`copy`/`topup`) | Unique together → at most one main copy + one top-up per account |
| `computed_quantity`, `status` (`pending`/`placed`/`failed`/`skipped`/`simulated`), `is_dry_run`, `attempts` | Our view |
| `broker_order_id`, `broker_status`, `filled_quantity` | Zerodha's view, refreshed each pass |
| `placed_quantity`, `placed_price`, `placed_trigger_price`, `placed_order_type`, `modifications` | What was last sent (mirror diffing) |
| `cancel_requested_at` | Throttles cancel retries (10 s) |
| `error_code`, `error_kind` (`transient`/`terminal`), `error_message` | |

### `Instrument`
Lot/tick size per `(broker, exchange, tradingsymbol)`; NFO + BFO synced daily.

### `Alert`
`kind` (`mismatch`, `order_failed`, `zero_qty`, `token_expired`), `account`,
`message`, `dedup_key`, `count`, `resolved`, `emailed_at`, timestamps. An open
alert with the same `(kind, dedup_key)` is updated (count+1) instead of
duplicated; email at most every `COPYTRADING_ALERT_EMAIL_COOLDOWN` s.

---

## 6. The copy engine in detail

`tasks.poll_master_orders` (every 2 s) → `heartbeat.beat()` → `sync.run_cycle()`:

```
run_cycle()
 ├─ market closed?            → return {"skipped": "market_closed"}
 ├─ pg_try_advisory_lock      → busy? return {"skipped": "previous_pass_running"}
 └─ _cycle()
     ├─ finalize trades older than today's 6 AM reset
     ├─ ingest_master(master)              (GET master orders once)
     │    ├─ first run: set baseline, return
     │    └─ ingest_order(o) for each order:
     │         ├─ before baseline → ignore
     │         ├─ existing Trade → _update_trade (qty/price/status/filled)
     │         └─ new: style = settings.copy_style (ON_FILL for non-"regular" variety)
     │              wanted? on_fill: terminal & filled>0 ; mirror: open, or terminal & filled>0
     │              create Trade; mode OFF → finalized (record only)
     │              on_fill            → dispatch_trade(filled_quantity)
     │              mirror & open      → dispatch_trade(quantity)
     ├─ refresh_copy_orders(trades)        (GET orders once per copy account)
     │    update broker_status / filled; REJECTED → alert
     └─ advance(trade) for each unfinalized trade:
          ├─ mode OFF          → finalize
          ├─ mirror & open     → _follow(): create missing copy; diff (qty,type,price,trigger)
          │                       vs placed_* → modify_order (or record, in dry run)
          └─ terminal / on_fill→ settle() per copy account; all done → finalized
```

`settle(trade, account)` (live):

```
target = copy_quantity(trade.filled_quantity)
main pending                        → wait
main open at broker:
    master COMPLETE and < grace     → wait
    else                            → cancel (retry every 10 s), wait
top-up pending/open                 → wait
any failed / rejected               → done (already alerted)
gap = target - (main.filled + top.filled)
gap > 0, no top-up yet              → create top-up (MARKET), wait
gap > 0, top-up done                → alert "Only X of Y"
gap < 0                             → alert "holds N extra" (never auto-exit)
                                    → done
```

In dry run, `settle` only creates a simulated top-up for mirror orders first seen
already filled; nothing touches the broker.

**Order parameters** (`dispatch.order_request`):

| Kind / style | order_type | price | trigger |
|---|---|---|---|
| top-up | MARKET | — | — |
| mirror main | master's | master's limit | master's trigger |
| on_fill main, LIMIT | LIMIT | master's **average** fill price | — |
| on_fill main, MARKET/SL/SL-M | MARKET | — | — |

All copies carry `tag="copytrade"` and the master's `product` and `variety`.

**Placement** (`place_copy_order`, Celery task with retries): re-reads mode (Off →
skipped; dry run → simulated), skips a mirror copy whose master was already
cancelled/rejected, places, records `placed_*`. Transient `BrokerError` →
Celery retry with exponential backoff (2, 4, 8 … s, max
`COPYTRADING_COPY_MAX_RETRIES`); terminal → `failed` + alert.

**Reconcile** (`reconcile.reconcile`, every 2 s, live only): compares net
positions via `positions.compare`, skipping symbols that have unfinalized
trades; mismatch → alert (dedup per account+symbol), match → auto-resolve.

**Invariants**
- One `Trade` per master order (unique constraint) and one `CopyOrder` per
  `(trade, account, kind)`. Creation uses `get_or_create`, so passes are idempotent.
- Passes never overlap (Postgres advisory lock `74201`).
- Each pass works from the current broker state, so a failed step is retried next pass.
- Baseline resets on: becoming master, master login, mode Off → on.

---

## 7. Scheduled and background tasks

| Task | Schedule | Purpose |
|---|---|---|
| `poll_master_orders` | every 2 s | Heartbeat + copy engine pass |
| `reconcile_positions` | every 2 s | Position check (live + market hours) |
| `login_reminder` | Mon–Fri 08:45 IST | Alert/email if an enabled account isn't logged in |
| `sync_instruments` | Mon–Fri 09:00 IST, and after the master logs in | NFO + BFO lot sizes |
| `place_copy_order` | on demand | Place one copy order (retries) |
| `kite_ticker` (process) | always running | If `instant_feed`: on a Zerodha order event, queue an immediate `poll_master_orders` |

Schedules live in `CELERY_BEAT_SCHEDULE` (`core/settings.py`), timezone
`CELERY_TIMEZONE=Asia/Kolkata`.

---

## 8. Broker adapter

`brokers/base.py` defines the interface every broker implements:

```python
class BrokerClient(ABC):
    def login_url(self, redirect_params: str = "") -> str: ...
    def generate_session(self, request_token: str) -> dict: ...   # {"access_token", "user_id", ...}
    def positions(self) -> list[Position]: ...
    def orders(self) -> list[dict]: ...                            # Kite-shaped order dicts
    def instruments(self, exchange: str) -> list[dict]: ...
    def place_order(self, order: OrderRequest) -> str: ...         # broker order id
    def modify_order(self, order_id, *, variety, quantity, order_type, price, trigger_price): ...
    def cancel_order(self, order_id, *, variety): ...
```

Errors are raised as `BrokerError(message, kind="transient"|"terminal", code="token"|"")`.
`zerodha.py` classifies: Kite `TokenException`, `PermissionException`,
`InputException`, `OrderException` and messages containing margin/RMS/circuit/
invalid/… → **terminal**; everything else (network, 5xx) → **transient**.
`code="token"` means "log in again" and produces *Login needed* alerts.

**Adding a broker:** add a `Broker` choice, implement `BrokerClient` in
`brokers/<name>.py`, return it from `factory.get_client`. The engine expects
order dicts with Kite's keys (`order_id`, `status`, `quantity`,
`filled_quantity`, `price`, `average_price`, `trigger_price`, `order_type`,
`variety`, `transaction_type`, `tradingsymbol`, `exchange`, `product`,
`order_timestamp`), so map the new broker's fields to those.

---

## 9. REST API reference (with examples)

Base: `/api/`. JSON in and out. Everything except `health/` and `auth/login/`
requires `Authorization: Token <token>`. Errors: `{"detail": "..."}` or
`{"field": ["message"]}` with status 400/401/404/429.

### Auth

**`POST /api/auth/login/`** (rate-limited: `LOGIN_RATE_LIMIT`, default 10/min per IP)
```bash
curl -X POST http://localhost:8000/api/auth/login/ \
     -H "Content-Type: application/json" -d '{"username":"admin","password":"..."}'
```
```json
{"expiry": "2026-10-14T20:15:00.000000+05:30", "token": "9f1c0e...e2"}
```
Token lifetime 10 h, extended on each request. 11th attempt in a minute → `429`.

`POST /api/auth/logout/` (this token) · `POST /api/auth/logoutall/` (all tokens) ·
`GET /api/auth/me/` → `{"id":1,"username":"admin","email":"...","first_name":"","last_name":""}`

**`GET /api/health/`** (no auth): `200 {"status":"ok","engine_last_run_seconds_ago":1}`
or `503 {"status":"engine_down","engine_last_run_seconds_ago":null}`.

### Overview (Home page)

**`GET /api/copytrading/overview/`**
```json
{
  "mode": "dry_run",
  "market_open": true,
  "accounts": [ { "...": "same shape as GET accounts/" } ],
  "checks": [
    {"ok": true,  "level": "ok",    "text": "Copy engine running"},
    {"ok": false, "level": "error", "text": "Master 'Mom' logged in to Zerodha today"},
    {"ok": true,  "level": "ok",    "text": "F&O lot sizes synced today"}
  ],
  "alerts": [ { "...": "same shape as GET alerts/" } ],
  "recent_trades": [ { "...": "same shape as GET orders/" } ]
}
```

### Accounts

**`GET /api/copytrading/accounts/`**
```json
[{
  "id": 2, "label": "Mom", "broker": "zerodha", "role": "master", "is_master": true,
  "client_id": "AB1234", "api_key": "abcd1234", "has_api_secret": true,
  "logged_in": true, "token_updated_at": "2026-10-14T08:52:10+05:30",
  "active": true, "multiplier": "1.0000", "zero_qty_policy": "skip_alert"
}]
```
`api_secret` is **write-only** and `access_token` is never exposed.

**`POST /api/copytrading/accounts/`**
```json
{"label": "Me", "api_key": "wxyz", "api_secret": "secret", "multiplier": "2"}
```
→ `201` + account. The first account ever becomes master.

**`PATCH /api/copytrading/accounts/<id>/`**: any subset of
`label, client_id, api_key, api_secret, multiplier, zero_qty_policy, active`.
Blank `api_secret` keeps the old one; changing `api_key` or `client_id` clears the
token. `multiplier` must be > 0.

**`DELETE /api/copytrading/accounts/<id>/`** → `204` (cascades its trades/copies).

**`POST /api/copytrading/accounts/<id>/make-master/`** → account (old master → copy).

**`GET /api/copytrading/accounts/<id>/login-url/`**
```json
{"url": "https://kite.zerodha.com/connect/login?api_key=abcd1234&v=3&redirect_params=account%3D2"}
```
`400 {"detail":"Add the API key and API secret first."}` if credentials are missing.

**`POST /api/copytrading/accounts/<id>/login/`** `{"request_token": "..."}` → account
with `logged_in: true`. `400` with Zerodha's reason, or
`"You logged in as XY9999, but this account is AB1234..."`.

### Positions

**`GET /api/copytrading/positions/`** (live calls to Zerodha)
```json
{
  "master": {"id": 2, "label": "Mom", "error": "", "positions": [
    {"exchange": "NFO", "symbol": "NIFTY24OCTFUT", "product": "NRML", "qty": 75,
     "avg_price": "22410.00", "last_price": "22426.50", "pnl": "1237.50"}
  ]},
  "copies": [{"id": 1, "label": "Me", "multiplier": "2.0000", "error": "", "rows": [
    {"exchange": "NFO", "symbol": "NIFTY24OCTFUT", "lot": 75, "master_qty": 75,
     "expected": 150, "actual": 150, "ok": true, "pnl": "2475.00"}
  ]}]
}
```
`error` is set (e.g. `"Not logged in to Zerodha."`) when an account can't be read.

### Orders

**`GET /api/copytrading/orders/?limit=100`** (max 500)
```json
[{
  "id": 7, "account": "Mom", "tradingsymbol": "NIFTY24OCTFUT", "exchange": "NFO",
  "side": "BUY", "quantity": 75, "filled_quantity": 75, "price": "22410.00",
  "average_price": "22410.00", "trigger_price": null, "order_type": "LIMIT",
  "product": "NRML", "status": "COMPLETE", "copy_style": "mirror", "finalized": true,
  "broker_order_id": "241014000123456", "observed_at": "2026-10-14T10:05:02+05:30",
  "copies": [{
    "id": 11, "account": "Me", "kind": "copy", "computed_quantity": 150,
    "filled_quantity": 150, "status": "placed", "broker_status": "COMPLETE",
    "is_dry_run": false, "attempts": 1, "modifications": 1,
    "broker_order_id": "241014000123999", "error_message": "",
    "created_at": "2026-10-14T10:00:02+05:30"
  }]
}]
```

### Settings

**`GET /api/copytrading/settings/`**
```json
{"mode": "dry_run", "copy_style": "on_fill", "alert_emails": "you@gmail.com",
 "instant_feed": false, "fill_grace_seconds": 15, "updated_at": "..."}
```
**`PATCH /api/copytrading/settings/`**: any of `mode`, `copy_style`,
`alert_emails` (validated), `instant_feed`. Switching from `off` to another mode
resets the master's baseline.
```bash
curl -X PATCH .../api/copytrading/settings/ -H "Authorization: Token $T" \
     -H "Content-Type: application/json" -d '{"mode":"off"}'
```

**`POST /api/copytrading/settings/test-email/`** → `{"sent_to": ["you@gmail.com"]}` or
`400 {"detail": "Sending failed: ..."}`.

### Alerts

`GET /api/copytrading/alerts/?resolved=false|true` (max 200)
```json
[{"id": 5, "kind": "order_failed", "kind_display": "Copy order failed", "account": "Me",
  "message": "Copy order FAILED for BUY 150 NIFTY24OCTFUT on 'Me': ...", "count": 1,
  "resolved": false, "created_at": "...", "last_seen_at": "..."}]
```
`POST /api/copytrading/alerts/<id>/resolve/` · `POST /api/copytrading/alerts/resolve-all/` → `{"resolved": 3}`

### Other routes
| Path | Notes |
|---|---|
| `/kite/callback/`, `/` (backend) | Redirect to `FRONTEND_URL/kite/callback` keeping the query string (old Redirect URLs keep working) |
| `/admin/` | Django admin (dev: open; prod: SSH tunnel only) |

---

## 10. Live events (WebSocket)

Connect to `/ws/dashboard/?token=<knox token>` (browsers can't send headers on
WebSockets). Invalid/missing token → closed with code `4401`. Messages are JSON:

| `type` | Sent when | Example |
|---|---|---|
| `master_order` | Master order created/updated | `{"type":"master_order","symbol":"NIFTY24OCTFUT","status":"OPEN","side":"BUY","qty":75}` |
| `copy_order` | Copy placed/simulated/failed/modified | `{"type":"copy_order","status":"placed","symbol":"...","qty":150,"copy":"Me","broker_order_id":"..."}` |
| `alert` | Alert raised/updated | `{"type":"alert","kind":"mismatch","message":"...","account":"Me","count":2}` |
| `reconcile` | Each live reconcile pass | `{"type":"reconcile","copies":1,"mismatches":0,"errors":0}` |
| `accounts_changed` | Account added/edited/login/master | `{"type":"accounts_changed"}` |
| `settings_changed` | Settings saved | `{"type":"settings_changed","mode":"live"}` |
| `ticker_status`, `ticker_order` | Instant feed connect/disconnect, order event | `{"type":"ticker_status","master":"Mom","connected":true}` |

The website treats events as "something changed" signals and re-fetches over
REST (debounced 800 ms).

Sending from Python: `services.alerts.broadcast({"type": "...", ...})`
(best-effort; never raises).

---

## 11. Frontend

- **Auth:** `stores/auth.js` keeps the Knox token in `localStorage`;
  `api/client.js` adds `Authorization: Token ...` and redirects to `/login` on 401.
  `router/index.js` guards routes with `meta.requiresAuth`.
- **Zerodha login flow:** `utils/kite.js#startKiteLogin` fetches `login-url`
  (with `redirect_params=account=<id>`), remembers the id in `sessionStorage`,
  navigates to Zerodha → Zerodha redirects to `/kite/callback?request_token=...&status=success&account=<id>`
  → `KiteCallbackView` posts the token to `accounts/<id>/login/`.
- **Live updates:** `composables/useLiveEvents.js` (auto-reconnect every 3 s).
- **Display helpers:** `utils/format.js` (`MODES`, `STYLES`, `copyState()`,
  `MASTER_STATUS`, `fmtTime`, `fmtMoney`, `pnlColor`).
- **API base:** `VITE_API_BASE_URL` (dev `http://localhost:8000/api`, prod
  build `/api`). WebSocket URL is derived from it (or `VITE_WS_BASE_URL`).

Build check: `cd frontend && docker compose exec web npx vite build --outDir /tmp/dist`.

---

## 12. Security implementation

| Concern | Implementation |
|---|---|
| Website auth | Knox tokens (hashed in DB), 10 h TTL with auto-refresh; no registration endpoint |
| Brute force | DRF `ScopedRateThrottle` scope `login` = `LOGIN_RATE_LIMIT`; cache in Redis; `NUM_PROXIES=1` in prod so the client IP comes from `X-Forwarded-For` |
| Broker secrets | `EncryptedTextField` (Fernet, `enc:` prefix, key `FIELD_ENCRYPTION_KEY` or derived from `SECRET_KEY`); write-only in the API |
| WebSocket | Token checked on connect |
| Production | `DJANGO_DEBUG` from env (False); `SECURE_PROXY_SSL_HEADER`, secure cookies, nosniff when not DEBUG; Caddy HTTPS + HSTS + headers; `/admin` 404 publicly, admin on `127.0.0.1:8000` only; db/redis unexposed |
| Wrong Zerodha user | `client_id` check on login |

---

## 13. Tests

```bash
cd backend
docker compose exec web python manage.py test copytrading
```

52 tests, no network: `FakeClient` replaces the broker with an in-memory Zerodha
(order books per account, positions, placed/modified/cancelled logs). Copy
orders are placed inline (Celery `.delay` patched), market hours are forced open,
grace period 0, cache in memory.

| Class | Covers |
|---|---|
| `OnFillTests` | dry run, limit at fill price, SL → MARKET, partial fill + cancel, grace + top-up, Off, disabled account, failures, rejection, zero-qty, baseline |
| `MirrorTests` | copy on open, SL trigger kept, modify, cancel, copy behind/ahead, already-filled, dry run, turning off, lock |
| `ReconcileTests` | mismatch alert + auto-resolve, skipped unless live |
| `AccountServiceTests` | make master, login, wrong user, encryption at rest |
| `ApiTests` | auth, no registration, secrets hidden, edit rules, login flow, settings, positions, overview |
| `OperationsTests` | health/heartbeat, login rate limit, login reminder |

Writing a test, e.g. a mirror scenario:
```python
class MyTests(CopyTradingTestCase):
    def test_example(self):
        self.set_mode(style=CopyStyle.MIRROR)       # mode is LIVE by default
        self.master_order(status="OPEN", price=100) # fake master order M1, 65 qty
        self.cycle()                                # one engine pass
        self.update_master(status="COMPLETE", filled_quantity=65, average_price=100)
        self.fill_copy("C1", 130)                   # fake Zerodha fills the copy
        self.cycle()
        self.assertTrue(self.trade().finalized)
```

---

## 14. Management commands

`docker compose exec web python manage.py <command>`

| Command | Purpose |
|---|---|
| `test copytrading` | Run the tests |
| `kite_login --account "Mom"` | Print the Zerodha login URL (terminal fallback) |
| `kite_login --account "Mom" --request-token XXXX` | Complete a login with a request token |
| `kite_sync_instruments [--account X] [--exchange NFO --exchange BFO]` | Re-sync lot sizes |
| `kite_ticker` | The instant-feed process (runs as its own container) |
| `createsuperuser` / `changepassword <user>` | Website users |

---

## 15. Common development tasks

**Add a setting editable on the website:** add a field to `AppSettings` →
`makemigrations` → add it to `SettingsSerializer.Meta.fields` → add a control in
`SettingsView.vue` → read it with `AppSettings.load().<field>`.

**Add a server-level setting:** `env(...)` in `core/settings.py`, document it in
`backend/.env.example`, `deploy/.env.example` and GUIDE.md section 12.

**Add a scheduled job:** a `@shared_task` in `tasks.py` + an entry in
`CELERY_BEAT_SCHEDULE`; restart `celery_beat` and `celery_worker`.

**Add an API endpoint:** view in `api.py`, route in `copytrading/urls.py`,
function in `frontend/src/api/copytrading.js`.

**Add a page:** `frontend/src/views/XView.vue`, route in `router/index.js`
(`meta: { requiresAuth: true }`), nav link in `App.vue`.

**Model change:**
```bash
docker compose exec web python manage.py makemigrations copytrading
docker compose exec web python manage.py migrate
```

---

## 16. Design decisions

| Decision | Why |
|---|---|
| Polling every 2 s as the primary path; WebSocket feed optional | Works without the paid streaming add-on; the poll is also the self-healing fallback |
| One engine pass rebuilds decisions from current broker state | Missed events and failed steps are corrected next pass; no fragile event chains |
| Copy settings on the account, one master | Simpler than master→copy mappings; matches how it's used |
| Mode and style in the database | Changed from the website, effective immediately, no restarts |
| Baseline instead of copying history | Never place old trades at today's prices |
| Never auto-exit extra quantity | Selling automatically can cause bigger mistakes than reporting |
| Top-ups at MARKET after a grace period | Keeps positions in sync while giving limit copies a fair chance |
| Caddy for production | Automatic Let's Encrypt with no extra containers |
| `kiteconnect` installed `--no-deps` | Its pinned `autobahn` conflicts with Daphne; only the REST client is used |

Earlier design notes: [../PLAN.md](../PLAN.md) (historical).
