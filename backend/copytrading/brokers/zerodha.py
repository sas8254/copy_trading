"""Zerodha (Kite Connect) adapter — REST only.

Imports the REST client directly (kiteconnect.connect.KiteConnect) and never the
Ticker, so it does not pull in autobahn. The live market feed is handled
separately (see PLAN.md / ticker step).
"""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote

from kiteconnect import exceptions as kex
from kiteconnect.connect import KiteConnect

from .base import BrokerClient, BrokerError, OrderRequest, Position

# Zerodha order-status / error signatures that will never succeed on retry.
# Anything not matching these is treated as transient (network, 5xx, throttle).
_TERMINAL_HINTS = (
    "insufficient",  # margin
    "margin",
    "rms",
    "blocked",
    "freeze",
    "not allowed",
    "circuit",
    "invalid",
)
# Kite exception types that will never succeed on retry.
_TERMINAL_TYPES = (
    kex.TokenException,
    kex.PermissionException,
    kex.InputException,
    kex.OrderException,
)


def _classify(exc: Exception) -> str:
    if isinstance(exc, _TERMINAL_TYPES):
        return "terminal"
    msg = str(exc).lower()
    return "terminal" if any(h in msg for h in _TERMINAL_HINTS) else "transient"


def _error(prefix: str, exc: Exception) -> BrokerError:
    """Wrap a Kite exception; token errors get code="token" so callers can
    tell the user to log in again."""
    code = "token" if isinstance(exc, kex.TokenException) else ""
    return BrokerError(f"{prefix}: {exc}", kind=_classify(exc), code=code)


class ZerodhaClient(BrokerClient):
    def __init__(self, api_key: str, api_secret: str, access_token: str | None = None):
        if not api_key:
            raise BrokerError("Zerodha api_key is missing", kind="terminal")
        self.api_secret = api_secret
        self.kite = KiteConnect(api_key=api_key)
        if access_token:
            self.kite.set_access_token(access_token)

    # --- Auth ---
    def login_url(self, redirect_params: str = "") -> str:
        url = self.kite.login_url()
        if redirect_params:
            url += "&redirect_params=" + quote(redirect_params, safe="")
        return url

    def generate_session(self, request_token: str) -> dict:
        try:
            data = self.kite.generate_session(request_token, api_secret=self.api_secret)
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"Kite login failed: {exc}", kind="terminal") from exc
        self.kite.set_access_token(data["access_token"])
        return data

    # --- Reads ---
    def positions(self) -> list[Position]:
        try:
            net = self.kite.positions().get("net", [])
        except Exception as exc:  # noqa: BLE001
            raise _error("Fetch positions failed", exc) from exc
        result: list[Position] = []
        for p in net:
            result.append(
                Position(
                    tradingsymbol=p.get("tradingsymbol", ""),
                    exchange=p.get("exchange", ""),
                    net_quantity=int(p.get("quantity", 0)),
                    average_price=Decimal(str(p.get("average_price", 0) or 0)),
                    instrument_token=p.get("instrument_token"),
                    last_price=Decimal(str(p.get("last_price", 0) or 0)),
                    pnl=Decimal(str(p.get("pnl", 0) or 0)),
                    product=p.get("product", ""),
                )
            )
        return result

    def orders(self) -> list[dict]:
        try:
            return self.kite.orders()
        except Exception as exc:  # noqa: BLE001
            raise _error("Fetch orders failed", exc) from exc

    def instruments(self, exchange: str) -> list[dict]:
        try:
            return self.kite.instruments(exchange)
        except Exception as exc:  # noqa: BLE001
            raise _error("Fetch instruments failed", exc) from exc

    # --- Writes ---
    def place_order(self, order: OrderRequest) -> str:
        try:
            return self.kite.place_order(
                variety=order.variety,
                exchange=order.exchange,
                tradingsymbol=order.tradingsymbol,
                transaction_type=order.transaction_type,
                quantity=order.quantity,
                product=order.product,
                order_type=order.order_type,
                price=order.price,
                trigger_price=order.trigger_price,
                tag=order.tag,
            )
        except Exception as exc:  # noqa: BLE001
            raise _error("Place order failed", exc) from exc

    def modify_order(self, order_id, *, variety, quantity, order_type, price, trigger_price):
        try:
            self.kite.modify_order(
                variety=variety,
                order_id=order_id,
                quantity=quantity,
                order_type=order_type,
                price=price,
                trigger_price=trigger_price,
            )
        except Exception as exc:  # noqa: BLE001
            raise _error("Modify order failed", exc) from exc

    def cancel_order(self, order_id, *, variety):
        try:
            self.kite.cancel_order(variety=variety, order_id=order_id)
        except Exception as exc:  # noqa: BLE001
            raise _error("Cancel order failed", exc) from exc
