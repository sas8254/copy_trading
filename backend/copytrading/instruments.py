"""Lot-size lookup and quantity rounding helpers."""

from __future__ import annotations

from .models import Instrument


def lot_size_for(tradingsymbol: str, exchange: str, default: int = 1) -> int:
    """Return the lot size for an instrument, or `default` if not synced.

    Equity (NSE/BSE) trades in single units, so a missing row defaults to 1.
    For F&O, run `manage.py kite_sync_instruments` so real lot sizes are known.
    """
    row = (
        Instrument.objects.filter(exchange=exchange, tradingsymbol=tradingsymbol)
        .values_list("lot_size", flat=True)
        .first()
    )
    return int(row) if row else default


def round_to_lot(quantity: float, lot_size: int) -> int:
    """Round a desired quantity DOWN to the nearest whole lot.

    Preserves sign (short positions are negative). Rounding toward zero means a
    fractional multiplier never over-buys. May return 0 (caller decides policy).
    """
    if lot_size <= 1:
        return int(quantity)
    lots = int(abs(quantity) // lot_size)
    signed = lots * lot_size
    return -signed if quantity < 0 else signed
