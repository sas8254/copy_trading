"""Create and place copy orders.

What gets placed depends on the trade's copy style and the order kind:

- mirror, main copy: same order type / limit / trigger as the master's order,
  placed while it is still open.
- on_fill, main copy: placed once the master has filled. LIMIT is copied at the
  master's average fill price; MARKET / SL / SL-M become MARKET (the master's
  stop has already triggered).
- top-up: MARKET order for whatever the main copy didn't fill (see sync.py).

The global copy mode (off / dry_run / live) is re-checked right before placing,
so switching it takes effect immediately. Idempotent: one CopyOrder per
(trade, copy account, kind).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError

from ..brokers import get_client
from ..brokers.base import BrokerError, OrderRequest
from ..instruments import lot_size_for, round_to_lot
from ..models import (
    AccountRole,
    AlertKind,
    AppSettings,
    BrokerAccount,
    CopyMode,
    CopyOrder,
    CopyOrderKind,
    CopyOrderStatus,
    CopyStyle,
    ErrorKind,
    Trade,
    ZeroQtyPolicy,
)
from .alerts import broadcast, raise_alert

logger = logging.getLogger(__name__)


def copy_accounts():
    return BrokerAccount.objects.filter(role=AccountRole.COPY, active=True)


def copy_quantity(trade: Trade, account: BrokerAccount, master_qty: int, *, alert=True) -> int:
    """master_qty x multiplier rounded down to whole lots, applying the
    account's zero-qty policy. Returns 0 if the copy should be skipped."""
    if master_qty <= 0:
        return 0
    lot = lot_size_for(trade.tradingsymbol, trade.exchange)
    qty = round_to_lot(master_qty * float(account.multiplier), lot)
    if qty:
        return qty
    if account.zero_qty_policy == ZeroQtyPolicy.ROUND_UP:
        return lot or 1
    if alert and account.zero_qty_policy == ZeroQtyPolicy.SKIP_ALERT:
        raise_alert(
            AlertKind.ZERO_QTY,
            f"Copy qty rounded to 0 for {trade.tradingsymbol} on '{account.label}' "
            f"(master {master_qty} x{account.multiplier}, lot {lot}). Skipped.",
            account=account,
            dedup_key=f"zeroqty:{account.id}:{trade.tradingsymbol}",
        )
    return 0


def create_copy_order(
    trade: Trade, account: BrokerAccount, qty: int, *, kind=CopyOrderKind.COPY, mode=None,
) -> CopyOrder | None:
    """Record a copy order and queue it for placement. Returns None if one of
    this kind already exists for (trade, account)."""
    mode = mode or AppSettings.load().mode
    defaults = {"computed_quantity": qty, "is_dry_run": mode != CopyMode.LIVE}
    if qty <= 0:
        defaults.update(status=CopyOrderStatus.SKIPPED,
                        error_message="Quantity rounded to 0 lots.")
    try:
        co, created = CopyOrder.objects.get_or_create(
            trade=trade, account=account, kind=kind, defaults=defaults
        )
    except IntegrityError:
        return None
    if not created:
        return None
    if co.status == CopyOrderStatus.PENDING:
        from ..tasks import place_copy_order

        place_copy_order.delay(co.id)
    return co


def dispatch_trade(trade: Trade, master_qty: int) -> int:
    """Create the main copy order on every enabled copy account. Returns the
    number of copies queued."""
    mode = AppSettings.load().mode
    if mode == CopyMode.OFF:
        return 0
    queued = 0
    for account in copy_accounts():
        qty = copy_quantity(trade, account, master_qty)
        if create_copy_order(trade, account, qty, mode=mode) and qty:
            queued += 1
    return queued


def _price(value) -> float | None:
    return float(value) if value is not None else None


