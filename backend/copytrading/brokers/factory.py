"""Build a BrokerClient from a BrokerAccount row."""

from __future__ import annotations

from ..models import Broker, BrokerAccount
from .base import BrokerClient, BrokerError


def get_client(account: BrokerAccount) -> BrokerClient:
    if account.broker == Broker.ZERODHA:
        from .zerodha import ZerodhaClient

        return ZerodhaClient(
            api_key=account.api_key,
            api_secret=account.api_secret,
            access_token=account.access_token or None,
        )
    raise BrokerError(
        f"No adapter for broker '{account.broker}'", kind="terminal"
    )
