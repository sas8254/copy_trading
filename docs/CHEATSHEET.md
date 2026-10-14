# Copy Trading — Cheat Sheet

One page for daily use. Details: [GUIDE.md](./GUIDE.md) · Server: [DEPLOYMENT.md](./DEPLOYMENT.md)

---

## Every trading morning (before 9:15 AM)

Zerodha logins expire around 6 AM IST.

1. Open the website (dev: **http://localhost:5173**, server: **https://&lt;your-domain&gt;**)
2. **Accounts** → **Login to Zerodha** on each account
3. **Home** → "Ready to trade?" all green ✓

Reminder email at 8:45 AM if you forget. Nothing to restart.
Only master orders placed **after** the master's login are copied.

---

## Where things are

| I want to… | Go to |
| --- | --- |
| **Stop all copying now** | **Settings → Copying → Off** |
| Switch Off / Dry run / Live | Settings → Copying |
| Copy after fill vs mirror the master's orders | Settings → Copy style |
| Instant feed (paid Zerodha add-on) | Settings → Instant copy feed |
| Alert emails / test email | Settings → Alert emails |
| Add / edit an account, change a multiplier | Accounts → Add account / Edit |
| Change the master | Accounts → ⋮ → Make master |
| Pause one account | Accounts → ⋮ → Disable |
| Master vs copy positions, P&L | Positions |
| What was copied, errors | Orders |
| Alerts | Home |

---

## Quantity rule

`copy = master × multiplier`, rounded **down** to whole lots.
Example: lot 75, multiplier 1.5 → master 75 → copy 75; master 150 → copy 225.

---

## Copy styles in one line each

- **When filled:** copy after the master's order fills. Unfilled/cancelled orders never reach copies.
- **Mirror:** copy when placed at the same price; follow modifications and cancels.

Both: after the master's order finishes, the app waits 15 s for the copy, then
buys/sells any shortfall at MARKET (top-up). Extra quantity → alert only.

---

## Alerts → what to do

| Alert | Do this |
| --- | --- |
| Login needed | Accounts → Login to Zerodha |
| Copy order failed (margin etc.) | Fix cause; trade manually if needed |
| "Only X of Y could be copied" | Buy/sell the rest in Zerodha |
| "... holds N extra" | Keep or exit the extra in Zerodha |
| Position mismatch | Check Positions; fix in Zerodha (clears itself when matched) |
| Zero quantity skipped | Raise the multiplier or set "Round up to 1 lot" |
| Instant copy feed refused (403) | Turn the feed off (no add-on); copying still works |

---

## Commands (run in `backend/`, or `deploy/` on a server)

```bash
docker compose ps                                                 # status
docker compose up -d                                              # start everything
docker compose down                                               # stop (keeps data)
docker compose logs -f celery_worker                              # watch the copy engine
docker compose logs -f kite_ticker                                # watch the instant feed
docker compose restart web celery_worker celery_beat kite_ticker  # after editing backend code (dev)
docker compose exec web python manage.py test copytrading         # tests (fake Zerodha)
docker compose exec web python manage.py kite_sync_instruments    # re-sync lot sizes
```

Server only: `./start.sh` (start/update), `./stop.sh`, admin via
`ssh -L 8000:127.0.0.1:8000 you@server` → http://localhost:8000/admin/

---

## Quick fixes

| Problem | Fix |
| --- | --- |
| Nothing copying | Mode (Settings), market hours (9:15–15:30 IST Mon–Fri), master logged in, order placed after login |
| "Copy engine running" red | `docker compose up -d`; check `docker compose logs celery_worker` |
| Logged in as the wrong Zerodha user | Log out at kite.zerodha.com (or private window), log in again |
| Zerodha login lands on an error page | Kite app Redirect URL = `<website>/kite/callback` |
| F&O quantity uses `lot 1` | Wait a minute after the master's login, or `kite_sync_instruments` |
| No emails | Settings → alert emails → **Send test email** (error explains); `EMAIL_*` in `.env` |
| "Too many attempts" on login | Wait one minute |
