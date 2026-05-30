"""Turn a master Trade into copy orders on each mapped copy account.

Mirrors the master's order type/price. Honors the per-mapping zero-qty policy
and the global COPYTRADING_LIVE_ORDERS dry-run switch. Idempotent: one CopyOrder
per (trade, mapping).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from ..brokers import get_client
from ..brokers.base import BrokerError, OrderRequest
from ..instruments import lot_size_for, round_to_lot
from ..models import (
    AlertKind,
    CopyMapping,
    CopyOrder,
    CopyOrderStatus,
    ErrorKind,
    Trade,
    ZeroQtyPolicy,
)
from .alerts import broadcast, raise_alert

logger = logging.getLogger(__name__)


def dispatch_trade(trade_id: int) -> dict:
    """Create CopyOrders for a Trade and enqueue placement. Returns a summary."""
    trade = Trade.objects.select_related("account").get(pk=trade_id)
    mappings = CopyMapping.objects.filter(
        master=trade.account, active=True, copy__active=True
    ).select_related("copy")

    summary = {"trade": trade_id, "created": 0, "skipped": 0}
    for mapping in mappings:
        co = _build_copy_order(trade, mapping)
        if co is None:
            summary["skipped"] += 1
            continue
        summary["created"] += 1
        from ..tasks import place_copy_order

        place_copy_order.delay(co.id)
    return summary


def _build_copy_order(trade: Trade, mapping: CopyMapping) -> CopyOrder | None:
    lot = lot_size_for(trade.tradingsymbol, trade.exchange)
    qty = round_to_lot(abs(trade.quantity) * float(mapping.multiplier), lot)

    if qty == 0:
        return _handle_zero_qty(trade, mapping, lot)

    try:
        co, created = CopyOrder.objects.get_or_create(
            trade=trade,
            mapping=mapping,
            defaults={
                "computed_quantity": qty,
                "is_dry_run": not settings.COPYTRADING_LIVE_ORDERS,
            },
        )
    except IntegrityError:
        return None  # already exists (idempotent)
    return co if created else None


def _handle_zero_qty(trade: Trade, mapping: CopyMapping, lot: int) -> CopyOrder | None:
    policy = mapping.zero_qty_policy
    if policy == ZeroQtyPolicy.ROUND_UP:
        qty = lot or 1
        co, created = CopyOrder.objects.get_or_create(
            trade=trade, mapping=mapping,
            defaults={"computed_quantity": qty,
                      "is_dry_run": not settings.COPYTRADING_LIVE_ORDERS},
        )
        return co if created else None

    # SKIP_SILENT / SKIP_ALERT: record a skipped CopyOrder for the audit trail.
    co, created = CopyOrder.objects.get_or_create(
        trade=trade, mapping=mapping,
        defaults={"computed_quantity": 0, "status": CopyOrderStatus.SKIPPED},
    )
    if created and policy == ZeroQtyPolicy.SKIP_ALERT:
        raise_alert(
            AlertKind.ZERO_QTY,
            f"Copy qty rounded to 0 for {trade.tradingsymbol} on "
            f"'{mapping.copy.label}' (master {trade.quantity} x{mapping.multiplier}, "
            f"lot {lot}). Skipped.",
            account=mapping.copy,
            dedup_key=f"zeroqty:{mapping.id}:{trade.tradingsymbol}",
        )
    return None  # never placed


def place_copy_order(copy_order_id: int, retries: int = 0) -> str:
    """Place one CopyOrder. Returns a status string. Raises BrokerError on a
    transient failure so the Celery task can retry."""
    co = CopyOrder.objects.select_related("trade", "mapping__copy").get(pk=copy_order_id)
    if co.status in (CopyOrderStatus.PLACED, CopyOrderStatus.SIMULATED, CopyOrderStatus.SKIPPED):
        return co.status  # already handled

    co.attempts = retries + 1
    trade = co.trade

    # Dry-run: record intent, never touch the broker.
    if not settings.COPYTRADING_LIVE_ORDERS:
        co.status = CopyOrderStatus.SIMULATED
        co.is_dry_run = True
        co.broker_order_id = "DRYRUN"
        co.save(update_fields=["status", "is_dry_run", "broker_order_id", "attempts"])
        broadcast({"type": "copy_order", "status": "simulated",
                   "symbol": trade.tradingsymbol, "qty": co.computed_quantity,
                   "copy": co.mapping.copy.label})
        return "simulated"

    req = OrderRequest(
        tradingsymbol=trade.tradingsymbol,
        exchange=trade.exchange,
        transaction_type=trade.side,
        quantity=abs(co.computed_quantity),
        product=trade.product or "NRML",
        order_type=trade.order_type or "MARKET",
        price=float(trade.price) if trade.price is not None else None,
        trigger_price=float(trade.trigger_price) if trade.trigger_price is not None else None,
        variety=trade.variety or "regular",
        tag="copytrade",
    )

    try:
        broker_order_id = get_client(co.mapping.copy).place_order(req)
    except BrokerError as exc:
        co.error_code = exc.code
        co.error_kind = ErrorKind.TRANSIENT if exc.kind == "transient" else ErrorKind.TERMINAL
        co.error_message = str(exc)
        if exc.kind == "transient" and retries < settings.COPYTRADING_COPY_MAX_RETRIES:
            co.save(update_fields=["error_code", "error_kind", "error_message", "attempts"])
            raise  # let the Celery task retry
        co.status = CopyOrderStatus.FAILED
        co.save(update_fields=["status", "error_code", "error_kind", "error_message", "attempts"])
        raise_alert(
            AlertKind.ORDER_FAILED,
            f"Copy order FAILED for {trade.tradingsymbol} on '{co.mapping.copy.label}' "
            f"(qty {co.computed_quantity}, {exc.kind}): {exc}",
            account=co.mapping.copy,
            dedup_key=f"orderfail:{co.id}",
        )
        return "failed"

    co.status = CopyOrderStatus.PLACED
    co.broker_order_id = broker_order_id
    co.error_code = co.error_kind = co.error_message = ""
    co.save(update_fields=["status", "broker_order_id", "error_code", "error_kind",
                           "error_message", "attempts"])
    broadcast({"type": "copy_order", "status": "placed", "symbol": trade.tradingsymbol,
               "qty": co.computed_quantity, "copy": co.mapping.copy.label,
               "broker_order_id": broker_order_id})
    return "placed"
