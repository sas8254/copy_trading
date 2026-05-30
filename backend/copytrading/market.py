"""Market-hours guard (NSE, IST).

The 2s reconciliation loop and order dispatch only make sense while the market
is open. Set COPYTRADING_FORCE_MARKET_OPEN=True in the env to bypass (testing).
"""

from __future__ import annotations

from datetime import time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

IST = ZoneInfo("Asia/Kolkata")
_OPEN = time(9, 15)
_CLOSE = time(15, 30)


def is_market_open(now=None) -> bool:
    if getattr(settings, "COPYTRADING_FORCE_MARKET_OPEN", False):
        return True
    now = (now or timezone.now()).astimezone(IST)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    return _OPEN <= now.time() <= _CLOSE
