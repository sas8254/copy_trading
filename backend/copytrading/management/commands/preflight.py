"""Go-live safety checklist. Run before flipping COPYTRADING_LIVE_ORDERS=True.

Read-only: validates tokens, mappings, lot sizes, alert email, and the master
streaming connection, then prints a GO / NO-GO summary. Places no orders.

    python manage.py preflight
"""

import json
import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from copytrading.brokers import get_client
from copytrading.brokers.base import BrokerError
from copytrading.models import (
    AccountRole,
    BrokerAccount,
    CopyMapping,
    Instrument,
)


class Command(BaseCommand):
    help = "Pre-go-live safety checklist (read-only)."

    def handle(self, *args, **opts):
        self.errors = 0
        self.warnings = 0
        out = self.stdout

        out.write(self.style.MIGRATE_HEADING("\n=== Copy Trading — Go-Live Preflight ===\n"))

        masters = list(BrokerAccount.objects.filter(role=AccountRole.MASTER, active=True))
        copies = list(BrokerAccount.objects.filter(role=AccountRole.COPY, active=True))
        mappings = list(
            CopyMapping.objects.filter(active=True, master__active=True, copy__active=True)
            .select_related("master", "copy")
        )

        self._check_accounts(masters, copies)
        self._check_tokens(masters + copies)
        self._check_mappings(mappings)
        self._check_instruments()
        self._check_email()
        self._check_ticker(masters)
        self._show_runtime()

        out.write("")
        if self.errors:
            out.write(self.style.ERROR(
                f"NO-GO — {self.errors} blocking issue(s), {self.warnings} warning(s). "
                f"Fix the errors above before enabling live orders."))
        elif self.warnings:
            out.write(self.style.WARNING(
                f"GO (with caution) — 0 blocking issues, {self.warnings} warning(s). "
                f"Review warnings above."))
        else:
            out.write(self.style.SUCCESS("GO — all checks passed."))
        out.write("")

    # --- check helpers ---
    def _ok(self, msg):
        self.stdout.write(self.style.SUCCESS(f"  [OK]   {msg}"))

    def _warn(self, msg):
        self.warnings += 1
        self.stdout.write(self.style.WARNING(f"  [WARN] {msg}"))

    def _err(self, msg):
        self.errors += 1
        self.stdout.write(self.style.ERROR(f"  [FAIL] {msg}"))

    def _head(self, msg):
        self.stdout.write(self.style.HTTP_INFO(f"\n{msg}"))

    # --- checks ---
    def _check_accounts(self, masters, copies):
        self._head("Accounts")
        if masters:
            self._ok(f"{len(masters)} active master(s): {', '.join(m.label for m in masters)}")
        else:
            self._err("No active master account.")
        if copies:
            self._ok(f"{len(copies)} active copy account(s): {', '.join(c.label for c in copies)}")
        else:
            self._err("No active copy account.")

    def _check_tokens(self, accounts):
        self._head("Access tokens (live REST check)")
        for a in accounts:
            if not a.access_token:
                self._err(f"'{a.label}' has no access token (run kite_login).")
                continue
            try:
                n = len(get_client(a).positions())
                self._ok(f"'{a.label}' token valid — {n} open position(s).")
            except BrokerError as exc:
                self._err(f"'{a.label}' token check failed ({exc.kind}): {exc}")

    def _check_mappings(self, mappings):
        self._head("Copy mappings")
        if not mappings:
            self._err("No active copy mappings.")
            return
        for m in mappings:
            line = f"{m.master.label} -> {m.copy.label}  x{m.multiplier}  (zero-qty: {m.zero_qty_policy})"
            if m.multiplier <= 0:
                self._err(f"{line}  <- multiplier must be > 0")
            elif m.multiplier >= 5:
                self._warn(f"{line}  <- large multiplier, double-check this is intended")
            else:
                self._ok(line)

    def _check_instruments(self):
        self._head("Instrument lot sizes")
        nfo = Instrument.objects.filter(exchange="NFO").count()
        if nfo == 0:
            self._warn("No NFO instruments synced — F&O lot rounding will default to 1. "
                       "Run kite_sync_instruments.")
        else:
            self._ok(f"{nfo} NFO instruments synced.")

    def _check_email(self):
        self._head("Alert email")
        if not settings.ALERT_EMAIL_TO:
            self._warn("ALERT_EMAIL_TO is empty — failures/mismatches will not be emailed.")
        else:
            self._ok(f"ALERT_EMAIL_TO = {', '.join(settings.ALERT_EMAIL_TO)}")
        backend = settings.EMAIL_BACKEND.rsplit(".", 1)[-1]
        if "console" in settings.EMAIL_BACKEND:
            self._warn(f"Email backend is '{backend}' (prints to logs, does not send real email).")
        else:
            self._ok(f"Email backend: {backend}")

    def _check_ticker(self, masters):
        self._head("Master streaming (WebSocket) reachability")
        if not masters:
            return
        try:
            import websocket
        except ImportError:
            self._warn("websocket-client not installed; skipping WS check.")
            return
        for m in masters:
            if not m.access_token:
                continue
            ok, detail = self._probe_ws(websocket, m)
            if ok:
                self._ok(f"'{m.label}' streaming reachable.")
            else:
                self._warn(f"'{m.label}' streaming NOT reachable ({detail}). "
                           f"REST poll still copies, just slower.")

    def _probe_ws(self, websocket, master):
        url = f"wss://ws.kite.trade?api_key={master.api_key}&access_token={master.access_token}"
        state = {"open": False, "err": None}

        def on_open(ws):
            state["open"] = True
            ws.close()

        def on_error(ws, e):
            state["err"] = str(e)[:80]

        ws = websocket.WebSocketApp(url, on_open=on_open, on_error=on_error)
        t = threading.Thread(target=ws.run_forever, daemon=True)
        t.start()
        deadline = time.time() + 8
        while time.time() < deadline and not state["open"] and state["err"] is None:
            time.sleep(0.2)
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass
        return state["open"], state["err"] or "timeout"

    def _show_runtime(self):
        self._head("Runtime flags")
        live = settings.COPYTRADING_LIVE_ORDERS
        if live:
            self.stdout.write(self.style.WARNING(
                "  COPYTRADING_LIVE_ORDERS = True  <- REAL orders will be placed!"))
        else:
            self.stdout.write("  COPYTRADING_LIVE_ORDERS = False (dry-run; copies are simulated)")
        forced = settings.COPYTRADING_FORCE_MARKET_OPEN
        if forced:
            self._warn("COPYTRADING_FORCE_MARKET_OPEN = True (market-hours guard bypassed).")
        self.stdout.write(f"  Copy max retries: {settings.COPYTRADING_COPY_MAX_RETRIES}")
        self.stdout.write(f"  Alert email cooldown: {settings.COPYTRADING_ALERT_EMAIL_COOLDOWN}s")

        self._head("Baselines (orders before this instant are NOT copied)")
        for m in BrokerAccount.objects.filter(role=AccountRole.MASTER, active=True):
            self.stdout.write(f"  {m.label}: copy_orders_since = {m.copy_orders_since}")
