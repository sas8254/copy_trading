"""Broker adapters.

Each broker implements the BrokerClient interface in base.py. v1 ships Zerodha;
future brokers (Angel One, Tradebulls, Groww) plug in via get_client().
"""

from .base import BrokerClient, OrderRequest, Position
from .factory import get_client

__all__ = ["BrokerClient", "OrderRequest", "Position", "get_client"]
