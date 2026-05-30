"""Compare master vs copy net positions per multiplier; alert on divergence.

Read-only against the brokers: fetches positions, never places orders. Designed
to run every 2s from Celery Beat, but skips quickly when the market is closed.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ..brokers import get_client
from ..brokers.base import BrokerError
from ..instruments import lot_size_for, round_to_lot
from ..market import is_market_open
from ..models import (
    AccountRole,
    AlertKind,
    BrokerAccount,
    CopyMapping,
    PositionSnapshot,
)
from .alerts import broadcast, raise_alert

logger = logging.getLogger(__name__)


def _positions_by_symbol(client) -> dict[tuple[str, str], "Position"]:  # noqa: F821
    return {(p.exchange, p.tradingsymbol): p for p in client.positions()}


def reconcile() -> dict:
    """Run one reconciliation pass. Returns a small summary dict."""
    if not is_market_open():
        return {"skipped": "market_closed"}

    summary = {"masters": 0, "mappings": 0, "mismatches": 0, "errors": 0}

    masters = BrokerAccount.objects.filter(role=AccountRole.MASTER, active=True)
    for master in masters:
        mappings = list(
            CopyMapping.objects.filter(master=master, active=True, copy__active=True)
            .select_related("copy")
        )
        if not mappings:
            continue
        summary["masters"] += 1

        master_pos = _safe_positions(master, summary)
        if master_pos is None:
            continue

        for mapping in mappings:
            summary["mappings"] += 1
            copy_pos = _safe_positions(mapping.copy, summary)
            if copy_pos is None:
                continue
            summary["mismatches"] += _reconcile_mapping(mapping, master_pos, copy_pos)

    broadcast({"type": "reconcile", **summary})
    return summary


def _safe_positions(account: BrokerAccount, summary: dict):
    """Fetch positions, converting auth/API failures into alerts."""
    if not account.access_token:
        raise_alert(
            AlertKind.TOKEN_EXPIRED,
            f"Account '{account.label}' has no access token; run kite_login.",
            account=account,
            dedup_key=f"token:{account.id}",
        )
        summary["errors"] += 1
        return None
    try:
        client = get_client(account)
        return _positions_by_symbol(client)
    except BrokerError as exc:
        kind = AlertKind.TOKEN_EXPIRED if exc.kind == "terminal" else AlertKind.MISMATCH
        raise_alert(
            kind,
            f"Could not fetch positions for '{account.label}': {exc}",
            account=account,
            dedup_key=f"posfail:{account.id}",
            email=(exc.kind == "terminal"),
        )
        summary["errors"] += 1
        return None


def _reconcile_mapping(mapping: CopyMapping, master_pos: dict, copy_pos: dict) -> int:
    """Compare one master->copy mapping across all instruments. Returns mismatch count."""
    mismatches = 0
    symbols = set(master_pos) | set(copy_pos)
    multiplier = float(mapping.multiplier)

    for key in symbols:
        exchange, tradingsymbol = key
        master_net = master_pos[key].net_quantity if key in master_pos else 0
        actual_copy = copy_pos[key].net_quantity if key in copy_pos else 0

        lot = lot_size_for(tradingsymbol, exchange)
        expected_copy = round_to_lot(master_net * multiplier, lot)

        dedup_key = f"recon:{mapping.id}:{exchange}:{tradingsymbol}"

        if expected_copy != actual_copy:
            mismatches += 1
            msg = (
                f"Position mismatch on {exchange}:{tradingsymbol} for "
                f"'{mapping.copy.label}': expected {expected_copy} "
                f"(master {master_net} x{mapping.multiplier}, lot {lot}), "
                f"actual {actual_copy}. Manual intervention may be required."
            )
            raise_alert(
                AlertKind.MISMATCH,
                msg,
                account=mapping.copy,
                dedup_key=dedup_key,
            )
            PositionSnapshot.objects.create(
                account=mapping.copy,
                tradingsymbol=tradingsymbol,
                exchange=exchange,
                net_quantity=actual_copy,
                avg_price=(copy_pos[key].average_price if key in copy_pos else None),
            )
        else:
            _resolve(dedup_key)

    return mismatches


def _resolve(dedup_key: str) -> None:
    """Auto-resolve any open mismatch alert that now matches."""
    from ..models import Alert

    Alert.objects.filter(
        kind=AlertKind.MISMATCH, dedup_key=dedup_key, resolved=False
    ).update(resolved=True)
