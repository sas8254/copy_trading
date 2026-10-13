"""The copy engine: one pass every poll (2s) during market hours.

1. Read the master's orders and create/update a Trade for each one after the
   baseline. on_fill trades are created once filled; mirror trades as soon as
   the order is open.
2. Refresh the status / filled quantity of copy orders still open at the broker.
3. Advance every unfinished Trade:
   - mirror, master still open: make sure each copy account has a copy and that
     it matches the master's quantity / type / prices (modify it if not).
   - master finished: the final check (`settle`). A copy still working after
     the grace period is cancelled; any gap is filled with a MARKET top-up; a
     copy that filled more than the master is reported (never auto-exited).

Each pass is idempotent and works from current state, so a missed or failed
step is simply retried on the next pass. A Postgres advisory lock keeps passes
from overlapping.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, connection
from django.utils import timezone

from ..brokers import get_client
from ..brokers.base import BrokerError
from ..market import IST, is_market_open, last_token_reset
from ..models import (
    OPEN_STATUSES,
    TERMINAL_STATUSES,
    AlertKind,
    AppSettings,
    BrokerAccount,
    CopyMode,
    CopyOrder,
    CopyOrderKind,
    CopyOrderStatus,
    CopyStyle,
    Side,
    Trade,
)
from .alerts import broadcast, raise_alert
from .dispatch import alert_failed, copy_accounts, copy_quantity, create_copy_order, dispatch_trade
from .positions import master_account

logger = logging.getLogger(__name__)

_LOCK_KEY = 74201  # arbitrary id for pg_try_advisory_lock
_CANCEL_RETRY_SECONDS = 10


def run_cycle() -> dict:
    if not is_market_open():
        return {"skipped": "market_closed"}
    with _lock() as acquired:
        if not acquired:
            return {"skipped": "previous_pass_running"}
        return _cycle()


@contextmanager
def _lock():
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [_LOCK_KEY])
        acquired = cur.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", [_LOCK_KEY])


def _cycle() -> dict:
    app = AppSettings.load()
    summary = {"new_trades": 0, "open_trades": 0, "errors": 0}

    # Orders from previous days are long gone at the broker.
    Trade.objects.filter(finalized=False, observed_at__lt=last_token_reset()).update(
        finalized=True
    )

    master = master_account()
    if master:
        try:
            summary["new_trades"] = ingest_master(master, app)
        except BrokerError as exc:
            summary["errors"] += 1
            _poll_alert(master, exc)

    trades = list(Trade.objects.filter(finalized=False).select_related("account"))
    summary["open_trades"] = len(trades)
    if trades:
        refresh_copy_orders(trades)
        for trade in trades:
            advance(trade, app.mode)
    return summary


# ---------------------------------------------------------------- master side

def ingest_master(master: BrokerAccount, app: AppSettings) -> int:
    if not master.access_token:
        raise_alert(
            AlertKind.TOKEN_EXPIRED,
            f"Master '{master.label}' is not logged in to Zerodha (Accounts page).",
            account=master,
            dedup_key=f"token:{master.id}",
        )
        return 0
    orders = get_client(master).orders()
    if master.copy_orders_since is None:
        # First run: only copy orders from now on.
        master.copy_orders_since = timezone.now()
        master.save(update_fields=["copy_orders_since"])
        return 0
    return sum(ingest_order(master, o, app) for o in orders)


def ingest_order(master: BrokerAccount, o: dict, app: AppSettings) -> bool:
    """Create or update the Trade for one master order. Returns True if a new
    Trade was created."""
    order_id = o.get("order_id") or ""
    if not order_id:
        return False
    ts = _to_aware(o.get("order_timestamp"))
    if master.copy_orders_since and ts is not None and ts < master.copy_orders_since:
        return False

    trade = Trade.objects.filter(account=master, broker_order_id=order_id).first()
    if trade:
        _update_trade(trade, o)
        return False

    status = o.get("status", "")
    filled = int(o.get("filled_quantity") or 0)
    # Only plain orders are mirrored; others (iceberg, cover...) are copied on fill.
    style = app.copy_style if (o.get("variety") or "regular") == "regular" else CopyStyle.ON_FILL
    if style == CopyStyle.MIRROR:
        wanted = status in OPEN_STATUSES or (status in TERMINAL_STATUSES and filled > 0)
    else:
        wanted = status in TERMINAL_STATUSES and filled > 0
    if not wanted:
        return False

    try:
        trade, created = Trade.objects.get_or_create(
            account=master, broker_order_id=order_id,
            defaults={**_order_fields(o), "copy_style": style, "placed_at": ts},
        )
    except IntegrityError:
        return False
    if not created:
        return False
    if trade.is_terminal:
        trade.completed_at = timezone.now()
    if app.mode == CopyMode.OFF:
        trade.finalized = True  # copying is off: record it, copy nothing
    trade.save(update_fields=["completed_at", "finalized"])

    if not trade.finalized:
        if style == CopyStyle.ON_FILL:
            dispatch_trade(trade, trade.filled_quantity)
        elif not trade.is_terminal:
            dispatch_trade(trade, trade.quantity)
        # A mirror order first seen already finished is copied by settle().
    broadcast({"type": "master_order", "symbol": trade.tradingsymbol,
               "status": trade.status, "side": trade.side, "qty": trade.quantity})
    return True


def _order_fields(o: dict) -> dict:
    side = Side.BUY if str(o.get("transaction_type", "")).upper() == "BUY" else Side.SELL
    return {
        "tradingsymbol": o.get("tradingsymbol", ""),
        "exchange": o.get("exchange", ""),
        "instrument_token": o.get("instrument_token"),
        "side": side,
        "quantity": int(o.get("quantity") or 0),
        "filled_quantity": int(o.get("filled_quantity") or 0),
        "price": _dec(o.get("price")),
        "average_price": _dec(o.get("average_price")),
        "trigger_price": _dec(o.get("trigger_price")),
        "product": o.get("product", "") or "",
        "order_type": o.get("order_type", "") or "",
        "variety": o.get("variety", "regular") or "regular",
        "status": o.get("status", ""),
    }


_MUTABLE = ("quantity", "filled_quantity", "price", "average_price", "trigger_price",
            "order_type", "status")


def _update_trade(trade: Trade, o: dict) -> None:
    fields = _order_fields(o)
    changed = [f for f in _MUTABLE if getattr(trade, f) != fields[f]]
    if not changed:
        return
    for f in changed:
        setattr(trade, f, fields[f])
    if trade.is_terminal and trade.completed_at is None:
        trade.completed_at = timezone.now()
        changed.append("completed_at")
    trade.save(update_fields=changed)
    broadcast({"type": "master_order", "symbol": trade.tradingsymbol,
               "status": trade.status, "filled": trade.filled_quantity})


def _poll_alert(master: BrokerAccount, exc: BrokerError) -> None:
    if exc.code == "token":
        raise_alert(
            AlertKind.TOKEN_EXPIRED,
            f"Master '{master.label}' needs a Zerodha login (Accounts page). {exc}",
            account=master,
            dedup_key=f"token:{master.id}",
        )
    else:
        raise_alert(
            AlertKind.MISMATCH,
            f"Order poll failed for '{master.label}': {exc}",
            account=master,
            dedup_key=f"pollfail:{master.id}",
            email=(exc.kind == "terminal"),
        )


def handle_ticker_order(master_id: int, o: dict) -> bool:
    """Instant-feed hook: run a pass right away instead of waiting for the
    next 2s poll. The pass itself reads the order from the REST API."""
    from ..tasks import poll_master_orders

    poll_master_orders.delay()
    return True


# ------------------------------------------------------------------ copy side

def refresh_copy_orders(trades: list[Trade]) -> None:
    """Pull status + filled quantity for copy orders still open at the broker."""
    open_orders = list(
        CopyOrder.objects.filter(trade__in=trades, status=CopyOrderStatus.PLACED,
                                 is_dry_run=False)
        .exclude(broker_status__in=TERMINAL_STATUSES)
        .select_related("account", "trade")
    )
    by_account: dict[int, list[CopyOrder]] = {}
    for co in open_orders:
        by_account.setdefault(co.account_id, []).append(co)

    for cos in by_account.values():
        try:
            book = {o.get("order_id"): o for o in get_client(cos[0].account).orders()}
        except BrokerError as exc:
            logger.warning("Could not fetch orders for %s: %s", cos[0].account.label, exc)
            continue
        for co in cos:
            o = book.get(co.broker_order_id)
            if not o:
                continue
            status = o.get("status", "")
            filled = int(o.get("filled_quantity") or 0)
            if (status, filled) == (co.broker_status, co.filled_quantity):
                continue
            co.broker_status, co.filled_quantity = status, filled
            if status == "REJECTED":
                co.error_message = o.get("status_message") or "Rejected by Zerodha."
                alert_failed(co, co.error_message)
            co.save(update_fields=["broker_status", "filled_quantity", "error_message"])


def advance(trade: Trade, mode: str) -> None:
    if mode == CopyMode.OFF:
        # Off stops all work; copy orders already at the broker are left as is.
        trade.finalized = True
        trade.save(update_fields=["finalized"])
        return
    accounts = list(copy_accounts())
    if trade.copy_style == CopyStyle.MIRROR and not trade.is_terminal:
        for account in accounts:
            _follow(trade, account, mode)
        return
    done = [settle(trade, account, mode) for account in accounts]
    if all(done):
        trade.finalized = True
        trade.save(update_fields=["finalized"])


def _copies(trade: Trade, account: BrokerAccount) -> dict[str, CopyOrder]:
    return {
        co.kind: co
        for co in CopyOrder.objects.filter(trade=trade, account=account).select_related(
            "trade", "account"
        )
    }


def _follow(trade: Trade, account: BrokerAccount, mode: str) -> None:
    """Mirror: keep the copy in line with the master's open order."""
    main = _copies(trade, account).get(CopyOrderKind.COPY)
    if main is None:
        # Account enabled (or created) after the master placed the order.
        if trade.status in OPEN_STATUSES:
            create_copy_order(trade, account, copy_quantity(trade, account, trade.quantity),
                              mode=mode)
        return

    qty = copy_quantity(trade, account, trade.quantity, alert=False)
    want = (qty, trade.order_type, _norm(trade.price), _norm(trade.trigger_price))
    have = (main.placed_quantity, main.placed_order_type,
            _norm(main.placed_price), _norm(main.placed_trigger_price))
    if want == have or qty <= 0:
        return

    if main.status == CopyOrderStatus.SIMULATED:
        _record_modification(main, want)
        return
    if not main.is_open_at_broker or qty <= main.filled_quantity:
        return  # nothing left to modify; settle() sorts out the quantities
    try:
        get_client(account).modify_order(
            main.broker_order_id,
            variety=trade.variety or "regular",
            quantity=qty,
            order_type=trade.order_type,
            price=float(trade.price) if trade.price is not None else None,
            trigger_price=float(trade.trigger_price) if trade.trigger_price is not None else None,
        )
    except BrokerError as exc:
        raise_alert(
            AlertKind.ORDER_FAILED,
            f"Could not update the copy of {trade.tradingsymbol} on '{account.label}' "
            f"to match the master's change: {exc}",
            account=account,
            dedup_key=f"modifyfail:{main.id}",
            email=False,
        )
        return
    _record_modification(main, want)


