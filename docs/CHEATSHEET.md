# Copy Trading — Cheat Sheet

One-page daily reference. Full details in [GUIDE.md](./GUIDE.md).

---

## Every trading morning (Zerodha logins expire ~6 AM IST)

1. Open **http://localhost:5173**
2. **Accounts** → click **Login to Zerodha** on each account
3. **Home** → the checklist should be all green

Nothing to restart. Lot sizes sync automatically.

---

## Where things are

| I want to… | Go to |
| --- | --- |
| Turn copying Off / Dry run / Live | **Settings → Copying** |
| Copy after fill vs mirror the master's orders | **Settings → Copy style** |
| Stop everything right now | **Settings → Copying → Off** |
| Add or edit an account, change a multiplier | **Accounts** |
| Change which account is the master | **Accounts → ⋮ → Make master** |
| Check master vs copy positions | **Positions** |
| See what was copied and why something failed | **Orders** |
| Change alert emails / send a test email | **Settings → Alert emails** |

---

## Start / stop the app

Run from `backend/` (and the same in `frontend/` for the website):

```bash
docker compose up -d                                              # start everything
docker compose ps                                                 # status of all containers
docker compose down                                               # stop (keeps data)
docker compose logs -f celery_worker                              # watch the copy/reconcile loop
docker compose logs -f kite_ticker                                # watch the live order feed
docker compose restart celery_worker celery_beat kite_ticker      # only after editing backend code
```

---

## Tests (safe, fake broker, no real orders)

```bash
docker compose exec web python manage.py test copytrading
```

---

## Quick fixes

| Problem | Fix |
| --- | --- |
| "Login needed" alert | Accounts → Login to Zerodha |
| Logged in as the wrong Zerodha user | Log out at kite.zerodha.com, log in again from Accounts |
| Nothing copying | Settings mode, market hours (9:15–15:30 IST), and only orders filled *after* login are copied |
| F&O quantity wrong / `lot 1` | Wait for the lot-size sync after the master logs in, or `docker compose exec web python manage.py kite_sync_instruments` |
| "Instant copy feed refused (403)" | Needs the paid streaming add-on; turn the feed off on Settings (copying works via 2s polling) |
| "holds N extra" alert | Copy filled but the master cancelled; exit the extra in Zerodha if you don't want it |
| "Only X of Y could be copied" | Top-up failed (e.g. margin); fix in Zerodha |
| No emails | Settings → alert emails + `EMAIL_*` in `backend/.env` → **Send test email** |
