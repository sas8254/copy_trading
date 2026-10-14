# Copy Trading — User Guide

Everything you need to **use** the app: what it does, first-time setup, the daily
routine, every page and setting, how copying behaves (with worked examples),
what each alert means, and how to fix common problems.

| Other documents | |
|---|---|
| [CHEATSHEET.md](./CHEATSHEET.md) | The daily steps on one page |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Running it on a server with HTTPS |
| [DEVELOPER.md](./DEVELOPER.md) | Code layout, API, internals, tests |

---

## Contents

1. [What the app does](#1-what-the-app-does)
2. [Words used in this guide](#2-words-used-in-this-guide)
3. [How it works (the big picture)](#3-how-it-works-the-big-picture)
4. [First-time setup](#4-first-time-setup)
5. [The daily routine](#5-the-daily-routine)
6. [The website, page by page](#6-the-website-page-by-page)
7. [Copy modes: Off, Dry run, Live](#7-copy-modes-off-dry-run-live)
8. [Copy styles: When filled vs Mirror](#8-copy-styles-when-filled-vs-mirror)
9. [How quantities are calculated](#9-how-quantities-are-calculated)
10. [The final check, top-ups and extras](#10-the-final-check-top-ups-and-extras)
11. [Alerts: what each one means and what to do](#11-alerts-what-each-one-means-and-what-to-do)
12. [Every setting explained](#12-every-setting-explained)
13. [Safety features](#13-safety-features)
14. [Limitations to know about](#14-limitations-to-know-about)
15. [Troubleshooting](#15-troubleshooting)
16. [FAQ](#16-faq)

---

## 1. What the app does

The app **copies trades from one Zerodha account to others**, automatically.

- One account is the **master**, for example your mom's account. Trades are placed there by
  hand, as usual, in Kite.
- The other accounts are **copy accounts**, for example yours. Whenever the master
  trades, the app places the same trade on every copy account.
- Each copy account has a **multiplier**. With a multiplier of 2, every master trade
  is copied at twice the quantity.
- Every 2 seconds the app also **compares positions** and alerts you
  (website + email) if a copy account no longer matches the master.

**Example.** Your mom buys 1 lot of a NIFTY future in her Kite app. About 2 seconds
later, your account buys 2 lots of the same future. If something goes wrong,
for example your account doesn't have enough margin, you get an email within seconds
saying so.

Everything is controlled from a website: accounts, the daily Zerodha login, choosing
the master, positions, orders, and the on/off switch.

---

## 2. Words used in this guide

| Word | Meaning |
|---|---|
| **Master** | The account whose trades are copied. Exactly one at a time. |
| **Copy account** | An account that receives copies. Any number. |
| **Multiplier** | Copy quantity = master quantity × multiplier (then rounded to whole lots). |
| **Lot / lot size** | F&O contracts trade in fixed blocks, e.g. a lot of 75. Shares (equity) have a lot size of 1. |
| **Kite Connect app** | A developer app on developers.kite.trade. It gives the API key and secret this app uses to trade for an account. One per Zerodha account. |
| **API key / API secret** | The two credentials of a Kite Connect app. |
| **Access token** | A daily pass Zerodha gives after you log in. Expires every morning around 6 AM. |
| **Redirect URL** | Where Zerodha sends you back after logging in. Must point at this app. |
| **Mode** | Off / Dry run / Live: whether copies are placed at all, and whether for real. |
| **Style** | When filled / Mirror: *when* copies are placed. |
| **Trade** | A master order the app has seen. |
| **Copy order** | The order the app placed (or simulated) on a copy account for a trade. |
| **Top-up** | An extra MARKET order that fills whatever the copy order didn't. |
| **Grace period** | How long (default 15 s) a copy may keep waiting at its own price after the master has filled. |
| **Baseline** | The moment from which master orders are copied. Older orders are never copied. |
| **Reconcile** | The 2-second position comparison between master and copies. |

---

## 3. How it works (the big picture)

```
 Mom places an order in Kite
            │
            ▼
 ┌─────────────────────────────┐    every 2 s (or instantly with the paid feed)
 │  Copy engine                │◀── reads the master's orders from Zerodha
 │  - new order?  → copy it    │
 │  - changed?    → follow it  │──▶ places / modifies / cancels orders on each copy account
 │  - finished?   → final check│
 └─────────────────────────────┘
            │
            ▼
 ┌─────────────────────────────┐    every 2 s (Live mode only)
 │  Position check (reconcile) │──▶ master qty × multiplier  vs  copy qty
 └─────────────────────────────┘          mismatch → alert (website + email)
            │
            ▼
       Website (updates live)
```

Behind the scenes these programs run (each in its own Docker container):

| Program | Job |
|---|---|
| **web** | The API behind the website, plus live updates |
| **celery_beat** | The clock: starts the copy engine and position check every 2 s, the 8:45 AM login reminder, the 9:00 AM lot-size sync |
| **celery_worker** | Does the work: talks to Zerodha, places orders |
| **kite_ticker** | Optional instant feed from Zerodha (needs a paid add-on; off by default) |
| **db** (PostgreSQL) | Stores accounts, settings, orders, alerts |
| **redis** | Message queue between the programs |
| **frontend** | The website itself |

You never need to restart anything for normal use. Logins, master changes and
setting changes take effect within seconds.

**Market hours.** The engine only works **Monday–Friday, 9:15 AM–3:30 PM IST**.
Outside those hours it idles. (NSE holidays are not known yet; on a holiday it
simply finds nothing to copy.)

---

## 4. First-time setup

You do this once. It takes about 20 minutes.

### 4.1 Start the app

On your computer (development setup), with Docker Desktop running, in Git Bash:

```bash
cd backend && ./start.sh      # database, API, copy engine
cd ../frontend && ./start.sh  # website
```

Open **http://localhost:5173** and sign in with `DJANGO_SUPERUSER_USERNAME` /
`DJANGO_SUPERUSER_PASSWORD` from `backend/.env`.

(For a server, see [DEPLOYMENT.md](./DEPLOYMENT.md). The steps below are the same,
only the website address differs.)

### 4.2 Create a Kite Connect app for each Zerodha account

Every Zerodha account the app trades on (master **and** each copy) needs its own
Kite Connect app, because the API key and secret belong to one Zerodha user.

1. Go to **https://developers.kite.trade** and sign up / log in.
2. **Create new app** → type **Connect** (paid).
3. Fill in:
   - **App name:** anything, e.g. `copytrading-mom`.
   - **Zerodha client ID:** the Zerodha user ID of the account, e.g. `AB1234`.
   - **Redirect URL:** `http://localhost:5173/kite/callback`
     (on a server: `https://<your-domain>/kite/callback`).
   - **Postback URL:** leave empty.
4. Save, then open the app and note the **API key** and **API secret**.

> **Streaming add-on:** only needed if you want the *instant copy feed* (section
> 12). Without it, copying works via 2-second polling.

**Changing the Redirect URL later:** developers.kite.trade → **My apps** → click
the app → edit **Redirect URL** → **Save**. Each app holds one Redirect URL, so
when you move to a server, change it to the server address.

### 4.3 Add the accounts

**Accounts → Add account**:

| Field | Example | Notes |
|---|---|---|
| Name | `Mom Zerodha` | Anything you like |
| Zerodha user ID | `AB1234` | Optional, filled automatically on first login. If set, the app refuses a login as a different Zerodha user. |
| API key | `abcd1234efgh5678` | From the Kite Connect app |
| API secret | `••••••••` | From the Kite Connect app. Stored encrypted, never shown again. Leave blank when editing to keep it. |
| Quantity multiplier | `1` | Copy accounts only. Start with 1. |
| If the quantity rounds down to 0 lots | Skip it and alert me | See section 9 |
| Enabled | on | Disabled accounts are ignored |

**The first account you add becomes the master.** Add the master first, then the
copy accounts. To change the master later: **Accounts → ⋮ → Make master**.

### 4.4 Log in to Zerodha

On each account card click **Login to Zerodha**:

1. You're sent to Zerodha's login page. Log in **as that account's user**.
2. Zerodha sends you back to the app's "Zerodha login" page:
   *"Mom Zerodha is logged in to Zerodha (AB1234)."*
3. Click **Back to accounts**. The card now shows a green ✓ **Logged in**.

> If your browser is already logged in to kite.zerodha.com as someone else,
> Zerodha may log you in as that user. Log out at kite.zerodha.com first, or use a
> private window.

After the **master** logs in, F&O lot sizes are downloaded automatically (takes a
few seconds).

### 4.5 Set up alert emails

1. In `backend/.env`, fill in the `EMAIL_*` block. For Gmail:
   - Turn on 2-Step Verification on the Google account.
   - Create an **App Password** at https://myaccount.google.com/apppasswords
     (16 letters; paste without spaces into `EMAIL_HOST_PASSWORD`).
   - Example:
     ```
     EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
     EMAIL_HOST=smtp.gmail.com
     EMAIL_PORT=587
     EMAIL_HOST_USER=you@gmail.com
     EMAIL_HOST_PASSWORD=abcdefghijklmnop
     EMAIL_USE_TLS=True
     DEFAULT_FROM_EMAIL=you@gmail.com
     ```
   - Apply: `cd backend && docker compose up -d`.
2. **Settings → Alert emails**: enter one or more addresses, comma-separated,
   e.g. `you@gmail.com, partner@gmail.com` → **Save**.
3. Click **Send test email** and check your inbox (and spam folder).

### 4.6 Check the Home page

**Home → Ready to trade?** should be all green:

```
✓ Copy engine running
✓ Master 'Mom Zerodha' logged in to Zerodha today
✓ Copy 'My Zerodha' logged in to Zerodha today
✓ F&O lot sizes synced today
✓ Alert emails configured
```

### 4.7 Try it in Dry run, then go Live

1. Leave **Settings → Copying** on **Dry run** (the default).
2. During market hours, place a small order in the master account.
3. Within a few seconds, **Orders** shows it with a yellow **Simulated** copy and
   the quantity that *would* have been placed.
4. When you're happy: **Settings → Copying → Live** → confirm.
5. Start with **multiplier 1** and **one cheap instrument**.

---

## 5. The daily routine

Zerodha cancels every access token at about **6:00 AM IST** each day. So once per
trading day, before 9:15 AM:

1. Open the website.
2. **Accounts → Login to Zerodha** on each account (Home shows a
   "Log in to Zerodha" button when any account needs it).
3. **Home** checklist all green → done.

At **8:45 AM** on weekdays, if any enabled account still isn't logged in, you get a
reminder alert and email.

**Nothing else is needed.** No restarts, no scripts. Lot sizes refresh by
themselves (9:00 AM, and right after the master logs in).

**Important:** only master orders placed **after** the master's login are copied
(see *Baseline*, section 13). Log in before your mom starts trading.

---

## 6. The website, page by page

### Home
- **Copying**: current mode (Off / Dry run / Live) and whether the market is open.
- **Ready to trade?** checklist (see 4.6). Red = blocks copying, amber = warning.
- **Alerts**: open alerts, newest first. **Dismiss** one, or **Dismiss all**.
- **Recent master orders**: the last 10 master orders and what happened to
  each copy.
- The **Live / Offline** chip shows whether the page is receiving live updates.
  Offline just means you must refresh to see changes.

### Accounts
One card per account, master first.
- ✓ **Logged in to Zerodha (at 08:52:10)** or ⚠ **Needs Zerodha login today**.
- **Login to Zerodha** / **Log in again**.
- **Edit**: name, user ID, API key/secret, multiplier, zero-lot rule, enabled.
  Changing the **API key** or **user ID** logs the account out (log in again).
- **⋮ menu**: **Make master**, **Disable/Enable**, **Delete** (also deletes its
  order history; disable instead if you may need it again).
- The box at the bottom shows the exact **Redirect URL** to use in your Kite apps,
  with a copy button.

### Positions
Live from Zerodha, refreshed every 10 s (switch off **Auto-refresh** to pause).

**Master card:** symbol, product, net quantity, average price, last price, P&L.

**One card per copy account** comparing quantities:

| Symbol | Master | Expected | Actual | | P&L |
|---|---|---|---|---|---|
| NIFTY24OCTFUT | 75 | 150 | 150 | ✓ | 1,240.00 |
| BANKNIFTY24OCT52000CE | 30 | 60 | 30 | ⚠ | −310.50 |

*Expected* = master × multiplier rounded down to whole lots. A ⚠ row means the
copy account doesn't hold what it should, so fix it in Zerodha.

### Orders
Every master order the app has seen, newest first:

| Time | Master order | Filled | Price | Status | Copies |
|---|---|---|---|---|---|
| 10:05:02 | **BUY** NIFTY24OCTFUT · LIMIT NRML · NFO · Mirror | 75/75 | 22,410.00 | Filled | `Filled` My Zerodha · 150 · modified 1× |
| 10:20:40 | **SELL** NIFTY24OCTFUT · MARKET NRML · NFO · When filled | 75/75 | 22,450.50 | Filled | `Cancelled` My Zerodha · 150 / `Top-up Filled` My Zerodha · 150 |

Copy states: **Placing…**, **Open**, **Open 75/150** (partly filled),
**Filled**, **Part-filled 75/150** (cancelled after a partial fill),
**Cancelled**, **Rejected**, **Failed**, **Skipped**, **Simulated** (dry run).
A **Top-up** prefix marks the extra market order from the final check. Errors are
shown in red next to the copy.

### Settings
- **Copying**: Off / Dry run / Live (Live asks for confirmation).
- **Copy style**: When filled / Mirror.
- **Instant copy feed**: on/off.
- **Alert emails**: recipients + **Send test email**.

---

## 7. Copy modes: Off, Dry run, Live

| Mode | What happens when the master trades | Use it when |
|---|---|---|
| **Off** | Nothing is copied. Master orders are still listed on Orders as "Not copied". | Stopping everything, e.g. an emergency or a day you don't want to copy |
| **Dry run** | The app works out each copy and records it as **Simulated**. Nothing is sent to Zerodha. Position checks are skipped. | Trying the app, testing a new style or multiplier |
| **Live** | Real orders are placed on copy accounts. Position checks run every 2 s. | Normal trading |

Changes take effect **immediately**, even for copies already queued: switching to
Off means a queued copy is skipped instead of placed. Copy orders that are
*already at Zerodha* are left alone. Cancel them in Kite if needed.

**Turning copying back on never copies what happened while it was off.**
Example: Off at 10:00, master buys at 10:30, Live again at 11:00 → the 10:30 buy
is not copied.

---

## 8. Copy styles: When filled vs Mirror

Set on **Settings → Copy style**. A change applies to **new** master orders;
orders already in progress keep their style.

All examples: lot size 75, multiplier 2 → 1 master lot = 2 copy lots (150).

### 8.1 When filled (default)

Wait until the master's order has **actually filled**, then copy it.

**Limit order that fills**
```
10:00:00  Master: BUY 75 @ ₹100 limit                 → nothing yet
10:05:00  Price touches ₹100, master fills            → app sees "COMPLETE"
10:05:02  Copy:   BUY 150 @ ₹100 limit (the master's average fill price)
10:05:03  Copy fills                                  → done ✅
```

**Limit order that never fills**
```
10:00  Master: BUY 75 @ ₹100
11:00  Master cancels (unfilled)                      → nothing ever placed on copies ✅
```

**Price runs away after the master's fill**
```
10:05:00  Master fills at ₹100
10:05:02  Copy: BUY 150 @ ₹100 limit. Price is already ₹101, doesn't fill
10:05:17  Grace period (15 s) over → app cancels it
10:05:19  Top-up: BUY 150 at MARKET → fills ≈ ₹101  ✅ (slightly worse price)
```

**Stop-loss**
```
Master: SL SELL 75, trigger ₹95                       → nothing on copies yet
Price falls to ₹95, master's stop triggers and fills
Copy:   SELL 150 at MARKET                            (stop already happened)
```
⚠ Copy accounts have **no stop-loss of their own** at Zerodha in this style. If
the app is down at that moment, copies are unprotected.

**Market orders** fill instantly, so the copy goes out about 2 s later at MARKET.

**Part fill, then cancel**
```
Master: BUY 150 @ ₹100 → only 75 fill → master cancels the rest
Copy:   BUY 150 (the filled 75 × 2)                   ✅
```

✅ Simple; copies only ever do what really happened on the master.
⚠ About 2 s behind (slightly worse prices in fast markets); stop-losses exist only on the master.

### 8.2 Mirror

Copy the order **the moment it's placed**, at the same price, and keep it in step.

**Limit order that fills**
```
10:00:00  Master: BUY 75 @ ₹100 limit
10:00:02  Copy:   BUY 150 @ ₹100 limit. Both wait at the exchange
10:05:00  Both fill at ₹100                           → same price as the master ✅
```

**Master changes the order**
```
10:00  Master BUY 75 @ ₹100     → Copy BUY 150 @ ₹100
10:10  Master price → ₹98       → Copy price → ₹98
10:20  Master qty → 150         → Copy qty → 300
```

**Master cancels**
```
10:00  Master BUY 75 @ ₹100     → Copy BUY 150 @ ₹100
10:30  Master cancels           → Copy cancelled ✅
```

**Stop-loss**
```
Master: SL SELL 75, trigger ₹95 → Copy: SL SELL 150, trigger ₹95
```
✅ The copy account has **its own real stop-loss** at Zerodha, which protects it even if
the app is down.

**Copy behind** (master filled, copy didn't fully)
```
10:05:00  Price touches ₹100 briefly: master fills 75, copy fills only 75 of 150
10:05:15  Grace over → cancel the copy's remaining 75
10:05:17  Top-up: BUY 75 at MARKET → copy now holds 150 ✅
```

**Copy ahead** (copy filled, master didn't)
```
10:05  Copy fills 150, master's order doesn't fill
10:30  Master cancels
       → copy holds 150 the master doesn't
       → ALERT + email: "... holds 150 extra; exit them in Zerodha if you don't want them."
```
The app **never sells the extra for you**. You decide.

**Not mirrored:** MARKET orders (they fill instantly) and special varieties
(iceberg, cover, AMO). These are copied *when filled*, as in 8.1.

✅ Same entry prices, real stop-losses, changes and cancels followed.
⚠ Occasionally a "copy ahead" alert you must handle yourself.

### 8.3 Side by side

| Situation | When filled | Mirror |
|---|---|---|
| Master places a limit order | Nothing yet | Copied in ~2 s, same price |
| Master modifies it | Nothing | Copy modified |
| Master cancels it (unfilled) | Nothing | Copy cancelled |
| Master's order fills | Copy placed ~2 s later | Usually already filled too |
| Copy's price | Can be slightly worse | Same as master |
| Stop-loss on copy account | Only after it triggers (as MARKET) | Real stop-loss at Zerodha |
| Copy can end up with *more* than master | No | Rarely (alert) |

**Which to choose?** Mostly market orders, or you want the simplest option →
**When filled**. Lots of limit orders and stop-losses → **Mirror**. Try either in
Dry run first.

---

## 9. How quantities are calculated

```
copy quantity = master quantity × multiplier, rounded DOWN to whole lots
```

Rounding is always **down**, so a copy never buys more than the multiplier allows.
Lot sizes come from Zerodha (synced daily). Shares (NSE/BSE equity) have a lot of 1.

| Master qty | Lot size | Multiplier | Raw | Copy qty |
|---|---|---|---|---|
| 75 (1 lot) | 75 | 2 | 150 | **150** (2 lots) |
| 75 | 75 | 1.5 | 112.5 | **75** (1 lot; 1.5 lots rounds down) |
| 150 (2 lots) | 75 | 1.5 | 225 | **225** (3 lots) |
| 75 | 75 | 0.5 | 37.5 | **0** → zero-lot rule applies |
| 10 shares | 1 | 3 | 30 | **30** |
| 7 shares | 1 | 0.5 | 3.5 | **3** |

**Zero-lot rule** (per copy account, "If the quantity rounds down to 0 lots"):

| Option | What happens |
|---|---|
| Skip it and alert me (default) | Copy skipped, alert *"Copy qty rounded to 0..."* |
| Skip it silently | Copy skipped, no alert |
| Round up to 1 lot | 1 lot is placed |

Example: multiplier 0.5, master trades 1 lot → with "Round up" the copy trades
1 lot; master trades 2 lots → copy trades 1 lot either way.

---

## 10. The final check, top-ups and extras

When the master's order is **finished** (filled, cancelled or rejected), the app
compares, for each copy account:

```
target  = master's FILLED quantity × multiplier (rounded to lots)
copied  = what the copy order (+ any top-up) actually filled
```

| Situation | What the app does |
|---|---|
| Copy order still open | Waits up to the **grace period** (15 s, `COPYTRADING_FILL_GRACE_SECONDS`), then cancels the rest |
| `copied < target` | Places a **top-up** MARKET order for the difference (only once) |
| Top-up also falls short | Alert *"Only X of Y ... could be copied"*; fix in Zerodha |
| `copied > target` | Alert *"... holds N extra"*; never auto-exited |
| Copy rejected / failed | Alert with Zerodha's reason; no top-up |
| `copied = target` | Done ✅ |

Example (When filled, master BUY 75 filled, multiplier 2 → target 150):
copy limit fills 100 in 15 s → remaining 50 cancelled → top-up BUY 50 MARKET →
150 ✅. Orders page shows: `Part-filled 100/150` and `Top-up Filled`.

---

## 11. Alerts: what each one means and what to do

Alerts appear on **Home** and are emailed to the addresses on Settings. The same
problem repeating is grouped into one alert (with a "× count"), and is re-emailed
at most every 15 minutes (`COPYTRADING_ALERT_EMAIL_COOLDOWN`).

| Alert (example text) | Meaning | What to do |
|---|---|---|
| **Login needed**: *"Master 'Mom' needs a Zerodha login (Accounts page)."* | Today's token is missing/expired. Nothing is copied from/to that account. | Accounts → Login to Zerodha |
| **Login needed**: *"Log in to Zerodha before the market opens: Mom, Me"* | 8:45 AM reminder | Same |
| **Login needed**: *"Instant copy feed for 'Mom' was refused by Zerodha (403)..."* | Instant feed is on but the streaming add-on is missing/expired | Turn the feed off on Settings, or buy the add-on. Copying still works. |
| **Copy order failed**: *"Copy order FAILED for BUY 150 NIFTY24OCTFUT on 'Me': ...insufficient margin"* | Zerodha refused the copy (margin, RMS, circuit, invalid...) | Fix the cause; place the trade manually if you still want it |
| **Copy order failed**: *"Top-up order FAILED ..."* | The market top-up was refused | Same; check the copy's position |
| **Copy order failed**: *"Only 100 of 150 NIFTY24OCTFUT could be copied to 'Me'."* | Final check couldn't complete the quantity | Buy/sell the rest in Zerodha |
| **Copy order failed**: *"Could not update the copy of ... to match the master's change"* | Mirror: modifying the copy failed | Check the copy's open order in Kite and adjust it |
| **Position mismatch**: *"Position mismatch on NFO:NIFTY24OCTFUT for 'Me': expected 150 ..., actual 75."* | The 2 s position check found a difference (Live only) | Look at Positions; fix in Zerodha. The alert clears itself once they match. |
| **Position mismatch**: *"'Me' got 150 NIFTY24OCTFUT but should have 0 ... It holds 150 extra"* | Mirror "copy ahead" | Decide: keep or exit the extra in Zerodha |
| **Position mismatch**: *"Order poll failed for 'Mom': ..."* / *"Could not fetch positions for ..."* | Zerodha didn't answer (network, Zerodha outage) | Usually clears by itself; if it persists, check internet / Zerodha status |
| **Zero quantity skipped**: *"Copy qty rounded to 0 for ... (master 75 x0.5, lot 75)"* | Multiplier too small for one lot | Raise the multiplier, or set the zero-lot rule |

**Common reasons positions differ** (mismatch alerts): you traded manually in a
copy account; a copy failed; positions were already open before the app started
(they are never copied); a "copy ahead" in Mirror mode.

---

## 12. Every setting explained

### 12.1 On the website

| Where | Setting | Values / default | What it does |
|---|---|---|---|
| Settings | Copying | Off / **Dry run** / Live | Section 7 |
| Settings | Copy style | **When filled** / Mirror | Section 8 |
| Settings | Instant copy feed | **Off** / On | On = Zerodha's live order stream instead of 2 s polling. Needs the paid Kite Connect **streaming add-on** on the master's app. |
| Settings | Alert emails | comma-separated | Who receives alerts |
| Accounts | Make master | — | Moves the master role; the old master becomes a copy |
| Accounts | Multiplier | 1 | Section 9 |
| Accounts | If the quantity rounds down to 0 lots | Skip and alert | Section 9 |
| Accounts | Enabled | on | Disabled accounts are ignored completely |
| Accounts | Zerodha user ID | blank | Guards against logging in as the wrong user |

### 12.2 `backend/.env` (development) and `deploy/.env` (server)

Changes need `docker compose up -d` in that folder to take effect.

| Setting | Example | What it does |
|---|---|---|
| `DJANGO_SECRET_KEY` | long random string | Django's signing key. Secret; different per environment. |
| `DJANGO_DEBUG` | `True` (dev) / `False` (server) | Debug error pages. **Never `True` on a server.** |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host names the backend answers to |
| `DJANGO_CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Website origins allowed to call the API (dev) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://trade.example.com` | Trusted origins for form posts |
| `FRONTEND_URL` | `http://localhost:5173` | Website address; Zerodha redirects reaching the backend are forwarded here |
| `POSTGRES_*` | `core` / password | Database name, user, password, host, port |
| `DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD` | `admin` | Website login created by `start.sh` if missing |
| `REDIS_URL`, `CELERY_*` | `redis://redis:6379/0` | Internal plumbing; `CELERY_TIMEZONE=Asia/Kolkata` |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | see 4.5 | Sending alert emails. Without `EMAIL_BACKEND`, emails are only printed to the logs. |
| `FIELD_ENCRYPTION_KEY` | 44-char base64 | Encrypts API secrets and tokens in the database. **Never change or lose it**, or you must re-enter every API secret and log in again. |
| `COPYTRADING_FILL_GRACE_SECONDS` | `15` | Section 10 |
| `COPYTRADING_COPY_MAX_RETRIES` | `3` | Retries for temporary errors (network, Zerodha 5xx). Margin/RMS errors are never retried. |
| `COPYTRADING_ALERT_EMAIL_COOLDOWN` | `900` | Seconds before the same open alert is emailed again |
| `HEARTBEAT_URL` | `https://hc-ping.com/<uuid>` | Pinged once a minute while the engine runs; an outside service alerts you if pings stop (see DEPLOYMENT.md) |
| `ENGINE_STALE_SECONDS` | `60` | After this many seconds without an engine pass, Home and `/api/health/` say the engine is down |
| `LOGIN_RATE_LIMIT` | `10/min` | Website login attempts per IP |
| `COPYTRADING_FORCE_MARKET_OPEN` | `False` | **Testing only**: run the engine outside market hours |

Server-only (`deploy/.env`): `SITE_ADDRESS`, see [DEPLOYMENT.md](./DEPLOYMENT.md).

### 12.3 `frontend/.env` (development)

| Setting | Example | What it does |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | Where the website sends API calls |
| `VITE_WS_BASE_URL` | `ws://localhost:8000` | Optional; live-update address (normally derived automatically) |

---

## 13. Safety features

1. **Dry run by default.** Real orders only after you choose Live and confirm.
2. **Instant Off.** Stops copying immediately, including copies already queued.
3. **Baseline (no late copies).** Only master orders placed after the master's
   latest login / becoming master / copying turned back on are copied. A late login
   never copies old orders at today's prices.
4. **Never twice.** Each master order produces at most one copy order (plus at
   most one top-up) per copy account, even if the engine retries or runs twice.
5. **Smart retries.** Temporary errors are retried (up to 3×); permanent ones
   (margin, RMS) fail immediately with an alert.
6. **Final check + 2 s position check.** Differences are fixed (top-up) or reported.
7. **Extras are never sold automatically.** You decide.
8. **Market-hours guard.** Nothing runs outside 9:15–15:30 IST, Mon–Fri.
9. **Health monitoring.** "Copy engine running" on Home, `/api/health/`, optional
   external heartbeat, 8:45 AM login reminder.
10. **Locked down.** Every page and API call needs a login; no public sign-up;
    login attempts limited (10/min); API secrets encrypted and never sent to the
    browser; on a server: HTTPS, admin not public.

---

## 14. Limitations to know about

| Limitation | Effect / workaround |
|---|---|
| Daily manual Zerodha login | Required by Zerodha. If missed, nothing is copied that day (reminder at 8:45). |
| ~2 s delay (without the paid feed) | Prices can differ slightly in fast markets. Mirror avoids this for limit orders. |
| NSE holidays unknown | Harmless: the engine polls but finds nothing. |
| MCX / evening sessions not supported | Only 9:15–15:30 IST is watched. |
| Existing positions are not copied | Only new orders after the baseline. Open matching positions manually. |
| One master at a time | By design. |
| No automatic database backups yet | Order history/settings would be lost with the server's disk; no money at risk. |
| Real-order behaviour of top-ups (Zerodha's market-protection rules for API market orders) not yet verified | Start live with a small multiplier; a refused top-up raises an alert. |

---

## 15. Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| "Page not found" at `localhost:8000/?...request_token=...` after Zerodha login | Very old Redirect URL / backend not restarted | The backend now forwards it; update the Kite app's Redirect URL to `.../kite/callback` and log in again |
| Zerodha says the redirect URL doesn't match / login loops | Wrong Redirect URL in the Kite app | Set it to the URL shown at the bottom of Accounts (section 4.2) |
| "You logged in as XY9999, but this account is AB1234" | Browser logged in to Kite as someone else | Log out at kite.zerodha.com (or use a private window), log in again |
| "Kite login failed: Token is invalid or has expired" | The login link is single-use and expires in minutes | Click **Login to Zerodha** again |
| Nothing is copied | Mode Off/Dry run; market closed; master not logged in; order placed before the baseline; copy account disabled | Check Home's checklist and Settings |
| "Copy engine running" is red | Worker or scheduler stopped | `cd backend && docker compose ps`, then `docker compose up -d`; see logs: `docker compose logs --tail 100 celery_worker` |
| F&O copy quantity looks like `lot 1` | Lot sizes not synced yet | Wait a minute after the master logs in, or run `docker compose exec web python manage.py kite_sync_instruments` |
| No alert emails | No recipients, or `EMAIL_*` not set | Settings → alert emails → **Send test email**; the error message says what's wrong |
| "Sending failed: ... Username and Password not accepted" | Using your Gmail password instead of an App Password | Create an App Password (4.5) |
| Website shows "Offline" | Live updates disconnected | Harmless; refresh the page. Check `web` is running. |
| Website login says "Too many attempts" | More than 10 attempts in a minute from your IP | Wait a minute |
| Positions page: "Not logged in to Zerodha" | That account's token is missing | Log in from Accounts |
| Changed backend code isn't used | Celery doesn't reload code | `docker compose restart web celery_worker celery_beat kite_ticker` |

**Where are the logs?** In `backend/` (or `deploy/` on a server):
```bash
docker compose logs -f celery_worker    # the copy engine: every pass, every order
docker compose logs -f web              # API / website requests
docker compose logs -f kite_ticker      # instant feed
```

---

## 16. FAQ

**Do I have to keep the website open?** No. Copying runs on the backend. The
website is only for watching and controlling.

**Does my computer have to stay on?** In the development setup, yes: Docker
must be running. To avoid that, deploy to a server (DEPLOYMENT.md).

**Can I trade manually in a copy account?** Yes, but the position check will
report a mismatch for that symbol in Live mode (expected vs actual). Dismiss it
or close the manual position.

**What if the master exits a position?** That's just another order (a SELL),
copied like any other.

**What if I change the multiplier during the day?** New copies use the new
multiplier. Existing positions are not adjusted, so the position check may report a
mismatch until you fix them manually.

**What if I switch the master during the day?** Only the new master's orders
placed from that moment on are copied. Existing positions aren't touched.

**Can the login be automated?** Technically yes, but Zerodha requires the daily
login to be done by the account holder, and it would mean storing passwords and
2FA secrets on the server. Not supported.

**Can I use it for MCX / commodities?** Not yet; only 9:15–15:30 IST is watched.

**Is my API secret safe?** It's encrypted in the database with
`FIELD_ENCRYPTION_KEY` and never sent to the browser. Keep `.env` files private.