def _record_modification(co: CopyOrder, want: tuple) -> None:
    co.computed_quantity, co.placed_order_type, co.placed_price, co.placed_trigger_price = want
    co.placed_quantity = co.computed_quantity
    co.modifications += 1
    co.save(update_fields=["computed_quantity", "placed_quantity", "placed_order_type",
                           "placed_price", "placed_trigger_price", "modifications"])
    broadcast({"type": "copy_order", "status": "modified", "symbol": co.trade.tradingsymbol,
               "copy": co.account.label})


def settle(trade: Trade, account: BrokerAccount, mode: str) -> bool:
    """Final check once the master's order has finished. Returns True when
    this copy account is done."""
    copies = _copies(trade, account)
    main, top = copies.get(CopyOrderKind.COPY), copies.get(CopyOrderKind.TOPUP)
    target = copy_quantity(trade, account, trade.filled_quantity, alert=main is None)

    if mode != CopyMode.LIVE or (main and main.is_dry_run):
        # Dry run: nothing real to reconcile. Simulate a copy for orders that
        # filled before a mirror copy could be placed.
        if main is None and top is None and target:
            create_copy_order(trade, account, target, kind=CopyOrderKind.TOPUP, mode=mode)
        return not any(c.status == CopyOrderStatus.PENDING for c in copies.values())

    if main and main.status == CopyOrderStatus.PENDING:
        return False  # still being placed
    if main and main.is_open_at_broker:
        grace = settings.COPYTRADING_FILL_GRACE_SECONDS
        finished = trade.completed_at or timezone.now()
        if trade.status == "COMPLETE" and (timezone.now() - finished).total_seconds() < grace:
            return False  # give the copy a chance to fill at its own price
        _cancel(main)
        return False  # wait for the cancel to show up
    if top and (top.status == CopyOrderStatus.PENDING or top.is_open_at_broker):
        return False
    if any(c.status == CopyOrderStatus.FAILED or c.broker_status == "REJECTED"
           for c in (main, top) if c):
        return True  # already alerted

    copied = sum(c.filled_quantity for c in (main, top) if c)
    gap = target - copied
    if gap > 0 and top is None:
        create_copy_order(trade, account, gap, kind=CopyOrderKind.TOPUP, mode=mode)
        return False
    if gap > 0:
        raise_alert(
            AlertKind.ORDER_FAILED,
            f"Only {copied} of {target} {trade.tradingsymbol} could be copied to "
            f"'{account.label}'. Fix it manually in Zerodha.",
            account=account,
            dedup_key=f"short:{trade.id}:{account.id}",
        )
    elif gap < 0:
        raise_alert(
            AlertKind.MISMATCH,
            f"'{account.label}' got {copied} {trade.tradingsymbol} but should have "
            f"{target} (master {trade.side} {trade.filled_quantity} of "
            f"{trade.quantity}, then {trade.status.lower()}). It holds {-gap} extra; "
            f"exit them in Zerodha if you don't want them.",
            account=account,
            dedup_key=f"over:{trade.id}:{account.id}",
        )
    return True


def _cancel(co: CopyOrder) -> None:
    now = timezone.now()
    if co.cancel_requested_at and (
        now - co.cancel_requested_at
    ).total_seconds() < _CANCEL_RETRY_SECONDS:
        return
    co.cancel_requested_at = now
    co.save(update_fields=["cancel_requested_at"])
    try:
        get_client(co.account).cancel_order(
            co.broker_order_id, variety=co.trade.variety or "regular"
        )
    except BrokerError as exc:
        # Usually "already complete/cancelled"; the next refresh shows which.
        logger.info("Cancel of copy order %s failed: %s", co.id, exc)


# ------------------------------------------------------------------- helpers

def _norm(v):
    return Decimal(str(v)).normalize() if v is not None else None


def _to_aware(ts):
    if ts is None:
        return None
    if isinstance(ts, str):
        from datetime import datetime

        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return None
    if timezone.is_naive(ts):
        return ts.replace(tzinfo=IST)  # Kite timestamps are IST
    return ts


def _dec(v):
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v))
        return d if d != 0 else None
    except Exception:  # noqa: BLE001
        return None
