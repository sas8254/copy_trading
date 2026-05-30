"""Broker-agnostic interface.

All broker adapters implement BrokerClient so the rest of the app (dispatcher,
reconciliation) never imports a specific broker SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class OrderRequest:
    """A broker-neutral order to place on a copy (or master) account."""

    tradingsymbol: str
    exchange: str  # NSE / NFO / BSE / MCX / CDS
    transaction_type: str  # BUY / SELL
    quantity: int
    product: str = "NRML"  # MIS / NRML / CNC
    order_type: str = "MARKET"  # MARKET / LIMIT / SL / SL-M
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    variety: str = "regular"
    tag: Optional[str] = None


@dataclass
class Position:
    """A net open position on an account."""

    tradingsymbol: str
    exchange: str
    net_quantity: int
    average_price: Optional[Decimal] = None
    instrument_token: Optional[int] = None


class BrokerError(Exception):
    """Base error. `kind` distinguishes retryable vs terminal failures."""

    def __init__(self, message: str, *, kind: str = "transient", code: str = ""):
        super().__init__(message)
        self.kind = kind  # "transient" | "terminal"
        self.code = code


class BrokerClient(ABC):
    """Interface every broker adapter must implement."""

    # --- Auth ---
    @abstractmethod
    def login_url(self) -> str:
        """URL the user visits to authorise and obtain a request token."""

    @abstractmethod
    def generate_session(self, request_token: str) -> dict:
        """Exchange a request token for an access token. Returns provider data
        including at least {"access_token": ...}."""

    # --- Reads ---
    @abstractmethod
    def positions(self) -> list[Position]:
        """Current net open positions."""

    @abstractmethod
    def orders(self) -> list[dict]:
        """Today's orders (raw broker dicts)."""

    # --- Writes ---
    @abstractmethod
    def place_order(self, order: OrderRequest) -> str:
        """Place an order; return the broker order id."""
