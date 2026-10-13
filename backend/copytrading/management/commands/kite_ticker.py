"""Live Zerodha order feed over WebSocket (low-latency copy trigger).

Connects one WebSocket for the active master account to wss://ws.kite.trade and
listens for order-update messages. On a COMPLETE order it dispatches a copy
immediately (the 2s REST poll remains as a fallback). Uses websocket-client, so
it does not depend on autobahn/twisted.

    python manage.py kite_ticker

Runs as its own long-lived container (see docker-compose `kite_ticker`). Every
few seconds it re-reads the master and the "instant feed" setting from the DB,
so a new login, a master switch or toggling the feed on the Settings page is
picked up without a restart. Idle while the feed is off (the default).
"""

import json
import threading
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from copytrading.models import AccountRole, AppSettings, BrokerAccount
from copytrading.services.alerts import broadcast

KITE_WS = "wss://ws.kite.trade"
RESCAN_SECONDS = 5


class _Worker:
    """One WebSocket connection loop for one master + token."""

    def __init__(self, command, master):
        self.command = command
        self.master_id = master.id
        self.label = master.label
        self.api_key = master.api_key
        self.token = master.access_token
        self.stop = threading.Event()
        self.ws = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def shutdown(self):
        self.stop.set()
        if self.ws is not None:
            self.ws.close()

    def run(self):
        out, err = self.command.stdout, self.command.stderr
        url = f"{KITE_WS}?api_key={self.api_key}&access_token={self.token}"
        state = {"auth_failed": False}
        label, master_id = self.label, self.master_id

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
                from copytrading.services.sync import handle_ticker_order

                dispatched = handle_ticker_order(master_id, order)
                broadcast({
                    "type": "ticker_order",
                    "master": label,
                    "symbol": order.get("tradingsymbol"),
                    "status": order.get("status"),
                    "dispatched": dispatched,
                })
            except Exception as exc:  # noqa: BLE001
                err.write(f"[{label}] order handling error: {exc}")

        def on_open(ws):
            out.write(self.command.style.SUCCESS(f"[{label}] ticker connected"))
            broadcast({"type": "ticker_status", "master": label, "connected": True})

        def on_close(ws, code, msg):
            out.write(f"[{label}] ticker closed ({code})")
            broadcast({"type": "ticker_status", "master": label, "connected": False})

        def on_error(ws, error):
            msg = str(error)
            if "403" in msg or "Authentication" in msg:
                state["auth_failed"] = True
            else:
                err.write(f"[{label}] ticker error: {msg[:160]}")

        # Reconnect loop with backoff. On auth failure (expired/invalid token,
        # inactive streaming subscription) back off hard and raise one deduped
        # alert instead of hammering the gateway.
        backoff = 5
        while not self.stop.is_set():
            state["auth_failed"] = False
            self.ws = self.command.websocket.WebSocketApp(
                url, on_open=on_open, on_message=on_message,
                on_close=on_close, on_error=on_error,
            )
            self.ws.run_forever(ping_interval=30, ping_timeout=10)
            if self.stop.is_set():
                break
            if state["auth_failed"]:
                from copytrading.models import AlertKind
                from copytrading.services.alerts import raise_alert

                raise_alert(
                    AlertKind.TOKEN_EXPIRED,
                    f"Instant copy feed for '{label}' was refused by Zerodha (403). "
                    f"Log in again from the Accounts page and check the Kite Connect "
                    f"subscription. Copying still works via polling (~2s slower).",
                    dedup_key=f"ws_auth:{master_id}",
                    email=False,
                )
                backoff = min(backoff * 2, 300)
            else:
                backoff = 5
            out.write(f"[{label}] reconnecting in {backoff}s...")
            self.stop.wait(backoff)
        out.write(f"[{label}] ticker stopped")


class Command(BaseCommand):
    help = "Stream Zerodha order updates over WebSocket and dispatch copies live."

    def handle(self, *args, **opts):
        import websocket  # websocket-client

        self.websocket = websocket
        self.stdout.write("kite_ticker starting...")
        worker: _Worker | None = None
        waiting_logged = False

        while True:
            close_old_connections()
            master = None
            if AppSettings.load().instant_feed:
                master = (
                    BrokerAccount.objects.filter(role=AccountRole.MASTER, active=True)
                    .exclude(access_token="")
                    .first()
                )
            # Restart the connection if the master or its token changed.
            if worker and (
                master is None
                or master.id != worker.master_id
                or master.access_token != worker.token
                or not worker.thread.is_alive()
            ):
                self.stdout.write(f"  master/token changed; stopping '{worker.label}'")
                worker.shutdown()
                worker = None
            if master and worker is None:
                worker = _Worker(self, master)
                worker.start()
                waiting_logged = False
                self.stdout.write(f"  connecting master '{master.label}'...")
            if master is None and not waiting_logged:
                self.stdout.write("  instant feed off or no logged-in master; waiting...")
                waiting_logged = True
            time.sleep(RESCAN_SECONDS)
