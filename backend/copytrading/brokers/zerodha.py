"""Zerodha (Kite Connect) adapter — REST only.

Imports the REST client directly (kiteconnect.connect.KiteConnect) and never the
Ticker, so it does not pull in autobahn. The live market feed is handled
separately (see PLAN.md / ticker step).
"""

from __future__ import annotations

from decimal import Decimal

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


def _classify(exc: Exception) -> str:
    msg = str(exc).lower()
    return "terminal" if any(h in msg for h in _TERMINAL_HINTS) else "transient"


class ZerodhaClient(BrokerClient):
    def __init__(self, api_key: str, api_secret: str, access_token: str | None = None):
        if not api_key:
            raise BrokerError("Zerodha api_key is missing", kind="terminal")
        self.api_secret = api_secret
        self.kite = KiteConnect(api_key=api_key)
        if access_token:
            self.kite.set_access_token(access_token)

    # --- Auth ---
    def login_url(self) -> str:
        return self.kite.login_url()

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
            raise BrokerError(f"Fetch positions failed: {exc}", kind=_classify(exc)) from exc
        result: list[Position] = []
        for p in net:
            result.append(
                Position(
                    tradingsymbol=p.get("tradingsymbol", ""),
                    exchange=p.get("exchange", ""),
                    net_quantity=int(p.get("quantity", 0)),
                    average_price=Decimal(str(p.get("average_price", 0) or 0)),
                    instrument_token=p.get("instrument_token"),
                )
            )
        return result

    def orders(self) -> list[dict]:
        try:
            return self.kite.orders()
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"Fetch orders failed: {exc}", kind=_classify(exc)) from exc

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
            raise BrokerError(
                f"Place order failed: {exc}", kind=_classify(exc)
            ) from exc