def order_request(co: CopyOrder) -> OrderRequest:
    trade = co.trade
    order_type = trade.order_type or "MARKET"
    price = trigger = None
    if co.kind == CopyOrderKind.TOPUP:
        order_type = "MARKET"
    elif trade.copy_style == CopyStyle.MIRROR:
        price, trigger = _price(trade.price), _price(trade.trigger_price)
    elif order_type == "LIMIT":
        price = _price(trade.average_price or trade.price)
    else:
        order_type = "MARKET"
    return OrderRequest(
        tradingsymbol=trade.tradingsymbol,
        exchange=trade.exchange,
        transaction_type=trade.side,
        quantity=abs(co.computed_quantity),
        product=trade.product or "NRML",
        order_type=order_type,
        price=price,
        trigger_price=trigger,
        variety=trade.variety or "regular",
        tag="copytrade",
    )


def _skip(co: CopyOrder, reason: str) -> str:
    co.status = CopyOrderStatus.SKIPPED
    co.error_message = reason
    co.save(update_fields=["status", "error_message", "attempts"])
    return "skipped"


def place_copy_order(copy_order_id: int, retries: int = 0) -> str:
    """Place one CopyOrder. Returns a status string. Raises BrokerError on a
    transient failure so the Celery task can retry."""
    co = CopyOrder.objects.select_related("trade", "account").get(pk=copy_order_id)
    if co.status != CopyOrderStatus.PENDING:
        return co.status  # already handled

    co.attempts = retries + 1
    trade = co.trade
    mode = AppSettings.load().mode

    if mode == CopyMode.OFF:
        return _skip(co, "Copying was turned off before this order was placed.")
    if (
        co.kind == CopyOrderKind.COPY
        and trade.copy_style == CopyStyle.MIRROR
        and trade.status in ("CANCELLED", "REJECTED")
    ):
        # Master gave up before we placed; the final check tops up any fill.
        return _skip(co, "Master order was cancelled before the copy was placed.")

    req = order_request(co)

    # Dry-run: record intent, never touch the broker.
    if mode != CopyMode.LIVE:
        co.status = CopyOrderStatus.SIMULATED
        co.is_dry_run = True
        co.broker_order_id = "DRYRUN"
        _remember_placed(co, req)
        co.save()
        broadcast({"type": "copy_order", "status": "simulated",
                   "symbol": trade.tradingsymbol, "qty": co.computed_quantity,
                   "copy": co.account.label})
        return "simulated"

    co.is_dry_run = False
    try:
        broker_order_id = get_client(co.account).place_order(req)
    except BrokerError as exc:
        co.error_code = exc.code
        co.error_kind = ErrorKind.TRANSIENT if exc.kind == "transient" else ErrorKind.TERMINAL
        co.error_message = str(exc)
        if exc.kind == "transient" and retries < settings.COPYTRADING_COPY_MAX_RETRIES:
            co.save()
            raise  # let the Celery task retry
        co.status = CopyOrderStatus.FAILED
        co.save()
        alert_failed(co, str(exc))
        return "failed"

    co.status = CopyOrderStatus.PLACED
    co.broker_order_id = broker_order_id
    co.error_code = co.error_kind = co.error_message = ""
    _remember_placed(co, req)
    co.save()
    broadcast({"type": "copy_order", "status": "placed", "symbol": trade.tradingsymbol,
               "qty": co.computed_quantity, "copy": co.account.label,
               "broker_order_id": broker_order_id})
    return "placed"


def _remember_placed(co: CopyOrder, req: OrderRequest) -> None:
    co.placed_quantity = req.quantity
    co.placed_order_type = req.order_type
    co.placed_price = Decimal(str(req.price)) if req.price is not None else None
    co.placed_trigger_price = (
        Decimal(str(req.trigger_price)) if req.trigger_price is not None else None
    )


def alert_failed(co: CopyOrder, reason: str) -> None:
    trade = co.trade
    what = "Top-up order" if co.kind == CopyOrderKind.TOPUP else "Copy order"
    raise_alert(
        AlertKind.ORDER_FAILED,
        f"{what} FAILED for {trade.side} {co.computed_quantity} {trade.tradingsymbol} "
        f"on '{co.account.label}': {reason}",
        account=co.account,
        dedup_key=f"orderfail:{co.id}",
    )
    broadcast({"type": "copy_order", "status": "failed", "symbol": trade.tradingsymbol,
               "qty": co.computed_quantity, "copy": co.account.label})
