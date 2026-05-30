# Copy Trading — v1 Plan

A Django app that mirrors trades from a **master** brokerage account onto one or
more **copy** accounts, with a per-account quantity multiplier and continuous
position reconciliation.

## v1 Scope (locked)

| Area                  | Decision                                                                 |
| --------------------- | ------------------------------------------------------------------------ |
| Broker                | **Zerodha only** (Kite Connect REST + Kite Ticker WS)                    |
| Segment               | **F&O** — multiplier with lot-size rounding                              |
| Master trade detect   | **Hybrid**: Kite postback/Ticker where available + 2s REST poll fallback |
| Copy quantity         | `master_qty × multiplier`, rounded **down** to nearest lot size          |
| Reconciliation        | **Celery Beat every 2s** — compare master vs each copy position          |
| Copy-order failure    | **Retry N times w/ backoff** (transient only) → then **email alert**     |
| Websockets            | Inbound: Kite Ticker. Outbound: **Django Channels → browser dashboard**  |
| Tenancy               | **Single user**                                                          |
| Build order           | **Infra first** (Redis + Celery + Channels), then models, then broker    |

## Runtime architecture

```
                        ┌─────────────────────────────────────────┐
   Zerodha Kite  ──WS──▶│ ticker process (mgmt cmd / container)     │
   (master acct)        │  - consumes order/tick stream            │
                        └───────────────┬──────────────────────────┘
                                        │ event
                                        ▼
   Zerodha REST ◀──poll── Celery Beat (2s) ── reconcile_positions
        ▲                                        │
        │ place_copy_order (retry+backoff)       │ mismatch → email + Channels alert
        │                                        ▼
   Zerodha (copy accts)          Channels group ──WS──▶ Browser dashboard
```

Containers (docker-compose):
- `db`         — Postgres (existing)
- `redis`      — Celery broker/result backend + Channels layer (new)
- `web`        — Daphne ASGI server (was gunicorn/runserver) (changed)
- `celery_worker` — order dispatch + retries (new)
- `celery_beat`   — 2s reconciliation schedule (new)
- (later) `ticker` — long-running Kite Ticker client (new)

## Data model (next step, not yet built)

- `BrokerAccount` — broker, role (master|copy), api creds ref, access_token, active
- `CopyMapping`   — master FK, copy FK, multiplier, active, qty rounding policy
- `Trade`         — observed master order/trade (symbol, side, qty, price, ts)
- `CopyOrder`     — per copy account: status, attempts, broker_order_id, error
- `PositionSnapshot` — periodic master/copy positions for reconciliation
- `Alert`         — type, message, account, resolved flag, emailed_at

## Broker adapter

`copytrading/brokers/base.py` defines an interface; `zerodha.py` implements:
`place_order`, `cancel_order`, `positions`, `orders`, `ticker_connect`.
Future brokers (Angel One, Tradebulls, Groww) implement the same interface.

## Open questions / risks to resolve before broker step

1. **Order updates source** — Kite Ticker is primarily market ticks; reliable
   order updates come from Kite **postback (HTTPS webhook)**. Plan: postback +
   2s REST poll; Ticker for live LTP on the dashboard.
2. **Daily token expiry** — Zerodha access tokens expire ~6 AM IST. Need a small
   daily login/refresh flow per account.
3. **Margin rejections** — a copy order can be rejected for insufficient margin
   even when master fills. Retry must distinguish **transient** (network/5xx →
   retry) from **terminal** (margin/freeze-qty/RMS → no retry, alert now).
4. **Zero-qty copies** — multiplier × qty can round to 0 lots. Policy: **skip +
   alert** (do not silently drop, do not round up).
5. **Timezone** — Zerodha operates in IST; Celery/Beat scheduling and market-hour
   guards should use `Asia/Kolkata`.

## Status

- [x] Infra: Redis, Celery (worker + beat), Channels/Daphne, ping task, echo WS
      (verified running 2026-05-30; redis pinned to 6.2.7 — local image, Hub CDN
      was truncating large layers; kiteconnect deferred to the Zerodha step)
- [x] Data model + admin (BrokerAccount, CopyMapping, Trade, CopyOrder,
      PositionSnapshot, Alert) — migration 0001 applied 2026-05-30; creds plain
      DB fields for now (encrypt later)
- [x] Zerodha adapter (REST): BrokerClient interface + ZerodhaClient + factory;
      kite_login / kite_positions management commands. kiteconnect 5.2.0 installed
      --no-deps in Dockerfile (its autobahn==19.11.2 pin conflicts with daphne;
      we use REST only, ticker handled separately). Verified in fresh build.
- [x] Dispatcher: order-event detection (poll_master_orders, baseline watermark
      so startup positions aren't replayed) -> dispatch_trade fan-out per mapping
      (lot rounding, zero-qty policy) -> place_copy_order task (mirrors master
      type/price, transient retry w/ backoff, terminal->fail+alert). Global
      COPYTRADING_LIVE_ORDERS dry-run switch (default False). Verified via
      dispatch_selftest (dry-run/live/terminal/zero-qty all pass).
- [x] reconcile_positions (real logic) + email alerts: Instrument lot-size cache
      (kite_sync_instruments) + round_to_lot, IST market-hours guard, reconcile
      service (master vs copy per multiplier), deduped Alerts with email cooldown
      + Channels broadcast, auto-resolve on match. Verified via 2s Beat loop.
- [x] Live ticker: kite_ticker management command + container; one
      websocket-client connection per master to wss://ws.kite.trade, listens for
      order updates -> handle_ticker_order -> instant dispatch (REST poll stays
      as fallback). Backoff + deduped alert on auth failure. NOTE: Kite streaming
      requires the paid WS add-on on the MASTER account only; copy accounts need
      REST only. Verified connected with mom_zerodha streaming enabled.
- [x] Dashboard: DashboardConsumer (ws/dashboard/) sends a state snapshot on
      connect then streams reconcile/alert/copy_order/ticker events; served at
      /dashboard/ (self-contained template, no frontend build). Verified live.
- [x] SPA frontend: DRF overview API (/api/copytrading/overview/, Knox auth) +
      resolve-alert endpoint; Vue/Vuetify DashboardView (accounts, mappings,
      alerts w/ resolve, copy orders, live event log) that fetches overview and
      live-updates over ws/dashboard/. Route + nav added; nginx /ws/ proxy added.
      SPA build verified; dev server live on :5173.
