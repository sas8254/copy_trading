"""Is the copy engine alive?

Every engine pass (each 2s poll) records a timestamp in Redis and, at most once
a minute, pings HEARTBEAT_URL. Two ways to notice a dead engine:

- /api/health/ returns 503 when the last pass is older than ENGINE_STALE_SECONDS
  (point an uptime monitor at it), and the Home page shows it.
- An external dead-man's switch (e.g. healthchecks.io) at HEARTBEAT_URL alerts
  you when the pings stop - this works even if the whole server is down.
"""

from __future__ import annotations

import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_LAST_RUN = "engine:last_run"
_LAST_PING = "engine:last_ping"


def beat() -> None:
    now = time.time()
    try:
        cache.set(_LAST_RUN, now, timeout=None)
        should_ping = settings.HEARTBEAT_URL and cache.add(_LAST_PING, now, timeout=60)
    except Exception:  # noqa: BLE001 - never let monitoring break copying
        logger.exception("heartbeat: cache unavailable")
        return
    if should_ping:
        try:
            requests.get(settings.HEARTBEAT_URL, timeout=5)
        except requests.RequestException as exc:
            logger.warning("heartbeat ping failed: %s", exc)


def seconds_since_last_run() -> float | None:
    try:
        last = cache.get(_LAST_RUN)
    except Exception:  # noqa: BLE001
        return None
    return None if last is None else max(0.0, time.time() - last)


def engine_alive() -> bool:
    age = seconds_since_last_run()
    return age is not None and age <= settings.ENGINE_STALE_SECONDS
