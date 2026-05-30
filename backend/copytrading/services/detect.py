"""Detect new completed orders on master accounts and hand them to dispatch.

Order-event model: we copy a master order once it COMPLETEs. A per-master
watermark (`copy_orders_since`) is set to "now" on first run so pre-existing
orders/positions are never replayed on startup.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import IntegrityError
from django.utils import timezone

from ..brokers import get_client
from ..brokers.base import BrokerError
from ..market import is_market_open
from ..models import AccountRole, AlertKind, BrokerAccount, Side, Trade
from .alerts import raise_alert

logger = logging.getLogger(__name__)

_COMPLETE = "COMPLETE"


def detect_all() -> dict:
    """Poll every active master once. Returns a summary dict."""
    if not is_market_open():
        return {"skipped": "market_closed"}

    summary = {"masters": 0, "new_trades": 0, "errors": 0}
    for master in BrokerAccount.objects.filter(role=AccountRole.MASTER, active=True):
        summary["masters"] += 1
        try:
            summary["new_trades"] += _detect_for_master(master)
        except BrokerError as exc:
            summary["errors"] += 1
            raise_alert(
                AlertKind.TOKEN_EXPIRED if exc.kind == "terminal" else AlertKind.MISMATCH,
                f"Order poll failed for '{master.label}': {exc}",
                account=master,
                dedup_key=f"pollfail:{master.id}",
                email=(exc.kind == "terminal"),
            )
    return summary


def _to_aware(ts):
    if ts is None:
        return None
    if timezone.is_naive(ts):
        # Kite timestamps are IST.
        from ..market import IST

        return ts.replace(tzinfo=IST)
    return ts


def _detect_for_master(master: BrokerAccount) -> int:
    if not master.access_token:
        raise_alert(
            AlertKind.TOKEN_EXPIRED,
            f"Master '{master.label}' has no access token; run kite_login.",
            account=master,
            dedup_key=f"token:{master.id}",
        )
        return 0

    client = get_client(master)
    orders = client.orders()

    # Baseline on first run: record the watermark and skip everything older.
    if master.copy_orders_since is None:
        master.copy_orders_since = timezone.now()
        master.save(update_fields=["copy_orders_since"])
        logger.info("Baseline set for master '%s'; existing orders skipped.", master.label)
        return 0

    new_count = 0
    for o in orders:
        if process_order(master, o):
            new_count += 1
    return new_count


def process_order(master: BrokerAccount, o: dict) -> bool:
    """Ingest a single broker order dict and dispatch it if it is a new,
    post-baseline COMPLETE fill. Shared by the REST poll and the WS ticker.
    Assumes `master.copy_orders_since` is already set.
    """
    if o.get("status") != _COMPLETE:
        return False
    if not (o.get("order_id") or ""):
        return False
    ts = _to_aware(o.get("order_timestamp"))
    if master.copy_orders_since and ts is not None and ts < master.copy_orders_since:
        return False

    trade, created = _ingest_order(master, o, ts)
    if not created:
        return False
    # Dispatch asynchronously so a slow broker call never blocks the caller.
    from ..tasks import dispatch_trade as dispatch_task

    dispatch_task.delay(trade.id)
    return True


def handle_ticker_order(master_id: int, o: dict) -> bool:
    """Entry point for the WS ticker thread: load the master, ensure a baseline
    exists, then process the order. Runs outside the request/Celery cycle."""
    master = BrokerAccount.objects.filter(pk=master_id, active=True).first()
    if master is None:
        return False
    if master.copy_orders_since is None:
        # No baseline yet (poll hasn't run); set it and skip this first event.
        master.copy_orders_since = timezone.now()
        master.save(update_fields=["copy_orders_since"])
        return False
    return process_order(master, o)


def _ingest_order(master: BrokerAccount, o: dict, ts):
    qty = int(o.get("filled_quantity") or o.get("quantity") or 0)
    side = Side.BUY if str(o.get("transaction_type", "")).upper() == "BUY" else Side.SELL
    defaults = dict(
        tradingsymbol=o.get("tradingsymbol", ""),
        exchange=o.get("exchange", ""),
        instrument_token=o.get("instrument_token"),
        side=side,
        quantity=qty,
        price=_dec(o.get("average_price") or o.get("price")),
        trigger_price=_dec(o.get("trigger_price")),
        product=o.get("product", "") or "",
        order_type=o.get("order_type", "") or "",
        variety=o.get("variety", "regular") or "regular",
        status=o.get("status", ""),
        placed_at=ts,
    )
    try:
        return Trade.objects.get_or_create(
            account=master, broker_order_id=o.get("order_id", ""), defaults=defaults
        )
    except IntegrityError:
        return Trade.objects.get(account=master, broker_order_id=o.get("order_id", "")), False


def _dec(v):
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v))
        return d if d != 0 else None
    except Exception:  # noqa: BLE001
        return None
