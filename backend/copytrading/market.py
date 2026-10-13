"""Market-hours guard (NSE, IST) and Zerodha token-expiry helper.

The 2s reconciliation loop and order dispatch only make sense while the market
is open. Set COPYTRADING_FORCE_MARKET_OPEN=True in the env to bypass (testing).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

IST = ZoneInfo("Asia/Kolkata")
_OPEN = time(9, 15)
_CLOSE = time(15, 30)
_TOKEN_RESET = time(6, 0)


def is_market_open(now=None) -> bool:
    if getattr(settings, "COPYTRADING_FORCE_MARKET_OPEN", False):
        return True
    now = (now or timezone.now()).astimezone(IST)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    return _OPEN <= now.time() <= _CLOSE


def last_token_reset(now=None) -> datetime:
    """Most recent 6:00 AM IST, when Zerodha invalidates all access tokens."""
    now = (now or timezone.now()).astimezone(IST)
    reset = datetime.combine(now.date(), _TOKEN_RESET, tzinfo=IST)
    if now < reset:
        reset -= timedelta(days=1)
    return reset
