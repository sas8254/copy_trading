"""Account actions used by the API: switch master, Zerodha login, instrument sync."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.db import transaction
from django.utils import timezone

from ..brokers import get_client
from ..brokers.base import BrokerError
from ..models import AccountRole, Alert, AlertKind, Broker, BrokerAccount, Instrument
from .alerts import broadcast

logger = logging.getLogger(__name__)

# F&O segments whose lot sizes matter (NSE and BSE derivatives).
SYNC_EXCHANGES = ("NFO", "BFO")


def reset_baseline(account: BrokerAccount) -> None:
    """Only copy master orders that complete from now on."""
    account.copy_orders_since = timezone.now()
    account.save(update_fields=["copy_orders_since"])


@transaction.atomic
def make_master(account: BrokerAccount) -> BrokerAccount:
    """Make `account` the master; the previous master becomes a copy account."""
    if account.is_master:
        return account
    BrokerAccount.objects.filter(role=AccountRole.MASTER).exclude(pk=account.pk).update(
        role=AccountRole.COPY
    )
    account.role = AccountRole.MASTER
    account.copy_orders_since = timezone.now()
    account.save(update_fields=["role", "copy_orders_since"])
    broadcast({"type": "accounts_changed"})
    return account


def kite_login_url(account: BrokerAccount) -> str:
    if not account.api_key or not account.api_secret:
        raise BrokerError("Add the API key and API secret first.", kind="terminal")
    # Zerodha sends redirect_params back to the redirect URL, so the callback
    # page knows which account just logged in.
    return get_client(account).login_url(urlencode({"account": account.pk}))


def complete_kite_login(account: BrokerAccount, request_token: str) -> BrokerAccount:
    """Exchange the request_token from Zerodha's redirect for an access token."""
    if not account.api_secret:
        raise BrokerError("API secret is missing.", kind="terminal")
    data = get_client(account).generate_session(request_token)

    user_id = data.get("user_id", "")
    if account.client_id and user_id and user_id.upper() != account.client_id.upper():
        raise BrokerError(
            f"You logged in as {user_id}, but this account is {account.client_id}. "
            "Log out of Zerodha (kite.zerodha.com) and try again.",
            kind="terminal",
        )

    account.access_token = data["access_token"]
    account.token_updated_at = timezone.now()
    fields = ["access_token", "token_updated_at"]
    if not account.client_id and user_id:
        account.client_id = user_id
        fields.append("client_id")
    if account.is_master:
        # Don't replay orders placed while we were logged out.
        account.copy_orders_since = timezone.now()
        fields.append("copy_orders_since")
    account.save(update_fields=fields)

    # The old "login needed" alerts for this account are now stale.
    Alert.objects.filter(
        account=account, kind=AlertKind.TOKEN_EXPIRED, resolved=False
    ).update(resolved=True)

    if account.is_master:
        from ..tasks import sync_instruments

        sync_instruments.delay(account.pk)
    broadcast({"type": "accounts_changed"})
    return account


def sync_instruments(account: BrokerAccount, exchanges=SYNC_EXCHANGES) -> int:
    """Upsert lot sizes for F&O instruments. Returns rows written."""
    client = get_client(account)
    total = 0
    for exchange in exchanges:
        rows = client.instruments(exchange)
        objs = [
            Instrument(
                broker=Broker.ZERODHA,
                exchange=r.get("exchange", ""),
                tradingsymbol=r.get("tradingsymbol", ""),
                instrument_token=r.get("instrument_token"),
                name=r.get("name", "") or "",
                lot_size=r.get("lot_size") or 1,
                tick_size=r.get("tick_size") or 0,
                instrument_type=r.get("instrument_type", "") or "",
                segment=r.get("segment", "") or "",
                expiry=r.get("expiry") or None,
                synced_at=timezone.now(),
            )
            for r in rows
        ]
        Instrument.objects.bulk_create(
            objs,
            batch_size=5000,
            update_conflicts=True,
            unique_fields=["broker", "exchange", "tradingsymbol"],
            update_fields=[
                "instrument_token", "name", "lot_size", "tick_size",
                "instrument_type", "segment", "expiry", "synced_at",
            ],
        )
        total += len(objs)
        logger.info("Synced %s %s instruments", len(objs), exchange)
    return total
