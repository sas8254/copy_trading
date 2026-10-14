# Copy Trading — Deployment Guide

How to run the app on a server, reachable at `https://<your-domain>`, with
automatic HTTPS (Let's Encrypt), so your computer doesn't need to stay on.

> Using the app: [GUIDE.md](./GUIDE.md) · Code and API: [DEVELOPER.md](./DEVELOPER.md)

---

## Contents

1. [What gets deployed](#1-what-gets-deployed)
2. [What you need](#2-what-you-need)
3. [Step 1: Server](#3-step-1-server)
4. [Step 2: Domain (DNS)](#4-step-2-domain-dns)
5. [Step 3: Get the code onto the server](#5-step-3-get-the-code-onto-the-server)
6. [Step 4: Fill in deploy/.env](#6-step-4-fill-in-deployenv)
7. [Step 5: Start](#7-step-5-start)
8. [Step 6: Kite apps, accounts, emails](#8-step-6-kite-apps-accounts-emails)
9. [Step 7: Monitoring (heartbeat)](#9-step-7-monitoring-heartbeat)
10. [Django admin over an SSH tunnel](#10-django-admin-over-an-ssh-tunnel)
11. [Day-to-day operations](#11-day-to-day-operations)
12. [Updating to a new version](#12-updating-to-a-new-version)
13. [Security checklist](#13-security-checklist)
14. [Alternatives: no domain / Cloudflare Tunnel / local trial](#14-alternatives-no-domain--cloudflare-tunnel--local-trial)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. What gets deployed

Everything lives in `deploy/`:

```
Internet ──443/80──▶ caddy ──┬── /            the website (built Vue files)
   (HTTPS, Let's Encrypt)    ├── /api/*  ──▶ web (Django + Daphne)
                             ├── /ws/*   ──▶ web (live updates)
                             └── /admin  ──▶ 404 (not public)

 web ◀─127.0.0.1:8000─ SSH tunnel (Django admin, for you only)

 celery_beat ──every 2 s──▶ celery_worker ──▶ Zerodha
 kite_ticker (optional instant feed)
 db (PostgreSQL), redis           private: no ports open to the internet
```

| File | Purpose |
|---|---|
| `deploy/docker-compose.yml` | All services |
| `deploy/Caddyfile` | HTTPS, security headers, routing, `/admin` blocked |
| `deploy/Dockerfile` | Builds the website into the Caddy image |
| `deploy/.env.example` | Template for `deploy/.env` (all settings, with comments) |
| `deploy/start.sh` | Checks `.env`, builds, starts, creates the website login |
| `deploy/stop.sh` | Stops everything (data and certificates are kept) |

Differences from the development setup: debug off, code baked into images (no
live reload), the website is pre-built and served by Caddy, HTTPS, Postgres/Redis
not reachable from outside, admin not public, secure cookies.

---

## 2. What you need

| Item | Example / notes |
|---|---|
| A Linux server (VPS) | Ubuntu 22.04/24.04, 1–2 vCPU, **2 GB RAM**, 20 GB disk. Any provider (DigitalOcean, Hetzner, AWS Lightsail, ...). A server in or near India keeps Zerodha calls fast. |
| A domain / subdomain | e.g. `trade.example.com` |
| SSH access | `ssh you@<server-ip>` |
| ~30 minutes | |

---

## 3. Step 1: Server

On the server:

```bash
# Docker + Compose plugin (official convenience script)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # then log out and back in

# Firewall: SSH + web only
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable

# Correct clock matters (orders, logins, certificates)
timedatectl                       # "System clock synchronized: yes"
```

> Docker publishes ports past `ufw`. That's fine here: only Caddy (80/443) is
> published publicly; the admin port is bound to `127.0.0.1` only.

---

## 4. Step 2: Domain (DNS)

At your DNS provider, create an **A record**:

| Type | Name | Value |
|---|---|---|
| A | `trade` (for `trade.example.com`) | your server's public IP, e.g. `203.0.113.10` |

Check it (from anywhere): `nslookup trade.example.com` → shows the server IP.
**Do this before starting**, because Let's Encrypt needs the name to reach the server.

---

## 5. Step 3: Get the code onto the server

```bash
git clone <your-repo-url> copy_trading
cd copy_trading/deploy
```
(Private repo: use a GitHub deploy key or a personal access token.)

---

## 6. Step 4: Fill in `deploy/.env`

```bash
cp .env.example .env
nano .env
```

Generate random values on the server:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"                            # secret key / passwords
python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"  # FIELD_ENCRYPTION_KEY
```

**Example of a filled-in `deploy/.env`** (fake values):

```ini
# ---- Website address ----
SITE_ADDRESS=trade.example.com
DJANGO_ALLOWED_HOSTS=trade.example.com,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://trade.example.com
FRONTEND_URL=https://trade.example.com
DJANGO_CORS_ALLOWED_ORIGINS=

# ---- Django ----
DJANGO_SECRET_KEY=q3V9mZ...50-random-characters...
DJANGO_DEBUG=False

# ---- Database ----
POSTGRES_DB=core
POSTGRES_USER=core
POSTGRES_PASSWORD=Xk29...random...
POSTGRES_HOST=db
POSTGRES_PORT=5432

# ---- Website login ----
DJANGO_SUPERUSER_USERNAME=shashi
DJANGO_SUPERUSER_EMAIL=you@gmail.com
DJANGO_SUPERUSER_PASSWORD=a-long-random-password

# ---- Redis / Celery ----
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
CELERY_TIMEZONE=Asia/Kolkata

# ---- Email ----
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=you@gmail.com
EMAIL_HOST_PASSWORD=abcdefghijklmnop
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=you@gmail.com

# ---- Copy trading ----
FIELD_ENCRYPTION_KEY=Jd8p...44-characters...=
HEARTBEAT_URL=https://hc-ping.com/1f2e3d4c-....
COPYTRADING_FILL_GRACE_SECONDS=15
COPYTRADING_COPY_MAX_RETRIES=3
COPYTRADING_ALERT_EMAIL_COOLDOWN=900
COPYTRADING_FORCE_MARKET_OPEN=False
```

Notes:
- **Use new values**, not the ones from your laptop's `backend/.env`.
- Keep `localhost` in `DJANGO_ALLOWED_HOSTS` (needed for the admin tunnel).
- `DJANGO_DEBUG` must be `False`; `start.sh` warns if it isn't.
- **Back up `deploy/.env` somewhere safe** (password manager). Losing
  `FIELD_ENCRYPTION_KEY` means re-entering every API secret.
- `HEARTBEAT_URL` can be left empty for now and filled in at Step 7.

---

## 7. Step 5: Start

```bash
./start.sh
```

What it does:
1. Refuses to start if `.env` is missing, still has `<placeholder>` values, or
   required values are empty.
2. Builds the images (first time: a few minutes) and starts everything.
3. `migrate` service sets up the database, then `web`, `celery_*`,
   `kite_ticker` and `caddy` start.
4. Creates the website login from `DJANGO_SUPERUSER_*` if it doesn't exist.
5. Caddy obtains the HTTPS certificate from Let's Encrypt (and renews it
   automatically before it expires; certificates are kept in the `caddy_data` volume).

Example output:
```
>> Building and starting...
 ✔ Container core-prod-db-1             Healthy
 ✔ Container core-prod-migrate-1        Exited
 ✔ Container core-prod-web-1            Started
 ...
>> Ensuring the website login exists...
Created login: shashi
>> Up. Website: trade.example.com
   Health:  <website>/api/health/  (503 until the copy engine has run once)
```

Check:
```bash
docker compose ps                                  # all "Up"; migrate "Exited (0)"
curl -s https://trade.example.com/api/health/      # {"status":"ok",...} during/after a pass
```
Open `https://trade.example.com` → padlock in the browser → log in.

> Health is `ok` outside market hours too: the engine runs a (skipped) pass
> every 2 s all day, so `ok` simply means the worker and scheduler are running.

---

## 8. Step 6: Kite apps, accounts, emails

The server has **its own, empty database**. Set it up like the first time
(GUIDE.md section 4), with the server address:

1. **Kite apps:** developers.kite.trade → My apps → each app → **Redirect URL** =
   `https://trade.example.com/kite/callback` → Save.
   (Your laptop setup stops working for login unless you keep a second Kite app for it.)
2. **Accounts:** add master + copies with API key/secret and multipliers.
3. **Login to Zerodha** on each.
4. **Settings:** alert emails → **Send test email**; choose the copy style; leave
   **Dry run** until you've watched a few copies, then **Live**.

---

## 9. Step 7: Monitoring (heartbeat)

If the server or the engine stops, nothing on the server can tell you. An outside
"dead-man's switch" can:

1. Create a free account at **https://healthchecks.io** → **Add Check**.
2. Set **Period: 1 minute**, **Grace: 3 minutes**. Add your email (or Telegram,
   etc.) under Integrations.
3. Copy the check's **ping URL** (e.g. `https://hc-ping.com/1f2e3d4c-...`).
4. Put it in `deploy/.env` as `HEARTBEAT_URL=...`, then:
   ```bash
   docker compose up -d
   ```
5. Within a minute the check turns green. If the engine stops for 3+ minutes
   (crash, server down, disk full), you get an email.

Also usable with any uptime monitor (UptimeRobot, Better Stack, ...):
`https://trade.example.com/api/health/` returns **200** when the engine ran
within the last 60 s (`ENGINE_STALE_SECONDS`), otherwise **503**.

---

## 10. Django admin over an SSH tunnel

`https://<domain>/admin` returns 404 for everyone. The admin is served only on
the server's `127.0.0.1:8000`. To use it from your computer:

```bash
ssh -L 8000:127.0.0.1:8000 you@203.0.113.10
```
Keep that terminal open and browse to **http://localhost:8000/admin/**. Log in
with the website user (it's a superuser). Close the terminal to end access.

Use it for: adding another website user, inspecting raw records, emergencies.
Everything for normal use is in the website.

> Port 8000 busy on your computer (e.g. the dev stack is running)? Pick another
> local port: `ssh -L 9000:127.0.0.1:8000 you@server` → http://localhost:9000/admin/

---

## 11. Day-to-day operations

All commands in `deploy/` on the server.

| Task | Command |
|---|---|
| Status | `docker compose ps` |
| Copy engine log (live) | `docker compose logs -f celery_worker` |
| Website/API log | `docker compose logs -f web` |
| HTTPS / Caddy log | `docker compose logs -f caddy` |
| Last 200 lines of everything | `docker compose logs --tail 200` |
| Restart the engine | `docker compose restart celery_worker celery_beat` |
| Stop everything | `./stop.sh` |
| Start again | `docker compose up -d` (or `./start.sh`) |
| Django shell | `docker compose exec web python manage.py shell` |
| Re-sync lot sizes | `docker compose exec web python manage.py kite_sync_instruments` |
| Database shell | `docker compose exec db psql -U core -d core` |
| Disk usage | `df -h` and `docker system df` |

Logs are rotated automatically (3 × 10 MB per service).

Containers restart automatically after a crash or a server reboot
(`restart: unless-stopped`); Docker itself starts on boot.

**Emergency stop of copying:** website → Settings → Copying → **Off** (instant).
If the website is unreachable: `docker compose stop celery_worker celery_beat`.

---

## 12. Updating to a new version

```bash
cd ~/copy_trading
git pull
cd deploy
./start.sh          # rebuilds images, applies migrations, restarts changed services
```

Do it **outside market hours** (or with copying Off). The update takes 1–3
minutes; the database, logins, settings and certificates are kept.

If a new version adds settings, compare `.env.example` with your `.env`:
```bash
diff <(grep -oE '^[A-Z_]+' .env.example | sort) <(grep -oE '^[A-Z_]+' .env | sort)
```

**Rolling back:** `git checkout <previous-commit>` then `./start.sh`. (Database
migrations are not rolled back automatically; ask before rolling back across a
migration.)

---

## 13. Security checklist

- [ ] `DJANGO_DEBUG=False`
- [ ] All secrets in `deploy/.env` are **new random values**
- [ ] `deploy/.env` backed up privately; never committed (it's gitignored)
- [ ] Strong website password (`DJANGO_SUPERUSER_PASSWORD`); you can change it
      later in admin
- [ ] Kite API secrets that were ever shared/pasted anywhere have been
      **regenerated** on developers.kite.trade (and re-entered on Accounts)
- [ ] Firewall: only 22, 80, 443 open
- [ ] SSH: key login; consider disabling password login
      (`PasswordAuthentication no` in `/etc/ssh/sshd_config`)
- [ ] `HEARTBEAT_URL` set and the healthchecks.io check is green
- [ ] Automatic OS security updates (`sudo apt install unattended-upgrades`)

Built in: HTTPS with HSTS, security headers, `/admin` blocked, login limited to
10 attempts/min per IP, secure cookies, Postgres/Redis private, broker secrets
encrypted.

**Not yet:** automatic database backups. To take one by hand:
```bash
docker compose exec -T db pg_dump -U core core | gzip > core-$(date +%F).sql.gz
```
Copy it off the server (e.g. `scp you@server:copy_trading/deploy/core-*.sql.gz .`).

---

## 14. Alternatives: no domain / Cloudflare Tunnel / local trial

| Situation | `SITE_ADDRESS` | Notes |
|---|---|---|
| Normal (domain → server IP) | `trade.example.com` | Caddy does HTTPS via Let's Encrypt |
| Cloudflare Tunnel / another HTTPS proxy in front | `:80` | The proxy does HTTPS; Caddy serves plain HTTP behind it. Keep `DJANGO_CSRF_TRUSTED_ORIGINS`/`FRONTEND_URL` with `https://<domain>`. |
| Try the production stack on your own computer | `:80` | `SITE_ADDRESS=:80 ./start.sh` → http://localhost. Stop the dev backend first (both use port 8000). Kite login needs a Redirect URL of `http://localhost/kite/callback`. |

---

## 15. Troubleshooting

| Problem | Cause / fix |
|---|---|
| `start.sh`: "still has <placeholder> values" | Replace every `<...>` in `deploy/.env` |
| Browser: certificate error / site not reachable | DNS not pointing at the server yet, or ports 80/443 blocked. `docker compose logs caddy` shows Let's Encrypt errors. Fix DNS/firewall, then `docker compose restart caddy`. |
| Caddy log: "too many certificates" / rate limited | Let's Encrypt limits repeated attempts; wait an hour. Don't delete the `caddy_data` volume. |
| "Bad Request (400)" | Domain missing from `DJANGO_ALLOWED_HOSTS` |
| "CSRF verification failed" (admin) | Use the tunnel at `http://localhost:8000`; keep `localhost` in `DJANGO_ALLOWED_HOSTS` |
| Website loads, login fails with network error | `web` not running: `docker compose ps`, `docker compose logs web` |
| `/api/health/` 503 | Engine stopped: `docker compose ps`; `docker compose up -d`; check `docker compose logs celery_worker celery_beat` |
| Zerodha login lands on a 404 | Kite app Redirect URL not set to `https://<domain>/kite/callback` |
| All API secrets "missing"/logins fail after moving `.env` | `FIELD_ENCRYPTION_KEY` changed. Restore the old value, or re-enter secrets and log in again. |
| Out of disk | `docker system prune` (removes old images), check `df -h` |
