"""Live Zerodha order feed over WebSocket (low-latency copy trigger).

Connects one WebSocket per active master account to wss://ws.kite.trade and
listens for order-update messages. On a COMPLETE order it dispatches a copy
immediately (the 2s REST poll remains as a fallback). Uses websocket-client, so
it does not depend on autobahn/twisted.

    python manage.py kite_ticker

Runs as its own long-lived container (see docker-compose `kite_ticker`).
Note: Zerodha tokens expire ~6 AM IST; restart this after the daily kite_login.
"""

import json
import threading
import time

from django.core.management.base import BaseCommand

from copytrading.models import AccountRole, BrokerAccount
from copytrading.services.alerts import broadcast

KITE_WS = "wss://ws.kite.trade"


class Command(BaseCommand):
    help = "Stream Zerodha order updates over WebSocket and dispatch copies live."

    def handle(self, *args, **opts):
        import websocket  # websocket-client

        self._ws = websocket
        self.stdout.write("kite_ticker starting...")
        seen: dict[int, threading.Thread] = {}

        while True:
            masters = BrokerAccount.objects.filter(
                role=AccountRole.MASTER, active=True
            ).exclude(access_token="")
            for master in masters:
                t = seen.get(master.id)
                if t is None or not t.is_alive():
                    th = threading.Thread(
                        target=self._run_master,
                        args=(master.id, master.label, master.api_key, master.access_token),
                        daemon=True,
                    )
                    th.start()
                    seen[master.id] = th
                    self.stdout.write(f"  connecting master '{master.label}'...")
            if not masters:
                self.stdout.write("  no master accounts with tokens; waiting...")
            time.sleep(30)  # re-scan for new/refreshed accounts

    def _run_master(self, master_id, label, api_key, access_token):
        url = f"{KITE_WS}?api_key={api_key}&access_token={access_token}"
        state = {"auth_failed": False}

        def on_message(ws, message):
            # Binary frames are market ticks (we don't subscribe) -> ignore.
            if isinstance(message, (bytes, bytearray)):
                return
            try:
                payload = json.loads(message)
            except (ValueError, TypeError):
                return
            if payload.get("type") != "order":
                return
            order = payload.get("data") or {}
            try:
                from copytrading.services.detect import handle_ticker_order

                dispatched = handle_ticker_order(master_id, order)
                broadcast({
                    "type": "ticker_order",
                    "master": label,
                    "symbol": order.get("tradingsymbol"),
                    "status": order.get("status"),
                    "dispatched": dispatched,
                })
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"[{label}] order handling error: {exc}")

        def on_open(ws):
            self.stdout.write(self.style.SUCCESS(f"[{label}] ticker connected"))
            broadcast({"type": "ticker_status", "master": label, "connected": True})

        def on_close(ws, code, msg):
            self.stdout.write(f"[{label}] ticker closed ({code})")
            broadcast({"type": "ticker_status", "master": label, "connected": False})

        def on_error(ws, error):
            msg = str(error)
            if "403" in msg or "Authentication" in msg:
                state["auth_failed"] = True
            else:
                self.stderr.write(f"[{label}] ticker error: {msg[:160]}")

        # Manual reconnect loop with backoff. On auth failure (expired/invalid
        # token, inactive streaming subscription) we back off hard and raise a
        # single deduped alert instead of hammering the gateway every 5s.
        backoff = 5
        while True:
            state["auth_failed"] = False
            ws = self._ws.WebSocketApp(
                url, on_open=on_open, on_message=on_message,
                on_close=on_close, on_error=on_error,
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
            if state["auth_failed"]:
                from copytrading.models import AlertKind
                from copytrading.services.alerts import raise_alert

                raise_alert(
                    AlertKind.TOKEN_EXPIRED,
                    f"Ticker auth failed for master '{label}' (Kite WS 403). "
                    f"Regenerate the access token (kite_login) and check the "
                    f"Kite Connect streaming subscription. REST polling still works.",
                    dedup_key=f"ws_auth:{master_id}",
                )
                backoff = min(backoff * 2, 300)
            else:
                backoff = 5
            self.stdout.write(f"[{label}] reconnecting in {backoff}s...")
            time.sleep(backoff)
