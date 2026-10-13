"""Compare master vs copy net positions per multiplier; alert on divergence.

Read-only against the brokers: fetches positions, never places orders. Runs
every 2s from Celery Beat, but only in live mode during market hours (in dry
run the copies are simulated, so positions are expected to differ).
"""

from __future__ import annotations

import logging

from ..market import is_market_open
from ..models import Alert, AlertKind, AppSettings, CopyMode, Trade
from . import positions as pos
from .alerts import broadcast, raise_alert
from .dispatch import copy_accounts

logger = logging.getLogger(__name__)


def reconcile() -> dict:
    """Run one reconciliation pass. Returns a small summary dict."""
    if AppSettings.load().mode != CopyMode.LIVE:
        return {"skipped": "not_live"}
    if not is_market_open():
        return {"skipped": "market_closed"}

    master = pos.master_account()
    copies = list(copy_accounts())
    if master is None or not copies:
        return {"skipped": "no_master_or_copies"}

    summary = {"copies": 0, "mismatches": 0, "errors": 0}
    # Symbols whose orders are still being copied/settled would show a
    # temporary difference; check them once their trades are finalized.
    in_flight = set(
        Trade.objects.filter(finalized=False).values_list("exchange", "tradingsymbol")
    )
    master_pos = pos.fetch(master)
    if not _ok(master_pos, summary):
        return summary

    for copy in copies:
        summary["copies"] += 1
        copy_pos = pos.fetch(copy)
        if not _ok(copy_pos, summary):
            continue
        for row in pos.compare(master_pos, copy_pos):
            if (row["exchange"], row["symbol"]) in in_flight:
                continue
            dedup_key = f"recon:{copy.id}:{row['exchange']}:{row['symbol']}"
            if row["ok"]:
                Alert.objects.filter(
                    kind=AlertKind.MISMATCH, dedup_key=dedup_key, resolved=False
                ).update(resolved=True)
                continue
            summary["mismatches"] += 1
            raise_alert(
                AlertKind.MISMATCH,
                f"Position mismatch on {row['exchange']}:{row['symbol']} for "
                f"'{copy.label}': expected {row['expected']} (master "
                f"{row['master_qty']} x{copy.multiplier}, lot {row['lot']}), "
                f"actual {row['actual']}. Fix it manually in Zerodha.",
                account=copy,
                dedup_key=dedup_key,
            )

    broadcast({"type": "reconcile", **summary})
    return summary


def _ok(result: pos.AccountPositions, summary: dict) -> bool:
    """Turn a failed position fetch into an alert."""
    if not result.error:
        return True
    summary["errors"] += 1
    account = result.account
    if result.error_code == "token":
        raise_alert(
            AlertKind.TOKEN_EXPIRED,
            f"'{account.label}' needs a Zerodha login (Accounts page). {result.error}",
            account=account,
            dedup_key=f"token:{account.id}",
        )
    else:
        raise_alert(
            AlertKind.MISMATCH,
            f"Could not fetch positions for '{account.label}': {result.error}",
            account=account,
            dedup_key=f"posfail:{account.id}",
            email=False,
        )
    return False
