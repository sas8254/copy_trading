#!/usr/bin/env bash
# Daily copy-trading startup: refresh Zerodha tokens (they expire ~6 AM IST),
# re-sync instruments, restart the ticker/workers, then run preflight.
#
# Zerodha login is interactive, so this pauses for you to paste each account's
# request_token (copied from the redirect URL after logging in).
#
# Usage:
#   ./morning.sh                       # interactive, uses MASTER/COPY below
#   MASTER=mom_zerodha COPY=my_zerodha ./morning.sh
set -euo pipefail
cd "$(dirname "$0")"

MASTER="${MASTER:-mom_zerodha}"
COPY="${COPY:-my_zerodha}"

dc() { docker compose "$@"; }
mc() { dc exec -T web python manage.py "$@"; }

login_account() {
    local acct="$1"
    echo ""
    echo ">> Login URL for '$acct' — open it, log in, then copy the request_token"
    echo "   from the redirect URL (the ?request_token=XXXX part):"
    echo ""
    mc kite_login --account "$acct"
    echo ""
    read -rp "   Paste request_token for '$acct': " token
    if [ -z "$token" ]; then
        echo "   ERROR: no token entered for '$acct'." >&2
        exit 1
    fi
    mc kite_login --account "$acct" --request-token "$token"
}

echo ">> Ensuring the stack is up..."
dc up -d >/dev/null

login_account "$MASTER"
login_account "$COPY"

echo ""
echo ">> Syncing instruments (lot sizes) from '$MASTER'..."
mc kite_sync_instruments --account "$MASTER"

echo ""
echo ">> Restarting ticker + workers to pick up fresh tokens..."
dc restart kite_ticker celery_worker celery_beat >/dev/null

echo ""
echo ">> Running preflight checklist..."
mc preflight || true

echo ""
echo ">> Done. Dashboard: http://localhost:8000/dashboard/"
echo "   Live orders are controlled by COPYTRADING_LIVE_ORDERS in .env."
