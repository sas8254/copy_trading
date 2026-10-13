"""Fetch live positions for master + copies and compare them.

Used by the Positions page and by the 2s reconciliation loop, so both always
agree on what "expected" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..brokers import get_client
from ..brokers.base import BrokerError, Position
from ..instruments import lot_size_for, round_to_lot
from ..models import AccountRole, BrokerAccount


@dataclass
class AccountPositions:
    account: BrokerAccount
    positions: dict[tuple[str, str], Position] = field(default_factory=dict)
    error: str = ""
    error_code: str = ""


def master_account() -> BrokerAccount | None:
    return BrokerAccount.objects.filter(role=AccountRole.MASTER, active=True).first()


def fetch(account: BrokerAccount) -> AccountPositions:
    result = AccountPositions(account)
    if not account.access_token:
        result.error = "Not logged in to Zerodha."
        result.error_code = "token"
        return result
    try:
        for p in get_client(account).positions():
            result.positions[(p.exchange, p.tradingsymbol)] = p
    except BrokerError as exc:
        result.error = str(exc)
        result.error_code = exc.code
    return result


def compare(master: AccountPositions, copy: AccountPositions) -> list[dict]:
    """One row per instrument held by either side, net quantities only."""
    multiplier = float(copy.account.multiplier)
    rows = []
    for key in sorted(set(master.positions) | set(copy.positions)):
        exchange, symbol = key
        master_qty = master.positions[key].net_quantity if key in master.positions else 0
        actual = copy.positions[key].net_quantity if key in copy.positions else 0
        lot = lot_size_for(symbol, exchange)
        expected = round_to_lot(master_qty * multiplier, lot)
        rows.append({
            "exchange": exchange,
            "symbol": symbol,
            "lot": lot,
            "master_qty": master_qty,
            "expected": expected,
            "actual": actual,
            "ok": expected == actual,
        })
    return rows
